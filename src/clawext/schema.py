"""Machine-readable description of an extension (used by ``schema`` and skill generation)."""

from __future__ import annotations

import inspect
import typing
from typing import Any

from .extension import Command, Extension
from .render import to_jsonable


def type_name(hint: Any) -> str:
    """Return a short readable name for a type annotation.

    Args:
        hint: A type annotation.

    Returns:
        For example ``"int"``, ``"Path"`` or ``"list[str]"``.
    """
    if hint is inspect.Parameter.empty:
        return "str"
    origin = typing.get_origin(hint)
    if origin is None:
        return str(getattr(hint, "__name__", hint))
    args = ", ".join(type_name(a) for a in typing.get_args(hint))
    if getattr(origin, "__name__", "") in ("UnionType", "Union"):
        return " | ".join(type_name(a) for a in typing.get_args(hint))
    return f"{getattr(origin, '__name__', str(origin))}[{args}]"


def command_params(cmd: Command) -> list[dict[str, Any]]:
    """Describe the parameters of one command (the context is omitted).

    Args:
        cmd: Command to describe.

    Returns:
        One mapping per parameter with name, kind, type, required and default.
    """
    hints = typing.get_type_hints(cmd.func)
    out: list[dict[str, Any]] = []
    for p in list(inspect.signature(cmd.func).parameters.values())[1:]:
        required = p.default is inspect.Parameter.empty
        entry: dict[str, Any] = {
            "name": p.name.replace("_", "-"),
            "kind": "argument" if required else "option",
            "type": type_name(hints.get(p.name, str)),
            "required": required,
        }
        if not required:
            entry["default"] = to_jsonable(p.default)
        out.append(entry)
    return out


def extension_schema(ext: Extension) -> dict[str, Any]:
    """Describe an extension and its commands.

    Args:
        ext: Extension to describe.

    Returns:
        A JSON-safe mapping.
    """
    config: dict[str, Any] = {}
    if ext.config is not None:
        for key, field in ext.config.model_fields.items():
            config[key] = {
                "type": type_name(field.annotation),
                "default": None
                if field.is_required()
                else to_jsonable(field.get_default(call_default_factory=True)),
                "description": field.description or "",
            }
    return {
        "name": ext.name,
        "about": ext.about,
        "plugin": ext.plugin.name,
        "runs_on": ext.runs_on,
        "state": ext.state,
        "secrets": list(ext.secrets),
        "needs": {"bins": list(ext.needs.bins), "python": list(ext.needs.python)},
        "config": config,
        "commands": [
            {
                "name": cmd.name,
                "help": cmd.help,
                "destructive": cmd.destructive,
                "params": command_params(cmd),
            }
            for cmd in ext.commands.values()
        ],
    }
