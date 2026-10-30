"""Smoke test — the package imports and exposes a version string."""

from __future__ import annotations

import clawext


def test_package_imports() -> None:
    """The top-level package imports cleanly."""
    assert clawext is not None


def test_version_is_a_nonempty_string() -> None:
    """``__version__`` is exposed and is a non-empty string."""
    assert isinstance(clawext.__version__, str)
    assert clawext.__version__
