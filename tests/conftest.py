"""Shared fixtures: an isolated plugin home and a sample extension."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawext import Config, Context, Extension, Plugin, extension

PLUGIN = Plugin("demo", home="~/.demo", home_env="DEMO_HOME")


class DemoConfig(Config):
    """Config model used by the sample extension."""

    inbox: str = "in"
    retries: int = 3
    token: str = ""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Return an empty plugin home folder."""
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def env(home: Path) -> dict[str, str]:
    """Return an isolated environment pointing the plugin home at ``home``."""
    return {"DEMO_HOME": str(home), "MACHINE_ROLE": "LOCAL"}


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> dict[str, str]:
    """Apply ``env`` to ``os.environ`` for CLI tests and return it."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DEMO_SAMPLE_RETRIES", raising=False)
    return env


@pytest.fixture
def sample() -> Extension:
    """Return a sample extension with a few commands."""
    app = extension(
        "sample",
        "A sample extension.",
        plugin=PLUGIN,
        config=DemoConfig,
        secrets=["svc.token"],
        needs={"bins": ["sh"], "python": ["json"]},
    )

    @app.command
    def hello(ctx: Context, name: str, times: int = 1, loud: bool = False) -> dict[str, object]:
        """Greet NAME."""
        ctx.log("greeting")
        text = f"hello {name}"
        return {"greeting": (text.upper() if loud else text), "times": times}

    @app.command
    def boom(ctx: Context) -> None:
        """Always fail."""
        raise RuntimeError("kaboom")

    @app.command
    def reveal(ctx: Context) -> str:
        """Return a secret (to prove redaction)."""
        return f"token={ctx.secret('svc.token')}"

    @app.command(destructive=True)
    def wipe(ctx: Context, target: str) -> dict[str, str]:
        """Delete TARGET."""
        return {"wiped": target}

    @app.command
    def tags(ctx: Context, items: list[str], limit: int | None = None) -> dict[str, object]:
        """Echo ITEMS."""
        return {"items": items, "limit": limit}

    return app


@pytest.fixture
def plugin_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the default plugin home at a temporary folder."""
    monkeypatch.setenv("CLAWEXT_HOME", str(tmp_path / "home"))
