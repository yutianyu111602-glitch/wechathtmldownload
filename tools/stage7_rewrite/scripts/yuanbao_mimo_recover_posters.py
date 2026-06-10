#!/usr/bin/env python3
"""
Use yuanbao (via opencli) to extract events + poster images from WeChat articles,
then match to aggregate children and patch current_release.
"""
import json, os, re, subprocess, sys, time, base64, pathlib
from urllib.request import Request, urlopen
from collections import defaultdict

REPO = pathlib.Path(r"C:\code\githubstar\wechathtmldownload")
CURRENT = REPO / "services/weekly_activity_cloudrun/data/current_release"
IMG_DIR = pathlib.Path(r"D:\downstream_results\stage7_rewrite\longrun\agg_child_recovery_20260607\yuanbao_posters")
IMG_DIR.mkdir(parents=True, exist_ok=True)
TASK_DIR = pathlib.Path(r"D:\downstream_results\stage7_rewrite\longrun\agg_child_recovery_20260607")

# TCB config
TCB_ENV = "huaidjweekly-d8g1go7-d0a07863e3e"
CLOUD_DIR = "weekly-posters/20260607"

os.environ["MIMO_API_KEY"] = os.environ.get("MIMO_API_KEY", "sk-cd29e1ac-5ce7-4bb5-b2e8-ae532b54a234")
MIMO_KEY = os.environ["MIMO_API_KEY"]
MIMO_BASE = "https://api.xiaomimimo.com/v1"
MIMO_MODEL = "mimo-v2.5"

# The 4 key parent articles per account
ARTICLES = {
    "dada": "https://mp.weixin.qq.com/s/xf1epKmpnP9YwYetwFTaXw",
    "oil": "https://mp.weixin.qq.com/s/Y4MYmn5aB-yqzfN8ut3CXQ",
    "loopy": "https://mp.weixin.qq.com/s/sCkHCA_OK7mhmdQPHZ-_9g",
    "wigwam": "https://mp.weixin.qq.com/s/GYFC3Ie5h3fIRPP92_yNeg",
}

# Load agg children
items_data = json.loads((CURRENT / "current.json").read_text(encoding="utf-8"))
agg_children = [i for i in items_data["items"] if i.get("id", "").startswith("agg-child-")]
print("{} aggregate children to fix".format(len(agg_children)))

# Step 1: Extract images from already-downloaded HTMLs
print("\n--- Step 1: Extract images from HTML ---")
article_images = defaultdict(list)
for hf in sorted((TASK_DIR).glob("*.html")):
    html = hf.read_text(encoding="utf-8", errors="ignore")
    img_urls = re.findall(r'<img[^>]+src="([^"]+)"', html)
    img_urls += re.findall(r"<img[^>]+src='([^']+)'", html)
    img_urls = [u for u in img_urls if u.startswith("http") and not u.startswith("data:")]
    account = hf.stem.split("_")[0]
    seen = set()
    for u in img_urls:
        if u not in seen:
            seen.add(u)
            article_images[account].append(u)
    print("  {}: {} images from {}".format(account, len(article_images[account]), hf.stem))

# Flatten all image URLs
all_img_urls = []
for acct, urls in article_images.items():
    for u in urls:
        all_img_urls.append({"account": acct, "url": u})

print("Total images to process: {}".format(len(all_img_urls)))

# Step 2: MiMo classify each image (fast batch)
print("\n--- Step 2: MiMo image classification ---")
def mimo_classify(url, idx):
    """Quick MiMo classification of one image by URL."""
    try:
        req = Request(url, headers={"Referer": "https://mp.weixin.qq.com/"})
        with urlopen(req, timeout=20) as resp:
            img_data = base64.b64encode(resp.read()).decode("utf-8")
    except:
        return {"is_event_poster": False, "image_role": "download_failed"}
    
    prompt = """判断这张图片类型。只输出JSON：{"is_event_poster":true/false,"image_role":"main_poster|qr_code|logo|menu|schedule|decorative|ticket","event_title":"标题","event_date":"日期","venue":"场地"}。如果是日程表/一览表/schedule类型，image_role="schedule"、is_event_poster=false。"""
    
    payload = {
        "model": MIMO_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_data}"}}
        ]}],
        "max_completion_tokens": 512, "temperature": 0.1,
    }
    
    try:
        req = Request(f"{MIMO_BASE}/chat/completions",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {MIMO_KEY}"})
        with urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        content = result["choices"][0]["message"]["content"]
        m = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            parsed["_url"] = url
            return parsed
    except Exception as e:
        pass
    return {"is_event_poster": False, "image_role": "error", "_url": url}

mimo_results = []
for idx, img in enumerate(all_img_urls):
    result = mimo_classify(img["url"], idx)
    result["account"] = img["account"]
    mimo_results.append(result)
    role = result.get("image_role", "?")
    is_poster = "P" if result.get("is_event_poster") else " "
    if idx % 5 == 0 or idx == len(all_img_urls) - 1:
        print("  [{}/{}] {} {}".format(idx+1, len(all_img_urls), is_poster, role))

posters = [r for r in mimo_results if r.get("is_event_poster")]
non_posters = [r for r in mimo_results if not r.get("is_event_poster")]
print("Posters: {}  Non-posters: {}".format(len(posters), len(non_posters)))

# Step 3: Match MiMo-classified images to agg children
print("\n--- Step 3: Match images to agg children ---")
matches = []
for child in agg_children:
    cid = child["id"]
    ctitle = (child.get("title") or "").lower()
    cdate = child.get("event_date_start", "")
    caccount = (child.get("source_account_name") or "").lower()
    
    best_score = -1
    best_posters = []
    
    for p in posters:
        acct = p.get("account", "")
        ptitle = (p.get("event_title") or "").lower()
        pdate = p.get("event_date") or ""
        pvenue = (p.get("venue") or "").lower()
        
        # Account filter: match account prefix
        if acct:
            if acct not in caccount and caccount not in acct:
                continue
        
        score = 0
        # Date match
        if cdate and pdate:
            cdate_clean = cdate.replace("-", "")
            pdate_clean = re.sub(r'[^\d]', '', pdate)
            if cdate_clean and pdate_clean and cdate_clean in pdate_clean:
                score += 10
        # Title word overlap
        ct_words = set(re.findall(r'\w+', ctitle))
        pt_words = set(re.findall(r'\w+', ptitle))
        overlap = ct_words & pt_words
        score += len(overlap) * 3
        
        if score > best_score:
            best_score = score
            best_posters = [p]
        elif score == best_score and score > 0:
            best_posters.append(p)
    
    match_info = {
        "child_id": cid, "child_title": child.get("title", ""), "child_date": cdate,
        "best_score": best_score, "matched_posters": best_posters[:1]
    }
    matches.append(match_info)
    status = "MATCHED" if best_score >= 8 else "WEAK" if best_score > 0 else "NONE"
    print("  {} score={:2d} {} | {}".format(cid[:20], best_score, status, child.get("title","")[:50]))

# Step 4: Download best-matched poster, upload to CloudBase, patch current_release
print("\n--- Step 4: Download + Upload + Patch ---")
patched = 0
for m in matches:
    if m["best_score"] < 8 or not m["matched_posters"]:
        continue
    
    poster = m["matched_posters"][0]
    img_url = poster.get("_url", "")
    if not img_url:
        continue
    
    cid = m["child_id"]
    child_file = CURRENT / "by-id" / "{}.json".format(cid)
    if not child_file.exists():
        continue
    
    # Download poster image
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', cid)
    local_img = IMG_DIR / "{}.jpg".format(safe_id)
    try:
        req = Request(img_url, headers={"Referer": "https://mp.weixin.qq.com/"})
        with urlopen(req, timeout=30) as resp:
            local_img.write_bytes(resp.read())
    except Exception as e:
        print("  {} download failed: {}".format(cid[:30], e))
        continue
    
    # Upload to CloudBase
    cloud_path = "{}/{}.jpg".format(CLOUD_DIR, safe_id)
    result = subprocess.run(
        ["tcb", "storage", "upload", str(local_img), cloud_path,
         "-e", TCB_ENV, "--json"],
        capture_output=True, text=True, timeout=60
    )
    
    if result.returncode != 0:
        print("  {} upload failed".format(cid[:30]))
        continue
    
    # Parse file ID
    try:
        upload_data = json.loads(result.stdout)
        file_id = upload_data.get("data", {}).get("fileId", "")
    except:
        file_id = ""
    
    if not file_id:
        # Try extracting from error/stdout
        match = re.search(r'cloud://[^\s"]+', result.stdout + result.stderr)
        if match:
            file_id = match.group()
    
    if not file_id:
        print("  {} no file_id in response".format(cid[:30]))
        continue
    
    print("  {} -> {}".format(cid[:30], file_id[:60]))
    
    # Patch all JSON files for this item
    for f in CURRENT.glob("**/*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else data.get("items", [])
            if not isinstance(items, list):
                continue
            changed = False
            for item in items:
                if item.get("id") == cid:
                    item["poster_file_id"] = file_id
                    item["posterFileId"] = file_id
                    item["poster_storage"] = "cloudbase"
                    item["posterStorage"] = "cloudbase"
                    item["poster_suppressed"] = False
                    item["posterSuppressed"] = False
                    if not item.get("cover_url") or "cloud://" not in str(item.get("cover_url", "")):
                        item["cover_url"] = file_id
                        item["coverUrl"] = file_id
                    changed = True
            if changed:
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                patched += 1
        except:
            pass

print("\nPatched: {} files".format(patched))

# Verify
items_data = json.loads((CURRENT / "current.json").read_text(encoding="utf-8"))
agg_fixed = sum(1 for i in items_data["items"] 
    if i.get("id","").startswith("agg-child-") 
    and "cloud://" in str(i.get("poster_file_id","")))
print("Agg children with CloudBase poster: {}/{}".format(agg_fixed, len(agg_children)))
