"""Path constants and helpers."""
from __future__ import annotations
import os
from pathlib import Path


def get_default_input_root() -> Path:
    return Path(r"D:\DDownload\_llm_release_v2\articles")


def get_default_output_root() -> Path:
    return Path(r"D:\downstream_results\stage7_rewrite")


def ensure_output_dirs(output_root: Path) -> None:
    dirs = [
        "manifests",
        "state",
        "llm_extract",
        "graph_candidates",
        "vectors",
        "reports",
        "logs",
    ]
    for d in dirs:
        (output_root / d).mkdir(parents=True, exist_ok=True)


def article_output_dir(output_root: Path, source_account: str, article_id: str) -> Path:
    safe_account = _safe_name(source_account)
    safe_id = _safe_name(article_id)
    return output_root / "llm_extract" / safe_account / safe_id


def _safe_name(name: str) -> str:
    """Replace path-unsafe chars."""
    unsafe = '<>:"/\\|?*'
    for ch in unsafe:
        name = name.replace(ch, '_')
    return name.strip('. ')
