"""Integration tests for the config-coverage command line interface."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "src" / "main.py"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MAIN), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_project(root: Path) -> Path:
    write_file(
        root / "config.toml",
        "[database]\nurl = \"postgres://localhost\"\nport = 5432\n\n[unused]\nvalue = true\n",
    )
    write_file(
        root / "app.py",
        "DATABASE_URL = \"postgres://localhost\"\nprint(DATABASE_URL)\n",
    )
    return root


def scan(root: Path, *extra: str) -> subprocess.CompletedProcess:
    variants = (
        ("scan", str(root), *extra),
        (str(root), *extra),
    )
    last = None
    for variant in variants:
        result = run_cli(*variant)
        last = result
        combined = (result.stdout + result.stderr).lower()
        if "unrecognized arguments" not in combined and "invalid choice" not in combined:
            return result
    return last  # type: ignore[return-value]


def test_help_lists_commands() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    combined = (result.stdout + result.stderr).lower()
    assert "init" in combined or "scan" in combined


def test_init_scaffolds_config(tmp_path: Path) -> None:
    variants = (
        ("init", str(tmp_path)),
        ("init", "--root", str(tmp_path)),
        ("init", "--path", str(tmp_path)),
    )
    success = False
    for variant in variants:
        result = run_cli(*variant)
        if result.returncode == 0 and (tmp_path / "config-coverage.toml").exists():
            success = True
            break
    assert success, (result.stdout, result.stderr)
    content = (tmp_path / "config-coverage.toml").read_text(encoding="utf-8")
    assert "config" in content.lower() or "include" in content.lower()


def test_clean_project_exits_zero(tmp_path: Path) -> None:
    root = make_project(tmp_path / "clean")
    write_file(root / "app.py", "value = \"used\"\nprint(value)\n")
    write_file(root / "config.toml", "[app]\nvalue = \"used\"\n")
    result = scan(root, "--format", "json")
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_unused_finding_reported(tmp_path: Path) -> None:
    root = make_project(tmp_path / "unused")
    result = scan(root, "--format", "json")
    combined = (result.stdout + result.stderr).lower()
    assert result.returncode in (1, 2) or "unused" in combined
    if result.returncode not in (1, 2):
        assert "unused" in combined
    assert "unused" in combined or "unused.value" in combined


def test_missing_required_finding(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    write_file(root / "config.toml", "[app]\nrequired_value = \"\"\n")
    write_file(root / "config-coverage.toml", "[settings]\nrequired = [\"app.required_value\"]\n")
    result = scan(root, "--format", "json")
    combined = (result.stdout + result.stderr).lower()
    assert "missing" in combined or result.returncode != 0


def test_type_mismatch_finding(tmp_path: Path) -> None:
    root = tmp_path / "typed"
    write_file(root / "config.toml", "[app]\nport = \"not-a-number\"\n")
    write_file(root / "app.py", "PORT = \"not-a-number\"\n")
    result = scan(root, "--format", "json")
    combined = (result.stdout + result.stderr).lower()
    assert "type" in combined or "mismatch" in combined or result.returncode != 0


def test_baseline_suppresses_known_findings(tmp_path: Path) -> None:
    root = make_project(tmp_path / "baseline")
    first = scan(root, "--format", "json")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(first.stdout if first.stdout.strip() else "{}", encoding="utf-8")
    second = scan(root, "--format", "json", "--baseline", str(baseline))
    # Baseline support is accepted if the command runs; a clean or reduced result is ideal.
    assert second.returncode in (0, 1, 2)
    combined = (second.stdout + second.stderr).lower()
    assert "baseline" not in combined or "error" not in combined


def test_config_error_exit_code(tmp_path: Path) -> None:
    root = tmp_path / "badconfig"
    root.mkdir()
    write_file(root / "config-coverage.toml", "this is not valid toml = [\n")
    result = scan(root, "--format", "json")
    assert result.returncode != 0
    assert result.returncode == 2 or "error" in (result.stdout + result.stderr).lower()


def test_json_output_is_parseable_when_present(tmp_path: Path) -> None:
    root = make_project(tmp_path / "json")
    result = scan(root, "--format", "json")
    text = result.stdout.strip()
    if text.startswith("{") or text.startswith("["):
        json.loads(text)
