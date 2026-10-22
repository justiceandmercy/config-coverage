# Architecture

config-coverage — Audits configuration definitions against code usage to report unused, missing, shadowed, and mistyped settings across supported formats.

## Overview

The codebase is organized around a small set of focused modules. Each module owns a
single responsibility and the public surface is kept deliberately small so the tool
stays easy to hack on.

## Module map

| Path | Responsibility |
| ---- | -------------- |
| `src/main.py` | CLI entrypoint that parses global options, dispatches scan, diff, init, and report subcommands, and maps results to process exit codes. |
| `src/models.py` | Define immutable dataclasses for ConfigKey, Reference, Finding, ScanResult, and BaselineEntry with validation helpers. |
| `src/config_loader.py` | Load and normalize configuration definitions from TOML, YAML, JSON, .env templates, and Python dataclasses into ConfigKey objects. |
| `src/reference_scanner.py` | Walk source trees and extract configuration references using language ASTs with configurable regex fallback patterns. |
| `src/coverage_analyzer.py` | Compare discovered keys with observed references and classify unused, missing, shadowed, mistyped, and override findings. |
| `src/baseline.py` | Read, write, and apply baseline suppressions keyed by finding fingerprint and project-relative location. |
| `src/reporters.py` | Render findings as terminal, JSON, and SARIF reports with stable ordering, severity filtering, and remediation text. |
| `src/cache.py` | Persist parsed AST and configuration metadata caches keyed by file content hashes to reduce repeat scan time. |
| `tests/test_config_loader.py` | Unit tests for format detection, key normalization, type inference, and source location capture. |
| `tests/test_coverage_analyzer.py` | Unit tests for all finding classifications, severity assignment, and deterministic ordering. |
| `tests/test_cli_integration.py` | Integration tests that scan fixture repositories and assert exact findings, baseline behavior, and exit codes. |
| `pyproject.toml` | Package metadata, console script entry point, runtime dependencies, and pytest configuration. |
| `docs/usage.md` | Document installation, configuration schema, CLI commands, output formats, and CI integration. |

## Key design decisions

- **Zero/low runtime dependencies**: the core works from the standard library so
  installs stay fast and supply-chain risk stays low.
- **Configuration before convention**: behavior is tunable through config files and
  documented CLI flags instead of magic environment variables.
- **Structured output modes**: human-readable text by default, machine-readable JSON
  for automation, and DOT/Mermaid exports where a graph applies.
- **Everything is guarded by tests**: the CI matrix runs the suite on every push.

## Data flow

`CLI entrypoint -> config loading -> per-item scanning/processing -> aggregation ->
reporting (text | JSON | graph)`.

## Testing

Unit tests cover configuration loading, reference extraction, analyzer classifications, baseline suppression, reporters, and cache invalidation. Integration tests scan small fixture repositories containing known unused, missing, mistyped, and shadowed keys, then assert exact finding sets, baseline filtering, JSON and SARIF structure, and CLI exit codes.

Run them locally with `pytest -q`. CI (`.github/workflows/ci.yml`) executes the
same suite on a version matrix for every push and pull request.
