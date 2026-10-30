"""The ``clawext`` hub command line and the factory for plugin hubs."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import click

from . import __version__, manager
from .adapter import JSON_META, to_click
from .builtin import add_builtin_commands
from .discovery import GROUP, Discovered, discover, load_entry_point
from .errors import EXIT_FAILURE, ClawextError, ExtensionError
from .extension import Extension
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


class HubGroup(click.Group):
    """A group that mounts installed extensions lazily, with an optional fallback.

    Extensions are looked up by entry-point name and loaded only when their subcommand is used,
    so ``hub remote ...`` never imports heavy sibling extensions. Listing (``--help``) loads all.

    Attributes:
        plugin: Restrict the hub to extensions of this plugin (``None`` shows all).
        fallback: Called with an unknown subcommand name; may return a command (for example a
            passthrough to a legacy executable).
        extra_names: Called to list names that only the fallback can serve.
    """

    def __init__(
        self,
        *args: Any,
        plugin: Plugin | None = None,
        discovered: list[Discovered] | None = None,
        fallback: Callable[[str], click.Command | None] | None = None,
        extra_names: Callable[[], Iterable[str]] | None = None,
        **kwargs: Any,
    ) -> None:
        """Create the hub group.

        Args:
            *args: Positional arguments for :class:`click.Group`.
            plugin: Restrict the hub to extensions of this plugin.
            discovered: Pre-loaded discovery results; entry points are not scanned when given.
            fallback: Resolver for names no extension provides.
            extra_names: Names the fallback can serve (shown in listings).
            **kwargs: Keyword arguments for :class:`click.Group`.
        """
        super().__init__(*args, **kwargs)
        self.plugin = plugin
        self.fallback = fallback
        self.extra_names = extra_names
        self._loaded: dict[str, click.Group | None] = {}
        self._fixed = discovered
        if discovered is not None:
            for item in discovered:
                if item.extension is not None:
                    self._loaded[item.entry] = self._mount(item.extension)

    def _mount(self, ext: Extension) -> click.Group | None:
        """Build the Click group of an extension unless it belongs to another plugin."""
        if self.plugin is not None and ext.plugin.name != self.plugin.name:
            return None
        group = to_click(ext)
        add_builtin_commands(ext, group)
        return group

    def _names(self) -> list[str]:
        if self._fixed is not None:
            return [d.entry for d in self._fixed if d.extension is not None]
        return sorted(ep.name for ep in entry_points(group=GROUP))

    def _extension_group(self, name: str) -> click.Group | None:
        if name not in self._loaded:
            self._loaded[name] = None
            if self._fixed is None:
                for ep in entry_points(group=GROUP, name=name):
                    try:
                        self._loaded[name] = self._mount(load_entry_point(ep))
                    except ExtensionError as exc:
                        raise click.ClickException(str(exc)) from exc
                    break
        return self._loaded[name]

    def get_command(self, ctx: click.Context, name: str) -> click.Command | None:
        """Return a built-in command, a mounted extension, or the fallback's command."""
        found = super().get_command(ctx, name)
        if found is not None:
            return found
        group = self._extension_group(name)
        if group is not None:
            return group
        return self.fallback(name) if self.fallback else None

    def list_commands(self, ctx: click.Context) -> list[str]:
        """List built-in commands, extensions (of this plugin) and fallback names."""
        names = set(super().list_commands(ctx))
        for name in self._names():
            if self._extension_group(name) is not None:
                names.add(name)
        if self.extra_names:
            names.update(self.extra_names())
        return sorted(names)


def build_hub(
    name: str = "clawext",
    plugin: Plugin | None = None,
    discovered: list[Discovered] | None = None,
    *,
    help_text: str | None = None,
    fallback: Callable[[str], click.Command | None] | None = None,
    extra_names: Callable[[], Iterable[str]] | None = None,
) -> HubGroup:
    """Build a hub group: ``ext`` management plus one lazily loaded subgroup per extension.

    ``hub --json <ext> <cmd>`` and ``hub <ext> --json <cmd>`` are equivalent.

    Args:
        name: Hub command name.
        plugin: Restrict the hub to extensions of this plugin; ``None`` shows all.
        discovered: Pre-loaded discovery results (entry points are scanned lazily when omitted).
        help_text: Help string for the hub.
        fallback: Resolver for subcommands no extension provides (for example legacy binaries).
        extra_names: Names the fallback can serve, shown in listings.

    Returns:
        The hub group.
    """
    hub = HubGroup(
        name,
        help=help_text or f"{name}: agent-callable CLI extensions.",
        context_settings={"help_option_names": ["-h", "--help"]},
        plugin=plugin,
        discovered=discovered,
        fallback=fallback,
        extra_names=extra_names,
        params=[
            click.Option(["--json", "json_flag"], is_flag=True, default=False, help="Emit JSON."),
            click.Option(
                ["--version"],
                is_flag=True,
                expose_value=False,
                is_eager=True,
                callback=_print_version,
                help="Show the clawext version.",
            ),
        ],
        callback=_hub_root,
    )
    hub.add_command(_ext_group(plugin or DEFAULT_PLUGIN))
    return hub


def _print_version(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Eager ``--version`` callback."""
    if value and not ctx.resilient_parsing:
        click.echo(f"clawext {__version__}")
        ctx.exit()


@click.pass_context
def _hub_root(ctx: click.Context, json_flag: bool) -> None:
    """Record the hub-level ``--json`` for every extension below."""
    ctx.meta[JSON_META] = json_flag


def main() -> None:
    """Run the hub CLI (entry point of the ``clawext`` script)."""
    build_hub()()
