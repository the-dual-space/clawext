"""The ``clawext`` hub command line and the factory for plugin hubs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from . import __version__, manager
from .adapter import to_click
from .builtin import add_builtin_commands
from .discovery import Discovered, discover
from .errors import EXIT_FAILURE, ClawextError
from .plugin import DEFAULT_PLUGIN, Plugin
from .render import render, render_error


def _emit(data: Any, json_flag: bool) -> None:
    """Print a result in the requested format."""
    click.echo(render(data, json_mode=json_flag))


def _json_flag(func: Any) -> Any:
    return click.option("--json", "json_flag", is_flag=True, default=False, help="Emit JSON.")(func)


def _guard(json_flag: bool, action: Any) -> None:
    """Run ``action`` and convert expected errors into exit codes."""
    try:
        action()
    except ClawextError as exc:
        click.echo(render_error(exc.to_dict(), json_mode=json_flag), err=not json_flag)
        sys.exit(exc.exit_code)


def _ext_group(plugin: Plugin) -> click.Group:
    """Build the ``ext`` management group for a hub."""

    @click.group("ext", help="Install, list and check extensions.")
    def ext() -> None:
        """Extension manager."""

    @ext.command("list")
    @_json_flag
    def list_cmd(json_flag: bool) -> None:
        """List installed extensions with their health."""
        found = {d.entry: d for d in discover()}
        rows = []
        for row in manager.installed_extensions():
            health = [found[e].error or "ok" for e in row["entries"] if e in found]
            rows.append(
                {**row, "health": "ok" if all(h == "ok" for h in health) else "; ".join(health)}
            )
        _emit(rows, json_flag)

    @ext.command("install")
    @click.argument("source")
    @click.option(
        "--editable/--no-editable",
        default=None,
        help="Editable install (default: for local paths).",
    )
    @_json_flag
    def install_cmd(source: str, editable: bool | None, json_flag: bool) -> None:
        """Install an extension from a PyPI name, git URL, or local path."""
        _guard(json_flag, lambda: manager.install(source, editable=editable))
        _emit({"installed": source}, json_flag)

    @ext.command("update")
    @click.argument("dist")
    @_json_flag
    def update_cmd(dist: str, json_flag: bool) -> None:
        """Upgrade an installed extension."""
        _guard(json_flag, lambda: manager.update(dist))
        _emit({"updated": dist}, json_flag)

    @ext.command("remove")
    @click.argument("dist")
    @click.option("--yes", is_flag=True, default=False, help="Confirm removal.")
    @_json_flag
    def remove_cmd(dist: str, yes: bool, json_flag: bool) -> None:
        """Uninstall an extension (needs --yes)."""
        if not yes:
            click.echo("error: removal needs --yes", err=True)
            sys.exit(2)
        _guard(json_flag, lambda: manager.remove(dist))
        _emit({"removed": dist}, json_flag)

    @ext.command("sync")
    @click.option(
        "--manifest",
        type=click.Path(path_type=Path),
        default=None,
        help="extensions.yaml to apply.",
    )
    @click.option(
        "--dry-run", is_flag=True, default=False, help="Only report what would be installed."
    )
    @_json_flag
    def sync_cmd(manifest: Path | None, dry_run: bool, json_flag: bool) -> None:
        """Install everything listed in extensions.yaml that is missing."""
        path = manifest or plugin.home_dir() / "extensions.yaml"
        outcome: dict[str, list[str]] = {}

        def run() -> None:
            outcome.update(manager.sync(path, dry_run=dry_run))

        _guard(json_flag, run)
        _emit(outcome, json_flag)

    @ext.command("doctor")
    @_json_flag
    def doctor_cmd(json_flag: bool) -> None:
        """Load every installed extension and report the ones that fail."""
        results = discover()
        report = [
            {
                "entry": d.entry,
                "dist": d.dist,
                "version": d.version,
                "status": "ok" if d.extension else d.error,
            }
            for d in results
        ]
        _emit({"ok": all(d.extension for d in results), "extensions": report}, json_flag)
        if not all(d.extension for d in results):
            sys.exit(EXIT_FAILURE)

    return ext


def build_hub(
    name: str = "clawext",
    plugin: Plugin | None = None,
    discovered: list[Discovered] | None = None,
    *,
    help_text: str | None = None,
) -> click.Group:
    """Build a hub group: ``ext`` management plus one subgroup per extension.

    Args:
        name: Hub command name.
        plugin: Restrict the hub to extensions of this plugin; ``None`` shows all.
        discovered: Pre-loaded discovery results (loaded from entry points when omitted).
        help_text: Help string for the hub.

    Returns:
        The Click group.
    """
    owner = plugin or DEFAULT_PLUGIN
    results = discover() if discovered is None else discovered

    @click.group(
        name,
        help=help_text or f"{name}: agent-callable CLI extensions.",
        context_settings={"help_option_names": ["-h", "--help"]},
    )
    @click.version_option(__version__, prog_name="clawext")
    def hub() -> None:
        """Root group of the hub command line."""

    hub.add_command(_ext_group(owner))
    for item in results:
        if item.extension is None:
            continue
        if plugin is not None and item.extension.plugin.name != plugin.name:
            continue
        group = to_click(item.extension)
        add_builtin_commands(item.extension, group)
        hub.add_command(group, name=item.extension.name)
    return hub


def main() -> None:
    """Run the hub CLI (entry point of the ``clawext`` script)."""
    build_hub()()
