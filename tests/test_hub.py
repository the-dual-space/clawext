"""Tests for discovery, the extension manager, and the hub CLI."""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib.metadata import EntryPoint
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from clawext import Extension, extension, manager
from clawext.cli import build_hub, main
from clawext.discovery import GROUP, discover, load_entry_point
from clawext.errors import ExtensionError

from .conftest import PLUGIN

pytestmark = pytest.mark.usefixtures("isolated")

SAMPLE_EXT = extension("alpha", "Alpha tool.", plugin=PLUGIN)


@SAMPLE_EXT.command
def ping(ctx: object) -> str:
    """Ping."""
    return "pong"


def make_ep(name: str, value: str) -> EntryPoint:
    """Create an entry point in the clawext group."""
    return EntryPoint(name=name, value=value, group=GROUP)


def alpha_factory() -> Extension:
    """Return the sample extension (used as a callable entry point)."""
    return SAMPLE_EXT


NOT_AN_EXTENSION = 42


def test_load_entry_point_accepts_extension_or_factory() -> None:
    """Both an Extension object and a factory callable load."""
    assert load_entry_point(make_ep("alpha", "tests.test_hub:SAMPLE_EXT")) is SAMPLE_EXT
    assert load_entry_point(make_ep("alpha", "tests.test_hub:alpha_factory")) is SAMPLE_EXT


def test_load_entry_point_errors() -> None:
    """Broken targets raise ExtensionError with the entry name."""
    with pytest.raises(ExtensionError, match="cannot load"):
        load_entry_point(make_ep("x", "no_such_module_xyz:thing"))
    with pytest.raises(ExtensionError, match="did not provide"):
        load_entry_point(make_ep("x", "tests.test_hub:NOT_AN_EXTENSION"))


def test_discover_reports_failures_and_duplicates() -> None:
    """Failures and duplicates are reported instead of raised."""
    eps = [
        make_ep("alpha", "tests.test_hub:SAMPLE_EXT"),
        make_ep("alpha", "tests.test_hub:alpha_factory"),
        make_ep("broken", "no_such_module_xyz:thing"),
    ]
    results = {(d.entry, d.error is None) for d in discover(eps)}
    assert ("broken", False) in results
    assert ("alpha", True) in results
    assert ("alpha", False) in results


def hub_for_sample(**kwargs: object) -> object:
    """Build a hub holding the sample extension."""
    results = discover([make_ep("alpha", "tests.test_hub:SAMPLE_EXT")])
    return build_hub("demo", discovered=results, **kwargs)  # type: ignore[arg-type]


def test_hub_exposes_extensions_and_free_commands() -> None:
    """The hub mounts each extension with its commands and builtins."""
    hub = hub_for_sample()
    result = CliRunner().invoke(hub, ["alpha", "ping"])  # type: ignore[arg-type]
    assert result.stdout.strip() == "pong"
    result = CliRunner().invoke(hub, ["alpha", "--json", "status"])  # type: ignore[arg-type]
    assert json.loads(result.stdout)["name"] == "alpha"


def test_hub_plugin_filter() -> None:
    """A plugin hub shows only its own extensions."""
    results = discover([make_ep("alpha", "tests.test_hub:SAMPLE_EXT")])
    other = build_hub("other", plugin=PLUGIN.__class__("other"), discovered=results)
    assert "alpha" not in other.list_commands(click.Context(other))
    mine = build_hub("mine", plugin=PLUGIN, discovered=results)
    assert "alpha" in mine.list_commands(click.Context(mine))


def test_hub_skips_broken_extensions() -> None:
    """Entries that failed to load do not appear in the hub."""
    results = discover([make_ep("broken", "no_such_module_xyz:thing")])
    hub = build_hub("demo", discovered=results)
    assert "broken" not in hub.list_commands(click.Context(hub))


class FakeRunner:
    """Records commands instead of running them."""

    def __init__(self, code: int = 0) -> None:
        """Create the runner with a fixed exit code."""
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, argv: Sequence[str]) -> int:
        """Record ``argv`` and return the configured code."""
        self.calls.append(list(argv))
        return self.code


def test_install_builds_the_right_command(tmp_path: Path) -> None:
    """Local directories install editable; names and URLs do not."""
    runner = FakeRunner()
    manager.install(str(tmp_path), runner=runner)
    assert "-e" in runner.calls[-1] and runner.calls[-1][-1] == str(tmp_path)
    manager.install("mypkg-docs", runner=runner)
    assert "-e" not in runner.calls[-1] and runner.calls[-1][-1] == "mypkg-docs"
    manager.install("mypkg-docs", editable=True, runner=runner)
    assert "-e" in runner.calls[-1]


def test_manager_failures_raise() -> None:
    """A non-zero installer exit becomes ExtensionError."""
    bad = FakeRunner(code=1)
    for call in (
        lambda: manager.install("x", runner=bad),
        lambda: manager.update("x", runner=bad),
        lambda: manager.remove("x", runner=bad),
    ):
        with pytest.raises(ExtensionError):
            call()


def test_update_and_remove_commands() -> None:
    """Update upgrades; remove uninstalls."""
    runner = FakeRunner()
    manager.update("dist", runner=runner)
    assert "--upgrade" in runner.calls[-1]
    manager.remove("dist", runner=runner)
    assert "uninstall" in runner.calls[-1] and runner.calls[-1][-1] == "dist"


def test_manifest_roundtrip_and_validation(tmp_path: Path) -> None:
    """Manifests accept strings and mappings; bad shapes are rejected."""
    path = tmp_path / "extensions.yaml"
    manager.write_manifest(path, [{"name": "a", "source": "git+https://example.invalid/a"}])
    assert manager.read_manifest(path) == [{"name": "a", "source": "git+https://example.invalid/a"}]
    path.write_text("extensions:\n  - plain\n  - {name: b}\n")
    assert manager.read_manifest(path) == [
        {"name": "plain", "source": "plain"},
        {"name": "b", "source": "b"},
    ]
    path.write_text("extensions: nope\n")
    with pytest.raises(ExtensionError):
        manager.read_manifest(path)
    path.write_text("extensions:\n  - [1]\n")
    with pytest.raises(ExtensionError, match="invalid entry"):
        manager.read_manifest(path)
    with pytest.raises(ExtensionError, match="not found"):
        manager.read_manifest(tmp_path / "missing.yaml")


def test_sync_installs_only_missing(tmp_path: Path) -> None:
    """Sync skips installed extensions and honours dry-run."""
    path = tmp_path / "extensions.yaml"
    manager.write_manifest(
        path, [{"name": "have_it", "source": "have_it"}, {"name": "need", "source": "need"}]
    )
    runner = FakeRunner()
    dry = manager.sync(path, installed={"have-it"}, runner=runner, dry_run=True)
    assert dry == {"installed": ["need"], "present": ["have_it"]}
    assert runner.calls == []
    done = manager.sync(path, installed={"have-it"}, runner=runner)
    assert done["installed"] == ["need"]
    assert runner.calls[-1][-1] == "need"


def test_installed_extensions_is_a_list() -> None:
    """Listing installed extensions returns well-formed rows."""
    for row in manager.installed_extensions():
        assert {"dist", "version", "entries"} <= set(row)


def test_installer_prefix_prefers_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    """uv is used when present, pip otherwise."""
    monkeypatch.setattr("clawext.manager.shutil.which", lambda _: "/usr/bin/uv")
    assert manager.installer_prefix()[0] == "uv"
    monkeypatch.setattr("clawext.manager.shutil.which", lambda _: None)
    assert manager.installer_prefix()[1:] == ["-m", "pip"]


def test_ext_commands_via_hub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The ``ext`` group wires through to the manager."""
    runner = FakeRunner()
    monkeypatch.setattr("clawext.manager.run_subprocess", runner)
    monkeypatch.setattr(
        manager, "install", lambda source, editable=None, runner=runner: runner(["install", source])
    )
    hub = build_hub("demo", plugin=PLUGIN, discovered=[])
    cli = CliRunner()
    ok = cli.invoke(hub, ["ext", "install", "somepkg", "--json"])
    assert json.loads(ok.stdout) == {"installed": "somepkg"}
    no_yes = cli.invoke(hub, ["ext", "remove", "somepkg"])
    assert no_yes.exit_code == 2
    manifest = tmp_path / "m.yaml"
    manager.write_manifest(manifest, [{"name": "zzz-not-installed", "source": "zzz"}])
    sync = cli.invoke(hub, ["ext", "sync", "--manifest", str(manifest), "--dry-run", "--json"])
    assert json.loads(sync.stdout)["installed"] == ["zzz-not-installed"]
    missing = cli.invoke(hub, ["ext", "sync", "--manifest", str(tmp_path / "nope.yaml"), "--json"])
    assert missing.exit_code == 1
    assert json.loads(missing.stdout)["error"]["type"] == "extension"


def test_ext_list_update_remove_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    """List, update, remove and doctor run through the hub."""
    calls: list[str] = []
    monkeypatch.setattr(manager, "update", lambda dist, runner=None: calls.append(f"update {dist}"))
    monkeypatch.setattr(manager, "remove", lambda dist, runner=None: calls.append(f"remove {dist}"))
    monkeypatch.setattr("clawext.cli.discover", lambda: [])
    hub = build_hub("demo", plugin=PLUGIN, discovered=[])
    cli = CliRunner()
    assert cli.invoke(hub, ["ext", "update", "d", "--json"]).exit_code == 0
    assert cli.invoke(hub, ["ext", "remove", "d", "--yes", "--json"]).exit_code == 0
    assert calls == ["update d", "remove d"]
    listed = cli.invoke(hub, ["ext", "list", "--json"])
    assert isinstance(json.loads(listed.stdout), list)
    doctor = cli.invoke(hub, ["ext", "doctor", "--json"])
    assert json.loads(doctor.stdout)["ok"] is True


def test_ext_doctor_fails_on_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    """Doctor exits 1 when any extension fails to load."""
    broken = discover([make_ep("broken", "no_such_module_xyz:thing")])
    monkeypatch.setattr("clawext.cli.discover", lambda *a, **k: broken)
    hub = build_hub("demo", plugin=PLUGIN, discovered=[])
    result = CliRunner().invoke(hub, ["ext", "doctor", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["extensions"][0]["entry"] == "broken"


def test_main_runs_the_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main`` builds the hub and runs it."""
    monkeypatch.setattr("sys.argv", ["clawext", "--version"])
    with pytest.raises(SystemExit) as info:
        main()
    assert info.value.code == 0


def test_hub_level_json_reaches_extensions() -> None:
    """``hub --json ext cmd`` and ``hub ext --json cmd`` both produce JSON."""
    hub = hub_for_sample()
    before = CliRunner().invoke(hub, ["--json", "alpha", "ping"])  # type: ignore[arg-type]
    after = CliRunner().invoke(hub, ["alpha", "--json", "ping"])  # type: ignore[arg-type]
    assert json.loads(before.stdout) == json.loads(after.stdout) == "pong"


def test_hub_fallback_and_extra_names() -> None:
    """Unknown subcommands go to the fallback; its names show up in listings."""

    @click.command("legacy")
    def legacy() -> None:
        """Legacy passthrough."""
        click.echo("from legacy")

    hub = build_hub(
        "demo",
        plugin=PLUGIN,
        discovered=[],
        fallback=lambda name: legacy if name == "legacy" else None,
        extra_names=lambda: ["legacy"],
    )
    assert CliRunner().invoke(hub, ["legacy"]).stdout.strip() == "from legacy"
    assert "legacy" in hub.list_commands(click.Context(hub))
    assert CliRunner().invoke(hub, ["nope"]).exit_code == 2


def test_hub_loads_entry_points_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the requested extension is imported; listing loads the rest."""
    loaded: list[str] = []
    real = load_entry_point

    def tracking(ep: EntryPoint) -> Extension:
        loaded.append(ep.name)
        return real(ep)

    eps = [
        make_ep("alpha", "tests.test_hub:SAMPLE_EXT"),
        make_ep("other", "tests.test_hub:SAMPLE_EXT"),
    ]
    monkeypatch.setattr("clawext.cli.load_entry_point", tracking)
    monkeypatch.setattr(
        "clawext.cli.entry_points",
        lambda group, name=None: [e for e in eps if name is None or e.name == name],
    )
    hub = build_hub("demo")
    assert CliRunner().invoke(hub, ["alpha", "ping"]).stdout.strip() == "pong"
    assert loaded == ["alpha"]
    hub.list_commands(click.Context(hub))
    assert sorted(loaded) == ["alpha", "other"]


def test_hub_reports_broken_extension_on_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken extension fails with a clear message only when it is used."""
    eps = [make_ep("broken", "no_such_module_xyz:thing")]
    monkeypatch.setattr(
        "clawext.cli.entry_points",
        lambda group, name=None: [e for e in eps if name is None or e.name == name],
    )
    result = CliRunner().invoke(build_hub("demo"), ["broken"])
    assert result.exit_code == 1
    assert "cannot load 'broken'" in result.stderr


def test_hub_version_flag() -> None:
    """``--version`` prints the clawext version."""
    result = CliRunner().invoke(build_hub("demo", discovered=[]), ["--version"])
    assert result.stdout.startswith("clawext ")
