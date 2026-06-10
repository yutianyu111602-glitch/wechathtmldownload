#!/usr/bin/env python3
"""Merge map version management: snapshot, diff, merge, rollback.

Part of Atlas Three-DB Merge Pipeline — Task 4: Version Management.

Usage:
    python3 merge_map_version.py snapshot --merge cross_db_merge_map.json
    python3 merge_map_version.py diff --v1 v1.json --v2 v2.json
    python3 merge_map_version.py merge --merge cross_db_merge_map.json --delta delta.json
    python3 merge_map_version.py rollback --merge cross_db_merge_map.json --version v1
    python3 merge_map_version.py list --merge cross_db_merge_map.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


VERSION_DIR_NAME = 'merge_map_versions'


def get_version_dir(merge_path: str) -> Path:
    p = Path(merge_path).parent / VERSION_DIR_NAME
    p.mkdir(exist_ok=True)
    return p


def snapshot(merge_path: str, label: str | None = None) -> str:
    """Create a versioned snapshot of the current merge_map."""
    version_dir = get_version_dir(merge_path)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if label:
        ts = f'{ts}_{label}'
    
    src = Path(merge_path)
    dst = version_dir / f'merge_map_{ts}.json'
    shutil.copy2(src, dst)
    
    # Update version index
    index_path = version_dir / 'version_index.json'
    index = []
    if index_path.exists():
        index = json.loads(index_path.read_text())
    
    with open(src) as f:
        data = json.load(f)
    
    index.append({
        'version': ts,
        'label': label,
        'path': str(dst),
        'mappings': len(data.get('db2_to_db3_map', {})),
        'created_at': datetime.now(timezone.utc).isoformat(),
    })
    index_path.write_text(json.dumps(index, indent=2))
    
    print(f'Snapshot created: {dst.name} ({index[-1]["mappings"]} mappings)')
    return str(dst)


def diff(v1_path: str, v2_path: str) -> dict:
    """Compute added and removed mappings between two versions."""
    v1 = json.load(open(v1_path))
    v2 = json.load(open(v2_path))
    
    m1 = v1.get('db2_to_db3_map', {})
    m2 = v2.get('db2_to_db3_map', {})
    
    keys1 = set(m1.keys())
    keys2 = set(m2.keys())
    
    added = {k: m2[k] for k in (keys2 - keys1)}
    removed = {k: m1[k] for k in (keys1 - keys2)}
    changed = {k: {'from': m1[k], 'to': m2[k]} for k in (keys1 & keys2) if m1[k] != m2[k]}
    
    return {
        'added': added,
        'added_count': len(added),
        'removed': removed,
        'removed_count': len(removed),
        'changed': changed,
        'changed_count': len(changed),
        'v1_mappings': len(m1),
        'v2_mappings': len(m2),
    }


def merge_delta(merge_path: str, delta_path: str):
    """Incrementally merge a delta file into the current merge_map."""
    merge = json.load(open(merge_path))
    delta = json.load(open(delta_path))
    
    # Auto-snapshot before merge
    snapshot(merge_path, 'pre_merge')
    
    db2_map = merge.setdefault('db2_to_db3_map', {})
    
    added = delta.get('added', {})
    for eid, db3_id in added.items():
        if eid in db2_map and db2_map[eid] != db3_id:
            print(f'CONFLICT: {eid}: {db2_map[eid]} → {db3_id}', file=sys.stderr)
        db2_map[eid] = db3_id
    
    removed = delta.get('removed', {})
    for eid in removed:
        db2_map.pop(eid, None)
    
    merge['generated_at'] = datetime.now(timezone.utc).isoformat()
    merge.setdefault('stats', {})['db2_to_db3_mappings'] = len(db2_map)
    
    with open(merge_path, 'w') as f:
        json.dump(merge, f, ensure_ascii=False, indent=2)
    
    print(f'Merged: +{len(added)} added, -{len(removed)} removed')
    print(f'Current mappings: {len(db2_map)}')


def rollback(merge_path: str, version: str):
    """Roll back to a specific version snapshot."""
    version_dir = get_version_dir(merge_path)
    target = version_dir / f'merge_map_{version}.json'
    
    if not target.exists():
        # Try partial match
        candidates = sorted(version_dir.glob(f'merge_map_{version}*.json'))
        if candidates:
            target = candidates[0]
        else:
            print(f'ERROR: Version {version} not found', file=sys.stderr)
            sys.exit(1)
    
    # Auto-snapshot before rollback
    snapshot(merge_path, 'pre_rollback')
    shutil.copy2(target, merge_path)
    print(f'Rolled back to: {target.name}')


def list_versions(merge_path: str):
    index_path = get_version_dir(merge_path) / 'version_index.json'
    if not index_path.exists():
        print('No versions found')
        return
    
    index = json.loads(index_path.read_text())
    print(f'{"Version":<30} {"Mappings":>10}  Label')
    print('-' * 60)
    for v in index:
        print(f'{v["version"]:<30} {v["mappings"]:>10}  {v.get("label", "")}')


def main():
    parser = argparse.ArgumentParser(description='Merge map version management')
    sub = parser.add_subparsers(dest='command')
    
    snap = sub.add_parser('snapshot')
    snap.add_argument('--merge', required=True)
    snap.add_argument('--label')
    
    d = sub.add_parser('diff')
    d.add_argument('--v1', required=True)
    d.add_argument('--v2', required=True)
    
    m = sub.add_parser('merge')
    m.add_argument('--merge', required=True)
    m.add_argument('--delta', required=True)
    
    rb = sub.add_parser('rollback')
    rb.add_argument('--merge', required=True)
    rb.add_argument('--version', required=True)
    
    sub.add_parser('list').add_argument('--merge', required=True)
    
    args = parser.parse_args()
    
    if args.command == 'snapshot':
        snapshot(args.merge, args.label)
    elif args.command == 'diff':
        result = diff(args.v1, args.v2)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == 'merge':
        merge_delta(args.merge, args.delta)
    elif args.command == 'rollback':
        rollback(args.merge, args.version)
    elif args.command == 'list':
        list_versions(args.merge)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
