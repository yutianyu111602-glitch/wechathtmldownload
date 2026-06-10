#!/usr/bin/env python3
"""Run bounded report-local source acquisition fetches for Atlas source/OCR.

This consumes source acquisition preflight work orders, resolves source URLs
internally from the sidecar, and stores fetched public HTML only under hashed
report-local bundles. It does not run OCR, accept facts, or write source DB,
serving SQLite, graph/vector, public pointer, or memory state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
PREFLIGHT_ROOT = STAGE7_ROOT / "reports" / "atlas_source_acquisition_preflight_t5_20260526"
DEFAULT_WORK_ORDERS = PREFLIGHT_ROOT / "fetch_preflight_ready_work_orders.jsonl"
DEFAULT_SOURCE_URL_JSONL = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "article_source_url.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_acquisition_bounded_fetch_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_ACQUISITION_BOUNDED_FETCH_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_acquisition_bounded_fetch.v1"

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)
CREDENTIAL_VALUE_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|"
    r"\b(?:token|secret|cookie|password|api[_-]?key|authorization|bearer|access_token|authkey|pass_ticket)\b"
    r"\s*[:=]\s*[^,\s;\"']{8,})"
)
HTML_MARKERS = (
    "rich_media_content",
    "js_content",
    "msg_title",
    "var msg_title",
)
WEAK_OR_BLOCK_MARKERS = (
    "captcha",
    "access denied",
    "verify",
    "login",
    "enable javascript",
    "blocked",
)
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "authkey",
    "code",
    "key",
    "openid",
    "pass_ticket",
    "poc_token",
    "signature",
    "sig",
    "token",
}
BLOCKED_RESPONSE_CONTENT_TYPES = (
    "audio/",
    "video/",
    "application/octet-stream",
)


Fetcher = Callable[[str, float, int], dict[str, Any]]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def full_hash(value: Any) -> str:
    return hashlib.sha256(compact(value, 8000).encode("utf-8", errors="ignore")).hexdigest()


def bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_hash(value: Any, length: int = 20) -> str:
    return full_hash(value)[:length]


def scrub_text(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit)
    text = URL_RE.sub("redacted-url", text)
    text = LOCAL_PATH_RE.sub("redacted-local-path", text)
    text = SENSITIVE_KEY_RE.sub("redacted-word", text)
    return text


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas source acquisition fetch: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_jsonl(path: Path, *, optional: bool = False) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if optional and not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        tmp = Path(handle.name)
    tmp.replace(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def source_url_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        keys: list[str] = []
        for field in ("article_uid", "article_id"):
            value = compact(row.get(field), 300)
            if value:
                keys.append(value)
                if "/" in value:
                    keys.append(value.rsplit("/", 1)[-1])
        for key in keys:
            indexed.setdefault(key, row)
    return indexed


def raw_source_url(row: dict[str, Any] | None) -> str:
    return compact((row or {}).get("source_url"), 5000)


def host_is_public(hostname: str) -> bool:
    host = compact(hostname).strip("[]")
    if not host or host.casefold() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        ip = parse.ipaddress.ip_address(host)  # type: ignore[attr-defined]
    except AttributeError:
        import ipaddress

        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return True
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)


def url_precheck(url: str) -> tuple[bool, str]:
    parsed = parse.urlsplit(compact(url, 5000))
    if parsed.scheme not in {"http", "https"}:
        return False, "unsupported_scheme"
    if not parsed.netloc:
        return False, "missing_host"
    if parsed.username or parsed.password:
        return False, "embedded_auth_material"
    if not host_is_public(parsed.hostname or ""):
        return False, "non_public_host"
    query_keys = {key.casefold() for key, _value in parse.parse_qsl(parsed.query, keep_blank_values=True)}
    if query_keys.intersection(SENSITIVE_QUERY_KEYS):
        return False, "auth_material_query_key_present"
    return True, "fetchable_public_url"


def request_safe_url(url: str) -> str:
    parsed = parse.urlsplit(compact(url, 5000))
    path = parse.quote(parsed.path or "/", safe="/%:@")
    query = parse.quote(parsed.query, safe="=&%:@/?")
    return parse.urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def media_or_attachment_block_reason(content_type: str, content_disposition: str = "") -> str:
    media_type = compact(content_type, 200).split(";", 1)[0].strip().casefold()
    disposition = compact(content_disposition, 300).casefold()
    if any(media_type.startswith(prefix) for prefix in BLOCKED_RESPONSE_CONTENT_TYPES):
        return "copyright_sensitive_media_content_type"
    if "attachment" in disposition:
        return "attachment_download_content_disposition"
    return ""


def fetch_html(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    ok, reason = url_precheck(url)
    if not ok:
        return {
            "ok": False,
            "status_code": 0,
            "content_type": "",
            "body": b"",
            "error_type": reason,
            "error": reason,
        }
    req = request.Request(
        request_safe_url(url),
        headers={
            "User-Agent": "AtlasSourceBoundedFetch/1.0 (+no-auth-material)",
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*;q=0.8",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=timeout_sec) as response:  # noqa: S310 - bounded public URL guard is applied.
        content_type = compact(response.headers.get("content-type", ""), 200)
        content_disposition = compact(response.headers.get("content-disposition", ""), 300)
        media_block_reason = media_or_attachment_block_reason(content_type, content_disposition)
        if media_block_reason:
            return {
                "ok": False,
                "status_code": int(getattr(response, "status", 0) or 0),
                "content_type": content_type,
                "content_disposition": content_disposition,
                "body": b"",
                "error_type": media_block_reason,
                "error": media_block_reason,
                "media_or_attachment_blocked": True,
            }
        return {
            "ok": True,
            "status_code": int(getattr(response, "status", 0) or 0),
            "content_type": content_type,
            "content_disposition": content_disposition,
            "body": response.read(max_bytes),
            "error_type": "",
            "error": "",
        }


def safe_fetch(url: str, timeout_sec: float, max_bytes: int, fetcher: Fetcher) -> dict[str, Any]:
    try:
        return fetcher(url, timeout_sec, max_bytes)
    except error.HTTPError as exc:
        content_type = compact(exc.headers.get("content-type", "") if exc.headers else "", 200)
        content_disposition = compact(exc.headers.get("content-disposition", "") if exc.headers else "", 300)
        media_block_reason = media_or_attachment_block_reason(content_type, content_disposition)
        if media_block_reason:
            return {
                "ok": False,
                "status_code": int(exc.code),
                "content_type": content_type,
                "content_disposition": content_disposition,
                "body": b"",
                "error_type": media_block_reason,
                "error": media_block_reason,
                "media_or_attachment_blocked": True,
            }
        return {
            "ok": False,
            "status_code": int(exc.code),
            "content_type": content_type,
            "content_disposition": content_disposition,
            "body": b"",
            "error_type": "http_status",
            "error": f"http_{int(exc.code)}",
        }
    except (error.URLError, TimeoutError, socket.timeout, OSError, UnicodeError) as exc:
        return {
            "ok": False,
            "status_code": 0,
            "content_type": "",
            "body": b"",
            "error_type": scrub_text(type(exc).__name__, 80),
            "error": scrub_text(str(exc), 240),
        }


def body_text_sample(body: bytes, limit: int = 120_000) -> str:
    return body[:limit].decode("utf-8", errors="replace")


def html_content_flags(body: bytes, content_type: str, expected_title: str = "") -> dict[str, Any]:
    raw_sample = body_text_sample(body)
    sample = raw_sample.casefold()
    js_content = re.search(r"id=[\"']js_content[\"'][^>]*>(.*?)</div>", raw_sample, flags=re.I | re.S)
    js_content_text_len = 0
    if js_content:
        js_content_text_len = len(re.sub(r"<[^>]+>", "", js_content.group(1)).strip())
    title_prefix = compact(expected_title, 80)[:12]
    return {
        "body_bytes": len(body),
        "text_sample_bytes": len(sample.encode("utf-8", errors="ignore")),
        "content_type": scrub_text(content_type, 200),
        "html_like": bool("<html" in sample or "<body" in sample or "<div" in sample or "text/html" in content_type.casefold()),
        "wechat_article_marker_seen": any(marker in sample for marker in HTML_MARKERS),
        "js_content_text_len": js_content_text_len,
        "title_prefix_seen": bool(title_prefix and title_prefix in raw_sample),
        "weak_or_block_marker_seen": any(marker in sample for marker in WEAK_OR_BLOCK_MARKERS),
    }


def classify_fetch(fetch: dict[str, Any], content_flags: dict[str, Any]) -> tuple[str, list[str], bool, bool]:
    status = int(fetch.get("status_code") or 0)
    if fetch.get("media_or_attachment_blocked"):
        return (
            "blocked_media_or_attachment_report_only",
            [compact(fetch.get("error_type"), 80) or "media_or_attachment_blocked"],
            False,
            False,
        )
    if not fetch.get("ok"):
        if status:
            return "blocked_http_status_report_only", [f"http_{status}"], False, False
        return "fetch_error_or_safety_block_report_only", [compact(fetch.get("error_type"), 80) or "fetch_error"], False, False
    if not (200 <= status < 400):
        return "blocked_http_status_report_only", [f"http_{status}"], False, False
    if not content_flags["body_bytes"]:
        return "blocked_empty_body_report_only", ["empty_body"], False, False
    has_article_content = bool(
        content_flags["wechat_article_marker_seen"]
        or content_flags["js_content_text_len"] >= 20
        or content_flags["title_prefix_seen"]
    )
    if content_flags["weak_or_block_marker_seen"] and not has_article_content:
        return (
            "fetched_html_verification_shell_blocked_report_only",
            ["weak_or_block_marker_seen", "article_content_marker_absent"],
            True,
            False,
        )
    if has_article_content and content_flags["html_like"]:
        return "fetched_html_article_content_review_ready", ["article_content_marker_seen", "html_like"], True, True
    if content_flags["weak_or_block_marker_seen"]:
        return "fetched_html_weak_or_block_marker_review_only", ["weak_or_block_marker_seen"], True, False
    if content_flags["html_like"]:
        return "fetched_html_content_weak_review_only", ["html_like", "article_content_marker_absent"], True, False
    return "fetched_non_html_review_only", ["non_html_or_unknown_content"], False, False


def artifact_bundle_dir(out_dir: Path, work_order: dict[str, Any]) -> Path:
    ticket_id = compact(work_order.get("acquisition_ticket_id"), 160)
    article_uid = compact(work_order.get("article_uid"), 240)
    return out_dir / "artifact_bundles" / safe_hash(f"{ticket_id}|{article_uid}", 24)


def build_result_row(
    *,
    generated_at: str,
    work_order: dict[str, Any],
    source_row: dict[str, Any] | None,
    out_dir: Path,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Fetcher,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    article_uid = compact(work_order.get("article_uid"), 240)
    source_evidence = work_order.get("source_url_evidence")
    if not isinstance(source_evidence, dict):
        source_evidence = {}
    candidate_hash = compact(source_evidence.get("candidate_source_url_sha256"), 96)
    sidecar_url = raw_source_url(source_row)
    sidecar_hash = full_hash(sidecar_url) if sidecar_url else ""
    hash_verified = bool(candidate_hash and sidecar_hash and candidate_hash == sidecar_hash)
    url_found = bool(source_row and sidecar_url)

    base = {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "article_uid": article_uid,
        "work_item_id": compact(work_order.get("work_item_id"), 120),
        "source_account": scrub_text(work_order.get("source_account"), 240),
        "title": scrub_text(work_order.get("title"), 500),
        "source_ref_id": compact(work_order.get("source_ref_id"), 160),
        "acquisition_ticket_id": compact(work_order.get("acquisition_ticket_id"), 160),
        "source_url_sha256": sidecar_hash,
        "source_url_hash_verified": hash_verified,
        "raw_source_url_emitted": False,
        "raw_target_path_emitted": False,
        "network_fetch_executed": False,
        "artifact_written": False,
        "article_artifact_ready": False,
        "artifact_bundle_ref_id": compact(
            (work_order.get("report_local_artifact_scope") or {}).get("artifact_bundle_ref_id"), 120
        ),
        "html_artifact_ref_id": "",
        "html_sha256": "",
        "html_bytes": 0,
        "status_code": 0,
        "content_type": "",
        "content_disposition": "",
        "content_flags": {
            "body_bytes": 0,
            "text_sample_bytes": 0,
            "html_like": False,
            "wechat_article_marker_seen": False,
            "weak_or_block_marker_seen": False,
        },
        "decision": "",
        "decision_reasons": [],
        "rollback_ref": "delete_report_local_bundle_for_ticket_only",
        "accepted_for_graph": False,
        "ocr_generation_allowed_now": False,
        "acceptance_precheck_allowed_now": False,
        "graph_write_allowed": False,
        "serving_rebuild_allowed": False,
        "source_sqlite_write_executed": False,
        "ocr_execution_executed": False,
        "write_status": "report_local_fetch_only",
    }

    if not url_found:
        base["decision"] = "blocked_source_url_missing_report_only"
        base["decision_reasons"] = ["source_url_missing_from_sidecar"]
        return base, None
    if not hash_verified:
        base["decision"] = "blocked_source_url_hash_mismatch_report_only"
        base["decision_reasons"] = ["source_url_hash_mismatch"]
        return base, None

    fetch_precheck_ok, fetch_precheck_reason = url_precheck(sidecar_url)
    if not fetch_precheck_ok:
        base["decision"] = "blocked_fetch_safety_precheck_report_only"
        base["decision_reasons"] = [fetch_precheck_reason]
        return base, None

    fetch = safe_fetch(sidecar_url, timeout_sec=timeout_sec, max_bytes=max_bytes, fetcher=fetcher)
    body = fetch.get("body") or b""
    if isinstance(body, str):
        body = body.encode("utf-8", errors="replace")
    content_flags = html_content_flags(body, compact(fetch.get("content_type"), 200), compact(work_order.get("title"), 500))
    decision, reasons, artifact_write_allowed, article_artifact_ready = classify_fetch(fetch, content_flags)
    base.update(
        {
            "network_fetch_executed": True,
            "status_code": int(fetch.get("status_code") or 0),
            "content_type": content_flags["content_type"],
            "content_disposition": scrub_text(fetch.get("content_disposition"), 300),
            "content_flags": content_flags,
            "decision": decision,
            "decision_reasons": reasons,
            "article_artifact_ready": article_artifact_ready,
        }
    )
    if fetch.get("error_type"):
        base["fetch_error_type"] = scrub_text(fetch.get("error_type"), 80)
    if fetch.get("error"):
        base["fetch_error"] = scrub_text(fetch.get("error"), 240)

    manifest: dict[str, Any] | None = None
    if artifact_write_allowed and body:
        bundle_dir = artifact_bundle_dir(out_dir, work_order)
        html_path = bundle_dir / "article.html"
        atomic_write_bytes(html_path, body)
        html_sha = bytes_hash(body)
        html_ref = f"report_local_html_artifact:{html_sha[:24]}"
        base.update(
            {
                "artifact_written": True,
                "article_artifact_ready": article_artifact_ready,
                "html_artifact_ref_id": html_ref,
                "html_sha256": html_sha,
                "html_bytes": len(body),
                "artifact_bundle_relpath": display_path(bundle_dir),
            }
        )
        manifest = {
            "schema_version": SCHEMA_VERSION + ".manifest",
            "generated_at": generated_at,
            "article_uid": article_uid,
            "source_account": base["source_account"],
            "source_ref_id": base["source_ref_id"],
            "acquisition_ticket_id": base["acquisition_ticket_id"],
            "source_url_sha256": sidecar_hash,
            "source_url_hash_verified": True,
            "raw_source_url_emitted": False,
            "raw_target_path_emitted": False,
            "artifact_bundle_ref_id": base["artifact_bundle_ref_id"],
            "artifact_bundle_relpath": base["artifact_bundle_relpath"],
            "html_artifact_ref_id": html_ref,
            "html_sha256": html_sha,
            "html_bytes": len(body),
            "status_code": base["status_code"],
            "content_type": base["content_type"],
            "content_disposition": base["content_disposition"],
            "content_flags": content_flags,
            "rollback_ref": "delete_report_local_bundle_for_ticket_only",
            "article_artifact_ready": article_artifact_ready,
            "ocr_generation_allowed_now": False,
            "acceptance_precheck_allowed_now": False,
            "accepted_for_graph": False,
            "write_status": "report_local_artifact_created",
        }
    return base, manifest


def leak_scan(rows: list[dict[str, Any]]) -> dict[str, int]:
    text = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(CREDENTIAL_VALUE_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def build_source_rollup(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"] or "UNKNOWN"].append(row)
    rollup = []
    for source, source_rows in sorted(grouped.items()):
        rollup.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_rollup",
                "generated_at": generated_at,
                "source_account": source,
                "target_rows": len(source_rows),
                "network_fetch_executed_rows": sum(1 for row in source_rows if row["network_fetch_executed"]),
                "artifact_written_rows": sum(1 for row in source_rows if row["artifact_written"]),
                "article_artifact_ready_rows": sum(1 for row in source_rows if row["article_artifact_ready"]),
                "html_bytes_total": sum(int(row.get("html_bytes") or 0) for row in source_rows),
                "decision_counts": dict(sorted(Counter(row["decision"] for row in source_rows).items())),
                "accepted_for_graph": 0,
                "ocr_generation_allowed_now_rows": 0,
                "acceptance_precheck_allowed_now_rows": 0,
                "write_status": "report_local_fetch_only",
            }
        )
    return rollup


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T5 Source Acquisition Bounded Fetch - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_local_fetch_only`",
        "",
        "## LLM Audit Finding",
        "",
        "The 04:56 preflight created five fetch-ready source acquisition work orders. This runner resolved those raw source URLs only inside the process, verified sidecar SHA256 per ticket, attempted bounded public HTML fetches, and wrote only hashed report-local evidence. OCR, graph acceptance, DB/vector/public writes, and serving rebuilds remain closed.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input work orders: `{counts['input_work_orders']}`",
        f"- Source URL hash verified rows: `{counts['source_url_hash_verified_rows']}`",
        f"- Network fetch executed rows: `{counts['network_fetch_executed_rows']}`",
        f"- Response artifact written rows: `{counts['artifact_written_rows']}`",
        f"- Article artifact ready rows: `{counts['article_artifact_ready_rows']}`",
        f"- Blocked/not-article-ready rows: `{counts['blocked_or_not_ready_rows']}`",
        f"- HTML bytes total: `{counts['html_bytes_total']}`",
        f"- OCR generation allowed now: `{counts['ocr_generation_allowed_now_rows']}`",
        f"- Acceptance precheck allowed now: `{counts['acceptance_precheck_allowed_now_rows']}`",
        f"- Report/manifest URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        f"- Summary JSON: `{outputs['summary_json']}`",
        f"- Fetch manifest: `{outputs['fetch_manifest_jsonl']}`",
        f"- Fetch succeeded rows: `{outputs['fetch_succeeded_jsonl']}`",
        f"- Fetch blocked/no-artifact rows: `{outputs['fetch_blocked_jsonl']}`",
        f"- Source rollup: `{outputs['source_rollup_jsonl']}`",
        "",
        "## Decision Counts",
        "",
    ]
    for key, value in summary["decision_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Row Snapshot", ""])
    for row in rows[:10]:
        lines.append(
            f"- `{row['article_uid']}` `{row['source_account']}` -> `{row['decision']}`; status `{row['status_code']}`; response artifact `{row['artifact_written']}`; article-ready `{row['article_artifact_ready']}`; bytes `{row['html_bytes']}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Network fetch happened only for preflight-ready public source URLs after sidecar SHA256 verification.",
            "- Audio/video/octet-stream/attachment responses are blocked before body read and never persisted.",
            "- Raw source URLs are never emitted to JSON, Markdown, stdout, or logs by this runner.",
            "- Leak scan covers JSON/Markdown report metadata and excludes raw fetched HTML by design; raw HTML is source evidence stored only inside hashed report-local bundles.",
            "- No OCR execution, source/OCR acceptance, source/raw Atlas DB write, serving SQLite rebuild/write, Neo4j/Qdrant/vector write, public pointer, deploy, upload/review, memory write, credential read, browser profile use, or D root scan occurred.",
            "",
            "## Next Cursor",
            "",
            "Review `fetch_blocked_rows.jsonl` if article-ready rows are zero; otherwise review `fetch_succeeded_rows.jsonl` and the manifest content flags. If article-ready rows pass content/leak policy, build the next report-only image/OCR-generation gate. Do not rerun source/OCR acceptance until exact-date and OCR/Markdown evidence exists.",
            "",
        ]
    )
    return "\n".join(lines)


def run_bounded_fetch(
    *,
    work_orders_path: Path,
    source_url_jsonl: Path,
    out_dir: Path,
    report_path: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Fetcher = fetch_html,
) -> dict[str, Any]:
    for label, path in (
        ("work_orders_path", work_orders_path),
        ("source_url_jsonl", source_url_jsonl),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        reject_d_path(path, label)

    generated_at = now_iso()
    work_orders = [row for row in read_jsonl(work_orders_path) if row.get("fetch_preflight_ready")]
    if limit > 0:
        work_orders = work_orders[:limit]
    source_rows = source_url_index(read_jsonl(source_url_jsonl, optional=True))

    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    for work_order in work_orders:
        article_uid = compact(work_order.get("article_uid"), 240)
        result, manifest = build_result_row(
            generated_at=generated_at,
            work_order=work_order,
            source_row=source_rows.get(article_uid),
            out_dir=out_dir,
            timeout_sec=timeout_sec,
            max_bytes=max_bytes,
            fetcher=fetcher,
        )
        rows.append(result)
        if manifest:
            manifest_rows.append(manifest)

    succeeded = [row for row in rows if row["article_artifact_ready"]]
    blocked = [row for row in rows if not row["article_artifact_ready"]]
    source_rollup = build_source_rollup(rows, generated_at)
    scan_rows = rows + manifest_rows + source_rollup
    leak_hits = leak_scan(scan_rows)
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        failed_checks.append("source_acquisition_fetch_report_or_manifest_contains_public_url_secret_or_local_path")
    if not rows:
        failed_checks.append("no_source_acquisition_fetch_rows")
    if any(row["ocr_generation_allowed_now"] or row["accepted_for_graph"] for row in rows):
        failed_checks.append("source_acquisition_fetch_opened_later_gate_unexpectedly")

    decision = (
        "atlas_source_acquisition_bounded_fetch_article_artifacts_ready_report_only"
        if succeeded and not failed_checks
        else "atlas_source_acquisition_bounded_fetch_blocked_report_only"
        if rows and not failed_checks
        else "atlas_source_acquisition_bounded_fetch_failed_safety_scan"
    )
    counts = {
        "input_work_orders": len(rows),
        "source_url_hash_verified_rows": sum(1 for row in rows if row["source_url_hash_verified"]),
        "network_fetch_executed_rows": sum(1 for row in rows if row["network_fetch_executed"]),
        "artifact_written_rows": sum(1 for row in rows if row["artifact_written"]),
        "article_artifact_ready_rows": len(succeeded),
        "blocked_or_not_ready_rows": len(blocked),
        "html_bytes_total": sum(int(row.get("html_bytes") or 0) for row in rows),
        "media_or_attachment_blocked_rows": sum(1 for row in rows if row["decision"] == "blocked_media_or_attachment_report_only"),
        "ocr_generation_allowed_now_rows": sum(1 for row in rows if row["ocr_generation_allowed_now"]),
        "acceptance_precheck_allowed_now_rows": sum(1 for row in rows if row["acceptance_precheck_allowed_now"]),
        "accepted_for_graph_rows": sum(1 for row in rows if row["accepted_for_graph"]),
    }
    outputs = {
        "summary_json": display_path(out_dir / "source_acquisition_bounded_fetch_summary.json"),
        "fetch_manifest_jsonl": display_path(out_dir / "source_acquisition_fetch_manifest.jsonl"),
        "fetch_succeeded_jsonl": display_path(out_dir / "fetch_succeeded_rows.jsonl"),
        "fetch_blocked_jsonl": display_path(out_dir / "fetch_blocked_rows.jsonl"),
        "source_rollup_jsonl": display_path(out_dir / "source_rollup.jsonl"),
        "report_markdown": display_path(report_path),
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "work_orders": display_path(work_orders_path),
            "source_url_jsonl": display_path(source_url_jsonl),
            "limit": limit,
            "timeout_sec": timeout_sec,
            "max_bytes": max_bytes,
        },
        "outputs": outputs,
        "counts": counts,
        "decision_counts": dict(sorted(Counter(row["decision"] for row in rows).items())),
        "status_counts": dict(sorted(Counter(str(row.get("status_code") or 0) for row in rows).items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] for row in rows).items())),
        "leak_scan": leak_hits,
        "llm_audit": {
            "artifact_consistency": "Resolved source URLs only in process and verified sidecar SHA256 before fetch.",
            "stale_loop_avoided": "Did not rerun source/OCR acceptance or OCR generation before manifest/content evidence exists.",
            "highest_leverage_next_lane": "review fetch_succeeded_rows.jsonl, then build image/OCR-generation gate only for artifact-written rows.",
        },
        "execution_cursor": {
            "next_lane": "source_acquisition_artifact_content_review_or_image_ocr_generation_gate",
            "next_input": outputs["fetch_succeeded_jsonl"] if succeeded else outputs["fetch_blocked_jsonl"],
            "rerun_ocr_generation_now": False,
            "rerun_acceptance_precheck_now": False,
            "next_command_intent": "Inspect fetched HTML response artifacts/content flags; if only verification shells were fetched, route to browser-safe/manual source artifact acquisition instead of OCR generation.",
        },
        "safety": {
            "report_local_only": True,
            "raw_source_url_emitted": False,
            "raw_local_path_emitted": False,
            "network_fetch_executed": any(row["network_fetch_executed"] for row in rows),
            "copyright_audio_video_or_attachment_fetched": False,
            "auth_material_used": False,
            "browser_profile_used": False,
            "ocr_execution_executed": False,
            "llm_call_executed": False,
            "production_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "source_sqlite_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if decision.endswith("article_artifacts_ready_report_only") else "source_acquisition_fetch_content_blocked_or_safety_failed",
        "wait_reason": "ready_for_content_or_image_ocr_gate" if succeeded and not failed_checks else "source_fetch_no_usable_article_artifact_or_failed_scan",
    }

    write_jsonl(out_dir / "source_acquisition_fetch_manifest.jsonl", manifest_rows)
    write_jsonl(out_dir / "fetch_succeeded_rows.jsonl", succeeded)
    write_jsonl(out_dir / "fetch_blocked_rows.jsonl", blocked)
    write_jsonl(out_dir / "source_rollup.jsonl", source_rollup)
    write_json(out_dir / "source_acquisition_bounded_fetch_summary.json", summary)
    write_text(report_path, render_report(summary, rows))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-orders", type=Path, default=DEFAULT_WORK_ORDERS)
    parser.add_argument("--source-url-jsonl", type=Path, default=DEFAULT_SOURCE_URL_JSONL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--max-bytes", type=int, default=524288)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_bounded_fetch(
        work_orders_path=args.work_orders,
        source_url_jsonl=args.source_url_jsonl,
        out_dir=args.out_dir,
        report_path=args.report,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "artifact_written_rows": summary["counts"]["artifact_written_rows"],
                "article_artifact_ready_rows": summary["counts"]["article_artifact_ready_rows"],
                "network_fetch_executed_rows": summary["counts"]["network_fetch_executed_rows"],
                "summary": summary["outputs"]["summary_json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
