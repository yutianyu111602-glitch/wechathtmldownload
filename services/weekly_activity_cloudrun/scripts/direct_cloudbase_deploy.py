#!/usr/bin/env python3
"""Deploy the staged CloudBase Run context through signed direct API calls.

This bypasses a @cloudbase/cli@3.3.1 deprecated CloudRun compatibility bug:
DescribeCloudBaseBuildService returns package fields under `data`, while the
deprecated version create/update command reads them as top-level fields.

The script never prints or writes UploadUrl, UploadHeaders, tokens, or secrets.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
SERVICE_NAME = "weekly-api"
PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_DIR = PROJECT_DIR / "tmp" / "cloudrun_deploy_context"
DEFAULT_OUT_DIR = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\full_pipeline_production_deploy_20260518"
)
TCB_CMD = [shutil.which("npm") or "npm", "exec", "--yes", "--package", "@cloudbase/cli@3.3.1", "--", "tcb"]
SECRETISH_KEYS = ("url", "header", "token", "secret", "authorization", "credential", "key")
TCB_API_TIMEOUT_SECONDS: int | None = 240
UPLOAD_TIMEOUT_SECONDS: int | None = 600
UPLOAD_MAX_ATTEMPTS = 3


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_first_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    value = json.loads(text[start : end + 1])
    return value if isinstance(value, dict) else {}


def scrub(value: Any, key: str = "") -> Any:
    if any(item in key.lower() for item in SECRETISH_KEYS):
        if isinstance(value, dict):
            return {name: "<redacted>" for name in value}
        if isinstance(value, list):
            return ["<redacted>" for _ in value]
        return "<redacted>"
    if isinstance(value, dict):
        return {name: scrub(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, key) for item in value]
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def tcb_api(action: str, body: dict[str, Any], *, service: str = "tcb", api_version: str | None = None) -> dict[str, Any]:
    cmd = [*TCB_CMD, "api", service, action]
    if api_version:
        cmd.extend(["--api-version", api_version])
    cmd.extend(["--body", json.dumps(body, ensure_ascii=False, separators=(",", ":")), "--json"])
    run_kwargs: dict[str, Any] = {"cwd": PROJECT_DIR, "capture_output": True, "text": True}
    if TCB_API_TIMEOUT_SECONDS is not None:
        run_kwargs["timeout"] = TCB_API_TIMEOUT_SECONDS
    result = subprocess.run(cmd, **run_kwargs)
    payload = parse_first_json_object((result.stdout or "") + "\n" + (result.stderr or ""))
    if result.returncode != 0:
        raise RuntimeError(
            json.dumps(
                {
                    "action": action,
                    "returncode": result.returncode,
                    "payload_redacted": scrub(payload),
                },
                ensure_ascii=False,
            )
        )
    return payload.get("data") if isinstance(payload.get("data"), dict) else payload


def zip_context(context_dir: Path, zip_path: Path) -> dict[str, Any]:
    if not context_dir.exists():
        raise FileNotFoundError(f"context dir not found: {context_dir}")
    blocked_names = {".env", ".env.local"}
    blocked_suffixes = (".pid", ".log", ".zip")
    files: list[Path] = []
    for path in sorted(context_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(context_dir)
        parts = set(rel.parts)
        if "node_modules" in parts or "__pycache__" in parts:
            continue
        if path.name in blocked_names or path.name.startswith("code") and path.suffix == ".zip":
            continue
        if path.suffix in blocked_suffixes:
            continue
        files.append(path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            zf.write(path, path.relative_to(context_dir).as_posix())
    return {
        "context_dir": str(context_dir),
        "zip_path": str(zip_path),
        "file_count": len(files),
        "zip_bytes": zip_path.stat().st_size,
        "context_bytes": sum(path.stat().st_size for path in files),
    }


def upload_package(upload_url: str, zip_path: Path) -> None:
    data = zip_path.read_bytes()
    # Signed COS uploads are large, idempotent PUTs.  Bypass workstation proxy
    # settings here because local HTTP proxies can reset long uploads while the
    # Tencent endpoint itself is directly reachable.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
        req = urllib.request.Request(
            upload_url,
            data=data,
            method="PUT",
            headers={
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,zh-TW;q=0.7,en-US;q=0.6",
                "Content-Type": "application/x-zip-compressed",
            },
        )
        try:
            with opener.open(req, timeout=UPLOAD_TIMEOUT_SECONDS) as response:
                if response.status >= 400:
                    raise RuntimeError(f"upload failed with HTTP {response.status}")
            return
        except (OSError, RuntimeError):
            if attempt >= UPLOAD_MAX_ATTEMPTS:
                raise
            time.sleep(2 * attempt)


def update_cloudrun_server(env_id: str, service_name: str, package_name: str, package_version: str, remark: str) -> dict[str, Any]:
    body = {
        "EnvId": env_id,
        "ServerName": service_name,
        "DeployInfo": {
            "DeployType": "package",
            "PackageName": package_name,
            "PackageVersion": package_version,
            "DeployRemark": remark,
            "ReleaseType": "FULL",
        },
        "Items": [
            {"Key": "HasDockerfile", "BoolValue": True},
            {"Key": "Dockerfile", "Value": "Dockerfile"},
            {"Key": "Port", "IntValue": 8787},
            {"Key": "CpuSpecs", "FloatValue": 1},
            {"Key": "MemSpecs", "FloatValue": 2},
            {"Key": "MinNum", "IntValue": 1},
            {"Key": "MaxNum", "IntValue": 2},
            {"Key": "PolicyDetails", "PolicyDetails": [{"PolicyType": "cpu", "PolicyThreshold": 60}]},
            {"Key": "LogPath", "Value": "stdout"},
        ],
    }
    return tcb_api("UpdateCloudRunServer", body, service="tcbr", api_version="2022-02-17")


def describe_cloudrun_server_identity(env_id: str, service_name: str) -> dict[str, Any]:
    data = tcb_api(
        "DescribeCloudRunServerDetail",
        {"EnvId": env_id, "ServerName": service_name},
        service="tcbr",
        api_version="2022-02-17",
    )
    base = data.get("BaseInfo") if isinstance(data.get("BaseInfo"), dict) else {}
    versions = data.get("OnlineVersionInfos") if isinstance(data.get("OnlineVersionInfos"), list) else []
    summarized_versions = []
    for item in versions:
        if not isinstance(item, dict):
            continue
        summarized_versions.append(
            {
                "version_name": str(item.get("VersionName") or item.get("versionName") or ""),
                "flow_ratio": item.get("FlowRatio", item.get("flowRatio", "")),
                "status": str(item.get("Status") or item.get("status") or ""),
                "update_time": str(item.get("UpdateTime") or item.get("updateTime") or ""),
            }
        )
    active = next((item for item in summarized_versions if str(item.get("flow_ratio")) == "100"), summarized_versions[0] if summarized_versions else {})
    return {
        "captured_at": now_iso(),
        "base_url": str(base.get("DefaultDomainName") or "").rstrip("/"),
        "status": str(base.get("Status") or ""),
        "update_time": str(base.get("UpdateTime") or ""),
        "access_types": base.get("AccessTypes") or [],
        "active_version": active.get("version_name", ""),
        "active_flow_ratio": active.get("flow_ratio", ""),
        "versions": summarized_versions,
        "request_id": data.get("RequestId", ""),
    }


def poll_task(env_id: str, service_name: str, task_id: int, max_wait_seconds: int) -> dict[str, Any]:
    if not task_id:
        return {"ok": False, "status": "missing_task_id", "polls": []}
    deadline = None if max_wait_seconds <= 0 else time.time() + max_wait_seconds
    polls: list[dict[str, Any]] = []
    while deadline is None or time.time() < deadline:
        data = tcb_api(
            "DescribeServerManageTask",
            {"EnvId": env_id, "ServerName": service_name, "TaskId": int(task_id)},
            service="tcbr",
            api_version="2022-02-17",
        )
        task = data.get("Task") if isinstance(data.get("Task"), dict) else {}
        status = str(task.get("Status") or data.get("Status") or "")
        version_name = str(task.get("VersionName") or "")
        fail_reason = str(task.get("FailReason") or "")
        polls.append({"at": now_iso(), "status": status, "version_name": version_name, "fail_reason": fail_reason})
        if status.lower() in {"finished", "success", "succeed", "normal"}:
            return {"ok": True, "status": status, "version_name": version_name, "polls": polls}
        if status.lower() in {"failed", "fail", "error", "deploy_failed"} or fail_reason:
            return {"ok": False, "status": status, "polls": polls}
        time.sleep(10)
    return {"ok": False, "status": "poll_timeout", "polls": polls}


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out_dir
    zip_path = out_dir / "cloudrun_direct_api_context.zip"
    report: dict[str, Any] = {
        "schema_version": "cloudrun_direct_api_deploy.v1",
        "generated_at": now_iso(),
        "ok": False,
        "decision": "cloudrun_direct_api_not_started",
        "env_id": args.env_id,
        "service_name": args.service_name,
        "safety": {
            "secret_value_read_or_printed": False,
            "upload_url_written": False,
            "cloud_deploy_executed": False,
            "production_publish_verified": False,
        },
    }
    zip_info = zip_context(args.context_dir, zip_path)
    report["zip"] = zip_info
    if args.dry_run:
        report["ok"] = True
        report["decision"] = "cloudrun_direct_api_dry_run_ready"
        write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
        return report

    try:
        report["previous_server_identity"] = describe_cloudrun_server_identity(args.env_id, args.service_name)
    except Exception as exc:  # noqa: BLE001
        report["previous_server_identity"] = {"capture_error": str(exc), "captured_at": now_iso()}

    build = tcb_api("DescribeCloudBaseBuildService", {"EnvId": args.env_id, "ServiceName": args.service_name})
    package_name = str(build.get("PackageName") or "")
    package_version = str(build.get("PackageVersion") or "")
    upload_url = str(build.get("UploadUrl") or "")
    report["build_service"] = {
        "package_name": package_name,
        "package_version": package_version,
        "has_upload_url": bool(upload_url),
        "has_upload_headers": bool(build.get("UploadHeaders")),
        "request_id": build.get("RequestId", ""),
    }
    if not package_name or not package_version or not upload_url:
        report["decision"] = "cloudrun_direct_api_blocked_missing_package_fields"
        write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
        return report

    upload_package(upload_url, zip_path)
    report["upload"] = {"ok": True, "zip_bytes": zip_info["zip_bytes"]}
    updated = update_cloudrun_server(
        args.env_id,
        args.service_name,
        package_name,
        package_version,
        f"stage7-full-pipeline direct-api {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )
    report["update_cloudrun_server"] = scrub(updated)
    task_id = int(updated.get("TaskId") or 0)
    request_id = str(updated.get("RequestId") or "")
    try:
        poll = poll_task(args.env_id, args.service_name, task_id, args.max_wait_seconds)
    except Exception as exc:  # noqa: BLE001
        poll = {
            "ok": False,
            "status": "poll_exception",
            "error": str(exc),
            "allowed_unverified": bool(args.allow_unverified_task_poll),
        }
    report["operation"] = poll
    report["safety"]["cloud_deploy_executed"] = bool(task_id or request_id)
    try:
        report["post_update_server_identity"] = describe_cloudrun_server_identity(args.env_id, args.service_name)
    except Exception as exc:  # noqa: BLE001
        report["post_update_server_identity"] = {"capture_error": str(exc), "captured_at": now_iso()}
    report["ok"] = bool(poll.get("ok")) or (bool(args.allow_unverified_task_poll) and bool(task_id or request_id))
    if poll.get("ok"):
        report["decision"] = "cloudrun_direct_api_deploy_verified"
    elif report["ok"]:
        report["decision"] = "cloudrun_direct_api_deploy_poll_unverified"
    else:
        report["decision"] = "cloudrun_direct_api_deploy_unverified"
    report["safety"]["production_publish_verified"] = bool(poll.get("ok"))
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-id", default=ENV_ID)
    parser.add_argument("--service-name", default=SERVICE_NAME)
    parser.add_argument("--context-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-wait-seconds", type=int, default=900)
    parser.add_argument(
        "--no-timeout",
        action="store_true",
        help="Disable per-request upload/API timeout and poll without a fixed deadline.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-unverified-task-poll",
        action="store_true",
        help="Exit 0 after UpdateCloudRunServer succeeds even if DescribeServerManageTask polling fails; caller must run remote smoke/reconcile next.",
    )
    return parser.parse_args(argv)


def main() -> int:
    global TCB_API_TIMEOUT_SECONDS, UPLOAD_TIMEOUT_SECONDS
    args = parse_args()
    if args.no_timeout:
        TCB_API_TIMEOUT_SECONDS = None
        UPLOAD_TIMEOUT_SECONDS = None
        args.max_wait_seconds = 0
    try:
        report = run(args)
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": "cloudrun_direct_api_deploy.v1",
            "generated_at": now_iso(),
            "ok": False,
            "decision": "cloudrun_direct_api_exception",
            "error": str(exc),
            "safety": {
                "secret_value_read_or_printed": False,
                "upload_url_written": False,
                "production_publish_verified": False,
            },
        }
        args.out_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.out_dir / "cloudrun_direct_api_deploy_report.json", report)
    print(json.dumps({k: report.get(k) for k in ["ok", "decision"]}, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
