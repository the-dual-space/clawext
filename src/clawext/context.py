"""Runtime context handed to every command: config, scoped secrets, state, redaction."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import LoadedConfig
from .plugin import Plugin
from .secrets import ScopedSecrets

REDACTED = "***"


def redact(text: str, secret_values: Iterable[str]) -> str:
    """Replace every known secret value in ``text``.

    Args:
        text: Text that may contain secrets.
        secret_values: Secret values resolved during this run.

    Returns:
        The text with secrets replaced by ``***``.
    """
    for value in sorted(secret_values, key=len, reverse=True):
        if value:
            text = text.replace(value, REDACTED)
    return text


@dataclass
class Context:
    """Everything a command may touch; created once per invocation.

    Attributes:
        extension: Name of the running extension.
        plugin: Plugin the extension belongs to.
        loaded: Layered config with provenance.
        secrets: Secret access limited to the declared names.
        environ: Environment the run was started with.
        json_mode: Whether the caller asked for JSON output.
        messages: Diagnostics emitted through ``log`` (written to stderr by the CLI).
    """

    extension: str
    plugin: Plugin
    loaded: LoadedConfig
    secrets: ScopedSecrets
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    json_mode: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def config(self) -> Any:
        """Return the validated config model (``None`` when the extension has none)."""
        return self.loaded.values

    def secret(self, name: str) -> str:
        """Return a declared secret.

        Args:
            name: Dotted secret name declared by the extension.

        Returns:
            The secret value.
        """
        return self.secrets.get(name)

    @property
    def home(self) -> Path:
        """Return the plugin home folder."""
        return self.plugin.home_dir(self.environ)

    def state_dir(self) -> Path:
        """Return this extension's state folder, creating it on first use.

        Returns:
            ``<home>/state/<extension>``.
        """
        path = self.plugin.state_dir(self.extension, self.environ)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def log(self, message: str) -> None:
        """Record a diagnostic line (secrets redacted); shown on stderr, never in the result.

        Args:
            message: Text to record.
        """
        self.messages.append(redact(message, self.secrets.resolved))
