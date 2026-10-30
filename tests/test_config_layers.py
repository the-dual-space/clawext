"""Tests for config pointers, nested env overrides, deep merge, streaming and stdin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import Field

from clawext import Config, Context, extension
from clawext.config import config_paths, load_config
from clawext.errors import ConfigError
from clawext.secrets import ScopedSecrets, SecretStore

from .conftest import PLUGIN
from .test_cli import invoke


class Nested(Config):
    """Config with a mapping and a defaulted scalar."""

    hosts: dict[str, dict[str, str]] = Field(default_factory=dict)
    path: str = "default"
    retries: int = 3


def _secrets(home: Path) -> ScopedSecrets:
    return ScopedSecrets(SecretStore(home / "secrets.yaml"), [], "sample")


def _write(path: Path, data: object) -> None:
    path.write_text(yaml.safe_dump(data))


def test_env_pointer(home: Path, env: dict[str, str]) -> None:
    """``${env:VAR}`` is expanded; an unset variable is a clear error."""
    shared, _ = config_paths(PLUGIN, "sample", env)
    _write(shared, {"path": "${env:MY_DIR}/x"})
    loaded = load_config(Nested, PLUGIN, "sample", _secrets(home), {**env, "MY_DIR": "/data"})
    assert loaded.as_dict()["path"] == "/data/x"
    with pytest.raises(ConfigError, match="MY_DIR"):
        load_config(Nested, PLUGIN, "sample", _secrets(home), env)


def test_deep_merge_across_files(home: Path, env: dict[str, str]) -> None:
    """Dict values merge key by key between the shared and local file."""
    shared, local = config_paths(PLUGIN, "sample", env)
    _write(shared, {"hosts": {"a": {"ip": "1"}, "b": {"ip": "2"}}})
    _write(local, {"hosts": {"b": {"ip": "9"}}})
    loaded = load_config(Nested, PLUGIN, "sample", _secrets(home), env)
    assert loaded.as_dict()["hosts"] == {"a": {"ip": "1"}, "b": {"ip": "9"}}


def test_nested_env_override(home: Path, env: dict[str, str]) -> None:
    """``PREFIX_KEY__A__B`` sets a nested value and wins over files."""
    shared, _ = config_paths(PLUGIN, "sample", env)
    _write(shared, {"hosts": {"a": {"ip": "1"}}})
    env = {**env, "DEMO_SAMPLE_HOSTS__A__IP": "7", "DEMO_SAMPLE_HOSTS__C__IP": "8"}
    loaded = load_config(Nested, PLUGIN, "sample", _secrets(home), env)
    assert loaded.as_dict()["hosts"] == {"a": {"ip": "7"}, "c": {"ip": "8"}}
    assert loaded.provenance["hosts"] == "env"


def test_null_means_default(home: Path, env: dict[str, str]) -> None:
    """An empty YAML key falls back to the default instead of failing validation."""
    shared, _ = config_paths(PLUGIN, "sample", env)
    shared.write_text("retries:\npath: x\n")
    loaded = load_config(Nested, PLUGIN, "sample", _secrets(home), env)
    assert loaded.as_dict()["retries"] == 3
    assert loaded.provenance["retries"] == "default"


def test_generator_streams_lines(plugin_env: None) -> None:
    """A generator command prints one JSON object per line as items are produced."""
    app = extension("g", "Stream.")

    @app.command
    def count(ctx: Context, n: int = 3):  # type: ignore[no-untyped-def]
        """Count."""
        for i in range(n):
            yield {"i": i}

    out = invoke(app, "--json", "count", "--n", "2").stdout.strip().splitlines()
    assert [json.loads(line) for line in out] == [{"i": 0}, {"i": 1}]


def test_live_log_and_stdin(plugin_env: None) -> None:
    """``log(live=True)`` goes to stderr at once and ``stdin_text`` reads piped input."""
    app = extension("l", "Live.")

    @app.command
    def echo(ctx: Context) -> str:
        """Echo."""
        ctx.log("working", live=True)
        return ctx.stdin_text().upper()

    from click.testing import CliRunner

    from clawext.adapter import build_group

    result = CliRunner().invoke(build_group(app), ["echo"], input="hello")
    assert "HELLO" in result.stdout
    assert "working" in result.output
