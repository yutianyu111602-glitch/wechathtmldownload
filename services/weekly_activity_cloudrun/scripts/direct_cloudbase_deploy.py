#!/usr/bin/env python3
"""Deploy the staged CloudBase Run context through signed direct API calls.

This bypasses a @cloudbase/cli@3.3.1 deprecated CloudRun compatibility bug:
DescribeCloudBaseBuildService returns package fields under `data`, while the
deprecated version create/update command reads them as top-level fields.

The script never prints or writes UploadUrl, UploadHeaders, tokens, or secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bake_and_deploy import validate_held_service_publish_lease  # noqa: E402


ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
SERVICE_NAME = "weekly-api"
PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = Path(
    os.environ.get(
        "HUAIDJ_CLOUDRUN_DATA_ROOT",
        r"F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data",
    )
)
DEFAULT_CONTEXT_DIR = PROJECT_DIR / "tmp" / "cloudrun_deploy_context"
DEFAULT_OUT_DIR = Path(
    os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports")
) / "cloudrun_direct_deploy"
TCB_CMD = [shutil.which("npm") or "npm", "exec", "--yes", "--package", "@cloudbase/cli@3.3.1", "--", "tcb"]
SECRETISH_KEYS = ("url", "header", "token", "secret", "authorization", "credential", "key")
TCB_API_TIMEOUT_SECONDS: int | None = 240
UPLOAD_TIMEOUT_SECONDS: int | None = 600
UPLOAD_MAX_ATTEMPTS = 3
DEPLOY_CONTEXT_MANIFEST = "deploy_context_manifest.json"


class SafeDeployError(RuntimeError):
    """An operator-actionable failure whose text is safe to persist."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def safe_failure(exc: Exception) -> dict[str, str]:
    if isinstance(exc, SafeDeployError):
        return {"code": exc.code}
    return {"code": "cloudrun_direct_api_unexpected_exception"}


def safe_remote_identifier(value: Any) -> str:
    text = str(value or "")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", text):
        return text
    return ""


def read_existing_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != "cloudrun_direct_api_deploy.v2":
        return {}
    return payload


def validate_previous_server_identity(identity: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not re.fullmatch(
        r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?",
        str(identity.get("base_url") or ""),
    ):
        failures.append("base_url_missing")
    if not safe_remote_identifier(identity.get("active_version")):
        failures.append("active_version_missing")
    try:
        active_flow_ratio = int(identity.get("active_flow_ratio"))
    except (TypeError, ValueError):
        active_flow_ratio = -1
    if active_flow_ratio != 100:
        failures.append("active_flow_ratio_not_100")
    return failures


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def packaged_context_files(context_dir: Path) -> list[Path]:
    blocked_names = {".env", ".env.local"}
    blocked_suffixes = (".pid", ".log", ".zip")
    files: list[Path] = []
    for path in sorted(Path(context_dir).rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(context_dir)
        parts = set(relative.parts)
        if "node_modules" in parts or "__pycache__" in parts:
            continue
        if path.name in blocked_names or (path.name.startswith("code") and path.suffix == ".zip"):
            continue
        if path.suffix in blocked_suffixes:
            continue
        files.append(path)
    return files


def validate_deploy_context(context_dir: Path) -> dict[str, Any]:
    """Verify the immutable bake manifest before uploading any bytes."""
    context_dir = context_dir.resolve()
    manifest_path = context_dir / DEPLOY_CONTEXT_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"deploy context manifest missing or invalid: {manifest_path}") from exc
    if manifest.get("schema_version") != "weekly_cloudrun_deploy_context_manifest.v1":
        raise ValueError("deploy context manifest schema mismatch")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("deploy context manifest has no files")
    canonical_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("deploy context manifest contains a non-object file row")
        relative = Path(str(row.get("dst") or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe deploy context path: {relative}")
        path = (context_dir / relative).resolve()
        if context_dir != path and context_dir not in path.parents:
            raise ValueError(f"deploy context path escapes root: {relative}")
        if not path.is_file():
            raise ValueError(f"deploy context file missing: {relative.as_posix()}")
        expected_size = int(row.get("size") or -1)
        if path.stat().st_size != expected_size:
            raise ValueError(f"deploy context size mismatch: {relative.as_posix()}")
        expected_sha = str(row.get("sha256") or "")
        actual_sha = sha256_file(path)
        if not expected_sha or actual_sha != expected_sha:
            raise ValueError(f"deploy context digest mismatch: {relative.as_posix()}")
        canonical_rows.append(
            {"dst": relative.as_posix(), "size": expected_size, "sha256": expected_sha}
        )
    if int(manifest.get("file_count") or -1) != len(canonical_rows):
        raise ValueError("deploy context file count mismatch")
    expected_packaged = {row["dst"] for row in canonical_rows} | {DEPLOY_CONTEXT_MANIFEST}
    actual_packaged = {
        path.relative_to(context_dir).as_posix() for path in packaged_context_files(context_dir)
    }
    unexpected = sorted(actual_packaged - expected_packaged)
    missing = sorted(expected_packaged - actual_packaged)
    if unexpected:
        raise ValueError("deploy context contains unlisted packaged files: " + ", ".join(unexpected))
    if missing:
        raise ValueError("deploy context is missing packaged files: " + ", ".join(missing))
    fingerprint_input = json.dumps(
        {
            "files": canonical_rows,
            "current_release_items": manifest.get("current_release_items") or [],
            "data_labels": manifest.get("data_labels") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    actual_fingerprint = hashlib.sha256(fingerprint_input).hexdigest()
    expected_fingerprint = str(manifest.get("fingerprint") or "")
    if actual_fingerprint != expected_fingerprint:
        raise ValueError("deploy context fingerprint mismatch")
    release_manifest_path = context_dir / "data" / "current_release" / "manifest.json"
    try:
        release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("deploy context current release manifest missing or invalid") from exc
    generation_id = str(
        release_manifest.get("generation_id") or release_manifest.get("generationId") or ""
    )
    if not generation_id:
        raise ValueError("deploy context current release is missing generation_id")
    return {
        "fingerprint": actual_fingerprint,
        "expected_generation_id": generation_id,
        "file_count": len(canonical_rows),
        "manifest_sha256": sha256_file(manifest_path),
        "packaged_files": sorted(actual_packaged),
        "file_digests": {row["dst"]: row["sha256"] for row in canonical_rows},
    }


def tcb_api(action: str, body: dict[str, Any], *, service: str = "tcb", api_version: str | None = None) -> dict[str, Any]:
    cmd = [*TCB_CMD, "api", service, action]
    if api_version:
        cmd.extend(["--api-version", api_version])
    cmd.extend(["--body", json.dumps(body, ensure_ascii=False, separators=(",", ":")), "--json"])
    run_kwargs: dict[str, Any] = {
        "cwd": PROJECT_DIR,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
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


def zip_context(
    context_dir: Path,
    zip_path: Path,
    *,
    expected_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not context_dir.exists():
        raise FileNotFoundError(f"context dir not found: {context_dir}")
    context_dir = context_dir.resolve()
    before = validate_deploy_context(context_dir)
    if expected_context and (
        before.get("fingerprint") != expected_context.get("fingerprint")
        or before.get("manifest_sha256") != expected_context.get("manifest_sha256")
    ):
        raise ValueError("deploy context changed before zip creation")
    files = [context_dir / relative for relative in before["packaged_files"]]
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in files:
                zf.write(path, path.relative_to(context_dir).as_posix())
        after = validate_deploy_context(context_dir)
        if (
            after.get("fingerprint") != before.get("fingerprint")
            or after.get("manifest_sha256") != before.get("manifest_sha256")
            or after.get("packaged_files") != before.get("packaged_files")
        ):
            raise ValueError("deploy context changed while zip was being created")
        expected_entry_digests = {
            **before["file_digests"],
            DEPLOY_CONTEXT_MANIFEST: before["manifest_sha256"],
        }
        with zipfile.ZipFile(zip_path, "r") as zf:
            if sorted(zf.namelist()) != before["packaged_files"]:
                raise ValueError("deploy zip entries differ from the validated context manifest")
            for name, expected_sha in expected_entry_digests.items():
                actual_sha = hashlib.sha256(zf.read(name)).hexdigest()
                if actual_sha != expected_sha:
                    raise ValueError(f"deploy zip entry digest mismatch: {name}")
    except Exception:
        if zip_path.exists():
            zip_path.unlink()
        raise
    return {
        "context_dir": str(context_dir.resolve()),
        "zip_path": str(zip_path.resolve()),
        "file_count": len(files),
        "zip_bytes": zip_path.stat().st_size,
        "context_bytes": sum(path.stat().st_size for path in files),
        "zip_sha256": sha256_file(zip_path),
        "deploy_context_fingerprint": before["fingerprint"],
        "deploy_context_manifest_sha256": before["manifest_sha256"],
    }


def upload_package(upload_url: str, zip_path: Path) -> None:
    data = zip_path.read_bytes()
    # Signed COS uploads are large, idempotent PUTs.  Bypass workstation proxy
    # settings here because local HTTP proxies can reset long uploads while the
    # Tencent endpoint itself is directly reachable.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(1, UPLOAD_MAX_ATTEMPTS + 1):
        try:
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
            with opener.open(req, timeout=UPLOAD_TIMEOUT_SECONDS) as response:
                if response.status >= 400:
                    raise SafeDeployError("cloudrun_package_upload_http_error")
            return
        except Exception as exc:  # noqa: BLE001 - convert every URL-bearing error to a fixed safe code
            if attempt >= UPLOAD_MAX_ATTEMPTS:
                if isinstance(exc, SafeDeployError):
                    raise exc from None
                raise SafeDeployError("cloudrun_package_upload_failed") from None
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
                "version_name": safe_remote_identifier(
                    item.get("VersionName") or item.get("versionName")
                ),
                "flow_ratio": item.get("FlowRatio", item.get("flowRatio", "")),
                "status": safe_remote_identifier(item.get("Status") or item.get("status")),
                "update_time": safe_remote_identifier(
                    item.get("UpdateTime") or item.get("updateTime")
                ),
            }
        )
    active = next((item for item in summarized_versions if str(item.get("flow_ratio")) == "100"), summarized_versions[0] if summarized_versions else {})
    return {
        "captured_at": now_iso(),
        "base_url": str(base.get("DefaultDomainName") or "").rstrip("/"),
        "status": safe_remote_identifier(base.get("Status")),
        "update_time": safe_remote_identifier(base.get("UpdateTime")),
        "access_types": base.get("AccessTypes") or [],
        "active_version": active.get("version_name", ""),
        "active_flow_ratio": active.get("flow_ratio", ""),
        "versions": summarized_versions,
        "request_id": safe_remote_identifier(data.get("RequestId")),
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
        status = safe_remote_identifier(task.get("Status") or data.get("Status"))
        version_name = safe_remote_identifier(task.get("VersionName"))
        failure_present = bool(task.get("FailReason"))
        polls.append(
            {
                "at": now_iso(),
                "status": status,
                "version_name": version_name,
                "failure_present": failure_present,
            }
        )
        if status.lower() in {"finished", "success", "succeed", "normal"}:
            return {"ok": True, "status": status, "version_name": version_name, "polls": polls}
        if status.lower() in {"failed", "fail", "error", "deploy_failed"} or failure_present:
            return {"ok": False, "status": status, "polls": polls}
        time.sleep(10)
    return {"ok": False, "status": "poll_timeout", "polls": polls}


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(args.transaction_id or "")):
        raise ValueError("transaction_id must be a safe 1-128 character label")
    lease_evidence: dict[str, Any] = {}
    if not args.dry_run:
        if not args.publish_lease_path or not args.publish_lease_token:
            raise ValueError(
                "production direct deploy requires --publish-lease-path and --publish-lease-token"
            )
        lease_evidence = validate_held_service_publish_lease(
            lease_path=args.publish_lease_path,
            lease_token=args.publish_lease_token,
            transaction_id=args.transaction_id,
            env_id=args.env_id,
            service_name=args.service_name,
            data_root=args.data_root,
        )
    out_dir = args.out_dir
    zip_path = out_dir / "cloudrun_direct_api_context.zip"
    context_evidence = validate_deploy_context(args.context_dir)
    report: dict[str, Any] = {
        "schema_version": "cloudrun_direct_api_deploy.v2",
        "generated_at": now_iso(),
        "ok": False,
        "decision": "cloudrun_direct_api_not_started",
        "env_id": args.env_id,
        "service_name": args.service_name,
        "evidence_binding": {
            "transaction_id": args.transaction_id,
            "env_id": args.env_id,
            "service_name": args.service_name,
            "deploy_context_fingerprint": context_evidence["fingerprint"],
            "expected_generation_id": context_evidence["expected_generation_id"],
            "publish_lease_token_sha256": lease_evidence.get("lease_token_sha256", ""),
        },
        "service_publish_lease": lease_evidence,
        "stage": "context_validated",
        "remote_mutation": {
            "state": "not_attempted",
            "update_attempted": False,
        },
        "safety": {
            "secret_value_read_or_printed": False,
            "upload_url_written": False,
            "cloud_deploy_executed": False,
            "production_publish_verified": False,
        },
    }
    zip_info = zip_context(args.context_dir, zip_path, expected_context=context_evidence)
    report["zip"] = zip_info
    report["evidence_binding"]["deploy_zip_sha256"] = zip_info["zip_sha256"]
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    if args.dry_run:
        report["ok"] = True
        report["decision"] = "cloudrun_direct_api_dry_run_ready"
        write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
        return report

    report["stage"] = "capturing_previous_server_identity"
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    try:
        previous_identity = describe_cloudrun_server_identity(args.env_id, args.service_name)
    except Exception:  # noqa: BLE001 - upstream text can contain credential-bearing request data
        report["previous_server_identity"] = {
            "capture_ok": False,
            "captured_at": now_iso(),
            "failure_code": "previous_server_identity_capture_failed",
        }
        report["failure"] = {"code": "previous_server_identity_capture_failed"}
        report["decision"] = "cloudrun_direct_api_blocked_previous_identity"
        report["stage"] = "blocked_before_remote_update"
        write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
        return report
    previous_identity_failures = validate_previous_server_identity(previous_identity)
    report["previous_server_identity"] = previous_identity
    if previous_identity_failures:
        report["failure"] = {
            "code": "previous_server_identity_not_rollback_capable",
            "checks": previous_identity_failures,
        }
        report["decision"] = "cloudrun_direct_api_blocked_previous_identity"
        report["stage"] = "blocked_before_remote_update"
        write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
        return report

    report["stage"] = "requesting_build_service"
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    build = tcb_api("DescribeCloudBaseBuildService", {"EnvId": args.env_id, "ServiceName": args.service_name})
    package_name = safe_remote_identifier(build.get("PackageName"))
    package_version = safe_remote_identifier(build.get("PackageVersion"))
    upload_url = str(build.get("UploadUrl") or "")
    report["build_service"] = {
        "package_name": package_name,
        "package_version": package_version,
        "has_upload_url": bool(upload_url),
        "has_upload_headers": bool(build.get("UploadHeaders")),
        "request_id": safe_remote_identifier(build.get("RequestId")),
    }
    if not package_name or not package_version or not upload_url:
        report["decision"] = "cloudrun_direct_api_blocked_missing_package_fields"
        write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
        return report

    report["stage"] = "uploading_validated_context"
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    upload_package(upload_url, zip_path)
    report["upload"] = {"ok": True, "zip_bytes": zip_info["zip_bytes"]}
    report["stage"] = "context_uploaded"
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    lease_before_update = validate_held_service_publish_lease(
        lease_path=args.publish_lease_path,
        lease_token=args.publish_lease_token,
        transaction_id=args.transaction_id,
        env_id=args.env_id,
        service_name=args.service_name,
        data_root=args.data_root,
    )
    if lease_before_update.get("lease_token_sha256") != lease_evidence.get("lease_token_sha256"):
        raise ValueError("service publish lease changed before UpdateCloudRunServer")
    report["service_publish_lease_revalidated_before_update"] = {
        **lease_before_update,
        "validated_at": now_iso(),
    }
    report["stage"] = "update_cloudrun_server_attempted"
    report["decision"] = "cloudrun_direct_api_update_attempted"
    report["remote_mutation"] = {
        "state": "update_attempted_unknown",
        "update_attempted": True,
        "attempted_at": now_iso(),
    }
    # Persist the rollback target and mutation intent before the remote call.  If
    # the client loses the response, operators must conservatively assume that
    # CloudBase accepted the update.
    report["safety"]["cloud_deploy_executed"] = True
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    updated = update_cloudrun_server(
        args.env_id,
        args.service_name,
        package_name,
        package_version,
        (
            f"huaidj weekly tx={args.transaction_id} "
            f"ctx={context_evidence['fingerprint'][:12]} "
            f"gen={context_evidence['expected_generation_id'][:20]}"
        ),
    )
    task_id_text = safe_remote_identifier(updated.get("TaskId"))
    request_id = safe_remote_identifier(updated.get("RequestId"))
    report["update_cloudrun_server"] = {
        "response_received": True,
        "task_id_present": bool(task_id_text),
        "request_id": request_id,
    }
    report["deployment_identity"] = {
        "task_id": 0,
        "task_id_raw": task_id_text,
        "request_id": request_id,
        "reported_version": "",
    }
    report["remote_mutation"] = {
        **report["remote_mutation"],
        "state": "update_response_received",
        "response_received_at": now_iso(),
        "request_id": request_id,
    }
    report["stage"] = "update_cloudrun_server_response_received"
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    try:
        task_id = int(task_id_text)
        if task_id <= 0:
            raise ValueError("non-positive task id")
    except (TypeError, ValueError):
        task_id = 0
        poll = {
            "ok": False,
            "status": "invalid_task_id",
            "error_code": "cloudrun_update_response_invalid_task_id",
            "allowed_unverified": bool(args.allow_unverified_task_poll),
        }
    else:
        report["deployment_identity"]["task_id"] = task_id
        try:
            poll = poll_task(args.env_id, args.service_name, task_id, args.max_wait_seconds)
        except Exception:  # noqa: BLE001 - never persist provider exception text
            poll = {
                "ok": False,
                "status": "poll_exception",
                "error_code": "cloudrun_task_poll_exception",
                "allowed_unverified": bool(args.allow_unverified_task_poll),
            }
    report["operation"] = poll
    report["deployment_identity"]["reported_version"] = safe_remote_identifier(
        poll.get("version_name")
    )
    try:
        report["post_update_server_identity"] = describe_cloudrun_server_identity(args.env_id, args.service_name)
    except Exception:  # noqa: BLE001 - never persist provider exception text
        report["post_update_server_identity"] = {
            "capture_ok": False,
            "captured_at": now_iso(),
            "failure_code": "post_update_server_identity_capture_failed",
        }
    report["deployment_identity"]["observed_active_version"] = str(
        (report.get("post_update_server_identity") or {}).get("active_version") or ""
    )
    report["ok"] = bool(poll.get("ok")) or (bool(args.allow_unverified_task_poll) and bool(task_id or request_id))
    if poll.get("ok"):
        report["decision"] = "cloudrun_direct_api_deploy_verified"
    elif report["ok"]:
        report["decision"] = "cloudrun_direct_api_deploy_poll_unverified"
    else:
        report["decision"] = "cloudrun_direct_api_deploy_unverified"
    report["safety"]["production_publish_verified"] = bool(poll.get("ok"))
    report["stage"] = "direct_deploy_finished"
    write_json(out_dir / "cloudrun_direct_api_deploy_report.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-id", default=ENV_ID)
    parser.add_argument("--service-name", default=SERVICE_NAME)
    parser.add_argument(
        "--transaction-id",
        required=True,
        help="Unique publish transaction that owns this immutable deploy context.",
    )
    parser.add_argument("--context-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--publish-lease-path",
        type=Path,
        default=None,
        help="Service-scoped lease file already held by the parent release wrapper.",
    )
    parser.add_argument(
        "--publish-lease-token",
        default="",
        help="Coordination nonce for the already-held service publish lease.",
    )
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
        args.out_dir.mkdir(parents=True, exist_ok=True)
        report_path = args.out_dir / "cloudrun_direct_api_deploy_report.json"
        report = read_existing_report(report_path)
        if not report:
            report = {
                "schema_version": "cloudrun_direct_api_deploy.v2",
                "generated_at": now_iso(),
                "safety": {
                    "secret_value_read_or_printed": False,
                    "upload_url_written": False,
                    "cloud_deploy_executed": False,
                    "production_publish_verified": False,
                },
                "remote_mutation": {
                    "state": "unknown_before_journal",
                    "update_attempted": False,
                },
            }
        report["ok"] = False
        report["decision"] = "cloudrun_direct_api_exception"
        report["failure"] = safe_failure(exc)
        report["failed_at"] = now_iso()
        report.setdefault("safety", {})["production_publish_verified"] = False
        if bool((report.get("remote_mutation") or {}).get("update_attempted")):
            report["safety"]["cloud_deploy_executed"] = True
        write_json(report_path, report)
    print(json.dumps({k: report.get(k) for k in ["ok", "decision"]}, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
