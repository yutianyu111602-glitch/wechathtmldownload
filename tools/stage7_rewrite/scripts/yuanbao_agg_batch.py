#!/usr/bin/env python3
"""
Batch process parent articles through yuanbao (via opencli).
Extracts structured event info, matches to agg-children, updates poster assignments.
"""
import json, pathlib, subprocess, sys, re, time

REPO = pathlib.Path(r"C:\code\githubstar\wechathtmldownload")
CURRENT = REPO / "services/weekly_activity_cloudrun/data/current_release"
OUT_DIR = pathlib.Path(r"D:\downstream_results\stage7_rewrite\longrun\agg_child_recovery_20260607")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 4 key overview articles (the ones most likely to be weekly/monthly summaries)
ARTICLES = [
    ("Dada Beijing weekly", "https://mp.weixin.qq.com/s/xf1epKmpnP9YwYetwFTaXw"),
    ("OIL weekly", "https://mp.weixin.qq.com/s/Y4MYmn5aB-yqzfN8ut3CXQ"),
    ("loopy weekly", "https://mp.weixin.qq.com/s/sCkHCA_OK7mhmdQPHZ-_9g"),
    ("wigwam weekly", "https://mp.weixin.qq.com/s/GYFC3Ie5h3fIRPP92_yNeg"),
]

# Build yuanbao prompts for batch processing
prompts = []
for name, url in ARTICLES:
    prompt = f"""请读取这篇微信公众号文章，提取里面列出的所有活动信息。

要求：
1. 如果文章是"本周活动一览"或"活动预告"类型，提取每天的活动
2. 如果文章是单个活动，只提取该活动
3. 输出严格的JSON格式，不要补充文章外信息
4. 如果有多个活动，每个活动包含：日期、活动标题、DJ/嘉宾、海报图片描述

JSON格式：
{{"article_type": "weekly_overview|single_event", "venue": "场地名", "events": [{{"date": "日期", "title": "活动标题", "dj": ["DJ1","DJ2"], "ticket": "票价"}}]}}

文章：{url}"""
    prompts.append((name, prompt))

results = {}
for name, prompt in prompts:
    print(f"\n{'='*60}")
    print(f"Processing: {name}")
    print(f"{'='*60}")
    try:
        result = subprocess.run(
            ["opencli", "yuanbao", "ask", prompt],
            capture_output=True, text=True, timeout=180, cwd=str(REPO)
        )
        text = result.stdout + "\n" + result.stderr
        # Extract JSON from yuanbao response
        json_blocks = re.findall(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        json_blocks += re.findall(r'\{[^{}]*"article_type"[^{}]*\}', text, re.DOTALL)
        
        parsed = None
        for block in json_blocks:
            try:
                parsed = json.loads(block)
                break
            except:
                continue
        
        if parsed:
            results[name] = parsed
            n_events = len(parsed.get("events", []))
            print(f"Events found: {n_events}")
            for ev in parsed.get("events", [])[:5]:
                print(f"  {ev.get('date','?')} | {ev.get('title','?')[:50]}")
        else:
            results[name] = {"raw": text[:2000]}
            print(f"No JSON extracted. Raw preview: {text[:300]}")
        
        time.sleep(3)  # Rate limit between calls
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT: {name}")
        results[name] = {"error": "timeout"}
    except Exception as e:
        print(f"ERROR: {name} - {e}")
        results[name] = {"error": str(e)}

# Save results
(OUT_DIR / "yuanbao_article_analysis.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

# Load agg-children for matching
items_data = json.loads((CURRENT / "current.json").read_text(encoding="utf-8"))
agg_children = [i for i in items_data["items"] if i.get("id", "").startswith("agg-child-")]
print(f"\n{len(agg_children)} agg-children to match")

# Match yuanbao events to agg-children
matches = []
for child in agg_children:
    cid = child["id"]
    ctitle = (child.get("title") or "").lower()
    cdate = child.get("event_date_start", "")
    caccount = (child.get("source_account_name") or "").lower()
    
    best_match = None
    best_score = 0
    
    for name, data in results.items():
        if not isinstance(data, dict) or "events" not in data:
            continue
        for ev in data.get("events", []):
            etitle = (ev.get("title") or ev.get("event_title") or "").lower()
            edate = (ev.get("date") or "")
            # Normalize date
            edate_clean = re.sub(r'[^\d-]', '', edate)[:10]
            
            score = 0
            # Date match
            if cdate and edate_clean and cdate in edate_clean:
                score += 10
            # Title word overlap
            ct_words = set(re.findall(r'\w+', ctitle))
            et_words = set(re.findall(r'\w+', etitle))
            overlap = ct_words & et_words
            if len(overlap) >= 2:
                score += len(overlap) * 3
            
            if score > best_score:
                best_score = score
                best_match = {"article": name, "event": ev, "score": score}
    
    matches.append({
        "child_id": cid,
        "child_title": child.get("title", ""),
        "child_date": cdate,
        "best_score": best_score,
        "match": best_match,
    })
    status = "MATCHED" if best_score >= 8 else "WEAK" if best_score > 0 else "NONE"
    print(f"  {cid} score={best_score:2d} {status} | {child.get('title','')[:50]}")

(OUT_DIR / "yuanbao_agg_child_matches.json").write_text(
    json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")

matched = sum(1 for m in matches if m["best_score"] >= 8)
print(f"\nMatched: {matched}/{len(matches)}")
