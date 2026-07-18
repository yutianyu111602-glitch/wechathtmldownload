#!/usr/bin/env python3
"""Enrich weekly activity candidates from Sanji local article images via VL.

This is the no-OCR image extraction path for the Sanji daily pipeline.
It reads the Sanji `article_dir/assets` files referenced by the queue, sends a
small number of local images directly to a VL model, and writes the same pack
shape consumed by the downstream weekly pipeline.
"""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CANDIDATE_FILE = "weekly_activity_recommendation_candidates.jsonl"
REVIEW_FILE = "weekly_activity_recommendation_review_candidates.jsonl"
SOURCE_EVIDENCE_DIR = "source_evidence"
ROUTING_MANIFEST_FILE = "routing_manifest.jsonl"
QUEUE_SCHEDULE_MARKER = ":schedule:"
HASH16_RE = re.compile(r"(?i)(?<![0-9a-f])([0-9a-f]{16})(?![0-9a-f])")
OVERVIEW_TITLE_RE = re.compile(
    r"(活动一览|活动预览|活动汇总|活动合集|"
    r"本周(?:活动)?(?:一览|预览|安排|日程)|"
    r"本月(?:活动)?(?:一览|预览|安排|日程)|"
    r"月度活动(?:一览|预览|安排|日程)|"
    r"(?:一|二|三|四|五|六|七|八|九|十|十一|十二)?月活动(?:一览|预览|安排|日程)|"
    r"端午(?:假期)?活动(?:一览|预览|安排|日程))",
    re.I,
)
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen3.6-plus"
DEFAULT_MAX_IMAGES = 0
DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_MIMO_MODEL = "mimo-v2.5"
POSTER_VL_USAGE_SUMMARY_FILE = "poster_vl_usage_summary.json"
POSTER_VL_USAGE_DETAILS_FILE = "poster_vl_usage_details.jsonl"
QWEN_VL_PRICE_SOURCE_URL = "https://help.aliyun.com/zh/model-studio/model-pricing"
QWEN3_VL_PLUS_PRICING_TIERS = (
    {
        "tier": "0<Token<=32K",
        "max_prompt_tokens": 32_000,
        "input_cny_per_million_tokens": 1.0,
        "output_cny_per_million_tokens": 10.0,
    },
    {
        "tier": "32K<Token<=128K",
        "max_prompt_tokens": 128_000,
        "input_cny_per_million_tokens": 1.5,
        "output_cny_per_million_tokens": 15.0,
    },
    {
        "tier": "128K<Token<=256K",
        "max_prompt_tokens": 256_000,
        "input_cny_per_million_tokens": 3.0,
        "output_cny_per_million_tokens": 30.0,
    },
)
QWEN3_VL_PLUS_MODEL_ALIASES = {
    "qwen3-vl-plus",
    "qwen3-vl-plus-latest",
    "qwen3-vl-plus-2025-12-19",
}
QWEN3_6_PLUS_PRICING_TIERS = (
    {
        "tier": "0<Token<=256K",
        "max_prompt_tokens": 256_000,
        "input_cny_per_million_tokens": 2.0,
        "output_cny_per_million_tokens": 12.0,
    },
    {
        "tier": "256K<Token<=1M",
        "max_prompt_tokens": 1_000_000,
        "input_cny_per_million_tokens": 8.0,
        "output_cny_per_million_tokens": 48.0,
    },
)
QWEN3_6_PLUS_MODEL_ALIASES = {
    "qwen3.6-plus",
    "qwen3.6-plus-2026-04-02",
}


@dataclass
class ImageAsset:
    path: Path
    source_url: str
    sha: str
    order: int
    size: int


@dataclass
class ProviderConfig:
    name: str
    api_key: str
    base_url: str
    model: str


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
            if isinstance(item, dict):
                rows.append(item)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def base_queue_id(queue_id: str) -> str:
    if QUEUE_SCHEDULE_MARKER in queue_id:
        return queue_id.split(QUEUE_SCHEDULE_MARKER, 1)[0]
    return queue_id


def env_first(names: Iterable[str]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def env_float(names: Iterable[str]) -> float | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if not value:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


def provider_config(name: str, model_override: str = "") -> ProviderConfig:
    normalized = (name or "").strip().lower()
    if normalized in {"qwen", "qwen3_vl", "qwen3-vl", "dashscope"}:
        api_key = env_first(
            [
                "ATLAS_DASHSCOPE_API_KEY",
                "DASHSCOPE_API_KEY",
                "DASHSCOPE_COMPATIBLE_API_KEY",
                "QWEN_API_KEY",
            ]
        )
        return ProviderConfig(
            name="qwen3_vl",
            api_key=api_key,
            base_url=env_first(["ATLAS_DASHSCOPE_BASE_URL", "DASHSCOPE_BASE_URL"])
            or DEFAULT_QWEN_BASE_URL,
            model=(model_override or "").strip()
            or env_first(["ATLAS_QWEN_VL_MODEL", "QWEN3_VL_MODEL", "QWEN_VL_MODEL"])
            or DEFAULT_QWEN_MODEL,
        )
    if normalized in {"mimo", "mimo_vl", "mimo-vl"}:
        api_key = env_first(["MIMO_VISION_API_KEY", "ATLAS_MIMO_API_KEY", "MIMO_API_KEY"])
        return ProviderConfig(
            name="mimo",
            api_key=api_key,
            base_url=env_first(["MIMO_VISION_BASE_URL", "MIMO_BASE_URL"]) or DEFAULT_MIMO_BASE_URL,
            model=(model_override or "").strip()
            or env_first(["MIMO_VISION_MODEL", "ATLAS_MIMO_MODEL", "MIMO_MODEL"])
            or DEFAULT_MIMO_MODEL,
        )
    raise ValueError(f"Unsupported VL provider: {name}")


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def first_int(mapping: dict[str, Any], keys: Iterable[str]) -> int | None:
    for key in keys:
        value = mapping.get(key)
        number = as_int(value)
        if number is not None:
            return number
    return None


def usage_to_dict(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        data = value.model_dump()
        return data if isinstance(data, dict) else {}
    if hasattr(value, "dict"):
        data = value.dict()
        return data if isinstance(data, dict) else {}
    return {}


def usage_token_counts(usage: dict[str, Any]) -> dict[str, int]:
    details = usage.get("prompt_tokens_details")
    if not isinstance(details, dict):
        details = usage.get("input_tokens_details")
    if not isinstance(details, dict):
        details = {}
    prompt_tokens = first_int(usage, ("prompt_tokens", "input_tokens", "input_token_count")) or 0
    completion_tokens = first_int(usage, ("completion_tokens", "output_tokens", "output_token_count")) or 0
    total_tokens = first_int(usage, ("total_tokens", "token_count")) or prompt_tokens + completion_tokens
    cached_prompt_tokens = (
        first_int(details, ("cached_tokens", "cache_read_input_tokens", "cached_input_tokens"))
        or first_int(usage, ("cached_tokens", "cached_prompt_tokens", "cache_read_input_tokens", "cached_input_tokens"))
        or 0
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_prompt_tokens": cached_prompt_tokens,
        "billable_prompt_tokens": max(0, prompt_tokens - cached_prompt_tokens),
    }


def pricing_tier_for_prompt_tokens(tiers: Iterable[dict[str, Any]], prompt_tokens: int) -> dict[str, Any]:
    for tier in tiers:
        if 0 < prompt_tokens <= int(tier["max_prompt_tokens"]):
            return dict(tier)
    return {}


def provider_pricing_cny_per_mtok(provider: ProviderConfig, prompt_tokens: int) -> dict[str, Any]:
    input_override = env_float(("HUAIDJ_VL_INPUT_CNY_PER_MTOK", "HUAIDJ_QWEN_VL_INPUT_CNY_PER_MTOK"))
    output_override = env_float(("HUAIDJ_VL_OUTPUT_CNY_PER_MTOK", "HUAIDJ_QWEN_VL_OUTPUT_CNY_PER_MTOK"))
    cached_override = env_float(("HUAIDJ_VL_CACHED_INPUT_CNY_PER_MTOK", "HUAIDJ_QWEN_VL_CACHED_INPUT_CNY_PER_MTOK"))
    if input_override is not None and output_override is not None:
        pricing = {
            "currency": "CNY",
            "input_cny_per_million_tokens": input_override,
            "output_cny_per_million_tokens": output_override,
            "pricing_basis": "env_override",
            "pricing_source_url": "",
            "pricing_overridden_by_env": True,
        }
        if cached_override is not None:
            pricing["cached_input_cny_per_million_tokens"] = cached_override
        return pricing

    model_key = provider.model.strip().lower()
    if provider.name == "qwen3_vl" and model_key in QWEN3_6_PLUS_MODEL_ALIASES:
        tier = pricing_tier_for_prompt_tokens(QWEN3_6_PLUS_PRICING_TIERS, prompt_tokens)
        if not tier:
            return {
                "currency": "CNY",
                "pricing_basis": "dashscope_qwen3_6_plus_cn_public_2026_06",
                "pricing_source_url": QWEN_VL_PRICE_SOURCE_URL,
                "usage_note": "usage_tokens_recorded_but_prompt_tokens_outside_known_pricing_tiers",
                "pricing_overridden_by_env": False,
            }
        pricing = {
            **tier,
            "currency": "CNY",
            "pricing_basis": "dashscope_qwen3_6_plus_cn_public_2026_06",
            "pricing_source_url": QWEN_VL_PRICE_SOURCE_URL,
            "pricing_overridden_by_env": False,
        }
        if cached_override is not None:
            pricing["cached_input_cny_per_million_tokens"] = cached_override
        return pricing
    if provider.name == "qwen3_vl" and model_key in QWEN3_VL_PLUS_MODEL_ALIASES:
        tier = pricing_tier_for_prompt_tokens(QWEN3_VL_PLUS_PRICING_TIERS, prompt_tokens)
        if not tier:
            return {
                "currency": "CNY",
                "pricing_basis": "dashscope_qwen3_vl_plus_cn_public_2026_06",
                "pricing_source_url": QWEN_VL_PRICE_SOURCE_URL,
                "usage_note": "usage_tokens_recorded_but_prompt_tokens_outside_known_pricing_tiers",
                "pricing_overridden_by_env": False,
            }
        pricing = {
            **tier,
            "currency": "CNY",
            "pricing_basis": "dashscope_qwen3_vl_plus_cn_public_2026_06",
            "pricing_source_url": QWEN_VL_PRICE_SOURCE_URL,
            "pricing_overridden_by_env": False,
        }
        if cached_override is not None:
            pricing["cached_input_cny_per_million_tokens"] = cached_override
        return pricing
    return {}


def calculate_usage_cost_cny(counts: dict[str, int], pricing: dict[str, Any]) -> dict[str, float] | None:
    if "input_cny_per_million_tokens" not in pricing or "output_cny_per_million_tokens" not in pricing:
        return None
    cached_prompt = counts["cached_prompt_tokens"]
    if cached_prompt and "cached_input_cny_per_million_tokens" not in pricing:
        return None
    billable_prompt = counts["billable_prompt_tokens"]
    input_cost = billable_prompt * float(pricing["input_cny_per_million_tokens"]) / 1_000_000
    cached_cost = (
        cached_prompt * float(pricing["cached_input_cny_per_million_tokens"]) / 1_000_000
        if cached_prompt
        else 0.0
    )
    output_cost = counts["completion_tokens"] * float(pricing["output_cny_per_million_tokens"]) / 1_000_000
    return {
        "input_cost_cny": round(input_cost, 8),
        "cached_input_cost_cny": round(cached_cost, 8),
        "output_cost_cny": round(output_cost, 8),
        "cost_cny": round(input_cost + cached_cost + output_cost, 8),
    }


def unknown_usage_cost_note(counts: dict[str, int], pricing: dict[str, Any]) -> str:
    if pricing.get("usage_note"):
        return str(pricing["usage_note"])
    if counts["cached_prompt_tokens"] and "cached_input_cny_per_million_tokens" not in pricing:
        return "usage_tokens_recorded_but_cached_pricing_unknown"
    if pricing:
        return "usage_tokens_recorded_but_pricing_incomplete"
    return "usage_tokens_recorded_but_pricing_unknown"


def pricing_public_fields(pricing: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in pricing.items()
        if key not in {"usage_note"}
    }


def build_usage_record(
    provider: ProviderConfig,
    usage: dict[str, Any],
    *,
    fallback_used: bool,
    image_count: int,
    queue_id: str,
) -> dict[str, Any]:
    counts = usage_token_counts(usage)
    pricing = provider_pricing_cny_per_mtok(provider, counts["prompt_tokens"])
    record = {
        "provider": provider.name,
        "model": str(usage.get("model") or provider.model),
        "fallback_used": fallback_used,
        "image_count": image_count,
        "queue_id_hash": stable_hash(queue_id),
        **counts,
    }
    if pricing:
        cost = calculate_usage_cost_cny(counts, pricing)
        record.update(pricing_public_fields(pricing))
        if cost:
            record.update({**cost, "exact_available": True})
        else:
            record["exact_available"] = False
            record["usage_note"] = unknown_usage_cost_note(counts, pricing)
    else:
        record["exact_available"] = False
        record["usage_note"] = "usage_tokens_recorded_but_pricing_unknown"
    return record


def summarize_usage_records(records: list[dict[str, Any]], args: argparse.Namespace, out_dir: Path) -> dict[str, Any]:
    totals = {
        "prompt_tokens": sum(int(row.get("prompt_tokens") or 0) for row in records),
        "completion_tokens": sum(int(row.get("completion_tokens") or 0) for row in records),
        "total_tokens": sum(int(row.get("total_tokens") or 0) for row in records),
        "cached_prompt_tokens": sum(int(row.get("cached_prompt_tokens") or 0) for row in records),
        "billable_prompt_tokens": sum(int(row.get("billable_prompt_tokens") or 0) for row in records),
    }
    provider_counts: dict[str, int] = {}
    cost_records = 0
    total_cost = 0.0
    pricing_basis: dict[str, int] = {}
    for row in records:
        provider_key = f"{row.get('provider')}/{row.get('model')}"
        provider_counts[provider_key] = provider_counts.get(provider_key, 0) + 1
        basis = str(row.get("pricing_basis") or row.get("usage_note") or "")
        if basis:
            pricing_basis[basis] = pricing_basis.get(basis, 0) + 1
        if row.get("cost_cny") not in (None, ""):
            cost_records += 1
            total_cost += float(row.get("cost_cny") or 0)
    exact_available = bool(records) and cost_records == len(records)
    summary = {
        "schema_version": "poster_vl_usage_summary.v1",
        "generated_at": now_iso(),
        "source": "enrich_weekly_activity_pack_with_qwen_vl.py",
        "provider": args.provider,
        "model": args.model or DEFAULT_QWEN_MODEL,
        "fallback_provider": args.fallback_provider,
        "currency": "CNY",
        "exact_available": exact_available,
        "call_count": len(records),
        "priced_call_count": cost_records,
        "provider_counts": provider_counts,
        "pricing_basis_counts": pricing_basis,
        "details_path": str(out_dir / POSTER_VL_USAGE_DETAILS_FILE),
        **totals,
    }
    if exact_available:
        summary["cost_cny"] = round(total_cost, 6)
        summary["note"] = "usage_tokens_and_pricing_recorded"
    elif records:
        summary["estimated_cost_cny"] = ""
        summary["note"] = "usage_tokens_recorded_but_some_pricing_unknown"
    else:
        summary["note"] = "no_billable_vl_calls_recorded"
    return summary


def load_queue_lookup(queue_path: Path) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(queue_path):
        for key_name in ("queue_id", "token"):
            key = str(row.get(key_name) or "")
            if key:
                lookup.setdefault(key, row)
                lookup.setdefault(base_queue_id(key), row)
        account_key = str(row.get("account_key") or "")
        source_hash = str(row.get("source_url_hash") or row.get("source_hash") or "")
        if account_key and source_hash:
            lookup.setdefault(f"{account_key}:{source_hash}", row)
    return lookup


def resolve_source_row(candidate: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    queue_id = str(candidate.get("queue_id") or candidate.get("id") or "")
    keys = [queue_id, base_queue_id(queue_id)]
    account_key = str(candidate.get("account_key") or "")
    source_hash = str(candidate.get("source_url_hash") or candidate.get("source_hash") or "")
    if account_key and source_hash:
        keys.append(f"{account_key}:{source_hash}")
    for key in keys:
        if key and key in lookup:
            return lookup[key]
    return None


def source_hashes_from_row(candidate: dict[str, Any], source_row: dict[str, Any] | None = None) -> set[str]:
    hashes: set[str] = set()
    for row in (candidate, source_row or {}):
        for key in ("source_url_hash", "source_hash", "url_hash", "article_hash", "link_hash"):
            value = str(row.get(key) or "").strip()
            if value:
                hashes.add(value.lower())
        url = str(row.get("source_url") or row.get("url") or row.get("link") or row.get("original_url") or "").strip()
        if url:
            hashes.add(stable_hash(url).lower())
        queue_id = str(row.get("queue_id") or row.get("id") or "").strip()
        for match in HASH16_RE.finditer(queue_id):
            hashes.add(match.group(1).lower())
    return {value for value in hashes if value}


def load_published_hashes(api_dir_text: str) -> set[str]:
    if not api_dir_text:
        return set()
    api_dir = Path(api_dir_text)
    if not api_dir.exists():
        return set()
    hashes: set[str] = set()

    def walk(value: Any, key_hint: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key_hint)
        elif isinstance(value, str):
            text = value.strip()
            if key_hint in {"url_hash", "source_url_hash", "source_hash", "sourceHash", "article_hash", "link_hash"}:
                hashes.add(text.lower())
            for match in HASH16_RE.finditer(text):
                hashes.add(match.group(1).lower())

    current_path = api_dir / "current.json"
    if current_path.exists():
        try:
            walk(json.loads(current_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    source_map_path = api_dir / "source_actions" / "source_url_map.json"
    if source_map_path.exists():
        try:
            source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
            sources = source_map.get("sources") if isinstance(source_map, dict) else {}
            if isinstance(sources, dict):
                for key, value in sources.items():
                    if isinstance(key, str) and key:
                        hashes.add(key.lower())
                    walk(value)
        except json.JSONDecodeError:
            pass
    return {value for value in hashes if value}


def list_strings(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def has_poster_selection_evidence(row: dict[str, Any]) -> bool:
    return isinstance(row.get("poster_selection_evidence"), dict) or isinstance(row.get("posterSelectionEvidence"), dict)


def published_item_has_lineup(row: dict[str, Any]) -> bool:
    return bool(list_strings(row.get("lineup")) or list_strings(row.get("lineup_artists")) or list_strings(row.get("poster_vl_lineup")))


def load_published_hash_quality(api_dir_text: str) -> dict[str, dict[str, bool]]:
    if not api_dir_text:
        return {}
    current_path = Path(api_dir_text) / "current.json"
    if not current_path.exists():
        return {}
    try:
        payload = json.loads(current_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return {}
    quality: dict[str, dict[str, bool]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_hashes = source_hashes_from_row(item)
        source_article = item.get("source_article")
        if isinstance(source_article, dict):
            item_hashes.update(source_hashes_from_row(source_article))
        source_action = item.get("source_action")
        if isinstance(source_action, dict):
            item_hashes.update(source_hashes_from_row(source_action))
        if not item_hashes:
            continue
        value = {
            "has_lineup": published_item_has_lineup(item),
            "has_poster_evidence": has_poster_selection_evidence(item),
        }
        for source_hash in item_hashes:
            quality[source_hash.lower()] = value
    return quality


def normalize_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value]


def parse_yyyy_mm_dd(text: str) -> dt.date | None:
    if not text:
        return None
    match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", str(text))
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def candidate_dates(candidate: dict[str, Any]) -> list[dt.date]:
    values: list[Any] = []
    for key in ("event_date_text", "date_text", "start_date", "date_start", "event_date"):
        values.extend(normalize_list(candidate.get(key)))
    dates: list[dt.date] = []
    for value in values:
        parsed = parse_yyyy_mm_dd(str(value))
        if parsed:
            dates.append(parsed)
    return dates


def title_looks_like_overview(title: str) -> bool:
    return bool(OVERVIEW_TITLE_RE.search(str(title or "")))


def should_process(candidate: dict[str, Any], window_start: dt.date, window_days: int) -> bool:
    if candidate.get("include_in_activity_feed") is False:
        return False
    if candidate.get("aggregation_parent") or candidate.get("is_aggregate_parent"):
        return False
    title = str(candidate.get("title") or candidate.get("event_title") or "")
    if title_looks_like_overview(title):
        if not QUEUE_SCHEDULE_MARKER in str(candidate.get("queue_id") or ""):
            return False
    dates = candidate_dates(candidate)
    if not dates:
        return False
    window_end = window_start + dt.timedelta(days=max(0, window_days - 1))
    return any(window_start <= item <= window_end for item in dates)


def read_asset_meta(asset: Path) -> dict[str, Any]:
    meta_path = asset.with_name(asset.name + ".meta.json")
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def select_article_assets(article_dir: str, max_images: int) -> list[ImageAsset]:
    root = Path(article_dir)
    assets_dir = root / "assets"
    if not assets_dir.exists():
        return []
    html = ""
    index_path = root / "index.html"
    if index_path.exists():
        try:
            html = index_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            html = ""
    items: list[ImageAsset] = []
    for asset in assets_dir.iterdir():
        if not asset.is_file():
            continue
        if asset.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            size = asset.stat().st_size
        except OSError:
            continue
        if size < 15000:
            continue
        meta = read_asset_meta(asset)
        source_url = str(meta.get("sourceUrl") or meta.get("source_url") or "")
        sha = str(meta.get("sha") or "")
        order = -1
        if html:
            probes = [asset.name]
            if source_url:
                probes.append(source_url)
            found = [html.find(probe) for probe in probes if probe and html.find(probe) >= 0]
            if found:
                order = min(found)
        items.append(ImageAsset(path=asset, source_url=source_url, sha=sha, order=order, size=size))
    if any(item.order >= 0 for item in items):
        items.sort(key=lambda item: (item.order if item.order >= 0 else 10**9, -item.size, item.path.name))
    else:
        items.sort(key=lambda item: (-item.size, item.path.name))
    if max_images <= 0:
        return items
    return items[:max_images]


def maybe_resize_image_bytes(path: Path, max_side: int = 1800) -> tuple[bytes, str]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    raw = path.read_bytes()
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return raw, mime
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        return raw, mime
    width, height = image.size
    if max(width, height) <= max_side:
        return raw, mime
    ratio = max_side / float(max(width, height))
    next_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
    image.thumbnail(next_size)
    out = io.BytesIO()
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), "image/png"


def image_to_data_url(path: Path) -> str:
    payload, mime = maybe_resize_image_bytes(path)
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def compact_candidate_context(candidate: dict[str, Any], source_row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "queue_id",
        "id",
        "title",
        "event_title",
        "event_date_text",
        "date_text",
        "event_time_text",
        "city",
        "venue",
        "address",
        "lineup",
        "source_url",
        "cover_url",
    ]
    candidate_part = {key: candidate.get(key) for key in keys if key in candidate}
    source_keys = [
        "account_nickname",
        "account_key",
        "title",
        "digest",
        "summary_digest",
        "post_date",
        "post_time",
        "source_url",
        "article_dir",
        "body_text_chars",
    ]
    source_part = {key: source_row.get(key) for key in source_keys if key in source_row}
    body = str(source_row.get("body_text") or source_row.get("content_text") or "")
    if body:
        source_part["body_text_excerpt"] = body[:8000]
    return {"candidate": candidate_part, "sanji_source": source_part}


def build_prompt(candidate: dict[str, Any], source_row: dict[str, Any], assets: list[ImageAsset]) -> str:
    image_notes = []
    for idx, asset in enumerate(assets):
        image_notes.append(
            {
                "index": idx,
                "file": asset.path.name,
                "source_url": asset.source_url,
                "sha": asset.sha,
                "size": asset.size,
            }
        )
    context = compact_candidate_context(candidate, source_row)
    return (
        "You are extracting one China electronic music event from a WeChat article.\n"
        "Use the attached local article images directly. Inspect every attached image before choosing "
        "the main poster or lineup. Do not assume OCR text exists.\n"
        "Do not use Sanji post_time as event time unless it is visibly part of the event poster/body.\n"
        "Main poster selection: choose the image that is the strongest single-event poster for this candidate. "
        "It must visibly match the event date/title/venue/lineup when possible. Reject account covers, QR cards, "
        "ticket screenshots, maps, drink menus, venue notices, generic artist portraits, decorative images, "
        "month/week/holiday calendars, and parent overview posters as main_poster_image_index. If no clean "
        "single-event poster is visible, return null and add risk flag no_clean_main_poster_visible.\n"
        "Lineup extraction: extract the full visible DJ/live lineup from all attached images plus the body excerpt, "
        "not only from the selected poster and not only the headliner. A normal club night often has 3 or more DJs; "
        "include every distinct DJ/live/artist name visible in poster/body order. Check lineup/DJs/support/guest/"
        "resident/host/room blocks, small footer text, timetable blocks, and B2B lines. Split B2B, slash, comma, "
        "and vertical-bar joined names into separate names, but keep each artist name spelling exactly as visible. "
        "Do not guess missing names. Do not include venue names, labels, crews, genres, ticket tiers, prose, "
        "QR/payment text, room names, or generic words such as lineup/support. If no lineup is visible, return an "
        "empty lineup and add risk flag missing_lineup_visible.\n"
        "The visible_text_lines array must include exact visible/body lines that support date, venue, title, poster "
        "choice, and lineup. The lineup_evidence array must quote exact visible/body substrings where the artist "
        "names appear.\n"
        "Parent overview/calendar articles should not be turned into a single feed event unless the "
        "candidate row is already a schedule child.\n"
        "Return one strict JSON object with this schema:\n"
        "{"
        '"is_event": boolean, "event_title": string, "date_start": "YYYY-MM-DD or empty", '
        '"date_end": "YYYY-MM-DD or empty", "time_text": string, "city": string, '
        '"venue": string, "address": string, "lineup": [string], "music_styles": [string], '
        '"price": [string], "ticketing_text": string, "main_poster_image_index": integer or null, '
        '"visible_text_lines": [string], "lineup_evidence": [string], "evidence": [string], "risk_flags": [string], '
        '"confidence": number'
        "}\n"
        "Prefer the poster/body visible facts over candidate guesses. If unknown, use empty string/list.\n"
        f"Candidate and Sanji context:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n"
        f"Attached images:\n{json.dumps(image_notes, ensure_ascii=False, indent=2)}\n"
    )


def parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model response is not a JSON object")
    return data


def provider_extra_body(provider: ProviderConfig) -> dict[str, Any]:
    if provider.name == "qwen3_vl":
        return {"enable_thinking": False}
    return {}


def call_openai_compatible_vl(
    provider: ProviderConfig,
    prompt: str,
    assets: list[ImageAsset],
    timeout_sec: int,
    retries: int,
) -> dict[str, Any]:
    if not provider.api_key:
        raise RuntimeError(f"{provider.name} API key is not configured in environment")
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:
        raise RuntimeError("openai package is required for --execute VL calls") from exc
    client = OpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=timeout_sec)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for asset in assets:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(asset.path)}})
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            request: dict[str, Any] = {
                "model": provider.model,
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"},
                "temperature": 0,
                "max_tokens": 4096,
            }
            extra_body = provider_extra_body(provider)
            if extra_body:
                request["extra_body"] = extra_body
            response = client.chat.completions.create(**request)
            message = response.choices[0].message.content or ""
            parsed = parse_json_object(message)
            usage = usage_to_dict(getattr(response, "usage", None))
            response_model = str(getattr(response, "model", "") or "").strip()
            if response_model:
                usage.setdefault("model", response_model)
            if usage:
                parsed["__vl_usage"] = usage
            return parsed
        except Exception as exc:  # pragma: no cover - exercised only against live APIs
            last_error = exc
            if attempt >= retries:
                break
    raise RuntimeError(f"{provider.name} VL call failed: {last_error}")


def mock_response_for(mock_payload: Any, queue_id: str) -> dict[str, Any]:
    if isinstance(mock_payload, dict):
        if queue_id in mock_payload and isinstance(mock_payload[queue_id], dict):
            return copy.deepcopy(mock_payload[queue_id])
        base_id = base_queue_id(queue_id)
        if base_id in mock_payload and isinstance(mock_payload[base_id], dict):
            return copy.deepcopy(mock_payload[base_id])
        if "default" in mock_payload and isinstance(mock_payload["default"], dict):
            return copy.deepcopy(mock_payload["default"])
        return copy.deepcopy(mock_payload)
    raise ValueError("--mock-response must contain a JSON object")


def as_string_list(value: Any) -> list[str]:
    output: list[str] = []
    for item in normalize_list(value):
        if isinstance(item, dict):
            text = str(
                item.get("name")
                or item.get("displayName")
                or item.get("display_name")
                or item.get("canonicalName")
                or item.get("canonical_name")
                or item.get("artistName")
                or item.get("artist_name")
                or item.get("djName")
                or item.get("dj_name")
                or item.get("raw")
                or ""
            ).strip()
        else:
            text = str(item).strip()
        if text:
            parts = re.split(r"\s*(?:\n|\r|/|／|、|，|,|｜|\||;|；|\+|＆|&|×|\bb2b\b|\bB2B\b)\s*", text)
            output.extend(part.strip() for part in parts if part and part.strip())
    return output


GENERIC_LINEUP_RE = re.compile(
    r"^(?:dj|djs|live|line\s*up|lineup|support|guest|resident|host|acts?|artists?|"
    r"阵容|嘉宾|艺人|演出阵容|演出者|演出|嘉宾阵容|票价|门票|预售|现场|免费|扫码|二维码|"
    r"购票|报名|活动|时间|日期|地点|地址|酒水|套餐|tba|none|null|n/?a)$",
    re.I,
)


def lineup_dedupe_key(value: str) -> str:
    text = re.sub(r"^\s*(?:dj|mc|vj)\s+", "", value.strip(), flags=re.I)
    text = re.sub(r"[\s\-_·.。・•'\"“”‘’()（）\[\]【】]+", "", text)
    return text.casefold()


def clean_lineup_values(value: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in as_string_list(value):
        text = re.sub(r"^\s*(?:line\s*up|lineup|djs?|阵容|嘉宾阵容)\s*[:：-]\s*", "", raw, flags=re.I)
        text = text.strip(" \t\r\n:-：,，;；/／|｜")
        if not text or GENERIC_LINEUP_RE.match(text):
            continue
        key = lineup_dedupe_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def set_if_text(row: dict[str, Any], key: str, value: Any) -> None:
    text = str(value or "").strip()
    if text:
        row[key] = text


def set_list_if_any(row: dict[str, Any], key: str, value: Any) -> None:
    items = as_string_list(value)
    if items:
        row[key] = items


def write_source_evidence(
    out_dir: Path,
    candidate: dict[str, Any],
    source_row: dict[str, Any],
    assets: list[ImageAsset],
    parsed: dict[str, Any],
) -> str:
    evidence_dir = out_dir / SOURCE_EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    queue_id = str(candidate.get("queue_id") or candidate.get("id") or "candidate")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", queue_id)[:140] or "candidate"
    path = evidence_dir / f"{safe_name}.qwen_vl.md"
    lines = [
        "# Weekly Sanji VL Evidence",
        "",
        f"- queue_id: `{queue_id}`",
        f"- source_queue_id: `{source_row.get('queue_id', '')}`",
        f"- article_dir: `{source_row.get('article_dir', '')}`",
        f"- source_url: {source_row.get('source_url', '')}",
        "",
        "## Images",
    ]
    for idx, asset in enumerate(assets):
        lines.append(
            f"- {idx}: `{asset.path.name}` size={asset.size} sha={asset.sha} source={asset.source_url}"
        )
    lines.extend(["", "## Parsed JSON", "```json"])
    lines.append(json.dumps(parsed, ensure_ascii=False, indent=2))
    lines.extend(["```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def selected_asset(assets: list[ImageAsset], parsed: dict[str, Any]) -> ImageAsset | None:
    value = parsed.get("main_poster_image_index")
    if value is None or value == "":
        return None
    try:
        idx = int(value)
    except (TypeError, ValueError):
        return None
    if idx < 0 or idx >= len(assets):
        return None
    return assets[idx]


def merge_vl_result(
    candidate: dict[str, Any],
    source_row: dict[str, Any],
    assets: list[ImageAsset],
    parsed: dict[str, Any],
    provider: ProviderConfig,
    fallback_used: bool,
    out_dir: Path,
) -> dict[str, Any]:
    row = copy.deepcopy(candidate)
    row["poster_vl_status"] = "enriched" if parsed.get("is_event", True) else "not_event"
    row["poster_vl_provider"] = provider.name
    row["poster_vl_model"] = provider.model
    row["poster_vl_fallback_used"] = fallback_used
    row["poster_vl_images"] = [
        {
            "index": idx,
            "path": str(asset.path),
            "file": asset.path.name,
            "source_url": asset.source_url,
            "sha": asset.sha,
            "size": asset.size,
        }
        for idx, asset in enumerate(assets)
    ]

    date_start = parse_yyyy_mm_dd(str(parsed.get("date_start") or ""))
    if date_start:
        row["event_date_text"] = [date_start.isoformat()]
        row["date_text"] = [date_start.isoformat()]
    set_if_text(row, "event_title", parsed.get("event_title"))
    set_if_text(row, "event_time_text", parsed.get("time_text"))
    set_if_text(row, "address", parsed.get("address"))
    set_list_if_any(row, "city", parsed.get("city"))
    set_list_if_any(row, "venue", parsed.get("venue"))
    lineup_values = clean_lineup_values(parsed.get("lineup"))
    if lineup_values:
        row["lineup"] = lineup_values
        row["lineup_artists"] = lineup_values
        row["poster_vl_lineup"] = lineup_values
    lineup_evidence = as_string_list(parsed.get("lineup_evidence"))
    if lineup_evidence:
        row["poster_vl_lineup_evidence"] = lineup_evidence
    set_list_if_any(row, "music_styles", parsed.get("music_styles"))
    set_list_if_any(row, "price", parsed.get("price"))
    set_if_text(row, "ticketing_text", parsed.get("ticketing_text"))

    asset = selected_asset(assets, parsed)
    if asset and asset.source_url:
        row["cover_url"] = asset.source_url
        row["poster_url"] = asset.source_url
        row["poster_source"] = "sanji_article_body_vl"

    evidence_path = write_source_evidence(out_dir, candidate, source_row, assets, parsed)
    row["source_evidence_path"] = evidence_path
    row["poster_selection_evidence"] = {
        "schema_version": "weekly_poster_selection_evidence.vl_direct.v1",
        "selected_by": "qwen_vl_direct_sanji_article_assets",
        "provider": provider.name,
        "model": provider.model,
        "fallback_used": fallback_used,
        "main_poster_image_index": parsed.get("main_poster_image_index"),
        "selected_source_url": asset.source_url if asset else "",
        "selected_sha": asset.sha if asset else "",
        "visible_text_lines": as_string_list(parsed.get("visible_text_lines")),
        "lineup_evidence": lineup_evidence,
        "cleaned_lineup": lineup_values,
        "evidence": as_string_list(parsed.get("evidence")),
        "risk_flags": as_string_list(parsed.get("risk_flags")),
        "confidence": parsed.get("confidence"),
        "source_evidence_path": evidence_path,
        "generated_at": now_iso(),
    }
    return row


def process_rows(
    rows: list[dict[str, Any]],
    lookup: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    provider: ProviderConfig,
    fallback: ProviderConfig,
    mock_payload: Any,
    out_dir: Path,
    stats: dict[str, Any],
    published_hashes: set[str],
    published_quality: dict[str, dict[str, bool]],
    routing_rows: list[dict[str, Any]],
    evidence_cache: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    window_start = dt.date.fromisoformat(args.window_start)
    output: list[dict[str, Any] | None] = [None] * len(rows)
    tasks: list[tuple[int, dict[str, Any], dict[str, Any], list[ImageAsset]]] = []
    for index, row in enumerate(rows):
        stats["rows_seen"] += 1
        if args.limit and stats["processed"] >= args.limit:
            stats["skipped_limit"] += 1
            output[index] = row
            routing_rows.append(
                {
                    "queue_id": str(row.get("queue_id") or row.get("id") or ""),
                    "bucket": "review_or_retry",
                    "reason": "skipped_limit",
                    "required_model": "deferred",
                    "source_hashes": sorted(source_hashes_from_row(row)),
                }
            )
            continue
        if not should_process(row, window_start, args.window_days):
            stats["skipped_not_in_window_or_not_feed"] += 1
            output[index] = row
            routing_rows.append(
                {
                    "queue_id": str(row.get("queue_id") or row.get("id") or ""),
                    "bucket": "easy_rule",
                    "reason": "outside_window_or_not_activity_feed",
                    "required_model": "none",
                    "source_hashes": sorted(source_hashes_from_row(row)),
                }
            )
            continue
        source_row = resolve_source_row(row, lookup)
        if not source_row:
            stats["missing_source_row"] += 1
            if args.execute:
                stats["failures"] += 1
            output[index] = row
            routing_rows.append(
                {
                    "queue_id": str(row.get("queue_id") or row.get("id") or ""),
                    "bucket": "review_or_retry",
                    "reason": "missing_source_row",
                    "required_model": "deferred",
                    "source_hashes": sorted(source_hashes_from_row(row)),
                }
            )
            continue
        row_hashes = source_hashes_from_row(row, source_row)
        matched_published = sorted(row_hashes & published_hashes)
        if matched_published:
            matched_quality = {source_hash: published_quality.get(source_hash, {}) for source_hash in matched_published}
            published_has_complete_quality = any(
                bool(quality.get("has_lineup")) and bool(quality.get("has_poster_evidence"))
                for quality in matched_quality.values()
            )
            row_has_complete_quality = published_item_has_lineup(row) and has_poster_selection_evidence(row)
            if published_has_complete_quality and row_has_complete_quality:
                stats["skipped_already_published"] += 1
                skipped = copy.deepcopy(row)
                skipped["poster_vl_status"] = "skipped_already_published"
                skipped["poster_vl_note"] = (
                    "Sanji source hash is already present in the published/base current_release, and the current "
                    "candidate already carries lineup plus poster selection evidence; daily incremental VL skipped."
                )
                output[index] = skipped
                routing_rows.append(
                    {
                        "queue_id": str(row.get("queue_id") or row.get("id") or ""),
                        "bucket": "easy_rule",
                        "reason": "already_published_source_hash_quality_complete",
                        "required_model": "none",
                        "source_hashes": sorted(row_hashes),
                        "matched_published_hashes": matched_published,
                        "matched_published_quality": matched_quality,
                    }
                )
                continue
            stats["published_quality_gap"] += 1
        assets = select_article_assets(str(source_row.get("article_dir") or ""), args.max_images)
        if not assets:
            stats["missing_assets"] += 1
            skipped = copy.deepcopy(row)
            skipped["poster_vl_status"] = "skipped_missing_assets"
            skipped["poster_vl_note"] = "Sanji source row exists but article_dir/assets has no usable local image files; keeping text candidate for downstream enrichment."
            output[index] = skipped
            routing_rows.append(
                {
                    "queue_id": str(row.get("queue_id") or row.get("id") or ""),
                    "bucket": "review_or_retry",
                    "reason": "missing_assets",
                    "required_model": "deferred",
                    "source_hashes": sorted(row_hashes),
                }
            )
            continue
        stats["processed"] += 1
        routing_rows.append(
            {
                "queue_id": str(row.get("queue_id") or row.get("id") or ""),
                "bucket": "hard_pro",
                "reason": "published_source_quality_gap" if matched_published else "unpublished_current_future_candidate",
                "required_model": provider.model,
                "source_hashes": sorted(row_hashes),
                "matched_published_hashes": matched_published,
                "image_count_sent": len(assets),
            }
        )
        tasks.append((index, row, source_row, assets))

    def run_one(row: dict[str, Any], source_row: dict[str, Any], assets: list[ImageAsset]) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
        prompt = build_prompt(row, source_row, assets)
        fallback_used = False
        active_provider = provider
        usage_record: dict[str, Any] | None = None
        if mock_payload is not None:
            parsed = mock_response_for(mock_payload, str(row.get("queue_id") or row.get("id") or ""))
        else:
            try:
                parsed = call_openai_compatible_vl(
                    provider,
                    prompt,
                    assets,
                    timeout_sec=args.timeout_sec,
                    retries=args.api_retries,
                )
            except Exception:
                if not fallback.api_key:
                    raise
                fallback_used = True
                active_provider = fallback
                parsed = call_openai_compatible_vl(
                    fallback,
                    prompt,
                    assets,
                    timeout_sec=args.timeout_sec,
                    retries=args.api_retries,
                )
        raw_usage = parsed.pop("__vl_usage", None)
        enriched = merge_vl_result(row, source_row, assets, parsed, active_provider, fallback_used, out_dir)
        if isinstance(raw_usage, dict):
            usage_record = build_usage_record(
                active_provider,
                raw_usage,
                fallback_used=fallback_used,
                image_count=len(assets),
                queue_id=str(row.get("queue_id") or row.get("id") or ""),
            )
        return enriched, active_provider.name, usage_record

    completed = 0
    progress_every = max(0, int(getattr(args, "progress_every", 0) or 0))
    if args.concurrency <= 1 or len(tasks) <= 1:
        iterator = tasks
        for index, row, source_row, assets in iterator:
            # Resume: if evidence_cache has this queue_id, reuse cached parsed JSON
            qid_for_check = str(row.get("queue_id") or row.get("id") or "")
            if evidence_cache and qid_for_check in evidence_cache:
                parsed = evidence_cache[qid_for_check]
                enriched = merge_vl_result(row, source_row, assets, parsed, provider, False, out_dir)
                output[index] = enriched
                stats["enriched"] += 1
                stats["resumed_from_evidence"] += 1
                stats["providers"][provider.name] = stats["providers"].get(provider.name, 0) + 1
                completed += 1
                if progress_every and completed % progress_every == 0:
                    print(f"vl_progress completed={completed}/{len(tasks)} enriched={stats['enriched']} failures={stats['failures']} resumed={stats['resumed_from_evidence']}", flush=True)
                continue
            try:
                enriched, provider_name, usage_record = run_one(row, source_row, assets)
                output[index] = enriched
                stats["enriched"] += 1
                stats["providers"][provider_name] = stats["providers"].get(provider_name, 0) + 1
                if usage_record:
                    stats.setdefault("_usage_records", []).append(usage_record)
            except Exception as exc:
                stats["failures"] += 1
                failure_row = copy.deepcopy(row)
                failure_row["poster_vl_status"] = "failed"
                failure_row["poster_vl_error"] = f"{type(exc).__name__}: {exc}"
                output[index] = failure_row
            completed += 1
            if progress_every and completed % progress_every == 0:
                print(
                    f"vl_progress completed={completed}/{len(tasks)} enriched={stats['enriched']} failures={stats['failures']}",
                    flush=True,
                )
    else:
        max_workers = max(1, int(args.concurrency))
        # Resume: handle cached items directly, only submit remaining to pool
        remaining_tasks = []
        for t_idx, t_row, t_source_row, t_assets in tasks:
            qid_check = str(t_row.get("queue_id") or t_row.get("id") or "")
            if evidence_cache and qid_check in evidence_cache:
                parsed = evidence_cache[qid_check]
                enriched = merge_vl_result(t_row, t_source_row, t_assets, parsed, provider, False, out_dir)
                output[t_idx] = enriched
                stats["enriched"] += 1
                stats["resumed_from_evidence"] += 1
                stats["providers"][provider.name] = stats["providers"].get(provider.name, 0) + 1
                completed += 1
            else:
                remaining_tasks.append((t_idx, t_row, t_source_row, t_assets))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_one, row, source_row, assets): (index, row)
                for index, row, source_row, assets in remaining_tasks
            }
            for future in as_completed(futures):
                index, row = futures[future]
                try:
                    enriched, provider_name, usage_record = future.result()
                    output[index] = enriched
                    stats["enriched"] += 1
                    stats["providers"][provider_name] = stats["providers"].get(provider_name, 0) + 1
                    if usage_record:
                        stats.setdefault("_usage_records", []).append(usage_record)
                except Exception as exc:
                    stats["failures"] += 1
                    failure_row = copy.deepcopy(row)
                    failure_row["poster_vl_status"] = "failed"
                    failure_row["poster_vl_error"] = f"{type(exc).__name__}: {exc}"
                    output[index] = failure_row
                completed += 1
                if progress_every and completed % progress_every == 0:
                    print(
                        f"vl_progress completed={completed}/{len(tasks)} enriched={stats['enriched']} failures={stats['failures']} resumed={stats['resumed_from_evidence']}",
                        flush=True,
                    )

    return [row if row is not None else {} for row in output]


def load_mock_payload(path: str) -> Any:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def copy_sidecar_files(pack_dir: Path, out_dir: Path) -> None:
    for path in pack_dir.iterdir():
        if path.name in {CANDIDATE_FILE, REVIEW_FILE}:
            continue
        if path.is_file():
            shutil.copy2(path, out_dir / path.name)


def run(args: argparse.Namespace) -> int:
    pack_dir = Path(args.pack_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (pack_dir / CANDIDATE_FILE).exists():
        raise FileNotFoundError(f"candidate file not found: {pack_dir / CANDIDATE_FILE}")
    lookup = load_queue_lookup(Path(args.weekly_queue))
    provider = provider_config(args.provider, args.model)
    fallback = provider_config(args.fallback_provider)
    if args.execute and not args.mock_response and not provider.api_key and not fallback.api_key:
        raise RuntimeError(
            "No VL provider key configured. Set DASHSCOPE_API_KEY/ATLAS_DASHSCOPE_API_KEY "
            "or a MiMo fallback key in the environment."
        )

    mock_payload = load_mock_payload(args.mock_response)
    evidence_cache: dict[str, dict[str, Any]] = {}
    if args.resume_from_evidence_dir:
        evidence_cache = load_evidence_checkpoint(args.resume_from_evidence_dir)
        if evidence_cache:
            print(f"[CHECKPOINT] Loaded {len(evidence_cache)} enriched items from {args.resume_from_evidence_dir}", flush=True)
    published_hashes = load_published_hashes(args.published_api_dir)
    published_quality = load_published_hash_quality(args.published_api_dir)
    routing_rows: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "schema_version": "weekly_activity_vl_enrichment_summary.v1",
        "generated_at": now_iso(),
        "source_pack_dir": str(pack_dir),
        "weekly_queue": str(Path(args.weekly_queue)),
        "out_dir": str(out_dir),
        "window_start": args.window_start,
        "window_days": args.window_days,
        "provider": provider.name,
        "provider_model": provider.model,
        "fallback_provider": fallback.name,
        "fallback_model": fallback.model,
        "max_images": int(args.max_images),
        "published_api_dir": str(Path(args.published_api_dir)) if args.published_api_dir else "",
        "published_hash_count": len(published_hashes),
        "published_quality_hash_count": len(published_quality),
        "concurrency": int(args.concurrency),
        "execute": bool(args.execute),
        "mock_response": bool(args.mock_response),
        "rows_seen": 0,
        "processed": 0,
        "enriched": 0,
        "failures": 0,
        "missing_source_row": 0,
        "missing_assets": 0,
        "skipped_already_published": 0,
        "published_quality_gap": 0,
        "skipped_limit": 0,
        "skipped_not_in_window_or_not_feed": 0,
        "resumed_from_evidence": 0,
        "providers": {},
    }

    candidates = read_jsonl(pack_dir / CANDIDATE_FILE)
    reviews = read_jsonl(pack_dir / REVIEW_FILE)
    enriched_candidates = process_rows(
        candidates, lookup, args, provider, fallback, mock_payload, out_dir, stats, published_hashes, published_quality, routing_rows, evidence_cache
    )
    enriched_reviews = process_rows(
        reviews, lookup, args, provider, fallback, mock_payload, out_dir, stats, published_hashes, published_quality, routing_rows, evidence_cache
    )
    write_jsonl(out_dir / CANDIDATE_FILE, enriched_candidates)
    write_jsonl(out_dir / REVIEW_FILE, enriched_reviews)
    write_jsonl(out_dir / ROUTING_MANIFEST_FILE, routing_rows)
    copy_sidecar_files(pack_dir, out_dir)
    usage_records = list(stats.pop("_usage_records", []))
    write_jsonl(out_dir / POSTER_VL_USAGE_DETAILS_FILE, usage_records)
    usage_summary = summarize_usage_records(usage_records, args, out_dir)
    write_json(out_dir / POSTER_VL_USAGE_SUMMARY_FILE, usage_summary)
    stats["poster_vl_usage_summary"] = usage_summary
    if usage_summary.get("cost_cny") not in (None, ""):
        stats["poster_vl_cost_cny"] = usage_summary["cost_cny"]
        stats["poster_vl_call_count"] = usage_summary.get("call_count", 0)
        stats["poster_vl_prompt_tokens"] = usage_summary.get("prompt_tokens", 0)
        stats["poster_vl_completion_tokens"] = usage_summary.get("completion_tokens", 0)
        stats["poster_vl_total_tokens"] = usage_summary.get("total_tokens", 0)
    provider_counts = dict(stats.get("providers") or {})
    primary_provider_count = int(provider_counts.get(provider.name, 0) or 0)
    fallback_provider_count = int(provider_counts.get(fallback.name, 0) or 0)
    processed_count = int(stats.get("processed") or 0)
    fallback_ratio = (fallback_provider_count / processed_count) if processed_count else 0.0
    stats["primary_provider_count"] = primary_provider_count
    stats["fallback_provider_count"] = fallback_provider_count
    stats["fallback_count"] = fallback_provider_count
    stats["fallback_ratio"] = round(fallback_ratio, 6)
    stats["max_fallback_ratio"] = float(args.max_fallback_ratio)
    stats["primary_provider_required"] = bool(args.require_primary_provider)
    stats["primary_provider_gate_ok"] = True
    stats["primary_provider_gate_reason"] = ""
    if (
        args.execute
        and args.require_primary_provider
        and not args.mock_response
        and provider.api_key
        and processed_count > 0
        and primary_provider_count <= 0
    ):
        stats["primary_provider_gate_ok"] = False
        stats["primary_provider_gate_reason"] = (
            f"requested primary provider {provider.name}/{provider.model} had zero successful outputs; "
            f"fallback provider {fallback.name}/{fallback.model} handled {fallback_provider_count} rows"
        )
    elif (
        args.execute
        and args.require_primary_provider
        and not args.mock_response
        and provider.api_key
        and processed_count > 0
        and fallback_provider_count > 0
        and fallback_ratio > float(args.max_fallback_ratio)
    ):
        stats["primary_provider_gate_ok"] = False
        stats["primary_provider_gate_reason"] = (
            f"fallback provider {fallback.name}/{fallback.model} handled {fallback_provider_count}/{processed_count} rows "
            f"({fallback_ratio:.1%}), above max_fallback_ratio={float(args.max_fallback_ratio):.1%}"
        )
    write_json(out_dir / "summary.json", stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if not stats["primary_provider_gate_ok"]:
        return 3
    if args.execute and stats["failures"] > int(args.max_failures):
        return 2
    return 0


def load_evidence_checkpoint(evidence_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Parse source_evidence/*.qwen_vl.md files to extract Qwen VL parsed JSON keyed by queue_id.

    Enables resume: skip already-enriched items without re-calling the API.
    """
    ev_dir = Path(evidence_dir)
    if not ev_dir.is_dir():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    qid_re = re.compile(r"queue_id: `([^`]+)`")
    json_re = re.compile(r"```json\n(.*?)\n```", re.DOTALL)
    for path in sorted(ev_dir.glob("*.qwen_vl.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        qm = qid_re.search(text)
        jm = json_re.search(text)
        if qm and jm:
            try:
                cache[qm.group(1)] = json.loads(jm.group(1))
            except json.JSONDecodeError:
                continue
    return cache


def _selfcheck() -> int:
    assert base_queue_id("loopy:b8:schedule:0") == "loopy:b8"
    assert parse_yyyy_mm_dd("2026.06.19").isoformat() == "2026-06-19"  # type: ignore[union-attr]
    window_start = dt.date(2026, 6, 20)
    assert should_process(
        {
            "queue_id": "gas_nation:test",
            "title": "本周六免票入场｜TiAo@GAS·【暗夜庇护所】哥特派对",
            "event_date_text": ["2026-06-20"],
        },
        window_start,
        15,
    )
    assert not should_process(
        {
            "queue_id": "loopy:test",
            "title": "loopy Club 本周活动一览",
            "event_date_text": ["2026-06-20"],
        },
        window_start,
        15,
    )
    assert should_process(
        {
            "queue_id": "loopy:test:schedule:20260620:1",
            "title": "loopy Club 本周活动一览",
            "event_date_text": ["2026-06-20"],
        },
        window_start,
        15,
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        article_dir = root / "article"
        assets_dir = article_dir / "assets"
        assets_dir.mkdir(parents=True)
        image_path = assets_dir / "0.png"
        image_path.write_bytes(b"x" * 20000)
        (image_path.with_name(image_path.name + ".meta.json")).write_text(
            json.dumps({"sourceUrl": "https://mmbiz.qpic.cn/test.png", "sha": "abc"}),
            encoding="utf-8",
        )
        (article_dir / "index.html").write_text('<img src="assets/0.png">', encoding="utf-8")
        assets = select_article_assets(str(article_dir), 1)
        assert assets and assets[0].source_url.endswith("test.png")
    print(json.dumps({"ok": True, "script": Path(__file__).name}, ensure_ascii=False))
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", required=False)
    parser.add_argument("--weekly-queue", required=False)
    parser.add_argument("--out-dir", required=False)
    parser.add_argument("--window-start", default=dt.date.today().isoformat())
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES)
    parser.add_argument("--model", default="")
    parser.add_argument("--published-api-dir", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--provider", default="qwen3_vl")
    parser.add_argument("--fallback-provider", default="mimo")
    parser.add_argument("--timeout-sec", type=int, default=90)
    parser.add_argument("--api-retries", type=int, default=1)
    parser.add_argument("--max-failures", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--require-primary-provider", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-fallback-ratio", type=float, default=0.2)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--mock-response", default="")
    parser.add_argument("--resume-from-evidence-dir", default="")
    parser.add_argument("--selfcheck", action="store_true")
    args = parser.parse_args(argv)
    if not args.selfcheck:
        missing = [name for name in ("pack_dir", "weekly_queue", "out_dir") if not getattr(args, name)]
        if missing:
            parser.error("missing required arguments: " + ", ".join("--" + item.replace("_", "-") for item in missing))
        dt.date.fromisoformat(args.window_start)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.selfcheck:
        return _selfcheck()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
