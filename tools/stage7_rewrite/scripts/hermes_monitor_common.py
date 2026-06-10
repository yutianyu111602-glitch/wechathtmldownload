"""Shared helpers for local Hermes Stage7 monitoring scripts."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Hermes report-only monitoring: {path}")


def read_json_if_exists(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    reject_d_path(path, "json_output")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    reject_d_path(path, "jsonl_output")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_text(path: Path, text: str) -> None:
    reject_d_path(path, "text_output")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def latest_markdown_heading(path: Path) -> str:
    reject_d_path(path, "markdown")
    if not path.exists():
        return ""
    headings: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            headings.append(line.strip())
    return headings[-1] if headings else ""


def flatten_numeric(obj: Any, prefix: str = "") -> Iterable[tuple[str, float]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_numeric(value, next_prefix)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from flatten_numeric(value, f"{prefix}[{index}]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield prefix, float(obj)


def safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
