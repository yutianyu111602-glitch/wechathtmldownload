#!/usr/bin/env python3
"""Build a read-only identity adjudication workbench packet for the atlas UI.

The source reports are existing Stage7 identity review artifacts. This script
does not fetch external pages, call models, or write graph/vector/database state.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
REPORT_ROOT = STAGE7_ROOT / "reports"
DEFAULT_OUT = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "stage7_atlas" / "identity_review_workbench.json"
DEFAULT_REPORT_DIR = REPORT_ROOT / "identity_review_workbench_138102_20260520"

SOURCE_CONFIGS = [
    {
        "id": "initial_adjudication",
        "label": "Initial identity adjudication",
        "summary": REPORT_ROOT
        / "external_identity_adjudication_47k_delta375_20260519"
        / "external_identity_adjudication_summary.json",
        "rows": REPORT_ROOT
        / "external_identity_adjudication_47k_delta375_20260519"
        / "external_identity_adjudication_review.jsonl",
    },
    {
        "id": "source_context_decision",
        "label": "Recovered source-context decision",
        "summary": REPORT_ROOT
        / "external_identity_source_context_decision_47k_delta375_20260519"
        / "source_context_decision_summary.json",
        "rows": REPORT_ROOT
        / "external_identity_source_context_decision_47k_delta375_20260519"
        / "source_context_decision.jsonl",
    },
    {
        "id": "future_direct_proof_review_gate",
        "label": "Future direct-proof review gate",
        "summary": REPORT_ROOT
        / "external_identity_future_direct_proof_review_gate_47k_delta375_20260519"
        / "source_followup_review_gate_summary.json",
        "rows": REPORT_ROOT
        / "external_identity_future_direct_proof_review_gate_47k_delta375_20260519"
        / "source_followup_review_gate.jsonl",
    },
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
            if limit and len(rows) >= limit:
                break
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def text(value: Any) -> str:
    return str(value or "").strip()


def domain_from_url(value: str) -> str:
    raw = text(value)
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    return raw.split("/", 1)[0].lower()


def normalize_initial(row: dict[str, Any], index: int) -> dict[str, Any]:
    context = row.get("context") if isinstance(row.get("context"), dict) else {}
    url = text(row.get("final_url") or row.get("url"))
    subject = text(context.get("subject_name") or row.get("username") or row.get("site_name") or domain_from_url(url))
    return {
        "id": f"initial:{row.get('row_index', index)}",
        "queue": "initial_adjudication",
        "bucket": text(row.get("adjudication_bucket") or row.get("review_tier") or "review_required"),
        "status": text(row.get("review_decision") or row.get("source_decision")),
        "subjectName": subject,
        "subjectType": text(context.get("subject_type")),
        "url": url,
        "domain": text(row.get("platform") or domain_from_url(url)),
        "sourceAccount": text(context.get("source_account")),
        "sourceArticleUid": text(context.get("source_article_uid")),
        "sourceTitle": text(context.get("source_title")),
        "supportCount": context.get("support_count") or 0,
        "identitySignalScore": row.get("identity_signal_score"),
        "reviewReason": text(row.get("review_reason")),
        "nextActions": row.get("next_actions") if isinstance(row.get("next_actions"), list) else [],
        "signals": row.get("signals") if isinstance(row.get("signals"), dict) else {},
        "acceptedForGraph": bool(row.get("accepted_for_graph")),
        "identityProof": bool(row.get("identity_proof")),
        "graphWriteAllowed": bool(row.get("graph_write_allowed")),
    }


def normalize_source_context(row: dict[str, Any], index: int) -> dict[str, Any]:
    url = text(row.get("url"))
    candidates = row.get("recovered_subject_candidates")
    if not isinstance(candidates, list):
        candidates = []
    return {
        "id": f"context:{row.get('row_index', index)}",
        "queue": "source_context_decision",
        "bucket": text(row.get("decision_bucket") or "review_only"),
        "status": text(row.get("decision_bucket")),
        "subjectName": text(row.get("subject_name") or (candidates[0] if candidates else "")),
        "subjectType": "/".join(row.get("candidate_types") or []) if isinstance(row.get("candidate_types"), list) else "",
        "url": url,
        "domain": text(row.get("domain") or domain_from_url(url)),
        "sourceAccount": "",
        "sourceArticleUid": text(row.get("source_article_uid")),
        "sourceTitle": text(row.get("source_title")),
        "supportCount": 0,
        "identitySignalScore": None,
        "reviewReason": "; ".join(row.get("decision_reasons") or []),
        "nextActions": ["manual_review_before_graph_acceptance"],
        "signals": {"handleHint": text(row.get("handle_hint")), "recoveredSubjectCandidates": candidates[:5]},
        "acceptedForGraph": bool(row.get("accepted_for_graph")),
        "identityProof": bool(row.get("identity_proof")),
        "graphWriteAllowed": bool(row.get("graph_write_allowed")),
    }


def normalize_followup_gate(row: dict[str, Any], index: int) -> dict[str, Any]:
    url = text(row.get("final_url") or row.get("url"))
    return {
        "id": f"followup:{row.get('row_index', index)}",
        "queue": "future_direct_proof_review_gate",
        "bucket": text(row.get("review_gate_decision") or "needs_more_source"),
        "status": text(row.get("followup_status")),
        "subjectName": text(row.get("subject_name") or domain_from_url(url)),
        "subjectType": "",
        "url": url,
        "domain": domain_from_url(url),
        "sourceAccount": "",
        "sourceArticleUid": text(row.get("source_article_uid")),
        "sourceTitle": text(row.get("source_title")),
        "supportCount": 0,
        "identitySignalScore": None,
        "reviewReason": text(row.get("review_gate_reason")),
        "nextActions": ["needs_stronger_source_backed_identity_text"],
        "signals": row.get("signals") if isinstance(row.get("signals"), dict) else {},
        "acceptedForGraph": bool(row.get("accepted_for_graph")),
        "identityProof": bool(row.get("identity_proof")),
        "graphWriteAllowed": bool(row.get("graph_write_allowed")),
    }


NORMALIZERS = {
    "initial_adjudication": normalize_initial,
    "source_context_decision": normalize_source_context,
    "future_direct_proof_review_gate": normalize_followup_gate,
}


def build_workbench(limit_per_source: int | None = None) -> dict[str, Any]:
    summaries = []
    items: list[dict[str, Any]] = []
    queue_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()

    for config in SOURCE_CONFIGS:
        summary = read_json(Path(config["summary"]))
        rows = read_jsonl(Path(config["rows"]), limit_per_source)
        normalizer = NORMALIZERS[str(config["id"])]
        normalized = [normalizer(row, index + 1) for index, row in enumerate(rows)]
        for item in normalized:
            queue_counts[item["queue"]] += 1
            bucket_counts[item["bucket"]] += 1
            domain_counts[item["domain"]] += 1
        items.extend(normalized)
        summaries.append(
            {
                "id": config["id"],
                "label": config["label"],
                "decision": summary.get("decision", ""),
                "ok": bool(summary.get("ok")),
                "generatedAt": summary.get("generated_at"),
                "inputRows": summary.get("input_rows") or summary.get("adjudicated_rows") or len(rows),
                "acceptedForGraph": summary.get("accepted_for_graph", 0),
                "reviewRows": len(rows),
                "summaryPath": str(config["summary"]),
                "rowsPath": str(config["rows"]),
            }
        )

    accepted = sum(1 for item in items if item["acceptedForGraph"])
    identity_proof = sum(1 for item in items if item["identityProof"])
    graph_write_allowed = sum(1 for item in items if item["graphWriteAllowed"])
    return {
        "schemaVersion": "stage7_atlas_identity_review_workbench.v1",
        "generatedAt": now_iso(),
        "decision": "identity_review_workbench_ready_read_only",
        "summary": {
            "sourceReportCount": len(summaries),
            "itemCount": len(items),
            "acceptedForGraph": accepted,
            "identityProofCount": identity_proof,
            "graphWriteAllowedCount": graph_write_allowed,
            "needsReviewCount": len(items) - accepted,
        },
        "sourceReports": summaries,
        "facets": {
            "queues": [{"label": key, "count": value} for key, value in queue_counts.most_common()],
            "buckets": [{"label": key, "count": value} for key, value in bucket_counts.most_common()],
            "domains": [{"label": key, "count": value} for key, value in domain_counts.most_common(30)],
        },
        "items": items,
        "safety": {
            "reportOnly": True,
            "networkCallExecuted": False,
            "modelCallExecuted": False,
            "graphWriteExecuted": False,
            "qdrantWriteExecuted": False,
            "sqliteWriteExecuted": False,
            "mem0WriteExecuted": False,
            "paidApiUsed": False,
            "cookieOrTokenExported": False,
            "dScanExecuted": False,
        },
    }


def write_markdown(path: Path, payload: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Atlas Identity Review Workbench",
        "",
        f"- generated_at: `{payload['generatedAt']}`",
        f"- decision: `{payload['decision']}`",
        f"- output: `{output_path}`",
        f"- items: `{payload['summary']['itemCount']}`",
        f"- accepted_for_graph: `{payload['summary']['acceptedForGraph']}`",
        f"- graph_write_allowed: `{payload['summary']['graphWriteAllowedCount']}`",
        "",
        "## Source Reports",
        "",
    ]
    for report in payload["sourceReports"]:
        lines.append(
            f"- `{report['id']}` decision=`{report['decision']}` rows=`{report['reviewRows']}` accepted=`{report['acceptedForGraph']}`"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Read-only packet build. No network, model, Qdrant, Neo4j, SQLite, mem0, paid API, cookie/token export, or D: scan.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--limit-per-source", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_workbench(limit_per_source=args.limit_per_source or None)
    write_json(args.out, payload)
    write_json(args.report_dir / "identity_review_workbench.json", payload)
    write_markdown(args.report_dir / "identity_review_workbench.md", payload, args.out)
    print(
        json.dumps(
            {
                "ok": True,
                "decision": payload["decision"],
                "items": payload["summary"]["itemCount"],
                "accepted_for_graph": payload["summary"]["acceptedForGraph"],
                "output": str(args.out),
                "report": str(args.report_dir / "identity_review_workbench.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
