"""Reference scanning for configuration usage."""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .models import Reference
from .config_loader import PathFilter


CONFIG_TARGET_NAMES = {
    "config",
    "cfg",
    "settings",
    "setting",
    "conf",
    "options",
    "env",
    "environment",
    "params",
    "parameters",
}

DEFAULT_REGEX_PATTERNS = (
    "(?<![A-Za-z0-9_])process[.]env[.]([A-Za-z_][A-Za-z0-9_]*)",
    "(?<![A-Za-z0-9_])(?:config|settings|cfg|conf)[.]([A-Za-z_][A-Za-z0-9_.]*)",
    "(?<![A-Za-z0-9_])(?:getenv|get_setting|get_config)\(\s*['\"]([^'\"]+)['\"]",
    "(?<![A-Za-z0-9_])(?:os[.]environ|environ)\[\s*['\"]([^'\"]+)['\"]\s*\]",
)


class ReferenceScanner:
    """Walk source trees and extract configuration references."""

    def __init__(
        self,
        root: Any,
        path_filter: Optional[PathFilter] = None,
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        use_gitignore: bool = True,
        regex_patterns: Optional[Sequence[str]] = None,
        cache_dir: Optional[Any] = None,
        use_cache: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        self.filter = path_filter or PathFilter(self.root, include=include, exclude=exclude, use_gitignore=use_gitignore)
        self.regex_patterns = list(regex_patterns) if regex_patterns else list(DEFAULT_REGEX_PATTERNS)
        self.cache_dir = Path(cache_dir).resolve() if cache_dir else self.root / ".config-coverage-cache"
        self.use_cache = use_cache

    def scan(self) -> List[Reference]:
        references: List[Reference] = []
        cache = self._load_cache() if self.use_cache else {"files": {}}
        cache_files = cache.setdefault("files", {})
        changed = False
        for path in self._discover():
            signature = [path.stat().st_mtime, path.stat().st_size]
            cached = cache_files.get(str(path))
            if cached and cached.get("signature") == signature:
                references.extend(Reference.from_dict(item) for item in cached.get("references", []))
                continue
            extracted = self._scan_file(path)
            references.extend(extracted)
            cache_files[str(path)] = {
                "signature": signature,
                "references": [item.to_dict() for item in extracted],
            }
            changed = True
        if changed and self.use_cache:
            self._save_cache(cache)
        seen = set()
        unique: List[Reference] = []
        for reference in references:
            key = (reference.source_path, reference.line, reference.key, reference.context)
            if key in seen:
                continue
            seen.add(key)
            unique.append(reference)
        return sorted(unique, key=lambda item: (item.source_path, item.line or 0, item.key or ""))

    def _discover(self) -> List[Path]:
        result: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            current = Path(dirpath)
            dirnames[:] = [name for name in dirnames if not self.filter.ignored(current / name)]
            for filename in filenames:
                path = current / filename
                if not self.filter.included(path):
                    continue
                if path.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
                    result.append(path)
        return sorted(result)

    def _scan_file(self, path: Path) -> List[Reference]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".py":
            return self._scan_python(path, text)
        return self._scan_regex(path, text)

    def _scan_python(self, path: Path, text: str) -> List[Reference]:
        references: List[Reference] = []
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            return references
        visitor = _PythonReferenceVisitor(str(path), references)
        visitor.visit(tree)
        return references

    def _scan_regex(self, path: Path, text: str) -> List[Reference]:
        references: List[Reference] = []
        for pattern in self.regex_patterns:
            try:
                regex = re.compile(pattern)
            except re.error:
                continue
            for match in regex.finditer(text):
                key = match.group(1) if match.groups() else None
                if key is None:
                    continue
                line = text[: match.start()].count("\n") + 1
                references.append(
                    Reference(
                        key=key,
                        source_path=str(path),
                        line=line,
                        language="javascript",
                        context=match.group(0),
                        dynamic=False,
                    )
                )
        return references

    def _load_cache(self) -> Dict[str, Any]:
        path = self.cache_dir / "references.json"
        if not path.exists():
            return {"files": {}}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"files": {}}

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / "references.json").write_text(
                json.dumps(cache, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            pass


class _PythonReferenceVisitor(ast.NodeVisitor):
    def __init__(self, path: str, references: List[Reference]) -> None:
        self.path = path
        self.references = references

    def _add(self, key: Optional[str], node: Any, dynamic: bool = False, language: str = "python") -> None:
        column = None
        if getattr(node, "col_offset", None) is not None:
            column = node.col_offset + 1
        self.references.append(
            Reference(
                key=key,
                source_path=self.path,
                line=getattr(node, "lineno", None),
                column=column,
                language=language,
                context=_safe_unparse(node),
                dynamic=dynamic,
            )
        )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        target = _expr_name(node.value)
        if _is_config_target(target):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                self._add(node.slice.value, node)
            else:
                self._add(None, node, dynamic=True)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        target = _expr_name(node.value)
        if _is_config_target(target):
            self._add(node.attr, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = _expr_name(node.func)
        if func in {"os.getenv", "getenv"} or func.endswith(".getenv"):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                self._add(node.args[0].value, node)
        if func.endswith(".get") and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            target = ""
            if isinstance(node.func, ast.Attribute):
                target = _expr_name(node.func.value)
            if _is_config_target(target):
                self._add(node.args[0].value, node)
        if func == "getattr" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
            target = _expr_name(node.args[0])
            if _is_config_target(target):
                self._add(node.args[1].value, node)
        self.generic_visit(node)


def _is_config_target(target: str) -> bool:
    if not target:
        return False
    lowered = target.lower()
    if lowered in CONFIG_TARGET_NAMES:
        return True
    if lowered.endswith(("config", "settings", "options", "conf", "env", "environ", "parameters")):
        return True
    if "environ" in lowered:
        return True
    return False


def _expr_name(node: Any) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _safe_unparse(node: Any) -> str:
    if hasattr(ast, "unparse"):
        try:
            return ast.unparse(node)
        except Exception:
            return ""
    return ""
