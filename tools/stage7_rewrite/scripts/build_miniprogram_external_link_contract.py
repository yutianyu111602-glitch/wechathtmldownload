#!/usr/bin/env python3
"""Build the S120 mini-program external-link display contract.

Consumes the S119 DB2 sidecar candidates and emits a public-safe, high
confidence package for mini-program API/UI integration. This script does not
fetch the network, mutate DB1/DB2/DB3, or authorize production release.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "miniprogram_external_link_contract_s120.v1"
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "external_link_db2_sidecar_contract_s119_20260601"
    / "external_link_db2_sidecar_candidates.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "miniprogram_external_link_contract_s120_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_MINIPROGRAM_EXTERNAL_LINK_CONTRACT_S120_20260601.md"

ALLOWED_PUBLIC_CATEGORIES = {
    "source_article",
    "instagram",
    "mixtape_music",
    "radio",
    "video",
    "public_profile",
}
CATEGORY_PRIORITY = {
    "source_article": 10,
    "instagram": 20,
    "mixtape_music": 30,
    "radio": 40,
    "video": 50,
    "public_profile": 90,
}
CATEGORY_LABELS = {
    "source_article": "原文",
    "instagram": "Instagram",
    "mixtape_music": "Mixtape",
    "radio": "电台",
    "video": "视频",
    "public_profile": "主页",
}
DIRECT_MEDIA_RE = re.compile(r"\.(mp3|m4a|aac|flac|wav|ogg|mp4|mov|mkv|avi|zip|rar|7z|tar|gz)(\?|#|$)", re.I)
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)
LOCAL_PATH_RE = re.compile(r"(?i)(^|[\"'\s])([A-Z]:\\|/mnt/[a-z]/|\\\\wsl\.localhost\\|tools/stage7_rewrite/reports/|cache/)")


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


def stable_id(value: Any) -> str:
    import hashlib

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def canonical_url(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def is_direct_media_url(url: str) -> bool:
    return bool(DIRECT_MEDIA_RE.search(str(url or "")))


def normalize_category(value: Any) -> str:
    category = str(value or "public_profile").strip().lower()
    return category if category in ALLOWED_PUBLIC_CATEGORIES else "public_profile"


def confidence_score(row: dict[str, Any]) -> int:
    try:
        return int(row.get("confidence_score") or 0)
    except (TypeError, ValueError):
        return 0


def is_high_confidence_public_safe(row: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    url = canonical_url(str(row.get("url") or ""))
    category = normalize_category(row.get("public_category"))
    if not url:
        reasons.append("invalid_url")
    if category not in ALLOWED_PUBLIC_CATEGORIES:
        reasons.append("unsupported_category")
    if row.get("confidence_band") != "high":
        reasons.append("not_high_confidence")
    if confidence_score(row) < 85:
        reasons.append("confidence_score_below_85")
    if row.get("block_reasons"):
        reasons.append("blocked_in_db2_sidecar")
    if is_direct_media_url(url):
        reasons.append("direct_media_or_archive_url")
    if row.get("copyright_safety") not in {"jump_out_only_no_hosting_no_proxy", "public_link_jump_out"}:
        reasons.append("copyright_policy_not_jump_out")
    return not reasons, reasons


def display_label(row: dict[str, Any]) -> str:
    category = normalize_category(row.get("public_category"))
    platform = str(row.get("platform") or "").strip()
    if platform == "residentadvisor":
        return "RA"
    if platform and category != "source_article":
        return platform[:1].upper() + platform[1:]
    return CATEGORY_LABELS.get(category, "外链")


def to_miniprogram_item(row: dict[str, Any]) -> dict[str, Any]:
    category = normalize_category(row.get("public_category"))
    url = canonical_url(str(row.get("url") or ""))
    entity_search_id = str(row.get("entity_search_id") or "")
    item_id = stable_id({"entity_search_id": entity_search_id, "url": url, "sidecar_id": row.get("sidecar_id")})
    return {
        "item_id": item_id,
        "sidecar_id": str(row.get("sidecar_id") or ""),
        "entity_search_id": entity_search_id,
        "entity_name": str(row.get("entity_name") or ""),
        "entity_type": str(row.get("entity_type") or ""),
        "platform": str(row.get("platform") or "external"),
        "public_category": category,
        "display_label": display_label(row),
        "display_group": CATEGORY_LABELS.get(category, "外链"),
        "display_priority": CATEGORY_PRIORITY[category],
        "url": url,
        "source_ref": str(row.get("source_ref") or ""),
        "source_layer": str(row.get("source_layer") or ""),
        "confidence_score": confidence_score(row),
        "confidence_band": "high",
        "copyright_safety": str(row.get("copyright_safety") or ""),
        "miniapp_display_allowed_candidate": True,
        "action": {
            "mode": "copy_original_link",
            "jump_out_original_url": True,
            "media_cached": False,
            "media_downloaded": False,
            "media_proxied": False,
        },
    }


def build_items(rows: list[dict[str, Any]], per_entity_limit: int) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, list[str]]]:
    reject_counts: Counter[str] = Counter()
    reject_samples: dict[str, list[str]] = defaultdict(list)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        ok, reasons = is_high_confidence_public_safe(row)
        if not ok:
            for reason in reasons:
                reject_counts[reason] += 1
                samples = reject_samples[reason]
                if len(samples) < 5:
                    samples.append(str(row.get("sidecar_id") or row.get("task_id") or "unknown"))
            continue
        item = to_miniprogram_item(row)
        dedupe_key = (item["entity_search_id"], item["url"])
        if dedupe_key in seen:
            reject_counts["duplicate_entity_url"] += 1
            continue
        seen.add(dedupe_key)
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            str(item["entity_name"]).lower(),
            int(item["display_priority"]),
            -int(item["confidence_score"]),
            str(item["url"]),
        )
    )
    entity_counts: Counter[str] = Counter()
    limited: list[dict[str, Any]] = []
    for item in candidates:
        entity_key = item["entity_search_id"] or item["entity_name"] or item["item_id"]
        if entity_counts[entity_key] >= per_entity_limit:
            reject_counts["per_entity_limit"] += 1
            continue
        entity_counts[entity_key] += 1
        limited.append(item)
    return limited, dict(reject_counts), dict(reject_samples)


def group_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item["entity_search_id"] or item["entity_name"] or item["item_id"]
        if key not in groups:
            groups[key] = {
                "entity_search_id": item["entity_search_id"],
                "entity_name": item["entity_name"],
                "entity_type": item["entity_type"],
                "links": [],
            }
        groups[key]["links"].append(item)
    return sorted(groups.values(), key=lambda group: str(group["entity_name"]).lower())


def schema_contract() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "required_item_fields": [
            "item_id",
            "entity_search_id",
            "entity_name",
            "platform",
            "public_category",
            "display_label",
            "display_priority",
            "url",
            "confidence_score",
            "confidence_band",
            "miniapp_display_allowed_candidate",
            "action",
        ],
        "allowed_public_categories": sorted(ALLOWED_PUBLIC_CATEGORIES),
        "copyright_policy": "jump_out_original_url_only_no_hosting_no_proxy",
        "forbidden_fields": ["cache_path", "raw_metadata_json", "cookie", "token", "password"],
    }


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "item_count": len(items),
        "entity_count": len({item["entity_search_id"] or item["entity_name"] for item in items}),
        "by_platform": dict(Counter(item["platform"] or "external" for item in items).most_common()),
        "by_public_category": dict(Counter(item["public_category"] for item in items).most_common()),
        "by_action_mode": dict(Counter(item["action"]["mode"] for item in items).most_common()),
    }


def gate_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = json.dumps(items, ensure_ascii=False)
    all_high = all(item["confidence_band"] == "high" and item["confidence_score"] >= 85 for item in items)
    jump_out_only = all(
        item["action"]["mode"] == "copy_original_link"
        and item["action"]["jump_out_original_url"] is True
        and not item["action"]["media_cached"]
        and not item["action"]["media_downloaded"]
        and not item["action"]["media_proxied"]
        for item in items
    )
    return [
        {"gate_id": "items_present", "passed": bool(items), "detail": f"items={len(items)}"},
        {"gate_id": "high_confidence_only", "passed": all_high, "detail": "confidence_band=high and score>=85"},
        {"gate_id": "allowed_categories_only", "passed": all(item["public_category"] in ALLOWED_PUBLIC_CATEGORIES for item in items), "detail": "source/instagram/mixtape/radio/video/profile only"},
        {"gate_id": "jump_out_only_no_media_proxy", "passed": jump_out_only, "detail": "copy original URL; no cache/download/proxy"},
        {"gate_id": "no_internal_cache_path_leak", "passed": LOCAL_PATH_RE.search(text) is None, "detail": "no cache_path/raw local path in public package"},
    ]


def secret_findings(report: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, str]]:
    text = json.dumps({"report": report, "items": items}, ensure_ascii=False)
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


def render_markdown(report: dict[str, Any], items: list[dict[str, Any]], gates: list[dict[str, Any]]) -> str:
    lines = [
        "# Weekly Mini-Program External-Link Contract S120",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Input: `{report['input_path']}`",
        f"- Item count: `{report['summary']['item_count']}`",
        f"- Entity count: `{report['summary']['entity_count']}`",
        f"- Secret-like findings: `{report['finding_count']}`",
        f"- DB mutation: `{report['boundaries']['database_mutation']}`",
        f"- Network fetch: `{report['boundaries']['network_fetch']}`",
        f"- Mini-program release: `{report['boundaries']['miniapp_release']}`",
        "",
        "## Outputs",
        "",
    ]
    for key, value in report["outputs"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Display Gates", ""])
    lines.extend(markdown_table(gates, ["gate_id", "passed", "detail"], 20))
    lines.extend(["", "## Category Counts", ""])
    for key, value in report["summary"]["by_public_category"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Sample Display Items", ""])
    lines.extend(
        markdown_table(
            items,
            ["item_id", "entity_name", "platform", "public_category", "display_label", "confidence_score"],
            20,
        )
    )
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- This package is public-safe candidate data for API/UI integration only.",
            "- Audio, video, radio, and mixtape links stay as original external links; no hosting, proxying, or downloading.",
            "- DB2 projection and production release still require later gates.",
            "",
            "## Next",
            "",
            "- S121 should audit DB1/DB2/DB3 join keys, index shape, and query performance before merge execution.",
            "- A later UI story can bind this package into artist/detail pages after rendered DevTools coverage passes.",
            "",
        ]
    )
    return "\n".join(lines)


def build_contract(input_path: Path, out_dir: Path, scorecard: Path, per_entity_limit: int) -> dict[str, Any]:
    rows = load_jsonl(input_path)
    items, reject_counts, reject_samples = build_items(rows, per_entity_limit=per_entity_limit)
    groups = group_items(items)
    gates = gate_results(items)

    out_dir.mkdir(parents=True, exist_ok=True)
    items_path = out_dir / "miniprogram_external_link_items.json"
    grouped_path = out_dir / "miniprogram_external_link_groups.json"
    schema_path = out_dir / "miniprogram_external_link_schema.json"
    report_path = out_dir / "miniprogram_external_link_contract.json"
    atomic_write_json(items_path, items)
    atomic_write_json(grouped_path, groups)
    atomic_write_json(schema_path, schema_contract())

    outputs = {
        "items_json": rel_path(items_path),
        "groups_json": rel_path(grouped_path),
        "schema": rel_path(schema_path),
        "report": rel_path(report_path),
        "scorecard": rel_path(scorecard),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "miniprogram_external_link_contract_ready",
        "input_path": rel_path(input_path),
        "outputs": outputs,
        "summary": summarize(items),
        "reject_counts": reject_counts,
        "reject_samples": reject_samples,
        "display_gates": gates,
        "boundaries": {
            "candidate_package_only": True,
            "network_fetch": False,
            "database_mutation": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection_allowed": False,
            "miniapp_api_contract_candidate": True,
            "miniapp_release": False,
            "cookie_values_read": False,
            "token_values_read": False,
        },
        "next_story": "S121",
    }
    findings = secret_findings(report, items)
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings or not all(gate["passed"] for gate in gates):
        report["decision"] = "miniprogram_external_link_contract_blocked"

    atomic_write_json(report_path, report)
    markdown = render_markdown(report, items, gates)
    atomic_write_text(out_dir / "miniprogram_external_link_contract.md", markdown)
    atomic_write_text(scorecard, markdown)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--per-entity-limit", type=int, default=12)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_contract(args.input, args.out_dir, args.scorecard, args.per_entity_limit)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "finding_count": report["finding_count"],
                "item_count": report["summary"]["item_count"],
                "entity_count": report["summary"]["entity_count"],
                "by_public_category": report["summary"]["by_public_category"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["decision"].endswith("_blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
