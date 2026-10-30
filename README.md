# clawext

Build agent-callable CLI tools as **extensions**: declare a few typed functions and get a
complete command line with `--json` output, stable exit codes, layered config, scoped
secrets, health checks, a generated `SKILL.md`, and an installable extension manager.

## An extension in a few lines

```python
from pathlib import Path

from clawext import Config, Context, Plugin, extension, main_for

# A plugin groups related extensions and owns their home folder (config, secrets, state).
# Skip `plugin=` for a standalone extension (home defaults to ~/.clawext).
PLUGIN = Plugin("mycli", home="~/.mycli", home_env="MYCLI_HOME")


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


main = main_for(app)  # [project.scripts] mycli-docs = "mypkg.cli:main"
```

Commands **return data**; the framework prints it (YAML for humans, JSON with `--json`
before or after the subcommand) and maps errors to exit codes:
`0` ok, `1` failure, `2` not configured or bad usage, `3` unreachable.

Every extension also gets `init`, `doctor`, `status`, `config show|set`, `schema` and
`skill` (generates `SKILL.md` following the Agent Skills standard).

## Parameters

The signature is the CLI. A parameter without a default is a positional argument, one with a
default is an `--option`, `bool` is a flag (`--no-x` when the default is `True`), `list[T]`
repeats, and `Literal[...]`/`Enum` become choices. The first parameter is the context when it is
named `ctx`/`context` or annotated `Context`; commands may also omit it. Help text comes from
the docstring `Args:` section; use markers when you need more:

```python
from typing import Annotated, Literal

from clawext import Arg, Opt


@app.command
def find(
    ctx: Context,
    pattern: str,  # positional
    where: Annotated[str | None, Arg()] = None,  # optional positional
    limit: Annotated[int, Opt("-n", help="Row limit")] = 10,  # -n / --limit
    mode: Literal["fast", "full"] = "fast",  # --mode {fast,full}
    *,
    name: Annotated[str, Opt(required=True)],  # required option (no default)
) -> list[dict[str, str]]:
    """Find things.

    Args:
        pattern: What to look for.
    """
```

`@app.command(destructive=True, exit_for=fn, hidden=True, aliases=["ls"])` adds a `--yes`
guard, maps the result to an exit code, hides the command, or adds alternative names. A
generator command streams: each yielded item is printed immediately (one JSON object per line
with `--json`). `ctx.log(msg, live=True)` writes to stderr at once; `ctx.stdin_text()` reads
piped input.

## Config values

- `${secret:name}` and `${env:VAR}` are expanded in any string, at any depth.
- Dict values merge key by key between `<ext>.yaml` and `<ext>.local.yaml`; an empty key
  (`retries:`) means "use the default".
- `<PLUGIN>_<EXT>_<KEY>__<SUB>__<LEAF>=value` overrides a nested value.

## Skills

`<cli> skill` renders the built-in Jinja template. To keep hand-written prose and still generate
the reference, ship a template and point the extension at it:
`extension(..., skill="skill/SKILL.md.j2")`. Variables: `name`, `description`, `about`, `cli`,
`conventions`, `commands_md`, `config_md`, `secrets`, `config`, `schema`. Undefined variables are
errors.

## Entry points and testing

`main_for(app, customize=fn, prog_name="x", version="1.0")` builds the console script;
`build_group(app, ...)` returns the Click group (mount your own sub-groups in `customize`).
`from clawext.testing import invoke` runs the full CLI in-process for tests.

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
