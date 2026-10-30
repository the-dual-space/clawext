"""Secrets: a private YAML file read through per-extension scoped access."""

from __future__ import annotations

import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError, SecretMissingError, SecretNotDeclaredError


class SecretStore:
    """Read-only view of the secrets file (``<home>/secrets.yaml``)."""

    def __init__(self, path: Path) -> None:
        """Bind the store to a file; it is read lazily.

        Args:
            path: Location of the secrets YAML file.
        """
        self.path = path
        self._data: dict[str, Any] | None = None

    def exists(self) -> bool:
        """Return whether the secrets file exists."""
        return self.path.is_file()

    def is_private(self) -> bool:
        """Return whether the file is unreadable by group and others (or absent)."""
        if not self.exists():
            return True
        return not (self.path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))

    def _load(self) -> dict[str, Any]:
        if self._data is None:
            if not self.exists():
                self._data = {}
            else:
                try:
                    loaded = yaml.safe_load(self.path.read_text()) or {}
                except yaml.YAMLError as exc:
                    raise ConfigError(f"{self.path}: invalid YAML ({exc})") from exc
                if not isinstance(loaded, dict):
                    raise ConfigError(f"{self.path}: expected a mapping at the top level")
                self._data = loaded
        return self._data

    def lookup(self, dotted: str) -> str | None:
        """Look up ``a.b.c`` in the nested secrets mapping.

        Args:
            dotted: Dotted secret name, for example ``dropbox.token``.

        Returns:
            The value as a string, or ``None`` when absent or empty.
        """
        node: Any = self._load()
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        if node is None or isinstance(node, dict | list):
            return None
        text = str(node)
        return text or None


class ScopedSecrets:
    """Secret access limited to the names an extension declared."""

    def __init__(self, store: SecretStore, declared: Iterable[str], extension: str) -> None:
        """Create the scoped view.

        Args:
            store: The underlying secrets file.
            declared: Secret names the extension declared.
            extension: Extension name (used in error messages).
        """
        self._store = store
        self.declared: tuple[str, ...] = tuple(declared)
        self._extension = extension
        self.resolved: list[str] = []

    @property
    def store(self) -> SecretStore:
        """Return the underlying secrets file (for health checks and ``init``)."""
        return self._store

    def has(self, name: str) -> bool:
        """Return whether a declared secret has a value.

        Args:
            name: Dotted secret name.

        Returns:
            ``True`` when the name is declared and set.
        """
        return name in self.declared and self._store.lookup(name) is not None

    def get(self, name: str) -> str:
        """Return a declared secret's value.

        Args:
            name: Dotted secret name.

        Returns:
            The secret value.

        Raises:
            SecretNotDeclaredError: The extension did not declare ``name``.
            SecretMissingError: The secret is declared but not set.
        """
        if name not in self.declared:
            raise SecretNotDeclaredError(
                f"extension '{self._extension}' did not declare secret '{name}'",
                hint=f"add {name!r} to secrets=[...] in the extension declaration",
            )
        value = self._store.lookup(name)
        if value is None:
            raise SecretMissingError(
                f"secret '{name}' is not set (needed by '{self._extension}')",
                hint=f"add it to {self._store.path} (key path: {name})",
            )
        if value not in self.resolved:
            self.resolved.append(value)
        return value
