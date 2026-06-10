#!/usr/bin/env python3
"""Build a strict report-only identity acceptance review for PRD-16.

This gate accepts only rows that already have strong deterministic identity
review, OpenCLI rendered profile evidence, a profile image hash, and at least
one subject-matching external profile link. It does not browse, log in, export
cookies/tokens, perform social actions, or write Neo4j/Qdrant/mem0/SQLite.
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


DEFAULT_OPENCLI_EVIDENCE = Path("reports/opencli_social_profile_evidence_20260516/social_profile_evidence.jsonl")
DEFAULT_OPENCLI_REVIEW = Path("reports/opencli_social_identity_review_20260516/opencli_identity_review.jsonl")
DEFAULT_IDENTITY_REVIEW = Path("reports/social_identity_cross_evidence_20260515/identity_cross_evidence_review.jsonl")
DEFAULT_CDCR_REVIEW = Path("reports/p1_cdcr_direct_source_review_20260516/cdcr_direct_source_review.jsonl")
DEFAULT_OUT_DIR = Path("reports/social_identity_strict_acceptance_review_20260517")
SCHEMA_VERSION = "stage7_social_identity_strict_acceptance_review.v1"
GATE_ID = "stage7_prd16_strict_public_profile_external_link_20260517"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for strict social identity acceptance: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
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


def normalize_compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def normalize_words(value: str) -> list[str]:
    return [part for part in re.split(r"[^0-9a-z\u4e00-\u9fff]+", value.casefold()) if part]


def contains_all_subject_words(subject: str, haystack: str) -> bool:
    words = normalize_words(subject)
    if not words:
        return False
    compact = normalize_compact(haystack)
    return all(word and word in compact for word in words)


def external_links(row: dict[str, Any]) -> list[dict[str, Any]]:
    value = row.get("external_links")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def row_haystack(row: dict[str, Any]) -> str:
    link_text = " ".join(
        first_text(item.get("text")) + " " + first_text(item.get("url")) + " " + first_text(item.get("domain"))
        for item in external_links(row)
    )
    return " ".join(
        [
            first_text(row.get("profile_display_name")),
            first_text(row.get("profile_handle")),
            first_text(row.get("rendered_title")),
            first_text(row.get("bio_excerpt")),
            first_text(row.get("canonical_url")),
            first_text(row.get("final_url")),
            link_text,
        ]
    )


def has_subject_matching_external_link(subject: str, row: dict[str, Any]) -> bool:
    own_domain = first_text(row.get("domain")).casefold()
    for item in external_links(row):
        domain = first_text(item.get("domain")).casefold()
        if not domain or domain == own_domain:
            continue
        link_text = " ".join([first_text(item.get("text")), first_text(item.get("url")), domain])
        if contains_all_subject_words(subject, link_text):
            return True
    return False


def review_row(
    evidence: dict[str, Any],
    *,
    opencli_review_by_id: dict[str, dict[str, Any]],
    identity_by_id: dict[str, dict[str, Any]],
    cdcr_subjects: set[str],
) -> dict[str, Any]:
    source_row_id = first_text(evidence.get("source_row_id"))
    opencli = opencli_review_by_id.get(source_row_id, {})
    identity = identity_by_id.get(source_row_id, {})
    subject = first_text(evidence.get("subject_name") or opencli.get("subject_name") or identity.get("subject_name"))
    signals = {
        "opencli_report_ready": first_text(evidence.get("decision")) == "report_ready",
        "unsafe_action_false": evidence.get("unsafe_action") is False,
        "no_opencli_error": not first_text(evidence.get("opencli_error")),
        "source_status_strong": first_text(evidence.get("source_status")) == "strong_review_candidate",
        "identity_review_strong": first_text(identity.get("review_tier")) == "strong_review_candidate",
        "opencli_review_strong": first_text(opencli.get("review_tier")) == "strong_opencli_review_candidate",
        "subject_in_rendered_profile": contains_all_subject_words(subject, row_haystack(evidence)),
        "profile_image_hash_present": first_text(evidence.get("profile_image_url_or_hash")).startswith("sha256:"),
        "subject_matching_external_link_present": has_subject_matching_external_link(subject, evidence),
        "public_source_url_present": first_text(evidence.get("evidence_url")).startswith("http"),
        "supported_profile_platform": first_text(evidence.get("platform")) in {"bandcamp", "soundcloud"},
    }
    accepted = all(signals.values())
    row = {
        "schema_version": SCHEMA_VERSION + ".row",
        "acceptance_gate_id": GATE_ID,
        "source_row_id": source_row_id,
        "subject_name": subject,
        "object_url": first_text(evidence.get("canonical_url") or evidence.get("final_url") or evidence.get("input_url")),
        "object_platform": first_text(evidence.get("platform")),
        "profile_display_name": first_text(evidence.get("profile_display_name")),
        "profile_handle": first_text(evidence.get("profile_handle")),
        "evidence_url": first_text(evidence.get("evidence_url")),
        "opencli_review_tier": first_text(opencli.get("review_tier")),
        "identity_review_tier": first_text(identity.get("review_tier")),
        "external_link_domains": sorted(
            {first_text(item.get("domain")) for item in external_links(evidence) if first_text(item.get("domain"))}
        ),
        "signals": signals,
        "accepted_for_staging": accepted,
        "graph_ready": accepted,
        "identity_proof": accepted,
        "proof_tier": "strict_public_profile_external_link" if accepted else "not_accepted",
        "review_status": "accepted_for_staging" if accepted else "strict_acceptance_rejected",
        "review_reason": (
            "Strong source-backed identity row with rendered profile, profile hash, and subject-matching external link."
            if accepted
            else "Strict public-profile external-link acceptance criteria not fully met."
        ),
        "cdcr_subject_overlap": normalize_compact(subject) in cdcr_subjects,
        "staging_only": True,
        "write_allowed": False,
        "rollback_key": GATE_ID,
    }
    return row


def build_review(
    *,
    opencli_evidence_path: Path,
    opencli_review_path: Path,
    identity_review_path: Path,
    cdcr_review_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    evidence_rows = read_jsonl(opencli_evidence_path)
    opencli_review_rows = read_jsonl(opencli_review_path)
    identity_rows = read_jsonl(identity_review_path)
    cdcr_rows = read_jsonl(cdcr_review_path)
    opencli_review_by_id = {first_text(row.get("source_row_id")): row for row in opencli_review_rows}
    identity_by_id = {first_text(row.get("edge_id")): row for row in identity_rows}
    cdcr_subjects = {normalize_compact(first_text(row.get("subject_name"))) for row in cdcr_rows if row.get("subject_name")}

    review_rows = [
        review_row(
            row,
            opencli_review_by_id=opencli_review_by_id,
            identity_by_id=identity_by_id,
            cdcr_subjects=cdcr_subjects,
        )
        for row in evidence_rows
    ]
    accepted_rows = [row for row in review_rows if row["accepted_for_staging"]]
    rejected_rows = [row for row in review_rows if not row["accepted_for_staging"]]
    platform_counts = Counter(first_text(row.get("object_platform")) or "unknown" for row in accepted_rows)
    accepted_subjects = sorted({first_text(row.get("subject_name")) for row in accepted_rows})
    cdcr_overlap = sum(1 for row in accepted_rows if row.get("cdcr_subject_overlap"))

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "social_identity_strict_acceptance_review.jsonl"
    accepted_path = out_dir / "accepted_social_edges_strict.jsonl"
    write_jsonl(review_path, review_rows)
    write_jsonl(accepted_path, accepted_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": (
            "social_identity_strict_acceptance_ready"
            if accepted_rows
            else "social_identity_strict_acceptance_no_rows_accepted"
        ),
        "acceptance_gate_id": GATE_ID,
        "opencli_evidence_path": str(opencli_evidence_path),
        "opencli_review_path": str(opencli_review_path),
        "identity_review_path": str(identity_review_path),
        "cdcr_review_path": str(cdcr_review_path),
        "review_path": str(review_path),
        "accepted_edges_path": str(accepted_path),
        "review_rows": len(review_rows),
        "accepted_edges": len(accepted_rows),
        "rejected_rows": len(rejected_rows),
        "accepted_subjects": accepted_subjects,
        "accepted_platform_counts": dict(platform_counts),
        "cdcr_subject_overlap_accepted_count": cdcr_overlap,
        "acceptance_policy": [
            "existing OpenCLI report row only; no new network call",
            "unsafe_action must be false and no OpenCLI error may be present",
            "source_status and deterministic identity review must both be strong",
            "OpenCLI review tier must be strong_opencli_review_candidate",
            "subject must appear in rendered profile evidence",
            "profile image hash must be present",
            "at least one external profile link on another domain must include the subject",
            "only Bandcamp/SoundCloud public profile rows are accepted by this gate",
        ],
        "blockers": [
            "accepted rows are report-only and require a separate Neo4j staging write gate before graph use",
            "production graph labels remain forbidden",
            "rows rejected by the strict policy remain review candidates only",
        ],
        "safety": {
            "reports_only": True,
            "existing_evidence_only": True,
            "no_network_calls": True,
            "no_login": True,
            "no_cookie_token_export": True,
            "no_account_action": True,
            "no_private_collection": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "reports_only",
    }
    write_json(out_dir / "social_identity_strict_acceptance_review.json", summary)
    write_markdown(out_dir / "social_identity_strict_acceptance_review.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Social Identity Strict Acceptance Review",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- review_rows: `{summary['review_rows']}`",
        f"- accepted_edges: `{summary['accepted_edges']}`",
        f"- rejected_rows: `{summary['rejected_rows']}`",
        f"- cdcr_subject_overlap_accepted_count: `{summary['cdcr_subject_overlap_accepted_count']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        "",
        "## Accepted Subjects",
        "",
    ]
    if summary["accepted_subjects"]:
        lines.extend(f"- {item}" for item in summary["accepted_subjects"])
    else:
        lines.append("- none")
    lines.extend(["", "## Acceptance Policy", ""])
    lines.extend(f"- {item}" for item in summary["acceptance_policy"])
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencli-evidence", type=Path, default=DEFAULT_OPENCLI_EVIDENCE)
    parser.add_argument("--opencli-review", type=Path, default=DEFAULT_OPENCLI_REVIEW)
    parser.add_argument("--identity-review", type=Path, default=DEFAULT_IDENTITY_REVIEW)
    parser.add_argument("--cdcr-review", type=Path, default=DEFAULT_CDCR_REVIEW)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_review(
        opencli_evidence_path=args.opencli_evidence,
        opencli_review_path=args.opencli_review,
        identity_review_path=args.identity_review,
        cdcr_review_path=args.cdcr_review,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "review_rows": summary["review_rows"],
                "accepted_edges": summary["accepted_edges"],
                "cdcr_subject_overlap_accepted_count": summary["cdcr_subject_overlap_accepted_count"],
                "summary": str(args.out_dir / "social_identity_strict_acceptance_review.json"),
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
