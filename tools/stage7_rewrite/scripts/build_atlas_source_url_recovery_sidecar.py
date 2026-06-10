#!/usr/bin/env python3
"""Recover source article URLs for the Atlas SQLite release.

The full Atlas SQLite release intentionally kept a compact article surface and
does not carry the original WeChat URLs. The original download queues and
mptext archive result files still exist locally, and the Atlas ``article_id``
is normally the WeChat short-link token. This script joins those artifacts back
into a private source-url sidecar.

It does not mutate ``atlas.sqlite`` and it does not perform network, LLM, paid
API, graph, vector, production, or secret/cookie reads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_local_sqlite_db_138102_20260521"
    / "atlas.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_source_url_recovery_20260522"
DEFAULT_QUEUE_DIRS = [
    Path(r"D:\downstream_results\stage7_rewrite\longrun\WHERE_TO_RAVE_WECHAT_SYNC_20260508"),
    Path(
        r"D:\downstream_results\stage7_rewrite\longrun\WHERE_TO_RAVE_WECHAT_SYNC_20260508"
        r"\FULL_MAP_SMART_BACKFILL_20260509"
    ),
    Path(
        r"D:\downstream_results\stage7_rewrite\longrun\WHERE_TO_RAVE_WECHAT_SYNC_20260508"
        r"\SECOND_PASS_NEW_ASSETS_20260509"
    ),
    Path(
        r"D:\downstream_results\stage7_rewrite\longrun\WHERE_TO_RAVE_WECHAT_SYNC_20260508"
        r"\SUPPLEMENTAL_VENUES_20260509"
    ),
]
QUEUE_FILE_RE = re.compile(
    r".*(ARTICLE_URLS|download_ready_queue|mptext_archive.*results|_results).*\.(jsonl|json)$",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", text(value).casefold())


def stable_id(prefix: str, *parts: Any) -> str:
    blob = "\u241f".join(text(part) for part in parts if text(part))
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def token_from_url(url: str) -> str:
    url = text(url)
    if not url:
        return ""
    for marker in ("/s/", "__biz="):
        if marker == "/s/" and marker in url:
            tail = url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0]
            return text(tail)
    return ""


def is_token(value: Any) -> bool:
    return bool(TOKEN_RE.match(text(value)))


def source_url_for_token(token: str) -> str:
    return f"https://mp.weixin.qq.com/s/{token}" if is_token(token) else ""


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def iter_json_rows(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            first = handle.read(1)
            handle.seek(0)
            if first == "[":
                payload = json.load(handle)
                if isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict):
                            yield item
                elif isinstance(payload, dict):
                    yield payload
                return
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    yield item
    except (OSError, UnicodeDecodeError):
        return


def discover_source_files(queue_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for queue_dir in queue_dirs:
        if not queue_dir.exists() or not queue_dir.is_dir():
            continue
        for child in queue_dir.iterdir():
            if not child.is_file():
                continue
            if not QUEUE_FILE_RE.match(child.name):
                continue
            resolved = child.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(child)
    files.sort(key=lambda item: str(item).casefold())
    return files


def choose_better(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return candidate
    current_score = float(current.get("_score") or 0)
    candidate_score = float(candidate.get("_score") or 0)
    winner = current
    loser = candidate
    if candidate_score > current_score:
        winner = candidate
        loser = current
    elif candidate_score == current_score:
        current_url = text(current.get("source_url"))
        candidate_url = text(candidate.get("source_url"))
        if candidate_url and not current_url:
            winner = candidate
            loser = current
        elif text(candidate.get("archive_raw_html_path")) and not text(current.get("archive_raw_html_path")):
            winner = candidate
            loser = current

    merged = dict(winner)
    for field in ("archive_raw_html_path", "capture_method", "queue_status", "source_file"):
        if not text(merged.get(field)) and text(loser.get(field)):
            merged[field] = loser[field]
    if text(winner.get("source_file")) and text(loser.get("source_file")) and winner.get("source_file") != loser.get("source_file"):
        merged["source_file"] = f"{winner['source_file']} | {loser['source_file']}"
    return merged


def queue_row_to_candidate(row: dict[str, Any], path: Path) -> dict[str, Any] | None:
    token = text(row.get("token")) or token_from_url(text(row.get("source_url")))
    if not is_token(token):
        return None
    source_url = text(row.get("source_url")) or source_url_for_token(token)
    account = text(row.get("account_key") or row.get("account_nickname") or row.get("source_account"))
    out_dir = text(row.get("out_dir"))
    archive_raw_html_path = str(Path(out_dir) / "raw.html") if out_dir else ""
    status = text(row.get("archive_status") or row.get("status"))
    score = 0.65
    if text(row.get("source_url")):
        score += 0.18
    if text(row.get("post_time") or row.get("post_date")):
        score += 0.07
    if status in {"archived", "succeeded", "ready"}:
        score += 0.05
    if archive_raw_html_path:
        score += 0.05
    return {
        "token": token,
        "source_url": source_url,
        "account_key": account,
        "title": text(row.get("title")),
        "author": text(row.get("author")),
        "cover_url": text(row.get("cover_url")),
        "post_time": text(row.get("post_time")),
        "post_date": text(row.get("post_date")),
        "discovered_at": text(row.get("discovered_at")),
        "discovery_source": text(row.get("discovery_source")),
        "asset_batch": text(row.get("asset_batch")),
        "queue_status": status,
        "capture_method": text(row.get("capture_method")),
        "archive_raw_html_path": archive_raw_html_path,
        "source_file": str(path),
        "_score": round(score, 4),
    }


def load_url_candidates(source_files: list[Path]) -> dict[str, dict[str, Any]]:
    by_token: dict[str, dict[str, Any]] = {}
    for path in source_files:
        for row in iter_json_rows(path):
            candidate = queue_row_to_candidate(row, path)
            if not candidate:
                continue
            token = candidate["token"]
            by_token[token] = choose_better(by_token.get(token), candidate)
    return by_token


def iter_atlas_articles(conn: sqlite3.Connection) -> Iterable[dict[str, Any]]:
    sql = """
        SELECT article_uid, article_id, title, source_account, entity_count, event_count, local_image_count
        FROM articles
        ORDER BY row_pk
    """
    for row in conn.execute(sql):
        yield row_dict(row)


def build_rows(db_path: Path, candidates_by_token: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    conn = connect_readonly(db_path)
    rows: list[dict[str, Any]] = []
    try:
        for article in iter_atlas_articles(conn):
            token = text(article.get("article_id"))
            candidate = candidates_by_token.get(token)
            source_url = ""
            match_basis = "missing"
            confidence = 0.0
            candidate_payload: dict[str, Any] = {}
            if candidate:
                source_url = text(candidate.get("source_url"))
                candidate_payload = {key: value for key, value in candidate.items() if not key.startswith("_")}
                same_account = norm(candidate.get("account_key")) == norm(article.get("source_account"))
                same_title = norm(candidate.get("title")) == norm(article.get("title"))
                confidence = float(candidate.get("_score") or 0.0)
                if same_account:
                    confidence += 0.04
                if same_title:
                    confidence += 0.04
                match_basis = "queue_token_exact"
                if same_account and same_title:
                    match_basis = "queue_token_account_title_exact"
                elif same_account:
                    match_basis = "queue_token_account_exact"
            elif is_token(token):
                source_url = source_url_for_token(token)
                confidence = 0.72
                match_basis = "constructed_from_article_id_token"
            rows.append(
                {
                    "source_ref_id": stable_id("source_ref", article.get("article_uid"), token),
                    "article_uid": text(article.get("article_uid")),
                    "article_id": token,
                    "source_account": text(article.get("source_account")),
                    "title": text(article.get("title")),
                    "source_url": source_url,
                    "post_time": text(candidate_payload.get("post_time")),
                    "post_date": text(candidate_payload.get("post_date")),
                    "cover_url": text(candidate_payload.get("cover_url")),
                    "archive_raw_html_path": text(candidate_payload.get("archive_raw_html_path")),
                    "source_file": text(candidate_payload.get("source_file")),
                    "match_basis": match_basis,
                    "confidence": round(min(confidence, 0.99), 4),
                    "entity_count": int(article.get("entity_count") or 0),
                    "event_count": int(article.get("event_count") or 0),
                    "local_image_count": int(article.get("local_image_count") or 0),
                    "private_internal_only": 1,
                    "public_graph_visible": 0,
                }
            )
    finally:
        conn.close()
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def write_sqlite(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE source_url_recovery_run (
              run_id TEXT PRIMARY KEY,
              generated_at TEXT NOT NULL,
              source_db TEXT NOT NULL,
              schema_version TEXT NOT NULL,
              summary_json TEXT NOT NULL,
              safety_json TEXT NOT NULL
            );
            CREATE TABLE article_source_url (
              source_ref_id TEXT PRIMARY KEY,
              article_uid TEXT NOT NULL,
              article_id TEXT,
              source_account TEXT,
              title TEXT,
              source_url TEXT,
              post_time TEXT,
              post_date TEXT,
              cover_url TEXT,
              archive_raw_html_path TEXT,
              source_file TEXT,
              match_basis TEXT,
              confidence REAL,
              entity_count INTEGER,
              event_count INTEGER,
              local_image_count INTEGER,
              private_internal_only INTEGER,
              public_graph_visible INTEGER
            );
            CREATE INDEX idx_article_source_url_uid ON article_source_url(article_uid);
            CREATE INDEX idx_article_source_url_token ON article_source_url(article_id);
            CREATE INDEX idx_article_source_url_account ON article_source_url(source_account);
            CREATE INDEX idx_article_source_url_basis ON article_source_url(match_basis);
            CREATE INDEX idx_article_source_url_post_date ON article_source_url(post_date);
            """
        )
        safety = {
            "source_sqlite_write_executed": False,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "secret_or_cookie_read_executed": False,
            "production_write_executed": False,
            "public_url_exposure_executed": False,
        }
        conn.execute(
            "INSERT INTO source_url_recovery_run VALUES (?, ?, ?, ?, ?, ?)",
            (
                stable_id("source_url_recovery_run", summary.get("generated_at"), summary.get("article_count")),
                text(summary.get("generated_at")),
                text(summary.get("source_db")),
                "atlas_source_url_recovery_sidecar.v1",
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
                json.dumps(safety, ensure_ascii=False, sort_keys=True),
            ),
        )
        columns = list(rows[0].keys()) if rows else []
        if columns:
            sql = f"INSERT INTO article_source_url ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
            conn.executemany(sql, [[row.get(column) for column in columns] for row in rows])
        conn.commit()
    finally:
        conn.close()


def build_summary(db_path: Path, out_dir: Path, rows: list[dict[str, Any]], source_files: list[Path]) -> dict[str, Any]:
    basis_counts = Counter(row["match_basis"] for row in rows)
    source_counts = Counter(text(row.get("source_account")) for row in rows if text(row.get("source_account")))
    with_url = sum(1 for row in rows if text(row.get("source_url")))
    with_queue_url = sum(1 for row in rows if row["match_basis"].startswith("queue_"))
    with_post_date = sum(1 for row in rows if text(row.get("post_date") or row.get("post_time")))
    with_archive_path = sum(1 for row in rows if text(row.get("archive_raw_html_path")))
    return {
        "schema_version": "atlas_source_url_recovery_sidecar.summary.v1",
        "generated_at": now_iso(),
        "source_db": str(db_path),
        "out_dir": str(out_dir),
        "sidecar_sqlite": str(out_dir / "atlas_source_url_recovery.sqlite"),
        "article_count": len(rows),
        "source_url_count": with_url,
        "queue_exact_url_count": with_queue_url,
        "constructed_url_count": basis_counts.get("constructed_from_article_id_token", 0),
        "missing_url_count": basis_counts.get("missing", 0),
        "post_date_count": with_post_date,
        "archive_raw_html_path_count": with_archive_path,
        "match_basis_counts": dict(basis_counts),
        "source_file_count": len(source_files),
        "source_files": [str(path) for path in source_files],
        "top_sources": [{"source_account": source, "count": count} for source, count in source_counts.most_common(30)],
        "safety": {
            "report_only": True,
            "source_sqlite_write_executed": False,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "secret_or_cookie_read_executed": False,
            "production_write_executed": False,
            "public_url_exposure_executed": False,
        },
        "next_gate": [
            "Join article_source_url to event_repair_overlay by article_uid for private evidence review.",
            "Use post_date to resolve month-day-only event times when the article publish year is reliable.",
            "Keep source_url private/internal; public graph should expose hashed evidence refs, not raw bulk URLs.",
        ],
    }


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas Source URL Recovery Sidecar",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_db: `{summary['source_db']}`",
        f"- sidecar_sqlite: `{summary['sidecar_sqlite']}`",
        "- write_status: `report_only_private_sidecar`",
        "",
        "## Coverage",
        "",
        f"- article_count: `{summary['article_count']}`",
        f"- source_url_count: `{summary['source_url_count']}`",
        f"- queue_exact_url_count: `{summary['queue_exact_url_count']}`",
        f"- constructed_url_count: `{summary['constructed_url_count']}`",
        f"- missing_url_count: `{summary['missing_url_count']}`",
        f"- post_date_count: `{summary['post_date_count']}`",
        f"- archive_raw_html_path_count: `{summary['archive_raw_html_path_count']}`",
        f"- source_file_count: `{summary['source_file_count']}`",
        "",
        "## Match Basis",
        "",
        "| Basis | Rows |",
        "|---|---:|",
    ]
    for basis, count in sorted(summary["match_basis_counts"].items()):
        lines.append(f"| `{basis}` | {count} |")
    lines.extend(["", "## Top Sources", "", "| Source | Rows |", "|---|---:|"])
    for row in summary["top_sources"][:20]:
        lines.append(f"| `{row['source_account']}` | {row['count']} |")
    lines.extend(["", "## Samples", "", "| Basis | Source | Title | URL | Date |", "|---|---|---|---|---|"])
    for row in rows[:12]:
        title = text(row.get("title"))
        if len(title) > 60:
            title = title[:57] + "..."
        lines.append(
            f"| `{row['match_basis']}` | `{row['source_account']}` | `{title}` | `{row['source_url']}` | `{row['post_date']}` |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_source_url_recovery_sidecar(db_path: Path, out_dir: Path, queue_dirs: list[Path]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_files = discover_source_files(queue_dirs)
    candidates = load_url_candidates(source_files)
    rows = build_rows(db_path, candidates)
    summary = build_summary(db_path, out_dir, rows, source_files)
    write_json(out_dir / "summary.json", summary)
    write_jsonl(out_dir / "article_source_url.jsonl", rows)
    write_markdown(out_dir / "summary.md", summary, rows)
    write_sqlite(out_dir / "atlas_source_url_recovery.sqlite", rows, summary)
    return {"summary": summary, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--queue-dir", type=Path, action="append", default=[])
    args = parser.parse_args()
    queue_dirs = args.queue_dir or DEFAULT_QUEUE_DIRS
    result = build_source_url_recovery_sidecar(args.db, args.out_dir, queue_dirs)
    print(json.dumps({"ok": True, "summary": result["summary"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
