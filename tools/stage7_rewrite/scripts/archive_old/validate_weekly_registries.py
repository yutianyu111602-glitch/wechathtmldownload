#!/usr/bin/env python3
"""Validate HUAIDJ weekly mini-program registry files.

Registries are human-maintained product truth tables. This validator checks
shape, duplicates, and publish-impacting gaps without fetching WeChat pages,
running LLMs, or touching production stores.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable


VALID_CITY_KEYS = {
    "",
    "beijing",
    "shanghai",
    "guangzhou",
    "shenzhen",
    "chengdu",
    "hangzhou",
    "nanjing",
    "wuhan",
    "xian",
    "changsha",
    "chongqing",
    "tianjin",
    "qingdao",
    "xiamen",
    "suzhou",
    "jinan",
    "kunming",
    "guiyang",
    "dali",
    "dalian",
    "shenyang",
    "lanzhou",
    "yinchuan",
    "taiyuan",
    "zhengzhou",
    "luoyang",
    "shijiazhuang",
    "weifang",
    "huaian",
    "quanzhou",
    "fuzhou",
    "haikou",
    "nanning",
    "zhuhai",
    "lhasa",
    "urumqi",
    "daqing",
    "harbin",
    "changchun",
    "hongkong",
    "taipei",
    "sanya",
    "hohhot",
}
VENUE_STATUSES = {"active", "closed", "pending_geocode", "review"}
ACCOUNT_STATUSES = {"active", "closed", "inactive", "review"}
ACCOUNT_TYPES = {"club", "promoter", "media", "venue", "label", "artist_collective", "unknown"}
ARTIST_STATUSES = {"active", "inactive", "review"}
ISO_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class RegistryIssue:
    severity: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "path": self.path, "message": self.message}


class RegistryValidationError(ValueError):
    def __init__(self, issues: list[RegistryIssue]):
        self.issues = issues
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in issues if issue.severity == "error"))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def first_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_key(value: Any) -> str:
    return re.sub(r"[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]+", "", first_string(value).lower())


def validate_iso_date(value: Any, path: str, issues: list[RegistryIssue], *, required: bool) -> None:
    raw = first_string(value)
    if not raw:
        if required:
            issues.append(RegistryIssue("error", path, "must be a non-empty ISO date"))
        return
    if not ISO_DATE_RE.match(raw):
        issues.append(RegistryIssue("error", path, "must be ISO date YYYY-MM-DD"))
        return
    try:
        date.fromisoformat(raw)
    except ValueError:
        issues.append(RegistryIssue("error", path, "must be a real calendar date"))


def require_string(obj: dict[str, Any], field: str, path: str, issues: list[RegistryIssue]) -> str:
    value = first_string(obj.get(field))
    if not value:
        issues.append(RegistryIssue("error", f"{path}.{field}", "must be a non-empty string"))
    return value


def optional_string(obj: dict[str, Any], field: str) -> str:
    return first_string(obj.get(field))


def require_string_array(obj: dict[str, Any], field: str, path: str, issues: list[RegistryIssue]) -> list[str]:
    value = obj.get(field)
    if value is None:
        issues.append(RegistryIssue("error", f"{path}.{field}", "must be an array"))
        return []
    if not isinstance(value, list):
        issues.append(RegistryIssue("error", f"{path}.{field}", "must be an array"))
        return []
    out: list[str] = []
    for index, item in enumerate(value):
        raw = first_string(item)
        if not raw:
            issues.append(RegistryIssue("error", f"{path}.{field}[{index}]", "must be a non-empty string"))
        else:
            out.append(raw)
    return out


def validate_city_key(value: str, path: str, issues: list[RegistryIssue]) -> None:
    if value not in VALID_CITY_KEYS:
        issues.append(RegistryIssue("error", path, f"unsupported city_key {value!r}"))


def validate_root(data: dict[str, Any], schema_version: str, collection: str, path: str, issues: list[RegistryIssue]) -> list[Any]:
    if data.get("schema_version") != schema_version:
        issues.append(RegistryIssue("error", f"{path}.schema_version", f"must be {schema_version}"))
    validate_iso_date(data.get("updated_at"), f"{path}.updated_at", issues, required=True)
    rows = data.get(collection)
    if not isinstance(rows, list):
        issues.append(RegistryIssue("error", f"{path}.{collection}", "must be an array"))
        return []
    return rows


def check_duplicate(normalized: str, path: str, seen: dict[str, str], issues: list[RegistryIssue], label: str) -> None:
    if not normalized:
        return
    previous = seen.get(normalized)
    if previous:
        issues.append(RegistryIssue("error", path, f"duplicate {label}; first seen at {previous}"))
    else:
        seen[normalized] = path


def validate_venue_registry(data: dict[str, Any], *, path: str) -> list[RegistryIssue]:
    issues: list[RegistryIssue] = []
    rows = validate_root(data, "weekly_venue_registry.v1", "venues", path, issues)
    seen_ids: dict[str, str] = {}
    seen_identities: dict[str, str] = {}
    for index, row in enumerate(rows):
        row_path = f"{path}.venues[{index}]"
        if not isinstance(row, dict):
            issues.append(RegistryIssue("error", row_path, "must be an object"))
            continue
        venue_id = require_string(row, "venue_id", row_path, issues)
        canonical_name = require_string(row, "canonical_name", row_path, issues)
        aliases = require_string_array(row, "aliases", row_path, issues)
        city_key = require_string(row, "city_key", row_path, issues)
        require_string(row, "city_name", row_path, issues)
        address_full = optional_string(row, "address_full")
        status = require_string(row, "status", row_path, issues)
        validate_iso_date(row.get("last_verified_at"), f"{row_path}.last_verified_at", issues, required=True)
        validate_city_key(city_key, f"{row_path}.city_key", issues)
        if status and status not in VENUE_STATUSES:
            issues.append(RegistryIssue("error", f"{row_path}.status", f"must be one of {sorted(VENUE_STATUSES)}"))
        check_duplicate(normalize_key(venue_id), f"{row_path}.venue_id", seen_ids, issues, "venue_id")
        identity_parts = [normalize_key(city_key), normalize_key(canonical_name), normalize_key(address_full)]
        if all(identity_parts):
            check_duplicate(
                "|".join(identity_parts),
                f"{row_path}.identity",
                seen_identities,
                issues,
                "venue city/name/address identity",
            )
        if status == "active" and not address_full:
            issues.append(RegistryIssue("warning", f"{row_path}.address_full", "active venue has no full address; events at this venue stay in review"))
        if status == "active" and (row.get("geo_lng") in (None, "") or row.get("geo_lat") in (None, "")):
            issues.append(RegistryIssue("warning", f"{row_path}.geo", "active venue has no geo coordinates"))
    return issues


def validate_account_registry(data: dict[str, Any], *, path: str) -> list[RegistryIssue]:
    issues: list[RegistryIssue] = []
    rows = validate_root(data, "weekly_account_registry.v1", "accounts", path, issues)
    seen_ids: dict[str, str] = {}
    seen_fakeids: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    for index, row in enumerate(rows):
        row_path = f"{path}.accounts[{index}]"
        if not isinstance(row, dict):
            issues.append(RegistryIssue("error", row_path, "must be an object"))
            continue
        account_id = require_string(row, "account_id", row_path, issues)
        account_name = require_string(row, "account_name", row_path, issues)
        aliases = require_string_array(row, "aliases", row_path, issues)
        fakeid = optional_string(row, "fakeid")
        city_key = optional_string(row, "city_key")
        account_type = require_string(row, "type", row_path, issues)
        status = require_string(row, "status", row_path, issues)
        priority = row.get("sync_priority")
        validate_iso_date(row.get("last_seen_at"), f"{row_path}.last_seen_at", issues, required=False)
        validate_city_key(city_key, f"{row_path}.city_key", issues)
        if account_type and account_type not in ACCOUNT_TYPES:
            issues.append(RegistryIssue("error", f"{row_path}.type", f"must be one of {sorted(ACCOUNT_TYPES)}"))
        if status and status not in ACCOUNT_STATUSES:
            issues.append(RegistryIssue("error", f"{row_path}.status", f"must be one of {sorted(ACCOUNT_STATUSES)}"))
        if not isinstance(priority, int) or priority < 0:
            issues.append(RegistryIssue("error", f"{row_path}.sync_priority", "must be a non-negative integer"))
        check_duplicate(normalize_key(account_id), f"{row_path}.account_id", seen_ids, issues, "account_id")
        if fakeid:
            check_duplicate(fakeid, f"{row_path}.fakeid", seen_fakeids, issues, "fakeid")
        row_names: set[str] = set()
        for name in [account_name, *aliases]:
            normalized_name = normalize_key(name)
            if normalized_name in row_names:
                continue
            row_names.add(normalized_name)
            check_duplicate(normalized_name, f"{row_path}.aliases", seen_names, issues, "account name or alias")
        city_scope = optional_string(row, "city_scope")
        cityless_allowed = city_scope in {"national", "multi_city", "online"}
        if status == "active" and not city_key and not cityless_allowed:
            issues.append(RegistryIssue("warning", f"{row_path}.city_key", "active account has no default city"))
    return issues


def validate_artist_registry(data: dict[str, Any], *, path: str) -> list[RegistryIssue]:
    issues: list[RegistryIssue] = []
    rows = validate_root(data, "weekly_artist_registry.v1", "artists", path, issues)
    seen_ids: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    blocked_terms = data.get("blocked_lineup_terms", [])
    if not isinstance(blocked_terms, list):
        issues.append(RegistryIssue("error", f"{path}.blocked_lineup_terms", "must be an array"))
        blocked_terms = []
    for term_index, term in enumerate(blocked_terms):
        if not first_string(term):
            issues.append(RegistryIssue("error", f"{path}.blocked_lineup_terms[{term_index}]", "must be a non-empty string"))
    for index, row in enumerate(rows):
        row_path = f"{path}.artists[{index}]"
        if not isinstance(row, dict):
            issues.append(RegistryIssue("error", row_path, "must be an object"))
            continue
        artist_id = require_string(row, "artist_id", row_path, issues)
        canonical_name = require_string(row, "canonical_name", row_path, issues)
        aliases = require_string_array(row, "aliases", row_path, issues)
        require_string_array(row, "style_tags", row_path, issues)
        status = require_string(row, "status", row_path, issues)
        validate_iso_date(row.get("last_verified_at"), f"{row_path}.last_verified_at", issues, required=False)
        if status and status not in ARTIST_STATUSES:
            issues.append(RegistryIssue("error", f"{row_path}.status", f"must be one of {sorted(ARTIST_STATUSES)}"))
        check_duplicate(normalize_key(artist_id), f"{row_path}.artist_id", seen_ids, issues, "artist_id")
        row_names: set[str] = set()
        for name in [canonical_name, *aliases]:
            normalized_name = normalize_key(name)
            if normalized_name in row_names:
                continue
            row_names.add(normalized_name)
            check_duplicate(normalized_name, f"{row_path}.aliases", seen_names, issues, "artist name or alias")
    return issues


VALIDATORS: dict[str, Callable[[dict[str, Any], str], list[RegistryIssue]]] = {
    "weekly_venue_registry.v1": lambda data, path: validate_venue_registry(data, path=path),
    "weekly_account_registry.v1": lambda data, path: validate_account_registry(data, path=path),
    "weekly_artist_registry.v1": lambda data, path: validate_artist_registry(data, path=path),
}


def validate_registry_file(path: Path) -> list[RegistryIssue]:
    data = read_json(path)
    schema_version = first_string(data.get("schema_version"))
    validator = VALIDATORS.get(schema_version)
    if validator is None:
        return [RegistryIssue("error", str(path), f"unsupported schema_version {schema_version!r}")]
    return validator(data, str(path))


def raise_for_registry_issues(issues: list[RegistryIssue], *, strict_warnings: bool = False) -> None:
    failing = [issue for issue in issues if issue.severity == "error" or strict_warnings]
    if failing:
        raise RegistryValidationError(failing)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate weekly mini-program registry JSON files")
    parser.add_argument("--json", nargs="+", required=True, help="Registry JSON files to validate")
    parser.add_argument("--strict-warnings", action="store_true", help="Fail when warnings are present")
    args = parser.parse_args(argv)

    issues: list[RegistryIssue] = []
    for raw_path in args.json:
        issues.extend(validate_registry_file(Path(raw_path)))
    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    result = {
        "ok": error_count == 0 and (warning_count == 0 or not args.strict_warnings),
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": [issue.to_dict() for issue in issues],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
