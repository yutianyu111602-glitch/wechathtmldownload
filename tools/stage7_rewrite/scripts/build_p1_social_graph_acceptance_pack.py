"""Build a report-only P1 social graph acceptance pack.

This merges source-validated Maigret hits and CDCR fallback source candidates
into a typed review pack for the next graph staging gate. It does not accept the
rows into Neo4j: every row remains graph_ready=false until identity review and a
separate staging writer/rollback gate exist.
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


DEFAULT_MAIGRET = Path("reports/p1_maigret_source_validation_20260515/maigret_source_validation.jsonl")
DEFAULT_CDCR = Path("reports/p1_cdcr_fallback_canary_20260515/cdcr_fallback_canary.jsonl")
DEFAULT_PUBLIC_LINKS = Path("reports/p1_public_social_link_validation_20260515/public_social_link_validation.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_social_graph_acceptance_pack_20260515")
SCHEMA_VERSION = "stage7_p1_social_graph_acceptance_pack.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for graph acceptance pack: {path}")


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


def first_text(value: Any) -> str:
    return str(value or "").strip()


def candidate_id(prefix: str, subject: str, source_url: str) -> str:
    raw = "|".join([prefix, subject, source_url])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def evidence_score_for_maigret(row: dict[str, Any]) -> float:
    score = 0.50
    if row.get("url_username_match"):
        score += 0.08
    if row.get("body_username_match"):
        score += 0.08
    if row.get("body_subject_match"):
        score += 0.08
    if row.get("accessible"):
        score += 0.06
    return min(round(score, 2), 0.75)


def evidence_score_for_cdcr(row: dict[str, Any]) -> float:
    score = 0.42
    if row.get("cdcr_match"):
        score += 0.05
    if row.get("artist_match"):
        score += 0.05
    if row.get("context_match"):
        score += 0.04
    if row.get("accessible"):
        score += 0.04
    return min(round(score, 2), 0.60)


def evidence_score_for_cdcr_direct(row: dict[str, Any]) -> float:
    confidence = row.get("confidence")
    if isinstance(confidence, (int, float)):
        return round(min(max(float(confidence), 0.0), 0.82), 2)
    score = 0.45
    if row.get("accessible"):
        score += 0.15
    if row.get("match_type") in {"name_exact", "name_context_match"}:
        score += 0.20
    if row.get("direct_source_candidate"):
        score += 0.10
    return min(round(score, 2), 0.82)


def public_validation_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in [first_text(row.get("url")), first_text(row.get("final_url")), first_text(row.get("normalized_url"))]:
            if key and key not in index:
                index[key] = row
    return index


def maigret_candidate(row: dict[str, Any], public_links: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if row.get("validation_status") != "source_validated":
        return None
    subject = first_text(row.get("subject_name") or row.get("username"))
    source_url = first_text(row.get("url") or row.get("final_url"))
    if not subject or not source_url:
        return None
    public_link = public_links.get(source_url) or public_links.get(first_text(row.get("final_url"))) or {}
    reasons = []
    for key, label in [
        ("url_username_match", "url contains candidate username"),
        ("body_username_match", "body contains candidate username"),
        ("body_subject_match", "body contains source subject name"),
        ("accessible", "public page reachable"),
    ]:
        if row.get(key):
            reasons.append(label)
    return {
        "schema_version": SCHEMA_VERSION + ".candidate",
        "candidate_id": candidate_id("maigret", subject, source_url),
        "candidate_source": "maigret_source_validation",
        "subject_name": subject,
        "source_family": first_text(row.get("source_family")),
        "source_platform": first_text(row.get("maigret_site_name")),
        "source_url": source_url,
        "final_url": first_text(row.get("final_url")) or source_url,
        "proposed_edge": "HAS_PROFILE",
        "evidence_text": "; ".join(reasons),
        "identity_match_reason": reasons,
        "negative_evidence": [
            "Maigret/public-page validation proves reachability and text match only.",
            "No direct owner confirmation or cross-platform account-control proof.",
        ],
        "evidence_confidence": evidence_score_for_maigret(row),
        "acceptance_status": "candidate_needs_identity_review",
        "graph_ready": False,
        "identity_proof": False,
        "rollback_key": f"p1_maigret:{subject}:{source_url}",
        "supporting_public_link_status": first_text(public_link.get("validation_status")),
        "source_row": row,
    }


def cdcr_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("schema_version") == "stage7_p1_cdcr_direct_source_validation.v1.row":
        return cdcr_direct_candidate(row)
    if row.get("fallback_status") != "fallback_source_candidate":
        return None
    subject = first_text(row.get("artist_name") or row.get("title"))
    source_url = first_text(row.get("search_url") or row.get("final_url"))
    if not subject or not source_url:
        return None
    reasons = []
    if row.get("accessible"):
        reasons.append("public Bilibili search page reachable")
    if row.get("cdcr_match"):
        reasons.append("page contains cdcr/cdcr.live token")
    if row.get("artist_match"):
        reasons.append("page contains artist token")
    if row.get("context_match"):
        reasons.append("page contains legacy context token")
    return {
        "schema_version": SCHEMA_VERSION + ".candidate",
        "candidate_id": candidate_id("cdcr", subject, source_url),
        "candidate_source": "cdcr_fallback_canary",
        "subject_name": subject,
        "source_family": "cdcr",
        "source_platform": "bilibili_search",
        "source_url": source_url,
        "final_url": first_text(row.get("final_url")) or source_url,
        "proposed_edge": "HAS_PUBLIC_CONTEXT_SOURCE",
        "evidence_text": "; ".join(reasons),
        "identity_match_reason": reasons,
        "negative_evidence": [
            "Bilibili search-result evidence is not a direct artist/source page.",
            "Legacy CDCR row is verification_status=legacy_unverified.",
            "No account-control or direct profile proof.",
        ],
        "evidence_confidence": evidence_score_for_cdcr(row),
        "acceptance_status": "candidate_needs_identity_review",
        "graph_ready": False,
        "identity_proof": False,
        "rollback_key": f"p1_cdcr:{subject}:{source_url}",
        "supporting_public_link_status": "",
        "source_row": row,
    }


def cdcr_direct_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    subject = first_text(row.get("subject_name"))
    source_url = first_text(row.get("source_url") or row.get("final_url"))
    if not subject or not source_url:
        return None
    reasons = []
    if row.get("accessible"):
        reasons.append("public direct-source candidate URL reachable")
    if row.get("match_type") in {"name_exact", "name_context_match"}:
        reasons.append("page contains CDCR subject token")
    if row.get("direct_source_candidate"):
        reasons.append("validator marked row as direct_source_candidate")
    if first_text(row.get("evidence_text")):
        reasons.append("bounded evidence snippet captured")
    source_type = first_text(row.get("source_type")) or first_text(row.get("platform")) or "unknown"
    return {
        "schema_version": SCHEMA_VERSION + ".candidate",
        "candidate_id": candidate_id("cdcr_direct", subject, source_url),
        "candidate_source": "cdcr_direct_source_validation",
        "subject_name": subject,
        "source_family": "cdcr",
        "source_platform": source_type,
        "source_url": source_url,
        "final_url": first_text(row.get("final_url")) or source_url,
        "proposed_edge": "HAS_PROFILE" if row.get("direct_source_candidate") else "HAS_PUBLIC_CONTEXT_SOURCE",
        "evidence_text": "; ".join(reasons),
        "identity_match_reason": reasons,
        "negative_evidence": [
            "CDCR direct-source validation is report-only evidence collection.",
            "No account-control proof; human identity review is still required before production use.",
        ],
        "evidence_confidence": evidence_score_for_cdcr_direct(row),
        "acceptance_status": "candidate_needs_identity_review",
        "graph_ready": False,
        "identity_proof": False,
        "rollback_key": f"p1_cdcr_direct:{subject}:{source_url}",
        "supporting_public_link_status": first_text(row.get("validation_status")),
        "source_row": row,
    }


def build_pack(
    maigret_path: Path,
    cdcr_path: Path,
    public_links_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    public_links = public_validation_index(read_jsonl(public_links_path))
    candidates: list[dict[str, Any]] = []
    for row in read_jsonl(maigret_path):
        candidate = maigret_candidate(row, public_links)
        if candidate:
            candidates.append(candidate)
    for row in read_jsonl(cdcr_path):
        candidate = cdcr_candidate(row)
        if candidate:
            candidates.append(candidate)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate["candidate_id"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    source_counts = Counter(row["candidate_source"] for row in deduped)
    platform_counts = Counter(row["source_platform"] for row in deduped)
    result_path = out_dir / "graph_acceptance_candidates.jsonl"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "p1_social_graph_acceptance_pack_review_ready" if deduped else "p1_social_graph_acceptance_pack_empty",
        "ok": bool(deduped),
        "maigret_path": str(maigret_path),
        "cdcr_path": str(cdcr_path),
        "public_links_path": str(public_links_path),
        "result_path": str(result_path),
        "candidates": len(deduped),
        "source_counts": dict(source_counts),
        "platform_counts": dict(platform_counts),
        "graph_ready_candidates": 0,
        "identity_proof_candidates": 0,
        "acceptance_status_counts": dict(Counter(row["acceptance_status"] for row in deduped)),
        "safety": [
            "reports_only",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
            "candidate_pack_is_not_graph_acceptance",
        ],
    }
    write_jsonl(result_path, deduped)
    write_json(out_dir / "graph_acceptance_pack_summary.json", report)
    write_markdown(out_dir / "graph_acceptance_pack_summary.md", report, deduped)
    return report


def write_markdown(path: Path, report: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    lines = [
        "# P1 Social Graph Acceptance Pack",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- candidates: `{report['candidates']}`",
        f"- graph_ready_candidates: `{report['graph_ready_candidates']}`",
        f"- identity_proof_candidates: `{report['identity_proof_candidates']}`",
        f"- result_path: `{report['result_path']}`",
        "",
        "## Source Counts",
        "",
    ]
    for key, value in sorted(report["source_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Candidate Rows",
            "",
            "| source | platform | subject | proposed_edge | confidence | graph_ready | source_url |",
            "|---|---|---|---|---:|---:|---|",
        ]
    )
    for row in candidates:
        lines.append(
            "| {source} | {platform} | {subject} | {edge} | {confidence} | {graph_ready} | {url} |".format(
                source=row["candidate_source"],
                platform=row["source_platform"],
                subject=first_text(row["subject_name"]).replace("|", "/"),
                edge=row["proposed_edge"],
                confidence=row["evidence_confidence"],
                graph_ready=row["graph_ready"],
                url=row["source_url"],
            )
        )
    lines.extend(
        [
            "",
            "## Required Next Gate Before Graph Write",
            "",
            "- Human/agent review must accept or reject each candidate.",
            "- Accepted rows need direct identity rationale, negative-evidence check, proposed typed edge, and rollback key.",
            "- A separate staging-only Neo4j writer must require an explicit confirmation token.",
            "",
            "## Safety",
            "",
            "- Reports only.",
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
    parser.add_argument("--maigret", type=Path, default=DEFAULT_MAIGRET)
    parser.add_argument("--cdcr", type=Path, default=DEFAULT_CDCR)
    parser.add_argument("--public-links", type=Path, default=DEFAULT_PUBLIC_LINKS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    report = build_pack(
        maigret_path=args.maigret,
        cdcr_path=args.cdcr,
        public_links_path=args.public_links,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "candidates": report["candidates"],
                "graph_ready_candidates": report["graph_ready_candidates"],
                "summary": str(args.out_dir / "graph_acceptance_pack_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["candidates"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
