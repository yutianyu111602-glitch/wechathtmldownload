"""Atomic file write helpers."""
from __future__ import annotations
import os
import json
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON atomically via temp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, default=str)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically via temp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def atomic_write_jsonl(path: Path, records: list[dict]) -> None:
    """Append records as JSONL atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    mode = "a" if path.exists() else "w"
    with open(tmp, mode, encoding="utf-8") as f:
        f.write(lines)
    if mode == "a" and path.exists():
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(existing + lines)
    os.replace(tmp, path)


def safe_read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def safe_read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return default
