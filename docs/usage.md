# config-coverage Usage

`config-coverage` audits configuration definitions against code usage. It reports unused keys, missing required keys, type mismatches, shadowed settings, and environment-only overrides with file and line evidence.

## Installation

Install from PyPI:

```bash
python -m pip install config-coverage
```

Install in a project for development:

```bash
python -m pip install -e .
```

The package installs the `config-coverage` console script. Verify it with:

```bash
config-coverage version
```

## Quick Start

Create a starter configuration file from detected project conventions:

```bash
config-coverage init
```

Run a scan:

```bash
config-coverage scan
```

Write a SARIF report for CI:

```bash
config-coverage scan --format sarif --output reports/config-coverage.sarif
```

## Configuration File

By default, `config-coverage` reads `config-coverage.toml` in the project root. Use `--config` to select another file. The `init` command creates a starter file with detected conventions.

### Schema

```toml
[project]
root = "."
respect_gitignore = true
include = ["**/*"]
exclude = [".git", "node_modules", ".venv", "dist", "build"]
baseline = ".config-coverage/baseline.json"
cache_dir = ".config-coverage/cache"

[definitions]
toml = ["pyproject.toml", "config/*.toml"]
yaml = ["config/*.yaml", "config/*.yml"]
json = ["config/*.json", "package.json"]
env = [".env.example", ".env.template", ".env.sample"]
python_dataclasses = ["src/settings.py", "src/**/config.py"]

[scan]
languages = ["python", "javascript"]
regex_fallback = true
dynamic_patterns = ["config.get({key})", "process.env[{key}]"]
severity = "warning"
fail_on = "new"

[report]
format = "terminal"
output = "-"
color = "auto"
hints = true
```

### Section Reference

- `[project]`: Project root, include/exclude globs, `.gitignore` handling, baseline path, and cache directory.
- `[definitions]`: Files and modules that define configuration keys. Patterns are repository-relative globs.
- `[scan]`: Source languages, regex fallback behavior, dynamic access patterns, minimum severity, and CI failure policy.
- `[report]`: Output format, destination, color behavior, and remediation hint display.

Globs use standard `*`, `**`, and `?` matching. Results are sorted deterministically by path and line number.

## CLI Commands

### `config-coverage init`

Scaffold `config-coverage.toml` from detected project conventions.

```bash
config-coverage init [ROOT] [--config PATH] [--force]
```

Options:

- `ROOT`: Project root to inspect. Defaults to the current directory.
- `--config`: Output configuration path. Defaults to `config-coverage.toml`.
- `--force`: Overwrite an existing configuration file.

### `config-coverage scan`

Audit definitions against source usage.

```bash
config-coverage scan [ROOT] [OPTIONS]
```

Options:

- `--config PATH`: Configuration file to load.
- `--format FORMAT`: `terminal`, `json`, or `sarif`.
- `--output PATH`: Report destination. Use `-` for stdout.
- `--baseline PATH`: Override the configured baseline file.
- `--fail-on POLICY`: `never`, `findings`, `new`, or `errors`.
- `--severity LEVEL`: Minimum severity to report: `info`, `warning`, or `error`.
- `--include GLOB`: Additional include glob. May be repeated.
- `--exclude GLOB`: Additional exclude glob. May be repeated.
- `--no-cache`: Disable AST and metadata caching for this run.
- `--refresh-cache`: Rebuild cache entries even when they appear valid.

### `config-coverage baseline update`

Regenerate the baseline from the current findings.

```bash
config-coverage baseline update [--config PATH] [--output PATH]
```

### `config-coverage cache clear`

Remove cached ASTs and configuration metadata.

```bash
config-coverage cache clear [--config PATH]
```

### `config-coverage version`

Print the installed version.

## Exit Codes

- `0`: Scan completed and no failing findings were found.
- `1`: Findings were reported according to the active failure policy.
- `2`: Configuration, input, or invocation error.

Use these codes in CI to distinguish a clean scan from a regression or setup problem.

## Findings

Each finding includes a rule, severity, message, evidence locations, and a remediation hint.

| Rule | Meaning |
| --- | --- |
| `unused-key` | A defined key is not referenced by scanned source. |
| `missing-required` | A required key has no definition or value. |
| `type-mismatch` | A value or default does not match the declared type. |
| `shadowed-setting` | A setting is overridden in a way that hides another definition. |
| `env-only-override` | A value exists only through an environment override. |

Severity levels are `info`, `warning`, and `error`.

## Baselines

Baseline files suppress known findings so CI can fail only on new regressions. A finding is matched by rule, key, and normalized location. Findings present in the baseline are reported as suppressed unless `--fail-on findings` is used.

Create or refresh a baseline:

```bash
config-coverage baseline update
```

Commit the baseline file to version control. Review baseline changes in pull requests.

## Output Formats

### Terminal

The terminal report groups findings by severity and shows evidence as `path:line:column`. Colors are enabled automatically when writing to a terminal.

### JSON

JSON output is stable and sorted. A report has this shape:

```json
{
  "schema_version": "1.0",
  "summary": {
    "findings": 2,
    "errors": 1,
    "warnings": 1,
    "info": 0,
    "suppressed": 3
  },
  "findings": [
    {
      "id": "unused-key:DATABASE_URL",
      "rule": "unused-key",
      "severity": "warning",
      "message": "Configuration key is defined but never used.",
      "locations": [{"path": "config/settings.py", "line": 12, "column": 1}],
      "evidence": ["src/app.py:45:10"],
      "hint": "Remove the key or add a reference."
    }
  ]
}
```

### SARIF

SARIF output follows SARIF 2.1.0 and can be uploaded to GitHub code scanning. Each finding becomes a result with physical locations and, when available, a suggested fix.

## CI Integration

Example GitHub Actions workflow:

```yaml
name: config-coverage
on: [pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install config-coverage
      - run: config-coverage scan --format sarif --output config-coverage.sarif
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: config-coverage.sarif
```

For a hard gate on new regressions, use `--fail-on new`. The command exits `1` when a new finding is introduced and `0` when all findings are already baselined.

## Cross-File References

`config-coverage` validates references such as environment variable names derived from settings prefixes. For example, a dataclass setting prefix `APP_` may imply `APP_DATABASE_URL`; the scan checks that the derived name is used consistently across `.env` templates and source code.

## Caching

Parsed ASTs and configuration metadata are cached in `cache_dir`. Cache entries are invalidated using file content hashes and modification times. Use `--no-cache` for a fully fresh scan or `config-coverage cache clear` to reset cached data.

## Troubleshooting

- `config-coverage: command not found`: Reinstall the package or run `python -m config_coverage`.
- `configuration error`: Validate TOML syntax and glob patterns.
- Unexpected findings after renames: Refresh or recreate the baseline.
- Slow scans: Ensure caching is enabled and exclude generated directories.
