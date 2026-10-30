"""Test helpers for extension authors: run an extension's CLI in-process."""

from __future__ import annotations

from collections.abc import Callable

import click
from click.testing import CliRunner, Result

from .adapter import build_group
from .extension import Extension


def invoke(
    ext: Extension,
    *args: str,
    input: str | None = None,
    customize: Callable[[click.Group], None] | None = None,
    version: str | None = None,
) -> Result:
    """Run an extension's full CLI (commands plus free commands) and return the result.

    Args:
        ext: Extension to run.
        *args: Command line arguments after the program name (``"--json", "status"``).
        input: Text fed to standard input.
        customize: Hook to mount extra Click commands (see ``build_group``).
        version: Version string for ``--version``.

    Returns:
        The Click result with ``exit_code``, ``stdout`` and ``output``.
    """
    return CliRunner().invoke(
        build_group(ext, customize=customize, version=version), list(args), input=input
    )
