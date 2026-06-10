#!/usr/bin/env python3
"""Online DeepSeek enrichment and adjudication for weekly activity candidates.

This is the production-facing replacement for the archived local gpt-oss
enrichment lane. It keeps the same source-grounded merge rules: DeepSeek may
clean display fields, but time, address, and lineup are accepted only when they
are supported by the existing candidate evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_PRIMARY_MODEL = "deepseek-v4-pro"
DEFAULT_ADJUDICATION_MODEL = "deepseek-v4-pro"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMP = 0
DEFAULT_TIMEOUT_S = 90
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_S = 2.0
SOURCE_EVIDENCE_MAX_CHARS = 16000
HARD_BIO_DESCRIPTION_RE = re.compile(
    r"他是一位|她是一位|作为.{0,24}(?:先锋|奠基|人物)|二十多年来|多年.{0,12}一件事|"
    r"历史最悠久|因创办|因创立|而闻名|创立的.{0,24}形式",
    re.I,
)
BIO_DESCRIPTION_RE = re.compile(
    r"音乐制作人|先锋人物|奠基者|创办|创立|创始|闻名|二十多年来|多年|年来|"
    r"历史最悠久|来自|出生|简介|介绍|履历|bio|biography|founder|founded|based\s+in",
    re.I,
)
EVENT_DETAIL_RE = re.compile(
    r"20\d{2}|\d{1,2}\s*[./月-]\s*\d{1,2}|周[一二三四五六日天]|今晚|明晚|当晚|"
    r"\b[0-2]?\d[:：][0-5]\d\b|lineup|阵容|嘉宾|舞池|现场|派对|活动|地址|地点|票价|入场|with|w/",
    re.I,
)
CONFLICT_RE = re.compile(r"conflict|冲突|矛盾|不一致|mismatch|inconsistent", re.I)
DATE_CONFLICT_RE = re.compile(r"date|日期|时间|day|calendar", re.I)
VENUE_ADDRESS_CONFLICT_RE = re.compile(r"venue|address|location|场地|地址|地点", re.I)
LINEUP_WEAK_RE = re.compile(r"lineup|artist|阵容|艺人|嘉宾|candidate|weak|uncertain|拿不准|候选|弱证据|不确定", re.I)

SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVE_SCRIPT_DIR = SCRIPT_DIR / "archive_old"
if ARCHIVE_SCRIPT_DIR.exists() and str(ARCHIVE_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(ARCHIVE_SCRIPT_DIR))

try:
    import enrich_weekly_activity_pack_with_gpt_oss as strict_merge
except Exception as exc:  # pragma: no cover - import failure is fatal in normal use.
    raise RuntimeError(f"strict weekly merge helper is unavailable: {exc}") from exc


DeepSeekCaller = Callable[[dict[str, Any]], dict[str, Any]]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return strict_merge.read_jsonl(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    strict_merge.write_jsonl(path, rows)


def write_json(path: Path, value: dict[str, Any]) -> None:
    strict_merge.write_json(path, value)


def first_string(value: Any) -> str:
    return strict_merge.first_string(value)


def list_strings(value: Any, *, limit: int = 12) -> list[str]:
    return strict_merge.list_strings(value, limit=limit)


def normalize_for_match(value: Any) -> str:
    text = first_string(value) if not isinstance(value, str) else value
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def source_evidence_text(row: dict[str, Any]) -> str:
    path_text = first_string(row.get("source_evidence_path"))
    if not path_text:
        return ""
    path = Path(path_text)
    try:
        if not path.exists() or not path.is_file():
            return ""
        if path.stat().st_size > 512 * 1024:
            return path.read_text(encoding="utf-8", errors="ignore")[:SOURCE_EVIDENCE_MAX_CHARS]
        return path.read_text(encoding="utf-8", errors="ignore")[:SOURCE_EVIDENCE_MAX_CHARS]
    except OSError:
        return ""


def row_source_text(row: dict[str, Any]) -> str:
    values = [
        first_string(row.get("title")),
        first_string(row.get("summary")),
        first_string(row.get("article_title")),
        first_string(row.get("body_text")),
        first_string(row.get("poster_ocr_text")),
        source_evidence_text(row),
        *list_strings(row.get("evidence"), limit=80),
        *list_strings(row.get("description_original_lines"), limit=20),
    ]
    return "\n".join(value for value in values if value)


def row_review_text(row: dict[str, Any]) -> str:
    values = [
        first_string(row.get("date_conflict")),
        first_string(row.get("cross_source_conflict")),
        first_string(row.get("venue_conflict")),
        first_string(row.get("address_conflict")),
        first_string(row.get("lineup_conflict")),
        *list_strings(row.get("review_flags"), limit=30),
        *list_strings(row.get("quality_flags"), limit=30),
        *list_strings(row.get("recommendation_reason"), limit=30),
    ]
    return " | ".join(value for value in values if value)


def lineup_has_weak_source_evidence(row: dict[str, Any]) -> bool:
    lineup = list_strings(row.get("lineup")) or list_strings(row.get("lineup_artists"))
    if not lineup:
        return False
    review_text = row_review_text(row)
    if LINEUP_WEAK_RE.search(review_text):
        return True
    support_text = normalize_for_match(row_source_text(row))
    if not support_text:
        return True
    unsupported = [
        value
        for value in lineup
        if normalize_for_match(value) and normalize_for_match(value) not in support_text
    ]
    return bool(unsupported)


def build_prompt(row: dict[str, Any]) -> str:
    prompt = (
        strict_merge.build_prompt(row)
        + "\n生产黄页补充规则："
        + "这是面向公众的小程序数据，实体准确率要求高于内部微信下载管线；"
        + "宁愿缺字段，也不能编错。拿不准 lineup 就输出空数组并写 review_flags，不要为了好看补艺名；"
        + "候选字段本身不是证据，只有正文、标题、OCR 或子活动原文里明确支持的实体才能保留；"
        + "拿不准地址、时间、场地或账号归属就输出 null；"
        + "票价必须逐字来自正文或 OCR：3am/3 AM/凌晨3点是时间条件，不能抽成 3元/￥3；"
        + "遇到“3am 后免费入场”这类内容要作为完整入场规则保留，不能拆成价格数字；"
        + "不要生成 DJ/艺人 bio、场地 bio、距离估算、购票建议或营销文案；"
        + "如果只能确认用户需要看原文，请在 review_flags 写 source_review_needed。"
        + "全量更新字段边界：title_display、event_date_text、event_time_text/running_hours_text、"
        + "lineup_artists、music_styles、description_original_lines、venue、city、address/address_candidate、"
        + "price/ticketing_text、review_flags；source_url、post_date、source_account_name、account_key 等溯源字段不得改写。"
        + "field_evidence_refs 对保留或修改字段必须尽量输出，写正文/标题/子活动原文片段、article/text/source 引用或 OCR image_id，"
        + "例如 {\"lineup_artists\":[\"ocr:img_xxx:LINEUP DJ A\"]}。"
    )
    evidence = source_evidence_text(row)
    if evidence:
        prompt += "\n\n## Unified Source Evidence\n" + evidence
    return prompt


def build_deepseek_payload(
    row: dict[str, Any],
    *,
    model: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temp: float = DEFAULT_TEMP,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是公开电子音乐活动黄页的数据清洗器。只输出 JSON object。"
                    "你的职责是降低误报和胡编，不是补全文案。"
                ),
            },
            {"role": "user", "content": build_prompt(row)},
        ],
        "thinking": {"type": "disabled"},
        "temperature": temp,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "stream": False,
    }


def has_publish_core_fields(row: dict[str, Any]) -> bool:
    dates = list_strings(row.get("event_date_text"), limit=4) or list_strings(row.get("date_text"), limit=4)
    return bool(
        first_string(row.get("title"))
        and dates
        and first_string(row.get("event_time_text"))
        and first_string(row.get("address"))
    )


def filter_description_original_lines(values: Any) -> list[str]:
    out: list[str] = []
    for value in list_strings(values, limit=8):
        if not EVENT_DETAIL_RE.search(value):
            continue
        if HARD_BIO_DESCRIPTION_RE.search(value):
            continue
        if BIO_DESCRIPTION_RE.search(value) and not EVENT_DETAIL_RE.search(value):
            continue
        out.append(value)
    return out


def prepare_enrichment_for_merge(
    row: dict[str, Any],
    parsed: dict[str, Any],
    *,
    risk_flags: list[str],
) -> dict[str, Any]:
    cleaned = dict(parsed)
    descriptions = filter_description_original_lines(cleaned.get("description_original_lines"))
    if descriptions:
        cleaned["description_original_lines"] = descriptions
    else:
        cleaned.pop("description_original_lines", None)

    review_flags = list_strings(cleaned.get("review_flags"), limit=12)
    if review_flags and not risk_flags and has_publish_core_fields(row):
        review_flags = [flag for flag in review_flags if flag != "source_review_needed"]
        if review_flags:
            cleaned["review_flags"] = review_flags
        else:
            cleaned.pop("review_flags", None)
    refs = sanitize_field_evidence_refs(cleaned.get("field_evidence_refs"))
    if refs:
        cleaned["field_evidence_refs"] = refs
    else:
        cleaned.pop("field_evidence_refs", None)
    return cleaned


def sanitize_field_evidence_refs(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    allowed_fields = {
        "title_display",
        "event_date_text",
        "lineup_artists",
        "music_styles",
        "description_original_lines",
        "event_time_text",
        "running_hours_text",
        "address",
        "address_candidate",
        "price",
        "ticketing_text",
        "venue",
        "venue_name",
        "city",
        "review_flags",
    }
    out: dict[str, list[str]] = {}
    for key, refs in value.items():
        if key not in allowed_fields:
            continue
        ref_values = list_strings(refs, limit=8)
        cleaned_refs = [
            ref[:300]
            for ref in ref_values
            if re.search(r"(ocr:img_|text:|article:|source:|evidence:|正文|标题|子活动|image_id|img_)", ref, re.I)
        ]
        if cleaned_refs:
            out[key] = cleaned_refs
    return out


def risk_flags_for_row(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    source_kind = first_string(row.get("source_kind")) or first_string(row.get("aggregation_source_kind"))
    discovery_source = first_string(row.get("discovery_source"))

    if (
        row.get("aggregation_child")
        or row.get("aggregation_child_review")
        or source_kind in {"parent_body", "secondary_link"}
        or "aggregate" in discovery_source
    ):
        flags.append("aggregate_child_or_body")

    review_text = row_review_text(row)
    if CONFLICT_RE.search(review_text) and DATE_CONFLICT_RE.search(review_text):
        flags.append("date_conflict")
    if CONFLICT_RE.search(review_text) and VENUE_ADDRESS_CONFLICT_RE.search(review_text):
        flags.append("venue_address_conflict")
    if lineup_has_weak_source_evidence(row):
        flags.append("lineup_weak_evidence")

    evidence = list_strings(row.get("evidence"), limit=40)
    source_text = row_source_text(row)

    image_count = row.get("image_count") or row.get("local_image_count") or row.get("poster_image_count") or 0
    try:
        image_count_value = int(image_count)
    except (TypeError, ValueError):
        image_count_value = 0
    if image_count_value >= 3 and (len(evidence) < 2 or len(source_text) < 600):
        flags.append("image_heavy_weak_text")

    out: list[str] = []
    seen: set[str] = set()
    for flag in flags:
        if flag not in seen:
            seen.add(flag)
            out.append(flag)
    return out


def model_sequence_for_row(
    row: dict[str, Any],
    *,
    primary_model: str,
    adjudication_model: str,
    adjudicate_risky: bool,
) -> tuple[list[tuple[str, list[str]]], list[str]]:
    flags = risk_flags_for_row(row)
    sequence: list[tuple[str, list[str]]] = [(primary_model, flags)]
    if adjudicate_risky and flags:
        sequence.append((adjudication_model, flags))
    return sequence, flags


def select_model_for_row(
    row: dict[str, Any],
    *,
    primary_model: str,
    adjudication_model: str,
    adjudicate_risky: bool,
) -> tuple[str, list[str]]:
    sequence, flags = model_sequence_for_row(
        row,
        primary_model=primary_model,
        adjudication_model=adjudication_model,
        adjudicate_risky=adjudicate_risky,
    )
    return sequence[-1][0], [] if not adjudicate_risky else flags


def deepseek_chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def deepseek_chat(
    payload: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    timeout_s: int,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is not configured")
    request = Request(
        deepseek_chat_url(base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"DeepSeek request failed: {exc.reason}") from exc
    return json.loads(raw)


def parse_chat_response(response_payload: dict[str, Any]) -> dict[str, Any]:
    message = ((response_payload.get("choices") or [{}])[0].get("message") or {})
    content = first_string(message.get("content")) or first_string(message.get("reasoning_content"))
    if not content:
        return {}
    return strict_merge.extract_json_object(content)


def merge_deepseek_enrichment(
    row: dict[str, Any],
    parsed: dict[str, Any],
    *,
    model: str,
    risk_flags: list[str],
) -> tuple[dict[str, Any], list[str]]:
    parsed = prepare_enrichment_for_merge(row, parsed, risk_flags=risk_flags)
    field_evidence_refs = parsed.pop("field_evidence_refs", None)
    merged, changed = strict_merge.merge_enrichment(row, parsed)
    if field_evidence_refs:
        merged["field_evidence_refs"] = field_evidence_refs
    merged["enrichment"] = {
        "provider": "deepseek",
        "model": model,
        "thinking": "disabled",
        "enriched_at": datetime.now().isoformat(timespec="seconds"),
        "changed_fields": changed,
        "risk_flags": risk_flags,
        "source_grounded_fields": sorted(strict_merge.SOURCE_GROUNDED_FIELDS),
        "policy": "flash_no_thinking_default_pro_no_thinking_risky_adjudication",
    }
    return merged, changed


def enrich_rows(
    rows: list[dict[str, Any]],
    *,
    api_key: str,
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
    primary_model: str = DEFAULT_PRIMARY_MODEL,
    adjudication_model: str = DEFAULT_ADJUDICATION_MODEL,
    adjudicate_risky: bool = True,
    limit: int = -1,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temp: float = DEFAULT_TEMP,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff_s: float = DEFAULT_RETRY_BACKOFF_S,
    progress_every: int = 0,
    concurrency: int = 1,
    caller: Callable[..., dict[str, Any]] = deepseek_chat,
    output_jsonl: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any] | None] = [None] * len(rows)
    enriched = 0
    failed = 0
    changed_counter: Counter[str] = Counter()
    model_counter: Counter[str] = Counter()
    risk_counter: Counter[str] = Counter()

    total = len(rows)
    out_fh = open(output_jsonl, "w", encoding="utf-8") if output_jsonl else None
    def process_one(index: int, row: dict[str, Any]) -> tuple[int, dict[str, Any], bool, bool, list[str], list[str], list[str], list[str]]:
        if limit >= 0 and index >= limit:
            return index, row, False, False, [], [], [], []
        sequence, risk_flags = model_sequence_for_row(
            row,
            primary_model=primary_model,
            adjudication_model=adjudication_model,
            adjudicate_risky=adjudicate_risky,
        )
        current = dict(row)
        changed_total: list[str] = []
        models_used: list[str] = []
        did_enrich = False
        for model, pass_risk_flags in sequence:
            payload = build_deepseek_payload(current, model=model, max_tokens=max_tokens, temp=temp)
            attempts = max(1, int(max_retries) + 1)
            for attempt in range(attempts):
                try:
                    response_payload = caller(payload, api_key=api_key, base_url=base_url, timeout_s=timeout_s)
                    parsed = parse_chat_response(response_payload)
                    current, changed = merge_deepseek_enrichment(current, parsed, model=model, risk_flags=pass_risk_flags)
                    changed_total.extend(changed)
                    models_used.append(model)
                    did_enrich = True
                    break
                except Exception as exc:
                    if attempt + 1 < attempts:
                        if retry_backoff_s > 0:
                            time.sleep(float(retry_backoff_s) * (2 ** attempt))
                        continue
                    failed_row = dict(current)
                    failed_row["deepseek_enrichment_error"] = str(exc)[-500:]
                    failed_row["deepseek_enrichment_model"] = model
                    failed_row["deepseek_enrichment_risk_flags"] = risk_flags
                    return index, failed_row, did_enrich, True, changed_total, models_used, risk_flags, [str(exc)[-200:]]
        return index, current, did_enrich, False, changed_total, models_used, risk_flags, []

    def accept_result(
        result: tuple[int, dict[str, Any], bool, bool, list[str], list[str], list[str], list[str]],
        done_count: int,
    ) -> tuple[int, int]:
        nonlocal enriched, failed
        index, next_row, did_enrich, did_fail, changed, models, risk_flags, _errors = result
        out[index] = next_row
        if out_fh is not None:
            out_fh.write(json.dumps(next_row, ensure_ascii=False) + "\n")
            out_fh.flush()
        if did_enrich:
            enriched += 1
            for model in models:
                model_counter[model] += 1
        if did_fail:
            failed += 1
        for flag in risk_flags:
            risk_counter[flag] += 1
        for field in changed:
            changed_counter[field] += 1
        if progress_every > 0 and (done_count % progress_every == 0 or done_count == total):
            print(
                json.dumps(
                    {
                        "progress": "deepseek_enrichment",
                        "done": done_count,
                        "total": total,
                        "enriched": enriched,
                        "failed": failed,
                        "model_counts": dict(model_counter),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
        return enriched, failed
    concurrency = max(1, int(concurrency))
    if concurrency == 1:
        for index, row in enumerate(rows):
            accept_result(process_one(index, row), index + 1)
    else:
        done_count = 0
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(process_one, index, row) for index, row in enumerate(rows)]
            for future in as_completed(futures):
                done_count += 1
                accept_result(future.result(), done_count)

    if out_fh is not None:
        out_fh.close()
    stats = {
        "enriched": enriched,
        "failed": failed,
        "changed_fields": dict(changed_counter),
        "model_counts": dict(model_counter),
        "risk_flag_counts": dict(risk_counter),
        "max_retries": max(0, int(max_retries)),
        "retry_backoff_s": float(retry_backoff_s),
        "policy": "flash_no_thinking_default_pro_no_thinking_risky_adjudication",
        "thinking": "disabled",
    }
    return [row if row is not None else rows[index] for index, row in enumerate(out)], stats


def main(
    argv: list[str] | None = None,
    *,
    caller: Callable[..., dict[str, Any]] = deepseek_chat,
) -> int:
    parser = argparse.ArgumentParser(description="Enrich weekly activity candidates with online DeepSeek")
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--limit", type=int, default=-1, help="-1 means all rows")
    parser.add_argument("--api-key", default="", help="Prefer env in normal use; this exists for tests only")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--base-url", default=DEFAULT_DEEPSEEK_BASE_URL)
    parser.add_argument("--primary-model", default=DEFAULT_PRIMARY_MODEL)
    parser.add_argument("--adjudication-model", default=DEFAULT_ADJUDICATION_MODEL)
    parser.add_argument("--no-adjudicate-risky", action="store_true")
    parser.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--retry-backoff-s", type=float, default=DEFAULT_RETRY_BACKOFF_S)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temp", type=float, default=DEFAULT_TEMP)
    parser.add_argument("--progress-every", type=int, default=25, help="Print JSON progress to stderr every N rows; 0 disables")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args(argv)

    api_key = args.api_key or os.environ.get(args.api_key_env, "")
    if not api_key:
        print(f"{args.api_key_env} is not configured", file=sys.stderr)
        return 2

    rows = read_jsonl(Path(args.input_jsonl))
    enriched_rows, stats = enrich_rows(
        rows,
        api_key=api_key,
        base_url=args.base_url,
        primary_model=args.primary_model,
        adjudication_model=args.adjudication_model,
        adjudicate_risky=not args.no_adjudicate_risky,
        limit=args.limit,
        timeout_s=args.timeout_s,
        max_tokens=args.max_tokens,
        temp=args.temp,
        max_retries=args.max_retries,
        retry_backoff_s=args.retry_backoff_s,
        progress_every=args.progress_every,
        concurrency=args.concurrency,
        caller=caller,
    )
    write_jsonl(Path(args.output_jsonl), enriched_rows)
    summary = {
        **stats,
        "input_rows": len(rows),
        "output_rows": len(enriched_rows),
        "primary_model": args.primary_model,
        "adjudication_model": args.adjudication_model,
        "base_url": args.base_url,
        "api_key_configured": bool(api_key),
    }
    if args.summary_json:
        write_json(Path(args.summary_json), summary)
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
