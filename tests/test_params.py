"""Tests for parameter markers, docstring help, skill templates and command options."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import pytest

from clawext import Context, Extension, extension
from clawext.errors import UsageError
from clawext.params import Arg, Opt, describe_params, split_doc
from clawext.skill import generate_skill
from tests.test_cli import invoke


@pytest.fixture
def plugin_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the default plugin home at a temporary folder."""
    monkeypatch.setenv("CLAWEXT_HOME", str(tmp_path / "home"))


def test_split_doc_extracts_arg_help() -> None:
    """The text before ``Args:`` is the summary and entries become per-arg help."""
    summary, args = split_doc(
        "Do it.\n\nArgs:\n    path: Where to look.\n    n: How many\n        rows.\n\nReturns:\n    x"
    )
    assert summary == "Do it."
    assert args == {"path": "Where to look.", "n": "How many rows."}


def test_opt_validates_flags() -> None:
    """Malformed flags are rejected at declaration time."""
    with pytest.raises(UsageError):
        Opt("nope")
    with pytest.raises(UsageError):
        Opt("--a", "--b")


def test_markers_shorts_choices_and_help(plugin_env: None) -> None:
    """Short flags, Literal choices, Arg positionals and docstring help reach the CLI."""
    app = extension("m", "Markers.")

    @app.command
    def go(
        ctx: Context,
        mode: Literal["fast", "slow"] = "fast",
        limit: Annotated[int, Opt("-n", help="Row limit")] = 5,
        path: Annotated[str | None, Arg()] = None,
        tags: list[str] | None = None,
    ) -> dict[str, object]:
        """Run.

        Args:
            mode: Speed.
            path: Optional location.
        """
        return {"mode": mode, "limit": limit, "path": path, "tags": list(tags or [])}

    ok = invoke(
        app, "--json", "go", "-n", "7", "--mode", "slow", "here", "--tags", "a", "--tags", "b"
    )
    assert json.loads(ok.stdout) == {"mode": "slow", "limit": 7, "path": "here", "tags": ["a", "b"]}
    bad = invoke(app, "go", "--mode", "warp")
    assert bad.exit_code == 2
    helptext = invoke(app, "go", "--help").stdout
    assert "Row limit" in helptext
    assert "Speed." in helptext


def test_required_option_and_negatable_flag(plugin_env: None) -> None:
    """``Opt(required=True)`` makes a required option; default-True bools get ``--no-x``."""
    app = extension("r", "Required.")

    @app.command
    def go(ctx: Context, *, name: Annotated[str, Opt(required=True)], color: bool = True) -> str:
        """Go."""
        return f"{name}:{color}"

    assert invoke(app, "go").exit_code == 2
    assert invoke(app, "go", "--name", "x", "--no-color").stdout.strip() == "x:False"


def test_command_without_context(plugin_env: None) -> None:
    """A function that does not take ``ctx`` is still a command."""
    app = extension("n", "No ctx.")

    @app.command
    def add(a: int, b: int = 1) -> int:
        """Add."""
        return a + b

    assert invoke(app, "--json", "add", "2", "--b", "3").stdout.strip() == "5"


def test_non_destructive_command_may_use_yes(plugin_env: None) -> None:
    """A command that declares its own ``yes`` parameter receives it."""
    app = extension("y", "Yes.")

    @app.command
    def ask(ctx: Context, yes: bool = False) -> bool:
        """Ask."""
        return yes

    assert invoke(app, "--json", "ask", "--yes").stdout.strip() == "true"


def test_exit_for_and_hidden(plugin_env: None) -> None:
    """``exit_for`` maps results to exit codes and ``hidden`` removes help entries."""
    app = extension("e", "Exit.")

    @app.command(exit_for=lambda r: 0 if r else 1, hidden=True)
    def check(ctx: Context) -> bool:
        """Check."""
        return False

    assert invoke(app, "check").exit_code == 1
    assert "check" not in invoke(app, "--help").stdout


def test_both_markers_rejected() -> None:
    """Combining Opt and Arg on one parameter is an error."""

    def fn(x: Annotated[str, Opt(), Arg()] = "a") -> None:
        """Fn."""

    with pytest.raises(UsageError):
        describe_params(fn)


def test_skill_template(sample: Extension, tmp_path: Path) -> None:
    """A custom Jinja template can embed generated blocks; typos fail loudly."""
    tpl = tmp_path / "SKILL.md.j2"
    tpl.write_text(
        "---\nname: {{ name }}\ndescription: {{ description }}\n---\nHand-written.\n\n{{ commands_md }}\n"
    )
    text = generate_skill(sample, tpl)
    assert "Hand-written." in text
    assert "### `demo sample hello <name>" in text
    assert "`--times`" in text
    tpl.write_text("{{ nope }}")
    with pytest.raises(UsageError):
        generate_skill(sample, tpl)


def test_default_skill_lists_params(sample: Extension) -> None:
    """The built-in template shows parameters and config keys."""
    text = generate_skill(sample)
    assert "- `--times` (int, default 1)" in text
    assert "## Config" in text
    assert text.endswith("\n")
