"""State classes: how an extension's persistent data is meant to be synced."""

from __future__ import annotations

from typing import Literal, get_args

StateClass = Literal["host", "git", "server-owned"]
"""host: never synced; git: versioned in a repo; server-owned: the server is the single writer."""

STATE_CLASSES: tuple[str, ...] = get_args(StateClass)

RunsOn = Literal["local", "server", "any"]
"""Where an extension is allowed to run."""

RUNS_ON_VALUES: tuple[str, ...] = get_args(RunsOn)
