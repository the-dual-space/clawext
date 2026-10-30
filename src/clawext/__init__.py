"""clawext — build agent-callable CLI extensions with shared config, secrets, skills and health checks."""

from __future__ import annotations

__version__ = "0.0.1"

from .adapter import main_for, to_click
from .context import Context
from .errors import (
    ClawextError,
    ConfigError,
    ExtensionError,
    SecretError,
    UnreachableError,
    UsageError,
    WrongHostError,
)
from .extension import Config, Extension, Needs, extension
from .plugin import Plugin
from .render import Output

__all__ = [
    "ClawextError",
    "Config",
    "ConfigError",
    "Context",
    "Extension",
    "ExtensionError",
    "Needs",
    "Output",
    "Plugin",
    "SecretError",
    "UnreachableError",
    "UsageError",
    "WrongHostError",
    "__version__",
    "extension",
    "main_for",
    "to_click",
]
