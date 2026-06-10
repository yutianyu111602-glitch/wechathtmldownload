#!/usr/bin/env python3
"""Build PRD-05a bounded URL seed queue and HTTP fast image evidence report.

This is the first layer of the OpenCLI external evidence plan. It uses only
bounded PRD-05a blocker samples and plain HTTP. It does not use browser state,
OpenCLI, OCR, paid APIs, graph/vector/DB writes, source archive mutation,
production publish, or D: scans.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


DEFAULT_BLOCKER_SYNTHESIS = Path("reports/ocr_asset_blocker_synthesis_20260515/ocr_asset_blocker_synthesis.json")
DEFAULT_MANIFEST = Path("reports/fullmap_manifest_20260513_routes/needs_ocr.remaining.jsonl")
DEFAULT_OUT_DIR = Path("reports/prd05a_external_evidence_fast_20260516")
SCHEMA_VERSION = "stage7_prd05a_external_evidence_fast.v1"
IMAGE_ATTRS = ("src", "data-src", "data-original", "data-backsrc", "data-ratio", "data-url")
SRCSET_ATTRS = ("srcset", "data-srcset")
IMAGE_KEYS = {"image", "images", "thumbnail", "thumbnailurl", "contenturl", "url"}
REMOVED_MARKERS = ("该内容已被发布者删除", "此内容因违规无法查看", "此内容无法查看", "内容已删除")
AUTH_MARKERS = ("环境异常", "登录", "验证", "安全验证", "访问受限")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
SENSITIVE_QUERY_KEYS = {"authkey", "key", "pass_ticket", "poc_token", "signature", "sig", "token"}


class EvidenceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_url = ""
        self.meta_images: list[tuple[str, str]] = []
        self.image_attrs: list[tuple[str, str]] = []
        self.pdf_candidates: list[str] = []
        self.jsonld_blobs: list[str] = []
        self._in_jsonld = False
        self._jsonld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.casefold(): v or "" for k, v in attrs}
        lowered = tag.casefold()
        if lowered == "link":
            rel = attr.get("rel", "").casefold()
            href = attr.get("href", "")
            if "canonical" in rel and href:
                self.canonical_url = href
        if lowered == "meta":
            key = (attr.get("property") or attr.get("name") or "").casefold()
            content = attr.get("content", "")
            if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"} and content:
                self.meta_images.append((key, content))
        if lowered in {"img", "source"}:
            for name in IMAGE_ATTRS:
                value = attr.get(name)
                if value:
                    self.image_attrs.append((name, value))
            for name in SRCSET_ATTRS:
                value = attr.get(name)
                if value:
                    for url in split_srcset(value):
                        self.image_attrs.append((name, url))
        if lowered == "a":
            href = attr.get("href", "")
            if href and is_pdf_or_attachment(href):
                self.pdf_candidates.append(href)
        if lowered == "script" and "ld+json" in attr.get("type", "").casefold():
            self._in_jsonld = True
            self._jsonld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._in_jsonld:
            self._in_jsonld = False
            blob = "".join(self._jsonld_parts).strip()
            if blob:
                self.jsonld_blobs.append(blob)
            self._jsonld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld_parts.append(data)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_broad_d_path(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_jsonl(path: Path, limit: int = 0) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
            if limit > 0 and len(rows) >= limit:
                break
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
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


def split_srcset(value: str) -> list[str]:
    urls: list[str] = []
    for part in first_text(value).split(","):
        token = part.strip().split(" ")[0].strip()
        if token:
            urls.append(token)
    return urls


def is_pdf_or_attachment(url: str) -> bool:
    lowered = first_text(url).casefold()
    return lowered.endswith(".pdf") or ".pdf?" in lowered or "download" in lowered


def article_url(token: str) -> str:
    return f"https://mp.weixin.qq.com/s/{token}"


def parse_uid(uid: str) -> tuple[str, str]:
    if "/" not in uid:
        return "", uid
    account, token = uid.split("/", 1)
    return account, token


def build_seed_queue(blocker_synthesis: Path, manifest_path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = read_json(blocker_synthesis)
    manifest_rows = read_jsonl(manifest_path, limit=max(limit * 4, 100))
    manifest_by_uid = {first_text(row.get("article_uid")): row for row in manifest_rows}
    sample_missing = report.get("empty_no_local_image", {}).get("sample_missing") or []
    blockers = report.get("blockers") or []
    blocker_reason = "; ".join(first_text(item) for item in blockers if first_text(item))

    queue: list[dict[str, Any]] = []
    seen: set[str] = set()
    for uid in sample_missing:
        account, token = parse_uid(first_text(uid))
        if not token or uid in seen:
            continue
        seen.add(first_text(uid))
        manifest_row = manifest_by_uid.get(first_text(uid), {})
        queue.append(
            {
                "schema_version": SCHEMA_VERSION + ".queue_row",
                "source_prd": "PRD-05a",
                "source_article_id": first_text(uid),
                "source_account": account or first_text(manifest_row.get("source_account")),
                "article_token": token,
                "input_url": article_url(token),
                "title": first_text(manifest_row.get("title")),
                "blocker_reason": blocker_reason or "missing OCR local image evidence",
                "current_local_image_count": manifest_row.get("local_image_count", 0),
                "priority": 10,
                "unsafe_action": False,
            }
        )
        if limit > 0 and len(queue) >= limit:
            break

    if limit <= 0 or len(queue) < limit:
        for row in manifest_rows:
            uid = first_text(row.get("article_uid"))
            if not uid or uid in seen:
                continue
            account, token = parse_uid(uid)
            if not token:
                continue
            seen.add(uid)
            queue.append(
                {
                    "schema_version": SCHEMA_VERSION + ".queue_row",
                    "source_prd": "PRD-05a",
                    "source_article_id": uid,
                    "source_account": account or first_text(row.get("source_account")),
                    "article_token": token,
                    "input_url": article_url(token),
                    "title": first_text(row.get("title")),
                    "blocker_reason": blocker_reason or "missing OCR local image evidence",
                    "current_local_image_count": row.get("local_image_count", 0),
                    "priority": 20,
                    "unsafe_action": False,
                }
            )
            if limit > 0 and len(queue) >= limit:
                break

    meta = {
        "source_blocker_synthesis": str(blocker_synthesis),
        "source_manifest": str(manifest_path),
        "blocker_decision": report.get("decision"),
        "blocker_reason": blocker_reason,
        "requested_limit": limit,
        "queue_rows": len(queue),
    }
    return queue, meta


class RedirectRecorder(request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.redirects: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        self.redirects.append(first_text(newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    redirect_handler = RedirectRecorder()
    opener = request.build_opener(redirect_handler)
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Stage7 PRD-05a HTTP evidence canary",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with opener.open(req, timeout=timeout_sec) as resp:
            body = resp.read(max_bytes + 1)
            truncated = len(body) > max_bytes
            body = body[:max_bytes]
            content_type = resp.headers.get("content-type", "")
            charset = resp.headers.get_content_charset() or "utf-8"
            text = body.decode(charset, errors="replace")
            return {
                "ok": True,
                "status_code": int(getattr(resp, "status", 0) or 0),
                "final_url": resp.geturl(),
                "redirect_chain": redirect_handler.redirects,
                "content_type": content_type,
                "body": text,
                "bytes_read": len(body),
                "truncated": truncated,
                "error": "",
            }
    except error.HTTPError as exc:
        body = exc.read(max_bytes)
        text = body.decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "final_url": exc.geturl(),
            "redirect_chain": redirect_handler.redirects,
            "content_type": exc.headers.get("content-type", ""),
            "body": text,
            "bytes_read": len(body),
            "truncated": False,
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 - report-only evidence needs exact failure text.
        return {
            "ok": False,
            "status_code": 0,
            "final_url": url,
            "redirect_chain": redirect_handler.redirects,
            "content_type": "",
            "body": "",
            "bytes_read": 0,
            "truncated": False,
            "error": str(exc),
        }


def normalize_url(url: str, base_url: str) -> str:
    raw = first_text(url)
    if not raw:
        return ""
    raw = raw.replace("&amp;", "&")
    joined = parse.urljoin(base_url, raw)
    parsed = parse.urlparse(joined)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parse.urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", parsed.query, ""))


def redact_url_for_report(url: str) -> str:
    raw = first_text(url)
    if not raw:
        return ""
    parsed = parse.urlparse(raw)
    if not parsed.query:
        return raw
    pairs = parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted_pairs = [(key, value) for key, value in pairs if key.casefold() not in SENSITIVE_QUERY_KEYS]
    return parse.urlunparse(parsed._replace(query=parse.urlencode(redacted_pairs, doseq=True)))


def looks_like_image_url(url: str) -> bool:
    parsed = parse.urlparse(first_text(url))
    lowered = parsed.path.casefold()
    host = parsed.netloc.casefold()
    query = parse.parse_qs(parsed.query)
    if lowered.endswith(IMAGE_EXTENSIONS):
        return True
    if "mmbiz.qpic.cn" in host or "qpic.cn" in host:
        return True
    if "wx_fmt" in query or "format" in query:
        return True
    return False


def extract_jsonld_images(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.casefold()
            if lowered in IMAGE_KEYS:
                if isinstance(child, str):
                    found.append(child)
                elif isinstance(child, list):
                    found.extend(str(item) for item in child if isinstance(item, str))
                    for item in child:
                        if isinstance(item, dict):
                            found.extend(extract_jsonld_images(item))
                elif isinstance(child, dict):
                    found.extend(extract_jsonld_images(child))
            elif isinstance(child, (dict, list)):
                found.extend(extract_jsonld_images(child))
    elif isinstance(value, list):
        for item in value:
            found.extend(extract_jsonld_images(item))
    return found


def parse_html_evidence(html: str, base_url: str) -> dict[str, Any]:
    parser = EvidenceHTMLParser()
    parser.feed(html)
    asset_candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_candidate(source_field: str, raw_url: str) -> None:
        normalized = normalize_url(raw_url, base_url)
        if not normalized or normalized in seen or not looks_like_image_url(normalized):
            return
        seen.add(normalized)
        asset_candidates.append(
            {
                "source_field": source_field,
                "url": normalized,
                "domain": parse.urlparse(normalized).netloc.casefold(),
            }
        )

    for field, url in parser.meta_images:
        add_candidate(field, url)
    for field, url in parser.image_attrs:
        add_candidate(field, url)
    jsonld_errors = 0
    for blob in parser.jsonld_blobs:
        try:
            value = json.loads(blob)
        except json.JSONDecodeError:
            jsonld_errors += 1
            continue
        for url in extract_jsonld_images(value):
            add_candidate("jsonld:image", url)

    pdf_candidates: list[str] = []
    for url in parser.pdf_candidates:
        normalized = normalize_url(url, base_url)
        if normalized and normalized not in pdf_candidates:
            pdf_candidates.append(normalized)

    return {
        "canonical_url": normalize_url(parser.canonical_url, base_url),
        "asset_candidates": asset_candidates,
        "pdf_candidates": pdf_candidates[:20],
        "jsonld_candidate_count": sum(1 for row in asset_candidates if row["source_field"].startswith("jsonld")),
        "jsonld_parse_errors": jsonld_errors,
    }


def classify_evidence(fetch: dict[str, Any], parsed: dict[str, Any]) -> str:
    body = first_text(fetch.get("body"))
    status = int(fetch.get("status_code") or 0)
    final_url = first_text(fetch.get("final_url")).casefold()
    if parsed.get("asset_candidates"):
        return "source_image_found"
    if "appmsgcaptcha" in final_url:
        return "auth_required"
    if status in {401, 403} or any(marker in body for marker in AUTH_MARKERS):
        return "auth_required"
    if status == 0 or status >= 500 or first_text(fetch.get("error")):
        return "unreachable"
    if any(marker in body for marker in REMOVED_MARKERS):
        return "no_source_image_removed_or_violation"
    if "<script" in body and len(body) > 0:
        return "no_image_or_js_needed"
    return "no_image"


Fetcher = Callable[[str, float, int], dict[str, Any]]


def evaluate_queue_row(row: dict[str, Any], fetcher: Fetcher, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    fetch = fetcher(first_text(row.get("input_url")), timeout_sec, max_bytes)
    parsed = parse_html_evidence(first_text(fetch.get("body")), first_text(fetch.get("final_url") or row.get("input_url")))
    decision = classify_evidence(fetch, parsed)
    raw_final_url = first_text(fetch.get("final_url") or row.get("input_url"))
    return {
        "schema_version": SCHEMA_VERSION + ".evidence_row",
        "source_prd": "PRD-05a",
        "source_article_id": first_text(row.get("source_article_id")),
        "source_account": first_text(row.get("source_account")),
        "input_url": first_text(row.get("input_url")),
        "final_url": redact_url_for_report(raw_final_url),
        "redirect_chain": [redact_url_for_report(url) for url in (fetch.get("redirect_chain") or [])],
        "canonical_url": redact_url_for_report(parsed.get("canonical_url") or ""),
        "status_code": int(fetch.get("status_code") or 0),
        "content_type": first_text(fetch.get("content_type")),
        "bytes_read": fetch.get("bytes_read", 0),
        "truncated": bool(fetch.get("truncated")),
        "asset_candidates": parsed.get("asset_candidates") or [],
        "pdf_candidates": parsed.get("pdf_candidates") or [],
        "jsonld_candidate_count": parsed.get("jsonld_candidate_count", 0),
        "jsonld_parse_errors": parsed.get("jsonld_parse_errors", 0),
        "decision": decision,
        "blocker_reason": first_text(row.get("blocker_reason")),
        "opencli_needed": decision in {"auth_required", "no_image_or_js_needed"},
        "unsafe_action": False,
        "write_scope": "reports_only",
        "error": first_text(fetch.get("error")),
    }


def build_fast_report(
    blocker_synthesis: Path,
    manifest_path: Path,
    out_dir: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Fetcher = fetch_url,
) -> dict[str, Any]:
    reject_broad_d_path(out_dir, "out_dir")
    queue, queue_meta = build_seed_queue(blocker_synthesis, manifest_path, limit)
    out_dir.mkdir(parents=True, exist_ok=True)
    queue_path = out_dir / "url_seed_queue.jsonl"
    evidence_path = out_dir / "external_evidence_fast.jsonl"
    write_jsonl(queue_path, queue)

    evidence_rows = [evaluate_queue_row(row, fetcher, timeout_sec, max_bytes) for row in queue]
    write_jsonl(evidence_path, evidence_rows)

    decision_counts = Counter(first_text(row.get("decision")) for row in evidence_rows)
    source_image_rows = decision_counts.get("source_image_found", 0)
    opencli_needed_rows = sum(1 for row in evidence_rows if row.get("opencli_needed"))
    summary_decision = "source_image_found_report_ready" if source_image_rows else "opencli_or_new_source_needed"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_prd": "PRD-05a",
        "decision": summary_decision,
        "ok": True,
        "queue_meta": queue_meta,
        "queue_path": str(queue_path),
        "evidence_path": str(evidence_path),
        "seed_rows": len(queue),
        "evidence_rows": len(evidence_rows),
        "source_image_rows": source_image_rows,
        "opencli_needed_rows": opencli_needed_rows,
        "decision_counts": dict(decision_counts),
        "asset_candidate_count": sum(len(row.get("asset_candidates") or []) for row in evidence_rows),
        "pdf_candidate_count": sum(len(row.get("pdf_candidates") or []) for row in evidence_rows),
        "next_gate": (
            "PRD-05a review must accept a source-backed image contract before OCR queue rebuild"
            if source_image_rows
            else "Use OpenCLI only for bounded HTTP blind spots or continue paid/source-backed recapture"
        ),
        "safety": [
            "reports_only",
            "bounded_prd05a_seed_queue",
            "http_fast_layer_only",
            "no_opencli_browser_state",
            "no_cookie_token_export",
            "no_ocr_execution",
            "no_paid_api",
            "no_graph_vector_db_write",
            "no_source_archive_mutation",
            "no_d_scan",
            "no_publish",
        ],
    }
    write_json(out_dir / "external_evidence_fast_summary.json", summary)
    write_markdown(out_dir / "external_evidence_fast_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-05a External Evidence Fast Layer",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- seed_rows: `{summary['seed_rows']}`",
        f"- evidence_rows: `{summary['evidence_rows']}`",
        f"- source_image_rows: `{summary['source_image_rows']}`",
        f"- opencli_needed_rows: `{summary['opencli_needed_rows']}`",
        f"- asset_candidate_count: `{summary['asset_candidate_count']}`",
        f"- pdf_candidate_count: `{summary['pdf_candidate_count']}`",
        f"- queue_path: `{summary['queue_path']}`",
        f"- evidence_path: `{summary['evidence_path']}`",
        "",
        "## Decisions",
        "",
    ]
    for key, value in sorted(summary["decision_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Next Gate", "", f"- {summary['next_gate']}", "", "## Safety", ""])
    for item in summary["safety"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocker-synthesis", type=Path, default=DEFAULT_BLOCKER_SYNTHESIS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_fast_report(
        blocker_synthesis=args.blocker_synthesis,
        manifest_path=args.manifest,
        out_dir=args.out_dir,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
