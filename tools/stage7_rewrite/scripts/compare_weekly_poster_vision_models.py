#!/usr/bin/env python3
"""Report-only poster vision model comparison for weekly activity packages.

The runner compares StepFun vision output with an optional MiMo-compatible
vision endpoint. It never writes DB2/DB3/CloudBase and never persists API keys.
Network calls are disabled unless --execute is passed.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_poster_vision_compare.v1"
BATCH_SCHEMA_VERSION = "weekly_poster_vision_compare_batch.v1"
DEFAULT_OUT_DIR = Path("tools/stage7_rewrite/reports/weekly_poster_vision_compare")
MAX_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_STEPFUN_BASE_URL = "https://api.stepfun.com/v1"
DEFAULT_STEPFUN_MODEL = "step-3.7-flash"
DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_MIMO_MODEL = "mimo-v2.5"
SECRET_ENV_NAMES = (
    "STEPFUN_VISION_API_KEY",
    "STEP_API_KEY",
    "STEPFUN_API_KEY",
    "MIMO_VISION_API_KEY",
    "MIMO_API_KEY",
)
OUTPUT_SIGNAL_KEYS = {
    "is_main_event_poster",
    "visible_text_lines",
    "event_title",
    "date_text",
    "time_text",
    "venue_text",
    "address_text",
    "city_text",
    "visual_layout_summary",
}
SOFT_PROVIDER_STATUSES = {"ok", "mocked", "not_configured", "dry_run"}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    model: str
    api_key_env: str
    configured: bool


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return text


def first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            for item in value:
                found = first_non_empty(item)
                if found:
                    return found
        elif value is not None and str(value).strip():
            return str(value).strip()
    return ""


def load_item_context(api_dir: Path | None, item_id: str | None) -> dict[str, Any]:
    if not api_dir or not item_id:
        return {}
    current = api_dir / "current.json"
    if not current.exists():
        raise FileNotFoundError(f"current.json not found: {current}")
    payload = read_json(current)
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError(f"current.json has no item list: {current}")
    for item in items:
        if isinstance(item, dict) and str(item.get("id") or "") == item_id:
            return item
    raise ValueError(f"item_id not found in current.json: {item_id}")


def load_ground_truth(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"ground truth must be a JSON object: {path}")
    return value


def read_optional_text(path: Path | None) -> str:
    if not path:
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def merge_context(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if value is not None and value != "":
            merged[key] = value
    return merged


def summarize_context(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": first_non_empty(item.get("title"), item.get("title_display"), item.get("title_original")),
        "date": first_non_empty(item.get("event_date_start"), item.get("event_date_text")),
        "time": first_non_empty(item.get("event_time_text"), item.get("running_hours_text"), item.get("time_start")),
        "city": first_non_empty(item.get("city"), item.get("city_name")),
        "venue": first_non_empty(item.get("venue"), item.get("venue_name")),
        "address": first_non_empty(item.get("address"), item.get("address_full")),
        "lineup": item.get("lineup") or item.get("lineup_artists") or [],
        "is_main_event_poster": item.get("is_main_event_poster")
        if "is_main_event_poster" in item
        else None,
    }


def image_to_data_url(image_path: Path) -> str:
    size = image_path.stat().st_size
    if size <= 0:
        raise ValueError(f"image is empty: {image_path}")
    if size > MAX_IMAGE_BYTES:
        raise ValueError(f"image exceeds 20MB StepFun guidance: {image_path} ({size} bytes)")
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def build_prompt(item: dict[str, Any]) -> str:
    context = {
        "id": item.get("id"),
        "title": first_non_empty(item.get("title"), item.get("title_display"), item.get("title_original")),
        "date": first_non_empty(item.get("event_date_start"), item.get("event_date_text")),
        "time": first_non_empty(item.get("event_time_text"), item.get("running_hours_text"), item.get("time_start")),
        "city": first_non_empty(item.get("city"), item.get("city_name")),
        "venue": first_non_empty(item.get("venue"), item.get("venue_name")),
        "address": first_non_empty(item.get("address"), item.get("address_full")),
        "lineup": item.get("lineup") or item.get("lineup_artists") or [],
    }
    return (
        "你是电子音乐活动海报理解评测器。只基于图片可见内容和下面的候选上下文输出 JSON，"
        "不要编造图片中没有的信息。重点评估 OCR、信息深度、主海报图理解、与候选上下文的正确性。"
        "如果图片明显不是活动海报（例如普通照片、自行车、菜单、场地营业说明、卡座预定图），"
        "必须设置 is_main_event_poster=false，并在 risk_flags 中加入 not_event_poster；"
        "只有图片内容不足以判断时才使用 null。输出根节点必须是 JSON 对象，必须包含下面字段，"
        "不要输出 JSON schema、字段类型说明、markdown 或纯字符串。\n\n"
        f"候选上下文: {json.dumps(context, ensure_ascii=False)}\n\n"
        "直接返回下面这个 JSON 对象模板的实例，保留所有键名并替换值；不要新增空键。"
        "visible_text_lines 最多 20 条，只保留关键信息，不要逐条抄写长篇注意事项。\n"
        "{\n"
        '  "schema_version": "poster_understanding.v1",\n'
        '  "is_main_event_poster": false,\n'
        '  "visible_text_lines": [],\n'
        '  "event_title": "",\n'
        '  "date_text": "",\n'
        '  "time_text": "",\n'
        '  "venue_text": "",\n'
        '  "address_text": "",\n'
        '  "city_text": "",\n'
        '  "lineup": [],\n'
        '  "ticketing_text": "",\n'
        '  "visual_layout_summary": "",\n'
        '  "context_match": {"title": "unknown", "date": "unknown", "venue": "unknown", "address": "unknown"},\n'
        '  "risk_flags": [],\n'
        '  "confidence": 0.0\n'
        "}"
    )


def provider_config(name: str) -> ProviderConfig:
    key = name.lower()
    if key == "stepfun":
        api_key_env = (
            "STEPFUN_VISION_API_KEY"
            if os.environ.get("STEPFUN_VISION_API_KEY")
            else ("STEP_API_KEY" if os.environ.get("STEP_API_KEY") else "STEPFUN_API_KEY")
        )
        base_url = (os.environ.get("STEPFUN_VISION_BASE_URL") or os.environ.get("STEPFUN_BASE_URL") or DEFAULT_STEPFUN_BASE_URL).rstrip("/")
        return ProviderConfig(
            name="stepfun",
            base_url=base_url,
            model=os.environ.get("STEPFUN_VISION_MODEL") or DEFAULT_STEPFUN_MODEL,
            api_key_env=api_key_env,
            configured=bool(base_url and os.environ.get(api_key_env)),
        )
    if key == "mimo":
        api_key_env = "MIMO_VISION_API_KEY" if os.environ.get("MIMO_VISION_API_KEY") else "MIMO_API_KEY"
        base_url = (os.environ.get("MIMO_VISION_BASE_URL") or DEFAULT_MIMO_BASE_URL).rstrip("/")
        return ProviderConfig(
            name="mimo",
            base_url=base_url,
            model=os.environ.get("MIMO_VISION_MODEL") or DEFAULT_MIMO_MODEL,
            api_key_env=api_key_env,
            configured=bool(base_url and os.environ.get(api_key_env)),
        )
    raise ValueError(f"unknown provider: {name}")


def build_chat_payload(model: str, prompt: str, image_data_url: str, *, json_mode: bool = True) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return only valid JSON. Do not include markdown fences.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": 4096,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def build_provider_payload(config: ProviderConfig, prompt: str, image_data_url: str, *, json_mode: bool = True) -> dict[str, Any]:
    payload = build_chat_payload(config.model, prompt, image_data_url, json_mode=json_mode)
    if config.name == "mimo":
        payload["max_completion_tokens"] = payload.pop("max_tokens")
    return payload


def extract_regex(pattern: str, text: str, flags: int = re.I) -> str:
    match = re.search(pattern, text, flags)
    return match.group(0).strip() if match else ""


def build_local_ocr_parsed(ocr_text: str, item: dict[str, Any]) -> dict[str, Any]:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    ocr_norm = normalize_text(ocr_text)
    expected_title = first_non_empty(item.get("title"), item.get("title_display"), item.get("title_original"))
    expected_venue = first_non_empty(item.get("venue"), item.get("venue_name"))
    expected_address = first_non_empty(item.get("address"), item.get("address_full"))
    expected_lineup = item.get("lineup") or item.get("lineup_artists") or []
    event_title = expected_title if expected_title and normalize_text(expected_title) in ocr_norm else (lines[0] if lines else "")
    date_text = extract_regex(r"20\d{2}[./-]\d{1,2}[./-]\d{1,2}", ocr_text)
    time_text = extract_regex(r"\b[0-2]?\d[:：][0-5]\d\s*[-–]\s*(?:late|[0-2]?\d[:：][0-5]\d)\b", ocr_text)
    venue_text = expected_venue if expected_venue and normalize_text(expected_venue) in ocr_norm else ""
    address_text = expected_address if expected_address and normalize_text(expected_address) in ocr_norm else ""
    lineup = [name for name in expected_lineup if normalize_text(name) in ocr_norm]
    return {
        "schema_version": "poster_understanding.local_ocr_baseline.v1",
        "is_main_event_poster": bool(event_title and date_text and time_text),
        "visible_text_lines": lines[:80],
        "event_title": event_title,
        "date_text": date_text,
        "time_text": time_text,
        "venue_text": venue_text,
        "address_text": address_text,
        "city_text": "",
        "lineup": lineup,
        "ticketing_text": extract_regex(r"before\s*23[:：]00.*?80rmb", ocr_text.replace("\n", " "), flags=re.I),
        "visual_layout_summary": "local OCR text baseline; no image layout understanding",
        "context_match": {},
        "risk_flags": ["text_only_baseline", "no_visual_layout_reasoning"],
        "confidence": None,
    }


def redact_error(value: str) -> str:
    text = value
    secrets = []
    for name in SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret and len(secret) >= 6:
            secrets.append(secret)
    for secret in sorted(set(secrets), key=len, reverse=True):
        text = text.replace(secret, "<redacted>")
    return text[:1000]


def call_openai_compatible(config: ProviderConfig, payload: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
    api_key = os.environ.get(config.api_key_env)
    if not api_key:
        raise RuntimeError(f"{config.api_key_env} is not set")
    base = config.base_url.rstrip("/")
    url = f"{base}/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    start = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(redact_error(f"HTTP {exc.code}: {raw_error}")) from exc
    except Exception as exc:  # noqa: BLE001 - report-only runner must preserve diagnostic.
        raise RuntimeError(redact_error(str(exc))) from exc
    elapsed_ms = int((time.time() - start) * 1000)
    parsed = json.loads(raw)
    return {"raw": parsed, "elapsed_ms": elapsed_ms}


def extract_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or part.get("content") or "") for part in content if isinstance(part, dict))
    return str(content or "")


def extract_finish_reason(response: dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices:
        return ""
    return str(choices[0].get("finish_reason") or "")


def parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    if not text:
        return {}
    try:
        value = json.loads(text)
        return canonicalize_parsed_json(value if isinstance(value, dict) else {"value": value})
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {"parse_error": "no_json_object", "raw_text": text[:2000]}
        try:
            value = json.loads(match.group(0))
            return canonicalize_parsed_json(value if isinstance(value, dict) else {"value": value})
        except json.JSONDecodeError as exc:
            return {"parse_error": str(exc), "raw_text": text[:2000]}


def canonicalize_parsed_json(value: dict[str, Any]) -> dict[str, Any]:
    parsed = normalize_model_json(value)
    if "schema_version" not in parsed:
        for key in list(parsed):
            if (
                key.strip(" :") == ""
                and str(parsed.get(key, "")).startswith("poster_understanding.")
            ) or key.startswith("poster_understanding."):
                if key.startswith("poster_understanding."):
                    parsed["schema_version"] = str(parsed.pop(key))
                    break
                parsed["schema_version"] = parsed.pop(key)
                break
    return parsed


def normalize_model_json(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            cleaned_key = str(key).strip().strip('"').strip("'").rstrip("{").strip()
            cleaned_key = re.sub(r"^[\s:]+|[\s:]+$", "", cleaned_key)
            if not cleaned_key:
                normalized_value = normalize_model_json(item)
                if str(normalized_value).startswith("poster_understanding."):
                    normalized["schema_version"] = normalized_value
                continue
            normalized[cleaned_key] = normalize_model_json(item)
        return normalized
    if isinstance(value, list):
        return [normalize_model_json(item) for item in value if normalize_model_json(item) != ""]
    if isinstance(value, str):
        text = value.strip()
        text = text.strip().strip(",").strip()
        if text in {"[]", "{}"}:
            return ""
        text = text.lstrip("[").rstrip("]").strip()
        text = text.strip('"').strip("'").strip().strip(",").strip()
        return text
    return value


def is_malformed_output(parsed: dict[str, Any]) -> bool:
    if not isinstance(parsed, dict) or parsed.get("parse_error"):
        return True
    return not any(key in parsed for key in OUTPUT_SIGNAL_KEYS)


def score_output(parsed: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "title": first_non_empty(item.get("title"), item.get("title_display"), item.get("title_original")),
        "date": first_non_empty(item.get("event_date_start"), item.get("event_date_text")),
        "time": first_non_empty(item.get("event_time_text"), item.get("running_hours_text"), item.get("time_start")),
        "city": first_non_empty(item.get("city"), item.get("city_name")),
        "venue": first_non_empty(item.get("venue"), item.get("venue_name")),
        "address": first_non_empty(item.get("address"), item.get("address_full")),
    }
    extracted = {
        "title": first_non_empty(parsed.get("event_title")),
        "date": first_non_empty(parsed.get("date_text")),
        "time": first_non_empty(parsed.get("time_text")),
        "city": first_non_empty(parsed.get("city_text")),
        "venue": first_non_empty(parsed.get("venue_text")),
        "address": first_non_empty(parsed.get("address_text")),
    }
    filled_fields = [key for key, value in extracted.items() if value]
    visible_lines = parsed.get("visible_text_lines") if isinstance(parsed.get("visible_text_lines"), list) else []
    if visible_lines:
        filled_fields.append("visible_text_lines")
    if parsed.get("visual_layout_summary"):
        filled_fields.append("visual_layout_summary")
    if parsed.get("lineup"):
        filled_fields.append("lineup")
    correctness: dict[str, str] = {}
    matches = 0
    comparable = 0
    for key, expected_value in expected.items():
        if not expected_value:
            correctness[key] = "no_ground_truth"
            continue
        comparable += 1
        got = extracted.get(key, "")
        exp_norm = normalize_text(expected_value)
        got_norm = normalize_text(got)
        if got_norm and (got_norm in exp_norm or exp_norm in got_norm):
            correctness[key] = "match"
            matches += 1
        elif got_norm:
            correctness[key] = "mismatch"
        else:
            correctness[key] = "missing"
    info_depth_score = min(10, len(set(filled_fields)))
    correctness_score = round((matches / comparable) * 10, 2) if comparable else 0.0
    main_poster_value = parsed.get("is_main_event_poster")
    expected_main_poster = item.get("is_main_event_poster")
    if isinstance(expected_main_poster, bool):
        main_poster_score = 5 if main_poster_value is expected_main_poster else 0
    else:
        main_poster_score = 5 if main_poster_value is True else 2 if main_poster_value is None else 0
    return {
        "info_depth_score": info_depth_score,
        "correctness_score": correctness_score,
        "main_poster_score": main_poster_score,
        "expected_is_main_event_poster": expected_main_poster
        if isinstance(expected_main_poster, bool)
        else None,
        "actual_is_main_event_poster": main_poster_value
        if isinstance(main_poster_value, bool) or main_poster_value is None
        else None,
        "field_correctness": correctness,
        "filled_fields": sorted(set(filled_fields)),
    }


def run_provider(
    name: str,
    prompt: str,
    image_data_url: str,
    prompt_item: dict[str, Any],
    score_item: dict[str, Any],
    *,
    execute: bool,
    timeout_sec: int,
    malformed_retries: int,
    api_retries: int,
    json_mode: bool,
    mock_response_path: Path | None,
    ocr_text: str = "",
) -> dict[str, Any]:
    if name.lower() == "local_ocr":
        if not ocr_text:
            return {
                "provider": "local_ocr",
                "model": "rapidocr_cache_text",
                "configured": False,
                "network_call_executed": False,
                "status": "not_configured",
                "reason": "--ocr-text was not provided",
            }
        parsed = build_local_ocr_parsed(ocr_text, prompt_item)
        return {
            "provider": "local_ocr",
            "model": "rapidocr_cache_text",
            "configured": True,
            "network_call_executed": False,
            "status": "ok",
            "parsed": parsed,
            "score": score_output(parsed, score_item),
        }
    config = provider_config(name)
    payload = build_provider_payload(config, prompt, image_data_url, json_mode=json_mode)
    result: dict[str, Any] = {
        "provider": config.name,
        "model": config.model,
        "base_url": config.base_url if config.name != "mimo" else ("configured" if config.base_url else ""),
        "configured": config.configured,
        "network_call_executed": False,
            "request_payload_preview": {
                "model": payload["model"],
                "message_count": len(payload["messages"]),
                "has_image_data_url": image_data_url.startswith("data:image/"),
                "json_mode": json_mode,
            },
        }
    if mock_response_path:
        raw = read_json(mock_response_path)
        content = extract_content(raw) if "choices" in raw else json.dumps(raw, ensure_ascii=False)
        parsed = parse_json_content(content)
        result.update({"status": "mocked", "parsed": parsed, "score": score_output(parsed, score_item)})
        return result
    if not config.configured:
        result.update({"status": "not_configured", "reason": f"{config.api_key_env}/base URL missing"})
        return result
    if not execute:
        result.update({"status": "dry_run", "reason": "pass --execute to call the provider"})
        return result
    attempts = []
    try:
        parsed: dict[str, Any] = {}
        elapsed_ms = 0
        malformed_retries_left = max(0, malformed_retries)
        api_retries_left = max(0, api_retries)
        attempt_index = 0
        retry_after_malformed = False
        while True:
            attempt_index += 1
            retry_prompt = prompt
            if retry_after_malformed:
                retry_prompt = (
                    prompt
                    + "\n\n上一次输出不是目标 JSON 对象。请只输出完整 JSON 对象，"
                    "必须包含 is_main_event_poster、visible_text_lines、event_title、date_text、"
                    "time_text、venue_text、address_text、city_text、lineup、risk_flags、confidence。"
                    "不要输出空对象，不要输出 JSON schema，不要新增空字符串键。"
                )
            try:
                response = call_openai_compatible(
                    config,
                    build_provider_payload(config, retry_prompt, image_data_url, json_mode=json_mode),
                    timeout_sec,
                )
            except Exception as exc:  # noqa: BLE001
                attempts.append({"attempt": attempt_index, "error": redact_error(str(exc)), "malformed": None})
                if api_retries_left > 0:
                    api_retries_left -= 1
                    retry_after_malformed = False
                    continue
                raise
            content = extract_content(response["raw"])
            parsed = parse_json_content(content)
            elapsed_ms += response["elapsed_ms"]
            finish_reason = extract_finish_reason(response["raw"])
            malformed = is_malformed_output(parsed) or finish_reason == "length"
            attempts.append(
                {
                    "attempt": attempt_index,
                    "elapsed_ms": response["elapsed_ms"],
                    "finish_reason": finish_reason,
                    "malformed": malformed,
                }
            )
            if not malformed:
                break
            if malformed_retries_left <= 0:
                break
            malformed_retries_left -= 1
            retry_after_malformed = True
        result.update(
            {
                "status": "ok",
                "network_call_executed": True,
                "elapsed_ms": elapsed_ms,
                "attempts": attempts,
                "malformed_output": attempts[-1]["malformed"] if attempts else is_malformed_output(parsed),
                "parsed": parsed,
                "score": score_output(parsed, score_item),
            }
        )
    except Exception as exc:  # noqa: BLE001
        result.update({"status": "error", "error": redact_error(str(exc)), "attempts": attempts})
    return result


def compare_provider_scores(results: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in results if isinstance(row.get("score"), dict)]
    ranking = sorted(
        scored,
        key=lambda row: (
            row["score"].get("correctness_score", 0),
            row["score"].get("info_depth_score", 0),
            row["score"].get("main_poster_score", 0),
        ),
        reverse=True,
    )
    return {
        "ranking": [
            {
                "provider": row.get("provider"),
                "correctness_score": row["score"].get("correctness_score", 0),
                "info_depth_score": row["score"].get("info_depth_score", 0),
                "main_poster_score": row["score"].get("main_poster_score", 0),
            }
            for row in ranking
        ],
        "winner": ranking[0].get("provider") if ranking else "",
    }


def summarize_provider_outcome(results: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    network_call_count = 0
    malformed_output_count = 0
    hard_failure_count = 0
    not_configured_count = 0
    for provider in results:
        status = str(provider.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if provider.get("network_call_executed"):
            network_call_count += 1
        if provider.get("malformed_output"):
            malformed_output_count += 1
        if status == "not_configured":
            not_configured_count += 1
        if status not in SOFT_PROVIDER_STATUSES:
            hard_failure_count += 1
    return {
        "ok": hard_failure_count == 0 and malformed_output_count == 0,
        "status_counts": status_counts,
        "network_call_count": network_call_count,
        "not_configured_count": not_configured_count,
        "malformed_output_count": malformed_output_count,
        "hard_failure_count": hard_failure_count,
    }


def parse_mock_map(mock_response_args: list[str] | None) -> dict[str, Path]:
    mock_map: dict[str, Path] = {}
    for item_arg in mock_response_args or []:
        provider, _, path = item_arg.partition("=")
        if not provider or not path:
            raise ValueError("--mock-response must use provider=path")
        mock_map[provider.lower()] = Path(path)
    return mock_map


def build_single_report(
    args: argparse.Namespace,
    *,
    image: str,
    ocr_text: str = "",
    api_dir: str = "",
    item_id: str = "",
    ground_truth: str = "",
    fixture_id: str = "",
    case_type: str = "",
    mock_map: dict[str, Path] | None = None,
) -> dict[str, Any]:
    image_path = Path(image).resolve()
    api_dir_path = Path(api_dir).resolve() if api_dir else None
    prompt_item = load_item_context(api_dir_path, item_id) if item_id else {}
    ground_truth_path = Path(ground_truth).resolve() if ground_truth else None
    ground_truth_item = load_ground_truth(ground_truth_path)
    score_item = merge_context(prompt_item, ground_truth_item)
    image_data_url = image_to_data_url(image_path)
    ocr_text_path = Path(ocr_text).resolve() if ocr_text else None
    ocr_text = read_optional_text(ocr_text_path)
    prompt = build_prompt(prompt_item)
    mock_map = mock_map or {}
    results = [
        run_provider(
            provider,
            prompt,
            image_data_url,
            prompt_item,
            score_item,
            execute=args.execute,
            timeout_sec=args.timeout_sec,
            malformed_retries=args.malformed_retries,
            api_retries=args.api_retries,
            json_mode=not args.disable_json_mode,
            mock_response_path=mock_map.get(provider.lower()),
            ocr_text=ocr_text,
        )
        for provider in args.provider
    ]
    safety = {
        "report_only": True,
        "network_enabled": bool(args.execute),
        "api_key_persisted": False,
        "db_write_executed": False,
        "cloudbase_write_executed": False,
        "deploy_or_upload_executed": False,
    }
    outcome = summarize_provider_outcome(results)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": outcome["ok"],
        "fixture_id": fixture_id,
        "case_type": case_type,
        "image_path": str(image_path),
        "image_size_bytes": image_path.stat().st_size,
        "ocr_text_path": str(ocr_text_path) if ocr_text_path else "",
        "api_dir": str(api_dir_path) if api_dir_path else "",
        "item_id": item_id,
        "ground_truth_path": str(ground_truth_path) if ground_truth_path else "",
        "prompt_context": summarize_context(prompt_item),
        "score_context": summarize_context(score_item),
        "item_context": summarize_context(score_item),
        "prompt": prompt if args.include_prompt else "<omitted; pass --include-prompt>",
        "providers": results,
        "comparison": compare_provider_scores(results),
        "outcome": outcome,
        "safety": safety,
    }


def summarize_batch_provider(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_provider: dict[str, dict[str, Any]] = {}
    for report in rows:
        for provider in report.get("providers", []):
            name = str(provider.get("provider") or "")
            if not name:
                continue
            bucket = by_provider.setdefault(
                name,
                {
                    "provider": name,
                    "fixture_count": 0,
                    "status_counts": {},
                    "network_call_count": 0,
                    "scored_count": 0,
                    "correctness_total": 0.0,
                    "info_depth_total": 0.0,
                    "main_poster_total": 0.0,
                    "case_types": {},
                },
            )
            bucket["fixture_count"] += 1
            status = str(provider.get("status") or "unknown")
            bucket["status_counts"][status] = bucket["status_counts"].get(status, 0) + 1
            if provider.get("network_call_executed"):
                bucket["network_call_count"] += 1
            score = provider.get("score")
            case_type = str(report.get("case_type") or "uncategorized")
            case_bucket = bucket["case_types"].setdefault(case_type, {"fixture_count": 0, "scored_count": 0})
            case_bucket["fixture_count"] += 1
            if isinstance(score, dict):
                bucket["scored_count"] += 1
                case_bucket["scored_count"] += 1
                for field, total_name in (
                    ("correctness_score", "correctness_total"),
                    ("info_depth_score", "info_depth_total"),
                    ("main_poster_score", "main_poster_total"),
                ):
                    value = float(score.get(field) or 0)
                    bucket[total_name] += value
                    case_bucket[total_name] = case_bucket.get(total_name, 0.0) + value
    for bucket in by_provider.values():
        scored_count = bucket["scored_count"] or 1
        bucket["avg_correctness_score"] = round(bucket.pop("correctness_total") / scored_count, 2)
        bucket["avg_info_depth_score"] = round(bucket.pop("info_depth_total") / scored_count, 2)
        bucket["avg_main_poster_score"] = round(bucket.pop("main_poster_total") / scored_count, 2)
        for case_bucket in bucket["case_types"].values():
            case_scored = case_bucket["scored_count"] or 1
            case_bucket["avg_correctness_score"] = round(case_bucket.pop("correctness_total", 0.0) / case_scored, 2)
            case_bucket["avg_info_depth_score"] = round(case_bucket.pop("info_depth_total", 0.0) / case_scored, 2)
            case_bucket["avg_main_poster_score"] = round(case_bucket.pop("main_poster_total", 0.0) / case_scored, 2)
    ranking = sorted(
        by_provider.values(),
        key=lambda row: (
            row.get("avg_correctness_score", 0),
            row.get("avg_info_depth_score", 0),
            row.get("avg_main_poster_score", 0),
        ),
        reverse=True,
    )
    return {
        "providers": ranking,
        "winner": ranking[0]["provider"] if ranking else "",
    }


def build_batch_report(args: argparse.Namespace) -> dict[str, Any]:
    fixture_list_path = Path(args.fixture_list).resolve()
    fixture_payload = read_json(fixture_list_path)
    fixtures = fixture_payload.get("fixtures") if isinstance(fixture_payload, dict) else fixture_payload
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError(f"fixture list must contain a non-empty fixtures array: {fixture_list_path}")
    mock_map = parse_mock_map(args.mock_response)
    reports = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ValueError("each fixture must be a JSON object")
        reports.append(
            build_single_report(
                args,
                image=str(fixture["image"]),
                ocr_text=str(fixture.get("ocr_text") or ""),
                api_dir=str(fixture.get("api_dir") or args.api_dir or ""),
                item_id=str(fixture.get("item_id") or ""),
                ground_truth=str(fixture.get("ground_truth") or ""),
                fixture_id=str(fixture.get("id") or ""),
                case_type=str(fixture.get("case_type") or ""),
                mock_map=mock_map,
            )
        )
    aggregate = summarize_batch_provider(reports)
    provider_results = [provider for report in reports for provider in report.get("providers", [])]
    outcome = summarize_provider_outcome(provider_results)
    safety = {
        "report_only": True,
        "network_enabled": bool(args.execute),
        "api_key_persisted": False,
        "db_write_executed": False,
        "cloudbase_write_executed": False,
        "deploy_or_upload_executed": False,
    }
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": outcome["ok"],
        "fixture_list_path": str(fixture_list_path),
        "fixture_count": len(reports),
        "providers_requested": args.provider,
        "fixtures": reports,
        "aggregate": aggregate,
        "outcome": outcome,
        "safety": safety,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.fixture_list:
        return build_batch_report(args)
    if not args.image:
        raise ValueError("--image is required unless --fixture-list is used")
    return build_single_report(
        args,
        image=args.image,
        ocr_text=args.ocr_text or "",
        api_dir=args.api_dir or "",
        item_id=args.item_id or "",
        ground_truth=args.ground_truth or "",
        mock_map=parse_mock_map(args.mock_response),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Local poster image path. Sent as base64 data URL when --execute is used.")
    parser.add_argument("--fixture-list", help="JSON fixture list for small batch model comparison.")
    parser.add_argument("--ocr-text", help="Optional local OCR text file for local_ocr baseline scoring.")
    parser.add_argument("--api-dir", help="Optional weekly package directory containing current.json.")
    parser.add_argument("--item-id", help="Optional item id for correctness scoring against package context.")
    parser.add_argument("--ground-truth", help="Optional JSON object that overrides/adds item context for scoring.")
    parser.add_argument("--provider", action="append", choices=["stepfun", "mimo", "local_ocr"], default=None)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--execute", action="store_true", help="Actually call configured provider APIs.")
    parser.add_argument("--include-prompt", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--malformed-retries", type=int, default=1, help="Retry provider call when the JSON object is structurally malformed.")
    parser.add_argument("--api-retries", type=int, default=1, help="Retry provider call on transport errors such as read timeouts.")
    parser.add_argument("--disable-json-mode", action="store_true", help="Do not send response_format=json_object; useful when a provider's vision JSON mode returns malformed schema fragments.")
    parser.add_argument("--mock-response", action="append", help="Offline provider response as provider=path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.provider is None:
        args.provider = ["stepfun", "mimo"]
        if args.ocr_text:
            args.provider.append("local_ocr")
    out_dir = Path(args.out_dir)
    report = build_report(args)
    report_name = "poster_vision_batch_report.json" if report.get("schema_version") == BATCH_SCHEMA_VERSION else "poster_vision_compare_report.json"
    write_json(out_dir / report_name, report)
    ok = bool(report.get("ok", True))
    print(json.dumps({"ok": ok, "report": str(out_dir / report_name)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
