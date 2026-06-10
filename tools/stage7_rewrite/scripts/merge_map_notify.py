#!/usr/bin/env python3
"""Merge map change notifier: detect updates and reload CloudRun server.

Part of Atlas Three-DB Merge Pipeline — Task 5: Change Notification.

Checks merge_map modification time, compares with last-known state,
and triggers a server reload if changed.

Usage:
    python3 merge_map_notify.py --merge cross_db_merge_map.json --state .merge_map_state.json
    
    # Or with auto-reload:
    python3 merge_map_notify.py --merge cross_db_merge_map.json --state .merge_map_state.json --reload
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_file_hash(path: str) -> str:
    """SHA256 hash of file contents."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def get_state(state_path: str) -> dict:
    """Load last-known state."""
    if os.path.exists(state_path):
        with open(state_path) as f:
            return json.load(f)
    return {'last_hash': '', 'last_mtime': 0, 'last_mappings': 0}


def save_state(state_path: str, state: dict):
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


def reload_cloudrun():
    """Restart the CloudRun server in WSL to pick up new merge_map."""
    try:
        # Find and kill existing server
        result = subprocess.run(
            ['wsl', '-e', 'bash', '-c', "ss -tlnp | grep 8787 | awk '{print $NF}' | grep -oP 'pid=\\K\\d+'"],
            capture_output=True, text=True, timeout=10
        )
        pid = result.stdout.strip()
        if pid:
            subprocess.run(['wsl', '-e', 'bash', '-c', f'kill {pid}'], timeout=5)
        
        # Restart
        subprocess.run([
            'wsl', '-e', 'bash', '-c',
            'cd /mnt/c/code/githubstar/wechathtmldownload/services/weekly_activity_cloudrun && '
            'setsid node src/server.mjs </dev/null >/tmp/cloudrun_reload.log 2>&1 & disown'
        ], timeout=10)
        print('[notify] CloudRun server reloaded', file=sys.stderr)
        return True
    except Exception as e:
        print(f'[notify] Reload failed: {e}', file=sys.stderr)
        return False


def check_merge_map(merge_path: str) -> dict:
    """Check current state of merge_map."""
    stat = os.stat(merge_path)
    hash_val = get_file_hash(merge_path)
    with open(merge_path) as f:
        data = json.load(f)
    mappings = len(data.get('db2_to_db3_map', {}))
    
    return {
        'hash': hash_val,
        'mtime': int(stat.st_mtime),
        'mappings': mappings,
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description='Check merge_map for changes')
    parser.add_argument('--merge', required=True, help='Path to cross_db_merge_map.json')
    parser.add_argument('--state', default='.merge_map_state.json', help='State tracking file')
    parser.add_argument('--reload', action='store_true', help='Auto-reload CloudRun on change')
    args = parser.parse_args()

    old_state = get_state(args.state)
    current = check_merge_map(args.merge)
    
    changed = (current['hash'] != old_state.get('last_hash', '') or
               current['mtime'] != old_state.get('last_mtime', 0))
    
    result = {
        'changed': changed,
        'previous': {
            'mappings': old_state.get('last_mappings', 0),
            'mtime': old_state.get('last_mtime', 0),
        },
        'current': current,
        'delta': 0,
    }
    
    if changed and old_state.get('last_mappings', 0) > 0:
        delta = current['mappings'] - old_state.get('last_mappings', 0)
        result['delta'] = delta
        print(f'CHANGE DETECTED: {delta:+d} mappings ({old_state["last_mappings"]} → {current["mappings"]})', file=sys.stderr)
        
        if args.reload:
            success = reload_cloudrun()
            result['reloaded'] = success
            if success:
                print('CloudRun reloaded with new merge_map', file=sys.stderr)
    else:
        print(f'No change ({current["mappings"]} mappings)', file=sys.stderr)
    
    save_state(args.state, current)
    print(json.dumps(result, indent=2))
    
    return 0 if not changed else 1


if __name__ == '__main__':
    sys.exit(main())
