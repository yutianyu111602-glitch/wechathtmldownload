"""SQLite state management."""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


class SQLiteState:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS article_status (
                    article_uid TEXT PRIMARY KEY,
                    source_account TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    stage TEXT DEFAULT 'llm_extract',
                    mode TEXT DEFAULT 'canary',
                    attempts INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    last_error_type TEXT,
                    last_error_message TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    llm_input_path TEXT,
                    output_dir TEXT,
                    json_valid INTEGER DEFAULT 0,
                    schema_valid INTEGER DEFAULT 0,
                    entity_count INTEGER DEFAULT 0,
                    event_count INTEGER DEFAULT 0,
                    relation_count INTEGER DEFAULT 0,
                    claim_count INTEGER DEFAULT 0,
                    quality_verdict TEXT DEFAULT '',
                    empty_recovery_blocked INTEGER DEFAULT 0,
                    empty_recovery_used INTEGER DEFAULT 0,
                    all_chunks_failed INTEGER DEFAULT 0,
                    context_exceeded_count INTEGER DEFAULT 0,
                    bio_cleared_count INTEGER DEFAULT 0,
                    ocr_evidence_count INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    level TEXT,
                    message TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS run_counters (
                    key TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            self._migrate_schema(conn)
            conn.commit()

    def _migrate_schema(self, conn) -> None:
        """Add missing columns to existing table."""
        cursor = conn.execute("PRAGMA table_info(article_status)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        new_cols = [
            ("quality_verdict", "TEXT DEFAULT ''"),
            ("empty_recovery_blocked", "INTEGER DEFAULT 0"),
            ("empty_recovery_used", "INTEGER DEFAULT 0"),
            ("all_chunks_failed", "INTEGER DEFAULT 0"),
            ("context_exceeded_count", "INTEGER DEFAULT 0"),
            ("bio_cleared_count", "INTEGER DEFAULT 0"),
            ("ocr_evidence_count", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE article_status ADD COLUMN {col_name} {col_type}")

    def upsert_article(self, record: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO article_status (
                    article_uid, source_account, article_id, status, stage, mode,
                    attempts, last_error_type, last_error_message, started_at,
                    finished_at, llm_input_path, output_dir, json_valid, schema_valid,
                    entity_count, event_count, relation_count, claim_count,
                    quality_verdict, empty_recovery_blocked, empty_recovery_used,
                    all_chunks_failed, context_exceeded_count, bio_cleared_count,
                    ocr_evidence_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_uid) DO UPDATE SET
                    status=excluded.status,
                    stage=excluded.stage,
                    mode=excluded.mode,
                    attempts=excluded.attempts,
                    last_error_type=excluded.last_error_type,
                    last_error_message=excluded.last_error_message,
                    started_at=COALESCE(excluded.started_at, article_status.started_at),
                    finished_at=excluded.finished_at,
                    output_dir=excluded.output_dir,
                    json_valid=excluded.json_valid,
                    schema_valid=excluded.schema_valid,
                    entity_count=excluded.entity_count,
                    event_count=excluded.event_count,
                    relation_count=excluded.relation_count,
                    claim_count=excluded.claim_count,
                    quality_verdict=excluded.quality_verdict,
                    empty_recovery_blocked=excluded.empty_recovery_blocked,
                    empty_recovery_used=excluded.empty_recovery_used,
                    all_chunks_failed=excluded.all_chunks_failed,
                    context_exceeded_count=excluded.context_exceeded_count,
                    bio_cleared_count=excluded.bio_cleared_count,
                    ocr_evidence_count=excluded.ocr_evidence_count,
                    updated_at=datetime('now')
            """, (
                record.get("article_uid"),
                record.get("source_account"),
                record.get("article_id"),
                record.get("status", "pending"),
                record.get("stage", "llm_extract"),
                record.get("mode", "canary"),
                record.get("attempts", 0),
                record.get("last_error_type"),
                record.get("last_error_message"),
                record.get("started_at"),
                record.get("finished_at"),
                record.get("llm_input_path"),
                record.get("output_dir"),
                record.get("json_valid", 0),
                record.get("schema_valid", 0),
                record.get("entity_count", 0),
                record.get("event_count", 0),
                record.get("relation_count", 0),
                record.get("claim_count", 0),
                record.get("quality_verdict", ""),
                record.get("empty_recovery_blocked", 0),
                record.get("empty_recovery_used", 0),
                record.get("all_chunks_failed", 0),
                record.get("context_exceeded_count", 0),
                record.get("bio_cleared_count", 0),
                record.get("ocr_evidence_count", 0),
                datetime.now().isoformat(),
            ))
            conn.commit()

    def get_pending(self, mode: str, limit: Optional[int] = None) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM article_status WHERE status = 'pending' AND mode = ? ORDER BY article_uid"
            params = [mode]
            if limit:
                sql += " LIMIT ?"
                params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_status(self, article_uid: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM article_status WHERE article_uid = ?",
                (article_uid,)
            ).fetchone()
            return row[0] if row else None

    def get_mode(self, article_uid: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT mode FROM article_status WHERE article_uid = ?",
                (article_uid,)
            ).fetchone()
            return row[0] if row else None

    def reset_stale_running(self, mode: str) -> int:
        """Reset stale 'running' articles to 'pending' for resume."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE article_status
                SET status = 'pending', updated_at = datetime('now')
                WHERE status = 'running' AND mode = ?
            """, (mode,))
            conn.commit()
            return cursor.rowcount

    def get_stats(self, mode: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) as running,
                    SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                    SUM(CASE WHEN status='done_with_warnings' THEN 1 ELSE 0 END) as done_with_warnings,
                    SUM(CASE WHEN status='failed_retryable' THEN 1 ELSE 0 END) as failed_retryable,
                    SUM(CASE WHEN status='failed_final' THEN 1 ELSE 0 END) as failed_final,
                    SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) as skipped,
                    SUM(json_valid) as json_valid_count,
                    SUM(schema_valid) as schema_valid_count,
                    SUM(entity_count) as entity_count,
                    SUM(event_count) as event_count,
                    SUM(relation_count) as relation_count,
                    SUM(claim_count) as claim_count,
                    SUM(empty_recovery_blocked) as empty_recovery_blocked,
                    SUM(empty_recovery_used) as empty_recovery_used
                FROM article_status WHERE mode = ?
            """, (mode,)).fetchone()
            return {
                "total": row[0] or 0,
                "pending": row[1] or 0,
                "running": row[2] or 0,
                "done": row[3] or 0,
                "done_with_warnings": row[4] or 0,
                "failed_retryable": row[5] or 0,
                "failed_final": row[6] or 0,
                "skipped": row[7] or 0,
                "json_valid_count": row[8] or 0,
                "schema_valid_count": row[9] or 0,
                "entity_count": row[10] or 0,
                "event_count": row[11] or 0,
                "relation_count": row[12] or 0,
                "claim_count": row[13] or 0,
                "empty_recovery_blocked": row[14] or 0,
                "empty_recovery_used": row[15] or 0,
            }

    def log(self, level: str, message: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO run_log (timestamp, level, message) VALUES (datetime('now'), ?, ?)", (level, message))
            conn.commit()

    def increment_counter(self, key: str, amount: int = 1) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO run_counters (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value=value+excluded.value,
                    updated_at=datetime('now')
            """, (key, amount))
            conn.commit()

    def get_counters(self) -> dict[str, int]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT key, value FROM run_counters").fetchall()
            return {row[0]: row[1] for row in rows}
