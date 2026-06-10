#!/usr/bin/env python3
"""Extract PRD-16 public social candidates from imported radio assets.

This is a report-only candidate scan. It reads the existing radio social asset
JSONL, classifies public links, skips Instagram by default, and writes one
deduplicated candidate file per platform.

No login, cookies, graph/vector/DB writes, paid API calls, D: scans, or publish.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_public_social_links as link_validator  # noqa: E402


DEFAULT_ASSETS = Path("reports/p1_dj_dataset_import_20260514/radio_social_assets.jsonl")
DEFAULT_OUT_DIR = Path("reports/social_deep_candidates_20260515")
DEFAULT_PLATFORMS = {
    "soundcloud",
    "bandcamp",
    "linktree",
    "residentadvisor",
    "youtube",
    "bilibili",
}
SCHEMA_VERSION = "stage7_social_deep_radio_social_candidates.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for PRD-16 social candidate scan: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "assets")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def platform_arg(value: str) -> str:
    text = value.strip().casefold()
    aliases = {
        "ra": "residentadvisor",
        "resident-advisor": "residentadvisor",
        "resident_advisor": "residentadvisor",
        "yt": "youtube",
    }
    return aliases.get(text, text)


def collect_candidates(
    assets_path: Path,
    platforms: set[str],
    include_instagram: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(assets_path)
    candidates: list[dict[str, Any]] = []
    observed_platform_counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    seen: set[str] = set()
    total_social_link_values = 0

    for asset in rows:
        links = asset.get("social_links") or []
        if not isinstance(links, list):
            skipped["invalid_social_links_field"] += 1
            continue
        for raw_url in links:
            url = first_text(raw_url)
            if not url:
                skipped["empty_url"] += 1
                continue
            total_social_link_values += 1
            platform = link_validator.platform_from_url(url)
            observed_platform_counts[platform] += 1
            if platform == "instagram" and not include_instagram:
                skipped["instagram_skipped_no_login"] += 1
                continue
            if platform not in platforms:
                skipped[f"unsupported_platform:{platform}"] += 1
                continue
            normalized = link_validator.normalize_url(url)
            if normalized in seen:
                skipped["duplicate_url"] += 1
                continue
            seen.add(normalized)
            candidate = {
                "schema_version": SCHEMA_VERSION + ".row",
                "source": "radio_social_assets",
                "source_family": first_text(asset.get("source_family")),
                "asset_type": first_text(asset.get("asset_type")),
                "subject_name": first_text(asset.get("artist_name") or asset.get("title")),
                "title": first_text(asset.get("title")),
                "evidence_url": first_text(asset.get("page_url")),
                "url": url,
                "normalized_url": normalized,
                "platform": platform,
                "link_kind": link_validator.link_kind(url),
                "raw_source_path": first_text(asset.get("raw_source_path")),
            }
            candidates.append(candidate)

    summary = {
        "rows_read": len(rows),
        "total_social_link_values": total_social_link_values,
        "observed_platform_counts": dict(observed_platform_counts),
        "skipped": dict(skipped),
    }
    return candidates, summary


def build_candidates(
    assets_path: Path,
    out_dir: Path,
    platforms: set[str],
    include_instagram: bool = False,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    candidates, source_summary = collect_candidates(
        assets_path=assets_path,
        platforms=platforms,
        include_instagram=include_instagram,
    )
    platform_counts = Counter(row["platform"] for row in candidates)
    kind_counts = Counter(row["link_kind"] for row in candidates)
    by_platform: dict[str, list[dict[str, Any]]] = {platform: [] for platform in sorted(platforms)}
    for row in candidates:
        by_platform.setdefault(row["platform"], []).append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    all_candidates_path = out_dir / "social_deep_candidates.jsonl"
    write_jsonl(all_candidates_path, candidates)
    platform_paths: dict[str, str] = {}
    for platform in sorted(platforms):
        path = out_dir / f"{platform}_urls.jsonl"
        write_jsonl(path, by_platform.get(platform, []))
        platform_paths[platform] = str(path)

    decision = "social_deep_candidates_found" if candidates else "social_deep_candidates_empty"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": True,
        "assets_path": str(assets_path),
        "out_dir": str(out_dir),
        "all_candidates_path": str(all_candidates_path),
        "platform_paths": platform_paths,
        "candidate_count": len(candidates),
        "platform_counts": dict(platform_counts),
        "kind_counts": dict(kind_counts),
        "include_instagram": include_instagram,
        "requested_platforms": sorted(platforms),
        "rows_read": source_summary["rows_read"],
        "total_social_link_values": source_summary["total_social_link_values"],
        "observed_platform_counts": source_summary["observed_platform_counts"],
        "skipped": source_summary["skipped"],
        "safety": [
            "reports_only",
            "public_urls_only",
            "instagram_skipped_by_default",
            "no_login",
            "no_cookies",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
    }
    write_json(out_dir / "social_deep_candidates_summary.json", summary)
    write_markdown(out_dir / "social_deep_candidates_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-16 Social Deep Candidates",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- candidate_count: `{summary['candidate_count']}`",
        f"- rows_read: `{summary['rows_read']}`",
        f"- total_social_link_values: `{summary['total_social_link_values']}`",
        f"- all_candidates_path: `{summary['all_candidates_path']}`",
        "",
        "## Platform Counts",
        "",
    ]
    for key, value in sorted(summary["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Observed Platform Counts", ""])
    for key, value in sorted(summary["observed_platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Link Kind Counts", ""])
    for key, value in sorted(summary["kind_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Skipped", ""])
    for key, value in sorted(summary["skipped"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Instagram is skipped by default; no login or cookies.",
            "- Public URL presence is not identity proof.",
            "- No graph/vector/DB write, paid API, D: scan, or publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", "--radio-dir", dest="assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--platform", action="append", default=[], help="Repeatable platform allow-list.")
    parser.add_argument("--include-instagram", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    platforms = {platform_arg(item) for item in args.platform} if args.platform else set(DEFAULT_PLATFORMS)
    summary = build_candidates(
        assets_path=args.assets,
        out_dir=args.out_dir,
        platforms=platforms,
        include_instagram=args.include_instagram,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "candidate_count": summary["candidate_count"],
                "summary": str(args.out_dir / "social_deep_candidates_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
