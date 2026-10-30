# clawext roadmap

## Done
- Extension declaration, Click adapter, error envelope, exit codes
- Layered config with provenance, scoped/redacted secrets, state classes, `runs_on`
- Free commands: init, doctor, status, config show|set, schema, skill
- Entry-point discovery, `ext` manager, lazy hub (`build_hub`)
- Param markers (`Opt`/`Arg`), docstring help, choices, optional ctx, `build_group`, Jinja skills

## Next
- Config: `${env:VAR}`, `__` nested env overrides, deep merge of dict keys, null -> default
- Context: streaming/live logging, `ctx.stdin_text()`, generator commands
- Plugin-level short skill names; generated-file marker in skills
- Builtin name clash handling (`ext-<name>`), command aliases
- `clawext.testing.invoke` helper for extension authors
- MCP adapter (decide default exposure first: read-only commands exposed, destructive opt-in)
- `plugin check|upgrade` to propagate structure changes
- Docs: README update for markers, `main_for` options, skill templates

## Rules for changes
- Add a test with every behaviour change; keep `pyclawd check` green before committing.
- Public API changes go in CHANGELOG.md.
