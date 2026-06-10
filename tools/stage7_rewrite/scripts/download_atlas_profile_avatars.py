#!/usr/bin/env python3
r"""Download confirmed social profile avatars and store to D: drive database.

Reads confirmed profile evidence from cross-validation + outlink expansion,
extracts avatar URLs, downloads images, deduplicates by SHA256, and stores
metadata in D:\DJ_DATA\databases\atlas_avatars.sqlite.

Only processes confirmed profiles (cross_validation_priority >= threshold).
Different avatars from different platforms are all downloaded.
"""

import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────
D_DRIVE = Path("D:/")
DJ_DATA = D_DRIVE / "DJ_DATA"
AVATAR_DIR = DJ_DATA / "avatars"
DB_PATH = DJ_DATA / "databases" / "atlas_avatars.sqlite"

# Cross-validated entities (most confirmed source)
CROSS_VALIDATED_QUEUE = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
    "/reports/atlas_cross_validation_20260521/atlas_cross_validated_queue.jsonl"
)

# Outlink evidence (has profile URLs + avatar URLs)
OUTLINK_FETCHES = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
    "/reports/atlas_social_profile_outlinks_batch001_http_20260521"
    "/atlas_social_profile_fetches.jsonl"
)

# OpenCLI evidence (has profile_image_url)
OPENCLI_EVIDENCE = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
    "/reports/opencli_social_profile_evidence_20260516"
    "/opencli_social_profile_evidence.jsonl"
)

SCHEMA_VERSION = "stage7_atlas_avatar_store.v1"
MIN_CONFIDENCE_SCORE = 15  # cross_validation_priority threshold
REQUEST_TIMEOUT = 15
MAX_AVATAR_SIZE = 10 * 1024 * 1024  # 10MB max per image
USER_AGENT = "Atlas-Avatar-Bot/1.0 (research; report-only; +https://github.com/atlas)"

# Platforms where we extract avatars
AVATAR_SELECTORS = {
    "instagram": [
        'meta[property="og:image"]',
    ],
    "soundcloud": [
        'meta[property="og:image"]',
        'meta[property="twitter:image"]',
    ],
    "bandcamp": [
        'meta[property="og:image"]',
    ],
    "mixcloud": [
        'meta[property="og:image"]',
    ],
    "residentadvisor": [
        'meta[property="og:image"]',
    ],
    "ra.co": [
        'meta[property="og:image"]',
    ],
    "youtube": [
        'meta[property="og:image"]',
        'link[rel="image_src"]',
    ],
    "linktree": [
        'meta[property="og:image"]',
    ],
    "bilibili": [
        'meta[property="og:image"]',
    ],
    "baihui.live": [
        'meta[property="og:image"]',
    ],
    "cdcr.live": [
        'meta[property="og:image"]',
    ],
    "byyb.live": [
        'meta[property="og:image"]',
    ],
    "shcr": [
        'meta[property="og:image"]',
    ],
    "spotify": [
        'meta[property="og:image"]',
    ],
    "beatport": [
        'meta[property="og:image"]',
    ],
}


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def init_db() -> sqlite3.Connection:
    """Create/migrate avatar database on D: drive."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS avatars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_search_id TEXT NOT NULL,
            entity_name TEXT,
            entity_type TEXT,
            platform TEXT NOT NULL,
            profile_url TEXT,
            avatar_url TEXT NOT NULL,
            file_path TEXT,
            file_size_bytes INTEGER,
            sha256 TEXT,
            width INTEGER,
            height INTEGER,
            content_type TEXT,
            downloaded_at TEXT,
            source_tool TEXT,
            cross_validation_priority INTEGER DEFAULT 0,
            atlas_mention_count INTEGER DEFAULT 0,
            accepted_for_graph INTEGER DEFAULT 0,
            graph_write_allowed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS avatar_download_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_search_id TEXT,
            avatar_url TEXT,
            status TEXT,       -- ok, error, skipped_duplicate, too_large, timeout
            error_message TEXT,
            duration_sec REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_avatars_entity ON avatars(entity_search_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_avatars_sha256 ON avatars(sha256)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_avatars_platform ON avatars(platform)
    """)

    conn.commit()
    return conn


def extract_avatar_url(profile_url: str, platform: str) -> str | None:
    """Extract avatar URL from a profile page via HTTP og:image."""
    if not profile_url:
        return None

    selectors = AVATAR_SELECTORS.get(platform.lower(), [])
    if not selectors:
        return None

    try:
        req = urllib.request.Request(
            profile_url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")[:200000]

        # Simple regex-based og:image extraction
        import re
        for selector in selectors:
            if 'property="og:image"' in selector:
                match = re.search(
                    r'<meta\s+property="og:image"\s+content="([^"]+)"',
                    html, re.IGNORECASE
                )
                if match:
                    return match.group(1)
            elif 'name="twitter:image"' in selector:
                match = re.search(
                    r'<meta\s+name="twitter:image"\s+content="([^"]+)"',
                    html, re.IGNORECASE
                )
                if match:
                    return match.group(1)
            elif 'rel="image_src"' in selector:
                match = re.search(
                    r'<link\s+rel="image_src"\s+href="([^"]+)"',
                    html, re.IGNORECASE
                )
                if match:
                    return match.group(1)

        return None
    except Exception:
        return None


def download_avatar(avatar_url: str) -> tuple[bytes | None, str | None, str | None]:
    """Download avatar image. Returns (content, content_type, error)."""
    try:
        req = urllib.request.Request(
            avatar_url,
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            content = resp.read(MAX_AVATAR_SIZE + 1)

        if len(content) > MAX_AVATAR_SIZE:
            return None, None, "too_large"

        return content, content_type, None
    except urllib.error.HTTPError as e:
        return None, None, f"http_{e.code}"
    except urllib.error.URLError as e:
        return None, None, f"url_error_{e.reason}"
    except Exception as e:
        return None, None, str(e)[:200]


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def file_extension(content_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
    }
    return mapping.get(content_type.split(";")[0].strip(), ".jpg")


def store_avatar(
    conn: sqlite3.Connection,
    content: bytes,
    entity_search_id: str,
    entity_name: str,
    entity_type: str,
    platform: str,
    profile_url: str | None,
    avatar_url: str,
    content_type: str,
    source_tool: str,
    priority: int,
    mention_count: int,
) -> int | None:
    """Store avatar file + metadata. Returns row id or None."""
    sha = sha256_hex(content)

    # Dedup: check if this SHA256 already exists
    cur = conn.execute(
        "SELECT id, file_path FROM avatars WHERE sha256 = ? LIMIT 1",
        (sha,)
    )
    existing = cur.fetchone()
    if existing:
        # Still create a record linking to same file (different source)
        existing_id, existing_path = existing
        conn.execute(
            """INSERT INTO avatars 
               (entity_search_id, entity_name, entity_type, platform, profile_url,
                avatar_url, file_path, file_size_bytes, sha256, content_type,
                downloaded_at, source_tool, cross_validation_priority, atlas_mention_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entity_search_id, entity_name, entity_type, platform, profile_url,
                avatar_url, existing_path, len(content), sha, content_type,
                now_cst(), source_tool, priority, mention_count,
            ),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Store file: DJ_DATA/avatars/{sha[:2]}/{sha}.{ext}
    ext = file_extension(content_type)
    rel_dir = sha[:2]
    rel_path = f"{rel_dir}/{sha}{ext}"
    abs_path = AVATAR_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    with open(abs_path, "wb") as f:
        f.write(content)

    conn.execute(
        """INSERT INTO avatars 
           (entity_search_id, entity_name, entity_type, platform, profile_url,
            avatar_url, file_path, file_size_bytes, sha256, content_type,
            downloaded_at, source_tool, cross_validation_priority, atlas_mention_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entity_search_id, entity_name, entity_type, platform, profile_url,
            avatar_url, rel_path, len(content), sha, content_type,
            now_cst(), source_tool, priority, mention_count,
        ),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def process_cross_validated_queue(conn: sqlite3.Connection) -> dict:
    """Process cross-validated entities with confirmed profiles."""
    if not CROSS_VALIDATED_QUEUE.exists():
        return {"status": "no_cross_validated_queue", "processed": 0}

    stats = {"processed": 0, "downloaded": 0, "skipped_duplicate": 0, "errors": 0, "no_avatar_url": 0}
    entities = []

    with open(CROSS_VALIDATED_QUEUE) as f:
        for line in f:
            entity = json.loads(line)
            priority = entity.get("cross_validation_priority", 0)
            if priority >= MIN_CONFIDENCE_SCORE:
                entities.append(entity)

    print(f"Entities above confidence threshold ({MIN_CONFIDENCE_SCORE}): {len(entities)}", file=sys.stderr)

    for entity in entities:
        stats["processed"] += 1
        entity_id = entity.get("entity_search_id", "")
        name = entity.get("entity_name", "unknown")
        etype = entity.get("entity_type", "unknown")
        priority = entity.get("cross_validation_priority", 0)
        mentions = entity.get("atlas_mention_count", 0)

        # Check for existing social URLs
        existing_urls = entity.get("atlas_existing_social_urls", [])
        for url_info in existing_urls:
            profile_url = url_info.get("url", "")
            domain = url_info.get("domain", "unknown")
            platform = domain.split(".")[0] if "." in domain else domain

            avatar_url = extract_avatar_url(profile_url, platform)
            if not avatar_url:
                stats["no_avatar_url"] += 1
                continue

            content, content_type, error = download_avatar(avatar_url)
            if error:
                stats["errors"] += 1
                conn.execute(
                    "INSERT INTO avatar_download_log (entity_search_id, avatar_url, status, error_message, duration_sec) VALUES (?, ?, ?, ?, 0)",
                    (entity_id, avatar_url, "error", error),
                )
                continue

            row_id = store_avatar(
                conn, content, entity_id, name, etype,
                platform, profile_url, avatar_url, content_type,
                "cross_validated_existing", priority, mentions,
            )
            if row_id:
                stats["downloaded"] += 1
                conn.execute(
                    "INSERT INTO avatar_download_log (entity_search_id, avatar_url, status) VALUES (?, ?, 'ok')",
                    (entity_id, avatar_url),
                )

            time.sleep(0.3)  # polite rate limit

    conn.commit()
    return stats


def process_outlink_fetches(conn: sqlite3.Connection) -> dict:
    """Process avatar URLs from outlink fetch evidence."""
    stats = {"processed": 0, "downloaded": 0, "errors": 0, "no_avatar_url": 0}

    for fetches_path in [OUTLINK_FETCHES, OPENCLI_EVIDENCE]:
        if not fetches_path.exists():
            continue

        with open(fetches_path) as f:
            for line in f:
                stats["processed"] += 1
                row = json.loads(line)

                entity_id = row.get("entity_search_id", "")
                name = row.get("name") or row.get("entity_name", "unknown")
                etype = row.get("type") or row.get("entity_type", "unknown")
                profile_url = row.get("profile_url") or row.get("final_url", "")
                platform = row.get("platform") or row.get("profile_platform", "unknown")
                avatar_url = row.get("profile_image_url_or_hash") or row.get("avatar_url", "")

                # Skip hash-only references
                if avatar_url.startswith("sha256:"):
                    stats["no_avatar_url"] += 1
                    continue

                if not avatar_url and profile_url:
                    avatar_url = extract_avatar_url(profile_url, platform)

                if not avatar_url:
                    stats["no_avatar_url"] += 1
                    continue

                content, content_type, error = download_avatar(avatar_url)
                if error:
                    stats["errors"] += 1
                    continue

                row_id = store_avatar(
                    conn, content, entity_id, name, etype,
                    platform, profile_url, avatar_url, content_type,
                    "outlink_fetch", 0, 0,
                )
                if row_id:
                    stats["downloaded"] += 1

                time.sleep(0.5)
                if stats["processed"] % 50 == 0:
                    print(f"  Processed {stats['processed']}...", file=sys.stderr)

    conn.commit()
    return stats


def main():
    print("Initializing avatar database on D: drive...", file=sys.stderr)
    conn = init_db()

    # Count existing
    cur = conn.execute("SELECT COUNT(*) FROM avatars")
    existing_count = cur.fetchone()[0]
    print(f"  Existing avatars in DB: {existing_count}", file=sys.stderr)

    total_stats = {
        "generated_at": now_cst(),
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_avatar_download_report_only",
        "db_path": str(DB_PATH),
        "avatar_dir": str(AVATAR_DIR),
    }

    # Phase 1: cross-validated confirmed entities
    print("\nPhase 1: Cross-validated confirmed entities...", file=sys.stderr)
    cv_stats = process_cross_validated_queue(conn)
    print(f"  Cross-validated: {cv_stats}", file=sys.stderr)
    total_stats["cross_validated"] = cv_stats

    # Phase 2: outlink fetch evidence
    print("\nPhase 2: Outlink fetch evidence...", file=sys.stderr)
    ol_stats = process_outlink_fetches(conn)
    print(f"  Outlink fetches: {ol_stats}", file=sys.stderr)
    total_stats["outlink_fetches"] = ol_stats

    # Final counts
    cur = conn.execute("SELECT COUNT(*) FROM avatars")
    total_stats["total_avatars"] = cur.fetchone()[0]

    cur = conn.execute("SELECT COUNT(DISTINCT entity_search_id) FROM avatars")
    total_stats["entities_with_avatars"] = cur.fetchone()[0]

    cur = conn.execute("SELECT platform, COUNT(*) FROM avatars GROUP BY platform ORDER BY COUNT(*) DESC")
    total_stats["platform_distribution"] = dict(cur.fetchall())

    cur = conn.execute("SELECT COUNT(DISTINCT sha256) FROM avatars WHERE sha256 IS NOT NULL")
    total_stats["unique_avatars"] = cur.fetchone()[0]

    # Total file size
    cur = conn.execute("SELECT SUM(file_size_bytes) FROM avatars WHERE file_size_bytes IS NOT NULL")
    total_bytes = cur.fetchone()[0] or 0
    total_stats["total_size_mb"] = round(total_bytes / (1024 * 1024), 2)

    conn.close()

    # Write summary
    summary_path = DJ_DATA / "reports" / "avatar_download_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as f:
        json.dump(total_stats, f, ensure_ascii=False, indent=2)

    print(f"\nSummary: {summary_path}", file=sys.stderr)
    print(json.dumps(total_stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
