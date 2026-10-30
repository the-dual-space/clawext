"""End-to-end tests of the generated CLI through Click's runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner, Result

from clawext import Extension, Output, extension, to_click
from clawext.builtin import add_builtin_commands
from clawext.errors import ExtensionError, UsageError
from clawext.extension import Needs, check_framework_range
from clawext.render import render, render_error, to_jsonable
from clawext.schema import extension_schema, type_name
from clawext.skill import generate_skill, skill_name, validate_skill

from .conftest import PLUGIN

pytestmark = pytest.mark.usefixtures("isolated")


def invoke(app: Extension, *args: str) -> Result:
    """Run the extension CLI (with free commands) and return the result."""
    group = to_click(app)
    add_builtin_commands(app, group)
    return CliRunner().invoke(group, list(args))


def write_secrets(home: Path, data: object, mode: int = 0o600) -> None:
    """Write a secrets file with the given permissions."""
    path = home / "secrets.yaml"
    path.write_text(yaml.safe_dump(data))
    path.chmod(mode)


def test_arguments_options_and_flags(sample: Extension) -> None:
    """No-default params are arguments, defaulted ones options, bools flags."""
    result = invoke(sample, "--json", "hello", "ana", "--times", "2", "--loud")
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"greeting": "HELLO ANA", "times": 2}


def test_json_flag_after_subcommand(sample: Extension) -> None:
    """``--json`` also works after the subcommand."""
    result = invoke(sample, "hello", "ana", "--json")
    assert json.loads(result.stdout)["greeting"] == "hello ana"


def test_human_output_is_yaml_like(sample: Extension) -> None:
    """Without --json dict results render as readable YAML."""
    result = invoke(sample, "hello", "ana")
    assert "greeting: hello ana" in result.stdout


def test_list_and_optional_parameters(sample: Extension) -> None:
    """List arguments take several values; Optional options default to None."""
    result = invoke(sample, "--json", "tags", "a", "b", "--limit", "4")
    assert json.loads(result.stdout) == {"items": ["a", "b"], "limit": 4}
    result = invoke(sample, "--json", "tags", "a")
    assert json.loads(result.stdout)["limit"] is None


def test_diagnostics_go_to_stderr(sample: Extension) -> None:
    """``ctx.log`` lines appear on stderr only."""
    result = CliRunner().invoke(_group(sample), ["--json", "hello", "x"])
    assert json.loads(result.stdout)["times"] == 1
    assert result.stderr.strip() == "greeting"
    assert "greeting" not in result.stdout.replace('"greeting"', "")


def _group(app: Extension):  # type: ignore[no-untyped-def]
    group = to_click(app)
    add_builtin_commands(app, group)
    return group


def test_unexpected_exception_becomes_envelope(sample: Extension) -> None:
    """Unhandled exceptions exit 1 with a JSON error envelope."""
    result = invoke(sample, "--json", "boom")
    assert result.exit_code == 1
    body = json.loads(result.stdout)["error"]
    assert body["type"] == "unexpected"
    assert "kaboom" in body["message"]


def test_missing_secret_exit_code_two(sample: Extension) -> None:
    """A declared but unset secret is a configuration error (exit 2)."""
    result = invoke(sample, "--json", "reveal")
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["type"] == "secret_missing"


def test_secret_value_is_redacted_from_output(sample: Extension, home: Path) -> None:
    """A secret returned by a command never reaches stdout."""
    write_secrets(home, {"svc": {"token": "hunter2hunter2"}})
    result = invoke(sample, "reveal")
    assert result.exit_code == 0
    assert "hunter2hunter2" not in result.output
    assert "token=***" in result.stdout


def test_destructive_requires_yes(sample: Extension) -> None:
    """Destructive commands refuse without --yes and run with it."""
    refused = invoke(sample, "--json", "wipe", "x")
    assert refused.exit_code == 2
    assert json.loads(refused.stdout)["error"]["hint"] == "re-run with --yes to confirm"
    ok = invoke(sample, "--json", "wipe", "x", "--yes")
    assert json.loads(ok.stdout) == {"wiped": "x"}


def test_wrong_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """``runs_on='server'`` refuses on a LOCAL machine."""
    app = extension("srv", "Server only.", plugin=PLUGIN, runs_on="server")

    @app.command
    def ping(ctx: object) -> str:
        """Ping."""
        return "pong"

    result = invoke(app, "--json", "ping")
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["type"] == "wrong_host"
    monkeypatch.setenv("MACHINE_ROLE", "SERVER")
    assert invoke(app, "ping").stdout.strip() == "pong"


def test_audit_log_records_runs_without_arguments(sample: Extension, home: Path) -> None:
    """One audit line per run; arguments are not recorded."""
    invoke(sample, "hello", "topsecretname")
    lines = (home / "audit.log").read_text().splitlines()
    record = json.loads(lines[-1])
    assert record["command"] == "hello"
    assert record["status"] == "ok"
    assert "topsecretname" not in lines[-1]


def test_doctor_reports_and_sets_exit_code(sample: Extension, home: Path) -> None:
    """Doctor exits 1 when a requirement fails and 0 when all pass."""
    write_secrets(home, {"svc": {"token": "x"}}, mode=0o644)
    bad = invoke(sample, "--json", "doctor")
    assert bad.exit_code == 1
    checks = {c["name"]: c["status"] for c in json.loads(bad.stdout)["checks"]}
    assert checks["secrets-file"] == "fail"
    (home / "secrets.yaml").chmod(0o600)
    good = invoke(sample, "doctor")
    assert good.exit_code == 0
    assert "[ok  ] bin:sh" in good.stdout


def test_doctor_flags_missing_requirements() -> None:
    """Missing binaries and modules fail the doctor."""
    app = extension(
        "needy",
        "Needs things.",
        plugin=PLUGIN,
        needs=Needs(bins=("definitely-not-a-binary",), python=("definitely_not_a_module",)),
    )
    result = invoke(app, "--json", "doctor")
    assert result.exit_code == 1
    statuses = [c["status"] for c in json.loads(result.stdout)["checks"]]
    assert statuses.count("fail") == 2


def test_status_lists_state(sample: Extension, home: Path) -> None:
    """Status reports placement, config files and which secrets are set."""
    write_secrets(home, {"svc": {"token": "x"}})
    data = json.loads(invoke(sample, "--json", "status").stdout)
    assert data["secrets"] == {"svc.token": True}
    assert data["role"] == "LOCAL"
    assert "hello" in data["commands"]


def test_init_creates_files_once(sample: Extension, home: Path) -> None:
    """Init writes a private secrets skeleton and default config, never overwriting."""
    first = json.loads(invoke(sample, "--json", "init").stdout)
    assert len(first["created"]) == 2
    assert (home / "secrets.yaml").stat().st_mode & 0o077 == 0
    assert yaml.safe_load((home / "sample.yaml").read_text())["retries"] == 3
    again = json.loads(invoke(sample, "--json", "init").stdout)
    assert again["created"] == []


def test_config_show_and_set(sample: Extension, home: Path) -> None:
    """Config show reports provenance; config set persists a value."""
    set_result = invoke(sample, "--json", "config", "set", "retries", "8")
    assert set_result.exit_code == 0
    shown = json.loads(invoke(sample, "--json", "config", "show").stdout)
    assert shown["values"]["retries"] == {"value": 8, "source": "shared file"}
    assert shown["values"]["inbox"]["source"] == "default"
    bad = invoke(sample, "--json", "config", "set", "nope", "1")
    assert bad.exit_code == 2


def test_config_set_without_config_model() -> None:
    """Config set on an extension without a config fails cleanly."""
    app = extension("plain", "No config.", plugin=PLUGIN)
    result = invoke(app, "--json", "config", "set", "a", "1")
    assert result.exit_code == 2


def test_schema_command(sample: Extension) -> None:
    """Schema lists commands, params and config fields."""
    data = json.loads(invoke(sample, "--json", "schema").stdout)
    hello = next(c for c in data["commands"] if c["name"] == "hello")
    assert [p["name"] for p in hello["params"]] == ["name", "times", "loud"]
    assert hello["params"][0]["required"] is True
    assert data["config"]["retries"]["default"] == 3


def test_skill_command_prints_and_writes(sample: Extension, tmp_path: Path) -> None:
    """Skill prints SKILL.md or writes it into a folder."""
    printed = invoke(sample, "skill")
    assert printed.stdout.startswith("---\nname: demo-sample")
    out = tmp_path / "out"
    written = invoke(sample, "--json", "skill", "--out", str(out))
    assert written.exit_code == 0
    assert (out / "SKILL.md").read_text().startswith("---\nname: demo-sample")


def test_user_command_overrides_builtin() -> None:
    """A user-defined ``status`` wins over the free one."""
    app = extension("own", "Own status.", plugin=PLUGIN)

    @app.command
    def status(ctx: object) -> str:
        """Custom status."""
        return "custom"

    assert invoke(app, "status").stdout.strip() == "custom"


def test_render_helpers() -> None:
    """Rendering covers strings, Output, None, scalars and error text."""
    assert render("x", json_mode=False) == "x"
    assert render(None, json_mode=False) == ""
    assert render(5, json_mode=False) == "5"
    assert render(Output({"a": 1}, "custom"), json_mode=False) == "custom"
    assert json.loads(render(Output({"a": 1}, "custom"), json_mode=True)) == {"a": 1}
    assert render_error({"message": "m", "hint": "h"}, json_mode=False) == "error: m\nhint: h"
    assert json.loads(render_error({"message": "m"}, json_mode=True)) == {"error": {"message": "m"}}


def test_to_jsonable_handles_common_types(tmp_path: Path) -> None:
    """Paths, sets, tuples, dataclasses and models become JSON-safe data."""
    from dataclasses import dataclass

    from .conftest import DemoConfig

    @dataclass
    class Box:
        path: Path

    assert to_jsonable({"p": tmp_path, "s": {1}, "t": (1, 2)}) == {
        "p": str(tmp_path),
        "s": [1],
        "t": [1, 2],
    }
    assert to_jsonable(Box(tmp_path)) == {"path": str(tmp_path)}
    assert to_jsonable(DemoConfig())["retries"] == 3
    assert to_jsonable(object()).startswith("<object")


def test_extension_validation() -> None:
    """Bad declarations raise UsageError / ExtensionError."""
    with pytest.raises(UsageError, match="invalid extension name"):
        extension("Bad Name", "x")
    with pytest.raises(UsageError, match="runs_on"):
        extension("ok", "x", runs_on="moon")
    with pytest.raises(UsageError, match="state"):
        extension("ok", "x", state="cloud")
    with pytest.raises(UsageError, match="needs keys"):
        extension("ok", "x", needs={"nope": ["a"]})
    app = extension("ok", "x")

    @app.command
    def one(ctx: object) -> None:
        """One."""

    with pytest.raises(UsageError, match="duplicate"):
        app.command(one)


def test_framework_range_check() -> None:
    """Version ranges are enforced."""
    check_framework_range(None)
    check_framework_range(">=0.0.1,<1", "0.0.5")
    with pytest.raises(ExtensionError, match="requires clawext"):
        check_framework_range(">=1,<2", "0.0.5")
    with pytest.raises(ExtensionError, match="invalid"):
        check_framework_range("not a spec")
    with pytest.raises(ExtensionError):
        extension("x", "y", requires_framework=">=99")


def test_skill_validation_and_naming(sample: Extension) -> None:
    """Skill names and descriptions are validated against the standard."""
    assert skill_name(sample) == "demo-sample"
    assert skill_name(extension("solo", "x")) == "solo"
    validate_skill("ok-name", "fine")
    with pytest.raises(UsageError):
        validate_skill("Bad_Name", "fine")
    with pytest.raises(UsageError):
        validate_skill("ok", "  ")
    with pytest.raises(UsageError):
        validate_skill("ok", "x" * 2000)
    text = generate_skill(sample)
    assert "### `demo sample hello <name> [--times] [--loud]`" in text
    assert "Destructive: requires `--yes`." in text
    assert "- `svc.token`" in text


def test_schema_type_names() -> None:
    """Type names are short and readable."""
    assert type_name(int) == "int"
    assert type_name(list[str]) == "list[str]"
    assert type_name(int | None) == "int | NoneType"
    app = extension("noc", "No config.")
    assert extension_schema(app)["config"] == {}
