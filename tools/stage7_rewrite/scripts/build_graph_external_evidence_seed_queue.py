#!/usr/bin/env python3
"""Build a report-only external evidence seed queue from the current graph stable rows.

The queue is the handoff between the verified graph marker and bounded public
network/social evidence tools. It does not fetch URLs, call models, spend paid
API budget, write graph/vector stores, export cookies, or scan D:.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_STABLE = Path(
    "reports/stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/stable_articles.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/graph_external_evidence_seed_queue_47k_plus_paid_20260518")
SCHEMA_VERSION = "stage7_graph_external_evidence_seed_queue.v1"

URL_RE = re.compile(r"https?://[^\s<>'\"）)]+", re.I)
HANDLE_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9_][A-Za-z0-9_.-]{1,40})")
ASCII_HANDLEISH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,40}$")
GENERIC_ENTITY_NAMES = {
    "dj",
    "live",
    "club",
    "bar",
    "party",
    "music",
    "电子音乐",
    "演出",
    "活动",
    "门票",
}
SOCIAL_HOST_HINTS = {
    "instagram.com",
    "soundcloud.com",
    "bandcamp.com",
    "linktr.ee",
    "linktree.com",
    "residentadvisor.net",
    "ra.co",
    "youtube.com",
    "youtu.be",
    "xiaohongshu.com",
    "weibo.com",
    "bilibili.com",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def compact(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def cjk_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def latin_count(text: str) -> int:
    return sum(1 for char in text if ("a" <= char.lower() <= "z"))


def meaningful_count(text: str) -> int:
    return cjk_count(text) + latin_count(text) + sum(1 for char in text if char.isdigit())


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:24]


def normalize_subject(text: str) -> str:
    return compact(text, 100).casefold()


def normalize_url(url: str) -> str:
    raw = compact(url, 500)
    return raw.rstrip(".,;:!?，。；：！？").strip()


def is_social_or_music_url(url: str) -> bool:
    lowered = normalize_url(url).casefold()
    return any(host in lowered for host in SOCIAL_HOST_HINTS)


def read_jsonl(path: Path, max_articles: int = 0) -> Iterable[dict[str, Any]]:
    reject_broad_d_path(path, "stable_jsonl")
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for idx, line in enumerate(handle, start=1):
            if max_articles > 0 and idx > max_articles:
                break
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                yield value


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


def entity_name_ok(name: str) -> bool:
    raw = compact(name, 100)
    if meaningful_count(raw) < 2 or len(raw) > 80:
        return False
    return raw.casefold() not in GENERIC_ENTITY_NAMES


def text_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from text_values(item)


def seed_template(seed_family: str, subject_key: str, row: dict[str, Any]) -> dict[str, Any]:
    article_uid = compact(row.get("article_uid"), 200)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "seed_id": "",
        "seed_family": seed_family,
        "subject_key": subject_key,
        "source_article_uid": article_uid,
        "source_article_id": compact(row.get("article_id"), 120),
        "source_account": compact(row.get("source_account"), 120),
        "source_title": compact(row.get("title"), 200),
        "support_count": 1,
        "evidence_articles": [
            {
                "article_uid": article_uid,
                "title": compact(row.get("title"), 160),
                "source_account": compact(row.get("source_account"), 120),
            }
        ],
        "accepted_for_graph": False,
        "review_status": "seed_only_needs_source_backed_evidence",
        "safety": {
            "report_only": True,
            "no_network_call_yet": True,
            "no_cookie_or_token_export": True,
            "no_account_action": True,
            "no_db_write": True,
            "no_paid_api": True,
        },
    }


def merge_seed(seeds: dict[tuple[str, str], dict[str, Any]], seed: dict[str, Any]) -> None:
    key = (seed["seed_family"], seed["subject_key"])
    existing = seeds.get(key)
    if existing is None:
        seed["seed_id"] = stable_id(seed["seed_family"], seed["subject_key"])
        seeds[key] = seed
        return
    existing["support_count"] += 1
    if len(existing["evidence_articles"]) < 5:
        existing["evidence_articles"].append(seed["evidence_articles"][0])
    existing["priority"] = min(100, max(int(existing.get("priority") or 0), int(seed.get("priority") or 0)) + 1)


def build_url_seed(url: str, row: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_url(url)
    seed = seed_template("url_evidence", normalized.casefold(), row)
    seed.update(
        {
            "url": normalized,
            "subject_name": "",
            "query": "",
            "priority": 92 if is_social_or_music_url(normalized) else 72,
            "suggested_layers": [
                "http_fast",
                "scrapling_if_static_blocked",
                "lightpanda_or_opencli_if_js_or_existing_browser_state",
            ],
            "reason": "URL found in current stable graph evidence text.",
        }
    )
    return seed


def build_handle_seed(handle: str, row: dict[str, Any], subject_name: str = "") -> dict[str, Any]:
    normalized = handle.strip("@").strip()
    seed = seed_template("handle_candidate", normalized.casefold(), row)
    seed.update(
        {
            "handle": normalized,
            "subject_name": compact(subject_name, 120),
            "query": normalized,
            "priority": 84,
            "suggested_layers": ["maigret_breadth", "public_social_link_validation", "identity_crosscheck_review"],
            "reason": "Handle-like token found in current graph evidence.",
        }
    )
    return seed


def build_entity_seed(entity: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    name = compact(entity.get("name"), 120)
    if not entity_name_ok(name):
        return None
    aliases = [compact(item, 100) for item in entity.get("aliases") or [] if compact(item, 100)]
    confidence = entity.get("confidence")
    try:
        confidence_num = float(confidence)
    except (TypeError, ValueError):
        confidence_num = 0.0
    type_name = compact(entity.get("type"), 80)
    subject_key = normalize_subject(name)
    seed = seed_template("entity_search", subject_key, row)
    seed.update(
        {
            "subject_name": name,
            "subject_type": type_name,
            "aliases": aliases[:8],
            "query": " ".join(part for part in [name, type_name, "electronic music"] if part),
            "priority": min(88, 50 + int(confidence_num * 20) + min(10, len(aliases) * 2)),
            "suggested_layers": [
                "bounded_search_method_audit",
                "maigret_if_handle_like_alias",
                "opencli_or_lightpanda_only_for_js_or_existing_browser_state",
                "manual_identity_review_before_graph_accept",
            ],
            "reason": "Current stable graph entity needs public corroborating evidence before new social/profile edges.",
        }
    )
    return seed


def iter_row_seeds(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
    account = compact(row.get("source_account"), 120)
    if entity_name_ok(account):
        seed = seed_template("account_search", normalize_subject(account), row)
        seed.update(
            {
                "subject_name": account,
                "query": f"{account} electronic music venue label collective",
                "priority": 70,
                "suggested_layers": ["bounded_search_method_audit", "http_fast_for_known_urls", "manual_review"],
                "reason": "WeChat source account is a graph provenance anchor.",
            }
        )
        yield seed

    for url in URL_RE.findall(" ".join(text_values(row))):
        yield build_url_seed(url, row)

    for entity in row.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        entity_seed = build_entity_seed(entity, row)
        if entity_seed:
            yield entity_seed
        subject_name = compact(entity.get("name"), 120)
        for value in text_values(entity):
            for handle_match in HANDLE_RE.findall(value):
                yield build_handle_seed(handle_match, row, subject_name=subject_name)
        for alias in entity.get("aliases") or []:
            alias_text = compact(alias, 80)
            if ASCII_HANDLEISH_RE.fullmatch(alias_text) and not alias_text.lower().startswith(("http", "www")):
                yield build_handle_seed(alias_text, row, subject_name=subject_name)


def build_seed_queue(stable_jsonl: Path, out_dir: Path, max_articles: int, max_seeds: int) -> dict[str, Any]:
    reject_broad_d_path(out_dir, "out_dir")
    seeds: dict[tuple[str, str], dict[str, Any]] = {}
    article_count = 0
    raw_seed_count = 0
    for row in read_jsonl(stable_jsonl, max_articles=max_articles):
        article_count += 1
        for seed in iter_row_seeds(row):
            raw_seed_count += 1
            merge_seed(seeds, seed)

    rows = sorted(seeds.values(), key=lambda item: (-int(item.get("priority") or 0), item["seed_family"], item["subject_key"]))
    if max_seeds > 0:
        rows = rows[:max_seeds]

    out_dir.mkdir(parents=True, exist_ok=True)
    queue_path = out_dir / "external_evidence_seed_queue.jsonl"
    write_jsonl(queue_path, rows)

    family_counts = Counter(row["seed_family"] for row in rows)
    next_layer_counts = Counter(layer for row in rows for layer in row.get("suggested_layers") or [])
    priority_buckets = Counter("90_100" if int(row.get("priority") or 0) >= 90 else "70_89" if int(row.get("priority") or 0) >= 70 else "0_69" for row in rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "graph_external_evidence_seed_queue_ready",
        "stable_jsonl": str(stable_jsonl),
        "queue_path": str(queue_path),
        "articles_scanned": article_count,
        "raw_seed_count": raw_seed_count,
        "deduped_seed_count": len(seeds),
        "written_seed_count": len(rows),
        "seed_family_counts": dict(sorted(family_counts.items())),
        "next_layer_counts": dict(sorted(next_layer_counts.items())),
        "priority_buckets": dict(sorted(priority_buckets.items())),
        "safety": {
            "report_only": True,
            "network_calls_executed": False,
            "model_calls_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "cookie_or_token_exported": False,
            "d_scan_executed": False,
        },
        "next_gate": "Run bounded HTTP-fast validation on url_evidence seeds, then Maigret breadth only on handle_candidate seeds, then OpenCLI/Lightpanda/Scrapling only for reviewed JS/static-blocked cases.",
    }
    write_json(out_dir / "seed_queue_summary.json", summary)
    write_markdown(out_dir / "seed_queue_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Graph External Evidence Seed Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- articles_scanned: `{summary['articles_scanned']}`",
        f"- raw_seed_count: `{summary['raw_seed_count']}`",
        f"- deduped_seed_count: `{summary['deduped_seed_count']}`",
        f"- written_seed_count: `{summary['written_seed_count']}`",
        f"- seed_family_counts: `{json.dumps(summary['seed_family_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- next_layer_counts: `{json.dumps(summary['next_layer_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Safety",
        "",
        "- Report-only seed queue. No network call, model call, paid API, DB write, cookie/token export, account action, or D: scan.",
        "",
        "## Next Gate",
        "",
        f"- {summary['next_gate']}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-jsonl", type=Path, default=DEFAULT_STABLE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-articles", type=int, default=0)
    parser.add_argument("--max-seeds", type=int, default=100000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_seed_queue(
        stable_jsonl=args.stable_jsonl,
        out_dir=args.out_dir,
        max_articles=args.max_articles,
        max_seeds=args.max_seeds,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "articles_scanned": summary["articles_scanned"],
                "written_seed_count": summary["written_seed_count"],
                "summary": str(args.out_dir / "seed_queue_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
