#!/usr/bin/env python3
"""Report-only compatibility check for weekly schemas and the Stage7 release pack.

This gate does not adapt or publish data. It checks what is true today:

* current weekly registry seed files against their JSON schemas.
* sampled Stage7 consumer release-pack events against weekly_event_published.v1.
* sampled release-pack names against account/artist/venue registry aliases.

Safety: reports only, no production writes, no DB writes, no paid API, no D: scan.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_RELEASE_PACK = Path("reports/consumer_release_pack_full_unknown_time_20260514")
DEFAULT_SCHEMAS = Path("schemas")
DEFAULT_REGISTRIES = Path("registries")
DEFAULT_OUT_DIR = Path("reports/e2e_integration_20260515")
DEFAULT_WEEKLY_PATH_REPORT = Path("reports/weekly_publish_path_decision_20260515/weekly_publish_path_decision.json")
PACK_SCHEMA = "stage7_consumer_release_pack.v1"

REGISTRY_BY_SCHEMA = {
    "weekly_account_registry.v1.schema.json": "weekly_accounts_seed.json",
    "weekly_artist_registry.v1.schema.json": "weekly_artists_seed.json",
    "weekly_venue_registry.v1.schema.json": "weekly_venues_seed.json",
}
EXPECTED_SCHEMA_NAMES = (
    "weekly_account_registry.v1.schema.json",
    "weekly_artist_registry.v1.schema.json",
    "weekly_event_published.v1.schema.json",
    "weekly_venue_registry.v1.schema.json",
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for weekly schema compat gate: {path}")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return read_json(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def sample_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                rows.append(row)
            if limit > 0 and len(rows) >= limit:
                break
    return rows


def iter_jsonl(path: Path, limit: int):
    with path.open("r", encoding="utf-8") as handle:
        count = 0
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                yield row
                count += 1
            if limit > 0 and count >= limit:
                break


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def type_matches(value: Any, expected: str) -> bool:
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def validate_value(value: Any, schema: dict[str, Any], path: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if not any(type_matches(value, item) for item in expected_type):
            issues.append({"path": path, "message": f"type {json_type_name(value)} not in {expected_type}"})
            return issues
    elif isinstance(expected_type, str) and not type_matches(value, expected_type):
        issues.append({"path": path, "message": f"type {json_type_name(value)} is not {expected_type}"})
        return issues

    if "const" in schema and value != schema["const"]:
        issues.append({"path": path, "message": f"must equal {schema['const']!r}"})
    if "enum" in schema and value not in schema["enum"]:
        issues.append({"path": path, "message": f"must be one of {schema['enum']!r}"})
    if isinstance(value, str) and "pattern" in schema:
        if not re.match(str(schema["pattern"]), value):
            issues.append({"path": path, "message": f"does not match pattern {schema['pattern']!r}"})
    if isinstance(value, str) and "minLength" in schema and len(value) < int(schema["minLength"]):
        issues.append({"path": path, "message": f"length below minLength {schema['minLength']}"})
    if isinstance(value, int) and "minimum" in schema and value < int(schema["minimum"]):
        issues.append({"path": path, "message": f"below minimum {schema['minimum']}"})

    if isinstance(value, dict):
        for forbidden in ((schema.get("not") or {}).get("anyOf") or []):
            required = forbidden.get("required") or []
            if required and all(key in value for key in required):
                issues.append({"path": path, "message": f"forbidden field set present: {required}"})
        for field in schema.get("required") or []:
            if field not in value:
                issues.append({"path": f"{path}.{field}", "message": "missing required field"})
        props = schema.get("properties") or {}
        for field, child_schema in props.items():
            if field in value and isinstance(child_schema, dict):
                issues.extend(validate_value(value[field], child_schema, f"{path}.{field}"))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            issues.extend(validate_value(item, schema["items"], f"{path}[{index}]"))
    return issues


def summarize_issues(issues: list[dict[str, Any]], limit: int = 30) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for issue in issues:
        path = str(issue.get("path") or "")
        normalized = re.sub(r"\[\d+\]", "[]", path)
        key = f"{normalized}: {issue.get('message')}"
        counts[key] = counts.get(key, 0) + 1
    return {
        "issue_count": len(issues),
        "top_issue_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]),
        "examples": issues[:limit],
    }


def field_coverage(rows: list[dict[str, Any]], required: list[str]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for field in required:
        present = sum(1 for row in rows if field in row)
        non_empty = sum(1 for row in rows if is_present(row.get(field)))
        coverage[field] = {
            "present": present,
            "non_empty": non_empty,
            "present_rate": round(present / max(len(rows), 1), 4),
            "non_empty_rate": round(non_empty / max(len(rows), 1), 4),
        }
    missing_all = [field for field, item in coverage.items() if item["present"] == 0]
    empty_all = [field for field, item in coverage.items() if item["present"] > 0 and item["non_empty"] == 0]
    return {"row_count": len(rows), "fields": coverage, "missing_all": missing_all, "empty_all": empty_all}


def normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s·・|@:,，.。()（）\[\]【】\-_/\\]+", "", text)


def build_alias_index(rows: list[dict[str, Any]], name_fields: list[str], alias_field: str = "aliases") -> set[str]:
    names: set[str] = set()
    for row in rows:
        for field in name_fields:
            key = normalize_key(row.get(field))
            if key:
                names.add(key)
        aliases = row.get(alias_field)
        if isinstance(aliases, list):
            for alias in aliases:
                key = normalize_key(alias)
                if key:
                    names.add(key)
    return names


def compare_names(source_names: set[str], registry_index: set[str], limit: int = 25) -> dict[str, Any]:
    matched = sorted(name for name in source_names if name in registry_index)
    unmatched = sorted(name for name in source_names if name not in registry_index)
    return {
        "source_unique": len(source_names),
        "matched_unique": len(matched),
        "unmatched_unique": len(unmatched),
        "match_rate": round(len(matched) / max(len(source_names), 1), 4),
        "unmatched_examples": unmatched[:limit],
    }


def load_registry_rows(registry: dict[str, Any], collection: str) -> list[dict[str, Any]]:
    rows = registry.get(collection)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def collect_release_names(release_pack: Path, coverage_limit: int) -> dict[str, set[str]]:
    account_names: set[str] = set()
    venue_names: set[str] = set()
    participant_names: set[str] = set()

    for row in iter_jsonl(release_pack / "articles.jsonl", coverage_limit):
        key = normalize_key(row.get("source_account"))
        if key:
            account_names.add(key)

    for row in iter_jsonl(release_pack / "events.jsonl", coverage_limit):
        for field in ("place", "venue_name"):
            key = normalize_key(row.get(field))
            if key:
                venue_names.add(key)
        participants = row.get("participants")
        if isinstance(participants, list):
            for item in participants:
                key = normalize_key(item)
                if key:
                    participant_names.add(key)
        organizers = row.get("organizers")
        if isinstance(organizers, list):
            for item in organizers:
                key = normalize_key(item)
                if key:
                    account_names.add(key)

    return {"accounts": account_names, "venues": venue_names, "participants": participant_names}


def validate_event_schema_against_pack(schema: dict[str, Any], release_pack: Path, sample_per_file: int) -> dict[str, Any]:
    rows = sample_jsonl(release_pack / "events.jsonl", sample_per_file)
    issues: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        issues.extend(validate_value(row, schema, f"events[{index}]"))
    required = list(schema.get("required") or [])
    coverage = field_coverage(rows, required)
    ok = not issues
    return {
        "target": "release_pack_events_direct",
        "sample_count": len(rows),
        "ok": ok,
        "direct_compatible": ok,
        "pack_schema_versions": sorted({str(row.get("schema_version") or "") for row in rows}),
        "field_coverage": coverage,
        "issues": summarize_issues(issues),
        "decision": "directly_compatible" if ok else "adapter_required_before_weekly_publish",
    }


def validate_registry_schema(
    schema_file: Path,
    schema: dict[str, Any],
    registries_dir: Path,
    release_names: dict[str, set[str]],
) -> dict[str, Any]:
    registry_name = REGISTRY_BY_SCHEMA[schema_file.name]
    registry_path = registries_dir / registry_name
    result: dict[str, Any] = {
        "target": registry_name,
        "path": str(registry_path),
        "exists": registry_path.exists(),
        "ok": False,
        "schema_valid": False,
        "coverage": {},
    }
    if not registry_path.exists():
        result["issues"] = summarize_issues([{"path": str(registry_path), "message": "missing registry file"}])
        result["decision"] = "registry_missing"
        return result

    registry = read_json(registry_path)
    issues = validate_value(registry, schema, registry_path.name)
    schema_valid = not issues
    result["schema_valid"] = schema_valid
    result["issues"] = summarize_issues(issues)

    if schema_file.name == "weekly_account_registry.v1.schema.json":
        rows = load_registry_rows(registry, "accounts")
        index = build_alias_index(rows, ["account_name", "account_id"])
        result["registry_rows"] = len(rows)
        result["coverage"] = compare_names(release_names["accounts"], index)
    elif schema_file.name == "weekly_artist_registry.v1.schema.json":
        rows = load_registry_rows(registry, "artists")
        index = build_alias_index(rows, ["canonical_name", "artist_id"])
        blocked = {normalize_key(item) for item in registry.get("blocked_lineup_terms", []) if normalize_key(item)}
        coverage = compare_names(release_names["participants"], index)
        coverage["blocked_term_matches"] = sum(1 for name in release_names["participants"] if name in blocked)
        result["registry_rows"] = len(rows)
        result["coverage"] = coverage
    elif schema_file.name == "weekly_venue_registry.v1.schema.json":
        rows = load_registry_rows(registry, "venues")
        index = build_alias_index(rows, ["canonical_name", "venue_id"])
        result["registry_rows"] = len(rows)
        result["coverage"] = compare_names(release_names["venues"], index)

    coverage = result.get("coverage") or {}
    coverage_ok = bool(coverage) and coverage.get("source_unique", 0) > 0 and coverage.get("match_rate", 0.0) > 0
    result["ok"] = schema_valid and coverage_ok
    result["decision"] = "registry_schema_and_sample_coverage_ready" if result["ok"] else "registry_schema_or_coverage_gap"
    return result


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    reject_d_path(args.release_pack, "release_pack")
    reject_d_path(args.schemas, "schemas")
    reject_d_path(args.registries, "registries")
    if args.weekly_path_report is not None:
        reject_d_path(args.weekly_path_report, "weekly_path_report")
    schema_files = sorted(args.schemas.glob("*.schema.json"))
    discovered_schema_names = [schema_file.name for schema_file in schema_files]
    expected_schema_names = set(EXPECTED_SCHEMA_NAMES)
    discovered_schema_name_set = set(discovered_schema_names)
    missing_schema_names = sorted(expected_schema_names - discovered_schema_name_set)
    unexpected_schema_names = sorted(discovered_schema_name_set - expected_schema_names)
    schema_set_ok = not missing_schema_names and not unexpected_schema_names
    release_names = collect_release_names(args.release_pack, args.coverage_limit)
    weekly_path = read_optional_json(args.weekly_path_report)

    checks: dict[str, Any] = {}
    for schema_file in schema_files:
        schema = read_json(schema_file)
        if schema_file.name == "weekly_event_published.v1.schema.json":
            checks[schema_file.name] = validate_event_schema_against_pack(schema, args.release_pack, args.sample_per_file)
        elif schema_file.name in REGISTRY_BY_SCHEMA:
            checks[schema_file.name] = validate_registry_schema(schema_file, schema, args.registries, release_names)
        else:
            checks[schema_file.name] = {"ok": False, "decision": "unknown_weekly_schema_target"}

    for schema_name in missing_schema_names:
        checks[schema_name] = {
            "target": schema_name,
            "path": str(args.schemas / schema_name),
            "exists": False,
            "ok": False,
            "decision": "required_schema_missing",
        }

    event_check = checks.get("weekly_event_published.v1.schema.json") or {}
    registry_checks = {name: checks.get(name) or {} for name in REGISTRY_BY_SCHEMA}
    direct_event_ok = bool(event_check.get("ok"))
    registries_ok = all(bool(item.get("ok")) for item in registry_checks.values())
    selected_weekly_path_ready = (
        bool(args.allow_selected_weekly_path)
        and bool(weekly_path.get("ok"))
        and bool(weekly_path.get("production_ready"))
        and weekly_path.get("recommended_path") == "weekly_recommendation_pipeline_for_weekly_publish"
    )
    direct_schema_blocked_but_selected_path_ready = (
        registries_ok and not direct_event_ok and selected_weekly_path_ready
    )
    all_expected_checks_ok = all(bool((checks.get(name) or {}).get("ok")) for name in EXPECTED_SCHEMA_NAMES)
    ok = schema_set_ok and (all_expected_checks_ok or direct_schema_blocked_but_selected_path_ready)
    blockers: list[str] = []
    if missing_schema_names:
        blockers.append(f"schema_set: missing required schemas: {', '.join(missing_schema_names)}")
    if unexpected_schema_names:
        blockers.append(f"schema_set: unexpected schemas: {', '.join(unexpected_schema_names)}")
    for name, item in checks.items():
        if direct_schema_blocked_but_selected_path_ready and name == "weekly_event_published.v1.schema.json":
            continue
        if not item.get("ok"):
            blockers.append(f"{name}: {item.get('decision')}")
    if not schema_set_ok:
        decision = "weekly_schema_set_missing_or_unexpected"
    elif direct_schema_blocked_but_selected_path_ready:
        decision = "weekly_schema_selected_path_ready_direct_stage7_adapter_deferred"
    else:
        decision = "weekly_schema_compat_ready" if ok else "weekly_schema_adapter_or_registry_fix_required"
    return {
        "schema_version": "stage7_weekly_schema_compat.v1",
        "generated_at": now_iso(),
        "ok": ok,
        "decision": decision,
        "release_pack": str(args.release_pack),
        "schemas": str(args.schemas),
        "registries": str(args.registries),
        "sample_per_file": args.sample_per_file,
        "coverage_limit": args.coverage_limit,
        "release_name_counts": {key: len(value) for key, value in release_names.items()},
        "schema_set": {
            "ok": schema_set_ok,
            "expected": list(EXPECTED_SCHEMA_NAMES),
            "discovered": discovered_schema_names,
            "missing": missing_schema_names,
            "unexpected": unexpected_schema_names,
        },
        "checks": checks,
        "selected_weekly_path": {
            "enabled": bool(args.allow_selected_weekly_path),
            "report": str(args.weekly_path_report) if args.weekly_path_report else "",
            "decision": weekly_path.get("decision"),
            "recommended_path": weekly_path.get("recommended_path"),
            "production_ready": weekly_path.get("production_ready"),
            "direct_stage7_schema_blocked_but_not_selected": direct_schema_blocked_but_selected_path_ready,
        },
        "blockers": blockers,
        "warnings": (
            [
                "Stage7 consumer release-pack events are not directly weekly_event_published.v1; "
                "weekly production remains on weekly recommendation/exporter path."
            ]
            if direct_schema_blocked_but_selected_path_ready
            else []
        ),
        "writes": "reports_only",
        "safety": [
            "no production publish",
            "no production SQLite write",
            "no Qdrant or Neo4j write",
            "no paid API call",
            "no D: scan",
        ],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Weekly Schema Compatibility",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- sample_per_file: `{report['sample_per_file']}`",
        f"- coverage_limit: `{report['coverage_limit']}`",
        f"- release_name_counts: `{json.dumps(report['release_name_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Schema Set",
        "",
        f"- ok: `{report['schema_set']['ok']}`",
        f"- expected: `{json.dumps(report['schema_set']['expected'], ensure_ascii=False)}`",
        f"- discovered: `{json.dumps(report['schema_set']['discovered'], ensure_ascii=False)}`",
        f"- missing: `{json.dumps(report['schema_set']['missing'], ensure_ascii=False)}`",
        f"- unexpected: `{json.dumps(report['schema_set']['unexpected'], ensure_ascii=False)}`",
        "",
        "## Selected Weekly Path",
        "",
        f"- enabled: `{report['selected_weekly_path']['enabled']}`",
        f"- decision: `{report['selected_weekly_path']['decision']}`",
        f"- recommended_path: `{report['selected_weekly_path']['recommended_path']}`",
        f"- production_ready: `{report['selected_weekly_path']['production_ready']}`",
        f"- direct_stage7_schema_blocked_but_not_selected: `{report['selected_weekly_path']['direct_stage7_schema_blocked_but_not_selected']}`",
        "",
        "## Checks",
        "",
    ]
    for name, item in report["checks"].items():
        lines.extend(
            [
                f"### {name}",
                "",
                f"- ok: `{item.get('ok')}`",
                f"- decision: `{item.get('decision')}`",
            ]
        )
        if "sample_count" in item:
            lines.append(f"- sample_count: `{item.get('sample_count')}`")
        if "registry_rows" in item:
            lines.append(f"- registry_rows: `{item.get('registry_rows')}`")
        if item.get("coverage"):
            lines.append(f"- coverage: `{json.dumps(item['coverage'], ensure_ascii=False, sort_keys=True)}`")
        issues = item.get("issues") or {}
        lines.append(f"- issue_count: `{issues.get('issue_count', 0)}`")
        top = issues.get("top_issue_counts") or {}
        if top:
            lines.append("- top_issues:")
            for key, count in top.items():
                lines.append(f"  - `{count}` x `{key}`")
        lines.append("")

    lines.extend(["## Blockers", ""])
    if report["blockers"]:
        for blocker in report["blockers"]:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        for warning in report["warnings"]:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- No production publish.",
            "- No production SQLite write.",
            "- No Qdrant or Neo4j write.",
            "- No paid API call.",
            "- No D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = build_report(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "schema_compat_report.json", report)
    write_markdown(args.out_dir / "schema_compat_report.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "blockers": len(report["blockers"]),
                "report": str(args.out_dir / "schema_compat_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-pack", type=Path, default=DEFAULT_RELEASE_PACK)
    parser.add_argument("--schemas", type=Path, default=DEFAULT_SCHEMAS)
    parser.add_argument("--registries", type=Path, default=DEFAULT_REGISTRIES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-per-file", type=int, default=200)
    parser.add_argument("--coverage-limit", type=int, default=50000, help="0 means full JSONL scan")
    parser.add_argument("--weekly-path-report", type=Path, default=DEFAULT_WEEKLY_PATH_REPORT)
    parser.add_argument(
        "--allow-selected-weekly-path",
        action="store_true",
        help=(
            "Treat direct Stage7-to-weekly schema incompatibility as non-blocking when the selected "
            "weekly recommendation/exporter path is already production_ready."
        ),
    )
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
