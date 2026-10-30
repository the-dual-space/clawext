# clawext design notes

Decisions that are not obvious from the code. Update when they change.

## Shape
- One declaration (`extension(...)` + `@app.command` functions) feeds every adapter: CLI (Click),
  `schema`, generated skill, and later MCP. Never describe a parameter twice.
- `params.py` is the single source for parameters (`ParamSpec`): signature + `Annotated[T, Opt(...)/Arg(...)]`
  + docstring `Args:` help. Adapter, schema and skill all read it.
- Commands RETURN data. They never print or exit. `Output(data, text)` customises human text,
  `exit_for=` maps a result to a non-error exit code.
- Core logic stays framework-free in the extension's own `core` module; `cli.py` is only the declaration.

## Contracts (do not break without a major version)
- Exit codes: 0 ok, 1 failure, 2 not configured / bad usage, 3 target unreachable.
- `--json` works before or after the subcommand (flag lives in `click.Context.meta["clawext.json"]`).
- Errors in JSON mode are an envelope: `{"error": {"code", "type", "message", "hint"}}`.
- Config precedence: env > local file > shared file > defaults; `config show` reports the winning layer.
- Secrets are only `${secret:...}` pointers, scoped to what the extension declared, redacted from output
  and audit log. No secret values in repos, docs or tests.
- Destructive commands need `--yes`. A command may declare its own `yes` parameter.

## Skills
- Generated from a Jinja template (`skill.md.j2`). An extension may ship its own template via
  `extension(..., skill="skill/SKILL.md.j2")`: hand-written prose plus generated blocks
  (`commands_md`, `config_md`, `secrets`, `schema`). Undefined variables are errors.

## Dependencies
click, pydantic, pyyaml, packaging, jinja2. Deliberately no pydantic-settings (manual layering for
provenance) and no resolver or registry (the `ext` manager wraps uv/pip).
