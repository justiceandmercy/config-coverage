"""Persist parsed AST and configuration metadata caches."""

from __future__ import annotations

import ast
import hashlib
import json
import pickle
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_CACHE_DIRNAME = ".config-coverage-cache"


def content_hash(path: Any) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, cache_dir: Any = None, *, enabled: bool = True) -> None:
        if cache_dir is None:
            cache_dir = Path.cwd() / DEFAULT_CACHE_DIRNAME
        self.cache_dir = Path(cache_dir)
        self.enabled = bool(enabled)
        if self.enabled:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.enabled = False

    def _path_for(self, namespace: str, key: str) -> Path:
        return self.cache_dir / namespace / (_safe_name(key) + ".bin")

    def _json_path_for(self, namespace: str, key: str) -> Path:
        return self.cache_dir / namespace / (_safe_name(key) + ".json")

    def get_ast(self, path: Any) -> Optional[ast.AST]:
        if not self.enabled:
            return None
        try:
            ch = content_hash(path)
        except OSError:
            return None
        p = self._path_for("ast", ch)
        if not p.exists():
            return None
        try:
            with p.open("rb") as fh:
                obj = pickle.load(fh)
            if isinstance(obj, tuple) and len(obj) == 2 and obj[0] == ch:
                return obj[1]
            if isinstance(obj, ast.AST):
                return obj
        except Exception:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        return None

    def set_ast(self, path: Any, tree: ast.AST) -> None:
        if not self.enabled:
            return
        try:
            ch = content_hash(path)
        except OSError:
            return
        p = self._path_for("ast", ch)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with p.open("wb") as fh:
                pickle.dump((ch, tree), fh)
        except Exception:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    def get_metadata(self, path: Any, namespace: str = "metadata") -> Optional[Any]:
        if not self.enabled:
            return None
        try:
            ch = content_hash(path)
        except OSError:
            return None
        p = self._json_path_for(namespace, ch)
        if not p.exists():
            return None
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("_hash") == ch:
                return data.get("value")
            return data
        except Exception:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        return None

    def set_metadata(self, path: Any, value: Any, namespace: str = "metadata") -> None:
        if not self.enabled:
            return
        try:
            ch = content_hash(path)
        except OSError:
            return
        p = self._json_path_for(namespace, ch)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            return
        try:
            with p.open("w", encoding="utf-8") as fh:
                json.dump({"_hash": ch, "value": value}, fh)
        except Exception:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    def get(self, key: str, namespace: str = "general") -> Optional[Any]:
        if not self.enabled:
            return None
        p = self._json_path_for(namespace, key)
        if not p.exists():
            return None
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("value", data)
        except Exception:
            return None

    def set(self, key: str, value: Any, namespace: str = "general") -> None:
        if not self.enabled:
            return
        p = self._json_path_for(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            return
        try:
            with p.open("w", encoding="utf-8") as fh:
                json.dump({"value": value}, fh)
        except Exception:
            pass

    def clear(self, namespace: Optional[str] = None) -> int:
        if not self.enabled or not self.cache_dir.exists():
            return 0
        count = 0
        targets = [self.cache_dir / namespace] if namespace else list(self.cache_dir.iterdir())
        for t in targets:
            if t.is_dir():
                for f in t.rglob("*"):
                    if f.is_file():
                        try:
                            f.unlink()
                            count += 1
                        except Exception:
                            pass
            elif t.is_file():
                try:
                    t.unlink()
                    count += 1
                except Exception:
                    pass
        return count

    def stats(self) -> Dict[str, Any]:
        if not self.cache_dir.exists():
            return {"entries": 0, "size_bytes": 0}
        entries = 0
        size = 0
        for f in self.cache_dir.rglob("*"):
            if f.is_file():
                entries += 1
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
        return {"entries": entries, "size_bytes": size}

    def cached_parse(self, path: Any) -> Optional[ast.AST]:
        tree = self.get_ast(path)
        if tree is not None:
            return tree
        try:
            p = Path(path)
            source = p.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(p))
        except (OSError, SyntaxError):
            return None
        self.set_ast(path, tree)
        return tree


def parse_cached(path: Any, cache: Optional[Cache] = None) -> Optional[ast.AST]:
    c = cache if cache is not None else Cache()
    return c.cached_parse(path)


def hash_file(path: Any) -> str:
    return content_hash(path)
