"""Machine-readable description of an extension (used by ``schema`` and skill generation)."""

from __future__ import annotations

from typing import Any

from .extension import Command, Extension
from .params import type_name
from .render import to_jsonable


def command_params(cmd: Command) -> list[dict[str, Any]]:
    """Describe the parameters of one command (the context is omitted).

    Args:
        cmd: Command to describe.

    Returns:
        One mapping per parameter with name, kind, type, required, default, help, choices.
    """
    out: list[dict[str, Any]] = []
    for spec in cmd.params:
        entry: dict[str, Any] = {
            "name": spec.display,
            "kind": spec.kind,
            "type": spec.type_name,
            "required": spec.required,
        }
        if not spec.required:
            entry["default"] = to_jsonable(spec.default)
        if spec.help:
            entry["help"] = spec.help
        if spec.choices:
            entry["choices"] = list(spec.choices)
        if spec.shorts:
            entry["short"] = list(spec.shorts)
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
