"""Read, write, and apply baseline suppressions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:
    from .coverage_analyzer import Finding, FindingKind, Severity
except Exception:
    try:
        from coverage_analyzer import Finding, FindingKind, Severity
    except Exception:
        Finding = None
        FindingKind = None
        Severity = None


@dataclass
class BaselineEntry:
    fingerprint: str
    location: Optional[str] = None
    key: Optional[str] = None
    kind: Optional[str] = None
    line: Optional[int] = None
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "location": self.location,
            "key": self.key,
            "kind": self.kind,
            "line": self.line,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaselineEntry":
        if not isinstance(data, dict):
            raise TypeError("Baseline entry must be a mapping")
        fp = data.get("fingerprint") or data.get("id") or data.get("hash")
        if not fp:
            raw = f"{data.get('kind')}|{data.get('key')}|{data.get('location')}|{data.get('line')}"
            fp = hashlib.sha256(raw.encode()).hexdigest()
        return cls(
            fingerprint=str(fp),
            location=data.get("location") or data.get("path") or data.get("file"),
            key=data.get("key"),
            kind=data.get("kind") or data.get("type"),
            line=data.get("line"),
            reason=data.get("reason") or data.get("comment"),
            metadata=dict(data.get("metadata", {}) or {}),
        )


@dataclass
class Baseline:
    version: int = 1
    entries: List[BaselineEntry] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def fingerprints(self) -> Set[str]:
        return {e.fingerprint for e in self.entries}

    def contains(self, finding: Any) -> bool:
        fp = get_fingerprint(finding)
        loc = get_location(finding)
        for e in self.entries:
            if e.fingerprint == fp:
                if e.location is None or e.location == loc:
                    return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "entries": [e.to_dict() for e in self.entries],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Baseline":
        if not isinstance(data, dict):
            raise TypeError("Baseline data must be a mapping")
        entries = [BaselineEntry.from_dict(x) for x in (data.get("entries") or data.get("findings") or data.get("suppressions") or [])]
        return cls(
            version=int(data.get("version", 1)),
            entries=entries,
            metadata=dict(data.get("metadata", {}) or {}),
        )


def _finding_attr(finding: Any, name: str, default: Any = None) -> Any:
    if isinstance(finding, dict):
        return finding.get(name, default)
    return getattr(finding, name, default)


def get_fingerprint(finding: Any) -> str:
    fp = _finding_attr(finding, "fingerprint", None)
    if fp:
        return str(fp)
    kind = _finding_attr(finding, "kind", "")
    key = _finding_attr(finding, "key", "")
    loc = get_location(finding)
    line = _finding_attr(finding, "line", None)
    raw = f"{kind}|{key}|{loc or ''}|{line if line is not None else ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_location(finding: Any) -> Optional[str]:
    return _finding_attr(finding, "location", None) or _finding_attr(finding, "path", None) or _finding_attr(finding, "file", None)


def load_baseline(path: Any) -> Baseline:
    p = Path(path)
    if not p.exists():
        return Baseline()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Cannot read baseline file {p}: {exc}") from exc
    if not text.strip():
        return Baseline()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in baseline file {p}: {exc}") from exc
    return Baseline.from_dict(data)


def save_baseline(path: Any, findings: Iterable[Any], *, append: bool = False, reason: Optional[str] = None) -> Baseline:
    p = Path(path)
    existing = Baseline()
    if append and p.exists():
        try:
            existing = load_baseline(p)
        except Exception:
            existing = Baseline()
    entries = list(existing.entries)
    seen = {e.fingerprint for e in entries}
    for f in findings:
        fp = get_fingerprint(f)
        if fp in seen:
            continue
        entries.append(BaselineEntry(
            fingerprint=fp,
            location=get_location(f),
            key=_finding_attr(f, "key", None),
            kind=str(_finding_attr(f, "kind", "")),
            line=_finding_attr(f, "line", None),
            reason=reason,
        ))
        seen.add(fp)
    baseline = Baseline(entries=entries, metadata=existing.metadata)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(baseline.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return baseline


def apply_baseline(findings: Iterable[Any], baseline: Any) -> Tuple[List[Any], List[Any]]:
    if baseline is None:
        bl = Baseline()
    elif isinstance(baseline, Baseline):
        bl = baseline
    elif isinstance(baseline, (str, Path)):
        bl = load_baseline(baseline)
    else:
        try:
            bl = Baseline.from_dict(baseline)
        except Exception:
            bl = Baseline()
    suppressed: List[Any] = []
    remaining: List[Any] = []
    for f in findings:
        if bl.contains(f):
            suppressed.append(f)
        else:
            remaining.append(f)
    return suppressed, remaining


def filter_baseline(findings: Iterable[Any], baseline: Any) -> List[Any]:
    _, remaining = apply_baseline(findings, baseline)
    return remaining


def new_findings(findings: Iterable[Any], baseline: Any) -> List[Any]:
    return filter_baseline(findings, baseline)


def write_baseline(path: Any, findings: Iterable[Any], **kwargs: Any) -> Baseline:
    return save_baseline(path, findings, **kwargs)
