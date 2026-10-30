"""Output rendering: command results become JSON or readable text."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


@dataclass
class Output:
    """A result with a custom human rendering.

    Attributes:
        data: The structured result (what ``--json`` prints).
        text: Human-readable text shown instead of the default rendering.
    """

    data: Any
    text: str


def to_jsonable(value: Any) -> Any:
    """Convert a command result into JSON-safe data.

    Args:
        value: Any value a command may return.

    Returns:
        Plain dicts, lists, strings, numbers, booleans and ``None``.
    """
    if isinstance(value, Output):
        return to_jsonable(value.data)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def render(result: Any, *, json_mode: bool) -> str:
    """Render a command result.

    Args:
        result: Value returned by a command.
        json_mode: Emit JSON instead of text.

    Returns:
        The text to print on stdout (no trailing newline).
    """
    if json_mode:
        return json.dumps(to_jsonable(result), indent=2, sort_keys=False)
    if isinstance(result, Output):
        return result.text
    if result is None:
        return ""
    data = to_jsonable(result)
    if isinstance(data, str):
        return data
    if isinstance(data, dict | list):
        return yaml.safe_dump(data, default_flow_style=False, sort_keys=False).rstrip()
    return str(data)


def render_error(body: dict[str, object], *, json_mode: bool) -> str:
    """Render an error envelope.

    Args:
        body: Mapping from :meth:`ClawextError.to_dict`.
        json_mode: Emit the JSON envelope instead of text.

    Returns:
        JSON ``{"error": {...}}`` or ``error: ...`` text with an optional hint line.
    """
    if json_mode:
        return json.dumps({"error": body}, indent=2)
    text = f"error: {body['message']}"
    if body.get("hint"):
        text += f"\nhint: {body['hint']}"
    return text
