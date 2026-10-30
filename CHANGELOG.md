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

## [0.0.1] - 2026

### Added
- Initial project skeleton.
