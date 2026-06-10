#!/usr/bin/env python3
"""Summarize bounded P1 radio/social canary outputs.

Report-only QA for Camoufox radio canaries. It validates that the crawler wrote
parseable rows with body/date/title/link fields and records station-level
failures without promoting any row into graph or consumer stores.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_INPUT = Path("reports/p1_radio_social_canary_20260514/radio_all_canary.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_radio_social_canary_20260514")
GENERIC_TITLES = {"genres", "cn", "节目", "programs", "shows", "all labels", "all partners", "all dj/artists"}
MUSIC_DOMAINS = [
    "soundcloud.com",
    "bandcamp.com",
    "bilibili.com",
    "youtube.com",
    "youtu.be",
    "mixcloud.com",
    "spotify.com",
    "music.163.com",
    "music.qq.com",
]
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    errors = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                errors.append({"line": idx, "error": str(exc)})
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                errors.append({"line": idx, "error": "row is not an object"})
    return rows, errors


def read_error_sidecar(input_path: Path) -> list[dict[str, Any]]:
    sidecar = input_path.with_suffix(input_path.suffix + ".errors.json")
    if not sidecar.exists():
        return []
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    return payload.get("errors") if isinstance(payload.get("errors"), list) else []


def domain(url: str) -> str:
    return urlparse(url).netloc.casefold().replace("www.", "")


def is_music_url(url: str) -> bool:
    host = domain(url)
    path = urlparse(url).path.casefold()
    return any(item in host for item in MUSIC_DOMAINS) or path.endswith(AUDIO_EXTENSIONS)


def validate_row(row: dict[str, Any]) -> list[str]:
    errors = []
    required = ["source_family", "page_url", "page_type", "title", "snapshot_length", "body_excerpt", "fetched_at"]
    for field in required:
        value = row.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"missing {field}")
    try:
        snapshot_length = int(row.get("snapshot_length") or 0)
    except (TypeError, ValueError):
        errors.append("snapshot_length not numeric")
    else:
        if snapshot_length < 500:
            errors.append("snapshot_length below 500")
    page_type = str(row.get("page_type") or "")
    title = str(row.get("title") or "").strip().casefold()
    if page_type in {"show", "profile"} and title in GENERIC_TITLES:
        errors.append(f"generic {page_type} title")
    if not isinstance(row.get("music_links"), list):
        errors.append("music_links not list")
    if not isinstance(row.get("outbound_links"), list):
        errors.append("outbound_links not list")
    return errors


def build_report(input_path: Path) -> dict[str, Any]:
    rows, parse_errors = read_jsonl(input_path)
    station_errors = read_error_sidecar(input_path)
    by_station: dict[str, Any] = {}
    row_errors = []
    music_links = set()
    outbound_links = set()
    station_counts: dict[str, Counter[str]] = defaultdict(Counter)
    station_music: Counter[str] = Counter()
    for idx, row in enumerate(rows, start=1):
        station = str(row.get("source_family") or "unknown")
        station_counts[station][str(row.get("page_type") or "unknown")] += 1
        for error in validate_row(row):
            row_errors.append({"row": idx, "station": station, "error": error, "url": row.get("page_url")})
        for url in row.get("music_links") or []:
            if is_music_url(str(url)):
                music_links.add(str(url))
                station_music[station] += 1
        for url in row.get("outbound_links") or []:
            outbound_links.add(str(url))
    for station, counts in station_counts.items():
        by_station[station] = {
            "rows": sum(counts.values()),
            "page_types": dict(counts),
            "music_link_refs": station_music.get(station, 0),
        }
    failed_stations = sorted({str(item.get("station")) for item in station_errors if item.get("station")})
    errors = []
    if parse_errors:
        errors.append("jsonl_parse_errors")
    if row_errors:
        errors.append("row_schema_errors")
    decision = "p1_canary_ready_for_next_small_wave"
    if station_errors or errors:
        decision = "p1_canary_partial_needs_fix"
    warnings = []
    if "cdcr" in failed_stations:
        warnings.append("cdcr requires retry or alternate lightweight fetch path")
    if "baihui" in by_station and by_station.get("baihui", {}).get("music_link_refs", 0) == 0:
        warnings.append("baihui live snapshot has no exposed music links; use seed crosscheck for direct mp3 validation")
    return {
        "schema_version": "stage7_p1_radio_social_canary_summary.v1",
        "generated_at": now_iso(),
        "input": str(input_path),
        "ok": not errors and not station_errors,
        "decision": decision,
        "rows": len(rows),
        "by_station": by_station,
        "unique_music_links": len(music_links),
        "unique_outbound_links": len(outbound_links),
        "station_errors": station_errors,
        "failed_stations": failed_stations,
        "missing_stations": [],
        "parse_errors": parse_errors,
        "row_errors": row_errors,
        "warnings": warnings,
        "writes": "reports_only",
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# P1 Radio/Social Canary QA",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- input: `{report['input']}`",
        f"- rows: `{report['rows']}`",
        f"- unique_music_links: `{report['unique_music_links']}`",
        f"- unique_outbound_links: `{report['unique_outbound_links']}`",
        "",
        "## By Station",
        "",
    ]
    for station, item in sorted(report["by_station"].items()):
        lines.append(
            f"- `{station}`: rows=`{item['rows']}`, page_types=`{json.dumps(item['page_types'], ensure_ascii=False)}`, "
            f"music_link_refs=`{item['music_link_refs']}`"
        )
    lines.extend(["", "## Station Errors", ""])
    if report["station_errors"]:
        for item in report["station_errors"]:
            lines.append(f"- `{item.get('station')}`: `{item.get('error_type')}` `{item.get('error')}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Row Errors", ""])
    if report["row_errors"]:
        for item in report["row_errors"][:30]:
            lines.append(f"- row `{item['row']}` `{item['station']}`: `{item['error']}` `{item.get('url')}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    warnings = [item for item in report["warnings"] if item]
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- No production graph write.",
            "- No production consumer publish.",
            "- No paid API call.",
            "- No D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = build_report(args.input)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "radio_social_canary_summary.json", report)
    write_markdown(args.out_dir / "radio_social_canary_summary.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "rows": report["rows"],
                "failed_stations": report["failed_stations"],
                "row_errors": len(report["row_errors"]),
                "report": str(args.out_dir / "radio_social_canary_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
