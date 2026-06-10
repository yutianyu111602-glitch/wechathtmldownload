#!/usr/bin/env python3
"""Incremental merge check: detect new DB2 eids not yet in merge_map.

Reads DB2 (via WSL), compares against current merge_map, outputs new eids.
Part of Atlas Three-DB Merge Pipeline — Task 3: Incremental Update.

Usage:
    # Windows (DB2 in WSL)
    wsl -e python3 incremental_merge_check.py --db2 /home/pc/swarm_data/atlas_swarm_data.sqlite --merge cross_db_merge_map.json
    
    # Or from WSL directly
    python3 incremental_merge_check.py --db2 /home/pc/swarm_data/atlas_swarm_data.sqlite --merge cross_db_merge_map.json
""" 
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Set


def get_db2_eids(db_path: str) -> Set[str]:
    """Extract all distinct eids from DB2's dj_outlinks table (read-only)."""
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        rows = conn.execute('SELECT DISTINCT eid FROM dj_outlinks WHERE eid IS NOT NULL').fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def get_db2_eid_info(db_path: str, eids: Set[str]) -> list[dict]:
    """Get entity_name, platforms for given eids."""
    if not eids:
        return []
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        placeholders = ','.join(['?' for _ in eids])
        rows = conn.execute(
            f"SELECT eid, entity_name, GROUP_CONCAT(DISTINCT outlink_platform) as platforms, "
            f"COUNT(*) as outlink_count "
            f"FROM dj_outlinks WHERE eid IN ({placeholders}) "
            f"GROUP BY eid",
            list(eids)
        ).fetchall()
        return [
            {
                'eid': r[0],
                'entity_name': r[1] or '',
                'platforms': (r[2] or '').split(','),
                'outlink_count': r[3]
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_merge_map_eids(merge_path: str) -> Set[str]:
    """Get all eids already in merge_map."""
    with open(merge_path) as f:
        merge = json.load(f)
    return set(merge.get('db2_to_db3_map', {}).keys())


def main():
    parser = argparse.ArgumentParser(description='Detect new DB2 eids for incremental merge')
    parser.add_argument('--db2', required=True, help='Path to DB2 SQLite (atlas_swarm_data.sqlite)')
    parser.add_argument('--merge', required=True, help='Path to cross_db_merge_map.json')
    parser.add_argument('--output', help='Output JSON file for new eids (default: stdout)')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        print(f'[incremental_check] Reading DB2: {args.db2}', file=sys.stderr)
    db2_eids = get_db2_eids(args.db2)
    if args.verbose:
        print(f'[incremental_check] DB2 eids: {len(db2_eids)}', file=sys.stderr)

    merge_eids = get_merge_map_eids(args.merge)
    if args.verbose:
        print(f'[incremental_check] merge_map eids: {len(merge_eids)}', file=sys.stderr)

    new_eids = db2_eids - merge_eids
    removed_eids = merge_eids - db2_eids

    if args.verbose:
        print(f'[incremental_check] New eids (not in merge_map): {len(new_eids)}', file=sys.stderr)
        print(f'[incremental_check] Removed eids (in merge_map but not DB2): {len(removed_eids)}', file=sys.stderr)

    # Get entity info for new eids
    new_entities = get_db2_eid_info(args.db2, new_eids)

    result = {
        'schema_version': 'incremental_check.v1',
        'db2_total_eids': len(db2_eids),
        'merge_map_total_eids': len(merge_eids),
        'new_eids': sorted(list(new_eids)),
        'new_count': len(new_eids),
        'removed_eids': sorted(list(removed_eids)),
        'removed_count': len(removed_eids),
        'new_entities': new_entities,
    }

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f'[incremental_check] Output written to {args.output}', file=sys.stderr)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # Return exit code based on whether there are new eids
    return 0 if not new_eids else 1


if __name__ == '__main__':
    sys.exit(main())
