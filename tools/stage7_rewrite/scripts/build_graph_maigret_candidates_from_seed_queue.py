#!/usr/bin/env python3
"""Build Maigret username candidates from the current graph external seed queue.

This is a report-only adapter. It converts handle_candidate seeds into the
existing Maigret canary input schema. Maigret results remain breadth evidence
only and must pass identity review before graph use.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SEED_QUEUE = Path("reports/graph_external_evidence_seed_queue_47k_plus_paid_20260518/external_evidence_seed_queue.jsonl")
DEFAULT_OUT_DIR = Path("reports/graph_maigret_candidates_47k_plus_paid_20260518")
SCHEMA_VERSION = "stage7_graph_maigret_candidates.v1"
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,40}$")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def compact(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "seed_queue")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def username_ok(username: str) -> bool:
    raw = compact(username, 80).strip("@")
    if raw.casefold() in {"admin", "official", "music", "label", "club", "live"}:
        return False
    return USERNAME_RE.fullmatch(raw) is not None


def candidate_from_seed(seed: dict[str, Any]) -> dict[str, Any] | None:
    username = compact(seed.get("handle"), 80).strip("@")
    if not username_ok(username):
        return None
    support = int(seed.get("support_count") or 1)
    priority = int(seed.get("priority") or 0)
    score = min(0.98, 0.55 + min(priority, 100) / 250 + min(support, 20) / 100)
    return {
        "schema_version": SCHEMA_VERSION + ".candidate",
        "username": username,
        "subject_name": compact(seed.get("subject_name"), 120),
        "source_family": "graph_external_seed_queue",
        "source_kind": "handle_candidate",
        "candidate_score": round(score, 4),
        "status": "candidate_only_not_identity_proof",
        "platform": "",
        "evidence": [
            {
                "seed_id": seed.get("seed_id"),
                "source_article_uid": seed.get("source_article_uid"),
                "source_account": seed.get("source_account"),
                "source_title": seed.get("source_title"),
                "support_count": support,
                "review_status": seed.get("review_status"),
            }
        ],
    }


def build_candidates(seed_queue: Path, out_dir: Path, limit: int) -> dict[str, Any]:
    reject_broad_d_path(out_dir, "out_dir")
    rows = read_jsonl(seed_queue)
    candidates_by_username: dict[str, dict[str, Any]] = {}
    skipped = Counter()
    for seed in rows:
        if seed.get("seed_family") != "handle_candidate":
            continue
        candidate = candidate_from_seed(seed)
        if candidate is None:
            skipped["invalid_username"] += 1
            continue
        key = candidate["username"].casefold()
        existing = candidates_by_username.get(key)
        if existing is None or candidate["candidate_score"] > existing["candidate_score"]:
            candidates_by_username[key] = candidate
        else:
            skipped["duplicate_username_lower_score"] += 1

    candidates = sorted(candidates_by_username.values(), key=lambda item: (-float(item["candidate_score"]), item["username"].casefold()))
    total_candidates = len(candidates)
    if limit > 0:
        candidates = candidates[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = out_dir / "maigret_candidates.jsonl"
    write_jsonl(candidate_path, candidates)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "graph_maigret_candidates_ready" if candidates else "graph_maigret_candidates_empty",
        "seed_queue": str(seed_queue),
        "candidate_path": str(candidate_path),
        "handle_seeds_seen": sum(1 for row in rows if row.get("seed_family") == "handle_candidate"),
        "deduped_candidates": total_candidates,
        "written_candidates": len(candidates),
        "skipped": dict(sorted(skipped.items())),
        "safety": {
            "report_only": True,
            "network_calls_executed": False,
            "paid_api_used": False,
            "db_write": False,
            "candidate_only_not_identity_proof": True,
        },
        "next_gate": "Run a bounded Maigret canary against a small prefix before scaling; route hits to source validation and identity review.",
    }
    write_json(out_dir / "maigret_candidate_summary.json", summary)
    write_markdown(out_dir / "maigret_candidate_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Graph Maigret Candidates",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- handle_seeds_seen: `{summary['handle_seeds_seen']}`",
        f"- deduped_candidates: `{summary['deduped_candidates']}`",
        f"- written_candidates: `{summary['written_candidates']}`",
        f"- candidate_path: `{summary['candidate_path']}`",
        "",
        "## Safety",
        "",
        "- Report-only candidate conversion. No network call, paid API, DB write, or graph acceptance.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-queue", type=Path, default=DEFAULT_SEED_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=1000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_candidates(args.seed_queue, args.out_dir, args.limit)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "handle_seeds_seen": summary["handle_seeds_seen"],
                "written_candidates": summary["written_candidates"],
                "summary": str(args.out_dir / "maigret_candidate_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
