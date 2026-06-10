#!/usr/bin/env python3
"""Build a PRD-16 social deep edge candidate pack from public canaries.

Reachable public profile pages become candidate edges only. They are not
accepted for Neo4j staging because public profile reachability alone is not
identity proof. The script writes an empty accepted edge file for dry-run writer
compatibility.

No graph/vector/DB writes, paid API calls, D: scans, or publish.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SOUNDCLOUD_DIR = Path("reports/soundcloud_canary_20260515")
DEFAULT_BANDCAMP_DIR = Path("reports/bandcamp_canary_20260515")
DEFAULT_LINKTREE_DIR = Path("reports/linktree_canary_20260515")
DEFAULT_OUT_DIR = Path("reports/social_deep_edge_pack_20260515")
SCHEMA_VERSION = "stage7_social_deep_edge_pack.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for PRD-16 social deep edge pack: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def edge_id(edge: dict[str, Any]) -> str:
    raw = "|".join(
        [
            first_text(edge.get("edge_type")),
            first_text(edge.get("source_family")),
            first_text(edge.get("subject_name")),
            first_text(edge.get("object_url")),
            first_text(edge.get("evidence_url")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def platform_canary_path(platform_dir: Path, platform: str) -> Path:
    return platform_dir / f"{platform}_profile_canary.jsonl"


def canary_rows(soundcloud_dir: Path, bandcamp_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for platform, directory in [("soundcloud", soundcloud_dir), ("bandcamp", bandcamp_dir)]:
        path = platform_canary_path(directory, platform)
        for row in read_jsonl(path):
            enriched = dict(row)
            enriched["source_canary_path"] = str(path)
            rows.append(enriched)
    return rows


def build_edge_candidate(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    platform = first_text(row.get("platform") or row.get("canary_platform"))
    edge = {
        "schema_version": SCHEMA_VERSION + ".candidate_row",
        "edge_type": "HAS_PROFILE",
        "source_family": first_text(row.get("source_family")),
        "subject_name": first_text(row.get("subject_name")),
        "object_url": first_text(row.get("final_url") or row.get("url")),
        "object_platform": platform,
        "object_title": first_text(row.get("page_title")),
        "evidence_url": first_text(row.get("evidence_url")),
        "confidence": 0.58,
        "verification_status": "public_profile_reachable",
        "review_status": "needs_identity_crosscheck",
        "review_reason": "Public profile reachability is not identity proof.",
        "staging_only": True,
        "graph_ready": False,
        "identity_proof": False,
        "rollback_key": run_id,
        "source_canary_path": first_text(row.get("source_canary_path")),
        "provenance": {
            "status_code": row.get("status_code"),
            "checked_at": first_text(row.get("checked_at")),
            "normalized_url": first_text(row.get("normalized_url")),
            "profile_canary_status": first_text(row.get("profile_canary_status")),
        },
    }
    edge["edge_id"] = edge_id(edge)
    return edge


def build_pack(
    soundcloud_dir: Path,
    bandcamp_dir: Path,
    linktree_dir: Path,
    out_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    reject_d_path(soundcloud_dir, "soundcloud_dir")
    reject_d_path(bandcamp_dir, "bandcamp_dir")
    reject_d_path(linktree_dir, "linktree_dir")
    reject_d_path(out_dir, "out_dir")

    rows = canary_rows(soundcloud_dir=soundcloud_dir, bandcamp_dir=bandcamp_dir)
    skipped: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not row.get("accessible"):
            skipped["blocked_or_unreachable"] += 1
            continue
        edge = build_edge_candidate(row, run_id=run_id)
        if not edge["subject_name"] or not edge["object_url"]:
            skipped["missing_required_edge_field"] += 1
            continue
        if edge["edge_id"] in seen:
            skipped["duplicate_edge"] += 1
            continue
        seen.add(edge["edge_id"])
        candidates.append(edge)
        skipped["not_accepted_public_reachability_only"] += 1

    edge_counts = Counter(row["edge_type"] for row in candidates)
    platform_counts = Counter(row["object_platform"] for row in candidates)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = out_dir / "social_deep_edge_candidates.jsonl"
    accepted_path = out_dir / "accepted_social_edges.jsonl"
    write_jsonl(candidate_path, candidates)
    write_jsonl(accepted_path, [])

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "social_deep_edge_candidates_ready_for_review" if candidates else "social_deep_edge_pack_empty",
        "ok": True,
        "run_id": run_id,
        "soundcloud_dir": str(soundcloud_dir),
        "bandcamp_dir": str(bandcamp_dir),
        "linktree_dir": str(linktree_dir),
        "candidate_path": str(candidate_path),
        "accepted_edges_path": str(accepted_path),
        "canary_rows_seen": len(rows),
        "candidate_edges": len(candidates),
        "accepted_edges": 0,
        "edge_counts": dict(edge_counts),
        "platform_counts": dict(platform_counts),
        "skipped": dict(skipped),
        "neo4j_writer_safe_input": str(accepted_path),
        "safety": [
            "reports_only",
            "candidate_edges_only",
            "accepted_edges_empty_without_identity_crosscheck",
            "staging_only",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
    }
    write_json(out_dir / "social_deep_edge_pack_summary.json", summary)
    write_markdown(out_dir / "social_deep_edge_pack_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-16 Social Deep Edge Pack",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- canary_rows_seen: `{summary['canary_rows_seen']}`",
        f"- candidate_edges: `{summary['candidate_edges']}`",
        f"- accepted_edges: `{summary['accepted_edges']}`",
        f"- candidate_path: `{summary['candidate_path']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        "",
        "## Platform Counts",
        "",
    ]
    for key, value in sorted(summary["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Skipped", ""])
    for key, value in sorted(summary["skipped"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- Reachable public profiles are candidate edges only.",
            "- Accepted edge file is intentionally empty until identity crosscheck/review is added.",
            "- Neo4j dry-run should read the empty accepted edge file and perform no mutation.",
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- No graph/vector/DB write, paid API, D: scan, or publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soundcloud-dir", type=Path, default=DEFAULT_SOUNDCLOUD_DIR)
    parser.add_argument("--bandcamp-dir", type=Path, default=DEFAULT_BANDCAMP_DIR)
    parser.add_argument("--linktree-dir", type=Path, default=DEFAULT_LINKTREE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--run-id", default="stage7_prd16_social_deep_20260515")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_pack(
        soundcloud_dir=args.soundcloud_dir,
        bandcamp_dir=args.bandcamp_dir,
        linktree_dir=args.linktree_dir,
        out_dir=args.out_dir,
        run_id=args.run_id,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "candidate_edges": summary["candidate_edges"],
                "accepted_edges": summary["accepted_edges"],
                "summary": str(args.out_dir / "social_deep_edge_pack_summary.json"),
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
