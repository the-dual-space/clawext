"""Plugin identity: the home folder, machine role, and env-var namespace of a plugin."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class Plugin:
    """A named collection of extensions that share one home folder.

    Attributes:
        name: Lowercase plugin name (also the prefix of its env-var overrides).
        home: Default home folder (``~`` is expanded).
        home_env: Environment variable that overrides ``home``.
        role_env: Environment variable that holds the machine role (``LOCAL``/``SERVER``).
    """

    name: str
    home: str = "~/.clawext"
    home_env: str = "CLAWEXT_HOME"
    role_env: str = "MACHINE_ROLE"

    def __post_init__(self) -> None:
        """Validate the plugin name."""
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"invalid plugin name {self.name!r}: use lowercase letters, digits, '-'"
            )

    @property
    def env_prefix(self) -> str:
        """Return the upper-case prefix for this plugin's env-var overrides."""
        return self.name.upper().replace("-", "_")

    def home_dir(self, environ: Mapping[str, str] | None = None) -> Path:
        """Resolve the home folder.

        Args:
            environ: Environment to read; defaults to ``os.environ``.

        Returns:
            The expanded home path (not created).
        """
        env = os.environ if environ is None else environ
        raw = env.get(self.home_env) or self.home
        return Path(raw).expanduser()

    def state_dir(self, extension: str, environ: Mapping[str, str] | None = None) -> Path:
        """Return the state folder of one extension (not created).

        Args:
            extension: Extension name.
            environ: Environment to read; defaults to ``os.environ``.

        Returns:
            ``<home>/state/<extension>``.
        """
        return self.home_dir(environ) / "state" / extension

    def role(self, environ: Mapping[str, str] | None = None) -> str | None:
        """Return the machine role, upper-cased, or ``None`` when unset.

        Args:
            environ: Environment to read; defaults to ``os.environ``.

        Returns:
            For example ``"LOCAL"`` or ``"SERVER"``.
        """
        env = os.environ if environ is None else environ
        value = env.get(self.role_env, "").strip().upper()
        return value or None


DEFAULT_PLUGIN = Plugin("clawext")
