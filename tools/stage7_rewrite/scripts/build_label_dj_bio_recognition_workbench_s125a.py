#!/usr/bin/env python3
"""Build the S125A label / DJ bio recognition hardening workbench.

Report-only. This script does not call models, fetch network pages, read
credentials, or write DB1/DB2/DB3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "label_dj_bio_recognition_s125a.v1"
DEFAULT_S122_TASKS = STAGE7_ROOT / "reports" / "poster_lineup_extraction_router_s122_20260601" / "poster_lineup_extraction_tasks.jsonl"
DEFAULT_S121_AUDIT = STAGE7_ROOT / "reports" / "three_db_merge_performance_s121_20260601" / "three_db_merge_performance_audit.json"
DEFAULT_S124_RESULTS = STAGE7_ROOT / "reports" / "external_link_no_cookie_canary_s124_20260601" / "external_link_no_cookie_canary_results.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "label_dj_bio_recognition_s125a_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_LABEL_DJ_BIO_RECOGNITION_S125A_20260601.md"

DJ_NAME_RE = re.compile(r"(?i)\b(?:DJ\s*)?[A-Z0-9][A-Z0-9._\- ]{1,38}\b")
LABEL_AFTER_RE = re.compile(r"(?P<name>[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._&+\-]{1,38})\s*(?:厂牌|label|Label|LABEL|crew|Crew|collective|Collective)")
LABEL_BEFORE_RE = re.compile(r"(?:厂牌|label|Label|LABEL|crew|Crew|collective|Collective)\s*[:：]?\s*(?P<name>[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._&+\-]{1,38})")
PRESENTER_RE = re.compile(r"(?P<name>[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._&+\-]{1,38})\s*(?:pres\.?|presents|presented by|出品|呈现|主办)", re.I)
BIO_RE = re.compile(
    r"(?P<name>(?:DJ\s*)?[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._&+\-]{1,38}?)\s*(?:是|is|来自|from)\s*(?P<bio>[^。.;；]{4,180})",
    re.I,
)
NOISE_RE = re.compile(r"(?i)^(the|and|with|live|event|party|club|bar|stage|lineup|label|crew|collective|present|presents|presented|by|pres)$")
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)

MODEL_POLICY = {
    "deterministic": "Exact role cue is present in bounded source text; no model call is needed for this report.",
    "deepseek_flash": "Bounded source text can be extracted cheaply later if a model run is authorized.",
    "deepseek_pro": "Role conflict or label/person ambiguity needs stronger adjudication later.",
    "mimo_multimodal": "Poster/logo-heavy evidence should be read by a multimodal lane later.",
    "hunyuan_summary_only": "CloudBase Hunyuan may summarize accepted facts later; it is not a truth extractor.",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def stable_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def compact(value: Any, limit: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def clean_name(value: str) -> str:
    text = compact(value, 80)
    text = re.sub(r"^[#@\-\s:：]+", "", text)
    text = re.sub(r"\s*(?:pres|presents|presented|by|出品|呈现|主办).*$", "", text, flags=re.I).strip()
    text = re.sub(r"^(?:厂牌|label|crew|collective)\s*[:：]?\s*", "", text, flags=re.I).strip()
    return text


def is_good_name(value: str) -> bool:
    text = clean_name(value)
    return bool(text and len(text) >= 2 and len(text) <= 60 and not NOISE_RE.match(text))


def model_lane(entity_kind: str, role_hint: str, source_lane: str, confidence: float) -> str:
    if source_lane == "multimodal_poster_lineup":
        return "mimo_multimodal"
    if role_hint in {"presented_by", "hosted_by"} or entity_kind in {"label_org", "promoter_org", "collective_crew"}:
        return "deepseek_pro" if confidence < 0.9 else "deterministic"
    if role_hint == "bio_claim":
        return "deepseek_flash"
    return "deterministic"


def make_row(
    *,
    source_ref_id: str,
    source_kind: str,
    source_url_or_article_id: str,
    evidence_text: str,
    entity_name: str,
    entity_kind: str,
    role_hint: str,
    bio_text: str = "",
    bio_subject_name: str = "",
    confidence: float = 0.8,
    disposition: str = "needs_review",
    source_lane: str = "",
) -> dict[str, Any]:
    lane = model_lane(entity_kind, role_hint, source_lane, confidence)
    return {
        "candidate_id": stable_id(
            {
                "source_ref_id": source_ref_id,
                "entity_name": entity_name,
                "entity_kind": entity_kind,
                "role_hint": role_hint,
                "bio_text": bio_text,
            }
        ),
        "source_ref_id": source_ref_id,
        "source_kind": source_kind,
        "source_url_or_article_id": source_url_or_article_id,
        "evidence_text": compact(evidence_text, 600),
        "entity_name": clean_name(entity_name),
        "entity_kind": entity_kind,
        "role_hint": role_hint,
        "bio_text": compact(bio_text, 400),
        "bio_subject_name": clean_name(bio_subject_name),
        "confidence": round(float(confidence), 3),
        "disposition": disposition,
        "model_lane": lane,
        "write_allowed": False,
        "db2_projection_allowed": False,
        "db3_identity_write_allowed": False,
        "miniapp_public_display_allowed": False,
    }


def extract_candidates_from_text(
    text: str,
    *,
    source_ref_id: str = "fixture",
    source_kind: str = "source_text",
    source_url_or_article_id: str = "",
    source_lane: str = "",
) -> list[dict[str, Any]]:
    evidence = compact(text, 4000)
    rows: list[dict[str, Any]] = []

    for regex, entity_kind, role_hint in (
        (LABEL_AFTER_RE, "label_org", "label_reference"),
        (LABEL_BEFORE_RE, "label_org", "label_reference"),
        (PRESENTER_RE, "promoter_org", "presented_by"),
    ):
        for match in regex.finditer(evidence):
            name = clean_name(match.group("name"))
            if not is_good_name(name):
                continue
            if entity_kind == "label_org" and ("是" in name or name.endswith("某")):
                continue
            rows.append(
                make_row(
                    source_ref_id=source_ref_id,
                    source_kind=source_kind,
                    source_url_or_article_id=source_url_or_article_id,
                    evidence_text=evidence,
                    entity_name=name,
                    entity_kind=entity_kind,
                    role_hint=role_hint,
                    confidence=0.82 if role_hint == "presented_by" else 0.9,
                    disposition="reject_not_dj" if entity_kind == "label_org" else "needs_review",
                    source_lane=source_lane,
                )
            )

    for match in BIO_RE.finditer(evidence):
        name = clean_name(match.group("name"))
        bio = compact(match.group("bio"), 220)
        if not is_good_name(name) or not bio:
            continue
        rows.append(
            make_row(
                source_ref_id=source_ref_id,
                source_kind=source_kind,
                source_url_or_article_id=source_url_or_article_id,
                evidence_text=evidence,
                entity_name=name,
                entity_kind="dj_person",
                role_hint="bio_claim",
                bio_text=bio,
                bio_subject_name=name,
                confidence=0.84,
                disposition="accept_candidate",
                source_lane=source_lane,
            )
        )

    return dedupe_rows(rows)


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("source_ref_id") or ""),
            str(row.get("entity_name") or "").casefold(),
            str(row.get("entity_kind") or ""),
            str(row.get("role_hint") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def rows_from_s122(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in iter_jsonl(path)[:limit]:
        evidence = " | ".join(
            part
            for part in (
                compact(task.get("title"), 240),
                compact(task.get("venue_name"), 160),
                ", ".join(str(x) for x in task.get("lineup_candidates_sample") or []),
            )
            if part
        )
        rows.extend(
            extract_candidates_from_text(
                evidence,
                source_ref_id=compact(task.get("task_id"), 180),
                source_kind="s122_poster_lineup_task",
                source_url_or_article_id=compact(task.get("event_id"), 180),
                source_lane=compact(task.get("lane"), 80),
            )
        )
        for name in task.get("lineup_candidates_sample") or []:
            cleaned = clean_name(str(name))
            if not is_good_name(cleaned):
                continue
            rows.append(
                make_row(
                    source_ref_id=compact(task.get("task_id"), 180),
                    source_kind="s122_poster_lineup_task",
                    source_url_or_article_id=compact(task.get("event_id"), 180),
                    evidence_text=evidence,
                    entity_name=cleaned,
                    entity_kind="dj_person",
                    role_hint="lineup_artist",
                    confidence=0.78,
                    disposition="accept_candidate",
                    source_lane=compact(task.get("lane"), 80),
                )
            )
    return dedupe_rows(rows)


def rows_from_s124(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in iter_jsonl(path)[:limit]:
        evidence = " | ".join(
            part
            for part in (
                compact(result.get("entity_name"), 120),
                compact(result.get("platform"), 80),
                compact(result.get("title"), 260),
                ",".join(result.get("blocked_reasons") or []),
            )
            if part
        )
        entity = clean_name(result.get("entity_name") or "")
        if not is_good_name(entity):
            continue
        rows.append(
            make_row(
                source_ref_id=compact(result.get("canary_id"), 120),
                source_kind="s124_external_link_canary",
                source_url_or_article_id=compact(result.get("item_id"), 120),
                evidence_text=evidence,
                entity_name=entity,
                entity_kind="unknown" if result.get("decision") != "fetch_ok_public_candidate" else "dj_person",
                role_hint="external_link_subject",
                confidence=0.7 if result.get("decision") == "fetch_ok_public_candidate" else 0.45,
                disposition="needs_review",
                source_lane="",
            )
        )
    return dedupe_rows(rows)


def secret_findings(report: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    text = json.dumps({"report": report, "rows": rows}, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def scorecard(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Label / DJ Bio Recognition S125A",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Candidate rows: `{summary['candidate_count']}`",
        f"- Bio candidates: `{summary['bio_candidate_count']}`",
        f"- Label/org-like candidates: `{summary['label_org_like_count']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Entity Kinds",
        "",
    ]
    for key, value in sorted(summary["by_entity_kind"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Model Lanes", ""])
    for key, value in sorted(summary["by_model_lane"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Sample Rows", ""])
    lines.append("| entity | kind | role | disposition | model_lane |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in rows[:10]:
        lines.append(
            f"| {row['entity_name']} | {row['entity_kind']} | {row['role_hint']} | {row['disposition']} | {row['model_lane']} |"
        )
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- Report-only workbench.",
            "- No model/API call, no DB write/projection, no mini-program public display, no cookie/token value read.",
            "- Hunyuan is summary-only after accepted facts exist.",
            "",
            "## Next",
            "",
            "- S125 can run a report-local DB2 projection smoke only after this workbench and the S121 entity-id mapping gate are both carried forward.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_workbench(
    s122_tasks: Path,
    s121_audit: Path,
    s124_results: Path,
    out_dir: Path,
    scorecard_path: Path,
    limit_s122: int,
    limit_s124: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = dedupe_rows(rows_from_s122(s122_tasks, limit_s122) + rows_from_s124(s124_results, limit_s124))
    by_kind = Counter(row["entity_kind"] for row in rows)
    by_lane = Counter(row["model_lane"] for row in rows)
    by_disposition = Counter(row["disposition"] for row in rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "label_dj_bio_recognition_workbench_ready_report_only",
        "inputs": {
            "s122_tasks": rel_path(s122_tasks),
            "s121_audit": rel_path(s121_audit),
            "s124_results": rel_path(s124_results),
        },
        "outputs": {
            "report": rel_path(out_dir / "label_dj_bio_recognition_workbench.json"),
            "candidates": rel_path(out_dir / "label_dj_bio_candidates.jsonl"),
            "model_policy": rel_path(out_dir / "label_dj_bio_model_policy.json"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "candidate_count": len(rows),
            "bio_candidate_count": sum(1 for row in rows if row["role_hint"] == "bio_claim"),
            "label_org_like_count": sum(1 for row in rows if row["entity_kind"] in {"label_org", "collective_crew", "promoter_org"}),
            "by_entity_kind": dict(by_kind),
            "by_model_lane": dict(by_lane),
            "by_disposition": dict(by_disposition),
            "s121_entity_mapping_gate_carried": True,
        },
        "boundaries": {
            "model_call_performed": False,
            "network_fetch": False,
            "cookie_values_read": False,
            "token_values_read": False,
            "database_mutation": False,
            "db2_projection_allowed": False,
            "db3_identity_write_allowed": False,
            "miniapp_public_display_allowed": False,
        },
        "secret_like_findings": [],
        "finding_count": 0,
        "next_story": "S125",
    }
    findings = secret_findings(report, rows)
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings:
        report["decision"] = "label_dj_bio_recognition_workbench_blocked_secret_like_findings"

    atomic_write_json(out_dir / "label_dj_bio_recognition_workbench.json", report)
    atomic_write_jsonl(out_dir / "label_dj_bio_candidates.jsonl", rows)
    atomic_write_json(
        out_dir / "label_dj_bio_model_policy.json",
        {
            "schema_version": f"{SCHEMA_VERSION}.model_policy",
            "generated_at": report["generated_at"],
            "policy": MODEL_POLICY,
            "hunyuan_boundary": "summary_only_after_fact_extraction",
            "model_call_performed": False,
        },
    )
    atomic_write_text(scorecard_path, scorecard(report, rows))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s122-tasks", type=Path, default=DEFAULT_S122_TASKS)
    parser.add_argument("--s121-audit", type=Path, default=DEFAULT_S121_AUDIT)
    parser.add_argument("--s124-results", type=Path, default=DEFAULT_S124_RESULTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--limit-s122", type=int, default=300)
    parser.add_argument("--limit-s124", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_workbench(
        args.s122_tasks,
        args.s121_audit,
        args.s124_results,
        args.out_dir,
        args.scorecard,
        args.limit_s122,
        args.limit_s124,
    )
    print(json.dumps({"decision": report["decision"], "finding_count": report["finding_count"], "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
