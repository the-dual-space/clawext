"""Tests for errors, plugin identity, secrets and layered config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clawext.config import config_paths, load_config, read_yaml_mapping, set_config_value
from clawext.errors import (
    ClawextError,
    ConfigError,
    SecretMissingError,
    SecretNotDeclaredError,
    UnreachableError,
    UsageError,
)
from clawext.plugin import Plugin
from clawext.secrets import ScopedSecrets, SecretStore

from .conftest import PLUGIN, DemoConfig


def write(path: Path, data: object) -> Path:
    """Write ``data`` as YAML and return the path."""
    path.write_text(yaml.safe_dump(data))
    return path


def test_error_envelope_and_exit_codes() -> None:
    """Errors carry stable exit codes and a JSON-ready body."""
    err = UnreachableError("down", hint="check vpn")
    assert err.exit_code == 3
    assert err.to_dict() == {
        "code": 3,
        "type": "unreachable",
        "message": "down",
        "hint": "check vpn",
    }
    assert UsageError("x").exit_code == 2
    assert "hint" not in ClawextError("plain").to_dict()


def test_plugin_name_validation_and_prefix() -> None:
    """Plugin names are validated; the env prefix is upper-cased with underscores."""
    assert Plugin("my-plugin").env_prefix == "MY_PLUGIN"
    with pytest.raises(ValueError, match="invalid plugin name"):
        Plugin("Bad Name")


def test_plugin_home_state_and_role(tmp_path: Path) -> None:
    """Home honours the override variable; role is upper-cased or None."""
    plugin = Plugin("demo", home="~/.demo", home_env="DEMO_HOME")
    env = {"DEMO_HOME": str(tmp_path), "MACHINE_ROLE": " server "}
    assert plugin.home_dir(env) == tmp_path
    assert plugin.state_dir("x", env) == tmp_path / "state" / "x"
    assert plugin.role(env) == "SERVER"
    assert plugin.role({}) is None
    assert plugin.home_dir({}) == Path("~/.demo").expanduser()


def test_secret_store_lookup_and_privacy(tmp_path: Path) -> None:
    """Nested lookup works; empty and structured values count as unset."""
    path = write(tmp_path / "s.yaml", {"a": {"b": "v"}, "empty": "", "n": 5, "lst": [1]})
    path.chmod(0o600)
    store = SecretStore(path)
    assert store.lookup("a.b") == "v"
    assert store.lookup("n") == "5"
    assert store.lookup("empty") is None
    assert store.lookup("a") is None
    assert store.lookup("lst") is None
    assert store.lookup("missing.key") is None
    assert store.is_private()
    path.chmod(0o644)
    assert not store.is_private()
    assert SecretStore(tmp_path / "none.yaml").is_private()
    assert SecretStore(tmp_path / "none.yaml").lookup("a") is None


def test_secret_store_rejects_bad_files(tmp_path: Path) -> None:
    """Malformed YAML and non-mapping files raise ConfigError."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed")
    with pytest.raises(ConfigError, match="invalid YAML"):
        SecretStore(bad).lookup("a")
    lst = tmp_path / "lst.yaml"
    lst.write_text("- 1\n")
    with pytest.raises(ConfigError, match="mapping"):
        SecretStore(lst).lookup("a")


def test_scoped_secrets_enforce_declaration(tmp_path: Path) -> None:
    """Only declared secrets are readable; missing ones raise with a hint."""
    path = write(tmp_path / "s.yaml", {"svc": {"token": "abc"}, "other": "zzz"})
    scoped = ScopedSecrets(SecretStore(path), ["svc.token", "svc.absent"], "demo")
    assert scoped.has("svc.token")
    assert not scoped.has("other")
    assert scoped.get("svc.token") == "abc"
    assert scoped.get("svc.token") == "abc"
    assert scoped.resolved == ["abc"]
    with pytest.raises(SecretNotDeclaredError):
        scoped.get("other")
    with pytest.raises(SecretMissingError) as info:
        scoped.get("svc.absent")
    assert info.value.hint is not None


def make_secrets(home: Path, data: object | None = None) -> ScopedSecrets:
    """Return scoped secrets backed by a file in ``home``."""
    path = home / "secrets.yaml"
    if data is not None:
        write(path, data)
    return ScopedSecrets(SecretStore(path), ["svc.token"], "sample")


def test_config_defaults_only(home: Path, env: dict[str, str]) -> None:
    """Without files or env the defaults are used and labelled."""
    loaded = load_config(DemoConfig, PLUGIN, "sample", make_secrets(home), env)
    assert loaded.as_dict() == {"inbox": "in", "retries": 3, "token": ""}
    assert set(loaded.provenance.values()) == {"default"}
    assert loaded.files == []


def test_config_layer_precedence(home: Path, env: dict[str, str]) -> None:
    """Env beats local file, which beats shared file, which beats defaults."""
    shared, local = config_paths(PLUGIN, "sample", env)
    write(shared, {"inbox": "shared", "retries": 5})
    write(local, {"inbox": "local"})
    env = {**env, "DEMO_SAMPLE_RETRIES": "9"}
    loaded = load_config(DemoConfig, PLUGIN, "sample", make_secrets(home), env)
    assert loaded.as_dict() == {"inbox": "local", "retries": 9, "token": ""}
    assert loaded.provenance == {"inbox": "local file", "retries": "env", "token": "default"}
    assert loaded.files == [shared, local]


def test_config_secret_pointer_is_resolved_and_masked(home: Path, env: dict[str, str]) -> None:
    """``${secret:...}`` is resolved, labelled, and masked in the dict view."""
    shared, _ = config_paths(PLUGIN, "sample", env)
    write(shared, {"token": "${secret:svc.token}"})
    loaded = load_config(
        DemoConfig, PLUGIN, "sample", make_secrets(home, {"svc": {"token": "s3cret"}}), env
    )
    assert loaded.values is not None
    assert loaded.values.token == "s3cret"  # type: ignore[attr-defined]
    assert loaded.provenance["token"] == "secret"
    assert loaded.as_dict()["token"] == "***"
    assert loaded.as_dict(mask_secrets=False)["token"] == "s3cret"


def test_config_validation_error_is_reported(home: Path, env: dict[str, str]) -> None:
    """Invalid values raise ConfigError naming the field."""
    shared, _ = config_paths(PLUGIN, "sample", env)
    write(shared, {"retries": "many"})
    with pytest.raises(ConfigError, match="retries"):
        load_config(DemoConfig, PLUGIN, "sample", make_secrets(home), env)


def test_config_without_model(home: Path, env: dict[str, str]) -> None:
    """An extension without a config model loads an empty config."""
    loaded = load_config(None, PLUGIN, "sample", make_secrets(home), env)
    assert loaded.values is None
    assert loaded.as_dict() == {}


def test_read_yaml_mapping_variants(tmp_path: Path) -> None:
    """Empty files give {}, lists and bad YAML raise."""
    empty = tmp_path / "e.yaml"
    empty.write_text("")
    assert read_yaml_mapping(empty) == {}
    lst = tmp_path / "l.yaml"
    lst.write_text("- 1\n")
    with pytest.raises(ConfigError):
        read_yaml_mapping(lst)
    bad = tmp_path / "b.yaml"
    bad.write_text("a: [")
    with pytest.raises(ConfigError):
        read_yaml_mapping(bad)


def test_set_config_value_roundtrip(home: Path, env: dict[str, str]) -> None:
    """``set_config_value`` validates, persists, and later loads see it."""
    path = set_config_value(DemoConfig, PLUGIN, "sample", "retries", "7", env)
    assert yaml.safe_load(path.read_text()) == {"retries": 7}
    loaded = load_config(DemoConfig, PLUGIN, "sample", make_secrets(home), env)
    assert loaded.as_dict()["retries"] == 7
    set_config_value(DemoConfig, PLUGIN, "sample", "token", "${secret:svc.token}", env)
    assert yaml.safe_load(path.read_text())["token"] == "${secret:svc.token}"


def test_set_config_value_rejects_bad_input(env: dict[str, str]) -> None:
    """Unknown keys and invalid values raise ConfigError and write nothing."""
    with pytest.raises(ConfigError, match="unknown config key"):
        set_config_value(DemoConfig, PLUGIN, "sample", "nope", "1", env)
    with pytest.raises(ConfigError, match="invalid value"):
        set_config_value(DemoConfig, PLUGIN, "sample", "retries", "many", env)
    shared, _ = config_paths(PLUGIN, "sample", env)
    assert not shared.exists()
