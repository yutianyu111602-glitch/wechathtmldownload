#!/usr/bin/env python3
"""OCR Benchmark: EasyOCR vs PaddleOCR on real poster images.

Tests accuracy, speed, VRAM, and Chinese text quality.
"""
import time, os, json, sys
import torch

print("=" * 60)
print("OCR ENGINE BENCHMARK")
print("=" * 60)

# Test images
test_images = [
    "/mnt/c/Users/pc/Pictures/微信图片_20260508224436_113_109.jpg",
]

# Add any found images
import glob
for p in glob.glob("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/tier_exp_*/flash_summary.json"):
    pass  # Not images

results = {}

# ── Engine 1: EasyOCR (GPU) ──
print("\n[1] EasyOCR (GPU)...")
try:
    import easyocr
    t0 = time.perf_counter()
    reader = easyocr.Reader(['ch_sim', 'en'], gpu=True)
    init_time = time.perf_counter() - t0
    print(f"    Init: {init_time:.1f}s  VRAM: {torch.cuda.memory_allocated()/1024**3:.1f}GB")
    
    easy_results = []
    for img_path in test_images:
        if not os.path.exists(img_path): continue
        t0 = time.perf_counter()
        result = reader.readtext(img_path, detail=0)
        elapsed = time.perf_counter() - t0
        text = "\n".join(result)
        easy_results.append({
            "image": os.path.basename(img_path),
            "time_s": round(elapsed, 2),
            "text_lines": len(result),
            "text": text[:500],
        })
        print(f"    {os.path.basename(img_path)}: {elapsed:.1f}s, {len(result)} lines")
        print(f"      sample: {text[:120]}")
    
    results["easyocr"] = {
        "init_s": round(init_time, 1),
        "vram_gb": round(torch.cuda.memory_allocated()/1024**3, 1),
        "images": easy_results,
    }
    # Free VRAM
    del reader
    torch.cuda.empty_cache()
except Exception as e:
    print(f"    ❌ EasyOCR failed: {e}")
    results["easyocr"] = {"error": str(e)}

# ── Engine 2: PaddleOCR (GPU) ──
print("\n[2] PaddleOCR (GPU)...")
try:
    t0 = time.perf_counter()
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(lang='ch', use_gpu=True)
    init_time = time.perf_counter() - t0
    vram = torch.cuda.memory_allocated()/1024**3 if torch.cuda.is_available() else 0
    print(f"    Init: {init_time:.1f}s  VRAM: {vram:.1f}GB")
    
    paddle_results = []
    for img_path in test_images:
        if not os.path.exists(img_path): continue
        t0 = time.perf_counter()
        result = ocr.ocr(img_path)
        elapsed = time.perf_counter() - t0
        
        # Extract text
        lines = []
        if result and result[0]:
            for line in result[0]:
                if line and len(line) > 1:
                    lines.append(line[1][0])
        text = "\n".join(lines)
        
        paddle_results.append({
            "image": os.path.basename(img_path),
            "time_s": round(elapsed, 2),
            "text_lines": len(lines),
            "text": text[:500],
        })
        print(f"    {os.path.basename(img_path)}: {elapsed:.1f}s, {len(lines)} lines")
        print(f"      sample: {text[:120]}")
    
    results["paddleocr"] = {
        "init_s": round(init_time, 1),
        "vram_gb": round(vram, 1),
        "images": paddle_results,
    }
except Exception as e:
    print(f"    ❌ PaddleOCR failed: {e}")
    results["paddleocr"] = {"error": str(e)}

# ── Summary ──
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

for engine in ["easyocr", "paddleocr"]:
    r = results.get(engine, {})
    if "error" in r:
        print(f"  {engine}: ❌ {r['error']}")
        continue
    
    imgs = r.get("images", [])
    if not imgs:
        print(f"  {engine}: no results")
        continue
    
    avg_time = sum(i["time_s"] for i in imgs) / len(imgs)
    avg_lines = sum(i["text_lines"] for i in imgs) / len(imgs)
    print(f"  {engine}: init={r['init_s']}s  vram={r['vram_gb']}GB  avg_time={avg_time:.1f}s  avg_lines={avg_lines:.0f}")

# Save report
report_path = "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/ocr_benchmark_20260512.json"
os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\nReport: {report_path}")
