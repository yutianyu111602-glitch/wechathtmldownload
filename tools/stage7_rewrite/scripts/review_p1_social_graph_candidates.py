"""Review P1 social graph candidates before any Neo4j staging write.

This gate converts the report-only graph acceptance candidate pack into a
reviewed candidate report and a small accepted-social-edges input. It remains
conservative: CDCR search-result candidates and Maigret breadth-only profiles
are not accepted for graph staging without direct source-link evidence.
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
from urllib import parse


DEFAULT_CANDIDATES = Path("reports/p1_social_graph_acceptance_pack_20260515/graph_acceptance_candidates.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_social_candidate_review_20260515")
SCHEMA_VERSION = "stage7_p1_social_candidate_review.v1"

DIRECT_PROFILE_PLATFORMS = {"instagram", "soundcloud", "bandcamp", "youtube", "bilibili"}
MANUAL_REVIEW_PLATFORMS = {"github", "githubgist", "reddit"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for social candidate review: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
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


def first_text(value: Any) -> str:
    return str(value or "").strip()


def normalized_url(value: str) -> str:
    parsed = parse.urlparse(first_text(value))
    if not parsed.scheme or not parsed.netloc:
        return first_text(value).rstrip("/")
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/") or "/"
    return parse.urlunparse((parsed.scheme.lower(), host, path, "", parsed.query, ""))


def normalized_platform(value: str) -> str:
    text = first_text(value).casefold()
    text = text.replace(" [github]", "")
    return "".join(ch for ch in text if ch.isalnum())


def edge_id(row: dict[str, Any]) -> str:
    raw = "|".join([row["edge_type"], row["subject_name"], row["object_url"], row["evidence_url"]])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def direct_profile_evidence(candidate: dict[str, Any]) -> dict[str, Any] | None:
    source_urls = {
        normalized_url(first_text(candidate.get("source_url"))),
        normalized_url(first_text(candidate.get("final_url"))),
    }
    for evidence in ((candidate.get("source_row") or {}).get("candidate_evidence") or []):
        if first_text(evidence.get("edge_type")) != "HAS_PROFILE":
            continue
        object_url = normalized_url(first_text(evidence.get("object_url")))
        if object_url and object_url in source_urls:
            return evidence
    return None


def review_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    reviewed = dict(candidate)
    reviewed["reviewed_at"] = now_iso()
    reviewed["schema_version"] = SCHEMA_VERSION + ".candidate"
    reviewed["review_notes"] = []

    source = first_text(candidate.get("candidate_source"))
    platform = normalized_platform(first_text(candidate.get("source_platform")))
    source_row = candidate.get("source_row") or {}
    direct_evidence = direct_profile_evidence(candidate)

    if source == "cdcr_fallback_canary":
        reviewed["review_status"] = "needs_direct_source_page"
        reviewed["graph_ready"] = False
        reviewed["review_notes"].append("CDCR evidence is a Bilibili search result, not a direct source/profile page.")
        return reviewed

    if source == "cdcr_direct_source_validation":
        reviewed["review_status"] = "needs_manual_identity_review"
        reviewed["graph_ready"] = False
        reviewed["review_notes"].append(
            "CDCR direct-source candidate is useful evidence but remains report-only until identity review."
        )
        return reviewed

    if source != "maigret_source_validation":
        reviewed["review_status"] = "needs_manual_identity_review"
        reviewed["graph_ready"] = False
        reviewed["review_notes"].append("Unsupported candidate source for automatic staging review.")
        return reviewed

    if platform not in DIRECT_PROFILE_PLATFORMS:
        reviewed["review_status"] = "needs_manual_identity_review"
        reviewed["graph_ready"] = False
        reviewed["review_notes"].append("Breadth profile is useful evidence but not a default music/social profile edge.")
        return reviewed

    if not direct_evidence:
        reviewed["review_status"] = "needs_direct_profile_link"
        reviewed["graph_ready"] = False
        reviewed["review_notes"].append("No matching HAS_PROFILE link from source-scored byyb/baihui evidence.")
        return reviewed

    required_matches = [
        bool(source_row.get("accessible")),
        bool(source_row.get("url_username_match")),
        bool(source_row.get("body_username_match") or source_row.get("body_subject_match")),
    ]
    if not all(required_matches):
        reviewed["review_status"] = "needs_manual_identity_review"
        reviewed["graph_ready"] = False
        reviewed["review_notes"].append("Direct profile link exists but public-page matching evidence is incomplete.")
        return reviewed

    reviewed["review_status"] = "accepted_for_staging"
    reviewed["graph_ready"] = True
    reviewed["identity_proof"] = False
    reviewed["review_notes"].append("Accepted for staging only: direct source HAS_PROFILE link plus public page username/subject match.")
    reviewed["direct_evidence"] = direct_evidence
    return reviewed


def accepted_edge(reviewed: dict[str, Any]) -> dict[str, Any]:
    evidence = reviewed.get("direct_evidence") or {}
    row = {
        "schema_version": SCHEMA_VERSION + ".accepted_edge",
        "edge_type": "HAS_PROFILE",
        "subject_name": first_text(reviewed.get("subject_name")),
        "source_family": first_text(reviewed.get("source_family")),
        "object_url": first_text(reviewed.get("final_url") or reviewed.get("source_url")),
        "object_platform": first_text(reviewed.get("source_platform")),
        "evidence_url": first_text(evidence.get("evidence_url")),
        "source_candidate_id": first_text(reviewed.get("candidate_id")),
        "source_edge_id": first_text(evidence.get("edge_id")),
        "confidence": min(float(reviewed.get("evidence_confidence") or 0.82), 0.88),
        "review_status": "accepted_for_staging",
        "staging_only": True,
        "production_ready": False,
        "identity_proof": False,
        "rollback_key": first_text(reviewed.get("rollback_key")),
        "review_notes": reviewed.get("review_notes") or [],
    }
    row["edge_id"] = edge_id(row)
    return row


def build_review(candidates_path: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    candidates = read_jsonl(candidates_path)
    reviewed = [review_candidate(candidate) for candidate in candidates]
    accepted = [accepted_edge(row) for row in reviewed if row.get("review_status") == "accepted_for_staging"]
    status_counts = Counter(first_text(row.get("review_status")) for row in reviewed)
    reviewed_path = out_dir / "reviewed_graph_candidates.jsonl"
    accepted_path = out_dir / "accepted_social_edges.jsonl"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "p1_social_candidate_review_ready" if reviewed else "p1_social_candidate_review_empty",
        "ok": bool(reviewed),
        "candidates_path": str(candidates_path),
        "reviewed_path": str(reviewed_path),
        "accepted_edges_path": str(accepted_path),
        "candidates_reviewed": len(reviewed),
        "accepted_for_staging": len(accepted),
        "graph_ready_candidates": len(accepted),
        "identity_proof_candidates": 0,
        "review_status_counts": dict(status_counts),
        "safety": [
            "reports_only",
            "accepted_edges_are_staging_only",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
    }
    write_jsonl(reviewed_path, reviewed)
    write_jsonl(accepted_path, accepted)
    write_json(out_dir / "social_candidate_review_summary.json", report)
    write_markdown(out_dir / "social_candidate_review_summary.md", report, reviewed)
    return report


def write_markdown(path: Path, report: dict[str, Any], reviewed: list[dict[str, Any]]) -> None:
    lines = [
        "# P1 Social Candidate Review",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- candidates_reviewed: `{report['candidates_reviewed']}`",
        f"- accepted_for_staging: `{report['accepted_for_staging']}`",
        f"- graph_ready_candidates: `{report['graph_ready_candidates']}`",
        f"- identity_proof_candidates: `{report['identity_proof_candidates']}`",
        f"- accepted_edges_path: `{report['accepted_edges_path']}`",
        "",
        "## Review Status Counts",
        "",
    ]
    for key, value in sorted(report["review_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Reviewed Candidates",
            "",
            "| status | platform | subject | source | graph_ready | source_url |",
            "|---|---|---|---|---:|---|",
        ]
    )
    for row in reviewed:
        lines.append(
            "| {status} | {platform} | {subject} | {source} | {graph_ready} | {url} |".format(
                status=row.get("review_status"),
                platform=first_text(row.get("source_platform")).replace("|", "/"),
                subject=first_text(row.get("subject_name")).replace("|", "/"),
                source=row.get("candidate_source"),
                graph_ready=row.get("graph_ready"),
                url=row.get("source_url"),
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Accepted rows are staging-only and not production identity proof.",
            "- CDCR search-result rows are not accepted for graph staging without direct source pages.",
            "- No graph/vector/DB write.",
            "- No paid API.",
            "- No D: scan.",
            "- No publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    report = build_review(args.candidates, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "candidates_reviewed": report["candidates_reviewed"],
                "accepted_for_staging": report["accepted_for_staging"],
                "summary": str(args.out_dir / "social_candidate_review_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["candidates_reviewed"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
