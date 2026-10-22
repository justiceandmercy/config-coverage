"""Render findings as terminal, JSON, and SARIF reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from .coverage_analyzer import Finding, FindingKind, Severity
except Exception:
    try:
        from coverage_analyzer import Finding, FindingKind, Severity
    except Exception:
        Finding = None
        FindingKind = None
        Severity = None

try:
    from .baseline import get_fingerprint, get_location
except Exception:
    try:
        from baseline import get_fingerprint, get_location
    except Exception:
        def get_fingerprint(f):
            return str(getattr(f, "fingerprint", "") or "")
        def get_location(f):
            return getattr(f, "location", None)


_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _attr(f: Any, name: str, default: Any = None) -> Any:
    if isinstance(f, dict):
        return f.get(name, default)
    return getattr(f, name, default)


def _kind_value(f: Any) -> str:
    k = _attr(f, "kind", "")
    return k.value if hasattr(k, "value") else str(k)


def _severity_value(f: Any) -> str:
    s = _attr(f, "severity", "warning")
    return s.value if hasattr(s, "value") else str(s)


def sort_findings(findings: Iterable[Any]) -> List[Any]:
    def key(f: Any):
        loc = get_location(f) or ""
        line = _attr(f, "line", None)
        line = line if line is not None else 0
        knd = _kind_value(f)
        keyname = _attr(f, "key", "") or ""
        return (loc, line, knd, keyname)
    return sorted(list(findings), key=key)


def filter_by_severity(findings: Iterable[Any], min_severity: Optional[str] = None) -> List[Any]:
    if not min_severity:
        return list(findings)
    threshold = _SEVERITY_ORDER.get(str(min_severity).lower(), 1)
    out = []
    for f in findings:
        sev = _severity_value(f).lower()
        rank = _SEVERITY_ORDER.get(sev, 1)
        if rank <= threshold:
            out.append(f)
    return out


def _remediation(f: Any) -> Optional[str]:
    return _attr(f, "remediation", None) or _attr(f, "hint", None) or _attr(f, "suggestion", None)


def render_terminal(findings: Iterable[Any], *, min_severity: Optional[str] = None, color: bool = False) -> str:
    items = sort_findings(filter_by_severity(findings, min_severity))
    lines: List[str] = []
    if not items:
        lines.append("No findings. Configuration coverage clean.")
        return "\n".join(lines)
    current_file = None
    for f in items:
        loc = get_location(f) or "<unknown>"
        if loc != current_file:
            current_file = loc
            lines.append(f"\n{loc}:")
        line_no = _attr(f, "line", None)
        col = _attr(f, "column", None)
        pos = f"{line_no}" if line_no is not None else ""
        if col is not None:
            pos = f"{pos}:{col}" if pos else str(col)
        sev = _severity_value(f).upper()
        kind = _kind_value(f).upper()
        key = _attr(f, "key", "")
        msg = _attr(f, "message", "")
        prefix = f"  [{sev}] {kind}"
        if pos:
            prefix += f" (line {pos})"
        lines.append(f"{prefix}: {key} - {msg}")
        rem = _remediation(f)
        if rem:
            lines.append(f"         hint: {rem}")
    counts: Dict[str, int] = {}
    for f in items:
        counts[_kind_value(f)] = counts.get(_kind_value(f), 0) + 1
    lines.append("")
    lines.append("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + f" (total {len(items)})")
    return "\n".join(lines)


def render_json(findings: Iterable[Any], *, min_severity: Optional[str] = None, indent: int = 2) -> str:
    items = sort_findings(filter_by_severity(findings, min_severity))
    payload = []
    for f in items:
        if hasattr(f, "to_dict"):
            d = f.to_dict()
        elif isinstance(f, dict):
            d = dict(f)
        else:
            d = {
                "kind": _kind_value(f),
                "key": _attr(f, "key", None),
                "message": _attr(f, "message", None),
                "severity": _severity_value(f),
                "location": get_location(f),
                "line": _attr(f, "line", None),
                "column": _attr(f, "column", None),
                "source_location": _attr(f, "source_location", None),
                "source_line": _attr(f, "source_line", None),
                "expected_type": _attr(f, "expected_type", None),
                "actual_type": _attr(f, "actual_type", None),
                "remediation": _remediation(f),
                "fingerprint": _attr(f, "fingerprint", None) or get_fingerprint(f),
            }
        payload.append(d)
    return json.dumps(payload, indent=indent, sort_keys=True)


def render_sarif(findings: Iterable[Any], *, tool_name: str = "config-coverage", tool_version: str = "0.1.0", min_severity: Optional[str] = None) -> str:
    items = sort_findings(filter_by_severity(findings, min_severity))
    results = []
    for f in items:
        loc = get_location(f)
        line = _attr(f, "line", None) or 1
        col = _attr(f, "column", None) or 1
        uri = loc or "config"
        sarif_loc = {
            "physicalLocation": {
                "artifactLocation": {"uri": uri},
                "region": {"startLine": int(line), "startColumn": int(col)},
            }
        }
        rule_id = f"config-coverage/{_kind_value(f)}"
        msg = _attr(f, "message", "") or ""
        level = "error" if _severity_value(f).lower() == "error" else ("warning" if _severity_value(f).lower() == "warning" else "note")
        result = {
            "ruleId": rule_id,
            "level": level,
            "message": {"text": msg},
            "locations": [sarif_loc],
            "properties": {
                "key": _attr(f, "key", None),
                "fingerprint": _attr(f, "fingerprint", None) or get_fingerprint(f),
                "remediation": _remediation(f),
            },
        }
        results.append(result)
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": tool_version,
                        "informationUri": "https://example.com/config-coverage",
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2)


def write_report(path: Any, findings: Iterable[Any], *, format: str = "json", **kwargs: Any) -> None:
    p = Path(path)
    fmt = str(format).lower()
    if fmt == "terminal":
        content = render_terminal(findings, **kwargs)
    elif fmt == "json":
        content = render_json(findings, **kwargs)
    elif fmt == "sarif":
        content = render_sarif(findings, **kwargs)
    else:
        raise ValueError(f"Unsupported report format: {format}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content + ("\n" if not content.endswith("\n") else ""), encoding="utf-8")


def render(findings, format="terminal", **kw):
    fmt = format.lower()
    if fmt == "json":
        return render_json(findings, **kw)
    if fmt == "sarif":
        return render_sarif(findings, **kw)
    return render_terminal(findings, **kw)
