"""Immutable data models for config-coverage."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Mapping


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.ERROR: 2,
    Severity.CRITICAL: 3,
}


def severity_rank(value: Any) -> int:
    try:
        return _SEVERITY_RANK[Severity(str(value).lower())]
    except (ValueError, KeyError):
        return 0


def normalize_severity(value: Any) -> Severity:
    if isinstance(value, Severity):
        return value
    try:
        return Severity(str(value).lower())
    except ValueError as exc:
        raise ValueError(f"unknown severity: {value!r}") from exc


@dataclass(frozen=True)
class SourceLocation:
    path: str
    line: Optional[int] = None
    column: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "line": self.line, "column": self.column}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceLocation":
        return cls(path=str(data.get("path", "")), line=data.get("line"), column=data.get("column"))


@dataclass(frozen=True)
class ConfigKey:
    key: str
    source: str
    location: SourceLocation
    value_type: str = "string"
    required: bool = False
    has_default: bool = False
    default_repr: Optional[str] = None
    description: str = ""
    env_var: Optional[str] = None
    metadata: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError("ConfigKey.key must be non-empty")
        if not self.source:
            raise ValueError("ConfigKey.source must be non-empty")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "source": self.source,
            "location": self.location.to_dict(),
            "value_type": self.value_type,
            "required": self.required,
            "has_default": self.has_default,
            "default_repr": self.default_repr,
            "description": self.description,
            "env_var": self.env_var,
            "metadata": [list(item) for item in self.metadata],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConfigKey":
        return cls(
            key=str(data["key"]),
            source=str(data["source"]),
            location=SourceLocation.from_dict(data.get("location", {})),
            value_type=str(data.get("value_type", "string")),
            required=bool(data.get("required", False)),
            has_default=bool(data.get("has_default", False)),
            default_repr=data.get("default_repr"),
            description=str(data.get("description", "")),
            env_var=data.get("env_var"),
            metadata=tuple(tuple(item) for item in data.get("metadata", [])),
        )


@dataclass(frozen=True)
class Reference:
    key: Optional[str]
    source_path: str
    line: Optional[int] = None
    column: Optional[int] = None
    language: str = "unknown"
    context: str = ""
    dynamic: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "source_path": self.source_path,
            "line": self.line,
            "column": self.column,
            "language": self.language,
            "context": self.context,
            "dynamic": self.dynamic,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Reference":
        return cls(
            key=data.get("key"),
            source_path=str(data["source_path"]),
            line=data.get("line"),
            column=data.get("column"),
            language=str(data.get("language", "unknown")),
            context=str(data.get("context", "")),
            dynamic=bool(data.get("dynamic", False)),
        )


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: Severity
    key: Optional[str]
    message: str
    location: Optional[SourceLocation] = None
    evidence: Tuple[str, ...] = ()
    remediation: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", normalize_severity(self.severity))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity.value,
            "key": self.key,
            "message": self.message,
            "location": self.location.to_dict() if self.location else None,
            "evidence": list(self.evidence),
            "remediation": self.remediation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Finding":
        location = data.get("location")
        return cls(
            kind=str(data["kind"]),
            severity=normalize_severity(data.get("severity", "warning")),
            key=data.get("key"),
            message=str(data.get("message", "")),
            location=SourceLocation.from_dict(location) if location else None,
            evidence=tuple(data.get("evidence", [])),
            remediation=str(data.get("remediation", "")),
        )


@dataclass(frozen=True)
class ScanResult:
    root: str
    config_keys: Tuple[ConfigKey, ...] = ()
    references: Tuple[Reference, ...] = ()
    findings: Tuple[Finding, ...] = ()
    metadata: Tuple[Tuple[str, str], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "config_keys": [item.to_dict() for item in self.config_keys],
            "references": [item.to_dict() for item in self.references],
            "findings": [item.to_dict() for item in self.findings],
            "metadata": [list(item) for item in self.metadata],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScanResult":
        return cls(
            root=str(data.get("root", "")),
            config_keys=tuple(ConfigKey.from_dict(item) for item in data.get("config_keys", [])),
            references=tuple(Reference.from_dict(item) for item in data.get("references", [])),
            findings=tuple(Finding.from_dict(item) for item in data.get("findings", [])),
            metadata=tuple(tuple(item) for item in data.get("metadata", [])),
        )


@dataclass(frozen=True)
class BaselineEntry:
    fingerprint: str
    reason: str = ""
    created: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"fingerprint": self.fingerprint, "reason": self.reason, "created": self.created}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BaselineEntry":
        return cls(
            fingerprint=str(data["fingerprint"]),
            reason=str(data.get("reason", "")),
            created=str(data.get("created", "")),
        )


def finding_fingerprint(finding: Finding) -> str:
    location = finding.location
    where = f"{location.path}:{location.line}" if location else ""
    return f"{finding.kind}|{finding.key or ''}|{where}"
