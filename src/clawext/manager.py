"""Extension manager: a thin wrapper over uv/pip plus a declarative ``extensions.yaml``."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

import yaml

from .config import read_yaml_mapping
from .discovery import GROUP
from .errors import ExtensionError

Runner = Callable[[Sequence[str]], int]
"""Runs a command line and returns its exit code."""


def run_subprocess(argv: Sequence[str]) -> int:
    """Run a command, streaming its output.

    Args:
        argv: Command and arguments.

    Returns:
        The process exit code.
    """
    return subprocess.run(list(argv), check=False).returncode


def installer_prefix() -> list[str]:
    """Return the command prefix used to install into the running interpreter.

    Returns:
        ``uv pip ... --python <exe>`` when uv exists, otherwise ``python -m pip``.
    """
    if shutil.which("uv"):
        return ["uv", "pip", "--python", sys.executable]
    return [sys.executable, "-m", "pip"]


def installed_extensions() -> list[dict[str, Any]]:
    """List installed distributions that provide ``clawext.extensions`` entry points.

    Returns:
        One mapping per distribution with ``dist``, ``version`` and ``entries``.
    """
    rows: dict[str, dict[str, Any]] = {}
    for dist in distributions():
        names = [ep.name for ep in dist.entry_points if ep.group == GROUP]
        if names:
            rows[dist.metadata["Name"]] = {
                "dist": dist.metadata["Name"],
                "version": dist.version,
                "entries": sorted(names),
            }
    return sorted(rows.values(), key=lambda r: str(r["dist"]))


def install(source: str, *, editable: bool | None = None, runner: Runner = run_subprocess) -> None:
    """Install an extension from a name, git URL or local path.

    Args:
        source: PyPI name, ``git+https://...`` URL, or a local directory.
        editable: Install in editable mode; defaults to ``True`` for local directories.
        runner: Function that executes the install command.

    Raises:
        ExtensionError: The installer exits non-zero.
    """
    is_dir = Path(source).expanduser().is_dir()
    use_editable = is_dir if editable is None else editable
    argv = [*installer_prefix(), "install"]
    if use_editable:
        argv.append("-e")
    argv.append(str(Path(source).expanduser()) if is_dir else source)
    if runner(argv) != 0:
        raise ExtensionError(f"install failed for '{source}'")


def update(dist: str, *, runner: Runner = run_subprocess) -> None:
    """Upgrade an installed extension distribution.

    Args:
        dist: Distribution name.
        runner: Function that executes the command.

    Raises:
        ExtensionError: The installer exits non-zero.
    """
    if runner([*installer_prefix(), "install", "--upgrade", dist]) != 0:
        raise ExtensionError(f"update failed for '{dist}'")


def remove(dist: str, *, runner: Runner = run_subprocess) -> None:
    """Uninstall an extension distribution.

    Args:
        dist: Distribution name.
        runner: Function that executes the command.

    Raises:
        ExtensionError: The installer exits non-zero.
    """
    argv = [*installer_prefix(), "uninstall"]
    if argv[0] == sys.executable:
        argv.append("-y")
    argv.append(dist)
    if runner(argv) != 0:
        raise ExtensionError(f"remove failed for '{dist}'")


def read_manifest(path: Path) -> list[dict[str, str]]:
    """Read ``extensions.yaml``.

    The file holds ``extensions:`` as a list of ``{name, source}`` entries, or plain source strings.

    Args:
        path: Manifest file.

    Returns:
        Normalised entries with ``name`` and ``source``.

    Raises:
        ExtensionError: The file is missing or malformed.
    """
    if not path.is_file():
        raise ExtensionError(f"manifest not found: {path}")
    data = read_yaml_mapping(path)
    raw = data.get("extensions")
    if not isinstance(raw, list):
        raise ExtensionError(f"{path}: expected an 'extensions:' list")
    entries: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            entries.append({"name": item, "source": item})
        elif isinstance(item, dict) and "name" in item:
            entries.append(
                {"name": str(item["name"]), "source": str(item.get("source", item["name"]))}
            )
        else:
            raise ExtensionError(f"{path}: invalid entry {item!r}")
    return entries


def write_manifest(path: Path, entries: list[dict[str, str]]) -> None:
    """Write ``extensions.yaml``.

    Args:
        path: Manifest file.
        entries: Entries with ``name`` and ``source``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"extensions": entries}, sort_keys=False))


def sync(
    manifest: Path,
    *,
    installed: set[str] | None = None,
    runner: Runner = run_subprocess,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Install every manifest entry that is not installed yet.

    Args:
        manifest: Path of ``extensions.yaml``.
        installed: Names of installed distributions; detected when omitted.
        runner: Function that executes install commands.
        dry_run: Only report what would be installed.

    Returns:
        ``{"installed": [...], "present": [...]}`` with extension names.
    """
    have = (
        {n.lower().replace("_", "-") for n in installed}
        if installed is not None
        else {str(r["dist"]).lower().replace("_", "-") for r in installed_extensions()}
    )
    result: dict[str, list[str]] = {"installed": [], "present": []}
    for entry in read_manifest(manifest):
        if entry["name"].lower().replace("_", "-") in have:
            result["present"].append(entry["name"])
            continue
        if not dry_run:
            install(entry["source"], runner=runner)
        result["installed"].append(entry["name"])
    return result
