#!/usr/bin/env python3
"""Build a staging-only P1 social/mixtape edge pack from verified radio evidence.

The pack is a graph-staging input, not a graph write. It only promotes rows that
passed the seed crosscheck by default. CDCR legacy rows are excluded until a
separate fallback canary proves current public evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_ASSETS = Path("reports/p1_dj_dataset_import_20260514/radio_social_assets.jsonl")
DEFAULT_CROSSCHECK = Path("reports/p1_radio_social_seeded_canary_20260514/radio_seed_crosscheck.json")
DEFAULT_OUT_DIR = Path("reports/p1_social_edge_pack_20260514")
SCHEMA_VERSION = "stage7_social_edge_pack.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for social edge pack: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


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


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", first_text(value)).strip(" -:|")


def artist_from_title(title: str) -> str:
    text = first_text(title)
    for pattern in [
        r"\bw/\s*([^|@]+)",
        r"\bwith\s+([^|@]+)",
        r"^([^@]+)\s+@",
    ]:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return normalize_name(match.group(1))
    return normalize_name(text)


def platform_from_url(url: str) -> str:
    host = urlparse(url).netloc.casefold().replace("www.", "")
    if "soundcloud.com" in host:
        return "soundcloud"
    if "bandcamp.com" in host:
        return "bandcamp"
    if "instagram.com" in host:
        return "instagram"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "bilibili.com" in host:
        return "bilibili"
    if "baihui.live" in host:
        return "baihui_audio"
    if "byyb.live" in host:
        return "byyb_audio"
    return host or "unknown"


def edge_id(edge: dict[str, Any]) -> str:
    raw = "|".join(
        [
            edge["edge_type"],
            edge["source_family"],
            edge["subject_name"],
            edge["object_url"],
            edge["evidence_url"],
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_pack(
    assets_path: Path,
    crosscheck_path: Path,
    out_dir: Path,
    require_crawl: bool = True,
) -> dict[str, Any]:
    reject_d_path(assets_path, "assets")
    reject_d_path(crosscheck_path, "crosscheck")
    reject_d_path(out_dir, "out_dir")
    assets = {row.get("page_url"): row for row in read_jsonl(assets_path) if row.get("page_url")}
    crosscheck = read_json(crosscheck_path)
    edges: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for row in crosscheck.get("rows") or []:
        source_family = first_text(row.get("source_family"))
        page_url = first_text(row.get("page_url"))
        asset = assets.get(page_url) or {}
        if source_family == "cdcr":
            skipped["cdcr_requires_fallback_canary"] += 1
            continue
        if source_family not in {"byyb", "baihui"}:
            skipped["unsupported_source_family"] += 1
            continue
        if require_crawl and not row.get("has_crawl"):
            skipped["not_live_crawled"] += 1
            continue
        audio_checks = [item for item in row.get("audio_checks") or [] if item.get("ok")]
        if not audio_checks:
            skipped["no_verified_audio"] += 1
            continue
        subject_name = normalize_name(first_text(asset.get("artist_name"), artist_from_title(first_text(asset.get("title"), row.get("expected_title")))))
        if not subject_name:
            skipped["missing_subject_name"] += 1
            continue
        for item in audio_checks:
            edge = {
                "schema_version": SCHEMA_VERSION,
                "edge_type": "HAS_MIXTAPE",
                "source_family": source_family,
                "subject_name": subject_name,
                "object_url": item["url"],
                "object_platform": platform_from_url(item["url"]),
                "object_title": first_text(asset.get("title"), row.get("expected_title")),
                "evidence_url": page_url,
                "evidence_title": first_text(row.get("crawl_title"), row.get("expected_title"), asset.get("title")),
                "confidence": 0.82 if row.get("title_match") else 0.72,
                "verification_status": "seed_crosschecked",
                "provenance": {
                    "legacy_asset_path": asset.get("raw_source_path", ""),
                    "crosscheck_report": str(crosscheck_path),
                    "has_live_crawl": bool(row.get("has_crawl")),
                    "title_match": bool(row.get("title_match")),
                    "audio_status_code": item.get("status_code"),
                },
            }
            edge["edge_id"] = edge_id(edge)
            edges.append(edge)
        if source_family == "byyb":
            for url in asset.get("social_links") or []:
                if not url:
                    continue
                edge = {
                    "schema_version": SCHEMA_VERSION,
                    "edge_type": "HAS_PROFILE",
                    "source_family": source_family,
                    "subject_name": subject_name,
                    "object_url": url,
                    "object_platform": platform_from_url(url),
                    "object_title": "",
                    "evidence_url": page_url,
                    "evidence_title": first_text(row.get("crawl_title"), row.get("expected_title"), asset.get("title")),
                    "confidence": 0.72,
                    "verification_status": "seed_crosschecked",
                    "provenance": {
                        "legacy_asset_path": asset.get("raw_source_path", ""),
                        "crosscheck_report": str(crosscheck_path),
                        "has_live_crawl": bool(row.get("has_crawl")),
                        "title_match": bool(row.get("title_match")),
                    },
                }
                edge["edge_id"] = edge_id(edge)
                edges.append(edge)
    # Deduplicate deterministic edge IDs while preserving first provenance.
    deduped = []
    seen = set()
    for edge in edges:
        if edge["edge_id"] in seen:
            continue
        seen.add(edge["edge_id"])
        deduped.append(edge)
    edge_counts = Counter(edge["edge_type"] for edge in deduped)
    source_counts = Counter(edge["source_family"] for edge in deduped)
    out_dir.mkdir(parents=True, exist_ok=True)
    edge_path = out_dir / "social_edge_pack.jsonl"
    write_jsonl(edge_path, deduped)
    summary = {
        "schema_version": "stage7_social_edge_pack_summary.v1",
        "generated_at": now_iso(),
        "ok": bool(deduped),
        "decision": "social_edge_pack_staging_ready" if deduped else "social_edge_pack_empty",
        "assets_path": str(assets_path),
        "crosscheck_path": str(crosscheck_path),
        "edge_path": str(edge_path),
        "edges": len(deduped),
        "edge_counts": dict(edge_counts),
        "source_counts": dict(source_counts),
        "skipped": dict(skipped),
        "require_crawl": require_crawl,
        "writes": "reports_only",
    }
    write_json(out_dir / "social_edge_pack_summary.json", summary)
    write_markdown(out_dir / "social_edge_pack_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# P1 Social Edge Pack",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- ok: `{summary['ok']}`",
        f"- decision: `{summary['decision']}`",
        f"- edges: `{summary['edges']}`",
        f"- edge_path: `{summary['edge_path']}`",
        f"- edge_counts: `{json.dumps(summary['edge_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- source_counts: `{json.dumps(summary['source_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- skipped: `{json.dumps(summary['skipped'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Decision",
        "",
        "- Staging pack only.",
        "- CDCR is excluded until a fallback canary passes.",
        "- Do not write Neo4j production or consumer release from this artifact directly.",
        "",
        "## Safety",
        "",
        "- Reports only.",
        "- No graph/vector/DB write.",
        "- No paid API.",
        "- No D: scan.",
        "- No publish.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    summary = build_pack(args.assets, args.crosscheck, args.out_dir, not args.allow_uncrawled_audio)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "edges": summary["edges"],
                "edge_counts": summary["edge_counts"],
                "summary": str(args.out_dir / "social_edge_pack_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--crosscheck", type=Path, default=DEFAULT_CROSSCHECK)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--allow-uncrawled-audio", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
