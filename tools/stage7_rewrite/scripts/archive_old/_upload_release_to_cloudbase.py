#!/usr/bin/env python3
"""[LEGACY — static hosting upload, NOT used by current CloudRun architecture]

The current architecture bakes data into the Docker image and deploys via
  services/weekly_activity_cloudrun/scripts/bake_and_deploy.py
This static-hosting upload path is kept for reference only.

Original purpose: Upload weekly release files to CloudBase static hosting via tcb CLI.
WARNING: ENV_ID below was the old 体验版 env that is no longer bound to the AppID.
         DO NOT run this script without first updating ENV_ID to the live env.
"""
import json
import subprocess
import sys
from pathlib import Path


RELEASE_MANIFEST = Path(
    r"D:\downstream_results\stage7_rewrite\longrun"
    r"\WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE_ENTITY_POSTEROCR6_20260509\release_manifest.json"
)
# WARNING: this was the old 体验版 env — AppID is NOT bound here.
# Current live env: huaidjweekly-d8g1go7-d0a07863e3e (个人版)
ENV_ID = "huaidjweekly-d8g1go7kj48ec76c9"  # LEGACY — DO NOT USE WITHOUT UPDATING
TCB_CMD = "npm exec --yes --package @cloudbase/cli@3.3.1 -- tcb hosting deploy"


def main():
    plan = json.loads(RELEASE_MANIFEST.read_text(encoding="utf-8"))
    files = plan["files"]
    total = len(files)
    print(f"Uploading {total} files to CloudBase env {ENV_ID}...")
    failed = []
    for i, f in enumerate(files, 1):
        local = f["local_path"]
        remote = f["remote_path"]
        print(f"[{i}/{total}] {remote}", end=" ", flush=True)
        cmd = f'{TCB_CMD} "{local}" {remote} -e {ENV_ID}'
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, shell=True)
        if result.returncode != 0:
            print("FAIL")
            failed.append((remote, result.stderr[-200:]))
        else:
            print("ok")
    print()
    print(f"Done: {total - len(failed)}/{total} ok, {len(failed)} failed")
    for r, err in failed:
        print(f"  FAIL: {r}")
        print(f"    {err[:150]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
