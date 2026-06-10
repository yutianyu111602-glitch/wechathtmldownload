#!/usr/bin/env python3
"""Build a bounded Maigret username candidate list from verified social edges.

Candidates are evidence for breadth discovery only. Maigret hits do not prove
identity; any useful hit must be cross-validated by a source-specific check.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_EDGES = Path("reports/p1_social_edge_pack_20260514/social_edge_pack.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_maigret_candidates_20260514")
HANDLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,40}$")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Maigret candidates: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows = []
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def first_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def handle_from_url(url: str) -> str:
    parsed = urlparse(first_text(url))
    host = parsed.netloc.casefold().replace("www.", "")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if not parts:
        return ""
    if "instagram.com" in host or "soundcloud.com" in host:
        return parts[0].strip("@")
    return ""


def normalize_candidate(value: str) -> str:
    value = first_text(value).strip("@")
    value = value.replace(" ", "")
    return value[:64]


def valid_candidate(value: str) -> bool:
    return bool(HANDLE_RE.match(value)) and not any(ord(ch) > 127 for ch in value)


def candidate_score(edge: dict[str, Any], source: str) -> float:
    base = float(edge.get("confidence") or 0.5)
    if source == "profile_url":
        base += 0.18
    elif source == "subject_name":
        base -= 0.08
    if edge.get("object_platform") in {"instagram", "soundcloud"}:
        base += 0.05
    return round(min(max(base, 0.0), 0.99), 3)


def build_candidates(edge_path: Path, out_dir: Path, limit: int) -> dict[str, Any]:
    reject_d_path(edge_path, "edge_path")
    reject_d_path(out_dir, "out_dir")
    edges = read_jsonl(edge_path)
    grouped: dict[str, dict[str, Any]] = {}
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        sources = []
        handle = handle_from_url(first_text(edge.get("object_url")))
        if handle:
            sources.append(("profile_url", handle))
        subject = normalize_candidate(first_text(edge.get("subject_name")))
        if valid_candidate(subject):
            sources.append(("subject_name", subject))
        for source, raw in sources:
            candidate = normalize_candidate(raw)
            if not valid_candidate(candidate):
                continue
            score = candidate_score(edge, source)
            item = grouped.get(candidate)
            if not item or score > item["candidate_score"]:
                grouped[candidate] = {
                    "schema_version": "stage7_p1_maigret_candidate.v1",
                    "username": candidate,
                    "candidate_score": score,
                    "source_kind": source,
                    "subject_name": first_text(edge.get("subject_name")),
                    "platform": first_text(edge.get("object_platform")),
                    "source_family": first_text(edge.get("source_family")),
                    "status": "candidate_only_not_identity_proof",
                }
            evidence[candidate].append(
                {
                    "edge_id": edge.get("edge_id"),
                    "edge_type": edge.get("edge_type"),
                    "object_url": edge.get("object_url"),
                    "evidence_url": edge.get("evidence_url"),
                    "verification_status": edge.get("verification_status"),
                    "source_kind": source,
                }
            )
    rows = sorted(grouped.values(), key=lambda item: (-item["candidate_score"], item["username"].casefold()))
    if limit:
        rows = rows[:limit]
    for row in rows:
        row["evidence"] = evidence[row["username"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = out_dir / "maigret_candidates.jsonl"
    write_jsonl(candidates_path, rows)
    summary = {
        "schema_version": "stage7_p1_maigret_candidate_summary.v1",
        "generated_at": now_iso(),
        "edge_path": str(edge_path),
        "candidate_path": str(candidates_path),
        "candidates": len(rows),
        "top_usernames": [row["username"] for row in rows[:10]],
        "writes": "reports_only",
        "decision": "maigret_candidates_ready" if rows else "maigret_candidates_empty",
    }
    write_json(out_dir / "maigret_candidate_summary.json", summary)
    write_markdown(out_dir / "maigret_candidate_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# P1 Maigret Candidate List",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- candidates: `{summary['candidates']}`",
        f"- candidate_path: `{summary['candidate_path']}`",
        f"- top_usernames: `{json.dumps(summary['top_usernames'], ensure_ascii=False)}`",
        "",
        "## Safety",
        "",
        "- Candidate list only.",
        "- Maigret hit is breadth evidence, not identity proof.",
        "- No graph/vector/DB write.",
        "- No paid API.",
        "- No D: scan.",
        "- No publish.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    summary = build_candidates(args.edge_pack, args.out_dir, args.limit)
    print(json.dumps({"decision": summary["decision"], "candidates": summary["candidates"], "summary": str(args.out_dir / "maigret_candidate_summary.json")}, ensure_ascii=False, indent=2))
    return 0 if summary["candidates"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edge-pack", type=Path, default=DEFAULT_EDGES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
