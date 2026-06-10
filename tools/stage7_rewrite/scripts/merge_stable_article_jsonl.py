#!/usr/bin/env python3
"""Merge stable article JSONL files without overwriting base rows.

This is a report/staging merge helper. It appends add-on rows whose
article_uid is not already present in the base stable JSONL.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                yield line_no, row


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def norm_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def list_len(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    return len(value) if isinstance(value, list) else 0


def lane_of(row: dict[str, Any]) -> str:
    route = row.get("corrected_route")
    if isinstance(route, dict):
        lane = route.get("lane")
        if lane:
            return str(lane)
    return "unknown"


def source_of(row: dict[str, Any]) -> str:
    route = row.get("corrected_route")
    if isinstance(route, dict):
        source = route.get("coverage_source")
        if source:
            return str(source)
    return "unknown"


def annotate_addon_row(
    row: dict[str, Any],
    *,
    addon_path: Path,
    line_no: int,
    addon_lane: str,
    addon_source: str,
) -> dict[str, Any]:
    updated = dict(row)
    route = updated.get("corrected_route")
    if not isinstance(route, dict):
        route = {}
    route = dict(route)
    route.setdefault("lane", addon_lane)
    route.setdefault("coverage_source", addon_source)
    route.setdefault("source_jsonl", norm_path(addon_path))
    route.setdefault("source_line", line_no)
    updated["corrected_route"] = route
    return updated


def merge_stable(
    base: Path,
    addon: Path,
    out_dir: Path,
    *,
    addon_lane: str,
    addon_source: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stable_path = out_dir / "stable_articles.jsonl"
    manifest_path = out_dir / "stable_articles_manifest.jsonl"
    summary_path = out_dir / "stable_merge_summary.json"
    summary_md_path = out_dir / "stable_merge_summary.md"

    seen: set[str] = set()
    base_rows = 0
    addon_rows = 0
    appended_rows = 0
    duplicate_addon_rows = 0
    missing_uid_rows = 0
    lane_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    totals: Counter[str] = Counter()

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=out_dir, delete=False) as stable_handle, tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=out_dir, delete=False
    ) as manifest_handle:
        stable_tmp = Path(stable_handle.name)
        manifest_tmp = Path(manifest_handle.name)

        for _line_no, row in read_jsonl(base):
            uid = str(row.get("article_uid") or "")
            if not uid:
                missing_uid_rows += 1
                continue
            if uid in seen:
                continue
            seen.add(uid)
            base_rows += 1
            stable_handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            lane = lane_of(row)
            source = source_of(row)
            lane_counts[lane] += 1
            source_counts[source] += 1
            totals["entities"] += list_len(row, "entities")
            totals["events"] += list_len(row, "events")
            totals["relations"] += list_len(row, "relations")
            totals["claims"] += list_len(row, "claims")
            manifest_handle.write(
                json.dumps(
                    {
                        "article_uid": uid,
                        "source_account": row.get("source_account"),
                        "title": row.get("title"),
                        "lane": lane,
                        "coverage_source": source,
                        "entities": list_len(row, "entities"),
                        "events": list_len(row, "events"),
                        "relations": list_len(row, "relations"),
                        "claims": list_len(row, "claims"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

        for line_no, row in read_jsonl(addon):
            addon_rows += 1
            uid = str(row.get("article_uid") or "")
            if not uid:
                missing_uid_rows += 1
                continue
            if uid in seen:
                duplicate_addon_rows += 1
                continue
            seen.add(uid)
            updated = annotate_addon_row(
                row,
                addon_path=addon,
                line_no=line_no,
                addon_lane=addon_lane,
                addon_source=addon_source,
            )
            appended_rows += 1
            lane = lane_of(updated)
            source = source_of(updated)
            stable_handle.write(json.dumps(updated, ensure_ascii=False, sort_keys=True) + "\n")
            lane_counts[lane] += 1
            source_counts[source] += 1
            totals["entities"] += list_len(updated, "entities")
            totals["events"] += list_len(updated, "events")
            totals["relations"] += list_len(updated, "relations")
            totals["claims"] += list_len(updated, "claims")
            manifest_handle.write(
                json.dumps(
                    {
                        "article_uid": uid,
                        "source_account": updated.get("source_account"),
                        "title": updated.get("title"),
                        "lane": lane,
                        "coverage_source": source,
                        "entities": list_len(updated, "entities"),
                        "events": list_len(updated, "events"),
                        "relations": list_len(updated, "relations"),
                        "claims": list_len(updated, "claims"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    stable_tmp.replace(stable_path)
    manifest_tmp.replace(manifest_path)

    article_count = base_rows + appended_rows
    summary = {
        "schema_version": "stage7_stable_article_jsonl_merge.v1",
        "generated_at": now_iso(),
        "base_stable_articles": norm_path(base),
        "addon_stable_articles": norm_path(addon),
        "articles": article_count,
        "base_rows": base_rows,
        "addon_rows": addon_rows,
        "appended_rows": appended_rows,
        "duplicate_addon_rows": duplicate_addon_rows,
        "missing_uid_rows": missing_uid_rows,
        "lane_counts": dict(sorted(lane_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "totals": dict(sorted(totals.items())),
        "writes": "merged stable JSONL artifacts only; no API/vector/DB/graph/source archive reads",
        "outputs": {
            "stable_articles": norm_path(stable_path),
            "manifest": norm_path(manifest_path),
            "summary_json": norm_path(summary_path),
            "summary_md": norm_path(summary_md_path),
        },
    }
    write_json(summary_path, summary)
    summary_md_path.write_text(
        "\n".join(
            [
                "# Stable Article Merge Summary",
                "",
                f"- generated_at: `{summary['generated_at']}`",
                f"- articles: `{summary['articles']}`",
                f"- base_rows: `{summary['base_rows']}`",
                f"- addon_rows: `{summary['addon_rows']}`",
                f"- appended_rows: `{summary['appended_rows']}`",
                f"- duplicate_addon_rows: `{summary['duplicate_addon_rows']}`",
                f"- lane_counts: `{summary['lane_counts']}`",
                f"- source_counts: `{summary['source_counts']}`",
                f"- writes: `{summary['writes']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--addon-lane", default="empty_no_local_image")
    parser.add_argument("--addon-source", default="recovered_dajiala_qwen_20260515")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = merge_stable(
        args.base,
        args.addon,
        args.out_dir,
        addon_lane=args.addon_lane,
        addon_source=args.addon_source,
    )
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
