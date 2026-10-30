"""Layered extension config: defaults < shared file < local file < env, with provenance."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from .errors import ConfigError
from .plugin import Plugin
from .secrets import ScopedSecrets

_SECRET_RE = re.compile(r"\$\{secret:([A-Za-z0-9_.\-]+)\}")
_ENV_RE = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")

SRC_DEFAULT = "default"
SRC_SHARED = "shared file"
SRC_LOCAL = "local file"
SRC_ENV = "env"
SRC_SECRET = "secret"


@dataclass
class LoadedConfig:
    """A validated config plus where each top-level value came from.

    Attributes:
        values: The validated config model (``None`` when the extension has no config).
        provenance: Mapping of config key to its source label.
        files: Config files that were found and read.
        secret_keys: Keys whose values were resolved from secrets and must be masked.
    """

    values: BaseModel | None
    provenance: dict[str, str] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    secret_keys: set[str] = field(default_factory=set)

    def as_dict(self, *, mask_secrets: bool = True) -> dict[str, Any]:
        """Return the config as a plain dict.

        Args:
            mask_secrets: Replace secret-derived values with ``"***"``.

        Returns:
            The config values, or an empty dict when there is no config.
        """
        if self.values is None:
            return {}
        data = self.values.model_dump(mode="json")
        if mask_secrets:
            for key in self.secret_keys:
                if key in data:
                    data[key] = "***"
        return data


def config_paths(
    plugin: Plugin, extension: str, environ: Mapping[str, str] | None = None
) -> tuple[Path, Path]:
    """Return the shared and local config file paths of an extension.

    Args:
        plugin: Owning plugin.
        extension: Extension name.
        environ: Environment to read; defaults to ``os.environ``.

    Returns:
        ``(shared, local)`` paths; neither is required to exist.
    """
    home = plugin.home_dir(environ)
    return home / f"{extension}.yaml", home / f"{extension}.local.yaml"


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file that must hold a mapping.

    Args:
        path: File to read.

    Returns:
        The mapping (empty for an empty file).

    Raises:
        ConfigError: The file is not valid YAML or not a mapping.
    """
    try:
        loaded = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML ({exc})") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return loaded


def _coerce_env(raw: str) -> Any:
    """Parse an env string as JSON when possible, else keep the string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _deep_merge(base: dict[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``extra`` into ``base``; nested mappings merge key by key, anything else replaces."""
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _walk(value: Any, env: Mapping[str, str], secrets: ScopedSecrets, used: list[bool]) -> Any:
    """Resolve ``${env:VAR}`` and ``${secret:name}`` in every string, at any depth."""
    if isinstance(value, str):

        def from_env(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in env:
                raise ConfigError(f"config refers to unset environment variable '{name}'")
            return env[name]

        text = _ENV_RE.sub(from_env, value)
        if _SECRET_RE.search(text):
            used.append(True)
            text = _SECRET_RE.sub(lambda m: secrets.get(m.group(1)), text)
        return text
    if isinstance(value, dict):
        return {k: _walk(v, env, secrets, used) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, env, secrets, used) for v in value]
    return value


def _env_value(raw: str) -> Any:
    """Parse an env string: JSON lists/objects become structures, everything else stays text.

    Scalars stay strings so pydantic can coerce them to the field type (``"7"`` to ``int``
    or ``str`` alike).
    """
    value = _coerce_env(raw)
    return value if isinstance(value, dict | list) else raw


def _resolve_pointers(
    values: dict[str, Any],
    secrets: ScopedSecrets,
    env: Mapping[str, str],
) -> tuple[dict[str, Any], set[str]]:
    """Resolve pointers in all values; keys that contained a secret are reported for masking."""
    out: dict[str, Any] = {}
    secret_keys: set[str] = set()
    for key, value in values.items():
        used: list[bool] = []
        out[key] = _walk(value, env, secrets, used)
        if used:
            secret_keys.add(key)
    return out, secret_keys


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    """Set ``target[a][b]... = value`` creating intermediate mappings."""
    for part in path[:-1]:
        nxt = target.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            target[part] = nxt
        target = nxt
    target[path[-1]] = value


def load_config(
    model: type[BaseModel] | None,
    plugin: Plugin,
    extension: str,
    secrets: ScopedSecrets,
    environ: Mapping[str, str] | None = None,
) -> LoadedConfig:
    """Load and validate an extension's configuration.

    Args:
        model: Pydantic model describing the config, or ``None`` for no config.
        plugin: Owning plugin (home folder and env prefix).
        extension: Extension name.
        secrets: Scoped secrets used to resolve ``${secret:...}`` pointers.
        environ: Environment to read; defaults to ``os.environ``.

    Returns:
        The validated config with per-key provenance.

    Raises:
        ConfigError: A file is malformed or the merged values fail validation.
    """
    if model is None:
        return LoadedConfig(values=None)

    import os

    env = os.environ if environ is None else environ
    merged: dict[str, Any] = {}
    provenance: dict[str, str] = dict.fromkeys(model.model_fields, SRC_DEFAULT)
    files: list[Path] = []

    shared, local = config_paths(plugin, extension, env)
    for path, label in ((shared, SRC_SHARED), (local, SRC_LOCAL)):
        if path.is_file():
            files.append(path)
            for key, value in read_yaml_mapping(path).items():
                field_info = model.model_fields.get(key)
                if (
                    value is None
                    and field_info is not None
                    and field_info.get_default(call_default_factory=True) is not None
                ):
                    continue  # an empty key means "use the default"
                merged = _deep_merge(merged, {key: value})
                provenance[key] = label

    prefix = f"{plugin.env_prefix}_{extension.upper().replace('-', '_')}_"
    for name in model.model_fields:
        env_name = prefix + name.upper()
        if env_name in env:
            merged[name] = _env_value(env[env_name])
            provenance[name] = SRC_ENV
        nested = env_name + "__"
        for var in sorted(k for k in env if k.startswith(nested)):
            keys = [name, *var[len(nested) :].lower().split("__")]
            if not isinstance(merged.get(name), dict):
                merged[name] = {}
            _set_nested(merged, keys, _env_value(env[var]))
            provenance[name] = SRC_ENV

    resolved, secret_keys = _resolve_pointers(merged, secrets, env)
    for key in secret_keys:
        provenance[key] = SRC_SECRET

    try:
        values = model.model_validate(resolved)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise ConfigError(
            f"invalid config for '{extension}': {problems}",
            hint=f"check {shared} (or set {prefix}<KEY> env vars)",
        ) from exc
    return LoadedConfig(values=values, provenance=provenance, files=files, secret_keys=secret_keys)


def set_config_value(
    model: type[BaseModel],
    plugin: Plugin,
    extension: str,
    key: str,
    raw: str,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Persist one value into the extension's shared config file.

    Args:
        model: Config model, used to validate ``key`` and the value.
        plugin: Owning plugin.
        extension: Extension name.
        key: Config key to set.
        raw: New value; parsed as JSON when possible, else kept as a string.
        environ: Environment to read; defaults to ``os.environ``.

    Returns:
        The file that was written.

    Raises:
        ConfigError: The key is unknown or the value fails validation.
    """
    if key not in model.model_fields:
        raise ConfigError(
            f"unknown config key '{key}' for '{extension}'",
            hint=f"known: {', '.join(model.model_fields)}",
        )
    value = _coerce_env(raw)
    path, _ = config_paths(plugin, extension, environ)
    data = read_yaml_mapping(path) if path.is_file() else {}
    data[key] = value
    if not (_SECRET_RE.search(str(value)) or _ENV_RE.search(str(value))):
        try:
            model.model_validate(
                {**{k: v for k, v in data.items() if k != key}, key: value}, strict=False
            )
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                for e in exc.errors()
                if e["loc"] == (key,)
            )
            if problems:
                raise ConfigError(f"invalid value for '{key}': {problems}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True))
    return path
