#!/usr/bin/env python3
"""Check PRD-12 poster vectorization prerequisites.

This is a report-only gate. It reads the latest OCR file index, counts poster
OCR rows that already have text, optionally probes local Qdrant collections, and
decides whether poster text vectorization can start.

No OCR execution, embedding calls, graph/vector/DB writes, paid API calls,
D: scans, alias changes, or publish.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_POINTER = Path("reports/ocr_file_index_latest.json")
DEFAULT_OUT_DIR = Path("reports/poster_vector_preflight_20260515")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
SCHEMA_VERSION = "stage7_prd12_poster_vector_preflight.v1"
TEXT_READY_STATUSES = {"complete"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def require_local_url(url: str, label: str) -> None:
    if not url:
        return
    parsed = parse.urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"{label} URL must be local: {url}")


def read_json(path: Path) -> Any:
    reject_d_path(path, "json")
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def first_text(value: Any) -> str:
    return str(value or "").strip()


def qdrant_get(url: str) -> dict[str, Any]:
    with request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def probe_qdrant(qdrant_url: str) -> dict[str, Any]:
    if not qdrant_url:
        return {"enabled": False}
    require_local_url(qdrant_url, "Qdrant")
    base = qdrant_url.rstrip("/")
    try:
        collections = qdrant_get(f"{base}/collections")
        aliases = qdrant_get(f"{base}/aliases")
    except (OSError, error.URLError, json.JSONDecodeError) as exc:
        return {"enabled": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    collection_names = [
        first_text(item.get("name"))
        for item in ((collections.get("result") or {}).get("collections") or [])
        if isinstance(item, dict)
    ]
    alias_items = (aliases.get("result") or {}).get("aliases") or []
    alias_names = [first_text(item.get("alias_name")) for item in alias_items if isinstance(item, dict)]
    return {
        "enabled": True,
        "ok": True,
        "collection_count": len(collection_names),
        "poster_collections": sorted(name for name in collection_names if "poster" in name.casefold()),
        "poster_aliases": sorted(name for name in alias_names if "poster" in name.casefold()),
    }


def build_preflight(
    pointer_path: Path,
    out_dir: Path,
    min_text_posters: int,
    qdrant_url: str,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    pointer = read_json(pointer_path)
    index_path = Path(pointer["index_path"])
    rows = read_jsonl(index_path)
    ocr_status_counts = Counter(first_text(row.get("ocr_status")) or "unknown" for row in rows)
    text_ready_rows = [row for row in rows if first_text(row.get("ocr_status")) in TEXT_READY_STATUSES]
    local_image_rows = [row for row in rows if int(row.get("existing_local_image_count") or 0) > 0]
    text_gate_met = len(text_ready_rows) >= min_text_posters
    qdrant = probe_qdrant(qdrant_url)

    blockers: list[str] = []
    if not text_gate_met:
        blockers.append(f"poster OCR text rows {len(text_ready_rows)} < required {min_text_posters}")
    if qdrant.get("enabled") and not qdrant.get("ok"):
        blockers.append("local Qdrant probe failed")
    decision = "poster_vectorization_preflight_ready" if not blockers else "poster_vectorization_blocked_missing_ocr_text"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": not blockers,
        "pointer_path": str(pointer_path),
        "index_path": str(index_path),
        "record_count": len(rows),
        "min_text_posters": min_text_posters,
        "text_ready_poster_rows": len(text_ready_rows),
        "text_gate_met": text_gate_met,
        "local_image_rows": len(local_image_rows),
        "ocr_status_counts": dict(ocr_status_counts),
        "qdrant": qdrant,
        "blockers": blockers,
        "allowed_next_actions": (
            ["build_poster_text_vectors_canary"]
            if text_gate_met
            else ["recover_or_generate_real_poster_ocr_text_before_vectorization"]
        ),
        "forbidden_next_actions": [
            "do_not_run_embedding_without_real_poster_ocr_text",
            "do_not_create_qdrant_poster_collection",
            "do_not_promote_qdrant_alias",
            "do_not_use_test_fixtures_as_prd12_success",
        ],
        "safety": [
            "reports_only",
            "ocr_execution_false",
            "embedding_calls_false",
            "qdrant_write_false",
            "alias_change_false",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "poster_vector_preflight_summary.json", summary)
    write_markdown(out_dir / "poster_vector_preflight_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-12 Poster Vectorization Preflight",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- record_count: `{summary['record_count']}`",
        f"- text_ready_poster_rows: `{summary['text_ready_poster_rows']}`",
        f"- min_text_posters: `{summary['min_text_posters']}`",
        f"- text_gate_met: `{summary['text_gate_met']}`",
        f"- local_image_rows: `{summary['local_image_rows']}`",
        "",
        "## OCR Status",
        "",
    ]
    for key, value in sorted(summary["ocr_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if summary["blockers"]:
        for blocker in summary["blockers"]:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Qdrant", "", f"`{json.dumps(summary['qdrant'], ensure_ascii=False, sort_keys=True)}`", ""])
    lines.extend(
        [
            "## Safety",
            "",
            "- Reports only.",
            "- No OCR execution, embedding call, Qdrant write, alias change, paid API, D: scan, or publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-text-posters", type=int, default=20)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_preflight(
        pointer_path=args.pointer,
        out_dir=args.out_dir,
        min_text_posters=args.min_text_posters,
        qdrant_url=args.qdrant_url,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "text_ready_poster_rows": summary["text_ready_poster_rows"],
                "text_gate_met": summary["text_gate_met"],
                "summary": str(args.out_dir / "poster_vector_preflight_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
