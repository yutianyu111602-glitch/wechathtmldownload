#!/usr/bin/env python3
"""Unified Atlas Entity Resolver — query-time merge_map based.

Usage:
    from atlas_unified_resolver import AtlasResolver
    r = AtlasResolver()
    entity = r.resolve_db2_eid("55fde4931e3281af")
    # → {"entity_id": "org:1ddb0431cf9cee2e", "display_name": "All Club/ALL", ...}

Features:
- O(1) HashMap lookup, zero SQL UPDATE on DB3
- Fully reversible (delete merge_map.json to rollback)
- Combines 16,927 existing entity remaps + 1,708 cross-DB identity links
- No DB lock contention — read-only access
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

# ── Default paths ──────────────────────────────────────────
DEFAULT_MERGE_MAP = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_identity_resolution_20260608\cross_db_merge_map.json"
)
DEFAULT_DB3 = Path(
    r"C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun"
    r"\tmp\cloudrun_deploy_context\data\atlas_serving.sqlite"
)


class AtlasResolver:
    """Query-time entity resolution using merge_map (no DB writes)."""

    def __init__(
        self,
        merge_map_path: Path | str | None = None,
        db3_path: Path | str | None = None,
    ):
        self.merge_map_path = Path(merge_map_path or DEFAULT_MERGE_MAP)
        self.db3_path = Path(db3_path or DEFAULT_DB3)
        self._db2_to_db3: dict[str, str] = {}
        self._subject_map: dict[str, str] = {}
        self._conn: sqlite3.Connection | None = None
        self._loaded = False

    def _load(self):
        """Lazy-load merge_map from disk."""
        if self._loaded:
            return

        if self.merge_map_path.exists():
            data = json.loads(self.merge_map_path.read_text(encoding="utf-8"))
            self._db2_to_db3 = data.get("db2_to_db3_map", {})
            self._subject_map = data.get("existing_subject_map", {})

        self._loaded = True

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy DB3 connection (read-only)."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                f"file:{self.db3_path}?mode=ro", uri=True
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    # ── Core resolution ─────────────────────────────────────

    def resolve_db2_eid(self, eid: str) -> Optional[str]:
        """Map DB2 eid → DB3 canonical entity_id. Returns None if no match."""
        self._load()
        return self._db2_to_db3.get(eid)

    def resolve_subject_id(self, subject_id: str) -> str:
        """Apply existing entity merge remap. Returns canonical entity_id."""
        self._load()
        return self._subject_map.get(subject_id, subject_id)

    def resolve(self, identifier: str, source: str = "auto") -> Optional[str]:
        """Unified resolve: auto-detect source or specify 'db2'/'db3'.

        Returns canonical DB3 entity_id or None.
        """
        self._load()
        if source == "db2" or (source == "auto" and identifier in self._db2_to_db3):
            db3_id = self._db2_to_db3.get(identifier)
            if db3_id:
                return self._subject_map.get(db3_id, db3_id)
            return None

        if source == "db3" or source == "auto":
            return self._subject_map.get(identifier, identifier)

        return identifier

    # ── Entity lookup ───────────────────────────────────────

    def get_entity(self, entity_id: str) -> Optional[dict[str, Any]]:
        """Get DB3 entity details by canonical entity_id."""
        row = self.conn.execute(
            "SELECT * FROM canonical_subject WHERE subject_id = ?",
            (entity_id,),
        ).fetchone()
        if row:
            return dict(row)
        return None

    def get_db3_entity_for_db2(self, eid: str) -> Optional[dict[str, Any]]:
        """Full pipeline: DB2 eid → DB3 entity details."""
        db3_id = self.resolve_db2_eid(eid)
        if db3_id:
            return self.get_entity(db3_id)
        return None

    def search_by_name(
        self, name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search DB3 entities by display_name or normalized_name."""
        rows = self.conn.execute(
            """SELECT subject_id, subject_type, display_name, city_primary
               FROM canonical_subject
               WHERE display_name LIKE ? OR normalized_name LIKE ?
               LIMIT ?""",
            (f"%{name}%", f"%{name}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Batch operations ────────────────────────────────────

    def resolve_many_db2(
        self, eids: list[str]
    ) -> dict[str, Optional[str]]:
        """Batch resolve DB2 eids."""
        self._load()
        return {eid: self._db2_to_db3.get(eid) for eid in eids}

    def get_db2_link_evidence(
        self, eid: str
    ) -> Optional[dict[str, Any]]:
        """Get DB2 external link evidence for a resolved entity.

        Requires WSL access to DB2.
        Returns None if DB2 not accessible.
        """
        import subprocess

        db3_id = self.resolve_db2_eid(eid)
        if not db3_id:
            return None

        script = f'''
import json, sqlite3
conn = sqlite3.connect("/home/pc/swarm_data/atlas_swarm_data.sqlite")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT * FROM dj_outlinks WHERE eid = ?", ("{eid}",)
).fetchall()
social = conn.execute(
    "SELECT platform, handle FROM dj_social_profiles WHERE eid = ?", ("{eid}",)
).fetchall()
conn.close()
outlinks = [dict(r) for r in rows]
handles = [dict(r) for r in social]
print(json.dumps({{"outlinks": outlinks, "handles": handles}}, ensure_ascii=False))
'''
        try:
            result = subprocess.run(
                ["wsl", "-e", "python3", "-c", script],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception:
            pass
        return None

    # ── Stats ───────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, int]:
        """Resolver statistics."""
        self._load()
        return {
            "db2_to_db3_mappings": len(self._db2_to_db3),
            "subject_remaps": len(self._subject_map),
            "total_mappings": len(self._db2_to_db3) + len(self._subject_map),
            "db3_entities": self.conn.execute(
                "SELECT COUNT(*) FROM canonical_subject"
            ).fetchone()[0],
        }

    def close(self):
        """Close DB connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# ── Convenience function ────────────────────────────────────

def resolve_entity(name_or_id: str, source: str = "auto") -> Optional[dict]:
    """One-shot: resolve any identifier to DB3 entity details.

    >>> resolve_entity("Dada Bar Beijing")
    >>> resolve_entity("55fde4931e3281af", source="db2")
    """
    r = AtlasResolver()
    try:
        entity_id = r.resolve(name_or_id, source)
        if entity_id:
            return r.get_entity(entity_id)
        # Try name search
        results = r.search_by_name(name_or_id, limit=1)
        return results[0] if results else None
    finally:
        r.close()


# ── CLI ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    r = AtlasResolver()
    print(f"Atlas Unified Resolver")
    print(f"  DB2→DB3 mappings: {r.stats['db2_to_db3_mappings']:,}")
    print(f"  Subject remaps:   {r.stats['subject_remaps']:,}")
    print(f"  DB3 entities:     {r.stats['db3_entities']:,}")
    print()

    if len(sys.argv) > 1:
        query = sys.argv[1]
        source = sys.argv[2] if len(sys.argv) > 2 else "auto"
        print(f"Resolving: {query} (source={source})")

        entity_id = r.resolve(query, source)
        if entity_id:
            entity = r.get_entity(entity_id)
            if entity:
                print(f"  ✅ {entity['subject_id']} | {entity['display_name']} | {entity['subject_type']} | {entity.get('city_primary', '')}")
            else:
                print(f"  ⚠️  Resolved to {entity_id} but entity not found in DB3")
        else:
            # Try name search
            results = r.search_by_name(query, limit=5)
            if results:
                print(f"  🔍 Name search results:")
                for row in results:
                    print(f"     {row['subject_id']} | {row['display_name']} | {row['subject_type']}")
            else:
                print(f"  ❌ Not found")

    r.close()
