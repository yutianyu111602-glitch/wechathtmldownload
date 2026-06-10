#!/usr/bin/env python3
"""Lightweight local memory for pipeline progress tracking.
Drop-in replacement for mem0 cloud; writes to ~/.deepseek/pipeline_memory.jsonl.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

MEMORY_PATH = Path.home() / ".deepseek" / "pipeline_memory.jsonl"


def add(content: str, *, metadata: dict[str, Any] | None = None) -> None:
    """Append a memory entry."""
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "content": content,
        "metadata": metadata or {},
    }
    with MEMORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def latest(n: int = 5) -> list[dict]:
    """Return the last N memory entries."""
    if not MEMORY_PATH.exists():
        return []
    lines = MEMORY_PATH.read_text(encoding="utf-8").strip().split("\n")
    entries = []
    for line in lines[-n:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def query(metadata_key: str, metadata_value: str) -> list[dict]:
    """Query memories by metadata field."""
    if not MEMORY_PATH.exists():
        return []
    results = []
    with MEMORY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("metadata", {}).get(metadata_key) == metadata_value:
                    results.append(entry)
            except json.JSONDecodeError:
                continue
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <content> [metadata_key=value ...]")
        sys.exit(1)
    content = sys.argv[1]
    meta = {}
    for kv in sys.argv[2:]:
        if "=" in kv:
            k, v = kv.split("=", 1)
            meta[k] = v
    add(content, metadata=meta)
    print(f"memory: wrote {len(content)} chars")
