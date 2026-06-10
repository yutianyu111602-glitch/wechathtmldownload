#!/usr/bin/env python3
"""
Aggregate child poster recovery via MiMo vision.
Downloads article images, runs MiMo OCR/classification, matches to agg-child events.
"""
import json, os, re, sys, time, base64, pathlib
from urllib.request import Request, urlopen
from urllib.error import HTTPError

MIMO_KEY = os.environ.get("MIMO_VISION_API_KEY") or os.environ.get("MIMO_API_KEY") or ""
MIMO_BASE = os.environ.get("MIMO_VISION_BASE_URL") or "https://api.xiaomimimo.com/v1"
MIMO_MODEL = os.environ.get("MIMO_VISION_MODEL") or "mimo-v2.5"

REPO = pathlib.Path(r"C:\code\githubstar\wechathtmldownload")
CURRENT_RELEASE = REPO / "services/weekly_activity_cloudrun/data/current_release"
HTML_DIR = pathlib.Path(r"D:\downstream_results\stage7_rewrite\longrun\agg_child_recovery_20260607")
IMG_DIR = HTML_DIR / "images"
IMG_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR = pathlib.Path(r"D:\downstream_results\stage7_rewrite\reports\agg_child_ocr_recovery_20260607")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Load current release items to get agg-children
items_data = json.loads((CURRENT_RELEASE / "current.json").read_text(encoding="utf-8"))
all_items = items_data["items"]
agg_children = [i for i in all_items if i.get("id", "").startswith("agg-child-")]

print(f"Found {len(agg_children)} aggregate children")

# Step 1: Find all images from downloaded HTMLs
all_images = []
html_files = sorted(HTML_DIR.glob("*.html"))
for hf in html_files:
    html = hf.read_text(encoding="utf-8", errors="ignore")
    # Extract all img src
    img_urls = re.findall(r'<img[^>]+src="([^"]+)"', html)
    img_urls += re.findall(r"<img[^>]+src='([^']+)'", html)
    # Filter out data URLs
    img_urls = [u for u in img_urls if u.startswith("http") and not u.startswith("data:")]
    # Deduplicate
    seen = set()
    unique = []
    for u in img_urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    for u in unique:
        all_images.append({"article": hf.stem, "url": u, "local": None})

print(f"Total unique images: {len(all_images)}")

# Step 2: Download images
print("Downloading images...")
downloaded = []
for i, img in enumerate(all_images):
    try:
        req = Request(img["url"], headers={"Referer": "https://mp.weixin.qq.com/"})
        with urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 100:
            continue
        ext = ".jpg"
        ct = resp.headers.get("Content-Type", "")
        if "png" in ct:
            ext = ".png"
        elif "webp" in ct:
            ext = ".webp"
        local = IMG_DIR / f"{img['article']}_{i:03d}{ext}"
        local.write_bytes(data)
        img["local"] = str(local)
        img["size"] = len(data)
        downloaded.append(img)
        if i % 10 == 0:
            print(f"  {i+1}/{len(all_images)}...")
    except Exception as e:
        pass

print(f"Downloaded: {len(downloaded)}/{len(all_images)}")

# Step 3: Run MiMo on each image
print("\nRunning MiMo vision classification...")
if not MIMO_KEY:
    print("ERROR: MIMO_VISION_API_KEY not set")
    sys.exit(1)

# Import an httplib-based poster for MiMo
import urllib.request as ur

def mimo_classify_image(image_path, context_title="", context_venue="", context_date=""):
    """Classify a single image with MiMo vision."""
    try:
        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return {"error": str(e)}
    
    prompt = f"""你是一个活动海报分析助手。请判断这张图片是否是音乐/地下俱乐部活动的独立活动海报。

如果是活动海报，请提取以下信息（JSON格式）：
{{
  "is_event_poster": true/false,
  "image_role": "main_poster" | "secondary_poster" | "qr_code" | "logo" | "schedule_table" | "menu" | "map" | "avatar" | "decorative" | "ticket" | "venue_photo",
  "event_title": "从图片OCR提取的活动标题",
  "event_date": "YYYY-MM-DD格式的活动日期",
  "venue_name": "从图片OCR提取的场地名称",
  "city": "城市名",
  "lineup_artists": ["艺人名1", "艺人名2"],
  "is_overview_poster": true/false,
  "contains_qr_code": true/false,
  "image_description": "图片内容的简短描述"
}}

注意：
- main_poster = 单个活动的正式海报
- schedule_table = 本周/本月活动一览表（包含多个活动）
- 如果是QR码、Logo、菜单、地图、头像、装饰图，is_event_poster应为false
- 如果是日程表/一览表，is_event_poster为true，is_overview_poster为true"""
    
    payload = {
        "model": MIMO_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a poster analysis assistant. Always respond in valid JSON."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_data}"}}
                ]
            }
        ],
        "max_completion_tokens": 2048,
        "temperature": 0.1,
    }
    
    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{MIMO_BASE}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MIMO_KEY}"
            },
            method="POST"
        )
        with urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        
        content = result["choices"][0]["message"]["content"]
        # Try to parse JSON from content
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
        else:
            parsed = {"raw": content}
        parsed["mimo_model"] = MIMO_MODEL
        return parsed
    except Exception as e:
        return {"error": str(e)[:200]}

results = {}
POSTER_IMAGES = []
for idx, img in enumerate(downloaded):
    if img["size"] < 5000:  # Skip tiny images
        continue
    article = img["article"]
    result = mimo_classify_image(img["local"])
    result["local_path"] = img["local"]
    result["source_url"] = img["url"]
    result["article"] = article
    results[img["local"]] = result
    
    is_poster = result.get("is_event_poster", False)
    role = result.get("image_role", "unknown")
    
    if is_poster:
        POSTER_IMAGES.append(result)
    
    status = "POSTER" if is_poster else role
    title = result.get("event_title", "")[:40]
    print(f"  [{idx+1}/{len(downloaded)}] {status:20s} | {title}")

# Save all results
(OUT_DIR / "mimo_classification_results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

# Step 4: Match poster images to aggregate children
print(f"\n{len(POSTER_IMAGES)} poster images found. Matching to aggregate children...")

matches = []
for child in agg_children:
    child_id = child["id"]
    child_title = child.get("title", "")
    child_date = child.get("event_date_start", "")
    child_venue = child.get("venue_name", "") or child.get("venue", "")
    if isinstance(child_venue, list):
        child_venue = child_venue[0] if child_venue else ""
    child_city = child.get("city", [""])[0] if isinstance(child.get("city"), list) else child.get("city", "")
    
    best_score = 0
    best_img = None
    
    for img in POSTER_IMAGES:
        score = 0
        mi_title = (img.get("event_title") or "").lower()
        mi_venue = (img.get("venue_name") or "").lower()
        mi_date = img.get("event_date") or ""
        mi_city = (img.get("city") or "").lower()
        
        cv = str(child_venue).lower()
        ct = str(child_title).lower()
        cc = str(child_city).lower()
        
        # Title matching
        title_words = set(re.findall(r'\w+', ct))
        mi_words = set(re.findall(r'\w+', mi_title))
        if title_words and mi_words:
            overlap = title_words & mi_words
            score += len(overlap) * 3
        
        # Venue matching
        if cv and mi_venue and (cv in mi_venue or mi_venue in cv):
            score += 5
        
        # City matching
        if cc and mi_city and (cc in mi_city or mi_city in cc):
            score += 3
        
        # Date matching
        if child_date and mi_date and child_date in mi_date:
            score += 10
        
        if score > best_score:
            best_score = score
            best_img = img
    
    match = {
        "child_id": child_id,
        "child_title": child_title,
        "child_date": child_date,
        "child_venue": child_venue,
        "best_score": best_score,
        "matched_image": best_img["local_path"] if best_img else None,
        "matched_mimo": best_img if best_img else None,
    }
    matches.append(match)
    status = "MATCHED" if best_score >= 5 else "WEAK" if best_score > 0 else "NONE"
    print(f"  {child_id} score={best_score:2d} {status} | {child_title[:40]}")

# Save matches
(OUT_DIR / "agg_child_poster_matches.json").write_text(
    json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")

# Summary
matched = sum(1 for m in matches if m["best_score"] >= 5)
print(f"\n=== Results ===")
print(f"Images downloaded: {len(downloaded)}/{len(all_images)}")
print(f"Mimo classified: {len(results)}")
print(f"Poster images found: {len(POSTER_IMAGES)}")
print(f"Agg-children matched: {matched}/{len(matches)} (score >= 5)")
print(f"Reports: {OUT_DIR}")
