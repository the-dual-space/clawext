"""Click adapter: turns an Extension's typed command functions into a CLI."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import click

from .context import Context, redact
from .errors import EXIT_FAILURE, EXIT_OK, ClawextError, UsageError
from .extension import Command, Extension
from .params import ParamSpec, scalar_click_type
from .render import render, render_error


def _click_param(spec: ParamSpec) -> click.Parameter:
    """Build the Click parameter for one ParamSpec."""
    ctype = scalar_click_type(spec)
    if spec.kind == "argument":
        return click.Argument(
            [spec.name],
            type=ctype,
            nargs=-1 if spec.multiple else 1,
            required=(spec.required and not spec.multiple) or (spec.multiple and spec.required),
            default=None if spec.required else spec.default,
            metavar=spec.metavar,
        )
    decls = [*spec.shorts]
    flag = spec.long or f"--{spec.name.replace('_', '-')}"
    if spec.is_flag:
        decls.insert(0, f"{flag}/--no-{flag[2:]}" if spec.negatable else flag)
        return click.Option(
            [*decls, spec.name],
            is_flag=True,
            default=bool(spec.default),
            show_default=spec.negatable,
            help=spec.help or None,
            hidden=spec.hidden,
        )
    default: Any = spec.default
    if spec.multiple:
        default = tuple(default) if default is not None else ()
    return click.Option(
        [flag, *decls, spec.name],
        type=ctype,
        default=default,
        multiple=spec.multiple,
        required=spec.required,
        show_default=default not in (None, ()),
        help=spec.help or None,
        metavar=spec.metavar,
        hidden=spec.hidden,
    )


def _signature_params(cmd: Command) -> list[click.Parameter]:
    return [_click_param(spec) for spec in cmd.params]


JSON_META = "clawext.json"
"""Key in ``click.Context.meta`` (shared by the whole context tree) holding the JSON-mode flag."""


def _json_option() -> click.Option:
    return click.Option(["--json", "json_flag"], is_flag=True, default=False, help="Emit JSON.")


def _write_audit(ctx: Context, command: str, status: str, code: int) -> None:
    """Append one audit line; failures to write are ignored."""
    line = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "extension": ctx.extension,
        "command": command,
        "status": status,
        "exit": code,
    }
    try:
        path = ctx.home / "audit.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError:
        return


def run_command(ext: Extension, cmd: Command, kwargs: dict[str, Any], *, json_mode: bool) -> int:
    """Execute a command and print its result or error.

    Args:
        ext: Extension being run.
        cmd: Command to run.
        kwargs: Parsed arguments for the function (without the context).
        json_mode: Whether to emit JSON.

    Returns:
        The process exit code.
    """
    ctx: Context | None = None
    secrets: list[str] = []
    try:
        ext.check_host()
        ctx = ext.build_context(json_mode=json_mode)
        own_yes = any(p.name == "yes" for p in cmd.params)
        if cmd.destructive:
            confirmed = kwargs.get("yes", False) if own_yes else kwargs.pop("yes", False)
            if not confirmed:
                raise UsageError(
                    f"'{cmd.name}' is destructive", hint="re-run with --yes to confirm"
                )
        result = cmd.func(ctx, **kwargs) if cmd.wants_ctx else cmd.func(**kwargs)
        secrets = ctx.secrets.resolved
        for line in ctx.messages:
            click.echo(line, err=True)
        out = render(result, json_mode=json_mode)
        if out:
            click.echo(redact(out, secrets))
        code = cmd.exit_for(result) if cmd.exit_for else EXIT_OK
        _write_audit(ctx, cmd.name, "ok" if code == EXIT_OK else "failed", code)
        return code
    except ClawextError as exc:
        body = exc.to_dict()
        if ctx is not None:
            secrets = ctx.secrets.resolved
            body["message"] = redact(str(body["message"]), secrets)
            _write_audit(ctx, cmd.name, str(body["type"]), exc.exit_code)
        click.echo(render_error(body, json_mode=json_mode), err=not json_mode)
        return exc.exit_code
    except Exception as exc:  # last resort so agents always get a clean envelope
        if ctx is not None:
            secrets = ctx.secrets.resolved
            _write_audit(ctx, cmd.name, "unexpected", EXIT_FAILURE)
        message = redact(f"{type(exc).__name__}: {exc}", secrets)
        body = {"code": EXIT_FAILURE, "type": "unexpected", "message": message}
        click.echo(render_error(body, json_mode=json_mode), err=not json_mode)
        return EXIT_FAILURE


def _make_callback(ext: Extension, cmd: Command) -> Callable[..., None]:
    def callback(json_flag: bool = False, **kwargs: Any) -> None:
        click_ctx = click.get_current_context()
        code = run_command(
            ext, cmd, kwargs, json_mode=json_flag or bool(click_ctx.meta.get(JSON_META))
        )
        if code:
            click_ctx.exit(code)

    return callback


def to_click(ext: Extension, *, group: click.Group | None = None) -> click.Group:
    """Build (or extend) a Click group for an extension.

    Args:
        ext: Extension whose commands become subcommands.
        group: Existing group to extend; a new one is created when omitted.

    Returns:
        The Click group.
    """
    target = group if group is not None else _new_group(ext)
    for cmd in ext.commands.values():
        add_command(ext, target, cmd)
    return target


def _new_group(ext: Extension) -> click.Group:
    """Create the root Click group of an extension (``--json`` before the subcommand)."""

    @click.group(
        name=ext.name, help=ext.about, context_settings={"help_option_names": ["-h", "--help"]}
    )
    @click.option("--json", "json_flag", is_flag=True, default=False, help="Emit JSON.")
    @click.pass_context
    def root(click_ctx: click.Context, json_flag: bool) -> None:
        click_ctx.meta[JSON_META] = json_flag or bool(click_ctx.meta.get(JSON_META))

    return root


def add_command(ext: Extension, group: click.Group, cmd: Command) -> None:
    """Attach one command to a Click group.

    Args:
        ext: Extension the command belongs to.
        group: Group (or subgroup) to extend.
        cmd: Command to attach.
    """
    params = _signature_params(cmd)
    if cmd.destructive and not any(p.name == "yes" for p in cmd.params):
        params.append(
            click.Option(
                ["--yes"], is_flag=True, default=False, help="Confirm a destructive action."
            )
        )
    params.append(_json_option())
    group.add_command(
        click.Command(
            cmd.name,
            callback=_make_callback(ext, cmd),
            params=params,
            help=cmd.help or None,
            hidden=cmd.hidden,
        )
    )


def build_group(
    ext: Extension,
    *,
    customize: Callable[[click.Group], None] | None = None,
    version: str | None = None,
) -> click.Group:
    """Build the complete Click group of an extension: commands, free commands, customizations.

    Args:
        ext: Extension to serve.
        customize: Called with the group before the free commands are added; use it to mount
            nested Click groups or other hand-written commands.
        version: When given, ``--version`` prints it.

    Returns:
        The ready-to-run group.
    """
    from .builtin import add_builtin_commands

    group = to_click(ext)
    if customize is not None:
        customize(group)
    add_builtin_commands(ext, group)
    if version is not None:
        click.version_option(version, "--version", prog_name=ext.name)(group)
    return group


def main_for(
    ext: Extension,
    *,
    customize: Callable[[click.Group], None] | None = None,
    prog_name: str | None = None,
    version: str | None = None,
) -> Callable[[], None]:
    """Return a ``main()`` entry point for an extension, suitable for ``[project.scripts]``.

    Args:
        ext: Extension to serve.
        customize: Hook to mount extra Click commands (see :func:`build_group`).
        prog_name: Program name shown in help (default: the extension name).
        version: When given, ``--version`` prints it.

    Returns:
        A zero-argument function that runs the CLI and exits with its code.
    """

    def main() -> None:
        group = build_group(ext, customize=customize, version=version)
        group(prog_name=prog_name or ext.name)
        sys.exit(EXIT_OK)

    return main
