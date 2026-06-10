from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FORBIDDEN_KEY_PARTS = ("cookie", "token", "secret", "password", "authorization")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _contains_forbidden_key(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                return str(key)
            found = _contains_forbidden_key(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _contains_forbidden_key(item)
            if found:
                return found
    return None


class JsonlSpoolClient:
    """Write complete JSONL batches for db2_writer_daemon to consume atomically."""

    def __init__(self, spool_dir: Path, *, prefix: str, batch_size: int = 100):
        self.spool_dir = Path(spool_dir)
        self.prefix = prefix
        self.batch_size = max(1, batch_size)
        self._buffer: list[dict[str, Any]] = []
        self._sequence = 0
        self.written_files = 0
        self.written_events = 0

    @property
    def incoming_dir(self) -> Path:
        return self.spool_dir / "incoming"

    def write_event(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise TypeError("spool event must be a dict")
        if "op" not in event:
            raise ValueError("spool event requires op")
        forbidden = _contains_forbidden_key(event)
        if forbidden:
            raise ValueError(f"spool event contains forbidden key: {forbidden}")
        self._buffer.append(dict(event))
        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self) -> Path | None:
        if not self._buffer:
            return None
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self._sequence += 1
        name = f"{self.prefix}_{utc_stamp()}_{os.getpid()}_{self._sequence:04d}.jsonl"
        final_path = self.incoming_dir / name
        temp_path = self.incoming_dir / f".{name}.tmp"
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            for event in self._buffer:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        os.replace(temp_path, final_path)
        self.written_files += 1
        self.written_events += len(self._buffer)
        self._buffer = []
        return final_path

    def status(self) -> dict[str, Any]:
        return {
            "spool_dir": str(self.spool_dir),
            "buffered_events": len(self._buffer),
            "written_files": self.written_files,
            "written_events": self.written_events,
        }
