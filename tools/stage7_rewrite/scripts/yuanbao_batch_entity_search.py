#!/usr/bin/env python3
"""Batch entity classification via Yuanbao PC client.

Reads yuanbao_search_queue.json, asks Yuanbao about each entity,
saves results incrementally, supports resume.

Rate limit: 60-120s per query, 40/day max.
"""

import json
import sys
import time
import random
import os
from pathlib import Path
from datetime import datetime

# Paths
SCRIPT_DIR = Path(__file__).parent
REPO = SCRIPT_DIR.parent.parent.parent
REPORT_DIR = REPO / 'tools/stage7_rewrite/reports/cross_db_identity_resolution_20260608'
QUEUE_FILE = REPORT_DIR / 'yuanbao_search_queue.json'
RESULTS_FILE = REPORT_DIR / 'yuanbao_entity_results.jsonl'

# Safety
MIN_INTERVAL = 65
MAX_DAILY = 40


def load_queue():
    with open(QUEUE_FILE, encoding='utf-8') as f:
        return json.load(f)


def load_completed_eids():
    """Load already-processed EIDs from results file."""
    done = set()
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                        if r.get('eid'):
                            done.add(r['eid'])
                    except json.JSONDecodeError:
                        pass
    return done


def save_result(result):
    """Append one result to JSONL file."""
    with open(RESULTS_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(result, ensure_ascii=False) + '\n')


def build_prompt(entity):
    """Build a search prompt for Yuanbao."""
    name = entity.get('entity_name') or entity.get('primary_name') or ''
    handles = entity.get('handles', [])[:3]
    platforms = entity.get('platforms', [])[:5]
    
    prompt = f'请搜索：在电子音乐/夜生活场景中，"{name}"'
    
    if handles:
        h_str = '、'.join(handles[:3])
        prompt += f'（相关账号：{h_str}）'
    
    prompt += '是什么身份？是DJ、俱乐部/场地、厂牌、还是其他？请简短回答：类型+中文名+一句话描述。'
    return prompt


def count_today_queries():
    """Count queries made today from results file."""
    today = datetime.now().strftime('%Y-%m-%d')
    count = 0
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        r = json.loads(line)
                        if r.get('timestamp', '').startswith(today):
                            count += 1
                    except json.JSONDecodeError:
                        pass
    return count


def main():
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 38
    start_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    
    queue = load_queue()
    done = load_completed_eids()
    today_count = count_today_queries()
    
    remaining = MAX_DAILY - today_count
    batch_size = min(batch_size, remaining)
    
    # Filter to unprocessed entities
    todo = [(i, e) for i, e in enumerate(queue) if e['eid'] not in done]
    
    if start_idx > 0:
        todo = todo[start_idx:]
    
    print(f'Queue: {len(queue)} total, {len(done)} done, {len(todo)} remaining')
    print(f'Today: {today_count}/{MAX_DAILY}, will process: {batch_size}')
    print(f'Results: {RESULTS_FILE}')
    print()
    
    if batch_size <= 0:
        print('Daily limit reached. Come back tomorrow.')
        return
    
    # Import YuanbaoPC
    sys.path.insert(0, str(SCRIPT_DIR))
    from yuanbao_pc_client import YuanbaoPC
    
    yb = YuanbaoPC()
    results = []
    
    for idx, (orig_i, entity) in enumerate(todo[:batch_size]):
        name = entity.get('entity_name') or entity.get('primary_name') or '?'
        eid = entity['eid']
        prompt = build_prompt(entity)
        
        print(f'[{idx+1}/{batch_size}] {name} (eid={eid[:8]}...)')
        
        try:
            result = yb.ask(prompt, new_chat=True, timeout=30, screenshot=True)
            result['eid'] = eid
            result['entity_name'] = name
            result['queue_index'] = orig_i
            save_result(result)
            results.append(result)
            print(f'  ✅ screenshot={result.get("screenshot_path","")}')
        except Exception as e:
            print(f'  ❌ {e}')
            save_result({
                'eid': eid,
                'entity_name': name,
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
            if 'Daily limit' in str(e):
                break
        
        # Rate limit
        if idx < batch_size - 1:
            wait = random.randint(MIN_INTERVAL, MIN_INTERVAL + 55)
            print(f'  ⏳ {wait}s...')
            time.sleep(wait)
    
    print(f'\nDone. Processed: {len(results)}, saved to {RESULTS_FILE}')


if __name__ == '__main__':
    main()
