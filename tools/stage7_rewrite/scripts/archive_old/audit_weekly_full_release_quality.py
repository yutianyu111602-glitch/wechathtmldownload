#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


LINEUP_TIME_RE = re.compile(r"\b[0-2]?\d:[0-5]\d\s*[-–—~至]\s*[0-2]?\d:[0-5]\d\b")
LINEUP_NOISE_RE = re.compile(r"地址|开始时间|活动开始|扫码|二维码|公众号|客服|购票|门票|周[一二三四五六日]|星期")
ADDRESS_NOISE_RE = re.compile(
    r"公众号|二维码|客服|咨询|加群|扫码|booking|sound|music history|there is music|https?://|www\.",
    re.I,
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def sample(samples: dict[str, list[dict[str, Any]]], key: str, item: dict[str, Any], reason: str, limit: int) -> None:
    rows = samples.setdefault(key, [])
    if len(rows) >= limit:
        return
    rows.append(
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "account": item.get("account") or item.get("source_account_name"),
            "venue": item.get("venue_name") or first_list(item.get("venue"))[:1],
            "reason": reason,
        }
    )


def source_hash(item: dict[str, Any]) -> str:
    action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    return str(action.get("url_hash") or article.get("url_hash") or "").strip()


def audit_items(items: list[dict[str, Any]], source_map: dict[str, Any], sample_limit: int) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    counts: Counter[str] = Counter()
    quality_flags: Counter[str] = Counter()
    cities: Counter[str] = Counter()
    venues: Counter[str] = Counter()
    accounts: Counter[str] = Counter()
    dates: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = {}
    source_entries = source_map.get("sources") if isinstance(source_map.get("sources"), dict) else {}

    all_lineup_values = 0
    non_empty_lineup_items = 0
    for item in items:
        item_id = str(item.get("id") or "")
        counts["items_seen"] += 1
        if not item_id:
            counts["missing_id"] += 1
            sample(samples, "missing_id", item, "empty id", sample_limit)
        if item.get("quality_status") != "READY":
            counts["not_ready"] += 1
            sample(samples, "not_ready", item, str(item.get("quality_status")), sample_limit)

        city_key = str(item.get("city_key") or "").strip()
        city_values = first_list(item.get("city"))
        if not city_key or not city_values:
            counts["missing_city"] += 1
            sample(samples, "missing_city", item, "city_key/city missing", sample_limit)
        else:
            cities[city_key] += 1

        address = str(item.get("address_full") or item.get("address") or "").strip()
        if not address:
            counts["missing_address"] += 1
            sample(samples, "missing_address", item, "address/address_full missing", sample_limit)
        elif ADDRESS_NOISE_RE.search(address):
            counts["address_noise"] += 1
            sample(samples, "address_noise", item, address[:120], sample_limit)

        event_time = str(item.get("running_hours_text") or item.get("event_time_text") or "").strip()
        if not event_time:
            counts["missing_time"] += 1
            sample(samples, "missing_time", item, "running_hours_text/event_time_text missing", sample_limit)

        event_date = str(item.get("event_date_start") or item.get("event_date_iso_guess") or "").strip()
        if not event_date:
            counts["missing_date"] += 1
            sample(samples, "missing_date", item, "event_date missing", sample_limit)
        else:
            dates[event_date] += 1
            try:
                date.fromisoformat(event_date)
            except ValueError:
                counts["invalid_date"] += 1
                sample(samples, "invalid_date", item, event_date, sample_limit)

        venue_values = first_list(item.get("venue"))
        venue_name = str(item.get("venue_name") or "").strip()
        if not venue_values and not venue_name:
            counts["missing_venue"] += 1
            sample(samples, "missing_venue", item, "venue/venue_name missing", sample_limit)
        else:
            venues[venue_name or venue_values[0]] += 1

        account = str(item.get("account") or item.get("source_account_name") or "").strip()
        if account:
            accounts[account] += 1
        else:
            counts["missing_account"] += 1

        lineup = first_list(item.get("lineup")) or first_list(item.get("lineup_artists"))
        all_lineup_values += len(lineup)
        if lineup:
            non_empty_lineup_items += 1
        else:
            counts["empty_lineup"] += 1
        for value in lineup:
            if LINEUP_TIME_RE.search(value) or LINEUP_NOISE_RE.search(value) or len(value) > 80:
                counts["lineup_noise"] += 1
                sample(samples, "lineup_noise", item, value, sample_limit)

        for flag in first_list(item.get("quality_flags")):
            quality_flags[flag] += 1

        cover = str(item.get("cover_image_url") or item.get("cover_url") or "").strip()
        if cover and not cover.startswith(("http://", "https://")):
            counts["invalid_cover_url"] += 1
            sample(samples, "invalid_cover_url", item, cover, sample_limit)

        h = source_hash(item)
        if not h:
            counts["missing_source_hash"] += 1
            sample(samples, "missing_source_hash", item, "no source hash", sample_limit)
        elif h not in source_entries:
            counts["source_map_missing"] += 1
            sample(samples, "source_map_missing", item, h, sample_limit)
        else:
            source = source_entries[h]
            url = str(source.get("url") or "")
            if not url.startswith(("http://", "https://")):
                counts["invalid_source_url"] += 1
                sample(samples, "invalid_source_url", item, url, sample_limit)

    return (
        {
            "counts": dict(counts),
            "items": len(items),
            "unique_cities": len(cities),
            "unique_venues": len(venues),
            "unique_accounts": len(accounts),
            "unique_dates": len(dates),
            "lineup_values": all_lineup_values,
            "non_empty_lineup_items": non_empty_lineup_items,
            "empty_lineup_items": counts.get("empty_lineup", 0),
            "quality_flags": dict(quality_flags),
            "top_cities": cities.most_common(20),
            "top_venues": venues.most_common(20),
            "top_accounts": accounts.most_common(20),
            "date_counts": dict(sorted(dates.items())),
            "source_map_sources": len(source_entries),
        },
        samples,
    )


def audit_llm(data_dir: Path, sample_limit: int) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    llm_dir = data_dir / "llm"
    samples: dict[str, list[dict[str, Any]]] = {}
    report_path = llm_dir / "materialize_report.json"
    summary_path = llm_dir / "weekly_summary.json"
    index_path = llm_dir / "enrichment_index.json"
    out: dict[str, Any] = {
        "materialize_report_exists": report_path.exists(),
        "weekly_summary_exists": summary_path.exists(),
        "enrichment_index_exists": index_path.exists(),
    }
    if report_path.exists():
        report = load_json(report_path)
        out["materialize_report"] = {
            "provider": report.get("provider"),
            "model": report.get("model"),
            "thinking": report.get("thinking"),
            "itemCount": report.get("itemCount"),
            "enrichRequested": report.get("enrichRequested"),
            "enrichWritten": report.get("enrichWritten"),
            "enrichSkipped": report.get("enrichSkipped"),
            "dryRun": report.get("dryRun"),
        }
    if summary_path.exists():
        summary = load_json(summary_path)
        payload = summary.get("summary") if isinstance(summary.get("summary"), dict) else {}
        out["weekly_summary"] = {
            "provider": summary.get("provider"),
            "model": summary.get("model"),
            "thinking": summary.get("thinking"),
            "itemCount": summary.get("itemCount"),
            "highlight_events": len(payload.get("highlight_events") or []),
        }
    if index_path.exists():
        index = load_json(index_path)
        enrichments = index.get("enrichments") if isinstance(index.get("enrichments"), list) else []
        missing_paths = []
        colon_paths = []
        parse_errors = []
        id_mismatches = []
        for entry in enrichments:
            rel_path = str(entry.get("path") or "")
            if ":" in rel_path:
                colon_paths.append(rel_path)
            path = data_dir / rel_path
            if not path.exists():
                missing_paths.append(rel_path)
                continue
            try:
                payload = load_json(path)
            except Exception as exc:  # noqa: BLE001 - report parser failures verbatim
                parse_errors.append({"path": rel_path, "error": str(exc)})
                continue
            if payload.get("id") != entry.get("id"):
                id_mismatches.append({"index_id": entry.get("id"), "payload_id": payload.get("id"), "path": rel_path})
        out["enrichment_index"] = {
            "provider": index.get("provider"),
            "model": index.get("model"),
            "thinking": index.get("thinking"),
            "itemCount": index.get("itemCount"),
            "enrichments": len(enrichments),
            "missing_paths": len(missing_paths),
            "colon_paths": len(colon_paths),
            "parse_errors": len(parse_errors),
            "id_mismatches": len(id_mismatches),
        }
        for key, rows in {
            "llm_missing_paths": missing_paths,
            "llm_colon_paths": colon_paths,
            "llm_parse_errors": parse_errors,
            "llm_id_mismatches": id_mismatches,
        }.items():
            if rows:
                samples[key] = rows[:sample_limit]
    return out, samples


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    item_counts = report["item_audit"]["counts"]
    llm = report["llm_audit"]
    lines = [
        f"# Weekly Full Release Quality Audit {report['generated_at'][:10]}",
        "",
        "## Summary",
        "",
        f"- release_dir: `{report['release_dir']}`",
        f"- data_dir: `{report['data_dir']}`",
        f"- items: `{report['item_audit']['items']}`",
        f"- hard_missing_city/address/time/date/venue: `{item_counts.get('missing_city', 0)}` / `{item_counts.get('missing_address', 0)}` / `{item_counts.get('missing_time', 0)}` / `{item_counts.get('missing_date', 0)}` / `{item_counts.get('missing_venue', 0)}`",
        f"- lineup_noise/address_noise/source_map_missing: `{item_counts.get('lineup_noise', 0)}` / `{item_counts.get('address_noise', 0)}` / `{item_counts.get('source_map_missing', 0)}`",
        f"- LLM materialized itemCount/index: `{llm.get('materialize_report', {}).get('itemCount')}` / `{llm.get('enrichment_index', {}).get('enrichments')}`",
        f"- LLM missing_paths/colon_paths/id_mismatches: `{llm.get('enrichment_index', {}).get('missing_paths', 0)}` / `{llm.get('enrichment_index', {}).get('colon_paths', 0)}` / `{llm.get('enrichment_index', {}).get('id_mismatches', 0)}`",
        f"- status: `{report['status']}`",
        "",
        "## Entity Coverage",
        "",
        f"- unique_cities: `{report['item_audit']['unique_cities']}`",
        f"- unique_venues: `{report['item_audit']['unique_venues']}`",
        f"- unique_accounts: `{report['item_audit']['unique_accounts']}`",
        f"- lineup_values: `{report['item_audit']['lineup_values']}`",
        f"- non_empty_lineup_items: `{report['item_audit']['non_empty_lineup_items']}`",
        f"- empty_lineup_items: `{report['item_audit']['empty_lineup_items']}`",
        f"- source_map_sources: `{report['item_audit']['source_map_sources']}`",
        "",
        "## Quality Flags",
        "",
    ]
    for key, value in sorted(report["item_audit"]["quality_flags"].items()):
        lines.append(f"- `{key}`: `{value}`")
    if not report["item_audit"]["quality_flags"]:
        lines.append("- none")
    lines.extend(["", "## Samples", ""])
    if report["samples"]:
        for key, rows in sorted(report["samples"].items()):
            lines.append(f"### {key}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(rows, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
    else:
        lines.append("No failure samples.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--source-map", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--sample-limit", type=int, default=8)
    args = parser.parse_args()

    release_dir = Path(args.release_dir)
    data_dir = Path(args.data_dir)
    current = load_json(release_dir / "current.json")
    items = current.get("items") if isinstance(current.get("items"), list) else []
    source_map = load_json(Path(args.source_map))
    item_audit, item_samples = audit_items(items, source_map, args.sample_limit)
    llm_audit, llm_samples = audit_llm(data_dir, args.sample_limit)

    hard_fail_keys = [
        "missing_id",
        "not_ready",
        "missing_city",
        "missing_address",
        "missing_time",
        "missing_date",
        "invalid_date",
        "missing_venue",
        "lineup_noise",
        "address_noise",
        "missing_source_hash",
        "source_map_missing",
        "invalid_source_url",
        "invalid_cover_url",
    ]
    llm_index = llm_audit.get("enrichment_index", {})
    llm_fail = (
        not llm_audit.get("materialize_report_exists")
        or not llm_audit.get("weekly_summary_exists")
        or not llm_audit.get("enrichment_index_exists")
        or llm_index.get("missing_paths", 0) > 0
        or llm_index.get("colon_paths", 0) > 0
        or llm_index.get("parse_errors", 0) > 0
        or llm_index.get("id_mismatches", 0) > 0
        or llm_index.get("enrichments") != len(items)
    )
    status = "PASS"
    if any(item_audit["counts"].get(key, 0) for key in hard_fail_keys) or llm_fail:
        status = "FAIL"

    report = {
        "schema_version": "weekly_full_release_quality_audit.v1",
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "release_dir": str(release_dir),
        "data_dir": str(data_dir),
        "source_map": str(args.source_map),
        "status": status,
        "item_audit": item_audit,
        "llm_audit": llm_audit,
        "samples": {**item_samples, **llm_samples},
    }
    write_json(Path(args.out_json), report)
    write_markdown(Path(args.out_md), report)
    print(json.dumps({"status": status, "items": len(items), "out_json": args.out_json, "out_md": args.out_md}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
