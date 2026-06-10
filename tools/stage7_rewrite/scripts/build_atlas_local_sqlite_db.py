from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STAGE7_ATLAS_DIR = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "stage7_atlas"
DEFAULT_GRAPH_VERIFY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "graph_production_promotion_all_full_llm_138102_verify_20260520"
    / "promotion_report.json"
)


def utcish_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas Local SQLite Database Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- db_path: `{report['db_path']}`",
        f"- db_bytes: `{report['db_bytes']}`",
        f"- elapsed_sec: `{report['elapsed_sec']}`",
        f"- fts_tokenizer: `{report['fts_tokenizer']}`",
        "",
        "## Counts",
        "",
        "| table | expected | actual | match |",
        "| --- | ---: | ---: | --- |",
    ]
    expected = report["expected_counts"]
    actual = report["actual_counts"]
    matches = report["count_matches"]
    for key in ["articles", "entities", "events"]:
        lines.append(f"| {key} | {expected.get(key, '')} | {actual.get(key, '')} | {matches.get(key)} |")
    for key in [
        "identity_review_items",
        "recommendations",
        "graph_rag_answers",
        "runtime_reports",
    ]:
        lines.append(f"| {key} |  | {actual.get(key, '')} |  |")
    lines.extend(
        [
            "",
            "## Parse Errors",
            "",
            "```json",
            json.dumps(report["parse_errors"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Smoke",
            "",
            "```json",
            json.dumps(report["smoke"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Safety",
            "",
            "```json",
            json.dumps(report["safety"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    if report["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{item}`" for item in report["blockers"])
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{item}`" for item in report["warnings"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def text_preview(value: Any, limit: int = 1200) -> str:
    normalized = re.sub(r"\s+", " ", text(value))
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def int_value(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def float_value(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any] | None, dict[str, Any] | None]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield line_no, json.loads(stripped), None
            except json.JSONDecodeError as exc:
                yield line_no, None, {
                    "line_no": line_no,
                    "error": str(exc),
                    "snippet": stripped[:180],
                }


def ensure_clean_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ["", "-wal", "-shm", "-journal"]:
        target = Path(str(path) + suffix)
        if target.exists():
            target.unlink()


def detect_fts_tokenizer(conn: sqlite3.Connection) -> str:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._tokenizer_probe USING fts5(x, tokenize='trigram')")
        conn.execute("DROP TABLE temp._tokenizer_probe")
        return "trigram"
    except sqlite3.OperationalError:
        return "unicode61"


def configure_conn(conn: sqlite3.Connection) -> str:
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    return detect_fts_tokenizer(conn)


def create_schema(conn: sqlite3.Connection, fts_tokenizer: str) -> None:
    conn.executescript(
        """
        CREATE TABLE metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE articles (
          row_pk INTEGER PRIMARY KEY,
          article_id TEXT,
          article_uid TEXT,
          title TEXT,
          source_account TEXT,
          publish_time TEXT,
          publish_time_status TEXT,
          publish_time_index_status TEXT,
          city_label TEXT,
          entity_count INTEGER,
          event_count INTEGER,
          quality_grade TEXT,
          extract_version TEXT,
          input_chars INTEGER,
          local_image_count INTEGER,
          source_archived_at TEXT,
          vector_text_preview TEXT,
          raw_json TEXT
        );

        CREATE TABLE entities (
          row_pk INTEGER PRIMARY KEY,
          eid TEXT,
          name TEXT,
          type TEXT,
          city TEXT,
          source_kind TEXT,
          source_article_uid TEXT,
          confidence REAL,
          aliases_json TEXT,
          bio TEXT,
          evidence_quote TEXT,
          vector_text_preview TEXT,
          raw_json TEXT
        );

        CREATE TABLE events (
          row_pk INTEGER PRIMARY KEY,
          evid TEXT,
          name TEXT,
          place TEXT,
          city TEXT,
          time_iso TEXT,
          time_text TEXT,
          source_kind TEXT,
          source_article_uid TEXT,
          confidence REAL,
          participants_json TEXT,
          organizers_json TEXT,
          vector_text_preview TEXT,
          raw_json TEXT
        );

        CREATE TABLE identity_review_items (
          row_pk INTEGER PRIMARY KEY,
          item_id TEXT,
          queue TEXT,
          bucket TEXT,
          status TEXT,
          subject_name TEXT,
          subject_type TEXT,
          url TEXT,
          domain TEXT,
          source_account TEXT,
          source_article_uid TEXT,
          source_title TEXT,
          support_count INTEGER,
          identity_signal_score REAL,
          accepted_for_graph INTEGER,
          identity_proof INTEGER,
          graph_write_allowed INTEGER,
          review_reason TEXT,
          next_actions_json TEXT,
          signals_json TEXT,
          raw_json TEXT
        );

        CREATE TABLE recommendations (
          row_pk INTEGER PRIMARY KEY,
          item_id TEXT,
          type TEXT,
          title TEXT,
          score REAL,
          evidence_json TEXT,
          source_scores_json TEXT,
          raw_json TEXT
        );

        CREATE TABLE graph_rag_answers (
          row_pk INTEGER PRIMARY KEY,
          item_id TEXT,
          query TEXT,
          answer TEXT,
          citation_count INTEGER,
          fact_count INTEGER,
          citations_json TEXT,
          facts_json TEXT,
          status TEXT,
          raw_json TEXT
        );

        CREATE TABLE runtime_reports (
          row_pk INTEGER PRIMARY KEY,
          report_name TEXT NOT NULL,
          path TEXT,
          decision TEXT,
          ok INTEGER,
          summary_json TEXT,
          raw_json TEXT
        );
        """
    )
    conn.execute(
        f"CREATE VIRTUAL TABLE article_fts USING fts5(row_pk UNINDEXED, article_uid, title, source_account, vector_text_preview, tokenize='{fts_tokenizer}')"
    )
    conn.execute(
        f"CREATE VIRTUAL TABLE entity_fts USING fts5(row_pk UNINDEXED, eid UNINDEXED, name, type, city, source_article_uid, vector_text_preview, tokenize='{fts_tokenizer}')"
    )
    conn.execute(
        f"CREATE VIRTUAL TABLE event_fts USING fts5(row_pk UNINDEXED, evid UNINDEXED, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview, tokenize='{fts_tokenizer}')"
    )


ARTICLE_SQL = """
INSERT INTO articles (
  row_pk, article_id, article_uid, title, source_account, publish_time,
  publish_time_status, publish_time_index_status, city_label, entity_count,
  event_count, quality_grade, extract_version, input_chars, local_image_count,
  source_archived_at, vector_text_preview, raw_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

ENTITY_SQL = """
INSERT INTO entities (
  row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
  aliases_json, bio, evidence_quote, vector_text_preview, raw_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

EVENT_SQL = """
INSERT INTO events (
  row_pk, evid, name, place, city, time_iso, time_text, source_kind,
  source_article_uid, confidence, participants_json, organizers_json,
  vector_text_preview, raw_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def build_article(row_pk: int, row: dict[str, Any], include_raw_json: bool) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    preview = text_preview(row.get("vector_text"))
    raw = compact_json(row) if include_raw_json else ""
    article_uid = text(row.get("article_uid"))
    title = text(row.get("title"))
    source_account = text(row.get("source_account"))
    return (
        (
            row_pk,
            text(row.get("article_id")),
            article_uid,
            title,
            source_account,
            text(row.get("publish_time")),
            text(row.get("publish_time_status")),
            text(row.get("publish_time_index_status")),
            text(row.get("city_label")),
            int_value(row.get("entity_count")),
            int_value(row.get("event_count")),
            text(row.get("quality_grade")),
            text(row.get("extract_version")),
            int_value(row.get("input_chars")),
            int_value(row.get("local_image_count")),
            text(row.get("source_archived_at")),
            preview,
            raw,
        ),
        (row_pk, article_uid, title, source_account, preview),
    )


def build_entity(row_pk: int, row: dict[str, Any], include_raw_json: bool) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    preview = text_preview(row.get("vector_text"))
    raw = compact_json(row) if include_raw_json else ""
    name = text(row.get("name"))
    type_name = text(row.get("type"))
    city = text(row.get("city"))
    source_article_uid = text(row.get("source_article_uid"))
    return (
        (
            row_pk,
            text(row.get("eid")),
            name,
            type_name,
            city,
            text(row.get("source_kind")),
            source_article_uid,
            float_value(row.get("confidence")),
            compact_json(row.get("aliases") or []),
            text(row.get("bio")),
            text(row.get("evidence_quote")),
            preview,
            raw,
        ),
        (row_pk, text(row.get("eid")), name, type_name, city, source_article_uid, preview),
    )


def build_event(row_pk: int, row: dict[str, Any], include_raw_json: bool) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    preview = text_preview(row.get("vector_text"))
    raw = compact_json(row) if include_raw_json else ""
    name = text(row.get("name"))
    place = text(row.get("place"))
    city = text(row.get("city"))
    time_text = text(row.get("time_text"))
    source_article_uid = text(row.get("source_article_uid"))
    participants = row.get("participants") or []
    organizers = row.get("organizers") or []
    participants_text = " ".join(text(item) for item in participants if text(item))
    return (
        (
            row_pk,
            text(row.get("evid")),
            name,
            place,
            city,
            text(row.get("time_iso")),
            time_text,
            text(row.get("source_kind")),
            source_article_uid,
            float_value(row.get("confidence")),
            compact_json(participants),
            compact_json(organizers),
            preview,
            raw,
        ),
        (row_pk, text(row.get("evid")), name, place, city, time_text, source_article_uid, participants_text, preview),
    )


def flush_batch(conn: sqlite3.Connection, kind: str, rows: list[tuple[Any, ...]], fts_rows: list[tuple[Any, ...]]) -> None:
    if kind == "articles":
        conn.executemany(ARTICLE_SQL, rows)
        conn.executemany(
            "INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)",
            fts_rows,
        )
    elif kind == "entities":
        conn.executemany(ENTITY_SQL, rows)
        conn.executemany(
            "INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)",
            fts_rows,
        )
    elif kind == "events":
        conn.executemany(EVENT_SQL, rows)
        conn.executemany(
            "INSERT INTO event_fts(row_pk, evid, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            fts_rows,
        )
    else:
        raise ValueError(f"unknown kind: {kind}")


def insert_jsonl_table(
    conn: sqlite3.Connection,
    *,
    kind: str,
    path: Path,
    batch_size: int,
    include_raw_json: bool,
) -> dict[str, Any]:
    builders = {
        "articles": build_article,
        "entities": build_entity,
        "events": build_event,
    }
    builder = builders[kind]
    rows: list[tuple[Any, ...]] = []
    fts_rows: list[tuple[Any, ...]] = []
    parse_errors: list[dict[str, Any]] = []
    inserted = 0
    scanned = 0
    for line_no, obj, err in iter_jsonl(path):
        scanned += 1
        if err is not None:
            if len(parse_errors) < 20:
                parse_errors.append(err)
            continue
        assert obj is not None
        table_row, fts_row = builder(inserted + 1, obj, include_raw_json)
        rows.append(table_row)
        fts_rows.append(fts_row)
        inserted += 1
        if len(rows) >= batch_size:
            flush_batch(conn, kind, rows, fts_rows)
            conn.commit()
            rows.clear()
            fts_rows.clear()
    if rows:
        flush_batch(conn, kind, rows, fts_rows)
        conn.commit()
    return {
        "path": str(path),
        "scanned_nonblank_lines": scanned,
        "inserted": inserted,
        "parse_error_count": scanned - inserted,
        "parse_error_samples": parse_errors,
    }


def list_from_payload(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [item for item in payload[key] if isinstance(item, dict)]
    return []


def insert_identity_review(conn: sqlite3.Connection, path: Path, include_raw_json: bool) -> int:
    payload = read_json(path, {})
    rows = list_from_payload(payload, "items")
    values = []
    for index, row in enumerate(rows, 1):
        values.append(
            (
                index,
                text(row.get("id")),
                text(row.get("queue")),
                text(row.get("bucket")),
                text(row.get("status")),
                text(row.get("subjectName")),
                text(row.get("subjectType")),
                text(row.get("url")),
                text(row.get("domain")),
                text(row.get("sourceAccount")),
                text(row.get("sourceArticleUid")),
                text(row.get("sourceTitle")),
                int_value(row.get("supportCount")),
                float_value(row.get("identitySignalScore")),
                bool_int(row.get("acceptedForGraph")),
                bool_int(row.get("identityProof")),
                bool_int(row.get("graphWriteAllowed")),
                text(row.get("reviewReason")),
                compact_json(row.get("nextActions") or []),
                compact_json(row.get("signals") or {}),
                compact_json(row) if include_raw_json else "",
            )
        )
    conn.executemany(
        """
        INSERT INTO identity_review_items (
          row_pk, item_id, queue, bucket, status, subject_name, subject_type,
          url, domain, source_account, source_article_uid, source_title,
          support_count, identity_signal_score, accepted_for_graph,
          identity_proof, graph_write_allowed, review_reason, next_actions_json,
          signals_json, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    conn.commit()
    return len(values)


def insert_recommendations(conn: sqlite3.Connection, path: Path, include_raw_json: bool) -> int:
    payload = read_json(path, {})
    rows = list_from_payload(payload, "recommendations")
    values = []
    for index, row in enumerate(rows, 1):
        values.append(
            (
                index,
                text(row.get("id")),
                text(row.get("type")),
                text(row.get("title") or row.get("name")),
                float_value(row.get("score") if row.get("score") is not None else row.get("final_score")),
                compact_json(row.get("evidence") or []),
                compact_json(row.get("source_scores") or {}),
                compact_json(row) if include_raw_json else "",
            )
        )
    conn.executemany(
        """
        INSERT INTO recommendations (
          row_pk, item_id, type, title, score, evidence_json, source_scores_json, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    conn.commit()
    return len(values)


def insert_graph_rag_answers(conn: sqlite3.Connection, path: Path, include_raw_json: bool) -> dict[str, Any]:
    values = []
    parse_errors = []
    scanned = 0
    inserted = 0
    for line_no, row, err in iter_jsonl(path):
        scanned += 1
        if err is not None:
            parse_errors.append(err)
            continue
        assert row is not None
        inserted += 1
        values.append(
            (
                inserted,
                text(row.get("id")),
                text(row.get("query")),
                text(row.get("answer")),
                int_value(row.get("citation_count")),
                int_value(row.get("fact_count")),
                compact_json(row.get("citations") or []),
                compact_json(row.get("facts") or []),
                text(row.get("status")),
                compact_json(row) if include_raw_json else "",
            )
        )
    conn.executemany(
        """
        INSERT INTO graph_rag_answers (
          row_pk, item_id, query, answer, citation_count, fact_count,
          citations_json, facts_json, status, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    conn.commit()
    return {
        "path": str(path),
        "scanned_nonblank_lines": scanned,
        "inserted": inserted,
        "parse_error_count": scanned - inserted,
        "parse_error_samples": parse_errors[:20],
    }


def insert_runtime_report(
    conn: sqlite3.Connection,
    *,
    name: str,
    path: Path,
    payload: Any,
    include_raw_json: bool,
) -> int:
    if payload is None:
        return 0
    decision = text(payload.get("decision")) if isinstance(payload, dict) else ""
    ok_value = payload.get("ok") if isinstance(payload, dict) else None
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if summary is None and isinstance(payload, dict):
        summary = {
            key: payload.get(key)
            for key in ["counts", "after_counts", "collection_groups", "type_counts"]
            if key in payload
        }
    next_row = conn.execute("SELECT COALESCE(MAX(row_pk), 0) + 1 FROM runtime_reports").fetchone()[0]
    conn.execute(
        """
        INSERT INTO runtime_reports (
          row_pk, report_name, path, decision, ok, summary_json, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            next_row,
            name,
            str(path),
            decision,
            bool_int(ok_value),
            compact_json(summary or {}),
            compact_json(payload) if include_raw_json else "",
        ),
    )
    conn.commit()
    return 1


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX idx_articles_article_id ON articles(article_id);
        CREATE INDEX idx_articles_article_uid ON articles(article_uid);
        CREATE INDEX idx_articles_source_account ON articles(source_account);
        CREATE INDEX idx_articles_publish_time_status ON articles(publish_time_status);

        CREATE INDEX idx_entities_eid ON entities(eid);
        CREATE INDEX idx_entities_name ON entities(name);
        CREATE INDEX idx_entities_type ON entities(type);
        CREATE INDEX idx_entities_city ON entities(city);
        CREATE INDEX idx_entities_source_article_uid ON entities(source_article_uid);

        CREATE INDEX idx_events_evid ON events(evid);
        CREATE INDEX idx_events_name ON events(name);
        CREATE INDEX idx_events_place ON events(place);
        CREATE INDEX idx_events_city ON events(city);
        CREATE INDEX idx_events_time_iso ON events(time_iso);
        CREATE INDEX idx_events_source_article_uid ON events(source_article_uid);

        CREATE INDEX idx_identity_review_status ON identity_review_items(status);
        CREATE INDEX idx_identity_review_subject ON identity_review_items(subject_name, subject_type);
        CREATE INDEX idx_identity_review_source_article ON identity_review_items(source_article_uid);

        CREATE INDEX idx_recommendations_type ON recommendations(type);
        CREATE INDEX idx_graph_rag_query ON graph_rag_answers(query);
        CREATE INDEX idx_runtime_reports_name ON runtime_reports(report_name);
        """
    )
    for table in ["article_fts", "entity_fts", "event_fts"]:
        conn.execute(f"INSERT INTO {table}({table}) VALUES('optimize')")
    conn.commit()


def count_table(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def smoke_queries(conn: sqlite3.Connection) -> dict[str, Any]:
    smoke: dict[str, Any] = {}
    for table, fields in {
        "article_fts": "row_pk, article_uid, title",
        "entity_fts": "row_pk, eid, name",
        "event_fts": "row_pk, evid, name",
    }.items():
        try:
            rows = conn.execute(f"SELECT {fields} FROM {table} WHERE {table} MATCH ? LIMIT 5", ("DADA",)).fetchall()
            smoke[f"{table}_dada_limit5"] = [list(row) for row in rows]
        except sqlite3.OperationalError as exc:
            smoke[f"{table}_dada_error"] = str(exc)

    entity_source = conn.execute(
        "SELECT source_article_uid FROM entities WHERE source_article_uid <> '' LIMIT 1"
    ).fetchone()
    if entity_source:
        uid = entity_source[0]
        smoke["first_entity_source_article_uid"] = uid
        smoke["first_entity_source_article_match_count"] = count_query(
            conn, "SELECT COUNT(*) FROM articles WHERE article_uid = ?", (uid,)
        )

    event_source = conn.execute("SELECT source_article_uid FROM events WHERE source_article_uid <> '' LIMIT 1").fetchone()
    if event_source:
        uid = event_source[0]
        smoke["first_event_source_article_uid"] = uid
        smoke["first_event_source_article_match_count"] = count_query(
            conn, "SELECT COUNT(*) FROM articles WHERE article_uid = ?", (uid,)
        )
    return smoke


def count_query(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def resolve_data_file(stage7_atlas_dir: Path, pointer: dict[str, Any], kind: str) -> Path:
    files = pointer.get("files") if isinstance(pointer, dict) else {}
    entry = files.get(kind) if isinstance(files, dict) else None
    rel = entry.get("path") if isinstance(entry, dict) else f"{kind}.jsonl.gz"
    return stage7_atlas_dir / rel


def insert_metadata(conn: sqlite3.Connection, metadata: dict[str, Any]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        [(key, compact_json(value) if isinstance(value, (dict, list)) else text(value)) for key, value in metadata.items()],
    )
    conn.commit()


def build_database(
    *,
    stage7_atlas_dir: Path,
    out_dir: Path,
    db_path: Path,
    batch_size: int = 5000,
    include_raw_json: bool = True,
    graph_verify_path: Path | None = DEFAULT_GRAPH_VERIFY,
) -> dict[str, Any]:
    started = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    pointer_path = stage7_atlas_dir / "release_pointer.staging.json"
    pointer = read_json(pointer_path, {})
    expected_counts = dict(pointer.get("counts") or {})
    ensure_clean_db(db_path)
    conn = sqlite3.connect(str(db_path))
    fts_tokenizer = configure_conn(conn)
    create_schema(conn, fts_tokenizer)

    insert_metadata(
        conn,
        {
            "schema_version": "stage7_atlas_local_sqlite_db.v1",
            "generated_at": utcish_now(),
            "stage7_atlas_dir": str(stage7_atlas_dir),
            "release_pointer": str(pointer_path),
            "include_raw_json": include_raw_json,
            "source_counts": expected_counts,
            "writes": "local SQLite atlas database only",
        },
    )

    ingest_reports: dict[str, Any] = {}
    for kind in ["articles", "entities", "events"]:
        path = resolve_data_file(stage7_atlas_dir, pointer, kind)
        ingest_reports[kind] = insert_jsonl_table(
            conn,
            kind=kind,
            path=path,
            batch_size=batch_size,
            include_raw_json=include_raw_json,
        )

    identity_path = stage7_atlas_dir / "identity_review_workbench.json"
    recommendations_path = stage7_atlas_dir / "recommendations.json"
    graph_rag_path = stage7_atlas_dir / "graph_rag_answer_drafts.jsonl"
    vector_router_path = stage7_atlas_dir / "vector_collection_router_smoke.json"
    package_manifest_path = stage7_atlas_dir / "package_manifest.json"
    source_manifest_path = stage7_atlas_dir / "source_manifest.json"

    identity_count = insert_identity_review(conn, identity_path, include_raw_json) if identity_path.exists() else 0
    recommendation_count = (
        insert_recommendations(conn, recommendations_path, include_raw_json) if recommendations_path.exists() else 0
    )
    graph_rag_report = (
        insert_graph_rag_answers(conn, graph_rag_path, include_raw_json)
        if graph_rag_path.exists()
        else {"inserted": 0, "parse_error_count": 0, "parse_error_samples": []}
    )

    runtime_count = 0
    runtime_count += insert_runtime_report(
        conn,
        name="release_pointer",
        path=pointer_path,
        payload=pointer,
        include_raw_json=include_raw_json,
    )
    for name, path in [
        ("package_manifest", package_manifest_path),
        ("source_manifest", source_manifest_path),
        ("vector_collection_router_smoke", vector_router_path),
    ]:
        runtime_count += insert_runtime_report(
            conn,
            name=name,
            path=path,
            payload=read_json(path, None),
            include_raw_json=include_raw_json,
        )
    if graph_verify_path and graph_verify_path.exists():
        runtime_count += insert_runtime_report(
            conn,
            name="neo4j_production_verify",
            path=graph_verify_path,
            payload=read_json(graph_verify_path, None),
            include_raw_json=include_raw_json,
        )

    create_indexes(conn)
    conn.execute("PRAGMA optimize")

    actual_counts = {
        "articles": count_table(conn, "articles"),
        "entities": count_table(conn, "entities"),
        "events": count_table(conn, "events"),
        "identity_review_items": identity_count,
        "recommendations": recommendation_count,
        "graph_rag_answers": count_table(conn, "graph_rag_answers"),
        "runtime_reports": runtime_count,
    }
    count_matches = {
        "articles": actual_counts["articles"] == int_value(expected_counts.get("articles")),
        "entities": actual_counts["entities"] == int_value(expected_counts.get("entities")),
        "events": actual_counts["events"] == int_value(expected_counts.get("events")),
    }
    parse_errors = {
        key: {
            "count": ingest_reports[key]["parse_error_count"],
            "samples": ingest_reports[key]["parse_error_samples"],
        }
        for key in ["articles", "entities", "events"]
    }
    parse_errors["graph_rag_answers"] = {
        "count": graph_rag_report.get("parse_error_count", 0),
        "samples": graph_rag_report.get("parse_error_samples", []),
    }

    smoke = smoke_queries(conn)
    conn.close()

    blockers: list[str] = []
    warnings: list[str] = []
    for key, ok in count_matches.items():
        if not ok:
            blockers.append(f"{key}_count_mismatch")
    for key, value in parse_errors.items():
        if value["count"]:
            blockers.append(f"{key}_parse_errors")
    if not smoke.get("first_entity_source_article_match_count"):
        warnings.append("entity_source_article_join_smoke_empty")
    if not smoke.get("first_event_source_article_match_count"):
        warnings.append("event_source_article_join_smoke_empty")

    db_bytes = db_path.stat().st_size if db_path.exists() else 0
    decision = "atlas_local_sqlite_db_ready"
    ok = not blockers
    if blockers:
        decision = "atlas_local_sqlite_db_blocked"
    elif warnings:
        decision = "atlas_local_sqlite_db_ready_with_warnings"

    report = {
        "schema_version": "stage7_atlas_local_sqlite_db_report.v1",
        "generated_at": utcish_now(),
        "decision": decision,
        "ok": ok,
        "db_path": str(db_path),
        "db_bytes": db_bytes,
        "stage7_atlas_dir": str(stage7_atlas_dir),
        "release_pointer": str(pointer_path),
        "expected_counts": expected_counts,
        "actual_counts": actual_counts,
        "count_matches": count_matches,
        "ingest": ingest_reports,
        "parse_errors": parse_errors,
        "fts_tokenizer": fts_tokenizer,
        "smoke": smoke,
        "blockers": blockers,
        "warnings": warnings,
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "safety": {
            "sqlite_write_executed": True,
            "sqlite_db_path": str(db_path),
            "llm_call_executed": False,
            "paid_api_used": False,
            "network_call_executed": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "neo4j_write_executed": False,
            "mem0_write_executed": False,
            "d_scan_executed": False,
            "source_package_reused": True,
        },
    }
    write_json(out_dir / "atlas_local_sqlite_db_report.json", report)
    write_markdown(out_dir / "atlas_local_sqlite_db_report.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the local full Stage7 atlas SQLite database.")
    parser.add_argument("--stage7-atlas-dir", type=Path, default=DEFAULT_STAGE7_ATLAS_DIR)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--skip-raw-json", action="store_true")
    parser.add_argument("--graph-verify-path", type=Path, default=DEFAULT_GRAPH_VERIFY)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pointer = read_json(args.stage7_atlas_dir / "release_pointer.staging.json", {})
    article_count = int_value((pointer.get("counts") or {}).get("articles"))
    date_tag = datetime.now().strftime("%Y%m%d")
    out_dir = args.out_dir or (
        REPO_ROOT
        / "tools"
        / "stage7_rewrite"
        / "reports"
        / f"atlas_local_sqlite_db_{article_count}_{date_tag}"
    )
    db_path = args.db_path or (out_dir / "atlas.sqlite")
    report = build_database(
        stage7_atlas_dir=args.stage7_atlas_dir,
        out_dir=out_dir,
        db_path=db_path,
        batch_size=args.batch_size,
        include_raw_json=not args.skip_raw_json,
        graph_verify_path=args.graph_verify_path,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "ok": report["ok"],
                "db_path": report["db_path"],
                "actual_counts": report["actual_counts"],
                "db_bytes": report["db_bytes"],
                "report": str(out_dir / "atlas_local_sqlite_db_report.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
