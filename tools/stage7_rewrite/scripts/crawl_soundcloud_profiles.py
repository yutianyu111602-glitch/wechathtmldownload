#!/usr/bin/env python3
"""Run a PRD-16 public SoundCloud profile canary.

This canary reads candidate profile URLs, fetches public pages, extracts the
page title, and writes report-only outputs. It does not log in, use cookies,
fetch audio, or mutate graph/vector/DB state.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_public_social_links as link_validator  # noqa: E402


DEFAULT_CANDIDATES = Path("reports/social_deep_candidates_20260515/soundcloud_urls.jsonl")
DEFAULT_OUT_DIR = Path("reports/soundcloud_canary_20260515")
SCHEMA_VERSION = "stage7_social_deep_profile_canary.v1"


PROFILE_KINDS_BY_PLATFORM = {
    "soundcloud": {"profile"},
    "bandcamp": {"profile"},
    "linktree": {"aggregator_profile"},
    "residentadvisor": {"profile_or_event"},
    "youtube": {"profile_or_channel"},
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for PRD-16 profile canary: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "candidates")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
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


def select_profile_candidates(candidates: list[dict[str, Any]], platform: str, limit: int) -> list[dict[str, Any]]:
    allowed_kinds = PROFILE_KINDS_BY_PLATFORM.get(platform, {"profile"})
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        if first_text(row.get("platform")) != platform:
            continue
        kind = first_text(row.get("link_kind")) or link_validator.link_kind(first_text(row.get("url")))
        if kind not in allowed_kinds:
            continue
        normalized = first_text(row.get("normalized_url")) or link_validator.normalize_url(first_text(row.get("url")))
        if normalized in seen:
            continue
        seen.add(normalized)
        enriched = dict(row)
        enriched["link_kind"] = kind
        enriched["normalized_url"] = normalized
        selected.append(enriched)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def candidate_to_validation_item(candidate: dict[str, Any], platform: str) -> dict[str, Any]:
    url = first_text(candidate.get("url"))
    return {
        "source": first_text(candidate.get("source")) or "social_deep_candidates",
        "source_family": first_text(candidate.get("source_family")),
        "subject_name": first_text(candidate.get("subject_name")),
        "edge_id": first_text(candidate.get("edge_id")),
        "edge_type": first_text(candidate.get("edge_type")) or "HAS_PROFILE",
        "evidence_url": first_text(candidate.get("evidence_url")),
        "url": url,
        "normalized_url": first_text(candidate.get("normalized_url")) or link_validator.normalize_url(url),
        "platform": platform,
        "link_kind": first_text(candidate.get("link_kind")) or link_validator.link_kind(url),
    }


def run_profile_canary(
    candidates_path: Path,
    out_dir: Path,
    platform: str,
    limit: int,
    expected_min_profiles: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Callable[[str, float, int], dict[str, Any]] = link_validator.fetch_url,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    candidates = read_jsonl(candidates_path)
    profile_candidates = select_profile_candidates(candidates, platform=platform, limit=limit)
    results: list[dict[str, Any]] = []
    for candidate in profile_candidates:
        item = candidate_to_validation_item(candidate, platform)
        row = link_validator.evaluate_link(item, fetcher(item["url"], timeout_sec, max_bytes))
        row.update(
            {
                "schema_version": SCHEMA_VERSION + ".row",
                "canary_platform": platform,
                "profile_canary_status": "profile_reachable" if row["accessible"] else "profile_blocked_or_unreachable",
                "public_metadata": {
                    "page_title": row["page_title"],
                    "final_url": row["final_url"],
                    "status_code": row["status_code"],
                },
                "graph_ready": False,
                "identity_proof": False,
            }
        )
        results.append(row)

    status_counts = Counter(row["profile_canary_status"] for row in results)
    reachable = status_counts.get("profile_reachable", 0)
    gate_met = reachable >= expected_min_profiles
    if gate_met:
        decision = f"{platform}_profile_canary_gate_met"
    elif results and reachable:
        decision = f"{platform}_profile_canary_partial"
    elif results:
        decision = f"{platform}_profile_canary_blocked"
    else:
        decision = f"{platform}_profile_canary_empty"

    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / f"{platform}_profile_canary.jsonl"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": bool(results),
        "platform": platform,
        "candidates_path": str(candidates_path),
        "result_path": str(result_path),
        "candidate_rows_seen": len(candidates),
        "candidate_profile_rows_checked": len(results),
        "profiles_reachable": reachable,
        "profiles_blocked_or_unreachable": status_counts.get("profile_blocked_or_unreachable", 0),
        "expected_min_profiles": expected_min_profiles,
        "gate_met": gate_met,
        "limit": limit,
        "status_counts": dict(status_counts),
        "graph_ready_links": 0,
        "identity_proof_links": 0,
        "safety": [
            "reports_only",
            "public_urls_only",
            "no_login",
            "no_cookies",
            "no_audio_download",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
            "public_profile_reachability_is_not_identity_proof",
        ],
    }
    write_jsonl(result_path, results)
    write_json(out_dir / f"{platform}_profile_canary_summary.json", summary)
    write_markdown(out_dir / f"{platform}_profile_canary_summary.md", summary, results)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        f"# PRD-16 {summary['platform'].title()} Public Profile Canary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- candidate_profile_rows_checked: `{summary['candidate_profile_rows_checked']}`",
        f"- profiles_reachable: `{summary['profiles_reachable']}`",
        f"- expected_min_profiles: `{summary['expected_min_profiles']}`",
        f"- gate_met: `{summary['gate_met']}`",
        f"- result_path: `{summary['result_path']}`",
        "",
        "## Rows",
        "",
        "| subject | status | http | url | title |",
        "|---|---|---:|---|---|",
    ]
    for row in results:
        title = first_text(row.get("page_title")).replace("|", "/")
        subject = first_text(row.get("subject_name")).replace("|", "/")
        lines.append(
            f"| {subject} | {row['profile_canary_status']} | {row.get('status_code') or ''} | {row['url']} | {title} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Public profile reachability is not identity proof.",
            "- No login, cookies, audio download, graph/vector/DB write, paid API, D: scan, or publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--expected-min-profiles", type=int, default=10)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--max-bytes", type=int, default=256_000)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = run_profile_canary(
        candidates_path=args.candidates,
        out_dir=args.out_dir,
        platform="soundcloud",
        limit=args.limit,
        expected_min_profiles=args.expected_min_profiles,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "profiles_reachable": summary["profiles_reachable"],
                "summary": str(args.out_dir / "soundcloud_profile_canary_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
