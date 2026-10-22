# config-coverage

[![CI](https://github.com/justiceandmercy/config-coverage/actions/workflows/ci.yml/badge.svg)](https://github.com/justiceandmercy/config-coverage/actions/workflows/ci.yml)


> Audits configuration definitions against code usage to report unused, missing, shadowed, and mistyped settings across supported formats.

[![CI](https://github.com/justiceandmercy/config-coverage/actions/workflows/ci.yml/badge.svg)](https://github.com/justiceandmercy/config-coverage/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Topics:** cli, configuration, static-analysis, developer-tools, python, audit

## Features

- Discover configuration keys from TOML, YAML, JSON, .env templates, and Python dataclass settings with source locations.
- Scan Python and JavaScript source using AST-aware references plus configurable regex fallbacks for dynamic key access.
- Report unused configuration keys, missing required keys, type mismatches, and environment-only overrides with severity levels.
- Support baseline files to suppress known findings and fail CI only on new regressions.
- Generate JSON, SARIF, and terminal reports with file and line evidence plus remediation hints.
- Respect .gitignore and include or exclude globs, with deterministic sorted output for reproducible CI.
- Validate cross-file references such as environment variable names derived from settings prefixes.
- Provide an init command to scaffold a starter config-coverage.toml from detected project conventions.
- Cache parsed ASTs and configuration metadata to speed repeated scans in large repositories.
- Return distinct exit codes for findings, configuration errors, and successful clean scans.

## Install

git clone https://github.com/justiceandmercy/config-coverage.git
cd config-coverage
pip install .

## Quick start

config-coverage --help

Entry point: `src/main.py`.

## Architecture

- `src/main.py` — CLI entrypoint that parses global options, dispatches scan, diff, init, and report subcommands, and maps results to process exit codes.
- `src/models.py` — Define immutable dataclasses for ConfigKey, Reference, Finding, ScanResult, and BaselineEntry with validation helpers.
- `src/config_loader.py` — Load and normalize configuration definitions from TOML, YAML, JSON, .env templates, and Python dataclasses into ConfigKey objects.
- `src/reference_scanner.py` — Walk source trees and extract configuration references using language ASTs with configurable regex fallback patterns.
- `src/coverage_analyzer.py` — Compare discovered keys with observed references and classify unused, missing, shadowed, mistyped, and override findings.
- `src/baseline.py` — Read, write, and apply baseline suppressions keyed by finding fingerprint and project-relative location.
- `src/reporters.py` — Render findings as terminal, JSON, and SARIF reports with stable ordering, severity filtering, and remediation text.
- `src/cache.py` — Persist parsed AST and configuration metadata caches keyed by file content hashes to reduce repeat scan time.
- `tests/test_config_loader.py` — Unit tests for format detection, key normalization, type inference, and source location capture.
- `tests/test_coverage_analyzer.py` — Unit tests for all finding classifications, severity assignment, and deterministic ordering.
- `tests/test_cli_integration.py` — Integration tests that scan fixture repositories and assert exact findings, baseline behavior, and exit codes.
- `pyproject.toml` — Package metadata, console script entry point, runtime dependencies, and pytest configuration.
- `docs/usage.md` — Document installation, configuration schema, CLI commands, output formats, and CI integration.

For the full module map and design decisions, read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Testing

pytest -q

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome!

## License

MIT — see [LICENSE](LICENSE).
