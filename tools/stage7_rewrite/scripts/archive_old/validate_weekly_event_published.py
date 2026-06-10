#!/usr/bin/env python3
"""Validate HUAIDJ weekly mini-program published event payloads.

This validator intentionally uses only the Python standard library. The schema
file documents the public shape, while this script enforces the publish gates
that matter for the mini-program contract.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_event_published.v1"
FORBIDDEN_KEYS = {
    "source_url",
    "raw_source_url",
    "sourceUrl",
    "confidence",
    "llm_confidence",
    "recommendation_reason",
}
FORBIDDEN_VISIBLE_VALUES = {"unknown", "UNKNOWN", "待确认"}
FORBIDDEN_URL_RE = re.compile(r"https?://(?:mp\.weixin\.qq\.com|weixin\.qq\.com)", re.I)
ISO_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")

REQUIRED_FIELDS = {
    "schema_version",
    "event_id",
    "title_display",
    "title_original",
    "event_date_start",
    "event_date_end",
    "event_date_text",
    "event_date_iso_guesses",
    "time_start",
    "time_end",
    "running_hours_text",
    "city_key",
    "city_name",
    "venue_id",
    "venue_name",
    "address_full",
    "cover_image_url",
    "poster_file_id",
    "poster_source",
    "lineup_artists",
    "music_styles",
    "price_text",
    "ticketing_text",
    "description_original_lines",
    "dj_bio_lines",
    "artist_profiles",
    "source_account_name",
    "source_published_at",
    "source_article",
    "source_action",
    "quality_status",
    "publish_status",
    "dedupe_key",
}

REQUIRED_NON_EMPTY = {
    "event_id",
    "title_display",
    "event_date_start",
    "event_date_end",
    "city_key",
    "city_name",
    "source_account_name",
    "quality_status",
    "publish_status",
    "dedupe_key",
}

ARRAY_FIELDS = {
    "event_date_text",
    "event_date_iso_guesses",
    "lineup_artists",
    "music_styles",
    "description_original_lines",
    "dj_bio_lines",
    "artist_profiles",
}


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


class PublishedSchemaError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in issues))


def _first_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_iso_date(value: Any, path: str, issues: list[ValidationIssue]) -> None:
    if not isinstance(value, str) or not ISO_DATE_RE.match(value):
        issues.append(ValidationIssue(path, "must be ISO date string YYYY-MM-DD"))
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        issues.append(ValidationIssue(path, "must be a real calendar date"))


def _scan_forbidden(value: Any, path: str, issues: list[ValidationIssue]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in FORBIDDEN_KEYS:
                issues.append(ValidationIssue(child_path, f"field {key!r} is not allowed in published payload"))
            _scan_forbidden(child, child_path, issues)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, f"{path}[{index}]", issues)
        return
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in FORBIDDEN_VISIBLE_VALUES:
            issues.append(ValidationIssue(path, f"placeholder value {stripped!r} is not allowed"))
        if FORBIDDEN_URL_RE.search(stripped):
            issues.append(ValidationIssue(path, "raw WeChat source URL is not allowed"))


def validate_published_event(item: dict[str, Any], *, path: str = "item") -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(item, dict):
        return [ValidationIssue(path, "must be an object")]

    missing = sorted(field for field in REQUIRED_FIELDS if field not in item)
    for field in missing:
        issues.append(ValidationIssue(f"{path}.{field}", "missing required field"))

    if item.get("schema_version") != SCHEMA_VERSION:
        issues.append(ValidationIssue(f"{path}.schema_version", f"must be {SCHEMA_VERSION}"))

    for field in sorted(REQUIRED_NON_EMPTY):
        if field in item and not _is_non_empty_string(item.get(field)):
            issues.append(ValidationIssue(f"{path}.{field}", "must be a non-empty string"))

    for field in sorted(ARRAY_FIELDS):
        if field in item and not isinstance(item.get(field), list):
            issues.append(ValidationIssue(f"{path}.{field}", "must be an array"))

    for field in ("event_date_start", "event_date_end"):
        if field in item:
            _validate_iso_date(item.get(field), f"{path}.{field}", issues)

    source_date_text = item.get("event_date_text")
    if "event_date_text" in item and (
        not isinstance(source_date_text, list)
        or not any(_is_non_empty_string(value) for value in source_date_text)
    ):
        issues.append(ValidationIssue(f"{path}.event_date_text", "must include source date evidence"))

    date_guesses = item.get("event_date_iso_guesses")
    if "event_date_iso_guesses" in item:
        if not isinstance(date_guesses, list) or not any(_is_non_empty_string(value) for value in date_guesses):
            issues.append(ValidationIssue(f"{path}.event_date_iso_guesses", "must include parsed source-backed date"))
        elif _first_string(item.get("event_date_start")) and item.get("event_date_start") not in date_guesses:
            issues.append(ValidationIssue(f"{path}.event_date_iso_guesses", "must include event_date_start"))

    if _first_string(item.get("city_key")).lower() == "unknown":
        issues.append(ValidationIssue(f"{path}.city_key", "must not be unknown"))

    if item.get("quality_status") != "READY":
        issues.append(ValidationIssue(f"{path}.quality_status", "must be READY"))
    if item.get("publish_status") != "published":
        issues.append(ValidationIssue(f"{path}.publish_status", "must be published"))

    source_article = item.get("source_article")
    if not isinstance(source_article, dict):
        issues.append(ValidationIssue(f"{path}.source_article", "must be an object"))
    else:
        for field in ("url_hash", "account_name", "published_at"):
            if field not in source_article:
                issues.append(ValidationIssue(f"{path}.source_article.{field}", "missing required field"))
        if "url" in source_article:
            issues.append(ValidationIssue(f"{path}.source_article.url", "raw source URL is not allowed"))

    source_action = item.get("source_action")
    if not isinstance(source_action, dict):
        issues.append(ValidationIssue(f"{path}.source_action", "must be an object"))
    else:
        for field in ("type", "label", "available", "url_hash"):
            if field not in source_action:
                issues.append(ValidationIssue(f"{path}.source_action.{field}", "missing required field"))
        if "url" in source_action:
            issues.append(ValidationIssue(f"{path}.source_action.url", "raw source URL is not allowed"))
        if "source_url" in source_action:
            issues.append(ValidationIssue(f"{path}.source_action.source_url", "raw source URL is not allowed"))
        if "available" in source_action and not isinstance(source_action.get("available"), bool):
            issues.append(ValidationIssue(f"{path}.source_action.available", "must be boolean"))

    _scan_forbidden(item, path, issues)
    return issues


def validate_published_items(items: list[dict[str, Any]], *, path: str = "items") -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(items, list):
        return [ValidationIssue(path, "must be an array")]
    seen_ids: set[str] = set()
    seen_dedupe: set[str] = set()
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        issues.extend(validate_published_event(item, path=item_path))
        event_id = _first_string(item.get("event_id") if isinstance(item, dict) else "")
        if event_id:
            if event_id in seen_ids:
                issues.append(ValidationIssue(f"{item_path}.event_id", "duplicate event_id"))
            seen_ids.add(event_id)
        dedupe_key = _first_string(item.get("dedupe_key") if isinstance(item, dict) else "")
        if dedupe_key:
            if dedupe_key in seen_dedupe:
                issues.append(ValidationIssue(f"{item_path}.dedupe_key", "duplicate dedupe_key"))
            seen_dedupe.add(dedupe_key)
    return issues


def validate_current_payload(payload: dict[str, Any], *, path: str = "current") -> list[ValidationIssue]:
    if not isinstance(payload, dict):
        return [ValidationIssue(path, "must be an object")]
    return validate_published_items(payload.get("items"), path=f"{path}.items")


def validate_payload_file(path: Path) -> list[ValidationIssue]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return validate_published_items(payload, path=path.name)
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return validate_current_payload(payload, path=path.name)
    if isinstance(payload, dict) and isinstance(payload.get("item"), dict):
        return validate_published_event(payload["item"], path=f"{path.name}.item")
    if isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION:
        return validate_published_event(payload, path=path.name)
    return [ValidationIssue(path.name, "unsupported payload shape for weekly_event_published.v1 validation")]


def raise_for_issues(issues: list[ValidationIssue]) -> None:
    if issues:
        raise PublishedSchemaError(issues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate weekly_event_published.v1 payload files")
    parser.add_argument("paths", nargs="+", help="current.json, by-id detail JSON, or raw event JSON files")
    parser.add_argument("--json", action="store_true", help="print machine-readable report")
    args = parser.parse_args(argv)

    all_issues: list[dict[str, str]] = []
    for raw_path in args.paths:
        path = Path(raw_path)
        try:
            issues = validate_payload_file(path)
        except Exception as exc:  # noqa: BLE001 - CLI should report all malformed inputs uniformly.
            issues = [ValidationIssue(path.name, f"read_or_parse_failed: {exc}")]
        all_issues.extend(issue.to_dict() for issue in issues)

    report = {"ok": not all_issues, "issue_count": len(all_issues), "issues": all_issues}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif all_issues:
        for issue in all_issues:
            print(f"{issue['path']}: {issue['message']}")
    else:
        print("weekly_event_published.v1 validation OK")
    return 0 if not all_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
