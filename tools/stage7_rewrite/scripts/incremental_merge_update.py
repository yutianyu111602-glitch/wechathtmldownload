#!/usr/bin/env python3
"""Incremental merge update: apply new matches to merge_map without rebuilding.

Reads new entity matches (from LLM or other sources) and incrementally 
merges them into the existing cross_db_merge_map.json.

Part of Atlas Three-DB Merge Pipeline — Task 3: Incremental Update.

Usage:
    python3 incremental_merge_update.py --merge cross_db_merge_map.json --new new_matches.json --output updated_merge_map.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_merge_map(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_merge_map(merge: dict, path: str):
    """Save merge map with backup."""
    # Auto-backup
    backup = path + f'.bak_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    shutil.copy2(path, backup)
    print(f'[incremental_update] Backup: {backup}', file=sys.stderr)
    
    # Update timestamp
    merge['generated_at'] = datetime.now(timezone.utc).isoformat()
    merge.setdefault('stats', {})['db2_to_db3_mappings'] = len(merge.get('db2_to_db3_map', {}))
    
    with open(path, 'w') as f:
        json.dump(merge, f, ensure_ascii=False, indent=2)
    print(f'[incremental_update] Saved: {path}', file=sys.stderr)


def apply_matches(merge: dict, new_matches: list[dict], source: str = 'incremental') -> dict:
    """Apply new eid→db3_id matches to merge_map.
    
    Args:
        merge: current merge_map dict
        new_matches: list of {eid, matched_db3_id, display_name, match_type, ...}
        source: label for stats tracking
    
    Returns:
        dict with {added, skipped_conflict, skipped_existing}
    """
    db2_map = merge.setdefault('db2_to_db3_map', {})
    stats = {'added': 0, 'skipped_conflict': 0, 'skipped_existing': 0}
    
    for m in new_matches:
        eid = m['eid']
        new_id = m['matched_db3_id']
        
        if eid in db2_map:
            existing = db2_map[eid]
            if existing != new_id:
                print(f'[incremental_update] CONFLICT: {eid} was {existing}, new={new_id} (skipped)', file=sys.stderr)
                stats['skipped_conflict'] += 1
            else:
                stats['skipped_existing'] += 1
        else:
            db2_map[eid] = new_id
            stats['added'] += 1
    
    # Update stats
    s = merge.setdefault('stats', {})
    s[f'incremental_{source}'] = stats['added']
    s['db2_to_db3_mappings'] = len(db2_map)
    
    return stats


def main():
    parser = argparse.ArgumentParser(description='Incrementally update merge_map with new matches')
    parser.add_argument('--merge', required=True, help='Path to cross_db_merge_map.json')
    parser.add_argument('--new', required=True, help='Path to new_matches.json (list of {eid, matched_db3_id, ...})')
    parser.add_argument('--source', default='incremental', help='Label for the source of new matches')
    parser.add_argument('--dry-run', action='store_true', help='Show what would change without writing')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    merge = load_merge_map(args.merge)
    new_matches = json.load(open(args.new))
    
    if not isinstance(new_matches, list):
        print(f'ERROR: --new file must contain a JSON array, got {type(new_matches).__name__}', file=sys.stderr)
        sys.exit(1)
    
    if args.verbose:
        print(f'[incremental_update] Current mappings: {len(merge.get("db2_to_db3_map", {}))}', file=sys.stderr)
        print(f'[incremental_update] New matches to apply: {len(new_matches)}', file=sys.stderr)
    
    if args.dry_run:
        # Simulate
        test_merge = json.loads(json.dumps(merge))
        stats = apply_matches(test_merge, new_matches, args.source)
        print(json.dumps(stats, indent=2))
        print(f'[incremental_update] DRY RUN — no changes written', file=sys.stderr)
    else:
        stats = apply_matches(merge, new_matches, args.source)
        save_merge_map(merge, args.merge)
        print(json.dumps(stats, indent=2))
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
