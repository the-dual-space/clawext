"""Entry-point discovery of installed extensions (group ``clawext.extensions``)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from .errors import ExtensionError
from .extension import Extension, check_framework_range

GROUP = "clawext.extensions"


@dataclass
class Discovered:
    """The outcome of loading one entry point.

    Attributes:
        entry: Entry-point name.
        dist: Distribution (package) that provides it, when known.
        version: Distribution version, when known.
        extension: The loaded extension, or ``None`` when loading failed.
        error: Why loading failed, or ``None`` on success.
    """

    entry: str
    dist: str | None
    version: str | None
    extension: Extension | None
    error: str | None = None


def load_entry_point(ep: EntryPoint) -> Extension:
    """Load an entry point and return its :class:`Extension`.

    The target may be an ``Extension`` or a zero-argument callable returning one.

    Args:
        ep: Entry point to load.

    Returns:
        The extension.

    Raises:
        ExtensionError: Loading fails or the target is not an extension.
    """
    try:
        target: Any = ep.load()
        if isinstance(target, Extension):
            ext = target
        elif callable(target):
            ext = target()
        else:
            ext = None
    except Exception as exc:
        raise ExtensionError(f"cannot load '{ep.name}' ({ep.value}): {exc}") from exc
    if not isinstance(ext, Extension):
        raise ExtensionError(f"entry point '{ep.name}' did not provide an Extension")
    check_framework_range(ext.requires_framework)
    return ext


def discover(
    eps: Iterable[EntryPoint] | None = None,
    loader: Callable[[EntryPoint], Extension] = load_entry_point,
) -> list[Discovered]:
    """Load every installed extension; failures are reported, not raised.

    Args:
        eps: Entry points to load; defaults to everything in the ``clawext.extensions`` group.
        loader: Function that loads one entry point.

    Returns:
        One result per entry point, sorted by entry name. Duplicate names are marked as errors
        (the first one wins).
    """
    found: list[Discovered] = []
    seen: set[str] = set()
    source = entry_points(group=GROUP) if eps is None else eps
    for ep in sorted(source, key=lambda e: e.name):
        dist = getattr(ep, "dist", None)
        name = dist.name if dist is not None else None
        version = dist.version if dist is not None else None
        if ep.name in seen:
            found.append(
                Discovered(ep.name, name, version, None, f"duplicate extension name '{ep.name}'")
            )
            continue
        seen.add(ep.name)
        try:
            found.append(Discovered(ep.name, name, version, loader(ep)))
        except ExtensionError as exc:
            found.append(Discovered(ep.name, name, version, None, str(exc)))
    return found
