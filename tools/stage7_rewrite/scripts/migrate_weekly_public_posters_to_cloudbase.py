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
import re
import shutil
import subprocess
import sys
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
                return value.rsplit("/", 1)[0].split("weekly-posters/", 1)[0]
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


def download(url: str, target: Path, timeout: int) -> tuple[Path, int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenClawWeeklyPosterMigrator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
        content_type = response.headers.get("content-type", "")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target, len(data), content_type


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


def resolve_tcb_command() -> str:
    for name in ("tcb", "tcb.cmd", "cloudbase", "cloudbase.cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("CloudBase CLI not found in PATH: expected tcb/tcb.cmd/cloudbase/cloudbase.cmd")


def upload_to_cloudbase(local_path: Path, cloud_path: str, env_id: str, timeout: int) -> tuple[str, dict[str, Any], str]:
    cmd = [
        resolve_tcb_command(),
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
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    parsed = parse_json_object(combined)
    if result.returncode != 0:
        raise SystemExit(f"CloudBase poster upload failed for {cloud_path}: exit={result.returncode}")
    return find_file_id(parsed), parsed if isinstance(parsed, dict) else {}, strip_ansi(combined).strip()


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
    cloud_prefix = args.mock_file_id_prefix or infer_cloud_prefix(items)
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

        content_type = ""
        bytes_written = 0
        if args.mock_file_id_prefix:
            local_path = local_stub.with_suffix(ext)
        else:
            local_path, bytes_written, content_type = download(public_url, local_stub.with_suffix(ext), args.download_timeout_sec)
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
            file_id, upload_json, upload_text = upload_to_cloudbase(local_path, cloud_path, args.env_id, args.upload_timeout_sec)
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
                "upload": upload_json,
            }
        )

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

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "api_dir": str(api_dir),
        "env_id": args.env_id,
        "cloud_dir": args.cloud_dir,
        "requested_write": requested_write,
        "write": write_authorized,
        "dry_run": not write_authorized,
        "write_authorized": write_authorized,
        "confirm_token_required": confirm_token_required,
        "confirm_token_valid": confirm_token_valid,
        "blocked_reason": blocked_reason,
        "target_count": len(targets),
        "planned_uploads": planned_uploads,
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
    parser.add_argument("--cache-dir", type=Path, default=Path("D:/downstream_results/stage7_rewrite/longrun/weekly_poster_cloudbase_cache"))
    parser.add_argument("--download-timeout-sec", type=int, default=45)
    parser.add_argument("--upload-timeout-sec", type=int, default=180)
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
