"""CLI entrypoint for config-coverage."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

try:
    from .models import ConfigKey, Finding, Reference, ScanResult, BaselineEntry, Severity, finding_fingerprint
except ImportError:  # pragma: no cover
    from models import ConfigKey, Finding, Reference, ScanResult, BaselineEntry, Severity, finding_fingerprint

try:
    from .config_loader import ConfigLoader, PathFilter, ConfigLoadError
except ImportError:  # pragma: no cover
    from config_loader import ConfigLoader, PathFilter, ConfigLoadError

try:
    from .reference_scanner import ReferenceScanner
except ImportError:  # pragma: no cover
    from reference_scanner import ReferenceScanner

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CONFIG_ERROR = 2


def _load_tool_config(root: Path, config_path: str) -> Any:
    path = Path(config_path)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        return {}
    try:
        if path.suffix.lower() == ".toml":
            if tomllib is None:
                return {}
            with path.open("rb") as handle:
                return tomllib.load(handle)
        if path.suffix.lower() in {".yaml", ".yml"}:
            if yaml is None:
                return {}
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if path.suffix.lower() == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _resolve_options(args: argparse.Namespace) -> Tuple[Path, Any, List[str], List[str], List[str], Optional[str], str]:
    root = Path(args.root).resolve()
    tool_config = _load_tool_config(root, getattr(args, "config", "config-coverage.toml"))
    scan_config = tool_config.get("scan", {}) if isinstance(tool_config, dict) else {}
    include = args.include if getattr(args, "include", None) else scan_config.get("include", ["**/*"])
    exclude = args.exclude if getattr(args, "exclude", None) else scan_config.get("exclude", [])
    regex = args.regex if getattr(args, "regex", None) else scan_config.get("regex_patterns", [])
    baseline = args.baseline if getattr(args, "baseline", None) else scan_config.get("baseline")
    fail_on = args.fail_on if getattr(args, "fail_on", None) else scan_config.get("fail_on", "warning")
    return root, tool_config, list(include), list(exclude), list(regex), baseline, str(fail_on)


def _type_mismatch(value_type: str, context: str) -> bool:
    lowered_type = value_type.lower()
    lowered_context = context.lower()
    if lowered_type in {"int", "integer"}:
        return "str(" in lowered_context or ".lower()" in lowered_context
    if lowered_type in {"str", "string"}:
        return "int(" in lowered_context or "float(" in lowered_context or "bool(" in lowered_context
    if lowered_type in {"bool", "boolean"}:
        return "int(" in lowered_context or "float(" in lowered_context
    return False


def analyze(config_keys: Sequence[ConfigKey], references: Sequence[Reference]) -> List[Finding]:
    findings: List[Finding] = []
    declared = {key.key: key for key in config_keys}
    grouped: dict = {}
    for key in config_keys:
        grouped.setdefault(key.key, []).append(key)
    for key, items in grouped.items():
        if len(items) > 1:
            findings.append(
                Finding(
                    kind="shadowed",
                    severity=Severity.WARNING,
                    key=key,
                    message=f"Configuration key {key!r} is defined multiple times",
                    location=items[1].location,
                    evidence=tuple(f"{item.source}: {item.location.path}" for item in items),
                    remediation="Remove or rename the duplicate definition.",
                )
            )
    referenced = {reference.key for reference in references if reference.key}
    for key in config_keys:
        if key.key not in referenced:
            findings.append(
                Finding(
                    kind="unused",
                    severity=Severity.WARNING,
                    key=key.key,
                    message=f"Configuration key {key.key!r} is defined but never referenced",
                    location=key.location,
                    remediation="Remove the unused key or add a reference.",
                )
            )
    for reference in references:
        if reference.key and reference.key not in declared:
            findings.append(
                Finding(
                    kind="missing",
                    severity=Severity.ERROR,
                    key=reference.key,
                    message=f"Referenced configuration key {reference.key!r} is not defined",
                    location=SourceLocation(reference.source_path, reference.line, reference.column),
                    evidence=(reference.context,),
                    remediation="Add the key to a configuration definition.",
                )
            )
    for reference in references:
        if reference.key in declared:
            config_key = declared[reference.key]
            if _type_mismatch(config_key.value_type, reference.context):
                findings.append(
                    Finding(
                        kind="mismatch",
                        severity=Severity.ERROR,
                        key=reference.key,
                        message=f"Possible type mismatch for {reference.key!r}: declared {config_key.value_type}",
                        location=SourceLocation(reference.source_path, reference.line, reference.column),
                        evidence=(reference.context,),
                        remediation="Align the declared type with code usage.",
                    )
                )
    seen = set()
    unique: List[Finding] = []
    for finding in findings:
        fingerprint = finding_fingerprint(finding)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(finding)
    return unique


def perform_scan(args: argparse.Namespace, apply_baseline: bool = False):
    root, tool_config, include, exclude, regex, baseline_path, fail_on = _resolve_options(args)
    path_filter = PathFilter(root, include=include, exclude=exclude, use_gitignore=not getattr(args, "no_gitignore", False))
    try:
        loader = ConfigLoader(root, path_filter=path_filter)
        config_keys = loader.load_all()
        scanner = ReferenceScanner(
            root,
            path_filter=path_filter,
            regex_patterns=regex,
            cache_dir=getattr(args, "cache_dir", None),
            use_cache=not getattr(args, "no_cache", False),
        )
        references = scanner.scan()
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    findings = analyze(config_keys, references)
    baseline_entries: List[BaselineEntry] = []
    if baseline_path:
        baseline_file = Path(baseline_path)
        if not baseline_file.is_absolute():
            baseline_file = root / baseline_file
        baseline_entries = _load_baseline(baseline_file)
    result_findings = findings
    if apply_baseline:
        baseline_fingerprints = {entry.fingerprint for entry in baseline_entries}
        result_findings = [finding for finding in findings if finding_fingerprint(finding) not in baseline_fingerprints]
    result = ScanResult(
        root=str(root),
        config_keys=tuple(config_keys),
        references=tuple(references),
        findings=tuple(result_findings),
        metadata=(("fail_on", fail_on),),
    )
    return result, findings, baseline_entries, fail_on


def _load_baseline(path: Path) -> List[BaselineEntry]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("entries", data.get("findings", []))
    entries: List[BaselineEntry] = []
    for item in data or []:
        if isinstance(item, dict):
            entries.append(
                BaselineEntry(
                    fingerprint=str(item.get("fingerprint", item.get("id", ""))),
                    reason=str(item.get("reason", "")),
                    created=str(item.get("created", "")),
                )
            )
    return entries


def _write_baseline(findings: Sequence[Finding], path: Path) -> None:
    entries = [
        {"fingerprint": finding_fingerprint(finding), "reason": "", "created": datetime.now().isoformat()}
        for finding in findings
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "entries": entries}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _terminal_report(result: ScanResult) -> str:
    lines = [f"config-coverage: {len(result.findings)} finding(s)", ""]
    for finding in result.findings:
        location = finding.location
        where = f"{location.path}:{location.line}" if location and location.line else (location.path if location else "")
        lines.append(f"{finding.severity.value.upper():8} {finding.kind:9} {finding.key or '-'} {where}")
        if finding.message:
            lines.append(f"         {finding.message}")
        if finding.remediation:
            lines.append(f"         hint: {finding.remediation}")
    if not result.findings:
        lines.append("No findings.")
    lines.append("")
    lines.append(f"Config keys: {len(result.config_keys)}; references: {len(result.references)}")
    return "\n".join(lines) + "\n"


def _sarif_report(result: ScanResult) -> str:
    level_map = {"info": "note", "warning": "warning", "error": "error", "critical": "error"}
    sarif_results = []
    for finding in result.findings:
        location = finding.location
        uri = Path(location.path).as_posix() if location else ""
        line = location.line if location and location.line else 1
        sarif_results.append(
            {
                "ruleId": finding.kind,
                "level": level_map.get(finding.severity.value, "warning"),
                "message": {"text": finding.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": uri},
                            "region": {"startLine": line},
                        }
                    }
                ],
            }
        )
    payload = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {"driver": {"name": "config-coverage", "version": "0.1.0"}},
                "results": sarif_results,
            }
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _render_result(result: ScanResult, output_format: str, output_path: Optional[str]) -> None:
    if output_format == "json":
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    elif output_format == "sarif":
        text = _sarif_report(result)
    else:
        text = _terminal_report(result)
    if output_path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _exit_code(findings: Sequence[Finding], fail_on: str) -> int:
    if fail_on == "none":
        return EXIT_OK
    ranks = {"info": 0, "warning": 1, "error": 2, "critical": 3}
    threshold = ranks.get(str(fail_on).lower(), 1)
    for finding in findings:
        if ranks.get(finding.severity.value, 0) >= threshold:
            return EXIT_FINDINGS
    return EXIT_OK


def _cmd_scan(args: argparse.Namespace) -> int:
    try:
        result, all_findings, baseline_entries, fail_on = perform_scan(args, apply_baseline=True)
    except Exception as exc:
        print(f"config-coverage: configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if getattr(args, "write_baseline", None):
        destination = Path(args.write_baseline)
        if not destination.is_absolute():
            destination = Path(result.root) / destination
        _write_baseline(all_findings, destination)
    _render_result(result, args.format, args.output)
    return _exit_code(result.findings, getattr(args, "fail_on", None) or fail_on)


def _cmd_diff(args: argparse.Namespace) -> int:
    try:
        result, all_findings, baseline_entries, fail_on = perform_scan(args, apply_baseline=False)
    except Exception as exc:
        print(f"config-coverage: configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    baseline_fingerprints = {entry.fingerprint for entry in baseline_entries}
    if args.left and args.right:
        try:
            left = ScanResult.from_dict(json.loads(Path(args.left).read_text(encoding="utf-8")))
            right = ScanResult.from_dict(json.loads(Path(args.right).read_text(encoding="utf-8")))
        except Exception as exc:
            print(f"config-coverage: configuration error: {exc}", file=sys.stderr)
            return EXIT_CONFIG_ERROR
        left_fingerprints = {finding_fingerprint(finding) for finding in left.findings}
        new_findings = [finding for finding in right.findings if finding_fingerprint(finding) not in left_fingerprints]
    else:
        new_findings = [finding for finding in all_findings if finding_fingerprint(finding) not in baseline_fingerprints]
    diff_result = ScanResult(
        root=result.root,
        config_keys=result.config_keys,
        references=result.references,
        findings=tuple(new_findings),
        metadata=result.metadata,
    )
    _render_result(diff_result, args.format, args.output)
    return _exit_code(new_findings, getattr(args, "fail_on", None) or fail_on)


def _cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    destination = root / "config-coverage.toml"
    if destination.exists() and not args.force:
        print(f"config-coverage: {destination} already exists")
        return EXIT_OK
    try:
        loader = ConfigLoader(root)
        discovered = loader.discover()
    except Exception:
        discovered = []
    content = _init_template(discovered)
    destination.write_text(content, encoding="utf-8")
    print(f"config-coverage: wrote {destination}")
    return EXIT_OK


def _init_template(discovered: Sequence[Path]) -> str:
    return (
        "# config-coverage configuration\n"
        "[scan]\n"
        'include = ["**/*"]\n'
        'exclude = [".git", "node_modules", "dist", "build", "__pycache__", ".venv"]\n'
        "regex_patterns = [\n"
        "  '(?<![A-Za-z0-9_])process[.]env[.]([A-Za-z_][A-Za-z0-9_]*)',\n"
        "  '(?<![A-Za-z0-9_])(?:config|settings|cfg|conf)[.]([A-Za-z_][A-Za-z0-9_.]*)',\n"
        "  '(?<![A-Za-z0-9_])(?:getenv|get_setting|get_config)\\(\\s*[\'"]([^\'"]+)[\'"]',\n"
        "  '(?<![A-Za-z0-9_])(?:os[.]environ|environ)\\[\\s*[\'"]([^\'"]+)[\'"]\\s*\\]',\n"
        "]\n"
        'baseline = ".config-coverage-baseline.json"\n'
        'fail_on = "warning"\n'
        "\n"
        "[report]\n"
        'format = "terminal"\n'
    )


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".")
    common.add_argument("--config", default="config-coverage.toml")
    common.add_argument("--include", action="append", default=[])
    common.add_argument("--exclude", action="append", default=[])
    common.add_argument("--no-gitignore", action="store_true")
    common.add_argument("--cache-dir")
    common.add_argument("--no-cache", action="store_true")
    common.add_argument("--regex", action="append", default=[])
    common.add_argument("--baseline")
    common.add_argument("--fail-on", default="warning")
    common.add_argument("--format", choices=["terminal", "json", "sarif"], default="terminal")
    common.add_argument("--output")
    common.add_argument("--verbose", action="store_true")

    parser = argparse.ArgumentParser(prog="config-coverage", description="Audit configuration definitions against code usage.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", parents=[common], help="Scan a project")
    scan.add_argument("--write-baseline")
    scan.set_defaults(func=_cmd_scan)

    diff = subparsers.add_parser("diff", parents=[common], help="Show new findings")
    diff.add_argument("left", nargs="?")
    diff.add_argument("right", nargs="?")
    diff.set_defaults(func=_cmd_diff)

    init = subparsers.add_parser("init", parents=[common], help="Scaffold configuration")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=_cmd_init)

    report = subparsers.add_parser("report", parents=[common], help="Generate a report")
    report.set_defaults(func=_cmd_scan)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
