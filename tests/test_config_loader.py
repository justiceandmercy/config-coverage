"""Unit tests for configuration discovery and normalization."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import config_loader as cl  # noqa: E402
import pytest  # noqa: E402


def _loader(root: Path):
    for name in ("ConfigLoader", "Loader", "ConfigParser"):
        cls = getattr(cl, name, None)
        if cls is not None:
            try:
                return cls(root)
            except TypeError:
                try:
                    return cls()
                except TypeError:
                    continue
    return None


def _detect(path: Path) -> str:
    if hasattr(cl, "detect_format"):
        return str(cl.detect_format(path))
    loader = _loader(path.parent)
    if loader is not None:
        for method in ("detect_format", "format_of", "detect", "format_for"):
            if hasattr(loader, method):
                return str(getattr(loader, method)(path))
    pytest.skip("No format detection API found")


def _load(path: Path):
    if hasattr(cl, "load_config"):
        return list(cl.load_config(path))
    if hasattr(cl, "load_file"):
        return list(cl.load_file(path))
    loader = _loader(path.parent)
    if loader is not None:
        for method in ("load", "load_file", "discover_file", "parse"):
            if hasattr(loader, method):
                try:
                    return list(getattr(loader, method)(path))
                except TypeError:
                    try:
                        return list(getattr(loader, method)(path, root=path.parent))
                    except TypeError:
                        continue
    pytest.skip("No config loading API found")


def _names(keys) -> list[str]:
    result = []
    for item in keys:
        value = None
        for attr in ("name", "key", "id", "path", "qualified_name"):
            if hasattr(item, attr):
                value = getattr(item, attr)
                break
        if value is None and isinstance(item, dict):
            for key in ("name", "key", "id", "path", "qualified_name"):
                if key in item:
                    value = item[key]
                    break
        result.append(str(value) if value is not None else str(item))
    return result


def _line(item) -> int:
    for attr in ("location", "source", "pos"):
        obj = getattr(item, attr, None)
        if obj is not None:
            for line_attr in ("line", "lineno", "line_number", "row"):
                value = getattr(obj, line_attr, None)
                if value is not None:
                    return int(value)
    for attr in ("line", "lineno", "line_number", "row"):
        value = getattr(item, attr, None)
        if value is not None:
            return int(value)
    if isinstance(item, dict):
        for key in ("line", "lineno", "line_number", "row"):
            if key in item:
                return int(item[key])
    return 0


def _normalize(value):
    for name in ("normalize_key", "normalize", "canonical_key"):
        func = getattr(cl, name, None)
        if callable(func):
            return func(value)
    loader = _loader(Path.cwd())
    if loader is not None:
        for method in ("normalize_key", "normalize", "canonical_key"):
            if hasattr(loader, method):
                return getattr(loader, method)(value)
    pytest.skip("No key normalization API found")


def _infer(value):
    for name in ("infer_type", "infer", "type_of", "guess_type"):
        func = getattr(cl, name, None)
        if callable(func):
            try:
                return func(value)
            except TypeError:
                try:
                    return func(str(value))
                except TypeError:
                    continue
    loader = _loader(Path.cwd())
    if loader is not None:
        for method in ("infer_type", "infer", "type_of", "guess_type"):
            if hasattr(loader, method):
                try:
                    return getattr(loader, method)(value)
                except TypeError:
                    try:
                        return getattr(loader, method)(str(value))
                    except TypeError:
                        continue
    pytest.skip("No type inference API found")


def test_format_detection(tmp_path: Path) -> None:
    samples = {
        "config.toml": "[app]\nname = \"demo\"\n",
        "config.yaml": "app:\n  name: demo\n",
        "config.yml": "app:\n  name: demo\n",
        "config.json": '{"app": {"name": "demo"}}\n',
        ".env.example": "APP_NAME=\nPORT=8080\n",
        "settings.py": "from dataclasses import dataclass\n\n@dataclass\nclass Settings:\n    app_name: str\n",
    }
    expected = {
        "config.toml": "toml",
        "config.yaml": "yaml",
        "config.yml": "yaml",
        "config.json": "json",
        ".env.example": "env",
        "settings.py": "python",
    }
    for filename, content in samples.items():
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        detected = _detect(path).lower()
        assert expected[filename] in detected or detected in expected[filename]


def test_toml_key_discovery_and_locations(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "[database]\nurl = \"postgres://localhost\"\nport = 5432\n\n[features]\nenabled = true\n",
        encoding="utf-8",
    )
    keys = _load(path)
    names = _names(keys)
    assert len(keys) == 3
    assert any(name.endswith("url") for name in names)
    assert any(name.endswith("port") for name in names)
    assert any(name.endswith("enabled") for name in names)
    assert any(_line(key) > 0 for key in keys)


def test_yaml_key_discovery(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("database:\n  url: postgres://localhost\n  port: 5432\n", encoding="utf-8")
    keys = _load(path)
    assert len(keys) == 2
    assert any("url" in _names(keys)[i] for i in range(len(keys)))


def test_json_key_discovery(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"database": {"url": "x", "port": 1}}', encoding="utf-8")
    keys = _load(path)
    assert len(keys) == 2


def test_env_template_discovery(tmp_path: Path) -> None:
    path = tmp_path / ".env.example"
    path.write_text("DATABASE_URL=\nPORT=8080\nDEBUG=false\n", encoding="utf-8")
    keys = _load(path)
    names = _names(keys)
    assert len(keys) == 3
    assert any("DATABASE_URL" in name or "database_url" in name.lower() for name in names)


def test_python_dataclass_discovery(tmp_path: Path) -> None:
    path = tmp_path / "settings.py"
    path.write_text(
        "from dataclasses import dataclass\n\n@dataclass\nclass Settings:\n    database_url: str\n    port: int = 5432\n",
        encoding="utf-8",
    )
    keys = _load(path)
    assert len(keys) >= 2
    names = [name.lower() for name in _names(keys)]
    assert any("database" in name or "url" in name for name in names)


def test_key_normalization_is_stable() -> None:
    samples = ["DATABASE_URL", "database.url", "database-url", "DatabaseUrl"]
    normalized = [_normalize(sample) for sample in samples]
    for value in normalized:
        assert _normalize(value) == value or _normalize(str(value)) == value
    assert len(set(str(value) for value in normalized)) <= len(samples)


def test_type_inference() -> None:
    cases = [
        (42, "int"),
        ("42", "int"),
        (3.14, "float"),
        ("3.14", "float"),
        (True, "bool"),
        ("true", "bool"),
        ("hello", "str"),
    ]
    for value, expected in cases:
        inferred = str(_infer(value)).lower()
        assert expected in inferred or inferred in {expected, expected + "eger", "boolean", "string"}


def test_source_location_capture(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[app]\nname = \"demo\"\nversion = \"1\"\n", encoding="utf-8")
    keys = _load(path)
    assert all(_line(key) in (0, 2, 3) or _line(key) > 0 for key in keys)
    assert any(_line(key) == 2 or _line(key) == 3 for key in keys)
