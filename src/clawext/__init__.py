"""clawext — build agent-callable CLI extensions with shared config, secrets, skills and health checks."""

from __future__ import annotations

__version__ = "0.0.1"

from .adapter import build_group, main_for, to_click
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
from .params import Arg, Opt
from .plugin import Plugin
from .render import Output

__all__ = [
    "Arg",
    "ClawextError",
    "Config",
    "ConfigError",
    "Context",
    "Extension",
    "ExtensionError",
    "Needs",
    "Opt",
    "Output",
    "Plugin",
    "SecretError",
    "UnreachableError",
    "UsageError",
    "WrongHostError",
    "__version__",
    "build_group",
    "extension",
    "main_for",
    "to_click",
]
