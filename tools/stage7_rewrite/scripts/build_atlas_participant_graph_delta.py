#!/usr/bin/env python3
"""Build graph-delta candidates from public-safe participant supplements.

This is a sidecar-only bridge from LLM adjudicated participants into the Atlas
relationship graph model. It does not mutate source Atlas SQLite, serving DBs,
vector stores, graph stores, uploads, or deployments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent.parent

DEFAULT_SUPPLEMENT_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_public_supplement_candidate_20260522"
    / "participant_public_supplement.sqlite"
)
DEFAULT_QUEUE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_llm_adjudication_queue_v2_20260522"
    / "participant_llm_queue.sqlite"
)
DEFAULT_BASE_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_recovered_public_v2_20260522"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_participant_graph_delta_candidate_20260522"

RAW_LEAK_RE = re.compile(
    r"https?://|mp\.weixin\.qq\.com|raw\.html|archive_html_path|archive_path|C:\\(?!\")|[A-Za-z]:\\(?!\")|/mnt/|/home/|\\\\wsl",
    re.IGNORECASE,
)
KNOWN_NON_PARTICIPANT_KEYS = {
    "guest",
    "guests",
    "special guest",
    "lineup",
    "unknown",
    "various artists",
    "tba",
    "待定",
    "嘉宾",
    "阵容",
}
PRODUCT_NOISE_TERMS = {
    "白葡萄酒",
    "红酒",
    "葡萄酒",
    "鸡尾酒",
    "酒单",
    "品酒",
    "品鉴",
    "啤酒",
    "精酿",
    "威士忌",
    "香槟",
    "cocktail",
    "beer",
    "whisky",
    "whiskey",
    "champagne",
    "tasting",
    "wine",
}
PLACEHOLDER_PLACE_KEYS = {"tba", "unknown", "待定", "未定", "未公布", "待公布"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def norm_key(value: Any) -> str:
    return norm_text(value).casefold()


def has_product_noise(value: Any) -> bool:
    key = norm_key(value)
    return any(term in key for term in PRODUCT_NOISE_TERMS)


def is_public_safe_collaborator_name(value: Any) -> bool:
    key = norm_key(value)
    if not key:
        return False
    if key in KNOWN_NON_PARTICIPANT_KEYS:
        return False
    if has_product_noise(key):
        return False
    if RAW_LEAK_RE.search(str(value or "")):
        return False
    return True


def scrub_placeholder_place(value: Any) -> str:
    cleaned = norm_text(value)
    if norm_key(cleaned) in PLACEHOLDER_PLACE_KEYS:
        return ""
    return cleaned


def stable_id(prefix: str, *parts: Any, length: int = 16) -> str:
    body = "\x1f".join(norm_text(part) for part in parts if norm_text(part))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def connect_output(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE graph_delta_event (
            event_id TEXT PRIMARY KEY,
            event_title TEXT,
            starts_at TEXT,
            time_text TEXT,
            venue_id TEXT,
            venue_name TEXT,
            city TEXT,
            source_ref_id TEXT,
            participant_delta_count INTEGER,
            exists_in_base INTEGER,
            confidence REAL
        );
        CREATE TABLE graph_delta_dj_profile (
            dj_id TEXT PRIMARY KEY,
            display_name TEXT,
            normalized_name TEXT,
            aliases_json TEXT,
            event_delta_count INTEGER,
            exists_in_base INTEGER,
            first_seen_at TEXT,
            last_seen_at TEXT,
            confidence REAL
        );
        CREATE TABLE graph_delta_dj_event (
            dj_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            starts_at TEXT,
            time_text TEXT,
            event_title TEXT,
            venue_id TEXT,
            venue_name TEXT,
            city TEXT,
            source_ref_id TEXT,
            confidence REAL,
            supplement_id TEXT NOT NULL,
            evidence_quote TEXT,
            exists_in_base INTEGER,
            PRIMARY KEY (dj_id, event_id, source_ref_id, supplement_id)
        );
        CREATE TABLE graph_delta_relation (
            src_dj_id TEXT NOT NULL,
            dst_dj_id TEXT NOT NULL,
            same_event_increment INTEGER NOT NULL,
            source_diversity_increment INTEGER NOT NULL,
            first_seen_at TEXT,
            last_seen_at TEXT,
            relation_score_increment REAL NOT NULL,
            relation_label_zh TEXT NOT NULL,
            sample_evidence_json TEXT NOT NULL,
            exists_in_base INTEGER,
            PRIMARY KEY (src_dj_id, dst_dj_id)
        );
        """
    )
    return conn


def merge_min_date(current: str, candidate: str) -> str:
    current = norm_text(current)
    candidate = norm_text(candidate)
    if not current:
        return candidate
    if not candidate:
        return current
    return min(current, candidate)


def merge_max_date(current: str, candidate: str) -> str:
    current = norm_text(current)
    candidate = norm_text(candidate)
    if not current:
        return candidate
    if not candidate:
        return current
    return max(current, candidate)


def relation_label(score: float, same_event_count: int) -> str:
    if same_event_count >= 5 or score >= 26:
        return "高频同台"
    if same_event_count >= 2:
        return "多次同台"
    return "同台出现"


def row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()} if row else {}


def load_base_sets(conn: sqlite3.Connection) -> dict[str, set[Any]]:
    return {
        "events": {row["event_id"] for row in conn.execute("SELECT event_id FROM performance_event")},
        "dj_profiles": {row["dj_id"] for row in conn.execute("SELECT dj_id FROM dj_profile")},
        "dj_events": {
            (row["dj_id"], row["event_id"])
            for row in conn.execute("SELECT dj_id, event_id FROM dj_event")
        },
        "relations": {
            (row["src_dj_id"], row["dst_dj_id"])
            for row in conn.execute("SELECT src_dj_id, dst_dj_id FROM dj_relation_rollup")
        },
    }


def load_base_profile_lookup(conn: sqlite3.Connection) -> dict[str, str]:
    lookup: dict[str, str] = {}
    available_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(dj_profile)").fetchall()
    }
    select_cols = ["dj_id"]
    if "normalized_name" in available_cols:
        select_cols.append("normalized_name")
    if "display_name" in available_cols:
        select_cols.append("display_name")
    rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM dj_profile").fetchall()
    for row in rows:
        dj_id = norm_text(row["dj_id"])
        if not dj_id:
            continue
        for col in ("normalized_name", "display_name"):
            if col in row.keys():
                key = norm_key(row[col])
                if key:
                    lookup.setdefault(key, dj_id)
    return lookup


def load_base_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM performance_event WHERE event_id = ?", (event_id,)).fetchone()
    return row_dict(row)


def load_base_event_djs(conn: sqlite3.Connection, event_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT de.dj_id, dp.display_name
        FROM dj_event de
        LEFT JOIN dj_profile dp ON dp.dj_id = de.dj_id
        WHERE de.event_id = ?
        """,
        (event_id,),
    ).fetchall()
    return [row_dict(row) for row in rows]


def load_queue_context(conn: sqlite3.Connection, queue_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT q.queue_id, q.article_context_id, a.source_ref_id, a.source_hash,
               a.source_account, a.source_title, a.post_date
        FROM participant_llm_queue q
        LEFT JOIN article_context a ON a.article_context_id = q.article_context_id
        WHERE q.queue_id = ?
        """,
        (queue_id,),
    ).fetchone()
    return row_dict(row)


def build_delta(args: argparse.Namespace) -> dict[str, Any]:
    supplement_db = Path(args.supplement_db)
    queue_db = Path(args.queue_db)
    base_serving_db = Path(args.base_serving_db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_db = out_dir / "participant_graph_delta.sqlite"
    if out_db.exists():
        out_db.unlink()

    generated_at = now_iso()
    supplement_conn = connect_readonly(supplement_db)
    queue_conn = connect_readonly(queue_db)
    base_conn = connect_readonly(base_serving_db)
    out_conn = connect_output(out_db)

    counters: Counter[str] = Counter()
    lane_counts: Counter[str] = Counter()
    base_sets = load_base_sets(base_conn)
    base_profile_lookup = load_base_profile_lookup(base_conn)
    events: dict[str, dict[str, Any]] = {}
    profiles: dict[str, dict[str, Any]] = {}
    dj_events: list[dict[str, Any]] = []
    relations: dict[tuple[str, str], dict[str, Any]] = {}
    event_participants: dict[str, dict[str, str]] = defaultdict(dict)
    event_existing_djs: dict[str, dict[str, str]] = defaultdict(dict)

    rows = supplement_conn.execute(
        """
        SELECT *
        FROM participant_public_supplement
        ORDER BY event_key, participant_name_key, queue_id
        """
    ).fetchall()
    counters["supplement_rows_seen"] = len(rows)

    for row in rows:
        item = row_dict(row)
        event_id = norm_text(item.get("event_key")) or norm_text(item.get("event_id"))
        if not event_id:
            counters["rows_skipped_missing_event_id"] += 1
            continue
        participant_name = norm_text(item.get("participant_name"))
        participant_key = norm_key(item.get("participant_name_key") or participant_name)
        if not participant_key:
            counters["rows_skipped_missing_participant"] += 1
            continue

        dj_id = base_profile_lookup.get(participant_key) or stable_id("dj", participant_key)
        queue_ctx = load_queue_context(queue_conn, norm_text(item.get("queue_id")))
        source_ref_id = norm_text(queue_ctx.get("source_ref_id")) or stable_id(
            "src",
            item.get("source_account"),
            item.get("source_title"),
            item.get("queue_id"),
        )
        base_event = load_base_event(base_conn, event_id)
        if event_id not in event_existing_djs:
            for base_dj in load_base_event_djs(base_conn, event_id):
                display_name = norm_text(base_dj.get("display_name")) or norm_text(base_dj.get("dj_id"))
                if base_dj.get("dj_id") and is_public_safe_collaborator_name(display_name):
                    event_existing_djs[event_id][base_dj["dj_id"]] = norm_text(base_dj.get("display_name")) or base_dj["dj_id"]

        venue_name = scrub_placeholder_place(norm_text(base_event.get("venue_name")) or norm_text(item.get("place")))
        event = events.setdefault(
            event_id,
            {
                "event_id": event_id,
                "event_title": norm_text(base_event.get("event_title")) or norm_text(item.get("event_name")),
                "starts_at": norm_text(base_event.get("starts_at")),
                "time_text": norm_text(base_event.get("time_text")) or norm_text(item.get("time_text")),
                "venue_id": norm_text(base_event.get("venue_id")) if venue_name else "",
                "venue_name": venue_name,
                "city": norm_text(base_event.get("city")) or norm_text(item.get("city")),
                "source_ref_id": norm_text(base_event.get("source_ref_id")) or source_ref_id,
                "participant_delta_count": 0,
                "exists_in_base": int(event_id in base_sets["events"]),
                "confidence": 0.0,
            },
        )
        event["participant_delta_count"] += 1
        event["confidence"] = max(float(event.get("confidence") or 0), float(item.get("confidence") or 0))

        profile = profiles.setdefault(
            dj_id,
            {
                "dj_id": dj_id,
                "display_name": participant_name,
                "normalized_name": participant_key,
                "aliases": set(),
                "event_ids": set(),
                "exists_in_base": int(dj_id in base_sets["dj_profiles"]),
                "first_seen_at": "",
                "last_seen_at": "",
                "confidence_values": [],
            },
        )
        profile["aliases"].add(participant_name)
        profile["event_ids"].add(event_id)
        profile["confidence_values"].append(float(item.get("confidence") or 0))
        profile["first_seen_at"] = merge_min_date(profile["first_seen_at"], event["starts_at"])
        profile["last_seen_at"] = merge_max_date(profile["last_seen_at"], event["starts_at"])
        event_participants[event_id][dj_id] = participant_name

        exists_dj_event = (dj_id, event_id) in base_sets["dj_events"]
        dj_event = {
            "dj_id": dj_id,
            "event_id": event_id,
            "starts_at": event["starts_at"],
            "time_text": event["time_text"],
            "event_title": event["event_title"],
            "venue_id": event["venue_id"],
            "venue_name": event["venue_name"],
            "city": event["city"],
            "source_ref_id": event["source_ref_id"],
            "confidence": float(item.get("confidence") or 0),
            "supplement_id": item["supplement_id"],
            "evidence_quote": norm_text(item.get("evidence_quote")),
            "exists_in_base": int(exists_dj_event),
        }
        dj_events.append(dj_event)
        lane_counts[f"{item.get('llm_lane')}:dj_event_rows"] += 1
        if exists_dj_event:
            counters["dj_event_already_in_base"] += 1
        else:
            counters["dj_event_new_candidate"] += 1

    for event_id, supplement_djs in event_participants.items():
        merged = dict(event_existing_djs.get(event_id, {}))
        merged.update(supplement_djs)
        if len(merged) < 2:
            counters["relation_events_skipped_singleton"] += 1
            continue
        event = events[event_id]
        supplement_set = set(supplement_djs)
        for a, b in combinations(sorted(merged), 2):
            if a not in supplement_set and b not in supplement_set:
                continue
            for src, dst in ((a, b), (b, a)):
                key = (src, dst)
                rel = relations.setdefault(
                    key,
                    {
                        "src_dj_id": src,
                        "dst_dj_id": dst,
                        "same_event_increment": 0,
                        "source_refs": set(),
                        "first_seen_at": "",
                        "last_seen_at": "",
                        "sample_evidence": [],
                        "exists_in_base": int(key in base_sets["relations"]),
                    },
                )
                rel["same_event_increment"] += 1
                if event["source_ref_id"]:
                    rel["source_refs"].add(event["source_ref_id"])
                rel["first_seen_at"] = merge_min_date(rel["first_seen_at"], event["starts_at"])
                rel["last_seen_at"] = merge_max_date(rel["last_seen_at"], event["starts_at"])
                if len(rel["sample_evidence"]) < 8:
                    rel["sample_evidence"].append(
                        {
                            "event_id": event_id,
                            "event_title": event["event_title"],
                            "starts_at": event["starts_at"],
                            "venue_name": event["venue_name"],
                            "city": event["city"],
                            "source_ref_id": event["source_ref_id"],
                        }
                    )

    out_conn.executemany(
        "INSERT INTO graph_delta_event VALUES (:event_id,:event_title,:starts_at,:time_text,:venue_id,:venue_name,:city,:source_ref_id,:participant_delta_count,:exists_in_base,:confidence)",
        list(events.values()),
    )
    profile_rows = []
    for profile in profiles.values():
        confidence_values = profile["confidence_values"]
        profile_rows.append(
            {
                "dj_id": profile["dj_id"],
                "display_name": profile["display_name"],
                "normalized_name": profile["normalized_name"],
                "aliases_json": json_dumps(sorted(profile["aliases"], key=str.casefold)),
                "event_delta_count": len(profile["event_ids"]),
                "exists_in_base": profile["exists_in_base"],
                "first_seen_at": profile["first_seen_at"],
                "last_seen_at": profile["last_seen_at"],
                "confidence": round(sum(confidence_values) / max(len(confidence_values), 1), 4),
            }
        )
    out_conn.executemany(
        "INSERT INTO graph_delta_dj_profile VALUES (:dj_id,:display_name,:normalized_name,:aliases_json,:event_delta_count,:exists_in_base,:first_seen_at,:last_seen_at,:confidence)",
        profile_rows,
    )
    out_conn.executemany(
        "INSERT INTO graph_delta_dj_event VALUES (:dj_id,:event_id,:starts_at,:time_text,:event_title,:venue_id,:venue_name,:city,:source_ref_id,:confidence,:supplement_id,:evidence_quote,:exists_in_base)",
        dj_events,
    )
    relation_rows = []
    for rel in relations.values():
        score = round(rel["same_event_increment"] * 4.0, 4)
        relation_rows.append(
            {
                "src_dj_id": rel["src_dj_id"],
                "dst_dj_id": rel["dst_dj_id"],
                "same_event_increment": rel["same_event_increment"],
                "source_diversity_increment": len(rel["source_refs"]),
                "first_seen_at": rel["first_seen_at"],
                "last_seen_at": rel["last_seen_at"],
                "relation_score_increment": score,
                "relation_label_zh": relation_label(score, rel["same_event_increment"]),
                "sample_evidence_json": json_dumps(rel["sample_evidence"]),
                "exists_in_base": rel["exists_in_base"],
            }
        )
    out_conn.executemany(
        "INSERT INTO graph_delta_relation VALUES (:src_dj_id,:dst_dj_id,:same_event_increment,:source_diversity_increment,:first_seen_at,:last_seen_at,:relation_score_increment,:relation_label_zh,:sample_evidence_json,:exists_in_base)",
        relation_rows,
    )
    out_conn.commit()
    out_conn.close()
    supplement_conn.close()
    queue_conn.close()
    base_conn.close()

    jsonl_paths = {
        "events": out_dir / "graph_delta_events.jsonl",
        "dj_profiles": out_dir / "graph_delta_dj_profiles.jsonl",
        "dj_events": out_dir / "graph_delta_dj_events.jsonl",
        "relations": out_dir / "graph_delta_relations.jsonl",
    }
    for path, rows_out in [
        (jsonl_paths["events"], list(events.values())),
        (jsonl_paths["dj_profiles"], profile_rows),
        (jsonl_paths["dj_events"], dj_events),
        (jsonl_paths["relations"], relation_rows),
    ]:
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows_out:
                serializable = {k: sorted(v) if isinstance(v, set) else v for k, v in row.items()}
                fh.write(json_dumps(serializable) + "\n")

    leak_hits = 0
    for path in [out_db, *jsonl_paths.values()]:
        if path.suffix == ".jsonl":
            leak_hits += len(RAW_LEAK_RE.findall(path.read_text(encoding="utf-8")))

    summary = {
        "generated_at": generated_at,
        "supplement_db": str(supplement_db),
        "queue_db": str(queue_db),
        "base_serving_db": str(base_serving_db),
        "output_sqlite": str(out_db),
        "output_jsonl": {key: str(value) for key, value in jsonl_paths.items()},
        "counts": {
            "events": len(events),
            "event_new_candidates": sum(1 for row in events.values() if not row["exists_in_base"]),
            "dj_profiles": len(profile_rows),
            "dj_profile_new_candidates": sum(1 for row in profile_rows if not row["exists_in_base"]),
            "dj_event_rows": len(dj_events),
            "dj_event_new_candidates": counters["dj_event_new_candidate"],
            "relation_rows_directed": len(relation_rows),
            "relation_new_candidates_directed": sum(1 for row in relation_rows if not row["exists_in_base"]),
        },
        "lane_counts": dict(lane_counts),
        "counters": dict(counters),
        "safety": {
            "raw_url_or_path_exposure_hits": leak_hits,
            "source_sqlite_write_executed": False,
            "production_write_executed": False,
            "deploy_or_upload_executed": False,
            "graph_vector_write_executed": False,
            "sidecar_only": True,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    write_summary(out_dir / "summary.md", summary)
    return summary


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Participant Graph Delta Candidate",
        "",
        f"Generated: `{summary['generated_at']}`",
        f"- Events: `{summary['counts']['events']}`",
        f"- New event candidates: `{summary['counts']['event_new_candidates']}`",
        f"- DJ profiles: `{summary['counts']['dj_profiles']}`",
        f"- New DJ profile candidates: `{summary['counts']['dj_profile_new_candidates']}`",
        f"- DJ-event rows: `{summary['counts']['dj_event_rows']}`",
        f"- New DJ-event candidates: `{summary['counts']['dj_event_new_candidates']}`",
        f"- Directed relation rows: `{summary['counts']['relation_rows_directed']}`",
        f"- New directed relation candidates: `{summary['counts']['relation_new_candidates_directed']}`",
        f"- Raw URL/path exposure hits: `{summary['safety']['raw_url_or_path_exposure_hits']}`",
        "",
        "## Boundary",
        "",
        "Sidecar-only. No source/public database mutation, graph/vector write, upload, or deployment was executed.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supplement-db", default=str(DEFAULT_SUPPLEMENT_DB))
    parser.add_argument("--queue-db", default=str(DEFAULT_QUEUE_DB))
    parser.add_argument("--base-serving-db", default=str(DEFAULT_BASE_SERVING_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args()


def main() -> None:
    summary = build_delta(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
