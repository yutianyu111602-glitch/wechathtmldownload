#!/usr/bin/env python3
"""Build a small MiMo review queue for risky weekly main-poster choices.

This is report-only. It reads a release-package quality report plus the local
poster cache and emits a fixture list for compare_weekly_poster_vision_models.py.
It never calls MiMo, uploads posters, writes CloudBase/DB, or patches packages.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_main_poster_mimo_review_queue.v1"
DEFAULT_CACHE_DIR = Path("E:/weekly_activity_pipeline/longrun/weekly_poster_cloudbase_cache")

POSTER_ID_FIELDS = (
    "poster_file_id",
    "posterFileId",
    "cloudFileId",
    "cloud_file_id",
    "coverUrl",
    "cover_url",
    "poster",
    "posterUrl",
    "poster_url",
)
OCR_TEXT_FIELDS = (
    "poster_ocr_text",
    "posterOcrText",
    "poster_text",
    "posterText",
    "selected_poster_ocr_text",
    "main_poster_ocr_text",
)
LINEUP_FIELDS = ("lineup", "lineup_artists", "artists", "artist_names", "performers")
GROUND_TRUTH_FIELDS = (
    "title",
    "event_date_start",
    "event_date_text",
    "event_time_text",
    "city",
    "venue_name",
    "address",
    "lineup",
    "is_main_event_poster",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def text_values(value: Any, *, limit: int = 80) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for child in value:
            out.extend(text_values(child, limit=limit))
            if len(out) >= limit:
                break
    elif isinstance(value, dict):
        for key in ("name", "title", "text", "value", "label"):
            child = value.get(key)
            if child:
                out.extend(text_values(child, limit=limit))
            if len(out) >= limit:
                break
    elif value is not None:
        text = str(value).strip()
        if text:
            out.append(text)
    return out[:limit]


def safe_stem(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    text = text.strip("._-")
    return text[:96] or "item"


def item_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": first_non_empty(item.get("id"), item.get("event_id"), item.get("article_id")),
        "title": first_non_empty(item.get("title_display"), item.get("title")),
        "event_date_start": first_non_empty(item.get("event_date_start"), item.get("eventDateStart")),
        "event_date_end": first_non_empty(item.get("event_date_end"), item.get("eventDateEnd")),
        "city": item.get("city"),
        "city_keys": item.get("city_keys"),
        "venue": first_non_empty(item.get("venue_name"), item.get("venue")),
    }


def selected_poster_ocr_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in OCR_TEXT_FIELDS:
        parts.extend(text_values(item.get(field)))
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        normalized = re.sub(r"\s+", " ", part).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(part)
    return "\n".join(unique)


def lineup_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in LINEUP_FIELDS:
        values.extend(text_values(item.get(field), limit=40))
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out[:40]


def ground_truth_context(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": first_non_empty(item.get("title_display"), item.get("title"), item.get("title_original")),
        "event_date_start": first_non_empty(item.get("event_date_start"), item.get("eventDateStart")),
        "event_date_text": first_non_empty(item.get("event_date_text"), item.get("date_text")),
        "event_time_text": first_non_empty(item.get("event_time_text"), item.get("running_hours_text"), item.get("time_start")),
        "city": item.get("city"),
        "venue_name": first_non_empty(item.get("venue_name"), item.get("venue")),
        "address": first_non_empty(item.get("address"), item.get("address_full"), item.get("venue_address")),
        "lineup": lineup_values(item),
        "is_main_event_poster": True,
    }


def context_field_count(context: dict[str, Any]) -> int:
    count = 0
    for field in GROUND_TRUTH_FIELDS:
        value = context.get(field)
        if isinstance(value, bool):
            count += 1
        elif isinstance(value, list) and value:
            count += 1
        elif value not in ("", None):
            count += 1
    return count


def source_hash(item: dict[str, Any]) -> str:
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    return first_non_empty(
        source_article.get("url_hash"),
        source_action.get("url_hash"),
        item.get("sourceHash"),
        item.get("source_hash"),
        item.get("article_hash"),
    )


def poster_hash(item: dict[str, Any]) -> str:
    return first_non_empty(
        item.get("poster_public_source_hash"),
        item.get("posterPublicSourceHash"),
        item.get("poster_source_hash"),
        item.get("posterSourceHash"),
    )


def poster_cloud_basename(item: dict[str, Any]) -> str:
    for field in POSTER_ID_FIELDS:
        value = str(item.get(field) or "").strip()
        if "/weekly-posters/" not in value:
            continue
        # cloud://env/weekly-posters/YYYYMMDD/file.jpg -> file.jpg
        return value.rsplit("/", 1)[-1]
    cloud_path = str(item.get("poster_cloud_path") or "").strip()
    if cloud_path:
        return cloud_path.rsplit("/", 1)[-1]
    return ""


def find_cache_image(item: dict[str, Any], cache_dir: Path) -> tuple[str, list[str]]:
    basename = poster_cloud_basename(item)
    candidates: list[Path] = []
    if basename:
        exact = cache_dir / basename
        if exact.exists():
            return str(exact), [str(exact)]
        candidates.extend(cache_dir.glob(f"*{basename}*"))

    phash = poster_hash(item)
    shash = source_hash(item)
    if phash and shash:
        candidates.extend(cache_dir.glob(f"*{shash}*--{phash}*"))
    if phash:
        candidates.extend(cache_dir.glob(f"*{phash}*"))

    unique = []
    seen = set()
    for path in candidates:
        if not path.is_file():
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)

    if not unique:
        return "", []
    preferred = sorted(unique, key=lambda path: (0 if shash and shash in path.name else 1, path.name))[0]
    return str(preferred), [str(path) for path in unique[:20]]


def load_current_items(api_dir: Path) -> dict[str, dict[str, Any]]:
    payload = read_json(api_dir / "current.json")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError(f"current.json has no item list: {api_dir / 'current.json'}")
    out = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = first_non_empty(item.get("id"), item.get("event_id"))
        if item_id:
            out[item_id] = item
    return out


def report_review_item_ids(quality_report: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    seen = set()
    for row in quality_report.get("main_poster_selection_review_required_items") or []:
        item_id = first_non_empty(row.get("id"))
        if item_id and item_id not in seen:
            seen.add(item_id)
            ids.append(item_id)
    if ids:
        return ids
    for group in quality_report.get("main_poster_selection_review_required_groups") or []:
        for row in group.get("items") or []:
            item_id = first_non_empty(row.get("id"))
            if item_id and item_id not in seen:
                seen.add(item_id)
                ids.append(item_id)
    return ids


def build_queue(args: argparse.Namespace) -> dict[str, Any]:
    api_dir = Path(args.api_dir).resolve()
    quality_report_path = Path(args.quality_report).resolve()
    cache_dir = Path(args.poster_cache_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    quality_report = read_json(quality_report_path)
    current_items = load_current_items(api_dir)
    item_ids = report_review_item_ids(quality_report)
    if args.max_items and args.max_items > 0:
        item_ids = item_ids[: args.max_items]

    rows = []
    fixtures = []
    missing_items = []
    missing_images = []
    ocr_text_count = 0
    context_complete_count = 0
    weak_context_items = []
    ocr_dir = out_dir / "ocr_text"
    ground_truth_dir = out_dir / "ground_truth"
    for item_id in item_ids:
        item = current_items.get(item_id)
        if not item:
            missing_items.append({"id": item_id, "reason": "item_not_found_in_current_json"})
            continue
        image_path, cache_candidates = find_cache_image(item, cache_dir)
        identity = item_identity(item)
        item_stem = safe_stem(item_id)
        ocr_text = selected_poster_ocr_text(item)
        ocr_text_path = ""
        if ocr_text:
            ocr_text_count += 1
            ocr_text_file = ocr_dir / f"{item_stem}.txt"
            ocr_text_file.parent.mkdir(parents=True, exist_ok=True)
            ocr_text_file.write_text(ocr_text + "\n", encoding="utf-8")
            ocr_text_path = str(ocr_text_file)

        ground_truth = ground_truth_context(item)
        context_fields = context_field_count(ground_truth)
        if context_fields >= 5:
            context_complete_count += 1
        else:
            weak_context_items.append({**identity, "context_field_count": context_fields})
        ground_truth_file = ground_truth_dir / f"{item_stem}.json"
        write_json(ground_truth_file, ground_truth)

        row = {
            **identity,
            "source_article_hash": source_hash(item),
            "poster_public_source_hash": poster_hash(item),
            "poster_file_id": first_non_empty(*(item.get(field) for field in POSTER_ID_FIELDS)),
            "poster_cloud_basename": poster_cloud_basename(item),
            "local_image_path": image_path,
            "cache_candidate_paths": cache_candidates,
            "ocr_text_path": ocr_text_path,
            "ocr_text_chars": len(ocr_text),
            "ground_truth_path": str(ground_truth_file),
            "ground_truth_field_count": context_fields,
            "review_reason": "main_poster_selection_review_required",
        }
        rows.append(row)
        if not image_path:
            missing_images.append({**identity, "reason": "poster_cache_image_not_found"})
            continue
        fixtures.append(
            {
                "id": item_id,
                "case_type": "main_poster_reuse_risk",
                "image": image_path,
                "api_dir": str(api_dir),
                "item_id": item_id,
                "ground_truth": str(ground_truth_file),
                "ocr_text": ocr_text_path,
            }
        )

    fixture_list_path = out_dir / "mimo_main_poster_review_fixtures.json"
    queue_path = out_dir / "main_poster_mimo_review_queue.json"
    compare_report_path = out_dir / "mimo_batch" / "poster_vision_batch_report.json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not missing_items and not missing_images and bool(fixtures),
        "api_dir": str(api_dir),
        "quality_report": str(quality_report_path),
        "poster_cache_dir": str(cache_dir),
        "review_item_count": len(item_ids),
        "queue_item_count": len(rows),
        "fixture_count": len(fixtures),
        "missing_item_count": len(missing_items),
        "missing_items": missing_items,
        "missing_image_count": len(missing_images),
        "missing_images": missing_images,
        "items": rows,
        "fixture_list_path": str(fixture_list_path),
        "compare_report_expected_path": str(compare_report_path),
        "audit": {
            "route_learning_source": "atlas_stage1_selection_audit_and_router_no_glm_canaries_20260616",
            "review_item_count": len(item_ids),
            "ground_truth_fixture_count": len(rows),
            "context_complete_count": context_complete_count,
            "weak_context_count": len(weak_context_items),
            "weak_context_items": weak_context_items[:50],
            "ocr_text_fixture_count": ocr_text_count,
            "ocr_text_missing_count": max(0, len(rows) - ocr_text_count),
            "poster_count_policy": "selected_poster_only_for_review; upstream selector should keep at most two body-image candidates before final selection",
            "indirect_quality_signal": "A selected poster is stronger when OCR/vision can recover title/date/venue/lineup from it; high package extraction success is a proxy but not a release gate.",
        },
        "recommended_local_ocr_command": (
            "python tools/stage7_rewrite/scripts/compare_weekly_poster_vision_models.py "
            f"--fixture-list \"{fixture_list_path}\" --provider local_ocr "
            f"--out-dir \"{out_dir / 'local_ocr_batch'}\""
        ),
        "recommended_command": (
            "python tools/stage7_rewrite/scripts/compare_weekly_poster_vision_models.py "
            f"--fixture-list \"{fixture_list_path}\" --provider qwen3_vl --provider qwen_ocr --provider deepseek_vision --provider mimo --execute "
            f"--disable-json-mode --out-dir \"{out_dir / 'mimo_batch'}\""
        ),
        "strong_model_policy": {
            "daily_source_mode": "sanji_desktop_client",
            "trigger": "main_poster_selection_review_required_count > 0",
            "provider_order": ["qwen3_vl", "qwen_ocr", "deepseek_vision", "mimo", "stepfun", "local_ocr"],
            "release_rule": "Do not deploy backend or upload frontend until the strong-model decision summary has no rejected/manual/provider-error poster rows and validate_weekly_release_package_quality.py reports main_poster_selection_review_required_count=0.",
        },
        "safety": {
            "report_only": True,
            "mimo_api_executed": False,
            "strong_model_api_executed": False,
            "db_write_executed": False,
            "cloudbase_write_executed": False,
            "package_patch_executed": False,
            "deploy_or_upload_executed": False,
        },
    }
    write_json(queue_path, report)
    write_json(fixture_list_path, {"fixtures": fixtures})
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", required=True, help="Weekly API package directory containing current.json.")
    parser.add_argument("--quality-report", required=True, help="release_package_quality_gate*.json with main-poster review items.")
    parser.add_argument("--poster-cache-dir", default=str(DEFAULT_CACHE_DIR), help="Local cache containing uploaded poster image copies.")
    parser.add_argument("--out-dir", required=True, help="Directory for queue and fixture-list artifacts.")
    parser.add_argument("--max-items", type=int, default=0, help="Optional cap for bounded debugging; 0 means all review items.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = build_queue(parse_args(argv))
    print(json.dumps(
        {
            "ok": report["ok"],
            "queue": str(Path(report["fixture_list_path"]).parent / "main_poster_mimo_review_queue.json"),
            "fixtures": report["fixture_list_path"],
            "fixture_count": report["fixture_count"],
            "missing_image_count": report["missing_image_count"],
        },
        ensure_ascii=False,
    ))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
