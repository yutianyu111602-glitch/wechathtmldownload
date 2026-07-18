#!/usr/bin/env python3
"""Autonomous Pipeline Supervisor — no human intervention needed.

Monitors all pipeline stages, auto-triggers downstream steps, updates docs.
Runs continuously until all phases complete.
"""
import json, glob, os, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

STAGE7_ROOT = Path("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite")
SCRIPTS = STAGE7_ROOT / "scripts"
MEMORY = Path.home() / ".deepseek" / "pipeline_memory.jsonl"

# ── Config ──
V6_BASE = STAGE7_ROOT / "reports/overnight_v6_20260510_111419"
WTR_BASE = Path("/mnt/d/downstream_results/stage7_rewrite/longrun/WHERE_TO_RAVE_WECHAT_SYNC_20260508/FULL_MAP_SMART_BACKFILL_20260509")
ASSET_STATUS = WTR_BASE / "mptext_archive_FULL_MAP_SMART_BACKFILL_20260509/asset-retention-status.json"
PROCESS_STATUS = WTR_BASE / "processed_FULL_MAP_SMART_BACKFILL_20260509_status.json"
OCR_STATUS = WTR_BASE / "ocr_FULL_MAP_SMART_BACKFILL_20260509_status.json"
RUN_STATUS = WTR_BASE / "post_archive_run_status.json"

PWSH = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
AUTH_KEY = os.environ.get("MPTEXT_AUTH_KEY", "").strip()


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str, phase: str = "supervisor"):
    """Write to persistent memory."""
    entry = {"timestamp": datetime.now().isoformat(timespec="seconds"), "content": msg, "metadata": {"type": "stage7_pipeline", "phase": phase}}
    MEMORY.parent.mkdir(parents=True, exist_ok=True)
    with MEMORY.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[{now()}] {msg}")


def check_v6() -> dict:
    """Check V6 Flash extraction progress."""
    total_s = 0; total_c = 0; running = 0
    for i in range(8):
        f = glob.glob(str(V6_BASE / f"flash_manifest_shard_0{i}_*/flash_running_summary.json"))
        if f:
            d = json.load(open(f[0])); total_s += d.get("processed_samples", 0); total_c += d.get("estimated_cny", 0)
            if d.get("status") == "running": running += 1
    pct = total_s / 81425 * 100
    elapsed_h = (time.time() - 1746839682) / 3600  # ~May 10 11:14 UTC
    rate = total_s / max(elapsed_h * 60, 1)
    eta_h = (81425 - total_s) / max(rate, 0.01) / 60
    return {"samples": total_s, "pct": pct, "cost": total_c, "running": running, "rate": rate, "eta_h": eta_h}


def check_assets() -> dict:
    """Check asset download progress from Windows status file."""
    if not ASSET_STATUS.exists():
        return {"status": "not_started"}
    st = os.stat(str(ASSET_STATUS))
    with open(ASSET_STATUS, encoding="utf-8") as f:
        raw = f.read(500)
    done = re.search(r'"succeededCount":\s*(\d+)', raw)
    running = re.search(r'"runningCount":\s*(\d+)', raw)
    queued = re.search(r'"queuedCount":\s*(\d+)', raw)
    status = re.search(r'"status":\s*"([^"]+)"', raw)
    return {
        "done": int(done.group(1)) if done else 0,
        "running": int(running.group(1)) if running else 0,
        "queued": int(queued.group(1)) if queued else 0,
        "status": status.group(1) if status else "?",
        "age_s": time.time() - st.st_mtime,
        "total": (int(done.group(1)) if done else 0) + (int(queued.group(1)) if queued else 0),
    }


def run_ocr_step() -> bool:
    """Trigger OCR via PowerShell. Returns True if started."""
    cmd = f'''
Set-Location C:\\code\\githubstar\\wechathtmldownload
[Environment]::SetEnvironmentVariable('WECHAT_OCR_COMMAND', 'wsl python3 /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/ocr_gpu.py')
$BATCH = 'FULL_MAP_SMART_BACKFILL_20260509'
$ROOT = 'D:\\downstream_results\\stage7_rewrite\\longrun\\WHERE_TO_RAVE_WECHAT_SYNC_20260508\\' + $BATCH
$ARCHIVE = $ROOT + '\\mptext_archive_' + $BATCH
$PROCESS = $ROOT + '\\processed_' + $BATCH
$STATUS = $ROOT + '\\ocr_' + $BATCH + '_status.json'
$RESULTS = $ROOT + '\\ocr_' + $BATCH + '_results.jsonl'
npx tsx src/cli.ts ocr-poster-batch --artifactRoot $PROCESS --archiveRoot $ARCHIVE --statusPath $STATUS --resultLogPath $RESULTS --resume --concurrency 2
Write-Host ('OCR_EXIT:' + $LASTEXITCODE)
'''
    try:
        result = subprocess.run(
            [PWSH, "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "MPTEXT_AUTH_KEY": AUTH_KEY},
        )
        output = result.stdout + result.stderr
        if "OCR_EXIT:0" in output:
            log("OCR step started successfully", "ocr_trigger")
            return True
        else:
            log(f"OCR step result: {output[-300:]}", "ocr_trigger")
            return False
    except Exception as e:
        log(f"OCR trigger failed: {e}", "ocr_error")
        return False


def wait_and_retry_ocr(asset_status: dict) -> bool:
    """Wait for assets to complete, then trigger OCR."""
    if asset_status.get("status") == "completed" or (asset_status.get("done", 0) >= asset_status.get("total", 1)):
        log(f"Assets complete ({asset_status['done']}/{asset_status['total']}). Triggering OCR...", "asset_complete")
        return run_ocr_step()
    elif asset_status.get("running", 0) == 0 and asset_status.get("queued", 0) > 0:
        log(f"Assets stalled (0 running, {asset_status['queued']} queued). Restarting...", "asset_stalled")
        # Restart asset download
        cmd = f'''
Set-Location C:\\code\\githubstar\\wechathtmldownload
$ROOT = 'D:\\downstream_results\\stage7_rewrite\\longrun\\WHERE_TO_RAVE_WECHAT_SYNC_20260508\\FULL_MAP_SMART_BACKFILL_20260509'
$ARCHIVE = $ROOT + '\\mptext_archive_FULL_MAP_SMART_BACKFILL_20260509'
$QUEUE = $ROOT + '\\download_ready_queue_FULL_MAP_SMART_BACKFILL_20260509.jsonl'
npx tsx src/cli.ts download-archive-assets-batch --inputDir $ARCHIVE --manifestPath $QUEUE --resume
Write-Host ('RESTART_EXIT:' + $LASTEXITCODE)
'''
        subprocess.Popen(
            [PWSH, "-NoProfile", "-Command", cmd],
            env={**os.environ, "MPTEXT_AUTH_KEY": AUTH_KEY},
        )
        return False
    return False


def main():
    if not AUTH_KEY:
        raise SystemExit("MPTEXT_AUTH_KEY must come from the current exporter session")
    log("Autonomous supervisor started. Monitoring all pipelines.", "start")

    ocr_triggered = False
    v6_done_reported = False
    last_v6_pct = 0

    while True:
        # ── Check V6 ──
        v6 = check_v6()
        if v6["pct"] > last_v6_pct + 5 or v6["pct"] >= 99.9:
            log(f"V6: {v6['samples']:,} ({v6['pct']:.0f}%) ¥{v6['cost']:.0f} ETA {v6['eta_h']:.0f}h", "v6_progress")
            last_v6_pct = v6["pct"]

        if v6["pct"] >= 99.9 and not v6_done_reported:
            log("V6 COMPLETE! Preparing downstream...", "v6_complete")
            v6_done_reported = True

        # ── Check Assets ──
        assets = check_assets()
        if assets.get("status") == "not_started":
            pass  # Will be handled later
        elif not ocr_triggered:
            pct = assets["done"] / max(assets["total"], 1) * 100
            if assets["age_s"] < 300:  # Active in last 5 min
                if pct > last_v6_pct:  # Only log when meaningful
                    pass  # Too noisy to log every minute

            # Try OCR if assets look done
            if wait_and_retry_ocr(assets):
                ocr_triggered = True

        # ── Check OCR ──
        if OCR_STATUS.exists():
            st = os.stat(str(OCR_STATUS))
            with open(OCR_STATUS, encoding="utf-8") as f:
                raw = f.read(500)
            ocr_done = re.search(r'"succeededCount":\s*(\d+)', raw)
            ocr_total = re.search(r'"totalItems":\s*(\d+)', raw)
            if ocr_done and ocr_total:
                log(f"OCR: {ocr_done.group(1)}/{ocr_total.group(1)}", "ocr_progress")

        # ── Sleep ──
        time.sleep(300)  # Check every 5 minutes


if __name__ == "__main__":
    main()
