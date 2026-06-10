#!/usr/bin/env python3
"""Audit why weekly activity candidates do or do not reach mini-program publish gates."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_weekly_activity_miniprogram_api as mini_api  # noqa: E402
from validate_weekly_registries import normalize_key  # noqa: E402


DEFAULT_PACK_DIR = Path(
    r"D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_64_FROM_MAY01_QWEN27_DELTA26_20260507_2016"
)
DEFAULT_OUT_JSON = Path(__file__).resolve().parents[1] / "reports" / "weekly_miniapp_gap_audit_20260508.json"
DEFAULT_OUT_MD = Path(__file__).resolve().parents[1] / "reports" / "weekly_miniapp_gap_audit_20260508.md"
DEFAULT_REGISTRY_ROOT = Path(__file__).resolve().parents[1] / "registries"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def top(counter: Counter[str], limit: int = 20) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


def load_account_registry(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {"rows": [], "by_name": {}, "status_counts": {}}
    payload = read_json(path)
    rows = payload.get("accounts") if isinstance(payload.get("accounts"), list) else []
    by_name: dict[str, dict[str, Any]] = {}
    status_counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, dict):
            continue
        status_counts[str(row.get("status") or "")] += 1
        names = [row.get("account_name"), *(row.get("aliases") if isinstance(row.get("aliases"), list) else [])]
        for name in names:
            normalized = normalize_key(name)
            if normalized:
                by_name[normalized] = row
    return {"rows": rows, "by_name": by_name, "status_counts": dict(status_counts)}


def load_artist_registry(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {"artist_names": set(), "blocked_terms": set()}
    payload = read_json(path)
    artists = payload.get("artists") if isinstance(payload.get("artists"), list) else []
    blocked = payload.get("blocked_lineup_terms") if isinstance(payload.get("blocked_lineup_terms"), list) else []
    names: set[str] = set()
    for row in artists:
        if not isinstance(row, dict):
            continue
        for name in [row.get("canonical_name"), *(row.get("aliases") if isinstance(row.get("aliases"), list) else [])]:
            normalized = normalize_key(name)
            if normalized:
                names.add(normalized)
    return {
        "artist_names": names,
        "blocked_terms": {normalize_key(term) for term in blocked if normalize_key(term)},
    }


def match_account(account_name: str, account_registry: dict[str, Any]) -> dict[str, Any] | None:
    normalized = normalize_key(account_name)
    if not normalized:
        return None
    return account_registry["by_name"].get(normalized)


def audit_pack(
    *,
    pack_dir: Path,
    venue_registry_path: Path | None,
    account_registry_path: Path | None,
    artist_registry_path: Path | None,
    window_start: date,
    window_days: int,
    evidence_limit: int,
) -> dict[str, Any]:
    rows = [
        *mini_api.read_jsonl(pack_dir / "weekly_activity_recommendation_candidates.jsonl"),
        *mini_api.read_jsonl(pack_dir / "weekly_activity_recommendation_review_candidates.jsonl"),
    ]
    source_summary = read_json(pack_dir / "summary.json")
    venue_registry = mini_api.load_venue_registry(venue_registry_path)
    account_registry = load_account_registry(account_registry_path)
    account_city_registry = mini_api.load_account_registry(account_registry_path)
    artist_registry = load_artist_registry(artist_registry_path)
    window_end = window_start + timedelta(days=max(1, window_days) - 1)

    blocked_counts: Counter[str] = Counter()
    missing_city_accounts: Counter[str] = Counter()
    missing_time_accounts: Counter[str] = Counter()
    missing_venue_accounts: Counter[str] = Counter()
    missing_address_venues: Counter[str] = Counter()
    review_accounts: Counter[str] = Counter()
    missing_account_registry: Counter[str] = Counter()
    frequent_artist_candidates: Counter[str] = Counter()
    style_counts: Counter[str] = Counter()
    publisher_filtered_counts: Counter[str] = Counter()
    publisher_ready_items: list[dict[str, Any]] = []

    for row in rows:
        item = mini_api.build_item(
            row,
            evidence_limit=evidence_limit,
            base_url="",
            venue_registry=venue_registry,
            account_registry=account_city_registry,
        )
        account_name = mini_api.first_string(item.get("source_account_name"), item.get("account"), item.get("promoter")) or "(missing account)"
        account_row = match_account(account_name, account_registry)
        if account_row is None:
            missing_account_registry[account_name] += 1
        elif account_row.get("status") != "active":
            review_accounts[f"{account_name} [{account_row.get('status') or 'unknown'}]"] += 1

        item_ready = True
        if not item.get("city_keys"):
            blocked_counts["missing_city"] += 1
            missing_city_accounts[account_name] += 1
            item_ready = False

        in_window_dates = mini_api.windowed_date_guesses(item, window_start, window_end)
        if not in_window_dates:
            blocked_counts["outside_date_window"] += 1
            item_ready = False
        else:
            item["event_date_iso_guess"] = in_window_dates[0]
            item["event_date_iso_guesses"] = in_window_dates
            item["event_date_start"] = in_window_dates[0]
            item["event_date_end"] = in_window_dates[0]

        if not item.get("venue_name"):
            blocked_counts["missing_venue"] += 1
            missing_venue_accounts[account_name] += 1
            item_ready = False

        if not item.get("address_full"):
            announcement_reason = mini_api.non_local_announcement_reason(row, item)
            if announcement_reason:
                blocked_counts[announcement_reason] += 1
            else:
                blocked_counts["missing_address"] += 1
                missing_address_venues[mini_api.first_string(item.get("venue_name"), account_name)] += 1
            item_ready = False

        if not mini_api.first_string(item.get("time_start"), item.get("running_hours_text"), item.get("event_time_text")):
            blocked_counts["missing_time"] += 1
            missing_time_accounts[account_name] += 1
            item_ready = False

        for artist in item.get("lineup_artists") if isinstance(item.get("lineup_artists"), list) else []:
            normalized = normalize_key(artist)
            if normalized and normalized not in artist_registry["blocked_terms"]:
                frequent_artist_candidates[artist] += 1
        for style in item.get("music_styles") if isinstance(item.get("music_styles"), list) else []:
            style_counts[style] += 1

        publisher_item = dict(item)
        in_window_dates_for_publish = mini_api.windowed_date_guesses(publisher_item, window_start, window_end)
        if not in_window_dates_for_publish:
            publisher_filtered_counts["outside_date_window"] += 1
            continue
        if not publisher_item.get("city_keys"):
            publisher_filtered_counts["missing_city"] += 1
            continue
        publisher_item["event_date_iso_guess"] = in_window_dates_for_publish[0]
        publisher_item["event_date_iso_guesses"] = in_window_dates_for_publish
        publisher_item["event_date_start"] = in_window_dates_for_publish[0]
        publisher_item["event_date_end"] = in_window_dates_for_publish[0]
        publisher_item["dedupe_key"] = mini_api.published_dedupe_key(publisher_item)
        if not publisher_item.get("address_full"):
            announcement_reason = mini_api.non_local_announcement_reason(row, publisher_item)
            if announcement_reason:
                publisher_filtered_counts[announcement_reason] += 1
                continue
            publisher_filtered_counts["missing_address"] += 1
            continue
        if not publisher_item.get("running_hours_text"):
            publisher_filtered_counts["missing_time"] += 1
            continue
        publisher_ready_items.append(publisher_item)
    publisher_ready_deduped = mini_api.sort_items(mini_api.dedupe_items(publisher_ready_items))

    return {
        "schema_version": "weekly_miniapp_gap_audit.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pack_dir": str(pack_dir),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "candidate_count": len(rows),
        "ready_by_current_publish_gates": len(publisher_ready_deduped),
        "raw_ready_before_dedupe": len(publisher_ready_items),
        "blocked_counts": dict(sorted(blocked_counts.items())),
        "publisher_filtered_counts": dict(sorted(publisher_filtered_counts.items())),
        "source_summary": {
            "weekly_queue_total": source_summary.get("weekly_queue_total"),
            "matched_articles": source_summary.get("matched_articles"),
            "candidates": source_summary.get("candidates"),
            "review_candidates": source_summary.get("review_candidates"),
        },
        "account_registry": {
            "path": str(account_registry_path) if account_registry_path else "",
            "account_count": len(account_registry["rows"]),
            "status_counts": account_registry["status_counts"],
            "missing_registry_top": top(missing_account_registry),
            "review_account_candidates_top": top(review_accounts),
        },
        "manual_targets": {
            "missing_address_venues_top": top(missing_address_venues),
            "missing_city_accounts_top": top(missing_city_accounts),
            "missing_time_accounts_top": top(missing_time_accounts),
            "missing_venue_accounts_top": top(missing_venue_accounts),
            "frequent_artist_candidates_top": top(frequent_artist_candidates),
            "style_counts": top(style_counts),
        },
    }


def write_markdown(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# Weekly Miniapp Gap Audit",
        "",
        f"Generated: `{audit['generated_at']}`",
        f"Window: `{audit['window_start']}..{audit['window_end']}`",
        f"Candidates: `{audit['candidate_count']}`",
        f"Ready by current publish gates: `{audit['ready_by_current_publish_gates']}`",
        f"Raw ready before dedupe: `{audit.get('raw_ready_before_dedupe', '')}`",
        "",
        "## Blocked Counts",
        "",
        "A row can be counted in more than one blocked bucket here.",
        "",
    ]
    for key, value in audit["blocked_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Publisher Filtered Counts", ""])
    for key, value in audit.get("publisher_filtered_counts", {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Top Missing Address Venues", ""])
    for row in audit["manual_targets"]["missing_address_venues_top"][:10]:
        lines.append(f"- `{row['name']}`: `{row['count']}`")
    lines.extend(["", "## Top Missing City Accounts", ""])
    for row in audit["manual_targets"]["missing_city_accounts_top"][:10]:
        lines.append(f"- `{row['name']}`: `{row['count']}`")
    lines.extend(["", "## Top Missing Time Accounts", ""])
    for row in audit["manual_targets"].get("missing_time_accounts_top", [])[:10]:
        lines.append(f"- `{row['name']}`: `{row['count']}`")
    lines.extend(["", "## Account Registry", ""])
    lines.append(f"- accounts: `{audit['account_registry']['account_count']}`")
    for key, value in audit["account_registry"]["status_counts"].items():
        lines.append(f"- status `{key}`: `{value}`")
    lines.extend(["", "## Frequent Artist Candidates", ""])
    for row in audit["manual_targets"]["frequent_artist_candidates_top"][:20]:
        lines.append(f"- `{row['name']}`: `{row['count']}`")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit weekly mini-program publication gaps")
    parser.add_argument("--pack-dir", default=str(DEFAULT_PACK_DIR))
    parser.add_argument("--venue-registry", default=str(DEFAULT_REGISTRY_ROOT / "weekly_venues_seed.json"))
    parser.add_argument("--account-registry", default=str(DEFAULT_REGISTRY_ROOT / "weekly_accounts_seed.json"))
    parser.add_argument("--artist-registry", default=str(DEFAULT_REGISTRY_ROOT / "weekly_artists_seed.json"))
    parser.add_argument("--window-start", default="today")
    parser.add_argument("--window-days", type=int, default=8)
    parser.add_argument("--evidence-limit", type=int, default=5)
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args(argv)

    window_start = date.today() if args.window_start == "today" else date.fromisoformat(args.window_start)
    audit = audit_pack(
        pack_dir=Path(args.pack_dir),
        venue_registry_path=Path(args.venue_registry) if args.venue_registry else None,
        account_registry_path=Path(args.account_registry) if args.account_registry else None,
        artist_registry_path=Path(args.artist_registry) if args.artist_registry else None,
        window_start=window_start,
        window_days=args.window_days,
        evidence_limit=args.evidence_limit,
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(Path(args.out_md), audit)
    print(json.dumps({"out_json": str(out_json), "out_md": str(Path(args.out_md)), "ready": audit["ready_by_current_publish_gates"], "blocked_counts": audit["blocked_counts"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
