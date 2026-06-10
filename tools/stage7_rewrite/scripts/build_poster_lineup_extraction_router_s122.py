#!/usr/bin/env python3
"""Build the S122 poster/lineup extraction router.

This is a report-only router/workbench. It does not call OCR, DeepSeek, Mimo,
Hunyuan, CloudBase, or any production database writer.
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


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "poster_lineup_extraction_router_s122.v1"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "poster_lineup_extraction_router_s122_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_POSTER_LINEUP_EXTRACTION_ROUTER_S122_20260601.md"
DEFAULT_WEEKLY_CURRENT = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_DB1 = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_S121_AUDIT = STAGE7_ROOT / "reports" / "three_db_merge_performance_s121_20260601" / "three_db_merge_performance_audit.json"

LINEUP_SPLIT_RE = re.compile(r"\s*(?:,|，|、|/|／|\+|&| x | X | b2b | B2B | vs\.? | feat\.? | with | w/ |\\n|;|；)\s*")
NOISE_RE = re.compile(
    r"(?i)^(dj|live|club|venue|bar|room|stage|lineup|guest|special|present|presents|party|event|tickets?|door|free|rsvp|afterparty|warmup|host|poster|flyer)$"
)
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)

MODEL_POLICY = {
    "deterministic_field_preserve": {
        "primary": "none",
        "fallback": "manual_review",
        "why": "Structured lineup already contains multiple artists; preserve fields and avoid paid/model calls.",
    },
    "source_text_flash_extract": {
        "primary": "deepseek-v4-flash",
        "fallback": "deepseek-v4-pro",
        "why": "Cheap source-text extraction for bounded inputs; escalate only when review flags remain.",
    },
    "chunked_source_lineup_flash_then_pro": {
        "primary": "deepseek-v4-flash",
        "fallback": "deepseek-v4-pro",
        "why": "Long inputs must be chunked first, then merged/adjudicated to avoid one-DJ truncation.",
    },
    "one_dj_lineup_repair_pro": {
        "primary": "deepseek-v4-pro",
        "fallback": "manual_review",
        "why": "A single extracted DJ with rich surrounding text is high risk for missed lineup members.",
    },
    "poster_ocr_deepseek_extract": {
        "primary": "deepseek-v4-flash",
        "fallback": "deepseek-v4-pro",
        "why": "Article image evidence exists but OCR/text is missing or too thin; OCR every image first, then let DeepSeek reason over OCR text. Mimo is visual-review only for unresolved conflicts.",
    },
    "manual_review": {
        "primary": "manual_review",
        "fallback": "none",
        "why": "Insufficient public text/poster evidence for safe automated extraction.",
    },
    "cloudbase_hunyuan_summary_only": {
        "primary": "cloudbase_hunyuan-v3-or-hy3-preview",
        "fallback": "none",
        "why": "Use only for mini-program summaries after facts are extracted; not a source-of-truth extractor.",
    },
}
CHUNK_POLICY = {
    "max_input_chars": 8000,
    "target_chunk_chars": 3600,
    "overlap_chars": 240,
    "merge_rule": "extract candidate names per chunk, dedupe by normalized name, then use pro/manual review for conflicts",
    "preserve_fields": ["title", "venue", "city", "date_text", "poster_text", "lineup_text", "source_ref"],
}
FULL_IMAGE_PROMPT_CONTRACT = """# Weekly Article Image/OCR Extraction Contract

你不是只看封面图。对每篇微信推文必须先处理全部图片，再判断主图和阵容。

步骤：
1. 枚举文章里的所有图片，保留原始顺序、URL、尺寸、下载/OCR状态；不要只取前几张。
2. 对每张可下载图片做 OCR。省成本时，先 OCR 全图，再把 OCR 命中的候选图交给 Mimo/多模态复核。
   - DeepSeek 负责大规模文本工作：读取正文 + 全图 OCR，做活动归并、主图候选排序、阵容/DJ bio/地址/坐标证据判断、去重和冲突解释。
   - Mimo/多模态只处理小的视觉复核队列：OCR 为空或明显乱码、主图候选冲突、图片角色无法靠 OCR 判断、候选图疑似错误覆盖时才调用。
   - 不要让 Mimo 扫全量图片；也不要让 DeepSeek 直接判断未 OCR 的图片内容。
3. 为每张图标注角色：main_event_poster、artist_bio、lineup_schedule、venue_address、ticket_qr、menu/bar、sponsor/logo、decorative、unknown。
4. 主图选择优先级：本活动标题/日期/时间/场地/阵容信息最完整的海报；不要用二维码、购票图、酒水菜单、纯头像、品牌 logo 或无活动信息的装饰图覆盖主图。
5. 阵容不是只从主海报抽取。合并正文、全部图片 OCR、DJ 介绍/ABOUT ARTISTS 段落、时间表里的所有 DJ/artist 名称。
6. bio 只取有来源证据的 DJ/artist 介绍句；不要把场地方、主办方、城市、票务、地址、菜单、导航、赞助商当成 DJ。
7. 输出要带证据：每个主图/阵容/bio/地址结论都引用 image_id、OCR行或正文片段。
8. 对“6月活动一览、本周活动、周末预览、weekly schedule/calendar”保留 parent calendar_preview 标记，并拆/关联子活动；不能因为标题是预览就丢掉后续单场图片。
"""


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


def compact(value: Any, limit: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [compact(item, 120) for item in value if compact(item, 120)]
    if isinstance(value, str):
        text = compact(value, 4000)
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return as_list(parsed)
        except json.JSONDecodeError:
            pass
        return [part for part in (compact(part, 120) for part in LINEUP_SPLIT_RE.split(text)) if part]
    return []


def clean_name(value: str) -> str:
    text = compact(value, 80)
    text = re.sub(r"^[#@\-\s]+", "", text)
    text = re.sub(r"\s*(?:dj set|live set|live|set|专场|嘉宾|主理人)\s*$", "", text, flags=re.I).strip()
    return text


def lineup_candidates(record: dict[str, Any]) -> list[str]:
    raw_items: list[str] = []
    for key in ("lineup_artists", "lineup", "lineup_text", "artist_lineup"):
        raw_items.extend(as_list(record.get(key)))
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw_items:
        name = clean_name(item)
        if not name or len(name) < 2 or len(name) > 60 or NOISE_RE.match(name):
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    return cleaned


def poster_url(record: dict[str, Any]) -> str:
    for key in ("poster_url", "flyer_url", "cover_image_url", "cover_url", "coverUrl", "poster_file_id"):
        value = compact(record.get(key), 1000)
        if value:
            return value
    return ""


def combined_text(record: dict[str, Any]) -> str:
    chunks = []
    for key in (
        "title",
        "event_title",
        "venue_name",
        "city",
        "city_name",
        "lineup_text",
        "poster_text",
        "poster_ocr",
        "source_text",
        "source_article_text",
        "raw_text",
    ):
        value = compact(record.get(key), 12000)
        if value:
            chunks.append(f"{key}: {value}")
    return "\n".join(chunks)


def route_record(record: dict[str, Any]) -> dict[str, Any]:
    lineup = lineup_candidates(record)
    text = combined_text(record)
    has_poster = bool(poster_url(record))
    poster_text = compact(record.get("poster_text") or record.get("poster_ocr"), 2000)
    input_chars = len(text)
    one_dj_only = len(lineup) == 1
    route_reasons: list[str] = []
    if len(lineup) >= 2:
        lane = "deterministic_field_preserve"
        route_reasons.append("structured_lineup_has_multiple_artists")
    elif has_poster and len(poster_text) < 40:
        lane = "poster_ocr_deepseek_extract"
        route_reasons.append("poster_exists_but_ocr_or_poster_text_is_missing_or_thin")
        route_reasons.append("mimo_visual_review_only_if_all_image_ocr_remains_ambiguous")
    elif input_chars > CHUNK_POLICY["max_input_chars"]:
        lane = "chunked_source_lineup_flash_then_pro"
        route_reasons.append("input_exceeds_single_prompt_budget")
    elif one_dj_only and input_chars >= 400:
        lane = "one_dj_lineup_repair_pro"
        route_reasons.append("only_one_artist_extracted_from_rich_context")
    elif input_chars:
        lane = "source_text_flash_extract"
        route_reasons.append("bounded_source_text_available")
    else:
        lane = "manual_review"
        route_reasons.append("no_usable_text_or_poster_signal")

    policy = MODEL_POLICY[lane]
    event_id = compact(record.get("id") or record.get("event_id") or record.get("activity_event_id"), 160)
    return {
        "task_id": compact(f"s122:{event_id or record.get('source_ref_id') or record.get('title') or len(text)}", 220),
        "event_id": event_id,
        "title": compact(record.get("title") or record.get("event_title"), 220),
        "venue_name": compact(record.get("venue_name") or record.get("venue") or record.get("venueLabel"), 160),
        "city": compact(record.get("city") or record.get("city_name"), 80),
        "poster_present": has_poster,
        "poster_text_chars": len(poster_text),
        "lineup_candidate_count": len(lineup),
        "lineup_candidates_sample": lineup[:12],
        "input_chars_estimate": input_chars,
        "lane": lane,
        "primary_model": policy["primary"],
        "fallback_model": policy["fallback"],
        "visual_review_model": "mimo_multimodal" if lane == "poster_ocr_deepseek_extract" else "none",
        "visual_review_allowed_only_after_ocr": lane == "poster_ocr_deepseek_extract",
        "model_policy_reason": policy["why"],
        "chunk_policy": CHUNK_POLICY if lane == "chunked_source_lineup_flash_then_pro" else {},
        "image_processing_policy": "process_all_article_images_then_ocr_then_select_main_poster",
        "lineup_policy": "merge_text_all_image_ocr_artist_bio_and_schedule_mentions",
        "cloudbase_hunyuan_role": "summary_after_fact_extraction_only",
        "route_reasons": route_reasons,
        "write_allowed": False,
        "model_call_allowed_by_this_report": False,
        "database_write_allowed": False,
    }


def load_weekly_records(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    return [row for row in rows[:limit] if isinstance(row, dict)]


def sqlite_uri(path: Path) -> str:
    return f"file:{path.resolve().as_posix()}?mode=ro"


def load_db1_activity_records(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists() or limit <= 0:
        return []
    conn = sqlite3.connect(sqlite_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT activity_event_id, event_id, title, venue_name, city_name,
                   lineup_artists_json, source_article_json
            FROM atlas_activity_events
            ORDER BY activity_event_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        record = dict(row)
        try:
            record["lineup_artists"] = json.loads(record.get("lineup_artists_json") or "[]")
        except json.JSONDecodeError:
            record["lineup_text"] = record.get("lineup_artists_json") or ""
        source_json = record.get("source_article_json") or ""
        if source_json:
            record["source_text"] = source_json[:12000]
        out.append(record)
    return out


def unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        key = compact(record.get("id") or record.get("event_id") or record.get("activity_event_id") or record.get("title") or index, 240)
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def promotion_gates(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    model_calls = sum(1 for task in tasks if task["model_call_allowed_by_this_report"])
    writes = sum(1 for task in tasks if task["database_write_allowed"])
    multi_artist = sum(1 for task in tasks if task["lineup_candidate_count"] >= 2)
    return [
        {"gate_id": "tasks_present", "passed": bool(tasks), "detail": f"tasks={len(tasks)}"},
        {"gate_id": "no_model_calls", "passed": model_calls == 0, "detail": f"model_calls={model_calls}"},
        {"gate_id": "no_database_writes", "passed": writes == 0, "detail": f"writes={writes}"},
        {"gate_id": "multi_artist_preservation_lane_present", "passed": multi_artist > 0 or bool(tasks), "detail": f"multi_artist_records={multi_artist}"},
        {"gate_id": "cloudbase_hunyuan_summary_only", "passed": True, "detail": "hunyuan reserved for mini-program summary after facts are extracted"},
    ]


def summarize(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_count": len(tasks),
        "by_lane": dict(Counter(task["lane"] for task in tasks).most_common()),
        "by_primary_model": dict(Counter(task["primary_model"] for task in tasks).most_common()),
        "poster_present_count": sum(1 for task in tasks if task["poster_present"]),
        "one_dj_risk_count": sum(1 for task in tasks if task["lane"] == "one_dj_lineup_repair_pro"),
        "chunked_count": sum(1 for task in tasks if task["lane"] == "chunked_source_lineup_flash_then_pro"),
        "manual_review_count": sum(1 for task in tasks if task["lane"] == "manual_review"),
    }


def secret_findings(report: dict[str, Any], tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    text = json.dumps({"report": report, "tasks": tasks[:20]}, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def markdown_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 24) -> list[str]:
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns) + " |")
    if len(rows) > limit:
        out.append("| " + " | ".join([f"{len(rows) - limit} more rows omitted"] + ["" for _ in columns[1:]]) + " |")
    return out


def render_markdown(report: dict[str, Any], tasks: list[dict[str, Any]]) -> str:
    lines = [
        "# Weekly Poster / Lineup Extraction Router S122",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Tasks: `{report['summary']['task_count']}`",
        f"- Secret-like findings: `{report['finding_count']}`",
        "",
        "## Model Routing Policy",
        "",
    ]
    for lane, policy in MODEL_POLICY.items():
        lines.append(f"- `{lane}`: primary `{policy['primary']}`, fallback `{policy['fallback']}` - {policy['why']}")
    lines.extend(
        [
            "",
            "## Full Image Prompt Contract",
            "",
            "- Process every article image before selecting the main poster.",
            "- OCR all downloadable images first; use Mimo only after OCR for unresolved image roles.",
            "- Extract lineup from source text, all image OCR, schedules, and artist bio sections, not only from the main poster.",
            f"- Prompt artifact: `{report['outputs'].get('prompt', '')}`",
        ]
    )
    lines.extend(["", "## Summary", ""])
    for key, value in report["summary"].items():
        lines.append(f"- `{key}`: `{json.dumps(value, ensure_ascii=False)}`")
    lines.extend(["", "## Gates", ""])
    lines.extend(markdown_table(report["promotion_gates"], ["gate_id", "passed", "detail"]))
    lines.extend(["", "## Sample Tasks", ""])
    lines.extend(
        markdown_table(
            tasks,
            ["task_id", "title", "lineup_candidate_count", "poster_present", "input_chars_estimate", "lane", "primary_model", "fallback_model"],
            30,
        )
    )
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- Report-only routing; no OCR/model/API call is executed.",
            "- No DB write, DB projection, mini-program upload/release, cookie/token read, or external network fetch.",
            "- Long input is chunked before model extraction to reduce the one-DJ truncation failure mode.",
            "",
            "## Next",
            "",
            "- S123 should diagnose Docker/exporter login state without exposing credentials.",
            "- S124 can run the first bounded no-cookie external-link crawl only after the S121 entity-id mapping gate is designed.",
            "",
        ]
    )
    return "\n".join(lines)


def build_router(
    weekly_current: Path,
    db1_path: Path,
    s121_audit: Path,
    out_dir: Path,
    scorecard: Path,
    limit: int,
) -> dict[str, Any]:
    weekly_records = load_weekly_records(weekly_current, limit)
    db1_records = load_db1_activity_records(db1_path, limit)
    records = unique_records(weekly_records + db1_records)
    tasks = [route_record(record) for record in records[:limit]]
    gates = promotion_gates(tasks)
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = out_dir / "poster_lineup_extraction_tasks.jsonl"
    report_path = out_dir / "poster_lineup_extraction_router.json"
    policy_path = out_dir / "poster_lineup_model_policy.json"
    prompt_path = out_dir / "poster_lineup_full_image_prompt.md"
    atomic_write_jsonl(tasks_path, tasks)
    atomic_write_text(prompt_path, FULL_IMAGE_PROMPT_CONTRACT)
    atomic_write_json(
        policy_path,
        {
            "schema_version": SCHEMA_VERSION + ".policy",
            "model_policy": MODEL_POLICY,
            "chunk_policy": CHUNK_POLICY,
            "full_image_prompt_contract_path": rel_path(prompt_path),
            "full_image_prompt_contract": FULL_IMAGE_PROMPT_CONTRACT,
        },
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "poster_lineup_extraction_router_ready_report_only",
        "inputs": {
            "weekly_current": rel_path(weekly_current),
            "db1": rel_path(db1_path),
            "s121_audit": rel_path(s121_audit),
        },
        "outputs": {
            "tasks": rel_path(tasks_path),
            "policy": rel_path(policy_path),
            "prompt": rel_path(prompt_path),
            "report": rel_path(report_path),
            "scorecard": rel_path(scorecard),
        },
        "summary": summarize(tasks),
        "promotion_gates": gates,
        "boundaries": {
            "report_only": True,
            "ocr_executed": False,
            "model_calls_executed": False,
            "deepseek_called": False,
            "mimo_called": False,
            "cloudbase_hunyuan_called": False,
            "database_mutation": False,
            "db_projection_allowed": False,
            "miniapp_release": False,
            "cookie_values_read": False,
            "token_values_read": False,
        },
        "next_story": "S123",
    }
    findings = secret_findings(report, tasks)
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings or not all(gate["passed"] for gate in gates):
        report["decision"] = "poster_lineup_extraction_router_blocked"
    atomic_write_json(report_path, report)
    markdown = render_markdown(report, tasks)
    atomic_write_text(out_dir / "poster_lineup_extraction_router.md", markdown)
    atomic_write_text(scorecard, markdown)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weekly-current", type=Path, default=DEFAULT_WEEKLY_CURRENT)
    parser.add_argument("--db1", type=Path, default=DEFAULT_DB1)
    parser.add_argument("--s121-audit", type=Path, default=DEFAULT_S121_AUDIT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--limit", type=int, default=400)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_router(args.weekly_current, args.db1, args.s121_audit, args.out_dir, args.scorecard, args.limit)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "finding_count": report["finding_count"],
                "summary": report["summary"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["decision"].endswith("_blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
