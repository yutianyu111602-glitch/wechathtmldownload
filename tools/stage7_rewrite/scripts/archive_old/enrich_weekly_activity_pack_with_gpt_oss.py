#!/usr/bin/env python3
"""Optional gpt-oss enrichment for HUAIDJ weekly activity candidates.

The enrichment layer is intentionally not the source of truth for publish gates.
It can improve display title, lineup, styles, and source-like description lines.
It may also suggest time/address values, but those are merged only when the
candidate is grounded in the supplied source evidence and passes deterministic
shape checks.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_RUNNER_COMMAND = ["__mac_gpt_oss_20b_tq3__"]
DEFAULT_SSH_TARGET = "masher@192.168.8.234"
DEFAULT_WRAPPER = "/Users/masher/.openclaw/workspace/model-runs/run-gpt-oss-20b-tq3"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMP = 0
NOISE_PREFIXES = (
    "[INFO]",
    "[transformers]",
    "The following generation flags",
)

SOFT_FIELDS = {
    "title_display",
    "lineup",
    "lineup_artists",
    "music_styles",
    "genres",
    "description_original_lines",
    "review_flags",
}
SOURCE_GROUNDED_FIELDS = {
    "event_time_text",
    "running_hours_text",
    "address",
    "address_candidate",
}
JSON_FIELD_KEYS = SOFT_FIELDS | SOURCE_GROUNDED_FIELDS

ADDRESS_SIGNAL_RE = re.compile(
    r"省|市|区|县|路|街|道|巷|弄|号|栋|幢|层|室|广场|文创园|创意园|园区|中心|B\d|L\d|M\d",
    re.I,
)
ADDRESS_REJECT_RE = re.compile(r"公众号|二维码|客服|咨询|加群|booking|创始|厂牌|sound|music history", re.I)
TIME_RE = re.compile(
    r"(?i)(?:\b[0-2]?\d[:：][0-5]\d\b|(?:凌晨|早上|上午|中午|下午|晚上|晚间|今晚|夜里)?\s*[零一二三四五六七八九十两0-9]{1,3}\s*点|late)"
)
DATE_LINEUP_RE = re.compile(
    r"(?i)(?:时间|日期|date|time)\s*[:：]?\s*(?:20\d{2}\s*[./年-]\s*)?\d{1,2}\s*(?:[./月-]|月)\s*\d{1,2}|"
    r"(?:20\d{2}\s*[./年-]\s*)?\d{1,2}\s*(?:[./月-]|月)\s*\d{1,2}\s*日?.*(?:时间|日期|date|time)"
)
NON_ARTIST_LINEUP_RE = re.compile(
    r"活动|派对|现场|阵容|加码|嘉宾|票务|购票|扫码|客服|公众号|阅读|本章|信息|标题|"
    r"open\s*deck|line\s*up|running\s*hours?|ticket|price|address|location|venue",
    re.I,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def list_strings(value: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip() if item is not None else ""
        if not text:
            continue
        key = re.sub(r"\s+", " ", text.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(re.sub(r"\s+", " ", text))
        if len(out) >= limit:
            break
    return out


def normalize_name(value: str) -> str:
    return re.sub(r"[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]+", "", value.lower())


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "").lower())


def support_corpus(row: dict[str, Any]) -> str:
    parts = [
        first_string(row.get("title")),
        first_string(row.get("event_time_text")),
        first_string(row.get("running_hours_text")),
        first_string(row.get("address")),
        first_string(row.get("account_key")),
        first_string(row.get("account")),
        *list_strings(row.get("event_date_text")),
        *list_strings(row.get("date_text")),
        *list_strings(row.get("city")),
        *list_strings(row.get("venue")),
        *list_strings(row.get("lineup")),
        *list_strings(row.get("genres")),
        *list_strings(row.get("music_styles")),
        *list_strings(row.get("evidence"), limit=40),
    ]
    return "\n".join(part for part in parts if part)


def exact_or_token_supported(row: dict[str, Any], value: str) -> bool:
    text = support_corpus(row)
    normalized_corpus = normalize_text(text)
    normalized_value = normalize_text(value)
    if not normalized_value:
        return False
    if normalized_value in normalized_corpus:
        return True
    time_tokens = [normalize_text(match.group(0)) for match in TIME_RE.finditer(value)]
    if time_tokens and all(token and token in normalized_corpus for token in time_tokens):
        if "late" in normalized_value and "late" not in normalized_corpus:
            return False
        return True
    return False


def looks_like_time(value: str) -> bool:
    text = unicodedata.normalize("NFKC", value or "").strip()
    if not text or len(text) > 40:
        return False
    if re.search(r"票|票价|购票|预售|门票|价格|price|ticket|¥|￥|\brmb\b|元", text, re.I):
        return bool(re.search(r"活动时间|演出时间|营业时间|running\s*hours?", text, re.I))
    return bool(TIME_RE.search(text))


def normalize_time_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    text = re.sub(r"^(?:活动时间|演出时间|营业时间|时间|time|running\s*hours?)\s*[:：]?\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n,，.。;；|｜")


def looks_like_address(value: str) -> bool:
    text = re.sub(r"^(?:活动地点|场地地址|详细地址|地址|地点|ADD(?:RESS)?|LOCATION|Venue|📍|⭕地址)\s*[:：]?\s*", "", value or "", flags=re.I)
    text = text.strip(" \t\r\n,，.。;；|｜")
    if not text or len(text) < 4 or len(text) > 100:
        return False
    if ADDRESS_REJECT_RE.search(text):
        return False
    return bool(ADDRESS_SIGNAL_RE.search(text))


def normalize_address_text(value: str) -> str:
    text = re.sub(r"^(?:活动地点|场地地址|详细地址|地址|地点|ADD(?:RESS)?|LOCATION|Venue|📍|⭕地址)\s*[:：]?\s*", "", value or "", flags=re.I)
    return text.strip(" \t\r\n,，.。;；|｜")


def entity_blocklist(row: dict[str, Any]) -> set[str]:
    values: list[str] = [
        first_string(row.get("account_key")),
        first_string(row.get("account")),
        first_string(row.get("promoter")),
        first_string(row.get("address")),
    ]
    values.extend(list_strings(row.get("venue")))
    values.extend(list_strings(row.get("city")))
    return {normalize_name(value) for value in values if normalize_name(value)}


def clean_lineup(row: dict[str, Any], values: Any) -> list[str]:
    blocked = entity_blocklist(row)
    out: list[str] = []
    seen: set[str] = set()
    for value in list_strings(values, limit=16):
        normalized = normalize_name(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if NON_ARTIST_LINEUP_RE.search(value) or TIME_RE.search(value) or DATE_LINEUP_RE.search(value):
            continue
        if not exact_or_token_supported(row, value):
            continue
        if any(normalized == blocked_name or normalized in blocked_name or blocked_name in normalized for blocked_name in blocked):
            continue
        out.append(value)
        if len(out) >= 12:
            break
    return out


def build_prompt(row: dict[str, Any]) -> str:
    payload = {
        "title": first_string(row.get("title")),
        "account": first_string(row.get("account_key"),) or first_string(row.get("account")),
        "event_date_text": list_strings(row.get("event_date_text")),
        "event_time_text": first_string(row.get("event_time_text")),
        "city": list_strings(row.get("city")),
        "venue": list_strings(row.get("venue")),
        "address": first_string(row.get("address")),
        "lineup": list_strings(row.get("lineup")),
        "genres": list_strings(row.get("genres")),
        "evidence": list_strings(row.get("evidence"), limit=10),
    }
    return (
        "你是地下电子音乐活动数据清洗器。只输出一个 JSON object，不要解释。\n"
        "硬规则：不要推断事实；只能从输入 evidence/title/address/event_time_text 里摘取或整理。\n"
        "可以做软字段增强：title_display, lineup_artists, music_styles, description_original_lines, review_flags。不要生成 DJ/艺人 bio。\n"
        "也可以输出 event_time_text 或 address_candidate，但必须是输入中明确出现的原文或等价规范化；没有精确钟点/街道地址就填 null。\n"
        "lineup_artists 只能是 DJ/艺人/Live act，必须剔除俱乐部、公众号、城市、地址、票务词、活动系列名。\n"
        "description_original_lines 只能摘原文自然句，不要生成营销总结腔。\n"
        "music_styles 只允许输出地下音乐风格词，例如 techno, house, hip-hop, bass, club trax, 4x4, electro, breaks, trance, disco, ambient。\n"
        "JSON schema: {\"title_display\":\"string\",\"lineup_artists\":[\"string\"],\"music_styles\":[\"string\"],"
        "\"description_original_lines\":[\"string\"],\"event_time_text\":\"string|null\","
        "\"address_candidate\":\"string|null\",\"review_flags\":[\"string\"]}\n"
        f"输入：{json.dumps(payload, ensure_ascii=False)}"
    )


def runner_from_arg(value: str | None) -> list[str]:
    if not value:
        return DEFAULT_RUNNER_COMMAND
    return shlex.split(value, posix=os.name != "nt")


def run_model(
    command: list[str],
    prompt: str,
    *,
    timeout_s: int,
    ssh_target: str = DEFAULT_SSH_TARGET,
    wrapper: str = DEFAULT_WRAPPER,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temp: float = DEFAULT_TEMP,
) -> str:
    if command == DEFAULT_RUNNER_COMMAND:
        remote = " ".join(
            shlex.quote(part)
            for part in [
                wrapper,
                prompt,
                "--max-tokens",
                str(max_tokens),
                "--temp",
                str(temp),
            ]
        )
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", ssh_target, remote]
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    if completed.returncode != 0:
        raise RuntimeError(f"runner exited with {completed.returncode}: {output[-800:]}")
    return output


def strip_analysis_markers(text: str) -> str:
    text = re.sub(r"(?is)<analysis>.*?</analysis>", "", text)
    text = re.sub(r"(?im)^analysis\s*:.*$", "", text)
    return text.replace("<final>", "").replace("</final>", "")


def sanitize_stdout(text: str) -> str:
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(prefix) for prefix in NOISE_PREFIXES):
            continue
        lines.append(stripped)
    return strip_analysis_markers("\n".join(lines)).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    text = sanitize_stdout(text)
    objects: list[dict[str, Any]] = []
    starts = [index for index, char in enumerate(text) if char == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(value, dict):
                        objects.append(value)
                    break
    if not objects:
        return {}
    for value in reversed(objects):
        if JSON_FIELD_KEYS.intersection(value.keys()):
            return value
    return objects[-1]


def merge_enrichment(row: dict[str, Any], enrichment: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    next_row = dict(row)
    changed: list[str] = []
    title_display = first_string(enrichment.get("title_display"))
    if title_display and len(title_display) <= 120 and title_display != first_string(row.get("title")):
        next_row["title_display"] = title_display
        changed.append("title_display")

    lineup = clean_lineup(row, enrichment.get("lineup_artists") or enrichment.get("lineup"))
    if lineup:
        next_row["lineup"] = lineup
        next_row["lineup_artists"] = lineup
        changed.append("lineup_artists")

    styles = list_strings(enrichment.get("music_styles") or enrichment.get("genres"), limit=6)
    if styles:
        next_row["genres"] = styles
        next_row["music_styles"] = styles
        changed.append("music_styles")

    for field in ("description_original_lines", "review_flags"):
        values = list_strings(enrichment.get(field), limit=8)
        if field == "description_original_lines":
            values = [value for value in values if exact_or_token_supported(row, value)]
        if values:
            next_row[field] = values
            changed.append(field)

    current_time = first_string(row.get("event_time_text")) or first_string(row.get("running_hours_text"))
    time_value = first_string(enrichment.get("event_time_text")) or first_string(enrichment.get("running_hours_text"))
    normalized_time = normalize_time_text(time_value)
    if not current_time and normalized_time and looks_like_time(normalized_time) and exact_or_token_supported(row, normalized_time):
        next_row["event_time_text"] = normalized_time
        changed.append("event_time_text")

    current_address = first_string(row.get("address"))
    address_value = first_string(enrichment.get("address_candidate")) or first_string(enrichment.get("address"))
    normalized_address = normalize_address_text(address_value)
    if not current_address and normalized_address and looks_like_address(normalized_address) and exact_or_token_supported(row, normalized_address):
        next_row["address"] = normalized_address
        changed.append("address")

    next_row["enrichment"] = {
        "provider": "gpt-oss-20b-tq3",
        "enriched_at": datetime.now().isoformat(timespec="seconds"),
        "changed_fields": changed,
        "source_grounded_fields": sorted(SOURCE_GROUNDED_FIELDS),
    }
    return next_row, changed


def enrich_rows(
    rows: list[dict[str, Any]],
    command: list[str],
    *,
    limit: int,
    timeout_s: int,
    ssh_target: str = DEFAULT_SSH_TARGET,
    wrapper: str = DEFAULT_WRAPPER,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temp: float = DEFAULT_TEMP,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    enriched = 0
    failed = 0
    changed_counter: dict[str, int] = {}
    for index, row in enumerate(rows):
        if limit >= 0 and index >= limit:
            out.append(row)
            continue
        try:
            raw = run_model(
                command,
                build_prompt(row),
                timeout_s=timeout_s,
                ssh_target=ssh_target,
                wrapper=wrapper,
                max_tokens=max_tokens,
                temp=temp,
            )
            parsed = extract_json_object(raw)
            next_row, changed = merge_enrichment(row, parsed)
            enriched += 1
            for field in changed:
                changed_counter[field] = changed_counter.get(field, 0) + 1
            out.append(next_row)
        except Exception as exc:
            failed += 1
            failed_row = dict(row)
            failed_row["enrichment_error"] = str(exc)[-500:]
            out.append(failed_row)
    return out, {"enriched": enriched, "failed": failed, "changed_fields": changed_counter}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich weekly activity candidates with Mac gpt-oss-20b-tq3")
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--limit", type=int, default=-1, help="-1 means all rows")
    parser.add_argument("--timeout-s", type=int, default=180)
    parser.add_argument("--runner-command", default="")
    parser.add_argument("--ssh-target", default=DEFAULT_SSH_TARGET)
    parser.add_argument("--wrapper", default=DEFAULT_WRAPPER)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temp", type=float, default=DEFAULT_TEMP)
    args = parser.parse_args(argv)

    input_path = Path(args.input_jsonl)
    output_path = Path(args.output_jsonl)
    rows = read_jsonl(input_path)
    command = runner_from_arg(args.runner_command)
    enriched_rows, stats = enrich_rows(
        rows,
        command,
        limit=args.limit,
        timeout_s=args.timeout_s,
        ssh_target=args.ssh_target,
        wrapper=args.wrapper,
        max_tokens=args.max_tokens,
        temp=args.temp,
    )
    write_jsonl(output_path, enriched_rows)
    summary = {
        "schema_version": "weekly_activity_gpt_oss_enrichment.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_jsonl": str(input_path),
        "output_jsonl": str(output_path),
        "row_count": len(rows),
        "limit": args.limit,
        "runner": command[0] if command else "",
        "ssh_target": args.ssh_target if command == DEFAULT_RUNNER_COMMAND else "",
        "max_tokens": args.max_tokens if command == DEFAULT_RUNNER_COMMAND else None,
        **stats,
        "soft_fields_only": sorted(SOFT_FIELDS),
        "source_grounded_fields": sorted(SOURCE_GROUNDED_FIELDS),
    }
    if args.summary_json:
        write_json(Path(args.summary_json), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
