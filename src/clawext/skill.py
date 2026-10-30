"""SKILL.md generation following the Agent Skills open standard."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Any

import jinja2

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


CONVENTIONS = (
    "Every command accepts `--json`. Exit codes: 0 ok, 1 failure, "
    "2 not configured or bad usage, 3 unreachable."
)


def _usage(cli: str, cmd: dict[str, Any]) -> str:
    parts = [cli, cmd["name"]]
    for p in cmd["params"]:
        if p["kind"] == "argument":
            parts.append(f"<{p['name']}>")
        else:
            parts.append(f"[--{p['name']}]")
    return " ".join(parts)


def _param_lines(cmd: dict[str, Any]) -> list[str]:
    lines = []
    for p in cmd["params"]:
        flag = f"`--{p['name']}`" if p["kind"] == "option" else f"`<{p['name']}>`"
        bits = [p["type"]]
        if p.get("choices"):
            bits = ["|".join(p["choices"])]
        if p["required"]:
            bits.append("required")
        elif p.get("default") not in (None, [], False):
            bits.append(f"default {p['default']}")
        text = f"- {flag} ({', '.join(bits)})"
        lines.append(f"{text}: {p['help']}" if p.get("help") else text)
    return lines


def render_commands(cli: str, schema: dict[str, Any]) -> str:
    """Render the command reference block (usage, help, parameters) as Markdown.

    Args:
        cli: The command line prefix (``tds remote``).
        schema: Result of :func:`extension_schema`.

    Returns:
        Markdown text, one section per command.
    """
    blocks: list[str] = []
    for cmd in schema["commands"]:
        lines = [f"### `{_usage(cli, cmd)}`", ""]
        if cmd["help"]:
            lines.extend([cmd["help"], ""])
        params = _param_lines(cmd)
        if params:
            lines.extend([*params, ""])
        if cmd["destructive"]:
            lines.extend(["Destructive: requires `--yes`.", ""])
        blocks.append("\n".join(lines).rstrip())
    return "\n\n".join(blocks)


def render_config(schema: dict[str, Any]) -> str:
    """Render the config keys as a Markdown list.

    Args:
        schema: Result of :func:`extension_schema`.

    Returns:
        One bullet per key with type, default and description.
    """
    lines = []
    for key, info in schema["config"].items():
        text = f"- `{key}` ({info['type']}, default `{info['default']}`)"
        lines.append(f"{text}: {info['description']}" if info["description"] else text)
    return "\n".join(lines)


def generate_skill(ext: Extension, template: str | Path | None = None) -> str:
    """Render the SKILL.md for an extension from a Jinja template.

    The template defaults to the built-in one; pass a path (or ``Extension.skill_template``)
    for a hand-written skill with generated blocks. Variables: ``name``, ``description``,
    ``about``, ``cli``, ``conventions``, ``commands_md``, ``config_md``, ``secrets``,
    ``config`` and the full ``schema``. Undefined variables are errors.

    Args:
        ext: Extension to document.
        template: Template file path, or ``None`` for the extension's own / built-in one.

    Returns:
        The full SKILL.md text (frontmatter plus body).

    Raises:
        UsageError: The name/description violate the standard or the template is broken.
    """
    schema = extension_schema(ext)
    name = skill_name(ext)
    names = ", ".join(c["name"] for c in schema["commands"])
    description = (
        f"{ext.about.rstrip('.')}. Commands: {names}." if names else f"{ext.about.rstrip('.')}."
    )
    validate_skill(name, description)
    cli = ext.name if ext.plugin.name == DEFAULT_PLUGIN.name else f"{ext.plugin.name} {ext.name}"
    source = template or ext.skill_template
    text = (
        Path(source).read_text()
        if source is not None
        else resources.files("clawext").joinpath("skill.md.j2").read_text()
    )
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    try:
        out = env.from_string(text).render(
            name=name,
            description=description,
            about=ext.about,
            cli=cli,
            conventions=CONVENTIONS,
            commands_md=render_commands(cli, schema),
            config_md=render_config(schema),
            secrets=schema["secrets"],
            config=schema["config"],
            schema=schema,
        )
    except jinja2.TemplateError as exc:
        raise UsageError(f"skill template error: {exc}") from exc
    return out if out.endswith("\n") else out + "\n"
