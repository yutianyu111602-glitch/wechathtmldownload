#!/usr/bin/env python3
"""Import legacy dj-dataset radio/social assets into a Stage7 staging report.

The import is evidence only. Rows are marked legacy_unverified and must be
cross-validated against current public pages before graph promotion. The script
reads only explicit C: files and writes C: reports; it does not scan D:, call
paid APIs, publish, or write graph/vector/DB stores.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SOURCE = Path(r"C:\Users\pc\code\dj-dataset\raw")
DEFAULT_OUT_DIR = Path("reports/p1_dj_dataset_import_20260514")
SOURCE_FILES = {
    "baihui_shows": "baihui_shows_full.jsonl",
    "byyb_shows": "byyb_shows_full.jsonl",
    "byyb_djs": "byyb_djs.json",
    "cdcr_djs": "cdcrlive_bilibili_djs.json",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for P1 import: {path}")


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def list_text(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [first_text(item) for item in values if first_text(item)]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_url(url: str) -> str:
    return first_text(url).replace(" ", "%20")


def soundcloud_url(value: str) -> str:
    value = first_text(value)
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return f"https://soundcloud.com/{value.strip('/')}"


def base_row(source_family: str, asset_type: str, source_path: Path) -> dict[str, Any]:
    return {
        "schema_version": "stage7_p1_radio_social_asset.v1",
        "source_family": source_family,
        "asset_type": asset_type,
        "verification_status": "legacy_unverified",
        "cross_validation_required": True,
        "raw_source_path": str(source_path),
        "imported_at": now_iso(),
    }


def import_baihui_shows(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in iter_jsonl(path):
        out = base_row("baihui", "show", path)
        out.update(
            {
                "title": first_text(row.get("title"), row.get("title_en"), row.get("title_cn")),
                "artist_name": "",
                "page_url": normalize_url(row.get("custom_url")),
                "date_raw": first_text(row.get("date")),
                "city": first_text(row.get("city")),
                "genres": list_text(row.get("tags")),
                "audio_links": [normalize_url(row.get("mp3_url"))] if first_text(row.get("mp3_url")) else [],
                "social_links": [],
                "notes": "baihui legacy show with direct mp3_url",
            }
        )
        rows.append(out)
        if limit and len(rows) >= limit:
            break
    return rows


def import_byyb_shows(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in iter_jsonl(path):
        social_links = []
        dj_info = row.get("dj_info") if isinstance(row.get("dj_info"), list) else []
        for dj in dj_info:
            if not isinstance(dj, dict):
                continue
            if first_text(dj.get("instagram"), dj.get("instagram_link")):
                handle = first_text(dj.get("instagram"), dj.get("instagram_link")).strip("@")
                social_links.append(f"https://instagram.com/{handle}")
            sc = soundcloud_url(first_text(dj.get("soundcloud"), dj.get("soundcloud_link")))
            if sc:
                social_links.append(sc)
            if first_text(dj.get("bandcamp")):
                social_links.append(first_text(dj.get("bandcamp")))
        slug = first_text(row.get("slug"))
        out = base_row("byyb", "performance", path)
        out.update(
            {
                "title": first_text(row.get("performance_full_name"), row.get("event_name")),
                "artist_name": first_text(row.get("dj_name")),
                "page_url": f"https://byyb.live/set/{slug}" if slug else "",
                "date_raw": first_text(row.get("date")),
                "city": "",
                "genres": list_text(row.get("genres")),
                "audio_links": [normalize_url(row.get("audio_file_url"))] if first_text(row.get("audio_file_url")) else [],
                "social_links": sorted(set(social_links)),
                "notes": "byyb legacy performance with direct audio_file_url",
            }
        )
        rows.append(out)
        if limit and len(rows) >= limit:
            break
    return rows


def import_byyb_djs(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in load_json(path):
        social_links = []
        if first_text(row.get("instagram"), row.get("instagram_link")):
            social_links.append(f"https://instagram.com/{first_text(row.get('instagram'), row.get('instagram_link')).strip('@')}")
        sc = soundcloud_url(first_text(row.get("soundcloud"), row.get("soundcloud_link")))
        if sc:
            social_links.append(sc)
        if first_text(row.get("bandcamp")):
            social_links.append(first_text(row.get("bandcamp")))
        out = base_row("byyb", "profile", path)
        out.update(
            {
                "title": first_text(row.get("name"), row.get("call_name")),
                "artist_name": first_text(row.get("name"), row.get("call_name")),
                "page_url": f"https://byyb.live/dj/{row.get('slug')}" if first_text(row.get("slug")) else "",
                "date_raw": "",
                "city": "",
                "genres": [],
                "audio_links": [],
                "social_links": sorted(set(social_links)),
                "notes": "byyb legacy DJ profile/social handles",
            }
        )
        rows.append(out)
        if limit and len(rows) >= limit:
            break
    return rows


def import_cdcr_djs(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in load_json(path):
        tracks = row.get("source_tracks") if isinstance(row.get("source_tracks"), list) else []
        out = base_row("cdcr", "bilibili_track_context", path)
        out.update(
            {
                "title": first_text(row.get("name")),
                "artist_name": first_text(row.get("name")),
                "page_url": "",
                "date_raw": "",
                "city": first_text(row.get("city")),
                "genres": list_text(row.get("genres")),
                "audio_links": [],
                "social_links": list_text(row.get("links")),
                "track_contexts": [first_text(item.get("raw_name")) for item in tracks if isinstance(item, dict) and first_text(item.get("raw_name"))],
                "notes": "cdcr legacy Bilibili-derived context; no direct live URL in source",
            }
        )
        rows.append(out)
        if limit and len(rows) >= limit:
            break
    return rows


def build_seed_rows(rows: list[dict[str, Any]], per_station: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    seeds = []
    for row in rows:
        source = row["source_family"]
        if counts.get(source, 0) >= per_station:
            continue
        page_url = first_text(row.get("page_url"))
        if not page_url:
            continue
        if not row.get("audio_links") and source in {"baihui", "byyb"}:
            continue
        seeds.append(
            {
                "source_family": source,
                "page_url": page_url,
                "expected_audio_links": row.get("audio_links") or [],
                "expected_title": row.get("title") or "",
                "expected_artist_name": row.get("artist_name") or "",
            }
        )
        counts[source] = counts.get(source, 0) + 1
    return seeds


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# P1 dj-dataset Legacy Radio/Social Import",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_dir: `{summary['source_dir']}`",
        f"- rows: `{summary['rows']}`",
        f"- seed_rows: `{summary['seed_rows']}`",
        f"- output: `{summary['assets_path']}`",
        f"- seed_output: `{summary['seed_path']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in sorted(summary["counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- Legacy rows are imported as evidence only.",
            "- Every row is `legacy_unverified` and requires live/source cross-validation before graph promotion.",
            "- CDCR legacy source has Bilibili-derived context but no direct live URL; handle it through a later Bilibili/Camofox fallback canary.",
            "",
            "## Safety",
            "",
            "- C: explicit files only.",
            "- No D: scan.",
            "- No paid API.",
            "- No graph/vector/DB write.",
            "- No publish.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def import_assets(source_dir: Path, out_dir: Path, limit_per_source: int, seed_per_station: int) -> dict[str, Any]:
    reject_d_path(source_dir, "source_dir")
    reject_d_path(out_dir, "out_dir")
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    loaders = [
        ("baihui_shows", import_baihui_shows),
        ("byyb_shows", import_byyb_shows),
        ("byyb_djs", import_byyb_djs),
        ("cdcr_djs", import_cdcr_djs),
    ]
    for key, loader in loaders:
        path = source_dir / SOURCE_FILES[key]
        if not path.exists():
            counts[f"{key}:missing"] = 1
            continue
        source_rows = loader(path, limit_per_source)
        counts[key] = len(source_rows)
        rows.extend(source_rows)

    seed_rows = build_seed_rows(rows, seed_per_station)
    assets_path = out_dir / "radio_social_assets.jsonl"
    seed_path = out_dir / "radio_canary_seed_urls.jsonl"
    write_jsonl(assets_path, rows)
    write_jsonl(seed_path, seed_rows)
    summary = {
        "schema_version": "stage7_p1_dj_dataset_import_summary.v1",
        "generated_at": now_iso(),
        "source_dir": str(source_dir),
        "out_dir": str(out_dir),
        "rows": len(rows),
        "seed_rows": len(seed_rows),
        "counts": counts,
        "assets_path": str(assets_path),
        "seed_path": str(seed_path),
        "writes": "reports_only",
    }
    write_json(out_dir / "p1_dj_dataset_import_summary.json", summary)
    write_markdown(out_dir / "p1_dj_dataset_import_summary.md", summary)
    return summary


def run(args: argparse.Namespace) -> int:
    summary = import_assets(args.source_dir, args.out_dir, args.limit_per_source, args.seed_per_station)
    print(
        json.dumps(
            {
                "rows": summary["rows"],
                "seed_rows": summary["seed_rows"],
                "summary": str(args.out_dir / "p1_dj_dataset_import_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit-per-source", type=int, default=0, help="0 means all rows")
    parser.add_argument("--seed-per-station", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
