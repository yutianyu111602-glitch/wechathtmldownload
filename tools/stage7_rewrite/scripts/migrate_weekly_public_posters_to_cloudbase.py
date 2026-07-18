#!/usr/bin/env python
"""Migrate public WeChat poster URLs in a weekly API package to CloudBase storage.

The release package must not depend on mmbiz/qpic public poster URLs. This
script only patches candidate API package files after a successful CloudBase
storage upload; it does not deploy CloudRun, sync databases, upload the
mini-program, or read credential files.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_public_poster_cloudbase_migration.v1"
CONFIRM_TOKEN_PREFIX = "ENABLE_CLOUDBASE_POSTER_MIGRATION"
PUBLIC_POSTER_FIELDS = (
    "poster_url",
    "posterUrl",
    "flyer_url",
    "cover_image_url",
    "cover_url",
    "raw_cover_url",
    "coverUrl",
)
INTERNAL_POSTER_FIELDS = (
    "poster_file_id",
    "posterFileId",
    "cloudFileId",
    "cover_file_id",
    "coverFileId",
)
POSTER_STORAGE_FIELDS = ("poster_storage", "posterStorage")


def confirm_token_for_cloud_dir(cloud_dir: str) -> str:
    suffix = str(cloud_dir or "").rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"\d{8}", suffix or ""):
        suffix = "UNKNOWN"
    return f"{CONFIRM_TOKEN_PREFIX}_{suffix}"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def is_public_wechat_image_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith(("http://", "https://")) and (
        "mmbiz.qpic.cn" in text or "mmecoa.qpic.cn" in text or "qpic.cn" in text
    )


def is_internal_file_id(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith(("cloud://", "cloudbase://", "wxfile://"))


def item_id(item: dict[str, Any]) -> str:
    return first_text(item.get("id"), item.get("event_id"), item.get("article_id"), item.get("queue_id"))


def item_public_poster_url(item: dict[str, Any]) -> str:
    for field in PUBLIC_POSTER_FIELDS:
        value = first_text(item.get(field))
        if is_public_wechat_image_url(value):
            return html.unescape(value)
    return ""


def item_internal_file_id(item: dict[str, Any]) -> str:
    return first_text(*(item.get(field) for field in INTERNAL_POSTER_FIELDS))


def safe_slug(value: str) -> str:
    text = value.replace(":", "u3a")
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return text[:120] or "poster"


def extension_from_url(url: str, content_type: str = "") -> str:
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    wx_fmt = first_text(*(qs.get("wx_fmt") or []))
    if wx_fmt:
        wx_fmt = wx_fmt.lower().replace("jpeg", "jpg")
        if wx_fmt in {"jpg", "png", "gif", "webp"}:
            return "." + wx_fmt
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else ""
    if guessed:
        return ".jpg" if guessed == ".jpe" else guessed
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def infer_cloud_prefix(items: list[dict[str, Any]]) -> str:
    for item in items:
        for field in INTERNAL_POSTER_FIELDS + PUBLIC_POSTER_FIELDS:
            value = first_text(item.get(field))
            if value.startswith("cloud://") and "/" in value:
                return normalize_cloud_prefix(value.rsplit("/", 1)[0].split("weekly-posters/", 1)[0])
    return ""


def normalize_cloud_prefix(value: str) -> str:
    text = first_text(value)
    if not text.startswith("cloud://"):
        return ""
    return text.rstrip("/") + "/"


def infer_cloud_prefix_from_reference_release(api_dir: Path) -> str:
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        repo_root / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json",
        api_dir.parent / "current_release" / "current.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            prefix = infer_cloud_prefix([item for item in items if isinstance(item, dict)])
            if prefix:
                return prefix
    return ""


def load_current_items(api_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    current = read_json(api_dir / "current.json")
    items = current.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"current.json does not contain items: {api_dir / 'current.json'}")
    return current, items


def migration_targets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        internal = item_internal_file_id(item)
        if is_internal_file_id(internal):
            continue
        public_url = item_public_poster_url(item)
        if not public_url:
            continue
        iid = item_id(item)
        if not iid:
            continue
        out.append({"id": iid, "title": first_text(item.get("title_display"), item.get("title")), "public_url": public_url})
    return out


def cached_download(local_stub: Path, preferred_ext: str) -> Path | None:
    candidates: list[Path] = []
    if preferred_ext:
        candidates.append(local_stub.with_suffix(preferred_ext))
    candidates.extend(sorted(local_stub.parent.glob(local_stub.name + ".*")) if local_stub.parent.exists() else [])
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def write_bytes_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)


def download_with_urllib(url: str, target: Path, timeout: int) -> tuple[Path, int, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 MicroMessenger/8.0.49 NetType/WIFI "
                "MiniProgramEnv/Windows OpenClawWeeklyPosterMigrator/1.1"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
        content_type = response.headers.get("content-type", "")
    write_bytes_atomic(target, data)
    return target, len(data), content_type


def download_with_curl(url: str, target: Path, timeout: int) -> tuple[Path, int, str]:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl not found for poster download fallback")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    cmd = [
        curl,
        "-L",
        "--fail",
        "--show-error",
        "--silent",
        "--http1.1",
        "--connect-timeout",
        str(min(timeout, 20)),
        "--max-time",
        str(max(timeout, 20)),
        "--retry",
        "2",
        "--retry-delay",
        "1",
        "-A",
        (
            "Mozilla/5.0 MicroMessenger/8.0.49 NetType/WIFI "
            "MiniProgramEnv/Windows OpenClawWeeklyPosterMigrator/1.1"
        ),
        "-o",
        str(tmp),
        "-w",
        "%{http_code}\t%{content_type}\t%{size_download}",
        url,
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout + 15)
    if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size <= 0:
        if tmp.exists():
            tmp.unlink()
        preview = strip_ansi((result.stderr or result.stdout or "")).strip()[:300]
        raise RuntimeError(f"curl download failed: exit={result.returncode}; output={preview}")
    stdout = (result.stdout or "").strip()
    parts = stdout.rsplit("\t", 2)
    status = parts[0] if parts else ""
    content_type = parts[1] if len(parts) >= 2 else ""
    if status and not status.startswith("2"):
        tmp.unlink()
        raise RuntimeError(f"curl download returned HTTP {status}")
    tmp.replace(target)
    return target, target.stat().st_size, content_type


def download(url: str, target: Path, timeout: int) -> tuple[Path, int, str, str]:
    errors: list[str] = []
    for attempt in range(1, 4):
        try:
            path, size, content_type = download_with_urllib(url, target, timeout)
            return path, size, content_type, f"urllib_attempt_{attempt}"
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            errors.append(f"urllib_attempt_{attempt}:{type(exc).__name__}:{str(exc)[:160]}")
            if attempt < 3:
                time.sleep(attempt)
    try:
        path, size, content_type = download_with_curl(url, target, timeout)
        return path, size, content_type, "curl_fallback"
    except Exception as exc:  # noqa: BLE001 - report all fallback failures in migration JSON/error text.
        errors.append(f"curl_fallback:{type(exc).__name__}:{str(exc)[:160]}")
    raise RuntimeError("; ".join(errors))


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def parse_json_object(text: str) -> Any:
    clean = strip_ansi(text).strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        return json.loads(clean[start : end + 1])
    except json.JSONDecodeError:
        return {}


def find_file_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("fileID", "fileId", "file_id", "FileId"):
            text = first_text(value.get(key))
            if text.startswith("cloud://"):
                return text
        for child in value.values():
            found = find_file_id(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = find_file_id(child)
            if found:
                return found
    return ""


def resolve_tcb_command() -> list[str]:
    for name in ("tcb", "tcb.cmd", "cloudbase", "cloudbase.cmd"):
        found = shutil.which(name)
        if found:
            return [found]
    # Keep this aligned with the deploy and poster-replacement paths.  The
    # project pins the known-compatible CloudBase CLI and npm's local cache
    # makes the scheduled path independent of a machine-global tcb shim.
    npm = shutil.which("npm") or "npm"
    return [npm, "exec", "--yes", "--package", "@cloudbase/cli@3.3.1", "--", "tcb"]


def upload_to_cloudbase(
    local_path: Path,
    cloud_path: str,
    env_id: str,
    timeout: int,
    max_attempts: int,
    retry_backoff_sec: float,
) -> tuple[str, dict[str, Any], str]:
    cmd = [
        *resolve_tcb_command(),
        "-e",
        env_id,
        "storage",
        "upload",
        str(local_path),
        cloud_path,
        "--json",
        "--times",
        "3",
    ]
    combined = ""
    parsed: Any = {}
    result_returncode = 1
    max_attempts = max(1, max_attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
            result_returncode = result.returncode
            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            parsed = parse_json_object(combined)
            if result.returncode == 0:
                break
        except (OSError, subprocess.TimeoutExpired) as exc:
            result_returncode = 124 if isinstance(exc, subprocess.TimeoutExpired) else 1
            combined = f"{type(exc).__name__}: {exc}"
            parsed = {}
        if attempt < max_attempts:
            time.sleep(max(0.0, retry_backoff_sec) * (2 ** (attempt - 1)))
    if result_returncode != 0:
        preview = strip_ansi(combined).strip()[:800]
        raise SystemExit(f"CloudBase poster upload failed for {cloud_path}: exit={result_returncode}; output={preview}")
    return find_file_id(parsed), parsed if isinstance(parsed, dict) else {}, strip_ansi(combined).strip()


def list_remote_cloud_keys(
    env_id: str,
    cloud_dir: str,
    timeout: int,
    max_attempts: int,
    retry_backoff_sec: float,
) -> tuple[set[str], str]:
    cmd = [*resolve_tcb_command(), "-e", env_id, "storage", "list", cloud_dir, "--json"]
    combined = ""
    max_attempts = max(1, max_attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            parsed = parse_json_object(combined)
            if result.returncode == 0 and isinstance(parsed, dict):
                rows = parsed.get("data")
                if isinstance(rows, list):
                    keys = {
                        first_text(row.get("key"), row.get("Key"), row.get("path"))
                        for row in rows
                        if isinstance(row, dict)
                    }
                    return {key for key in keys if key}, ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            combined = f"{type(exc).__name__}: {exc}"
        if attempt < max_attempts:
            time.sleep(max(0.0, retry_backoff_sec) * (2 ** (attempt - 1)))
    return set(), strip_ansi(combined).strip()[:800]


def load_checkpoint(path: Path, env_id: str, cloud_dir: str) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("env_id") != env_id or payload.get("cloud_dir") != cloud_dir:
        return {}
    completed = payload.get("completed")
    if not isinstance(completed, dict):
        return {}
    return {str(key): value for key, value in completed.items() if isinstance(value, dict)}


def save_checkpoint(
    path: Path,
    env_id: str,
    cloud_dir: str,
    completed: dict[str, dict[str, str]],
    status: str,
    target_count: int,
) -> None:
    write_json_atomic(
        path,
        {
            "schema_version": SCHEMA_VERSION + ".checkpoint.v1",
            "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "env_id": env_id,
            "cloud_dir": cloud_dir,
            "status": status,
            "target_count": target_count,
            "completed_count": len(completed),
            "completed": completed,
        },
    )


def patch_item(item: dict[str, Any], file_id: str, cloud_path: str, migrated_at: str, public_url: str) -> bool:
    if item_id(item) == "":
        return False
    changed = False
    for field in INTERNAL_POSTER_FIELDS:
        if item.get(field) != file_id:
            item[field] = file_id
            changed = True
    for field in PUBLIC_POSTER_FIELDS:
        if field in item and item.get(field) != file_id:
            item[field] = file_id
            changed = True
    for field in ("poster_url", "cover_url", "cover_image_url", "coverUrl"):
        if item.get(field) != file_id:
            item[field] = file_id
            changed = True
    for field in POSTER_STORAGE_FIELDS:
        if item.get(field) != "cloudbase":
            item[field] = "cloudbase"
            changed = True
    item["poster_cloud_path"] = cloud_path
    item["poster_source"] = "cloudbase_storage_from_wechat_article"
    item["poster_migrated_at"] = migrated_at
    item["poster_public_source_hash"] = hashlib.sha256(public_url.encode("utf-8")).hexdigest()[:16]
    return changed


def patch_nested(payload: Any, patches: dict[str, dict[str, str]]) -> int:
    changed = 0
    if isinstance(payload, dict):
        iid = item_id(payload)
        if iid in patches and patch_item(
            payload,
            patches[iid]["file_id"],
            patches[iid]["cloud_path"],
            patches[iid]["migrated_at"],
            patches[iid]["public_url"],
        ):
            changed += 1
        for value in payload.values():
            changed += patch_nested(value, patches)
    elif isinstance(payload, list):
        for value in payload:
            changed += patch_nested(value, patches)
    return changed


def json_files(api_dir: Path) -> list[Path]:
    files = [api_dir / "current.json"]
    for subdir in ("by-id", "by-city", "by-date"):
        root = api_dir / subdir
        if root.exists():
            files.extend(sorted(root.glob("*.json")))
    return [path for path in files if path.exists()]


def migrate(args: argparse.Namespace) -> dict[str, Any]:
    api_dir = args.api_dir
    current, items = load_current_items(api_dir)
    targets = migration_targets(items)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    cloud_prefix = (
        normalize_cloud_prefix(args.mock_file_id_prefix)
        or normalize_cloud_prefix(args.cloud_prefix)
        or infer_cloud_prefix(items)
        or infer_cloud_prefix_from_reference_release(api_dir)
    )
    requested_write = bool(args.write)
    confirm_token_required = confirm_token_for_cloud_dir(args.cloud_dir)
    confirm_token_valid = str(args.confirm_token or "").strip() == confirm_token_required
    write_authorized = requested_write and confirm_token_valid
    blocked_reason = ""
    if requested_write and not confirm_token_valid:
        blocked_reason = "missing_or_invalid_confirm_token"
    patches: dict[str, dict[str, str]] = {}
    uploads: list[dict[str, Any]] = []
    planned_uploads: list[dict[str, Any]] = []
    checkpoint_path = args.checkpoint or (
        args.cache_dir / f"migration-{safe_slug(args.env_id)}-{safe_slug(args.cloud_dir)}.checkpoint.json"
    )
    completed = load_checkpoint(checkpoint_path, args.env_id, args.cloud_dir) if write_authorized else {}
    remote_keys: set[str] = set()
    remote_list_error = ""
    if write_authorized and not args.mock_file_id_prefix:
        remote_keys, remote_list_error = list_remote_cloud_keys(
            args.env_id,
            args.cloud_dir,
            args.upload_timeout_sec,
            args.remote_list_attempts,
            args.upload_retry_backoff_sec,
        )
    resumed_checkpoint_count = 0
    resumed_remote_count = 0

    for target in targets:
        iid = target["id"]
        public_url = target["public_url"]
        digest = hashlib.sha256(public_url.encode("utf-8")).hexdigest()[:20]
        local_stub = args.cache_dir / f"{safe_slug(iid)}--{digest}"
        ext = extension_from_url(public_url, "")
        cloud_path = f"{args.cloud_dir.rstrip('/')}/{safe_slug(iid)}--{digest}{ext}"
        if not write_authorized:
            planned_uploads.append(
                {
                    "id": iid,
                    "title": target["title"],
                    "cloud_path": cloud_path,
                    "public_url_hash": hashlib.sha256(public_url.encode("utf-8")).hexdigest()[:16],
                }
            )
            continue

        cloud_path_prefix = f"{args.cloud_dir.rstrip('/')}/{safe_slug(iid)}--{digest}"
        prior = completed.get(iid, {})
        prior_cloud_path = first_text(prior.get("cloud_path"))
        prior_file_id = first_text(prior.get("file_id"))
        prior_public_hash = first_text(prior.get("public_url_hash"))
        resume_source = ""
        if (
            prior_cloud_path.startswith(cloud_path_prefix)
            and is_internal_file_id(prior_file_id)
            and prior_public_hash == hashlib.sha256(public_url.encode("utf-8")).hexdigest()[:16]
        ):
            cloud_path = prior_cloud_path
            file_id = prior_file_id
            resume_source = "checkpoint"
            resumed_checkpoint_count += 1
        else:
            remote_matches = sorted(key for key in remote_keys if key.startswith(cloud_path_prefix + "."))
            if remote_matches and cloud_prefix:
                cloud_path = remote_matches[0]
                file_id = cloud_prefix.rstrip("/") + "/" + cloud_path
                resume_source = "remote_storage"
                resumed_remote_count += 1

        if resume_source:
            patches[iid] = {
                "file_id": file_id,
                "cloud_path": cloud_path,
                "public_url": public_url,
                "migrated_at": first_text(prior.get("migrated_at")) or generated_at,
            }
            uploads.append(
                {
                    "id": iid,
                    "title": target["title"],
                    "cloud_path": cloud_path,
                    "file_id": file_id,
                    "bytes": 0,
                    "content_type": "",
                    "download_source": resume_source,
                    "upload": {"resumed": True, "source": resume_source},
                }
            )
            completed[iid] = {
                "cloud_path": cloud_path,
                "file_id": file_id,
                "public_url_hash": hashlib.sha256(public_url.encode("utf-8")).hexdigest()[:16],
                "migrated_at": patches[iid]["migrated_at"],
            }
            save_checkpoint(checkpoint_path, args.env_id, args.cloud_dir, completed, "in_progress", len(targets))
            continue

        content_type = ""
        bytes_written = 0
        download_source = ""
        if args.mock_file_id_prefix:
            local_path = local_stub.with_suffix(ext)
        else:
            cached_path = cached_download(local_stub, ext)
            if cached_path:
                local_path = cached_path
                bytes_written = cached_path.stat().st_size
                content_type = mimetypes.guess_type(cached_path.name)[0] or ""
                download_source = "cache"
            else:
                local_path, bytes_written, content_type, download_source = download(
                    public_url,
                    local_stub.with_suffix(ext),
                    args.download_timeout_sec,
                )
            real_ext = extension_from_url(public_url, content_type)
            if real_ext != local_path.suffix:
                real_path = local_stub.with_suffix(real_ext)
                local_path.replace(real_path)
                local_path = real_path
                cloud_path = f"{args.cloud_dir.rstrip('/')}/{safe_slug(iid)}--{digest}{real_ext}"
        if args.mock_file_id_prefix:
            file_id = args.mock_file_id_prefix.rstrip("/") + "/" + cloud_path
            upload_json: dict[str, Any] = {"mock": True}
        else:
            file_id, upload_json, upload_text = upload_to_cloudbase(
                local_path,
                cloud_path,
                args.env_id,
                args.upload_timeout_sec,
                args.upload_max_attempts,
                args.upload_retry_backoff_sec,
            )
            if not file_id:
                if not cloud_prefix:
                    raise SystemExit(f"CloudBase upload returned no fileID and no cloud prefix could be inferred: {iid}")
                file_id = cloud_prefix.rstrip("/") + "/" + cloud_path
            upload_json = {"parsed": upload_json, "stdout_preview": upload_text[:500]}
        patches[iid] = {
            "file_id": file_id,
            "cloud_path": cloud_path,
            "public_url": public_url,
            "migrated_at": generated_at,
        }
        uploads.append(
            {
                "id": iid,
                "title": target["title"],
                "cloud_path": cloud_path,
                "file_id": file_id,
                "bytes": bytes_written,
                "content_type": content_type,
                "download_source": download_source,
                "upload": upload_json,
            }
        )
        completed[iid] = {
            "cloud_path": cloud_path,
            "file_id": file_id,
            "public_url_hash": hashlib.sha256(public_url.encode("utf-8")).hexdigest()[:16],
            "migrated_at": generated_at,
        }
        save_checkpoint(checkpoint_path, args.env_id, args.cloud_dir, completed, "in_progress", len(targets))

    patched_files: list[str] = []
    patched_occurrences = 0
    if write_authorized and patches:
        for path in json_files(api_dir):
            payload = read_json(path)
            changed = patch_nested(payload, patches)
            if changed:
                write_json(path, payload)
                patched_files.append(str(path))
                patched_occurrences += changed
        manifest_path = api_dir / "manifest.json"
        if manifest_path.exists():
            manifest = read_json(manifest_path)
            manifest["poster_migration"] = {
                "schema_version": SCHEMA_VERSION + ".manifest",
                "migrated_at": generated_at,
                "migrated_count": len(patches),
                "cloud_dir": args.cloud_dir,
                "env_id": args.env_id,
            }
            write_json(manifest_path, manifest)
            patched_files.append(str(manifest_path))

    if write_authorized and len(patches) == len(targets):
        save_checkpoint(checkpoint_path, args.env_id, args.cloud_dir, completed, "complete", len(targets))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "api_dir": str(api_dir),
        "env_id": args.env_id,
        "cloud_dir": args.cloud_dir,
        "cloud_prefix": cloud_prefix,
        "requested_write": requested_write,
        "write": write_authorized,
        "dry_run": not write_authorized,
        "write_authorized": write_authorized,
        "confirm_token_required": confirm_token_required,
        "confirm_token_valid": confirm_token_valid,
        "blocked_reason": blocked_reason,
        "target_count": len(targets),
        "planned_uploads": planned_uploads,
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_completed_count": len(completed),
        "resumed_checkpoint_count": resumed_checkpoint_count,
        "resumed_remote_count": resumed_remote_count,
        "remote_discovered_count": len(remote_keys),
        "remote_list_error": remote_list_error,
        "migrated_count": len(patches),
        "patched_occurrences": patched_occurrences,
        "patched_files": patched_files,
        "uploads": uploads,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--env-id", default="huaidjweekly-d8g1go7-d0a07863e3e")
    parser.add_argument("--cloud-dir", required=True)
    parser.add_argument("--cloud-prefix", default=os.environ.get("HUAIDJ_WEEKLY_POSTER_CLOUD_PREFIX", ""))
    parser.add_argument("--cache-dir", type=Path, default=Path("E:/weekly_activity_pipeline/longrun/weekly_poster_cloudbase_cache"))
    parser.add_argument("--download-timeout-sec", type=int, default=45)
    parser.add_argument("--upload-timeout-sec", type=int, default=180)
    parser.add_argument("--upload-max-attempts", type=int, default=5)
    parser.add_argument("--upload-retry-backoff-sec", type=float, default=3.0)
    parser.add_argument("--remote-list-attempts", type=int, default=3)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--mock-file-id-prefix", default="")
    args = parser.parse_args(argv)

    report = migrate(args)
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("requested_write") and not report.get("write_authorized"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
