import json, pathlib, os, time, re
from urllib.request import Request, urlopen
from urllib.error import HTTPError

MIMO_KEY = os.environ.get("MIMO_VISION_API_KEY") or os.environ.get("MIMO_API_KEY") or ""
ENDPOINT = "http://127.0.0.1:17300"
API_KEY = "ec9dd7f24326400eb8878fcb3d9d3640"
OUT_DIR = pathlib.Path(r"D:\downstream_results\stage7_rewrite\longrun\agg_child_recovery_20260607")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 8 unique parent articles from 4 accounts
ARTICLES = {
    "loopy_1": "https://mp.weixin.qq.com/s/sCkHCA_OK7mhmdQPHZ-_9g",
    "loopy_2": "https://mp.weixin.qq.com/s/g-fwMRFkA7vtCKN8L_bl3A",
    "loopy_3": "https://mp.weixin.qq.com/s/l-oBCcueMF1aUrRw4W57Wg",
    "loopy_4": "https://mp.weixin.qq.com/s/faa2LIs8W8XBkOscnYWaXw",
    "oil_1": "https://mp.weixin.qq.com/s/Y4MYmn5aB-yqzfN8ut3CXQ",
    "oil_2": "https://mp.weixin.qq.com/s/0B1BH3p8MwCdYb1T1ZPxJg",
    "dada_1": "https://mp.weixin.qq.com/s/xf1epKmpnP9YwYetwFTaXw",
    "wigwam_1": "https://mp.weixin.qq.com/s/GYFC3Ie5h3fIRPP92_yNeg",
}

results = {}
for name, url in ARTICLES.items():
    api_url = f"{ENDPOINT}/api/public/v1/download?url={url}&format=html"
    try:
        req = Request(api_url, headers={"X-Auth-Key": API_KEY})
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        
        out_path = OUT_DIR / f"{name}.html"
        out_path.write_text(html, encoding="utf-8")
        
        # Extract image URLs
        img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html)
        img_urls = [u for u in img_urls if not u.startswith('data:')]
        results[name] = {"ok": True, "size": len(html), "images": len(img_urls), "img_urls": img_urls}
        print(f"{name}: ok html={len(html)}b images={len(img_urls)}")
    except Exception as e:
        results[name] = {"ok": False, "error": str(e)[:200]}
        print(f"{name}: FAILED {e}")

# Save manifest
(out_dir / "download_manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
total_imgs = sum(r.get("images", 0) for r in results.values())
print(f"\nTotal: {sum(1 for r in results.values() if r['ok'])}/{len(ARTICLES)} downloaded, {total_imgs} images found")
