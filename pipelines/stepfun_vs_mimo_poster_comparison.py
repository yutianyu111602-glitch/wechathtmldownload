#!/usr/bin/env python3
"""
StepFun vs MiMo Poster Vision Comparison — P4
==============================================
Compares StepFun step-3.7-flash vs MiMo mimo-v2.5 on poster understanding.

Rules:
- API keys from environment only, NEVER hardcoded or written to reports.
- Model output must not override package truth without rule-based validation.
- All results written to reports/, no package/DB/CloudBase writes.

Comparison dimensions:
1. Main poster identification (vs QR/ticket/menu/logo/map/avatar/decorative)
2. Date/time extraction accuracy
3. Venue/address extraction
4. Lineup/DJ name extraction
5. Genre/music style detection
6. Information depth (total structured fields extracted)
7. Correctness (verified against known package truth)
8. Rejection: QR/ticket/menu/logo/map/avatar/decorative false positives
"""

import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request

# ── Config from environment (keys never printed) ──────────────────────
STEPFUN_KEY = os.environ.get("STEPFUN_VISION_API_KEY", "")
STEPFUN_BASE = os.environ.get("STEPFUN_VISION_BASE_URL", "https://api.stepfun.com/v1")
STEPFUN_MODEL = os.environ.get("STEPFUN_VISION_MODEL", "step-3.7-flash")

MIMO_KEY = os.environ.get("MIMO_VISION_API_KEY", "")
MIMO_BASE = os.environ.get("MIMO_VISION_BASE_URL", "https://api.xiaomimimo.com/v1")
MIMO_MODEL = os.environ.get("MIMO_VISION_MODEL", "mimo-v2.5")

REPO = Path(os.environ.get("HUAIDJ_REPO", r"C:\code\githubstar\wechathtmldownload").strip())
API_DIR = REPO / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
OUT_DIR = REPO / "tools" / "stage7_rewrite" / "reports" / "stepfun_mimo_poster_comparison_20260606"

PROMPT = """You are a poster analyst for a nightlife events mini-program.
Analyze this event poster image and return a JSON object with these fields.

Return ONLY valid JSON, no markdown, no explanation.

{
  "has_poster": true/false,
  "is_event_poster": true/false,
  "reject_reason": null or string explaining why this is NOT an event poster (QR code only, ticket, menu, logo, map, avatar, decorative image, etc.),
  "main_poster_confident": true/false,
  "event_title": "exact text from poster",
  "event_date": "YYYY-MM-DD format, or null if unclear",
  "event_date_raw": "date text as shown on poster",
  "event_time": "time text or null",
  "venue_name": "venue name from poster",
  "venue_address": "address from poster or null",
  "city": "city name or null",
  "lineup_djs": ["DJ Name 1", "DJ Name 2"],
  "genres": ["genre1", "genre2"],
  "ticket_price": "price text or null",
  "has_qr_code": true/false,
  "has_wechat_qr": true/false,
  "extra_images_detected": ["logo", "sponsor", "map", "decorative"],
  "info_density": "low/medium/high",
  "confidence_score": 0.0-1.0
}"""


def load_current_items():
    """Load items from current.json"""
    with open(API_DIR / "current.json", encoding="utf-8") as f:
        return json.load(f)["items"]


def download_poster_as_base64(cloud_file_id, timeout=30):
    """
    Download a poster from CloudBase via temp URL and return as base64 data URL.
    Uses wx.cloud.getTempFileURL equivalent logic via CloudBase HTTP API.
    """
    if not cloud_file_id or not cloud_file_id.startswith("cloud://"):
        return None

    # Parse cloud:// path
    # Format: cloud://env-id.region-bucket/path/to/file.png
    try:
        cloud_part = cloud_file_id.replace("cloud://", "")
        env_id, remaining = cloud_part.split("/", 1)
        env_id = env_id.split(".")[0]  # Remove .region-bucket suffix

        # Use CloudBase HTTP storage API
        # First get temp URL via CloudBase storage getTempFileURL
        # Simplified: try direct HTTP download
        # The actual temp URL resolution requires CloudBase SDK
        # For now, use the CloudBase CDN pattern
        temp_url = (
            f"https://{env_id}.tcb.qcloud.la/{remaining}"
        )
        req = Request(temp_url, headers={"User-Agent": "HUAIDJ-Weekly/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        print(f"  [WARN] Failed to download poster: {e}", file=sys.stderr)
        return None


def call_vision_api(provider, base_url, api_key, model, image_data_url):
    """Call vision API with base64 image. Returns parsed JSON or error dict."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url, "detail": "high"},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": 2000,
    }

    t0 = time.time()
    try:
        req = Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        with urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - t0

        content = raw["choices"][0]["message"]["content"]
        # Try to parse JSON from response
        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
        result = json.loads(content)
        result["_provider"] = provider
        result["_model"] = model
        result["_latency_s"] = round(elapsed, 2)
        result["_raw_tokens"] = raw.get("usage", {}).get("total_tokens", 0)
        return result
    except json.JSONDecodeError:
        return {
            "_provider": provider,
            "_model": model,
            "_error": "json_parse_failed",
            "_raw_content": content[:500] if 'content' in dir() else "N/A",
            "_latency_s": round(time.time() - t0, 2),
        }
    except Exception as e:
        return {
            "_provider": provider,
            "_model": model,
            "_error": str(e)[:200],
            "_latency_s": round(time.time() - t0, 2),
        }


def score_result(result, ground_truth):
    """
    Score a vision result against known package truth.
    Returns dict with per-dimension scores and total.
    """
    scores = {}
    details = {}

    # 1. Poster identification
    if result.get("_error"):
        scores["poster_id"] = 0
        details["poster_id"] = f"API error: {result['_error']}"
    elif result.get("is_event_poster") and result.get("main_poster_confident"):
        scores["poster_id"] = 10
        details["poster_id"] = "correctly identified as event poster"
    elif result.get("is_event_poster"):
        scores["poster_id"] = 5
        details["poster_id"] = "identified as poster but low confidence"
    else:
        scores["poster_id"] = 0
        details["poster_id"] = f"rejected: {result.get('reject_reason', 'unknown')}"

    # 2. Date extraction
    gt_date = ground_truth.get("event_date_start", "")
    pred_date = result.get("event_date", "")
    if gt_date and pred_date == gt_date:
        scores["date"] = 15
        details["date"] = f"exact match: {gt_date}"
    elif gt_date and pred_date:
        scores["date"] = 5
        details["date"] = f"partial: pred={pred_date} vs gt={gt_date}"
    elif not gt_date:
        scores["date"] = None  # skip
        details["date"] = "no ground truth"
    else:
        scores["date"] = 0
        details["date"] = f"missed: gt={gt_date}"

    # 3. Venue extraction
    gt_venue = str(ground_truth.get("venue_name", "")).lower()
    pred_venue = str(result.get("venue_name", "")).lower()
    if gt_venue and pred_venue and (gt_venue in pred_venue or pred_venue in gt_venue):
        scores["venue"] = 15
        details["venue"] = f"matched: '{ground_truth.get('venue_name','')}'"
    elif gt_venue and pred_venue:
        scores["venue"] = 7
        details["venue"] = f"partial: pred='{result.get('venue_name','')}' vs gt='{ground_truth.get('venue_name','')}'"
    elif not gt_venue:
        scores["venue"] = None
        details["venue"] = "no ground truth"
    else:
        scores["venue"] = 0
        details["venue"] = "venue not extracted"

    # 4. City extraction
    gt_city = ground_truth.get("city_name", "")
    pred_city = result.get("city", "")
    if gt_city and pred_city and gt_city in pred_city:
        scores["city"] = 10
        details["city"] = f"matched: {gt_city}"
    elif gt_city and pred_city:
        scores["city"] = 3
        details["city"] = f"partial: pred='{pred_city}' vs gt='{gt_city}'"
    elif not gt_city:
        scores["city"] = None
        details["city"] = "no ground truth"
    else:
        scores["city"] = 0
        details["city"] = "city not extracted"

    # 5. Lineup extraction
    gt_lineup = [x.lower() for x in ground_truth.get("lineup_artists", [])]
    pred_lineup = [x.lower() for x in result.get("lineup_djs", [])]
    if not gt_lineup:
        scores["lineup"] = None
        details["lineup"] = "no ground truth lineup"
    elif pred_lineup:
        matches = sum(1 for g in gt_lineup if any(g in p or p in g for p in pred_lineup))
        if matches == len(gt_lineup):
            scores["lineup"] = 15
            details["lineup"] = f"full match: {matches}/{len(gt_lineup)}"
        else:
            scores["lineup"] = max(3, matches * 5)
            details["lineup"] = f"partial: {matches}/{len(gt_lineup)}"
    else:
        scores["lineup"] = 0
        details["lineup"] = "no lineup extracted"

    # 6. Genre detection
    gt_genres = [g.lower() for g in ground_truth.get("genres", [])]
    pred_genres = [g.lower() for g in result.get("genres", [])]
    if not gt_genres:
        scores["genres"] = None
        details["genres"] = "no ground truth genres"
    elif pred_genres:
        matches = sum(1 for g in gt_genres if any(g in p or p in g for p in pred_genres))
        scores["genres"] = min(15, matches * 5)
        details["genres"] = f"{matches}/{len(gt_genres)} matched"
    else:
        scores["genres"] = 0
        details["genres"] = "no genres extracted"

    # 7. QR rejection (fewer false positives = better)
    qr_detected = result.get("has_qr_code", False)
    scores["qr_rejection"] = 5 if not qr_detected else 0  # We assume posters don't have QR codes
    details["qr_rejection"] = "no QR false positive" if not qr_detected else "QR detected (possible false positive)"

    # 8. Information density
    density = result.get("info_density", "low")
    density_scores = {"high": 10, "medium": 7, "low": 3}
    scores["info_density"] = density_scores.get(density, 3)
    details["info_density"] = f"model rated: {density}"

    # 9. Confidence
    conf = result.get("confidence_score", 0)
    scores["confidence"] = min(5, int(conf * 5))
    details["confidence"] = f"self-rated: {conf}"

    # Compute total
    valid_scores = [v for v in scores.values() if v is not None]
    max_possible = sum(1 for v in scores.values() if v is not None)  # count dimensions with ground truth
    actual_max = 100  # theoretical max if all dims present
    total = sum(valid_scores)
    pct = round(total / actual_max * 100, 1) if actual_max else 0

    return {
        "scores": scores,
        "details": details,
        "total": total,
        "max_possible": actual_max,
        "pct": pct,
    }


def select_test_posters(items, count=3):
    """Select diverse posters for testing."""
    selected = []
    for item in items:
        pid = item.get("poster_file_id", "")
        if not pid or not pid.startswith("cloud://"):
            continue
        has_lineup = len(item.get("lineup", [])) > 0 or len(item.get("lineup_artists", [])) > 0
        genres = item.get("genres", [])
        
        if len(selected) == 0:
            selected.append(item)
        elif len(selected) == 1 and has_lineup:
            selected.append(item)
        elif len(selected) == 2 and len(genres) >= 3:
            selected.append(item)
        if len(selected) >= count:
            break
    return selected


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Validate keys
    if not STEPFUN_KEY:
        print("ERROR: STEPFUN_VISION_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    if not MIMO_KEY:
        print("ERROR: MIMO_VISION_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print(f"StepFun: model={STEPFUN_MODEL}, base={STEPFUN_BASE}")
    print(f"MiMo:    model={MIMO_MODEL}, base={MIMO_BASE}")
    print(f"Output:  {OUT_DIR}")
    print()

    # Load items
    items = load_current_items()
    print(f"Loaded {len(items)} items from current.json")

    # Select test posters
    test_items = select_test_posters(items, count=3)
    print(f"Selected {len(test_items)} posters for comparison:\n")

    all_results = []
    
    for idx, item in enumerate(test_items):
        item_id = item["id"]
        title = item.get("title_display", item.get("title", ""))
        venue = item.get("venue_name", "")
        city = item.get("city_name", "")
        cloud_id = item.get("poster_file_id", "")
        
        print(f"--- Poster {idx+1}: {item_id} ---")
        print(f"  Title: {title[:80]}")
        print(f"  Venue: {venue}, City: {city}")
        print(f"  Ground truth: date={item.get('event_date_start')}, "
              f"lineup={item.get('lineup_artists', [])}, "
              f"genres={item.get('genres', [])}")

        # Download poster as base64
        print(f"  Downloading poster...")
        image_b64 = download_poster_as_base64(cloud_id)
        if not image_b64:
            print(f"  [SKIP] Could not download poster for {item_id}")
            continue
        
        print(f"  Image size: {len(image_b64)} bytes (base64)")

        # Call StepFun
        print(f"  Calling StepFun ({STEPFUN_MODEL})...")
        sf_result = call_vision_api("stepfun", STEPFUN_BASE, STEPFUN_KEY, STEPFUN_MODEL, image_b64)
        sf_score = score_result(sf_result, item)
        print(f"    → Score: {sf_score['total']}/{sf_score['max_possible']} ({sf_score['pct']}%) "
              f"latency: {sf_result.get('_latency_s', '?')}s")

        # Call MiMo
        print(f"  Calling MiMo ({MIMO_MODEL})...")
        mimo_result = call_vision_api("mimo", MIMO_BASE, MIMO_KEY, MIMO_MODEL, image_b64)
        mimo_score = score_result(mimo_result, item)
        print(f"    → Score: {mimo_score['total']}/{mimo_score['max_possible']} ({mimo_score['pct']}%) "
              f"latency: {mimo_result.get('_latency_s', '?')}s")

        all_results.append({
            "item_id": item_id,
            "title": title,
            "venue": venue,
            "city": city,
            "ground_truth": {
                "date": item.get("event_date_start"),
                "venue": venue,
                "city": city,
                "lineup": item.get("lineup_artists", []),
                "genres": item.get("genres", []),
            },
            "stepfun": {
                "result": sf_result,
                "score": sf_score,
            },
            "mimo": {
                "result": mimo_result,
                "score": mimo_score,
            },
        })
        print()

    # ── Summary ──
    print("=" * 60)
    print("SUMMARY: StepFun vs MiMo Poster Vision Comparison")
    print("=" * 60)
    
    total_sf = sum(r["stepfun"]["score"]["total"] for r in all_results)
    total_mimo = sum(r["mimo"]["score"]["total"] for r in all_results)
    max_possible = sum(r["stepfun"]["score"]["max_possible"] for r in all_results)
    
    print(f"\nOverall:")
    print(f"  StepFun total: {total_sf}/{max_possible} ({round(total_sf/max_possible*100,1)}%)")
    print(f"  MiMo total:    {total_mimo}/{max_possible} ({round(total_mimo/max_possible*100,1)}%)")
    
    # Per dimension comparison
    dims = ["poster_id", "date", "venue", "city", "lineup", "genres", "qr_rejection", "info_density", "confidence"]
    print(f"\nPer-dimension averages:")
    for dim in dims:
        sf_vals = [r["stepfun"]["score"]["scores"].get(dim) for r in all_results if r["stepfun"]["score"]["scores"].get(dim) is not None]
        mimo_vals = [r["mimo"]["score"]["scores"].get(dim) for r in all_results if r["mimo"]["score"]["scores"].get(dim) is not None]
        sf_avg = round(sum(sf_vals)/len(sf_vals), 1) if sf_vals else "N/A"
        mimo_avg = round(sum(mimo_vals)/len(mimo_vals), 1) if mimo_vals else "N/A"
        winner = "StepFun" if (isinstance(sf_avg, float) and isinstance(mimo_avg, float) and sf_avg > mimo_avg) else \
                 "MiMo" if (isinstance(sf_avg, float) and isinstance(mimo_avg, float) and mimo_avg > sf_avg) else \
                 "tie"
        print(f"  {dim:20s}  StepFun={sf_avg:<6}  MiMo={mimo_avg:<6}  → {winner}")

    # Latency comparison
    sf_lat = [r["stepfun"]["result"].get("_latency_s", 0) for r in all_results]
    mimo_lat = [r["mimo"]["result"].get("_latency_s", 0) for r in all_results]
    print(f"\nLatency:")
    print(f"  StepFun avg: {round(sum(sf_lat)/len(sf_lat),2)}s")
    print(f"  MiMo avg:    {round(sum(mimo_lat)/len(mimo_lat),2)}s")

    # Write report
    report = {
        "schema_version": "stepfun_mimo_poster_comparison.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "providers": {
            "stepfun": {"model": STEPFUN_MODEL, "base_url": STEPFUN_BASE},
            "mimo": {"model": MIMO_MODEL, "base_url": MIMO_BASE},
        },
        "results": all_results,
        "summary": {
            "stepfun_total": total_sf,
            "mimo_total": total_mimo,
            "max_possible": max_possible,
            "stepfun_pct": round(total_sf / max_possible * 100, 1),
            "mimo_pct": round(total_mimo / max_possible * 100, 1),
        },
    }
    
    report_path = OUT_DIR / "stepfun_mimo_poster_comparison.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport written to: {report_path}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
