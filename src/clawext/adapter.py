"""Click adapter: turns an Extension's typed command functions into a CLI."""

from __future__ import annotations

import inspect
import json
import sys
import types
import typing
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from .context import Context, redact
from .errors import EXIT_FAILURE, EXIT_OK, ClawextError, UsageError
from .extension import Command, Extension
from .render import render, render_error

_SCALARS: dict[Any, Any] = {
    str: click.STRING,
    int: click.INT,
    float: click.FLOAT,
    Path: click.Path(path_type=Path),
}


def _unwrap_optional(hint: Any) -> Any:
    """Return ``X`` for ``X | None`` / ``Optional[X]``, else the hint itself."""
    origin = typing.get_origin(hint)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return hint


def _click_type(hint: Any) -> tuple[Any, bool]:
    """Map an annotation to ``(click type, is_list)``."""
    hint = _unwrap_optional(hint)
    if typing.get_origin(hint) in (list, tuple):
        inner = typing.get_args(hint)
        return _SCALARS.get(inner[0] if inner else str, click.STRING), True
    return _SCALARS.get(hint, click.STRING), False


def _param(p: inspect.Parameter, hint: Any) -> click.Parameter:
    """Build the Click parameter for one function parameter."""
    flag = p.name.replace("_", "-")
    base = _unwrap_optional(hint)
    if base is bool:
        flag_default = p.default is True
        return click.Option([f"--{flag}/--no-{flag}"], default=flag_default, show_default=True)
    ctype, is_list = _click_type(hint)
    if p.default is inspect.Parameter.empty:
        return click.Argument([p.name], type=ctype, nargs=-1 if is_list else 1, required=True)
    default: Any = p.default
    return click.Option(
        [f"--{flag}"],
        type=ctype,
        default=tuple(default) if is_list and default is not None else default,
        multiple=is_list,
        show_default=default is not None,
    )


def _signature_params(cmd: Command) -> list[click.Parameter]:
    sig = inspect.signature(cmd.func)
    hints = typing.get_type_hints(cmd.func)
    params: list[click.Parameter] = []
    for p in list(sig.parameters.values())[1:]:
        params.append(_param(p, hints.get(p.name, str)))
    return params


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
        if cmd.destructive and not kwargs.pop("yes", False):
            raise UsageError(f"'{cmd.name}' is destructive", hint="re-run with --yes to confirm")
        kwargs.pop("yes", None)
        result = cmd.func(ctx, **kwargs)
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
        group_json = bool((click_ctx.parent.obj or {}).get("json")) if click_ctx.parent else False
        code = run_command(ext, cmd, kwargs, json_mode=json_flag or group_json)
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
        click_ctx.ensure_object(dict)
        click_ctx.obj["json"] = json_flag

    return root


def add_command(ext: Extension, group: click.Group, cmd: Command) -> None:
    """Attach one command to a Click group.

    Args:
        ext: Extension the command belongs to.
        group: Group (or subgroup) to extend.
        cmd: Command to attach.
    """
    params = _signature_params(cmd)
    if cmd.destructive:
        params.append(
            click.Option(
                ["--yes"], is_flag=True, default=False, help="Confirm a destructive action."
            )
        )
    params.append(_json_option())
    group.add_command(
        click.Command(
            cmd.name, callback=_make_callback(ext, cmd), params=params, help=cmd.help or None
        )
    )


def main_for(ext: Extension) -> Callable[[], None]:
    """Return a ``main()`` entry point for an extension, suitable for ``[project.scripts]``.

    Args:
        ext: Extension to serve.

    Returns:
        A zero-argument function that runs the CLI and exits with its code.
    """
    from .builtin import add_builtin_commands

    def main() -> None:
        group = to_click(ext)
        add_builtin_commands(ext, group)
        group(prog_name=ext.name)
        sys.exit(EXIT_OK)

    return main
