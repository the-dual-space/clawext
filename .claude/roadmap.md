# clawext roadmap

## Done
- Extension declaration, Click adapter, error envelope, exit codes
- Layered config with provenance, scoped/redacted secrets, state classes, `runs_on`
- Free commands: init, doctor, status, config show|set, schema, skill
- Entry-point discovery, `ext` manager, lazy hub (`build_hub`)
- Param markers (`Opt`/`Arg`), docstring help, choices, optional ctx, `build_group`, Jinja skills
- Config pointers/overrides/deep merge, streaming commands, live log, stdin, aliases, testing helper

## Next
- MCP adapter (decide default exposure first: read-only commands exposed, destructive opt-in)
- `plugin check|upgrade` to propagate structure changes

## Rules for changes
- Add a test with every behaviour change; keep `pyclawd check` green before committing.
- Public API changes go in CHANGELOG.md.
