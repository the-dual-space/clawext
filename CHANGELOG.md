# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this
project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `extension()` declaration with typed commands, a Click adapter (`--json` before or
  after the subcommand, exit codes 0/1/2/3, JSON error envelope) and `main_for`.
- Layered config with provenance, `${secret:...}` pointers, scoped and redacted secrets,
  `runs_on` placement guard, destructive-command `--yes`, audit log.
- Free commands: `init`, `doctor`, `status`, `config show|set`, `schema`, `skill`.
- SKILL.md generation validated against the Agent Skills limits.
- Entry-point discovery (`clawext.extensions`), extension manager and `extensions.yaml`
  sync, and the `clawext` hub CLI.

- `Opt`/`Arg` parameter markers, `Literal`/`Enum` choices, docstring `Args:` help, optional
  `ctx`, `aliases=`, `hidden=`, `exit_for=`; one `ParamSpec` feeds CLI, schema and skill.
- Jinja skill templates (`extension(skill=...)`), generated marker, parameter tables.
- Config: `${env:VAR}`, nested `__` env overrides, deep merge, empty key means default.
- Generator commands stream; `ctx.log(live=True)`, `ctx.stdin_text()`.
- `build_group`, `main_for(customize=, prog_name=, version=)`, `clawext.testing.invoke`.

### Fixed
- Required options stay required on Click >= 8.5; non-destructive commands can declare `yes`.
- A command named like a free command wins; the free one is reachable as `ext-<name>`.

## [0.0.1] - 2026

### Added
- Initial project skeleton.
