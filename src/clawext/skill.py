"""SKILL.md generation following the Agent Skills open standard."""

from __future__ import annotations

import re
from typing import Any

from .errors import UsageError
from .extension import Extension
from .plugin import DEFAULT_PLUGIN
from .schema import extension_schema

MAX_NAME = 64
MAX_DESCRIPTION = 1024
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def skill_name(ext: Extension) -> str:
    """Return the skill name: ``<plugin>-<extension>``, or just the extension when standalone.

    Args:
        ext: Extension to name.

    Returns:
        A lowercase hyphenated skill name.
    """
    if ext.plugin.name == DEFAULT_PLUGIN.name:
        return ext.name
    return f"{ext.plugin.name}-{ext.name}"


def validate_skill(name: str, description: str) -> None:
    """Check name and description against the Agent Skills limits.

    Args:
        name: Skill name.
        description: Skill description.

    Raises:
        UsageError: A field is empty, malformed, or too long.
    """
    if not _NAME_RE.match(name) or len(name) > MAX_NAME:
        raise UsageError(
            f"invalid skill name {name!r}: lowercase letters, digits, single hyphens, max {MAX_NAME}"
        )
    if not description.strip():
        raise UsageError("skill description must not be empty")
    if len(description) > MAX_DESCRIPTION:
        raise UsageError(f"skill description is {len(description)} chars, max {MAX_DESCRIPTION}")


def _usage(cli: str, cmd: dict[str, Any]) -> str:
    parts = [cli, cmd["name"]]
    for p in cmd["params"]:
        parts.append(f"<{p['name']}>" if p["kind"] == "argument" else f"[--{p['name']}]")
    return " ".join(parts)


def generate_skill(ext: Extension) -> str:
    """Render the SKILL.md for an extension from its declaration.

    Args:
        ext: Extension to document.

    Returns:
        The full SKILL.md text (frontmatter plus body).

    Raises:
        UsageError: The generated name or description violates the standard.
    """
    schema = extension_schema(ext)
    name = skill_name(ext)
    names = ", ".join(c["name"] for c in schema["commands"])
    description = (
        f"{ext.about.rstrip('.')}. Commands: {names}." if names else f"{ext.about.rstrip('.')}."
    )
    validate_skill(name, description)
    cli = ext.name if ext.plugin.name == DEFAULT_PLUGIN.name else f"{ext.plugin.name} {ext.name}"

    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "---",
        "",
        f"# {name}",
        "",
        ext.about,
        "",
        "Every command accepts `--json`. Exit codes: 0 ok, 1 failure, 2 not configured or bad usage, 3 unreachable.",
        "",
        "## Commands",
        "",
    ]
    for cmd in schema["commands"]:
        lines.append(f"### `{_usage(cli, cmd)}`")
        lines.append("")
        if cmd["help"]:
            lines.extend([cmd["help"], ""])
        if cmd["destructive"]:
            lines.extend(["Destructive: requires `--yes`.", ""])
    if schema["secrets"]:
        lines.extend(["## Secrets", "", *[f"- `{s}`" for s in schema["secrets"]], ""])
    lines.extend(
        [
            "## Health",
            "",
            f"Run `{cli} doctor` to verify requirements and `{cli} status` for configuration state.",
            "",
        ]
    )
    return "\n".join(lines)
