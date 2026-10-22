"""Configuration loading and normalization."""
from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from .models import ConfigKey, SourceLocation


class ConfigLoadError(Exception):
    """Raised when a configuration file cannot be loaded."""


DEFAULT_DATACLASS_PATTERNS = (
    "*Config",
    "*Settings",
    "*Options",
    "*Env",
    "*Parameters",
    "*Configuration",
)


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _expr_name(node: Any) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _expr_name(node.func)
    return ""


def _normalize_annotation(annotation: str) -> str:
    lowered = annotation.strip().lower()
    for candidate in ("int", "str", "string", "bool", "float", "list", "dict", "tuple", "set"):
        if candidate in lowered:
            if candidate == "string":
                return "str"
            return candidate
    return "string"


def _find_line(text: str, leaf: str) -> Optional[int]:
    if not leaf:
        return None
    pattern = re.compile(r"^\s*['\"]?" + re.escape(leaf) + r"['\"]?\s*[:=]")
    for index, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            return index
    return None


class PathFilter:
    """Apply include, exclude, and basic .gitignore rules."""

    DEFAULT_EXCLUDES = (
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".venv",
        "venv",
    )

    def __init__(
        self,
        root: Any,
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        use_gitignore: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        self.include = list(include) if include else ["**/*"]
        self.exclude = list(exclude) if exclude else []
        self.use_gitignore = use_gitignore
        self._gitignore = self._read_gitignore() if use_gitignore else []

    def _read_gitignore(self) -> List[Tuple[Path, str, bool]]:
        patterns: List[Tuple[Path, str, bool]] = []
        for gitignore in self.root.rglob(".gitignore"):
            base = gitignore.parent
            try:
                for raw in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    negated = line.startswith("!")
                    if negated:
                        line = line[1:].strip()
                    patterns.append((base, line, negated))
            except OSError:
                continue
        return patterns

    def _match(self, path: Path, relative: str, pattern: str) -> bool:
        pattern = pattern.strip()
        if not pattern:
            return False
        directory_only = pattern.endswith("/")
        if directory_only:
            pattern = pattern.rstrip("/")
        if fnmatch.fnmatch(relative, pattern):
            return True
        if "/" not in pattern and fnmatch.fnmatch(path.name, pattern):
            return True
        if "**" in pattern:
            simplified = pattern.replace("**/", "").replace("**", "*")
            if fnmatch.fnmatch(relative, simplified):
                return True
        try:
            if path.match(pattern):
                return True
        except Exception:
            pass
        return False

    def ignored(self, path: Any) -> bool:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = (self.root / candidate).resolve()
        try:
            relative = candidate.relative_to(self.root).as_posix()
        except ValueError:
            return False
        for pattern in self.DEFAULT_EXCLUDES + self.exclude:
            if self._match(candidate, relative, pattern):
                return True
        ignored = False
        for base, pattern, negated in self._gitignore:
            try:
                relative_to_base = candidate.relative_to(base).as_posix()
            except ValueError:
                continue
            if self._match(candidate, relative_to_base, pattern):
                ignored = False if negated else True
        return ignored

    def included(self, path: Any) -> bool:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = (self.root / candidate).resolve()
        if self.ignored(candidate):
            return False
        try:
            relative = candidate.relative_to(self.root).as_posix()
        except ValueError:
            return False
        return any(self._match(candidate, relative, pattern) for pattern in self.include)


class ConfigLoader:
    """Load configuration definitions from supported formats."""

    def __init__(
        self,
        root: Any,
        path_filter: Optional[PathFilter] = None,
        dataclass_patterns: Optional[Sequence[str]] = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.filter = path_filter or PathFilter(self.root)
        self.dataclass_patterns = tuple(dataclass_patterns or DEFAULT_DATACLASS_PATTERNS)

    def discover(self) -> List[Path]:
        discovered: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            current = Path(dirpath)
            dirnames[:] = [name for name in dirnames if not self.filter.ignored(current / name)]
            for filename in filenames:
                path = current / filename
                if not self.filter.included(path):
                    continue
                if self._is_supported(path):
                    discovered.append(path)
        return sorted(discovered)

    def _is_supported(self, path: Path) -> bool:
        name = path.name.lower()
        if name.startswith(".env"):
            return True
        if path.suffix.lower() in {".toml", ".yaml", ".yml", ".json"}:
            return True
        if path.suffix.lower() == ".py":
            return True
        return False

    def load_all(self) -> List[ConfigKey]:
        keys: List[ConfigKey] = []
        for path in self.discover():
            keys.extend(self.load_file(path))
        return keys

    def load_file(self, path: Any) -> List[ConfigKey]:
        path = Path(path)
        name = path.name.lower()
        try:
            if name.startswith(".env"):
                return self._load_dotenv(path)
            suffix = path.suffix.lower()
            if suffix == ".toml":
                if tomllib is None:
                    raise ConfigLoadError("tomllib is unavailable")
                text = path.read_text(encoding="utf-8")
                data = tomllib.loads(text)
                return self._flatten_mapping(data, "toml", path, text)
            if suffix in {".yaml", ".yml"}:
                if yaml is None:
                    raise ConfigLoadError("PyYAML is unavailable")
                text = path.read_text(encoding="utf-8")
                data = yaml.safe_load(text) or {}
                return self._flatten_mapping(data, "yaml", path, text)
            if suffix == ".json":
                text = path.read_text(encoding="utf-8")
                data = json.loads(text)
                return self._flatten_mapping(data, "json", path, text)
            if suffix == ".py":
                return self._load_python(path)
        except ConfigLoadError:
            raise
        except Exception as exc:
            raise ConfigLoadError(f"{path}: {exc}") from exc
        return []

    def _flatten_mapping(self, data: Any, source: str, path: Path, text: str) -> List[ConfigKey]:
        if not isinstance(data, dict):
            return []
        results: List[ConfigKey] = []

        def walk(obj: Any, prefix: str) -> None:
            if not isinstance(obj, dict):
                return
            if not obj:
                return
            for key, value in obj.items():
                new_key = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, dict):
                    walk(value, new_key)
                elif isinstance(value, list):
                    if value and all(isinstance(item, dict) for item in value):
                        for index, item in enumerate(value):
                            walk(item, f"{new_key}[{index}]")
                    else:
                        results.append(
                            ConfigKey(
                                key=new_key,
                                source=source,
                                location=SourceLocation(str(path)),
                                value_type="array",
                                required=False,
                                has_default=True,
                                default_repr=repr(value),
                            )
                        )
                else:
                    results.append(
                        ConfigKey(
                            key=new_key,
                            source=source,
                            location=SourceLocation(str(path)),
                            value_type=_infer_type(value),
                            required=False,
                            has_default=True,
                            default_repr=repr(value),
                        )
                    )

        walk(data, "")
        updated: List[ConfigKey] = []
        for item in results:
            if item.location.line is None:
                leaf = item.key.split(".")[-1].split("[")[0]
                line = _find_line(text, leaf)
                updated.append(
                    replace(item, location=SourceLocation(str(path), line, item.location.column))
                )
            else:
                updated.append(item)
        return updated

    def _load_python(self, path: Path) -> List[ConfigKey]:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        results: List[ConfigKey] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not self._is_dataclass(node):
                continue
            if not any(fnmatch.fnmatch(node.name, pattern) for pattern in self.dataclass_patterns):
                continue
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
                    continue
                key = statement.target.id
                annotation = ast.unparse(statement.annotation) if hasattr(ast, "unparse") else ""
                default_repr = None
                required = True
                if statement.value is not None:
                    required = False
                    default_repr = ast.unparse(statement.value) if hasattr(ast, "unparse") else None
                results.append(
                    ConfigKey(
                        key=key,
                        source="python-dataclass",
                        location=SourceLocation(str(path), statement.lineno, statement.col_offset + 1),
                        value_type=_normalize_annotation(annotation),
                        required=required,
                        has_default=default_repr is not None,
                        default_repr=default_repr,
                        metadata=(("class", node.name),),
                    )
                )
        return results

    def _is_dataclass(self, node: ast.ClassDef) -> bool:
        for decorator in node.decorator_list:
            name = _expr_name(decorator)
            if name == "dataclass" or name.endswith(".dataclass"):
                return True
            if isinstance(decorator, ast.Call):
                name = _expr_name(decorator.func)
                if name == "dataclass" or name.endswith(".dataclass"):
                    return True
        return False

    def _load_dotenv(self, path: Path) -> List[ConfigKey]:
        text = path.read_text(encoding="utf-8")
        results: List[ConfigKey] = []
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            required = value == ""
            results.append(
                ConfigKey(
                    key=key,
                    source="dotenv",
                    location=SourceLocation(str(path), lineno),
                    value_type=_infer_type(value),
                    required=required,
                    has_default=not required,
                    default_repr=repr(value),
                    env_var=key,
                )
            )
        return results
