#!/usr/bin/env python3
"""Build a public-safe Atlas participant supplement from LLM sidecars.

This script is read-only against queue/result sidecars. It never mutates source
Atlas SQLite, the public serving DB, vector stores, graph stores, or deployments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent.parent

DEFAULT_QUEUE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_llm_adjudication_queue_v2_20260522"
    / "participant_llm_queue.sqlite"
)
DEFAULT_REVIEW_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_llm_adjudication_full_review_candidates_v2_20260522"
    / "participant_llm_decisions.sqlite"
)
DEFAULT_REEXTRACT_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_llm_adjudication_full_reextract_v2_20260522"
    / "participant_llm_decisions.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_participant_public_supplement_candidate_20260522"

KNOWN_NON_PARTICIPANT_KEYS = {
    "all",
    "oil",
    "dada",
    "tag",
    "shcr",
    "byyb",
    "baihui",
    "cdcr",
    "heim",
    "loopy",
    "potent",
    "system",
    "club",
    "radio",
    "fm",
    "bar",
    "livehouse",
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
    "场地",
    "俱乐部",
    "电台",
    "酒吧",
}

PSEUDO_EVENT_NAME_KEYS = {
    "预售",
    "预售截止",
    "早鸟",
    "早鸟截止",
    "门票",
    "票价",
    "购票",
    "售票",
    "开票",
    "报名",
    "报名截止",
    "福利",
    "抽奖",
    "入场",
    "入场须知",
    "观演须知",
    "如何入场",
    "场地更换",
}
HARD_ADMIN_EVENT_TERMS = {"报名", "入门卡", "优惠时段"}
PSEUDO_EVENT_TOKEN_RE = re.compile(r"(预售|早鸟|门票|票价|购票|售票|开票|报名|福利|抽奖|入场须知|观演须知|如何入场|场地更换|截止)")
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
PLACEHOLDER_PLACE_KEYS = {
    "tba",
    "unknown",
    "待定",
    "未定",
    "未公布",
    "待公布",
}

RAW_LEAK_RE = re.compile(
    r"https?://|mp\.weixin\.qq\.com|raw\.html|archive_html_path|archive_path|C:\\(?!\")|[A-Za-z]:\\(?!\")|/mnt/|/home/|\\\\wsl",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://\S+|mp\.weixin\.qq\.com/\S+", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\wsl)[^\s\"']+", re.IGNORECASE)
LINUX_PATH_RE = re.compile(r"(?:/mnt/|/home/)[^\s\"']+", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def norm_key(value: Any) -> str:
    return norm_name(value).lower()


def parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def scrub_public_text(value: Any, max_chars: int = 360) -> str:
    text = str(value or "")
    text = URL_RE.sub("[redacted_url]", text)
    text = WINDOWS_PATH_RE.sub("[redacted_path]", text)
    text = LINUX_PATH_RE.sub("[redacted_path]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def has_product_noise_text(value: Any) -> bool:
    key = norm_key(value)
    return any(term in key for term in PRODUCT_NOISE_TERMS)


def scrub_public_place(value: Any) -> str:
    text = scrub_public_text(value)
    if norm_key(text) in PLACEHOLDER_PLACE_KEYS:
        return ""
    return text


def is_public_safe_name(name: str) -> bool:
    cleaned = norm_name(name)
    key = norm_key(cleaned)
    if len(cleaned) <= 1:
        return False
    if key in KNOWN_NON_PARTICIPANT_KEYS:
        return False
    if has_product_noise_text(cleaned):
        return False
    if RAW_LEAK_RE.search(cleaned):
        return False
    return True


def is_public_safe_event_name(name: str) -> bool:
    cleaned = norm_name(name)
    compact = re.sub(r"\s+", "", cleaned).lower()
    if not compact:
        return False
    if compact in PSEUDO_EVENT_NAME_KEYS:
        return False
    if any(term in cleaned for term in HARD_ADMIN_EVENT_TERMS):
        return False
    # Short ticketing/admin fragments are not performance-event nodes. Longer
    # titles may mention tickets while still naming the actual show, so only
    # block compact pseudo titles here.
    if len(compact) <= 12 and PSEUDO_EVENT_TOKEN_RE.search(cleaned):
        return False
    if has_product_noise_text(cleaned):
        return False
    if RAW_LEAK_RE.search(cleaned):
        return False
    return True


def accepted_names(value: Any) -> list[str]:
    parsed = parse_json(value, [])
    names: list[str] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                name = item.get("name") or item.get("participant_name")
                if name:
                    names.append(norm_name(name))
            elif isinstance(item, str):
                names.append(norm_name(item))
    return [name for name in names if name]


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def connect_output(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS participant_public_supplement (
            supplement_id TEXT PRIMARY KEY,
            queue_id TEXT NOT NULL,
            llm_lane TEXT NOT NULL,
            event_key TEXT,
            event_id TEXT,
            event_name TEXT,
            time_text TEXT,
            place TEXT,
            city TEXT,
            source_account TEXT,
            source_title TEXT,
            participant_name TEXT NOT NULL,
            participant_name_key TEXT NOT NULL,
            confidence REAL,
            relationship_basis TEXT,
            evidence_quote TEXT,
            risk_flags_json TEXT,
            source_decision_db TEXT NOT NULL,
            generated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_participant_event ON participant_public_supplement(event_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_participant_name ON participant_public_supplement(participant_name_key)")
    return conn


def supplement_id(event_key: str, event_id: str, queue_id: str, name_key: str) -> str:
    raw = "|".join([event_key or "", event_id or "", queue_id or "", name_key])
    return "participant_supplement:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def iter_decisions(path: Path, label: str) -> Iterable[sqlite3.Row]:
    if not path.exists():
        return []
    conn = connect_readonly(path)
    try:
        return conn.execute(
            """
            SELECT queue_id, llm_lane, event_id, event_name, confidence,
                   accepted_participants_json, relationship_basis, evidence_quote,
                   risk_flags_json
            FROM participant_llm_decision
            WHERE decision = 'accept' AND public_graph_ready = 1
            """
        ).fetchall()
    finally:
        conn.close()


def queue_lookup(conn: sqlite3.Connection, queue_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT queue_id, llm_lane, event_key, event_id, event_name, time_text,
               place, city, source_account, source_title
        FROM participant_llm_queue
        WHERE queue_id = ?
        """,
        (queue_id,),
    ).fetchone()


def build_supplement(args: argparse.Namespace) -> dict[str, Any]:
    queue_db = Path(args.queue_db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "participant_public_supplement.jsonl"
    sqlite_path = out_dir / "participant_public_supplement.sqlite"
    if sqlite_path.exists():
        sqlite_path.unlink()
    if jsonl_path.exists():
        jsonl_path.unlink()

    decision_sources = [
        ("review", Path(args.review_db)),
        ("reextract", Path(args.reextract_db)),
    ]
    generated_at = now_iso()
    counters: Counter[str] = Counter()
    lane_counts: Counter[str] = Counter()
    filtered_counts: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    rows_out: list[dict[str, Any]] = []

    queue_conn = connect_readonly(queue_db)
    out_conn = connect_output(sqlite_path)
    try:
        for label, decision_db in decision_sources:
            decisions = list(iter_decisions(decision_db, label))
            counters[f"{label}_ready_decisions"] += len(decisions)
            for decision in decisions:
                queue_row = queue_lookup(queue_conn, str(decision["queue_id"]))
                if not queue_row:
                    filtered_counts["missing_queue_row"] += 1
                    continue
                lane = str(decision["llm_lane"] or queue_row["llm_lane"] or "")
                lane_counts[f"{lane}:ready_decisions"] += 1
                accepted = accepted_names(decision["accepted_participants_json"])
                event_name = scrub_public_text(queue_row["event_name"] or decision["event_name"])
                place = scrub_public_place(queue_row["place"])
                if not is_public_safe_event_name(event_name):
                    filtered_counts["unsafe_or_pseudo_event_name"] += len(accepted)
                    continue
                if has_product_noise_text(place):
                    filtered_counts["unsafe_or_product_event_context"] += len(accepted)
                    continue
                for raw_name in accepted:
                    name = norm_name(raw_name)
                    name_key = norm_key(name)
                    if not is_public_safe_name(name):
                        filtered_counts["unsafe_or_non_participant_name"] += 1
                        continue
                    event_key = str(queue_row["event_key"] or "")
                    dedupe_key = (event_key or str(queue_row["queue_id"]), name_key)
                    if dedupe_key in seen:
                        filtered_counts["duplicate_event_participant"] += 1
                        continue
                    seen.add(dedupe_key)
                    row = {
                        "supplement_id": supplement_id(
                            event_key,
                            str(queue_row["event_id"] or decision["event_id"] or ""),
                            str(queue_row["queue_id"] or decision["queue_id"]),
                            name_key,
                        ),
                        "queue_id": str(queue_row["queue_id"]),
                        "llm_lane": lane,
                        "event_key": event_key,
                        "event_id": str(queue_row["event_id"] or decision["event_id"] or ""),
                        "event_name": event_name,
                        "time_text": scrub_public_text(queue_row["time_text"]),
                        "place": place,
                        "city": scrub_public_text(queue_row["city"]),
                        "source_account": scrub_public_text(queue_row["source_account"]),
                        "source_title": scrub_public_text(queue_row["source_title"]),
                        "participant_name": name,
                        "participant_name_key": name_key,
                        "confidence": float(decision["confidence"] or 0),
                        "relationship_basis": scrub_public_text(decision["relationship_basis"], 120),
                        "evidence_quote": scrub_public_text(decision["evidence_quote"]),
                        "risk_flags_json": json_dumps(parse_json(decision["risk_flags_json"], [])),
                        "source_decision_db": label,
                        "generated_at": generated_at,
                    }
                    rows_out.append(row)
                    lane_counts[f"{lane}:participant_rows"] += 1
        with jsonl_path.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows_out:
                fh.write(json_dumps(row) + "\n")
                out_conn.execute(
                    """
                    INSERT OR REPLACE INTO participant_public_supplement
                    (supplement_id, queue_id, llm_lane, event_key, event_id, event_name,
                     time_text, place, city, source_account, source_title, participant_name,
                     participant_name_key, confidence, relationship_basis, evidence_quote,
                     risk_flags_json, source_decision_db, generated_at)
                    VALUES
                    (:supplement_id, :queue_id, :llm_lane, :event_key, :event_id, :event_name,
                     :time_text, :place, :city, :source_account, :source_title, :participant_name,
                     :participant_name_key, :confidence, :relationship_basis, :evidence_quote,
                     :risk_flags_json, :source_decision_db, :generated_at)
                    """,
                    row,
                )
        out_conn.commit()
    finally:
        queue_conn.close()
        out_conn.close()

    leak_hits = 0
    if jsonl_path.exists():
        leak_hits = len(RAW_LEAK_RE.findall(jsonl_path.read_text(encoding="utf-8")))

    summary = {
        "generated_at": generated_at,
        "queue_db": str(queue_db),
        "review_db": str(Path(args.review_db)),
        "reextract_db": str(Path(args.reextract_db)),
        "output_jsonl": str(jsonl_path),
        "output_sqlite": str(sqlite_path),
        "ready_decisions": dict(counters),
        "participant_rows": len(rows_out),
        "lane_counts": dict(lane_counts),
        "filtered_counts": dict(filtered_counts),
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
    write_summary_md(out_dir / "summary.md", summary)
    return summary


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Participant Public Supplement Candidate",
        "",
        f"Generated: `{summary['generated_at']}`",
        f"- Participant rows: `{summary['participant_rows']}`",
        f"- Raw URL/path exposure hits: `{summary['safety']['raw_url_or_path_exposure_hits']}`",
        f"- Output JSONL: `{summary['output_jsonl']}`",
        f"- Output SQLite: `{summary['output_sqlite']}`",
        "",
        "## Lane Counts",
    ]
    for key, value in sorted(summary["lane_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## Filtered Counts")
    for key, value in sorted(summary["filtered_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## Safety")
    lines.append("- Sidecar-only. No source/public database mutation, upload, deploy, vector, or graph write was executed.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-db", default=str(DEFAULT_QUEUE_DB))
    parser.add_argument("--review-db", default=str(DEFAULT_REVIEW_DB))
    parser.add_argument("--reextract-db", default=str(DEFAULT_REEXTRACT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args()


def main() -> None:
    summary = build_supplement(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
