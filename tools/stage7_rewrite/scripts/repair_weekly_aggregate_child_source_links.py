#!/usr/bin/env python3
"""Repair aggregate child source links in an already-built weekly API package.

This fixes a narrow release-pack failure mode: parent-body aggregate children can
survive conflict repair with a source hash inherited from another aggregate child
row. The correct action for these children is to open the aggregate parent
article when no event-specific article exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


CANDIDATES = "weekly_activity_recommendation_candidates.jsonl"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def backup(path: Path, stamp: str) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{stamp}"))


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str) and entry.strip():
                    return entry.strip()
    return ""


def list_texts(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(entry).strip() for entry in value if str(entry).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize(value: Any) -> str:
    text = " ".join(list_texts(value)) if isinstance(value, list) else str(value or "")
    return re.sub(r"[\W_]+", "", text.lower(), flags=re.UNICODE)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]


def event_date(item: dict[str, Any]) -> str:
    return first_text(item.get("event_date_start"), item.get("event_date_iso_guess"), item.get("event_date_text"))


def canonical_parent_body_candidates(pack_dir: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(pack_dir / CANDIDATES)
    out: list[dict[str, Any]] = []
    for row in rows:
        if first_text(row.get("aggregation_source_kind")) != "parent_body":
            continue
        if first_text(row.get("aggregation_parent_article_id")).startswith("agg-child-"):
            continue
        if not first_text(row.get("source_url")):
            continue
        out.append(row)
    return out


def match_score(item: dict[str, Any], candidate: dict[str, Any]) -> int:
    score = 0
    if event_date(item) == first_text(candidate.get("event_date_text")):
        score += 30

    item_account = normalize(first_text(item.get("account_key"), item.get("promoter"), item.get("account")))
    candidate_account = normalize(candidate.get("account_key"))
    if item_account and candidate_account and item_account == candidate_account:
        score += 10

    item_venue = normalize(first_text(item.get("venue_name"), item.get("venue")))
    candidate_venue = normalize(first_text(candidate.get("venue")))
    if item_venue and candidate_venue and (item_venue in candidate_venue or candidate_venue in item_venue):
        score += 12

    item_lineup = normalize(item.get("lineup"))
    candidate_lineup = normalize(candidate.get("lineup"))
    if item_lineup and candidate_lineup and (item_lineup in candidate_lineup or candidate_lineup in item_lineup):
        score += 18

    item_title = normalize(item.get("title"))
    candidate_title = normalize(candidate.get("title"))
    if item_title and candidate_title and (item_title in candidate_title or candidate_title in item_title):
        score += 12
    return score


def best_match(item: dict[str, Any], candidates: list[dict[str, Any]], min_score: int) -> tuple[dict[str, Any] | None, int]:
    scored = [(row, match_score(item, row)) for row in candidates]
    scored = [(row, score) for row, score in scored if score >= min_score]
    scored.sort(key=lambda entry: entry[1], reverse=True)
    if not scored:
        return None, 0
    return scored[0]


def patch_item_source(item: dict[str, Any], target: dict[str, Any]) -> bool:
    old_hash = first_text((item.get("source_action") or {}).get("url_hash"), (item.get("source_article") or {}).get("url_hash"))
    new_hash = target["url_hash"]
    if not new_hash or old_hash == new_hash:
        return False
    source_article = dict(item.get("source_article") or {})
    source_article.update(
        {
            "url_hash": new_hash,
            "account_name": target["account_name"],
            "published_at": target["published_at"],
        }
    )
    source_action = dict(item.get("source_action") or {})
    source_action.update(
        {
            "type": "wechat_article",
            "label": "公众号",
            "available": True,
            "url_hash": new_hash,
        }
    )
    item["source_article"] = source_article
    item["source_action"] = source_action
    item["source_account_name"] = target["account_name"]
    item["source_published_at"] = target["published_at"]
    return True


def patch_nested_items(payload: Any, replacements: dict[str, dict[str, Any]]) -> int:
    changed = 0
    if isinstance(payload, dict):
        item_id = first_text(payload.get("id"), payload.get("event_id"))
        if item_id in replacements and patch_item_source(payload, replacements[item_id]):
            changed += 1
        for value in payload.values():
            changed += patch_nested_items(value, replacements)
    elif isinstance(payload, list):
        for value in payload:
            changed += patch_nested_items(value, replacements)
    return changed


def discover_json_files(api_dir: Path) -> list[Path]:
    files = [api_dir / "current.json"]
    for subdir in ("by-id", "by-city", "by-date"):
        root = api_dir / subdir
        if root.exists():
            files.extend(sorted(root.glob("*.json")))
    return [path for path in files if path.exists()]


def repair(api_dir: Path, pack_dir: Path, source_url_map: Path, *, min_score: int, write: bool) -> dict[str, Any]:
    current_path = api_dir / "current.json"
    source_map_path = source_url_map
    current = read_json(current_path)
    items = current.get("items") if isinstance(current.get("items"), list) else []
    candidates = canonical_parent_body_candidates(pack_dir)
    replacements: dict[str, dict[str, Any]] = {}
    changes: list[dict[str, Any]] = []

    for item in items:
        item_id = first_text(item.get("id"))
        if not item_id.startswith("agg-child-"):
            continue
        match, score = best_match(item, candidates, min_score)
        if not match:
            continue
        source_url = first_text(match.get("source_url"))
        new_hash = url_hash(source_url)
        old_hash = first_text((item.get("source_action") or {}).get("url_hash"), (item.get("source_article") or {}).get("url_hash"))
        if old_hash == new_hash:
            continue
        target = {
            "url_hash": new_hash,
            "url": source_url,
            "account_name": first_text(item.get("source_account_name"), item.get("account"), match.get("account_key")),
            "published_at": first_text(match.get("post_date"), item.get("source_published_at"), item.get("post_date")),
            "matched_article_id": first_text(match.get("article_id")),
            "matched_parent_article_id": first_text(match.get("aggregation_parent_article_id")),
            "score": score,
        }
        replacements[item_id] = target
        changes.append(
            {
                "id": item_id,
                "title": first_text(item.get("title")),
                "event_date": event_date(item),
                "old_hash": old_hash,
                "new_hash": new_hash,
                "new_url": source_url,
                "matched_article_id": target["matched_article_id"],
                "matched_parent_article_id": target["matched_parent_article_id"],
                "score": score,
            }
        )

    source_map = read_json(source_map_path)
    patched_files: list[str] = []
    nested_replacement_count = 0
    if write and replacements:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for path in discover_json_files(api_dir):
            payload = read_json(path)
            changed = patch_nested_items(payload, replacements)
            if changed:
                backup(path, stamp)
                write_json(path, payload)
                patched_files.append(str(path))
                nested_replacement_count += changed

        backup(source_map_path, stamp)
        sources = source_map.setdefault("sources", {})
        for item_id, target in replacements.items():
            entry = sources.setdefault(target["url_hash"], {})
            entry.update(
                {
                    "type": "wechat_article",
                    "url": target["url"],
                    "account_name": target["account_name"],
                    "published_at": target["published_at"],
                    "event_id": item_id,
                    "source_kind": "aggregate_parent_body",
                    "aggregate_parent_article_id": target["matched_parent_article_id"],
                }
            )
            event_ids = entry.setdefault("event_ids", [])
            if item_id not in event_ids:
                event_ids.append(item_id)
        source_map["source_count"] = len(sources)
        source_map.setdefault("repair_report", {})["aggregate_child_source_link_repair"] = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "changed_item_count": len(replacements),
        }
        write_json(source_map_path, source_map)
        patched_files.append(str(source_map_path))

    return {
        "api_dir": str(api_dir),
        "pack_dir": str(pack_dir),
        "source_url_map": str(source_map_path),
        "write": write,
        "min_score": min_score,
        "candidate_parent_body_count": len(candidates),
        "changed_item_count": len(changes),
        "nested_replacement_count": nested_replacement_count,
        "patched_file_count": len(patched_files),
        "patched_files": patched_files,
        "changes": changes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--source-url-map", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--min-score", type=int, default=42)
    parser.add_argument("--write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_url_map = args.source_url_map or args.api_dir / "source_actions" / "source_url_map.json"
    report = repair(args.api_dir, args.pack_dir, source_url_map, min_score=args.min_score, write=args.write)
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
