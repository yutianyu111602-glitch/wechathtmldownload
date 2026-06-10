#!/usr/bin/env python3
"""Build a source-preserving Atlas activity sidecar from weekly current.json.

This bridge is intentionally not the generic Stage7 graph extractor. It keeps
the weekly mini-program's rich activity fields before any graph projection so a
later Atlas DB merge can preserve source-backed date, time, venue, lineup,
ticketing, description, and provenance fields.

The script is local-only. It does not perform network, LLM, deploy, graph,
vector, or source database writes. Raw source URLs are hashed and never written
to the public JSONL/SQLite outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.weekly_atlas_bridge.snapshot import load_current_items  # noqa: E402


SCHEMA_VERSION = "atlas_activity_source_sidecar.v1"
EVENT_SCHEMA_VERSION = "atlas_activity_event.v1"
EVIDENCE_SCHEMA_VERSION = "evidence_ref.v1.1"
PROV_SCHEMA_VERSION = "prov_lite.v1"

RAW_URL_RE = re.compile(r"https?://|www\.|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|qpic\.cn", re.I)
OPENID_RE = re.compile(r"(?i)([?&])openid=[^&]*(&|$)|\bopenid=[^&\s]*")

PRESERVED_FIELDS = [
    "title",
    "title_display",
    "event_date_text",
    "event_date_start",
    "event_date_end",
    "event_time_text",
    "time_start",
    "time_end",
    "venue_name",
    "venue_id",
    "address",
    "city",
    "city_key",
    "city_name",
    "lineup_artists",
    "lineup",
    "music_styles",
    "genres",
    "price",
    "price_text",
    "ticketing_text",
    "description_original_lines",
    "dj_bio_lines",
    "evidence",
    "source_action",
    "source_article",
    "post_date",
    "source_published_at",
    "source_account_name",
    "account_key",
]

FIELD_EVIDENCE_PATHS = [
    "title",
    "event_date_text",
    "event_time_text",
    "venue_name",
    "address",
    "lineup_artists",
    "music_styles",
    "price",
    "ticketing_text",
    "description_original_lines",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def text(value: Any) -> str:
    return str(value or "").strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    blob = "\u241f".join(text(part) for part in parts if text(part))
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def clean_text(value: str, *, limit: int | None = None) -> str:
    cleaned = OPENID_RE.sub("[openid_sanitized]", value)
    cleaned = RAW_URL_RE.sub("[url_sanitized]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if limit is not None and len(cleaned) > limit:
        return cleaned[: limit - 1].rstrip() + "..."
    return cleaned


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_value(val) for key, val in value.items() if str(key) != "url"}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return clean_text(value)
    return value


def as_list(value: Any, *, limit: int | None = None) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        item = clean_text(text(raw))
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out


def compact_json(value: Any) -> str:
    return json.dumps(sanitize_value(value), ensure_ascii=False, separators=(",", ":"))


def source_map_default_path(current_path: Path) -> Path | None:
    manifest_path = current_path.parent / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        for key in ("static_source_url_map_path", "source_url_map_path"):
            candidate = manifest.get(key)
            if candidate and Path(candidate).exists():
                return Path(candidate)
    candidate = current_path.parent / "source_actions" / "source_url_map.json"
    if candidate.exists():
        return candidate
    return None


def load_source_map(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def source_hash_from_item(item: dict[str, Any]) -> str:
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    return text(
        source_action.get("url_hash")
        or source_article.get("url_hash")
        or item.get("source_url_hash")
        or ""
    )


def source_url_hash(source_hash: str, source_map: dict[str, Any]) -> str:
    sources = source_map.get("sources") if isinstance(source_map.get("sources"), dict) else {}
    mapped = sources.get(source_hash) if source_hash and isinstance(sources, dict) else None
    url = ""
    if isinstance(mapped, dict):
        url = text(mapped.get("url"))
    elif isinstance(mapped, str):
        url = text(mapped)
    if not url:
        return f"urlhash:{source_hash}" if source_hash else ""
    cleaned = OPENID_RE.sub("", url).strip()
    return f"sha256:{sha256_text(cleaned)}"


def token_hash_from_source(source_hash: str, source_map: dict[str, Any]) -> str:
    sources = source_map.get("sources") if isinstance(source_map.get("sources"), dict) else {}
    mapped = sources.get(source_hash) if source_hash and isinstance(sources, dict) else None
    url = mapped.get("url") if isinstance(mapped, dict) else mapped if isinstance(mapped, str) else ""
    url_text = text(url)
    if "/s/" not in url_text:
        return ""
    token = url_text.split("/s/", 1)[1].split("?", 1)[0].split("#", 1)[0]
    return f"sha256:{sha256_text(token)}" if token else ""


def item_identity(item: dict[str, Any]) -> str:
    return text(item.get("event_id") or item.get("id") or item.get("queue_id") or item.get("dedupe_key"))


def build_activity_event(
    item: dict[str, Any],
    *,
    publish_package: str,
    source_map: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    event_id = item_identity(item)
    source_hash = source_hash_from_item(item)
    row = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "activity_event_id": stable_id("activity_event", publish_package, event_id),
        "event_id": event_id,
        "source_event_id": event_id,
        "publish_package": publish_package,
        "generated_at": generated_at,
        "source_url_map_key": source_hash,
        "source_url_hash": source_url_hash(source_hash, source_map),
        "source_token_hash": token_hash_from_source(source_hash, source_map),
        "field_contract": "weekly-current-rich-fields-to-atlas-activity",
        "atlas_write_status": "sidecar_only_no_source_db_mutation",
    }
    for field in PRESERVED_FIELDS:
        row[field] = sanitize_value(item.get(field))
    return row


def evidence_lines(item: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in ("evidence", "description_original_lines", "dj_bio_lines"):
        lines.extend(as_list(item.get(key), limit=20))
    title = text(item.get("title"))
    if title:
        lines.insert(0, clean_text(title))
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.casefold()
        if key not in seen:
            seen.add(key)
            out.append(line)
    return out


def values_for_field(item: dict[str, Any], field_path: str) -> list[str]:
    if field_path == "lineup_artists":
        return as_list(item.get("lineup_artists") or item.get("lineup"), limit=20)
    if field_path == "music_styles":
        return as_list(item.get("music_styles") or item.get("genres"), limit=20)
    if field_path == "price":
        return as_list(item.get("price") or item.get("price_text"), limit=8)
    if field_path == "description_original_lines":
        return as_list(item.get("description_original_lines"), limit=6)
    return as_list(item.get(field_path), limit=8)


def quote_for_value(value: str, lines: list[str]) -> str:
    folded = value.casefold()
    for line in lines:
        if folded and folded in line.casefold():
            return clean_text(line, limit=240)
    return clean_text(value, limit=240)


def deterministic_confidence(field_path: str, value: str, quote: str) -> float:
    if not value:
        return 0.0
    if value.casefold() in quote.casefold():
        return 0.92
    if field_path in {"description_original_lines", "title"}:
        return 0.9
    return 0.76


def build_evidence_refs(
    item: dict[str, Any],
    *,
    activity_event_id: str,
    source_map: dict[str, Any],
    generated_at: str,
) -> list[dict[str, Any]]:
    source_hash = source_hash_from_item(item)
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    lines = evidence_lines(item)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for field_path in FIELD_EVIDENCE_PATHS:
        for idx, value in enumerate(values_for_field(item, field_path)):
            key = (field_path, value)
            if key in seen:
                continue
            seen.add(key)
            quote = quote_for_value(value, lines)
            rows.append(
                {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "evidence_ref_id": stable_id("eref", activity_event_id, field_path, idx, value),
                    "activity_event_id": activity_event_id,
                    "field_path": field_path if idx == 0 else f"{field_path}[{idx}]",
                    "field_value": clean_text(value, limit=160),
                    "support_type": "source_text",
                    "source_kind": text(source_action.get("type") or "wechat_article"),
                    "source_url_map_key": source_hash,
                    "source_url_hash": source_url_hash(source_hash, source_map),
                    "source_account_name": clean_text(text(source_article.get("account_name") or item.get("source_account_name"))),
                    "source_published_at": text(source_article.get("published_at") or item.get("source_published_at") or item.get("post_date")),
                    "quote": quote,
                    "quote_policy": "short_quote_sanitized_240_chars",
                    "ocr_span_id": "",
                    "ocr_span_status": "not_available_in_current_api",
                    "confidence": deterministic_confidence(field_path, value, quote),
                    "created_at": generated_at,
                }
            )
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(sanitize_value(row), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def create_sqlite(path: Path, events: list[dict[str, Any]], evidence_refs: list[dict[str, Any]], prov_rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE activity_events (
          activity_event_id TEXT PRIMARY KEY,
          event_id TEXT,
          publish_package TEXT,
          title TEXT,
          event_date_text_json TEXT,
          event_date_start TEXT,
          event_date_end TEXT,
          event_time_text TEXT,
          time_start TEXT,
          time_end TEXT,
          venue_name TEXT,
          venue_id TEXT,
          address TEXT,
          city_key TEXT,
          city_name TEXT,
          lineup_artists_json TEXT,
          music_styles_json TEXT,
          genres_json TEXT,
          price_json TEXT,
          ticketing_text TEXT,
          source_url_map_key TEXT,
          source_url_hash TEXT,
          source_token_hash TEXT,
          source_article_json TEXT,
          source_action_json TEXT,
          raw_event_json TEXT,
          generated_at TEXT
        );
        CREATE TABLE evidence_refs (
          evidence_ref_id TEXT PRIMARY KEY,
          activity_event_id TEXT,
          field_path TEXT,
          field_value TEXT,
          support_type TEXT,
          source_kind TEXT,
          source_url_map_key TEXT,
          source_url_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          quote TEXT,
          quote_policy TEXT,
          ocr_span_id TEXT,
          ocr_span_status TEXT,
          confidence REAL,
          created_at TEXT
        );
        CREATE INDEX idx_evidence_refs_event ON evidence_refs(activity_event_id);
        CREATE INDEX idx_evidence_refs_field ON evidence_refs(field_path);
        CREATE TABLE prov_activities (
          prov_activity_id TEXT PRIMARY KEY,
          schema_version TEXT,
          activity_type TEXT,
          generated_at TEXT,
          input_current_path TEXT,
          input_source_map_path TEXT,
          output_dir TEXT,
          summary_json TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO activity_events VALUES (
          :activity_event_id, :event_id, :publish_package, :title,
          :event_date_text_json, :event_date_start, :event_date_end,
          :event_time_text, :time_start, :time_end, :venue_name, :venue_id,
          :address, :city_key, :city_name, :lineup_artists_json,
          :music_styles_json, :genres_json, :price_json, :ticketing_text,
          :source_url_map_key, :source_url_hash, :source_token_hash,
          :source_article_json, :source_action_json, :raw_event_json, :generated_at
        )
        """,
        [
            {
                "activity_event_id": row["activity_event_id"],
                "event_id": text(row.get("event_id")),
                "publish_package": text(row.get("publish_package")),
                "title": text(row.get("title")),
                "event_date_text_json": compact_json(row.get("event_date_text") or []),
                "event_date_start": text(row.get("event_date_start")),
                "event_date_end": text(row.get("event_date_end")),
                "event_time_text": text(row.get("event_time_text")),
                "time_start": text(row.get("time_start")),
                "time_end": text(row.get("time_end")),
                "venue_name": text(row.get("venue_name")),
                "venue_id": text(row.get("venue_id")),
                "address": text(row.get("address")),
                "city_key": text(row.get("city_key") or row.get("city")),
                "city_name": text(row.get("city_name")),
                "lineup_artists_json": compact_json(row.get("lineup_artists") or row.get("lineup") or []),
                "music_styles_json": compact_json(row.get("music_styles") or []),
                "genres_json": compact_json(row.get("genres") or []),
                "price_json": compact_json(row.get("price") or []),
                "ticketing_text": text(row.get("ticketing_text")),
                "source_url_map_key": text(row.get("source_url_map_key")),
                "source_url_hash": text(row.get("source_url_hash")),
                "source_token_hash": text(row.get("source_token_hash")),
                "source_article_json": compact_json(row.get("source_article") or {}),
                "source_action_json": compact_json(row.get("source_action") or {}),
                "raw_event_json": compact_json(row),
                "generated_at": text(row.get("generated_at")),
            }
            for row in events
        ],
    )
    conn.executemany(
        """
        INSERT INTO evidence_refs VALUES (
          :evidence_ref_id, :activity_event_id, :field_path, :field_value,
          :support_type, :source_kind, :source_url_map_key, :source_url_hash,
          :source_account_name, :source_published_at, :quote, :quote_policy,
          :ocr_span_id, :ocr_span_status, :confidence, :created_at
        )
        """,
        evidence_refs,
    )
    conn.executemany(
        """
        INSERT INTO prov_activities VALUES (
          :prov_activity_id, :schema_version, :activity_type, :generated_at,
          :input_current_path, :input_source_map_path, :output_dir, :summary_json
        )
        """,
        prov_rows,
    )
    conn.commit()
    conn.close()


def scan_raw_url_leaks(paths: list[Path]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists() or path.suffix.lower() == ".sqlite":
            continue
        try:
            for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if RAW_URL_RE.search(line):
                    hits.append({"path": str(path), "line": line_no})
                    break
        except OSError:
            continue
    return hits


def build_activity_source_sidecar(
    current_path: Path,
    out_dir: Path,
    *,
    source_map_path: Path | None = None,
    publish_package: str = "",
) -> dict[str, Any]:
    generated_at = utc_now()
    items = load_current_items(current_path)
    package = publish_package or current_path.parent.name
    resolved_source_map_path = source_map_path or source_map_default_path(current_path)
    source_map = load_source_map(resolved_source_map_path)

    events = [
        build_activity_event(item, publish_package=package, source_map=source_map, generated_at=generated_at)
        for item in items
        if item_identity(item)
    ]
    evidence_refs: list[dict[str, Any]] = []
    for item, event in zip((item for item in items if item_identity(item)), events):
        evidence_refs.extend(
            build_evidence_refs(
                item,
                activity_event_id=event["activity_event_id"],
                source_map=source_map,
                generated_at=generated_at,
            )
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "atlas_activity_events.jsonl"
    evidence_path = out_dir / "atlas_activity_evidence_refs.jsonl"
    ocr_path = out_dir / "ocr_span_registry.jsonl"
    prov_path = out_dir / "prov_activities.jsonl"
    sqlite_path = out_dir / "atlas_activity_source_sidecar.sqlite"
    summary_path = out_dir / "summary.json"
    summary_md_path = out_dir / "summary.md"

    field_counts = Counter(ref["field_path"].split("[", 1)[0] for ref in evidence_refs)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": "activity_source_sidecar_built",
        "current_path": str(current_path),
        "source_map_path": str(resolved_source_map_path) if resolved_source_map_path else "",
        "publish_package": package,
        "input_items": len(items),
        "activity_events": len(events),
        "evidence_refs": len(evidence_refs),
        "ocr_span_rows": 0,
        "field_evidence_counts": dict(sorted(field_counts.items())),
        "events_with_source_url_hash": sum(1 for event in events if event.get("source_url_hash")),
        "events_with_lineup_artists": sum(1 for event in events if event.get("lineup_artists") or event.get("lineup")),
        "events_with_ticketing": sum(1 for event in events if event.get("ticketing_text") or event.get("price")),
        "events_with_description_lines": sum(1 for event in events if event.get("description_original_lines")),
        "safety": {
            "network_call_executed": False,
            "llm_call_executed": False,
            "source_db_mutated": False,
            "raw_url_written": False,
        },
        "outputs": {
            "events_jsonl": str(events_path),
            "evidence_refs_jsonl": str(evidence_path),
            "ocr_span_registry_jsonl": str(ocr_path),
            "prov_activities_jsonl": str(prov_path),
            "sqlite": str(sqlite_path),
            "summary_json": str(summary_path),
            "summary_md": str(summary_md_path),
        },
    }
    prov_rows = [
        {
            "prov_activity_id": stable_id("prov", package, current_path, generated_at),
            "schema_version": PROV_SCHEMA_VERSION,
            "activity_type": "mini_program_current_to_atlas_activity_sidecar",
            "generated_at": generated_at,
            "input_current_path": str(current_path),
            "input_source_map_path": str(resolved_source_map_path) if resolved_source_map_path else "",
            "output_dir": str(out_dir),
            "summary_json": compact_json({k: v for k, v in summary.items() if k != "outputs"}),
        }
    ]

    write_jsonl(events_path, events)
    write_jsonl(evidence_path, evidence_refs)
    write_jsonl(ocr_path, [])
    write_jsonl(prov_path, prov_rows)
    create_sqlite(sqlite_path, events, evidence_refs, prov_rows)

    leak_hits = scan_raw_url_leaks([events_path, evidence_path, ocr_path, prov_path, summary_path, summary_md_path])
    summary["safety"]["raw_url_written"] = bool(leak_hits)
    summary["raw_url_leak_hits"] = leak_hits

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_md_path.write_text(summary_markdown(summary), encoding="utf-8")
    return {"summary": summary, "events": events, "evidence_refs": evidence_refs, "prov_rows": prov_rows}


def summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas Activity Source Sidecar",
        "",
        f"- decision: `{summary['decision']}`",
        f"- input_items: `{summary['input_items']}`",
        f"- activity_events: `{summary['activity_events']}`",
        f"- evidence_refs: `{summary['evidence_refs']}`",
        f"- ocr_span_rows: `{summary['ocr_span_rows']}`",
        f"- events_with_source_url_hash: `{summary['events_with_source_url_hash']}`",
        f"- raw_url_leak_hits: `{len(summary.get('raw_url_leak_hits') or [])}`",
        f"- source_db_mutated: `{summary['safety']['source_db_mutated']}`",
        f"- llm_call_executed: `{summary['safety']['llm_call_executed']}`",
        "",
        "## Preserved Fields",
        "",
    ]
    lines.extend(f"- `{field}`" for field in PRESERVED_FIELDS)
    lines.extend(["", "## Outputs", ""])
    for key, value in summary["outputs"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--source-map", type=Path, default=None)
    parser.add_argument("--publish-package", default="")
    args = parser.parse_args(argv)

    result = build_activity_source_sidecar(
        args.current,
        args.out_dir,
        source_map_path=args.source_map,
        publish_package=args.publish_package,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result["summary"]["safety"]["raw_url_written"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
