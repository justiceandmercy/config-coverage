"""Compare discovered configuration keys with observed source references."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @classmethod
    def from_str(cls, value: Optional[str]) -> "Severity":
        if value is None:
            return cls.WARNING
        v = str(value).lower()
        for member in cls:
            if member.value == v:
                return member
        if v in {"err", "critical", "high"}:
            return cls.ERROR
        if v in {"warn", "medium", "low"}:
            return cls.WARNING
        if v in {"information", "debug", "note"}:
            return cls.INFO
        return cls.WARNING


class FindingKind(str, Enum):
    UNUSED = "unused"
    MISSING = "missing"
    SHADOWED = "shadowed"
    MISTYPED = "mistyped"
    OVERRIDE = "override"


@dataclass
class ConfigKey:
    key: str
    source: str = ""
    path: str = ""
    line: Optional[int] = None
    type: Optional[str] = None
    required: bool = False
    default: Any = None
    env_var: Optional[str] = None
    format: Optional[str] = None
    values: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfigKey":
        if not isinstance(data, dict):
            raise TypeError("ConfigKey data must be a mapping")
        key = data.get("key") or data.get("name") or data.get("id")
        if not key:
            raise ValueError("ConfigKey requires a 'key' (or 'name'/'id')")
        return cls(
            key=str(key),
            source=str(data.get("source", data.get("file", ""))),
            path=str(data.get("path", data.get("file", ""))),
            line=data.get("line"),
            type=data.get("type") or data.get("expected_type"),
            required=bool(data.get("required", False)),
            default=data.get("default", data.get("value")),
            env_var=data.get("env_var") or data.get("env"),
            format=data.get("format") or data.get("kind"),
            values=list(data.get("values", []) or []),
            metadata=dict(data.get("metadata", {}) or {}),
        )


@dataclass
class Reference:
    key: str
    path: str = ""
    file: str = ""
    line: Optional[int] = None
    column: Optional[int] = None
    value_type: Optional[str] = None
    context: Optional[str] = None
    dynamic: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Reference":
        if not isinstance(data, dict):
            raise TypeError("Reference data must be a mapping")
        key = data.get("key") or data.get("name")
        if not key:
            raise ValueError("Reference requires a 'key' (or 'name')")
        path = data.get("path", data.get("file", ""))
        return cls(
            key=str(key),
            path=str(path),
            file=str(data.get("file", path)),
            line=data.get("line"),
            column=data.get("column"),
            value_type=data.get("value_type") or data.get("type"),
            context=data.get("context"),
            dynamic=bool(data.get("dynamic", False)),
            metadata=dict(data.get("metadata", {}) or {}),
        )


@dataclass
class Finding:
    kind: FindingKind
    key: str
    message: str
    severity: Severity = Severity.WARNING
    location: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    source_location: Optional[str] = None
    source_line: Optional[int] = None
    expected_type: Optional[str] = None
    actual_type: Optional[str] = None
    remediation: Optional[str] = None
    fingerprint: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value if isinstance(self.kind, FindingKind) else str(self.kind),
            "key": self.key,
            "message": self.message,
            "severity": self.severity.value if isinstance(self.severity, Severity) else str(self.severity),
            "location": self.location,
            "line": self.line,
            "column": self.column,
            "source_location": self.source_location,
            "source_line": self.source_line,
            "expected_type": self.expected_type,
            "actual_type": self.actual_type,
            "remediation": self.remediation,
            "fingerprint": self.fingerprint,
            "metadata": self.metadata,
        }


_TYPE_ALIASES = {
    "str": "string", "string": "string", "text": "string",
    "int": "integer", "integer": "integer", "number": "number",
    "float": "number", "double": "number", "bool": "boolean",
    "boolean": "boolean", "list": "array", "array": "array",
    "dict": "object", "object": "object", "mapping": "object",
    "none": "null", "null": "null",
}


def normalize_type(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        v = value.strip().lower()
        return _TYPE_ALIASES.get(v, v)
    if isinstance(value, (list, tuple, set)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__.lower()


def _as_config_key(item: Any) -> ConfigKey:
    if isinstance(item, ConfigKey):
        return item
    if isinstance(item, dict):
        return ConfigKey.from_dict(item)
    key = getattr(item, "key", None) or getattr(item, "name", None)
    if not key:
        raise TypeError("Cannot convert item to ConfigKey: missing key")
    return ConfigKey(
        key=str(key),
        source=getattr(item, "source", "") or getattr(item, "file", "") or "",
        path=getattr(item, "path", "") or getattr(item, "file", "") or "",
        line=getattr(item, "line", None),
        type=getattr(item, "type", None) or getattr(item, "expected_type", None),
        required=bool(getattr(item, "required", False)),
        default=getattr(item, "default", None),
        env_var=getattr(item, "env_var", None) or getattr(item, "env", None),
        format=getattr(item, "format", None) or getattr(item, "kind", None),
        values=list(getattr(item, "values", []) or []),
        metadata=dict(getattr(item, "metadata", {}) or {}),
    )


def _as_reference(item: Any) -> Reference:
    if isinstance(item, Reference):
        return item
    if isinstance(item, dict):
        return Reference.from_dict(item)
    key = getattr(item, "key", None) or getattr(item, "name", None)
    if not key:
        raise TypeError("Cannot convert item to Reference: missing key")
    return Reference(
        key=str(key),
        path=getattr(item, "path", "") or getattr(item, "file", "") or "",
        file=getattr(item, "file", "") or getattr(item, "path", "") or "",
        line=getattr(item, "line", None),
        column=getattr(item, "column", None),
        value_type=getattr(item, "value_type", None) or getattr(item, "type", None),
        context=getattr(item, "context", None),
        dynamic=bool(getattr(item, "dynamic", False)),
        metadata=dict(getattr(item, "metadata", {}) or {}),
    )


def _fingerprint(kind: FindingKind, key: str, location: Optional[str], line: Optional[int]) -> str:
    raw = f"{kind.value}|{key}|{location or ''}|{line if line is not None else ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _remediation(kind: FindingKind, key: str, **ctx: Any) -> str:
    if kind == FindingKind.UNUSED:
        return f"Remove unused setting '{key}' or add a reference where it is consumed."
    if kind == FindingKind.MISSING:
        return f"Define '{key}' in configuration or remove the reference."
    if kind == FindingKind.SHADOWED:
        return f"Resolve shadowing for '{key}': keep a single source of truth."
    if kind == FindingKind.MISTYPED:
        exp = ctx.get("expected")
        act = ctx.get("actual")
        return f"Change value/type of '{key}' from {act} to {exp}."
    if kind == FindingKind.OVERRIDE:
        return f"Document environment override for '{key}' or move it into config."
    return f"Review finding for '{key}'."


class CoverageAnalyzer:
    """Compare discovered config keys against observed references."""

    def __init__(
        self,
        discovered: Optional[Iterable[Any]] = None,
        references: Optional[Iterable[Any]] = None,
        *,
        env_prefix: Optional[str] = None,
        type_strict: bool = True,
        report_overrides: bool = True,
        shadow_by_precedence: bool = True,
    ) -> None:
        self.discovered: List[ConfigKey] = [_as_config_key(x) for x in (discovered or [])]
        self.references: List[Reference] = [_as_reference(x) for x in (references or [])]
        self.env_prefix = env_prefix
        self.type_strict = type_strict
        self.report_overrides = report_overrides
        self.shadow_by_precedence = shadow_by_precedence

    def analyze(self) -> List[Finding]:
        findings: List[Finding] = []
        findings.extend(self.find_missing())
        findings.extend(self.find_unused())
        findings.extend(self.find_shadowed())
        findings.extend(self.find_mistyped())
        if self.report_overrides:
            findings.extend(self.find_overrides())
        for f in findings:
            if not f.fingerprint:
                f.fingerprint = _fingerprint(f.kind, f.key, f.location, f.line)
        return findings

    def _ref_keys(self) -> Dict[str, List[Reference]]:
        out: Dict[str, List[Reference]] = {}
        for r in self.references:
            out.setdefault(r.key, []).append(r)
        return out

    def _discovered_by_key(self) -> Dict[str, List[ConfigKey]]:
        out: Dict[str, List[ConfigKey]] = {}
        for k in self.discovered:
            out.setdefault(k.key, []).append(k)
        return out

    def find_unused(self) -> List[Finding]:
        ref_keys = set(self._ref_keys().keys())
        out: List[Finding] = []
        for key in self.discovered:
            if key.key in ref_keys:
                continue
            sev = Severity.INFO if key.required else Severity.WARNING
            out.append(Finding(
                kind=FindingKind.UNUSED,
                key=key.key,
                message=f"Configuration key '{key.key}' is defined but never referenced.",
                severity=sev,
                location=key.path or key.source or None,
                line=key.line,
                source_location=key.source or key.path or None,
                source_line=key.line,
                remediation=_remediation(FindingKind.UNUSED, key.key),
            ))
        return out

    def find_missing(self) -> List[Finding]:
        discovered_keys = {k.key for k in self.discovered}
        out: List[Finding] = []
        for key, refs in self._ref_keys().items():
            if key in discovered_keys:
                continue
            for r in refs:
                out.append(Finding(
                    kind=FindingKind.MISSING,
                    key=key,
                    message=f"Referenced configuration key '{key}' is not defined.",
                    severity=Severity.ERROR,
                    location=r.path or r.file or None,
                    line=r.line,
                    column=r.column,
                    remediation=_remediation(FindingKind.MISSING, key),
                ))
        return out

    def find_shadowed(self) -> List[Finding]:
        out: List[Finding] = []
        by_key = self._discovered_by_key()
        for key, items in by_key.items():
            if len(items) < 2:
                continue
            for i, earlier in enumerate(items[:-1]):
                later = items[i + 1]
                out.append(Finding(
                    kind=FindingKind.SHADOWED,
                    key=key,
                    message=f"Configuration key '{key}' is defined multiple times; later definition shadows earlier.",
                    severity=Severity.WARNING,
                    location=later.path or later.source or None,
                    line=later.line,
                    source_location=earlier.path or earlier.source or None,
                    source_line=earlier.line,
                    remediation=_remediation(FindingKind.SHADOWED, key),
                ))
        if self.env_prefix:
            for key in self.discovered:
                if key.env_var:
                    out.append(Finding(
                        kind=FindingKind.SHADOWED,
                        key=key.key,
                        message=f"Environment variable '{key.env_var}' may shadow configuration key '{key.key}'.",
                        severity=Severity.INFO,
                        location=key.path or key.source or None,
                        line=key.line,
                        remediation=_remediation(FindingKind.SHADOWED, key.key),
                    ))
        return out

    def find_mistyped(self) -> List[Finding]:
        out: List[Finding] = []
        discovered = self._discovered_by_key()
        for key, refs in self._ref_keys().items():
            defs = discovered.get(key)
            if not defs:
                continue
            declared = defs[0].type
            if declared is None:
                continue
            declared_norm = normalize_type(declared)
            for r in refs:
                if r.value_type is None:
                    continue
                actual_norm = normalize_type(r.value_type)
                if declared_norm is not None and actual_norm is not None and declared_norm != actual_norm:
                    if declared_norm == "number" and actual_norm == "integer":
                        continue
                    if not self.type_strict and {declared_norm, actual_norm} <= {"integer", "number"}:
                        continue
                    out.append(Finding(
                        kind=FindingKind.MISTYPED,
                        key=key,
                        message=f"Type mismatch for '{key}': expected {declared_norm}, got {actual_norm}.",
                        severity=Severity.ERROR,
                        location=r.path or r.file or None,
                        line=r.line,
                        column=r.column,
                        source_location=defs[0].path or defs[0].source or None,
                        source_line=defs[0].line,
                        expected_type=declared_norm,
                        actual_type=actual_norm,
                        remediation=_remediation(FindingKind.MISTYPED, key, expected=declared_norm, actual=actual_norm),
                    ))
        for key in self.discovered:
            if key.type is None or key.default is None:
                continue
            dt = normalize_type(key.default)
            kt = normalize_type(key.type)
            if dt is not None and kt is not None and dt != kt:
                if {dt, kt} <= {"integer", "number"}:
                    continue
                out.append(Finding(
                    kind=FindingKind.MISTYPED,
                    key=key.key,
                    message=f"Default value for '{key.key}' does not match declared type {kt}.",
                    severity=Severity.WARNING,
                    location=key.path or key.source or None,
                    line=key.line,
                    expected_type=kt,
                    actual_type=dt,
                    remediation=_remediation(FindingKind.MISTYPED, key.key, expected=kt, actual=dt),
                ))
        return out

    def find_overrides(self) -> List[Finding]:
        out: List[Finding] = []
        for key in self.discovered:
            if key.env_var:
                if not (key.path or key.source):
                    out.append(Finding(
                        kind=FindingKind.OVERRIDE,
                        key=key.key,
                        message=f"Setting '{key.key}' is provided only via environment variable '{key.env_var}'.",
                        severity=Severity.INFO,
                        remediation=_remediation(FindingKind.OVERRIDE, key.key),
                    ))
                else:
                    out.append(Finding(
                        kind=FindingKind.OVERRIDE,
                        key=key.key,
                        message=f"Environment variable '{key.env_var}' overrides '{key.key}'.",
                        severity=Severity.INFO,
                        location=key.path or key.source or None,
                        line=key.line,
                        remediation=_remediation(FindingKind.OVERRIDE, key.key),
                    ))
        return out

    def run(self) -> List[Finding]:
        return self.analyze()


def analyze(discovered: Iterable[Any], references: Iterable[Any], **kwargs: Any) -> List[Finding]:
    return CoverageAnalyzer(discovered=discovered, references=references, **kwargs).analyze()


def find_unused(discovered, references, **kw):
    return CoverageAnalyzer(discovered=discovered, references=references, **kw).find_unused()


def find_missing(discovered, references, **kw):
    return CoverageAnalyzer(discovered=discovered, references=references, **kw).find_missing()


def find_shadowed(discovered, references, **kw):
    return CoverageAnalyzer(discovered=discovered, references=references, **kw).find_shadowed()


def find_mistyped(discovered, references, **kw):
    return CoverageAnalyzer(discovered=discovered, references=references, **kw).find_mistyped()


def find_overrides(discovered, references, **kw):
    return CoverageAnalyzer(discovered=discovered, references=references, **kw).find_overrides()
