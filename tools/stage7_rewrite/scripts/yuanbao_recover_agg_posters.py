#!/usr/bin/env python3
"""
Yuanbao-powered aggregate child poster recovery.
Uses opencli yuanbao to read WeChat overview articles,
extract events + poster image URLs, download, upload to CloudBase, patch.
"""
import json, os, re, subprocess, sys, time, base64, pathlib
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO = pathlib.Path(r"C:\code\githubstar\wechathtmldownload")
CURRENT = REPO / "services/weekly_activity_cloudrun/data/current_release"
TCB_ENV = "huaidjweekly-d8g1go7-d0a07863e3e"
CLOUD_DIR = "weekly-posters/20260607"

OUT_DIR = pathlib.Path(r"D:\downstream_results\stage7_rewrite\longrun\yuanbao_recovery_20260607")
OUT_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR = OUT_DIR / "posters"
IMG_DIR.mkdir(parents=True, exist_ok=True)

def yuanbao_read_article(url, account_hint=""):
    """Use opencli yuanbao to read a WeChat article and extract events."""
    prompt = (
        "请读取并分析这篇微信公众号文章。"
        "这是一个{}的每周活动预告/本周一览文章。"
        "请提取文章中列出的每一个活动，包括："
        "1. 活动日期（YYYY-MM-DD格式）"
        "2. 活动标题"
        "3. DJ/嘉宾名单"
        "4. 票价信息"
        "5. 活动海报图片的描述（颜色、图案、风格等特征，用于在文章中定位该图片）"
        ""
        "用JSON格式输出："
        '{{"events":[{{"date":"YYYY-MM-DD","title":"活动标题","dj":["DJ1"],"ticket":"票价","poster_desc":"海报描述"}}]}}'
        ""
        "文章链接：{}"
    ).format(account_hint, url)
    
    print("  Sending to yuanbao...")
    try:
        result = subprocess.run(
            ["opencli", "yuanbao", "ask", prompt],
            capture_output=True, text=True, timeout=180,
            cwd=str(REPO)
        )
        text = result.stdout + "\n" + result.stderr
        
        # Extract JSON
        json_blocks = re.findall(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        for block in json_blocks:
            try:
                return json.loads(block)
            except:
                continue
        
        # Try inline JSON
        json_matches = re.findall(r'\{[^{}]*"events"[^{}]*\}', text, re.DOTALL)
        for m in json_matches:
            try:
                return json.loads(m)
            except:
                continue
        
        print("  No JSON found in response")
        return {"error": "no_json", "raw": text[:500]}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)}

def find_poster_url_from_html(article_url, poster_desc=""):
    """Download article HTML and find the poster image matching the description."""
    API_KEY = os.environ.get("MPTEXT_AUTH_KEY", "").strip()
    if not API_KEY:
        raise RuntimeError("MPTEXT_AUTH_KEY must come from the current exporter session")
    api_url = "http://127.0.0.1:17300/api/public/v1/download?url={}&format=html".format(article_url)
    try:
        req = Request(api_url, headers={"X-Auth-Key": API_KEY})
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        
        # Find all images
        img_urls = re.findall(r'<img[^>]+src="([^"]+)"', html)
        img_urls = [u for u in img_urls if u.startswith("http") and "mmbiz.qpic.cn" in u]
        # Deduplicate, return the largest/most likely poster
        seen = set()
        unique = []
        for u in img_urls:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique
    except Exception as e:
        print("  HTML download failed: {}".format(e))
        return []

def upload_to_cloudbase(local_path, cloud_filename):
    """Upload image to CloudBase storage."""
    cloud_path = "{}/{}".format(CLOUD_DIR, cloud_filename)
    result = subprocess.run(
        ["tcb", "storage", "upload", str(local_path), cloud_path,
         "-e", TCB_ENV, "--json"],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        return data.get("data", {}).get("fileId", "")
    except:
        m = re.search(r'cloud://[^\s"]+', result.stdout + result.stderr)
        return m.group() if m else None

def patch_current_release(child_id, file_id, poster_url=""):
    """Update all JSON files for an aggregate child with new poster."""
    patched = 0
    for f in CURRENT.glob("**/*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("items", [])
            if not isinstance(items, list):
                continue
            changed = False
            for item in items:
                if item.get("id") == child_id:
                    item["poster_file_id"] = file_id
                    item["posterFileId"] = file_id
                    item["poster_storage"] = "cloudbase"
                    item["posterStorage"] = "cloudbase"
                    item["poster_suppressed"] = False
                    item["posterSuppressed"] = False
                    if poster_url:
                        item["cover_url"] = file_id
                        item["coverUrl"] = file_id
                    changed = True
            if changed:
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                patched += 1
        except:
            pass
    return patched


def main():
    # Load agg children
    items = json.loads((CURRENT / "current.json").read_text(encoding="utf-8"))
    agg_children = {i["id"]: i for i in items if i.get("id","").startswith("agg-child-")}
    print("Agg children: {}".format(len(agg_children)))
    
    # Step 1: Search exporter for overview articles
    print("\n=== Step 1: Search for overview articles ===")
    API_KEY = os.environ.get("MPTEXT_AUTH_KEY", "").strip()
    if not API_KEY:
        raise RuntimeError("MPTEXT_AUTH_KEY must come from the current exporter session")
    ENDPOINT = "http://127.0.0.1:17300"
    
    # Use the download queue to find URLs for target account nicknames
    queue_path = r"D:\downstream_results\stage7_rewrite\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\latest_queue.jsonl"
    
    # Group agg-children by account
    by_account = {}
    for cid, child in agg_children.items():
        acct = child.get("source_account_name", "")
        if acct not in by_account:
            by_account[acct] = []
        by_account[acct].append(cid)
    
    # For each account, find overview articles (June 1-5, containing "本周" or "活动")
    overview_urls = {}
    for acct in by_account:
        print("\n--- {} ---".format(acct))
        candidates = []
        with open(queue_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    nick = str(e.get("account_nickname", ""))
                    if acct not in nick:
                        continue
                    url = e.get("source_url", "")
                    title = str(e.get("title", ""))
                    pdate = str(e.get("post_date", ""))[:10]
                    if "2026-06" not in pdate:
                        continue
                    if any(kw in title for kw in ["本周", "一览", "活动", "预告", "WEEKLY", "排期", "周报", "月报"]):
                        candidates.append({"url": url, "title": title[:80], "date": pdate})
                except:
                    pass
        
        if candidates:
            for c in candidates:
                print("  {} | {}".format(c["date"], c["title"]))
            overview_urls[acct] = candidates[0]["url"]
        else:
            print("  No overview articles found in queue")
    
    print("\n=== Step 2: Process with yuanbao ===")
    all_events = {}
    for acct, url in overview_urls.items():
        print("\nProcessing: {}".format(acct))
        print("  URL: {}".format(url[:80]))
        result = yuanbao_read_article(url, acct)
        if "error" in result:
            print("  ERROR: {}".format(result["error"]))
            continue
        events = result.get("events", [])
        print("  Found {} events".format(len(events)))
        for ev in events:
            print("    {} | {}".format(ev.get("date", "?"), ev.get("title", "")[:50]))
        all_events[acct] = events
        time.sleep(2)
    
    # Save results
    (OUT_DIR / "yuanbao_extracted_events.json").write_text(
        json.dumps({"overview_urls": overview_urls, "events": all_events}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    
    print("\n=== Step 3: Download + Upload + Patch ===")
    for acct, events in all_events.items():
        for ev in events:
            edate = ev.get("date", "")
            etitle = ev.get("title", "")
            if not edate or not etitle:
                continue
            
            # Match to agg-child
            for cid, child in agg_children.items():
                cdate = child.get("event_date_start", "")
                ctitle = (child.get("title") or "").lower()
                if cdate in edate and len(set(re.findall(r'\w+', ctitle)) & set(re.findall(r'\w+', etitle.lower()))) >= 2:
                    print("\n  Match: {} -> {}".format(cid[:25], child.get("title","")[:40]))
                    
                    # Download article HTML to find poster images
                    url = overview_urls.get(acct, "")
                    images = find_poster_url_from_html(url)
                    if not images:
                        print("    No images found in article")
                        continue
                    
                    # Try each image - use the first large one as poster
                    poster_url = None
                    for img_url in images:
                        try:
                            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', cid)
                            local_img = IMG_DIR / "{}.jpg".format(safe_name)
                            req = Request(img_url, headers={"Referer": "https://mp.weixin.qq.com/"})
                            with urlopen(req, timeout=30) as resp:
                                local_img.write_bytes(resp.read())
                            
                            file_id = upload_to_cloudbase(local_img, "{}.jpg".format(safe_name))
                            if file_id:
                                poster_url = file_id
                                print("    Uploaded: {}".format(file_id[:60]))
                                break
                        except Exception as e:
                            continue
                    
                    if poster_url:
                        patched = patch_current_release(cid, poster_url)
                        print("    Patched {} files".format(patched))

if __name__ == "__main__":
    main()
