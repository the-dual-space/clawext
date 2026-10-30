"""Commands every extension gets for free: init, doctor, status, config, schema, skill."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

import click
import yaml

from . import __version__
from .adapter import add_command
from .config import config_paths, set_config_value
from .context import Context
from .errors import EXIT_FAILURE, EXIT_OK, ConfigError
from .extension import Command, Extension, make_command
from .render import Output, to_jsonable
from .schema import extension_schema
from .skill import generate_skill

OK, WARN, FAIL = "ok", "warn", "fail"


def _check(name: str, status: str, detail: str = "") -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def run_checks(ext: Extension, ctx: Context) -> list[dict[str, str]]:
    """Run the health checks of an extension.

    Args:
        ext: Extension being checked.
        ctx: Context for the current run.

    Returns:
        One entry per check with ``name``, ``status`` (ok/warn/fail) and ``detail``.
    """
    checks: list[dict[str, str]] = []
    role = ctx.plugin.role(ctx.environ)
    if ext.runs_on == "any" or role is None:
        checks.append(
            _check(
                "host",
                OK if ext.runs_on == "any" else WARN,
                f"role={role or 'unset'}, runs_on={ext.runs_on}",
            )
        )
    elif role == ext.runs_on.upper():
        checks.append(_check("host", OK, f"role={role}"))
    else:
        checks.append(_check("host", FAIL, f"runs_on={ext.runs_on} but role={role}"))
    for binary in ext.needs.bins:
        found = shutil.which(binary)
        checks.append(_check(f"bin:{binary}", OK if found else FAIL, found or "not on PATH"))
    for module in ext.needs.python:
        try:
            present = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            present = False
        checks.append(
            _check(
                f"python:{module}",
                OK if present else FAIL,
                "importable" if present else "not installed",
            )
        )
    store = ctx.secrets.store
    if ext.secrets:
        if not store.is_private():
            checks.append(
                _check(
                    "secrets-file", FAIL, f"{store.path} is readable by group/others (chmod 600)"
                )
            )
        for name in ext.secrets:
            checks.append(
                _check(
                    f"secret:{name}",
                    OK if ctx.secrets.has(name) else WARN,
                    "set" if ctx.secrets.has(name) else "not set",
                )
            )
    checks.append(
        _check("config", OK, ", ".join(str(p) for p in ctx.loaded.files) or "defaults only")
    )
    return checks


def _doctor_exit(result: Any) -> int:
    return EXIT_FAILURE if any(c["status"] == FAIL for c in result["checks"]) else EXIT_OK


def _doctor_text(checks: list[dict[str, str]]) -> str:
    marks = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}
    return "\n".join(f"[{marks[c['status']]}] {c['name']}: {c['detail']}" for c in checks)


def build_builtins(ext: Extension) -> dict[str, Command]:
    """Create the free commands bound to one extension.

    Args:
        ext: Extension the commands operate on.

    Returns:
        Mapping of command name to command (``config show`` / ``config set`` are keyed ``config:show`` / ``config:set``).
    """

    def doctor(ctx: Context) -> Output:
        """Check that the host, binaries, Python modules, secrets and config are in order."""
        checks = run_checks(ext, ctx)
        return Output(
            {"ok": all(c["status"] != FAIL for c in checks), "checks": checks}, _doctor_text(checks)
        )

    def status(ctx: Context) -> dict[str, Any]:
        """Show the extension's version, placement, config files and which secrets are set."""
        shared, local = config_paths(ctx.plugin, ext.name, ctx.environ)
        return {
            "name": ext.name,
            "framework": __version__,
            "plugin": ext.plugin.name,
            "role": ctx.plugin.role(ctx.environ),
            "runs_on": ext.runs_on,
            "state": ext.state,
            "state_dir": str(ctx.plugin.state_dir(ext.name, ctx.environ)),
            "config_files": {"shared": str(shared), "local": str(local)},
            "secrets": {name: ctx.secrets.has(name) for name in ext.secrets},
            "commands": sorted(ext.commands),
        }

    def init(ctx: Context) -> dict[str, Any]:
        """Create the home folder, a private secrets file, and a default config file (never overwrites)."""
        created: list[str] = []
        ctx.home.mkdir(parents=True, exist_ok=True)
        secrets_path = ctx.secrets.store.path
        if ext.secrets and not secrets_path.exists():
            skeleton: dict[str, Any] = {}
            for dotted in ext.secrets:
                node = skeleton
                *parents, leaf = dotted.split(".")
                for part in parents:
                    node = node.setdefault(part, {})
                node[leaf] = ""
            secrets_path.write_text(yaml.safe_dump(skeleton))
            secrets_path.chmod(0o600)
            created.append(str(secrets_path))
        shared, _ = config_paths(ctx.plugin, ext.name, ctx.environ)
        if ext.config is not None and not shared.exists():
            defaults = ext.config().model_dump(mode="json")
            shared.write_text(yaml.safe_dump(defaults, sort_keys=True))
            created.append(str(shared))
        return {"created": created, "home": str(ctx.home)}

    def config_show(ctx: Context) -> dict[str, Any]:
        """Show every config value and which layer (default, file, env, secret) it came from."""
        values = ctx.loaded.as_dict()
        return {
            "files": [str(p) for p in ctx.loaded.files],
            "values": {
                k: {"value": v, "source": ctx.loaded.provenance.get(k, "default")}
                for k, v in values.items()
            },
        }

    def config_set(ctx: Context, key: str, value: str) -> dict[str, str]:
        """Set one config value in the shared config file (validated against the config model)."""
        if ext.config is None:
            raise ConfigError(f"extension '{ext.name}' has no config")
        path = set_config_value(ext.config, ctx.plugin, ext.name, key, value, ctx.environ)
        return {"written": str(path), "key": key}

    def schema(ctx: Context) -> dict[str, Any]:
        """Print a machine-readable description of this extension and its commands."""
        del ctx
        return extension_schema(ext)

    def skill(ctx: Context, out: Path | None = None) -> Output:
        """Generate the SKILL.md for this extension (printed, or written to OUT/SKILL.md)."""
        del ctx
        text = generate_skill(ext)
        if out is not None:
            out.mkdir(parents=True, exist_ok=True)
            target = out / "SKILL.md"
            target.write_text(text)
            return Output({"written": str(target)}, f"wrote {target}")
        return Output({"skill": text}, text)

    def build(func: Any, name: str, exit_for: Any = None) -> Command:
        return make_command(name, func, exit_for=exit_for)

    return {
        "doctor": build(doctor, "doctor", _doctor_exit_output),
        "status": build(status, "status"),
        "init": build(init, "init"),
        "config:show": build(config_show, "show"),
        "config:set": build(config_set, "set"),
        "schema": build(schema, "schema"),
        "skill": build(skill, "skill"),
    }


def _doctor_exit_output(result: Any) -> int:
    data = result.data if isinstance(result, Output) else result
    return _doctor_exit(to_jsonable(data))


def add_builtin_commands(ext: Extension, group: click.Group) -> None:
    """Attach the free commands to an extension's group (an extension's own command of the same name wins; the free one becomes ``ext-<name>``).

    Args:
        ext: Extension the commands operate on.
        group: The extension's Click group.
    """
    builtins = build_builtins(ext)
    config_group = click.Group("config", help="Inspect and change configuration.")
    for key, cmd in builtins.items():
        if key.startswith("config:"):
            add_command(ext, config_group, cmd)
        elif cmd.name not in group.commands:
            add_command(ext, group, cmd)
        else:  # the extension's own command wins; the free one stays reachable as ext-<name>
            cmd.name = f"ext-{cmd.name}"
            add_command(ext, group, cmd)
    if "config" not in group.commands:
        group.add_command(config_group)
    else:
        config_group.name = "ext-config"
        group.add_command(config_group)
