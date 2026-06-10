#!/usr/bin/env python3
"""
Stage7 v4 Canary Runner - 安全参数 + retry逻辑 + v4 prompt
单卡4090 / Qwen3.6-27B / llama-swap
用法: python scripts/stage7/run_canary_v4.py --count 10
"""
import json, os, sys, time, re, subprocess, argparse
sys.stdout.reconfigure(line_buffering=True)

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "http://127.0.0.1:11434/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen36-27b-q4-stage7-nospec")
PROMPT_PATH = os.getenv("PROMPT_PATH", r"C:\code\githubstar\wechathtmldownload\prompts\downstream\event_extract_v4_zh.md")
INPUT_DIR = r"D:\DDownload\_llm_release_v2\articles"
OUTPUT_DIR = r"D:\downstream_results\stage7_v4_single_qwen_chunked_20260428"
CHUNK_TARGET, CHUNK_OVERLAP, HARD_MAX = 800, 120, 950
EMERGENCY, LAST_RESORT = 500, 350
MAX_TOKENS, TEMPERATURE = 768, 0.0
RETRY_BACKOFF = [5, 15, 45]
MAX_RETRIES = 3

def log(msg):
    t = time.strftime("%H:%M:%S")
    print(f"[{t}] {msg}", flush=True)

def chunk_text(text):
    chunks, start, idx = [], 0, 0
    while start < len(text):
        size = min(CHUNK_TARGET, HARD_MAX)
        chunk = text[start:start+size]
        if not chunk: break
        if len(chunk) < 50 and len(text)-start < 100:
            if chunks: chunks[-1]["text"] += chunk
            break
        chunks.append({"idx":idx,"start":start,"text":chunk,"chars":len(chunk),"degraded":False})
        idx += 1
        start += size - min(CHUNK_OVERLAP, size//2)
    if not chunks:
        chunks.append({"idx":0,"start":0,"text":text,"chars":len(text),"degraded":False})
    return chunks

def call_llm(text, system_prompt):
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role":"system","content":system_prompt},{"role":"user","content":text}],
        "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE, "stream": False
    }
    try:
        r = subprocess.run(["curl","-s","--max-time","180",LLM_ENDPOINT,
            "-H","Content-Type: application/json","-d",json.dumps(payload)],
            capture_output=True, text=True, timeout=200)
    except subprocess.TimeoutExpired: return "", "timeout"
    except Exception as e: return "", f"curl_error:{e}"
    if r.returncode != 0: return "", f"curl_exit_{r.returncode}"
    try: resp = json.loads(r.stdout)
    except json.JSONDecodeError: return "", f"non_json:{r.stdout[:200]}"
    if "error" in resp:
        err = resp["error"].get("message",str(resp["error"]))
        if "context" in err.lower() or "exceed" in err.lower(): return "", f"context_exceeded:{err}"
        return "", f"api_error:{err}"
    content = resp.get("choices",[{}])[0].get("message",{}).get("content","")
    return content, None

def call_with_retry(text, system_prompt, chunk_info):
    for attempt in range(1, MAX_RETRIES+2):
        content, error = call_llm(text, system_prompt)
        if error is None: return content, None, attempt
        if "context_exceeded" in error and attempt <= MAX_RETRIES:
            wait = RETRY_BACKOFF[min(attempt-1, len(RETRY_BACKOFF)-1)]
            log(f"  RETRY {attempt}/{MAX_RETRIES} ctx_exceeded, wait {wait}s")
            time.sleep(wait)
            continue
        if "context_exceeded" in error and attempt > MAX_RETRIES:
            c = chunk_info.get("chars", len(text))
            if c > LAST_RESORT:
                new_c = EMERGENCY if c >= EMERGENCY else LAST_RESORT
                log(f"  DEGRADE {c}->{new_c}c")
                chunk_info["chars"] = new_c
                return call_with_retry(text[:new_c], system_prompt, chunk_info)
            break
        break
    return "", error, MAX_RETRIES+1

def merge_results(results):
    merged = {"article_id":"","source":{"title":"","account":"","published_at":""},
              "entities":[],"events":[],"relations":[],"warnings":[],"errors":[]}
    seen_ent, seen_evt = {}, set()
    for r in results:
        if not isinstance(r,dict): continue
        if not merged["source"]["title"] and r.get("source",{}).get("title"):
            merged["source"] = r["source"]
        if not merged["article_id"] and r.get("article_id"):
            merged["article_id"] = r["article_id"]
        for e in r.get("entities",[]):
            n = e.get("name","").strip()
            if not n: continue
            key = n.lower()
            if key in seen_ent:
                idx = seen_ent[key]
                existing = merged["entities"][idx]
                exist_q = {ev.get("quote","") for ev in existing.get("evidence",[])}
                for ev in e.get("evidence",[]):
                    if ev.get("quote","") not in exist_q:
                        existing.setdefault("evidence",[]).append(ev)
            else:
                seen_ent[key] = len(merged["entities"])
                merged["entities"].append(e)
        for ev in r.get("events",[]):
            if ev.get("name") and ev["name"] not in seen_evt:
                seen_evt.add(ev["name"])
                merged["events"].append(ev)
        merged["relations"].extend(r.get("relations",[]))
        merged["warnings"].extend(r.get("warnings",[]))
        merged["errors"].extend(r.get("errors",[]))
    return merged

def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*","",text,flags=re.IGNORECASE)
    text = re.sub(r"\s*```$","",text)
    s, e = text.find("{"), text.rfind("}")
    return text[s:e+1] if s>=0 and e>s else text

def process_article(text, article_id="", account="", title="", published_at=""):
    with open(PROMPT_PATH, 'r', encoding='utf-8') as f:
        system_prompt = f.read()
    chunks = chunk_text(text)
    log(f"  Chunks: {len(chunks)}")
    chunk_results = []
    for i, ci in enumerate(chunks):
        log(f"  Chunk {i+1}/{len(chunks)}: {ci['chars']}c")
        content, error, attempts = call_with_retry(ci["text"], system_prompt, ci)
        if error:
            log(f"    FAIL after {attempts}a: {error[:60]}")
            chunk_results.append({"article_id":article_id,"source":{"title":title},"entities":[],"events":[],"relations":[],"warnings":[f"chunk_{i}_fail:{error}"],"errors":[error]})
            continue
        try:
            result = json.loads(extract_json(content))
            if not isinstance(result,dict): raise ValueError("not dict")
        except Exception as e:
            log(f"    PARSE FAIL: {e}")
            chunk_results.append({"article_id":article_id,"source":{"title":title},"entities":[],"events":[],"warnings":[f"chunk_{i}_parse_fail:{e}"],"errors":[f"parse_fail:{e}"]})
            continue
        if not result.get("article_id"): result["article_id"] = article_id
        if not result.get("source",{}).get("title"): result.setdefault("source",{})["title"] = title
        ent, evt = len(result.get("entities",[])), len(result.get("events",[]))
        log(f"    OK entities={ent} events={evt} attempts={attempts}")
        chunk_results.append(result)
    merged = merge_results(chunk_results)
    merged["article_id"] = article_id or merged["article_id"]
    if not merged["source"]["title"]:
        merged["source"] = {"title":title,"account":account,"published_at":published_at}
    merged["_meta"] = {"chunks":len(chunks),"ok_chunks":sum(1 for r in chunk_results if not r.get("errors")),"total_chars":len(text)}
    return merged

def collect_articles(count=10):
    """Walk INPUT_DIR recursively, collect .md files."""
    articles = []
    for root, dirs, files in os.walk(INPUT_DIR):
        for f in files:
            if not f.endswith(('.md','.txt')): continue
            fpath = os.path.join(root, f)
            rel = os.path.relpath(fpath, INPUT_DIR)
            parts = rel.split(os.sep)
            acct = parts[0] if len(parts) > 1 else "unknown"
            art_id = parts[1] if len(parts) > 1 else f.replace('.md','')
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                    text = fh.read()
                if len(text) < 50: continue
                articles.append({
                    "text": text,
                    "id": art_id,
                    "account": acct,
                    "title": f,
                    "published_at": ""
                })
                if len(articles) >= count: break
            except: continue
        if len(articles) >= count: break
    return articles

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--output", default=OUTPUT_DIR)
    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)
    
    log(f"Loading prompt from {PROMPT_PATH}")
    log(f"Collecting {args.count} articles...")
    articles = collect_articles(args.count)
    log(f"Found {len(articles)} articles")
    if not articles: log("No articles found!"); return
    
    results, good, bad = [], 0, 0
    t0 = time.time()
    for i, a in enumerate(articles):
        log(f"[{i+1}/{len(articles)}] {a['account']}/{a['id']} ({len(a['text'])}c)")
        result = process_article(a["text"], a["id"], a["account"], a["title"])
        is_ok = not result.get("errors")
        if is_ok: good += 1
        else: bad += 1
        # Save individual result
        fname = f"{a['account']}_{a['id']}_v4.json".replace(" ","_").replace("/","_")
        fpath = os.path.join(args.output, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        results.append({"article":a['id'],"account":a['account'],"ok":is_ok,"entities":len(result.get("entities",[])),"events":len(result.get("events",[])),"errors":result.get("errors",[]),"warnings":result.get("warnings",[])})
    
    elapsed = time.time() - t0
    # Summary
    total_ent = sum(r["entities"] for r in results)
    total_evt = sum(r["events"] for r in results)
    report = {
        "canary":"v4","timestamp":time.strftime("%Y-%m-%d %H:%M:%S"),
        "count":len(articles),"good":good,"bad":bad,
        "elapsed_s":round(elapsed,1),"avg_s_per_article":round(elapsed/max(good+bad,1),1),
        "total_entities":total_ent,"total_events":total_evt,
        "avg_entities_per_article":round(total_ent/max(len(articles),1),1),
        "avg_events_per_article":round(total_evt/max(len(articles),1),1),
        "results":results
    }
    report_path = os.path.join(args.output, "CANARY_v4_REPORT.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"\n{'='*50}")
    log(f"Canary v4 complete: {good}/{good+bad} OK, {elapsed:.0f}s ({elapsed/max(good+bad,1):.1f}s/article)")
    log(f"Total entities: {total_ent}, Total events: {total_evt}")
    log(f"Avg entities/article: {total_ent/max(len(articles),1):.1f}")
    log(f"Report: {report_path}")
    log(f"{'='*50}")

if __name__ == "__main__":
    main()
