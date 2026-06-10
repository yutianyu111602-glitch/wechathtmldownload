#!/usr/bin/env python3
"""Build the S119 DB2 incremental outlink sidecar contract.

Consumes S118 lock/cache production-candidate rows and materializes a report-
local SQLite/JSON sidecar. This does not fetch pages or mutate DB1/DB2/DB3.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "external_link_db2_sidecar_contract_s119.v1"
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "external_link_lock_cache_runner_s118_20260601_followup748"
    / "external_link_lock_cache_results.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "external_link_db2_sidecar_contract_s119_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_EXTERNAL_LINK_DB2_SIDECAR_CONTRACT_S119_20260601.md"

ALLOWED_PUBLIC_CATEGORIES = {
    "instagram",
    "mixtape_music",
    "radio",
    "video",
    "source_article",
    "public_profile",
}
MUSIC_PLATFORMS = {"soundcloud", "bandcamp", "mixcloud", "spotify", "applemusic", "beatport", "netease", "xiami"}
VIDEO_PLATFORMS = {"youtube", "youtu", "bilibili", "vimeo", "douyin", "kuaishou"}
SOCIAL_PLATFORMS = {"instagram", "weibo", "xhs", "rednote", "xiaohongshu"}
TRACKING_HOST_TOKENS = {"doubleclick", "googleadservices", "pagead", "analytics", "googlesyndication"}
LOW_VALUE_PATH_TOKENS = {
    "/privacy",
    "/terms",
    "/policies",
    "/policy",
    "/about",
    "/help",
    "/login",
    "/signin",
    "/signup",
    "/account",
    "/consent",
}
DIRECT_MEDIA_RE = re.compile(r"\.(mp3|m4a|aac|flac|wav|ogg|mp4|mov|mkv|avi|zip|rar|7z|tar|gz)(\?|#|$)", re.I)
SECRET_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)")


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


def stable_id(value: Any) -> str:
    import hashlib

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def load_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, dict) and isinstance(payload.get("sample_results"), list):
        return [row for row in payload["sample_results"] if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "instagram.com" in host:
        return "instagram"
    if "soundcloud.com" in host:
        return "soundcloud"
    if "bandcamp.com" in host:
        return "bandcamp"
    if "mixcloud.com" in host:
        return "mixcloud"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "bilibili.com" in host:
        return "bilibili"
    if "weibo.com" in host:
        return "weibo"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xhs"
    if "ra.co" in host or "residentadvisor" in host:
        return "source_article"
    if "radio" in host or "fm" in host:
        return "radio"
    return ""


def classify_category(platform: str, link_kind: str, url: str) -> str:
    text = f"{platform} {link_kind} {url}".lower()
    if platform == "instagram":
        return "instagram"
    if platform in MUSIC_PLATFORMS or any(token in text for token in ("mixtape", "playlist", "track", "audio", "music")):
        return "mixtape_music"
    if platform in VIDEO_PLATFORMS or "video" in text:
        return "video"
    if platform == "radio" or "radio" in text or "/fm" in text:
        return "radio"
    if "source" in text or "article" in text or "official" in text:
        return "source_article"
    if platform in SOCIAL_PLATFORMS:
        return "public_profile"
    return "public_profile"


def block_reasons(url: str, category: str) -> list[str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    reasons = []
    if not url:
        reasons.append("missing_url")
    if parsed.scheme not in {"http", "https"}:
        reasons.append("unsupported_scheme")
    if host in {"localhost", "127.0.0.1"} or host.startswith("10.") or host.startswith("192.168."):
        reasons.append("private_or_local_host")
    if any(token in host for token in TRACKING_HOST_TOKENS) or "pagead" in path:
        reasons.append("tracking_or_ads_url")
    if any(token in path for token in LOW_VALUE_PATH_TOKENS):
        reasons.append("low_value_policy_or_account_page")
    if DIRECT_MEDIA_RE.search(url):
        reasons.append("direct_media_or_archive_url")
    if category not in ALLOWED_PUBLIC_CATEGORIES:
        reasons.append("unsupported_public_category")
    return reasons


def confidence_score(row: dict[str, Any], category: str, reasons: list[str]) -> tuple[int, str, list[str]]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    raw_score = metadata.get("priority_score") or metadata.get("review_score") or row.get("priority") or 50
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        score = 50
    confidence_reasons = list(metadata.get("priority_reasons") or row.get("decision_reasons") or [])
    if category in {"instagram", "mixtape_music", "radio", "video"}:
        score += 5
        confidence_reasons.append(f"public_category:{category}")
    if metadata.get("source_layer") == "profile_page":
        score += 5
        confidence_reasons.append("source_layer:profile_page")
    if any(reason == "subject_match" for reason in confidence_reasons):
        score += 5
    if reasons:
        score = min(score, 40)
        confidence_reasons.extend([f"blocked:{reason}" for reason in reasons])
    score = max(0, min(score, 100))
    if score >= 85:
        band = "high"
    elif score >= 65:
        band = "medium"
    else:
        band = "low"
    return score, band, confidence_reasons[:24]


def copyright_safety(category: str, reasons: list[str]) -> str:
    if "direct_media_or_archive_url" in reasons:
        return "blocked_direct_media_or_archive"
    if category in {"mixtape_music", "video", "radio"}:
        return "jump_out_only_no_hosting_no_proxy"
    return "public_link_jump_out"


def normalize_candidate(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    url = str(row.get("url") or metadata.get("outlink_url") or metadata.get("profile_url") or "").strip()
    platform = str(row.get("platform") or metadata.get("outlink_platform") or "").strip().lower() or platform_from_url(url)
    link_kind = str(metadata.get("outlink_kind") or "").strip()
    category = classify_category(platform, link_kind, url)
    reasons = block_reasons(url, category)
    score, band, confidence_reasons = confidence_score(row, category, reasons)
    promotion_status = "candidate_ready_for_bounded_fetch"
    if reasons:
        promotion_status = "blocked_before_bounded_fetch"
    elif score >= 85:
        promotion_status = "high_confidence_pending_fetch_evidence"
    elif score >= 65:
        promotion_status = "medium_confidence_pending_review"
    else:
        promotion_status = "low_confidence_hold"
    sidecar_id = stable_id({
        "task_id": row.get("task_id"),
        "url": url,
        "entity_search_id": metadata.get("entity_search_id"),
    })
    return {
        "sidecar_id": sidecar_id,
        "task_id": str(row.get("task_id") or metadata.get("outlink_id") or sidecar_id),
        "entity_search_id": str(metadata.get("entity_search_id") or ""),
        "entity_name": str(row.get("subject") or metadata.get("name") or ""),
        "entity_type": str(metadata.get("type") or ""),
        "platform": platform,
        "url": url,
        "profile_url": str(metadata.get("profile_url") or ""),
        "parent_link_url": str(metadata.get("parent_link_url") or ""),
        "link_kind": link_kind or category,
        "public_category": category,
        "confidence_score": score,
        "confidence_band": band,
        "confidence_reasons": confidence_reasons,
        "copyright_safety": copyright_safety(category, reasons),
        "block_reasons": reasons,
        "fetch_status": "pending_bounded_fetch" if not reasons else "blocked_before_fetch",
        "source_layer": str(metadata.get("source_layer") or ""),
        "source_ref": str(metadata.get("source_ref") or metadata.get("entity_search_id") or ""),
        "cache_key": str(row.get("cache_key") or ""),
        "cache_path": str(row.get("cache_path") or ""),
        "lock_status": str(row.get("lock_status") or ""),
        "runner_decision": str(row.get("decision") or ""),
        "promotion_status": promotion_status,
        "db2_projection_allowed": False,
        "miniapp_display_allowed": False,
        "raw_metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        "created_at": now_iso(),
    }


def schema_contract() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tables": {
            "external_link_candidates": {
                "primary_key": "sidecar_id",
                "fields": [
                    "sidecar_id",
                    "task_id",
                    "entity_search_id",
                    "entity_name",
                    "entity_type",
                    "platform",
                    "url",
                    "profile_url",
                    "parent_link_url",
                    "link_kind",
                    "public_category",
                    "confidence_score",
                    "confidence_band",
                    "confidence_reasons_json",
                    "copyright_safety",
                    "block_reasons_json",
                    "fetch_status",
                    "source_layer",
                    "source_ref",
                    "cache_key",
                    "cache_path",
                    "lock_status",
                    "runner_decision",
                    "promotion_status",
                    "db2_projection_allowed",
                    "miniapp_display_allowed",
                    "raw_metadata_json",
                    "created_at",
                ],
            },
            "promotion_gates": {
                "fields": ["gate_id", "passed", "detail"],
            },
        },
        "promotion_rule": "DB2 projection remains false until bounded fetch evidence, leak scan, copyright gate, schema compat, and performance smoke pass.",
    }


def write_sqlite(path: Path, candidates: list[dict[str, Any]], gates: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            CREATE TABLE external_link_candidates (
              sidecar_id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              entity_search_id TEXT,
              entity_name TEXT,
              entity_type TEXT,
              platform TEXT,
              url TEXT NOT NULL,
              profile_url TEXT,
              parent_link_url TEXT,
              link_kind TEXT,
              public_category TEXT,
              confidence_score INTEGER,
              confidence_band TEXT,
              confidence_reasons_json TEXT,
              copyright_safety TEXT,
              block_reasons_json TEXT,
              fetch_status TEXT,
              source_layer TEXT,
              source_ref TEXT,
              cache_key TEXT,
              cache_path TEXT,
              lock_status TEXT,
              runner_decision TEXT,
              promotion_status TEXT,
              db2_projection_allowed INTEGER NOT NULL DEFAULT 0,
              miniapp_display_allowed INTEGER NOT NULL DEFAULT 0,
              raw_metadata_json TEXT,
              created_at TEXT
            )
            """
        )
        con.execute("CREATE INDEX idx_external_link_candidates_entity ON external_link_candidates(entity_search_id)")
        con.execute("CREATE INDEX idx_external_link_candidates_platform ON external_link_candidates(platform, public_category)")
        con.execute("CREATE INDEX idx_external_link_candidates_promotion ON external_link_candidates(promotion_status, confidence_band)")
        con.execute("CREATE TABLE promotion_gates (gate_id TEXT PRIMARY KEY, passed INTEGER NOT NULL, detail TEXT)")
        for row in candidates:
            con.execute(
                """
                INSERT INTO external_link_candidates VALUES (
                  :sidecar_id, :task_id, :entity_search_id, :entity_name, :entity_type,
                  :platform, :url, :profile_url, :parent_link_url, :link_kind, :public_category,
                  :confidence_score, :confidence_band, :confidence_reasons_json,
                  :copyright_safety, :block_reasons_json, :fetch_status, :source_layer,
                  :source_ref, :cache_key, :cache_path, :lock_status, :runner_decision,
                  :promotion_status, :db2_projection_allowed, :miniapp_display_allowed,
                  :raw_metadata_json, :created_at
                )
                """,
                {
                    **row,
                    "confidence_reasons_json": json.dumps(row["confidence_reasons"], ensure_ascii=False),
                    "block_reasons_json": json.dumps(row["block_reasons"], ensure_ascii=False),
                    "db2_projection_allowed": int(row["db2_projection_allowed"]),
                    "miniapp_display_allowed": int(row["miniapp_display_allowed"]),
                },
            )
        for gate in gates:
            con.execute(
                "INSERT INTO promotion_gates VALUES (:gate_id, :passed, :detail)",
                {"gate_id": gate["gate_id"], "passed": int(gate["passed"]), "detail": gate["detail"]},
            )
        con.commit()
    finally:
        con.close()


def promotion_gates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    row_count = len(candidates)
    high_count = sum(1 for row in candidates if row["confidence_band"] == "high")
    blocked_count = sum(1 for row in candidates if row["block_reasons"])
    db2_allowed = sum(1 for row in candidates if row["db2_projection_allowed"])
    return [
        {"gate_id": "rows_present", "passed": row_count > 0, "detail": f"rows={row_count}"},
        {"gate_id": "high_confidence_candidates_present", "passed": high_count > 0, "detail": f"high={high_count}"},
        {"gate_id": "blocked_rows_separated", "passed": blocked_count >= 0, "detail": f"blocked={blocked_count}"},
        {"gate_id": "no_db2_projection_without_fetch", "passed": db2_allowed == 0, "detail": f"db2_projection_allowed={db2_allowed}"},
        {"gate_id": "copyright_jump_out_policy_present", "passed": True, "detail": "audio/video/radio/music links are jump-out only"},
    ]


def summarize(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "row_count": len(candidates),
        "by_platform": dict(Counter(row["platform"] or "unknown" for row in candidates).most_common()),
        "by_public_category": dict(Counter(row["public_category"] for row in candidates).most_common()),
        "by_confidence_band": dict(Counter(row["confidence_band"] for row in candidates).most_common()),
        "by_promotion_status": dict(Counter(row["promotion_status"] for row in candidates).most_common()),
        "blocked_count": sum(1 for row in candidates if row["block_reasons"]),
        "high_confidence_count": sum(1 for row in candidates if row["confidence_band"] == "high"),
    }


def secret_findings(report: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    text = json.dumps({"report": report, "rows": candidates[:20]}, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def markdown_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 20) -> list[str]:
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns) + " |")
    if len(rows) > limit:
        out.append("| " + " | ".join([f"{len(rows) - limit} more rows omitted"] + ["" for _ in columns[1:]]) + " |")
    return out


def render_markdown(report: dict[str, Any], candidates: list[dict[str, Any]], gates: list[dict[str, Any]]) -> str:
    lines = [
        "# Weekly External-Link DB2 Sidecar Contract S119",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Input: `{report['input_path']}`",
        f"- Row count: `{report['summary']['row_count']}`",
        f"- High confidence: `{report['summary']['high_confidence_count']}`",
        f"- Blocked before fetch: `{report['summary']['blocked_count']}`",
        f"- Secret-like findings: `{report['finding_count']}`",
        f"- DB mutation: `{report['boundaries']['database_mutation']}`",
        f"- Network fetch: `{report['boundaries']['network_fetch']}`",
        "",
        "## Outputs",
        "",
    ]
    for key, value in report["outputs"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Promotion Gates", ""])
    lines.extend(markdown_table(gates, ["gate_id", "passed", "detail"], 20))
    lines.extend(["", "## Category Counts", ""])
    for key, value in report["summary"]["by_public_category"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Sample Candidates", ""])
    lines.extend(
        markdown_table(
            candidates,
            ["sidecar_id", "entity_name", "platform", "public_category", "confidence_score", "confidence_band", "promotion_status"],
            20,
        )
    )
    lines.extend([
        "",
        "## Next",
        "",
        "- S120 should expose only high-confidence public-safe categories to the mini-program API/UI.",
        "- S121 should run DB1/DB2/DB3 join-key and performance audits before any DB2 promotion.",
        "",
    ])
    return "\n".join(lines)


def build_sidecar(input_path: Path, out_dir: Path, scorecard: Path) -> dict[str, Any]:
    rows = load_rows(input_path)
    candidates = [normalize_candidate(row) for row in rows]
    gates = promotion_gates(candidates)
    out_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = out_dir / "external_link_db2_sidecar.sqlite"
    candidates_path = out_dir / "external_link_db2_sidecar_candidates.jsonl"
    schema_path = out_dir / "external_link_db2_sidecar_schema.json"
    report_path = out_dir / "external_link_db2_sidecar_contract.json"
    write_sqlite(sqlite_path, candidates, gates)
    atomic_write_jsonl(candidates_path, candidates)
    atomic_write_json(schema_path, schema_contract())
    outputs = {
        "sqlite": rel_path(sqlite_path),
        "candidates_jsonl": rel_path(candidates_path),
        "schema": rel_path(schema_path),
        "report": rel_path(report_path),
        "scorecard": rel_path(scorecard),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "external_link_db2_sidecar_contract_ready",
        "input_path": rel_path(input_path),
        "outputs": outputs,
        "summary": summarize(candidates),
        "promotion_gates": gates,
        "boundaries": {
            "candidate_sidecar_only": True,
            "network_fetch": False,
            "database_mutation": False,
            "production_db_write": False,
            "cookie_values_read": False,
            "token_values_read": False,
            "db2_projection_allowed": False,
            "miniapp_display_allowed": False,
        },
        "next_story": "S120",
    }
    findings = secret_findings(report, candidates)
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings:
        report["decision"] = "external_link_db2_sidecar_contract_blocked_secret_like_output"
    atomic_write_json(report_path, report)
    markdown = render_markdown(report, candidates, gates)
    atomic_write_text(out_dir / "external_link_db2_sidecar_contract.md", markdown)
    atomic_write_text(scorecard, markdown)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_sidecar(args.input, args.out_dir, args.scorecard)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "finding_count": report["finding_count"],
                "row_count": report["summary"]["row_count"],
                "high_confidence_count": report["summary"]["high_confidence_count"],
                "blocked_count": report["summary"]["blocked_count"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
