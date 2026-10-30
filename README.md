# clawext

Build agent-callable CLI tools as **extensions**: declare a few typed functions and get a
complete command line with `--json` output, stable exit codes, layered config, scoped
secrets, health checks, a generated `SKILL.md`, and an installable extension manager.

## An extension in a few lines

```python
from pathlib import Path

from clawext import Config, Context, Plugin, extension, main_for

PLUGIN = Plugin("tds", home="~/.tds", home_env="TDS_HOME")


class DocsConfig(Config):
    inbox: str = "~/Scans"


app = extension(
    "docs",
    "File personal documents with the right name.",
    plugin=PLUGIN,
    config=DocsConfig,
    secrets=["dropbox.token"],
    needs={"bins": ["sips"]},
    runs_on="local",
)


@app.command
def rename(ctx: Context, file: Path, dry_run: bool = False) -> dict[str, str]:
    """Rename FILE to YYYYMMDD_topic_detail.ext from its contents."""
    return {"file": str(file), "dry_run": str(dry_run)}


main = main_for(app)  # [project.scripts] tds-docs = "mypkg.cli:main"
```

Commands **return data**; the framework prints it (YAML for humans, JSON with `--json`
before or after the subcommand) and maps errors to exit codes:
`0` ok, `1` failure, `2` not configured or bad usage, `3` unreachable.

Every extension also gets `init`, `doctor`, `status`, `config show|set`, `schema` and
`skill` (generates `SKILL.md` following the Agent Skills standard).

## Config, secrets, state

- Precedence: env (`<PLUGIN>_<EXT>_<KEY>`) > `<ext>.local.yaml` > `<ext>.yaml` > defaults;
  `config show` reports which layer won.
- Secrets live only in `<home>/secrets.yaml` (chmod 600) and are referenced as
  `${secret:dotted.name}`. An extension can read only the secrets it declared, and values
  are redacted from output and logs.
- `runs_on` (`local`/`server`/`any`) refuses to run on the wrong machine (`MACHINE_ROLE`).

## Discovery and the extension manager

Extensions register an entry point in the group `clawext.extensions`:

```toml
[project.entry-points."clawext.extensions"]
docs = "mypkg.cli:app"
```

`clawext` (or a plugin hub built with `clawext.cli.build_hub`) mounts every installed
extension and offers `ext list|install|update|remove|sync|doctor`, a thin wrapper over
uv/pip driven by an `extensions.yaml` manifest.

## Development

Driven by [pyclawd](https://github.com/anyoptimization/pyclawd); `pyclawd check` is the gate
(ruff, mypy strict, pytest).

## License

Apache-2.0 — see [LICENSE](LICENSE).
