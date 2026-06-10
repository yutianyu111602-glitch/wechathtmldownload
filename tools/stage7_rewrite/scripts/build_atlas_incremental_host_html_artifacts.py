#!/usr/bin/env python3
"""Build Stage7 LLM artifacts from incremental WeChat URL metadata.

This is a host-side fallback for cases where the local Docker exporter can
list article metadata but its /download endpoint fails to parse mp.weixin
article pages. It fetches article HTML directly, extracts visible text, runs
bounded poster-image OCR when possible, and writes the same manifest shape
consumed by stage7_deepseek_flash_pilot.py.

The generated LLM input intentionally omits raw source URLs, cookies, and
private filesystem roots. Source URL hashes/tokens remain available for local
lineage joins.
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
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx


SCHEMA_VERSION = "atlas_incremental_host_html_artifacts.v1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
IMAGE_ATTR_RE = re.compile(
    r"""(?:data-src|src|data-original|data-backsrc|data-lazy-src)=["']([^"']+)["']""",
    re.I,
)
RAW_URL_RE = re.compile(r"""https?://[^\s<>"'）)\]}】]+""", re.I)
META_CONTENT_RE = re.compile(
    r"""<meta\s+[^>]*(?:property|name)=["'](?P<name>[^"']+)["'][^>]*content=["'](?P<value>[^"']*)["'][^>]*>""",
    re.I,
)
FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
TEXT_SKIP_PREFIXES = (
    "var ",
    "window.",
    "function(",
    "copyright",
    "微信扫一扫",
    "继续滑动看下一个",
)
META_EVIDENCE_KEYS = (
    "description",
    "og:description",
    "twitter:description",
    "og:title",
    "twitter:title",
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sha16(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def safe_name(value: str, fallback: str = "item") -> str:
    text = FILENAME_SAFE_RE.sub("_", str(value or "").strip()).strip("._-")
    return text[:80] or fallback


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def compact_text(value: str, *, max_chars: int = 120000) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in value.splitlines():
        line = re.sub(r"\s+", " ", html.unescape(raw_line)).strip()
        if not line:
            continue
        low = line.lower()
        if any(low.startswith(prefix) for prefix in TEXT_SKIP_PREFIXES):
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(redact_raw_urls(line))
        if sum(len(item) for item in lines) >= max_chars:
            break
    return "\n".join(lines).strip()


def redact_raw_urls(value: str) -> str:
    """Remove raw URLs before content is sent to an online LLM."""

    def repl(match: re.Match[str]) -> str:
        parsed = urlparse(match.group(0))
        host = parsed.netloc.lower() or "unknown"
        host = host[4:] if host.startswith("www.") else host
        return f"[link:{host}]"

    return RAW_URL_RE.sub(repl, value)


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []
        self._line_break_tags = {"p", "div", "br", "section", "article", "li", "tr", "h1", "h2", "h3", "h4"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in self._line_break_tags:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in self._line_break_tags:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def extract_visible_text(html_text: str) -> str:
    parser = VisibleTextParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        return compact_text(re.sub(r"<[^>]+>", "\n", html_text))
    return compact_text(parser.text())


def extract_meta(html_text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for match in META_CONTENT_RE.finditer(html_text):
        name = html.unescape(match.group("name")).strip()
        value = html.unescape(match.group("value")).strip()
        if name and value and name not in meta:
            meta[name] = value
    return meta


def source_context_lines(*, row_digest: str, page_meta: dict[str, str], max_chars: int = 4000) -> list[str]:
    lines: list[str] = []
    if row_digest:
        lines.extend(["### Queue Digest", redact_raw_urls(row_digest)[:1200], ""])
    seen: set[str] = set()
    meta_lines: list[str] = []
    for key in META_EVIDENCE_KEYS:
        value = str(page_meta.get(key) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        meta_lines.append(f"- {key}: {redact_raw_urls(value)[:800]}")
    if meta_lines:
        lines.extend(["### Page Metadata", *meta_lines, ""])
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text.splitlines() if text else []


def clean_image_url(raw: str) -> str:
    value = html.unescape(str(raw or "").strip())
    if not value or value.startswith("data:"):
        return ""
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if "mmbiz.qpic.cn" not in parsed.netloc and "mmbiz.qlogo.cn" not in parsed.netloc:
        return ""
    query = parse_qs(parsed.query, keep_blank_values=True)
    # Keep wx_fmt when present, but drop volatile width/height hints.
    kept = {}
    for key in ("wx_fmt", "tp"):
        if key in query:
            kept[key] = query[key][-1]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(kept), ""))


def extract_image_urls(html_text: str, cover_url: str = "") -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    candidates = [cover_url] if cover_url else []
    candidates.extend(match.group(1) for match in IMAGE_ATTR_RE.finditer(html_text))
    for raw in candidates:
        url = clean_image_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def guess_image_suffix(content_type: str, url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    fmt = first_text(*(query.get("wx_fmt") or []))
    if fmt:
        fmt = fmt.lower().replace("jpeg", "jpg")
        if fmt in {"jpg", "png", "webp", "gif", "bmp"}:
            return "." + fmt
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip().lower())
    if guessed:
        return ".jpg" if guessed == ".jpe" else guessed
    return ".jpg"


def fetch_html(client: httpx.Client, url: str, timeout_sec: int) -> tuple[int, str, str]:
    response = client.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://mp.weixin.qq.com/",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
        timeout=timeout_sec,
        follow_redirects=True,
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.status_code, response.url.host or "", response.text


def fetch_image(client: httpx.Client, url: str, path: Path, timeout_sec: int) -> bool:
    response = client.get(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": "https://mp.weixin.qq.com/"},
        timeout=timeout_sec,
        follow_redirects=True,
    )
    response.raise_for_status()
    if not response.content or len(response.content) < 256:
        return False
    final_path = path.with_suffix(guess_image_suffix(response.headers.get("content-type", ""), url))
    final_path.write_bytes(response.content)
    if final_path != path:
        path = final_path
    return True


def tesseract_exe() -> str:
    return shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def image_is_ocr_candidate(path: Path, *, min_width: int, min_height: int) -> tuple[bool, str]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        if width < min_width or height < min_height:
            return False, f"small_image:{width}x{height}"
        return True, f"{width}x{height}"
    except Exception as exc:
        return True, f"dimension_probe_failed:{type(exc).__name__}"


def ocr_image(path: Path, *, timeout_sec: int, lang: str, min_width: int, min_height: int) -> dict[str, Any]:
    candidate, reason = image_is_ocr_candidate(path, min_width=min_width, min_height=min_height)
    if not candidate:
        return {
            "image_path": str(path),
            "ocr_status": "skipped",
            "skip_reason": reason,
            "text": "",
            "text_chars": 0,
        }
    exe = tesseract_exe()
    if not Path(exe).exists():
        return {
            "image_path": str(path),
            "ocr_status": "tesseract_missing",
            "text": "",
            "text_chars": 0,
        }
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_base = Path(tmp_dir) / "ocr"
        try:
            result = subprocess.run(
                [exe, str(path), str(out_base), "-l", lang, "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return {
                "image_path": str(path),
                "ocr_status": "timeout",
                "text": "",
                "text_chars": 0,
            }
        out_txt = out_base.with_suffix(".txt")
        text = out_txt.read_text(encoding="utf-8", errors="replace") if out_txt.exists() else ""
        text = compact_text(text, max_chars=12000)
        return {
            "image_path": str(path),
            "ocr_status": "complete" if result.returncode == 0 else "failed",
            "image_probe": reason,
            "returncode": result.returncode,
            "stderr_preview": (result.stderr or "")[:240],
            "text": text,
            "text_chars": len(text),
        }


def article_uid(row: dict[str, Any]) -> str:
    account_key = first_text(row.get("account_key"), row.get("account_nickname"), "unknown_account")
    token = first_text(row.get("source_url_token"), row.get("token"), row.get("source_url_hash"), row.get("title"))
    return f"atlas_inc/{safe_name(account_key)}/{sha16(token)}"


def article_id(row: dict[str, Any]) -> str:
    token = first_text(row.get("source_url_token"), row.get("token"), row.get("source_url_hash"), row.get("title"))
    return sha16(token)


def build_llm_input(
    *,
    title: str,
    account: str,
    publish_time: str,
    body_text: str,
    ocr_items: list[dict[str, Any]],
    image_count: int,
    source_hash: str,
    row_digest: str,
    page_meta: dict[str, str],
) -> str:
    ocr_texts = [str(item.get("text") or "").strip() for item in ocr_items if str(item.get("text") or "").strip()]
    context_lines = source_context_lines(row_digest=row_digest, page_meta=page_meta)
    lines = [
        f"# {title}",
        "",
        "## Article Metadata",
        "",
        f"- 公众号: {account}",
        f"- 发布时间: {publish_time}",
        f"- Source URL hash: {source_hash}",
        f"- Local image count: {image_count}",
        "",
        "## Source Context",
        "",
        *(context_lines or ["(No queue digest or useful page metadata.)"]),
        "",
        "## Main Content",
        "",
        body_text or "(empty body text)",
        "",
        "## Poster OCR",
        "",
    ]
    if ocr_texts:
        for index, text in enumerate(ocr_texts, start=1):
            lines.extend([f"### Image OCR {index}", "", text[:12000], ""])
    elif image_count:
        lines.append("(No OCR text extracted from downloaded images.)")
    else:
        lines.append("(No article images discovered.)")
    lines.extend(
        [
            "",
            "## Evidence Boundary",
            "",
            "- Raw source URLs, cookies, and private filesystem paths are intentionally omitted from this LLM input.",
            "- Poster OCR comes from local Tesseract OCR and may miss Chinese text when the installed language pack is unavailable.",
            "",
        ]
    )
    return "\n".join(lines)


@dataclass
class WorkerArgs:
    out_dir: Path
    html_timeout_sec: int
    image_timeout_sec: int
    ocr_timeout_sec: int
    download_images: bool
    run_ocr: bool
    max_images_per_article: int
    tesseract_lang: str
    min_ocr_width: int
    min_ocr_height: int
    retries: int
    retry_sleep_sec: float


def process_row(row: dict[str, Any], args: WorkerArgs) -> dict[str, Any]:
    uid = article_uid(row)
    aid = article_id(row)
    account_key = safe_name(first_text(row.get("account_key"), "unknown_account"))
    artifact_dir = args.out_dir / "artifacts" / account_key / aid
    artifact_dir.mkdir(parents=True, exist_ok=True)
    image_dir = artifact_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    source_url = first_text(row.get("source_url"))
    title = first_text(row.get("title"), "Untitled")
    account = first_text(row.get("account_nickname"), row.get("account_key"), "unknown")
    publish_time = first_text(row.get("post_time"), row.get("post_date"))
    source_hash = first_text(row.get("source_url_hash"), f"sha256:{sha16(source_url)}")

    status_code = 0
    host = ""
    html_text = ""
    fetch_error = ""
    for attempt in range(1, args.retries + 2):
        try:
            with httpx.Client() as client:
                status_code, host, html_text = fetch_html(client, source_url, args.html_timeout_sec)
            break
        except Exception as exc:
            fetch_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            if attempt <= args.retries:
                time.sleep(args.retry_sleep_sec * attempt)
    if not html_text:
        meta_path = artifact_dir / "meta.json"
        write_json(
            meta_path,
            {
                "schema_version": SCHEMA_VERSION,
                "article_uid": uid,
                "article_id": aid,
                "source_account": account_key,
                "title": title,
                "fetch_status": "failed",
                "fetch_error": fetch_error,
                "source_url_hash": source_hash,
            },
        )
        return {
            "article_uid": uid,
            "article_id": aid,
            "source_account": account_key,
            "title": title,
            "status": "failed",
            "error": fetch_error,
            "meta_path": str(meta_path),
        }

    (artifact_dir / "source.html").write_text(html_text, encoding="utf-8", errors="replace")
    page_meta = extract_meta(html_text)
    body_text = extract_visible_text(html_text)
    image_urls = extract_image_urls(html_text, first_text(row.get("cover_url")))
    images_downloaded: list[Path] = []
    image_errors: list[dict[str, Any]] = []
    if args.download_images and image_urls:
        with httpx.Client() as client:
            for index, image_url in enumerate(image_urls[: args.max_images_per_article], start=1):
                image_path = image_dir / f"image_{index:03d}.jpg"
                try:
                    if fetch_image(client, image_url, image_path, args.image_timeout_sec):
                        candidates = sorted(image_dir.glob(f"image_{index:03d}.*"))
                        images_downloaded.append(candidates[0] if candidates else image_path)
                except Exception as exc:
                    image_errors.append(
                        {
                            "image_index": index,
                            "image_url_hash": "sha256:" + sha16(image_url),
                            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                        }
                    )

    ocr_items: list[dict[str, Any]] = []
    if args.run_ocr and images_downloaded:
        for image_path in images_downloaded:
            ocr_items.append(
                ocr_image(
                    image_path,
                    timeout_sec=args.ocr_timeout_sec,
                    lang=args.tesseract_lang,
                    min_width=args.min_ocr_width,
                    min_height=args.min_ocr_height,
                )
            )
    ocr_status_counts = Counter(str(item.get("ocr_status") or "unknown") for item in ocr_items)
    ocr_text_chars = sum(int(item.get("text_chars") or 0) for item in ocr_items)
    row_digest = first_text(
        row.get("digest"),
        row.get("summary_digest"),
        row.get("summary"),
        row.get("description"),
    )
    body_extraction_quality = "ok"
    if len(html_text) > 50000 and len(body_text) < 800:
        body_extraction_quality = "short_body_large_html"
    evidence_loss_risk = body_extraction_quality != "ok" and ocr_text_chars < 500 and not row_digest
    poster_ocr_path = artifact_dir / "poster_ocr.json"
    write_json(
        poster_ocr_path,
        {
            "schema_version": "atlas_incremental_poster_ocr.v1",
            "article_uid": uid,
            "article_id": aid,
            "ocr_engine": "tesseract",
            "ocr_lang": args.tesseract_lang,
            "ocr_executed": bool(args.run_ocr and images_downloaded),
            "ocr_status_counts": dict(sorted(ocr_status_counts.items())),
            "image_candidates": len(image_urls),
            "image_downloaded": len(images_downloaded),
            "image_download_errors": image_errors[:20],
            "images": ocr_items,
        },
    )

    llm_input = build_llm_input(
        title=title,
        account=account,
        publish_time=publish_time,
        body_text=body_text,
        ocr_items=ocr_items,
        image_count=len(images_downloaded) if args.download_images else len(image_urls),
        source_hash=source_hash,
        row_digest=row_digest,
        page_meta=page_meta,
    )
    llm_input_path = artifact_dir / "llm_input.md"
    llm_input_path.write_text(llm_input, encoding="utf-8")

    meta_path = artifact_dir / "meta.json"
    meta = {
        "schema_version": SCHEMA_VERSION,
        "article_uid": uid,
        "article_id": aid,
        "source_account": account_key,
        "account_name": account,
        "title": title,
        "publish_time_text": publish_time,
        "post_date": first_text(row.get("post_date")),
        "fetch_status": "ok",
        "http_status": status_code,
        "host": host,
        "source_url_hash": source_hash,
        "source_url_token": first_text(row.get("source_url_token")),
        "queue_id": first_text(row.get("queue_id")),
        "cover_url_hash": "sha256:" + sha16(first_text(row.get("cover_url"))) if row.get("cover_url") else "",
        "html_chars": len(html_text),
        "body_text_chars": len(body_text),
        "body_extraction_quality": body_extraction_quality,
        "evidence_loss_risk": evidence_loss_risk,
        "queue_digest_chars": len(row_digest),
        "image_candidates": len(image_urls),
        "local_image_count": len(images_downloaded) if args.download_images else len(image_urls),
        "image_downloaded": len(images_downloaded),
        "image_download_errors": len(image_errors),
        "poster_ocr_path": str(poster_ocr_path),
        "poster_ocr_status_counts": dict(sorted(ocr_status_counts.items())),
        "page_meta": {key: page_meta[key] for key in sorted(page_meta)[:30]},
    }
    write_json(meta_path, meta)

    return {
        "sample_id": "",
        "article_uid": uid,
        "source_account": account_key,
        "article_id": aid,
        "title": title,
        "input_chars": len(llm_input),
        "quality_grade": "host_html_ocr_ready" if body_text else "host_html_empty_text",
        "local_image_count": meta["local_image_count"],
        "bucket": "atlas_incremental_new_wechat",
        "llm_input_path": str(llm_input_path),
        "meta_path": str(meta_path),
        "status": "pending",
        "fetch_status": "ok",
        "body_text_chars": len(body_text),
        "body_extraction_quality": body_extraction_quality,
        "evidence_loss_risk": evidence_loss_risk,
        "queue_digest_chars": len(row_digest),
        "html_chars": len(html_text),
        "image_candidates": len(image_urls),
        "image_downloaded": len(images_downloaded),
        "ocr_text_chars": ocr_text_chars,
        "ocr_status_counts": dict(sorted(ocr_status_counts.items())),
    }


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Incremental Host HTML Artifact Summary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- manifest_rows: `{summary['manifest_rows']}`",
        f"- failed_rows: `{summary['failed_rows']}`",
        f"- body_text_ready_rows: `{summary['body_text_ready_rows']}`",
        f"- rows_with_images: `{summary['rows_with_images']}`",
        f"- images_downloaded: `{summary['images_downloaded']}`",
        f"- rows_with_ocr_text: `{summary['rows_with_ocr_text']}`",
        f"- ocr_text_chars: `{summary['ocr_text_chars']}`",
        f"- short_body_large_html_rows: `{summary.get('short_body_large_html_rows', 0)}`",
        f"- evidence_loss_risk_rows: `{summary.get('evidence_loss_risk_rows', 0)}`",
        f"- rows_with_queue_digest: `{summary.get('rows_with_queue_digest', 0)}`",
        f"- max_images_per_article: `{summary['max_images_per_article']}`",
        f"- tesseract_lang: `{summary['tesseract_lang']}`",
        "",
        "## Outputs",
        "",
    ]
    for key, value in summary["outputs"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- No Docker write, no production DB write, no Qdrant/Neo4j write.",
            "- LLM input omits raw source URLs and cookies.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(Path(args.new_url_jsonl))
    if args.limit:
        rows = rows[: args.limit]
    worker_args = WorkerArgs(
        out_dir=out_dir,
        html_timeout_sec=args.html_timeout_sec,
        image_timeout_sec=args.image_timeout_sec,
        ocr_timeout_sec=args.ocr_timeout_sec,
        download_images=args.download_images,
        run_ocr=args.ocr,
        max_images_per_article=args.max_images_per_article,
        tesseract_lang=args.tesseract_lang,
        min_ocr_width=args.min_ocr_width,
        min_ocr_height=args.min_ocr_height,
        retries=args.retries,
        retry_sleep_sec=args.retry_sleep_sec,
    )
    manifest_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        futures = {executor.submit(process_row, row, worker_args): row for row in rows}
        for done, future in enumerate(as_completed(futures), start=1):
            try:
                result = future.result()
            except Exception as exc:
                row = futures[future]
                result = {
                    "article_uid": article_uid(row),
                    "article_id": article_id(row),
                    "source_account": first_text(row.get("account_key")),
                    "title": first_text(row.get("title")),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }
            if result.get("status") == "pending":
                manifest_rows.append(result)
            else:
                error_rows.append(result)
            if args.progress_every and (done % args.progress_every == 0 or done == len(rows)):
                print(
                    json.dumps(
                        {
                            "done": done,
                            "total": len(rows),
                            "manifest_rows": len(manifest_rows),
                            "failed_rows": len(error_rows),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    manifest_rows.sort(key=lambda row: (str(row.get("source_account") or ""), str(row.get("article_id") or "")))
    error_rows.sort(key=lambda row: (str(row.get("source_account") or ""), str(row.get("article_id") or "")))
    manifest_path = out_dir / "stage7_manifest.jsonl"
    errors_path = out_dir / "host_fetch_errors.jsonl"
    write_jsonl(manifest_path, manifest_rows)
    write_jsonl(errors_path, error_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "input_path": str(args.new_url_jsonl),
        "input_rows": len(rows),
        "manifest_rows": len(manifest_rows),
        "failed_rows": len(error_rows),
        "body_text_ready_rows": sum(1 for row in manifest_rows if int(row.get("body_text_chars") or 0) > 0),
        "rows_with_images": sum(1 for row in manifest_rows if int(row.get("local_image_count") or 0) > 0),
        "rows_with_ocr_text": sum(1 for row in manifest_rows if int(row.get("ocr_text_chars") or 0) > 0),
        "images_downloaded": sum(int(row.get("image_downloaded") or 0) for row in manifest_rows),
        "ocr_text_chars": sum(int(row.get("ocr_text_chars") or 0) for row in manifest_rows),
        "short_body_large_html_rows": sum(
            1 for row in manifest_rows if str(row.get("body_extraction_quality") or "") == "short_body_large_html"
        ),
        "evidence_loss_risk_rows": sum(1 for row in manifest_rows if row.get("evidence_loss_risk")),
        "rows_with_queue_digest": sum(1 for row in manifest_rows if int(row.get("queue_digest_chars") or 0) > 0),
        "max_images_per_article": args.max_images_per_article,
        "download_images": bool(args.download_images),
        "ocr_executed": bool(args.ocr),
        "tesseract_lang": args.tesseract_lang,
        "tesseract_exe": tesseract_exe() if args.ocr else "",
        "outputs": {
            "manifest": str(manifest_path),
            "errors": str(errors_path),
            "summary_json": str(out_dir / "host_html_artifact_summary.json"),
            "summary_md": str(out_dir / "host_html_artifact_summary.md"),
        },
        "safety": {
            "raw_source_url_in_llm_input": False,
            "docker_write_executed": False,
            "sqlite_write_executed": False,
            "llm_call_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
        },
    }
    write_json(out_dir / "host_html_artifact_summary.json", summary)
    write_summary_md(out_dir / "host_html_artifact_summary.md", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-url-jsonl", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--html-timeout-sec", type=int, default=30)
    parser.add_argument("--image-timeout-sec", type=int, default=30)
    parser.add_argument("--ocr-timeout-sec", type=int, default=25)
    parser.add_argument("--download-images", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--max-images-per-article", type=int, default=8)
    parser.add_argument("--tesseract-lang", default="eng")
    parser.add_argument("--min-ocr-width", type=int, default=220)
    parser.add_argument("--min-ocr-height", type=int, default=180)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-sleep-sec", type=float, default=1.5)
    parser.add_argument("--progress-every", type=int, default=25)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_artifacts(args)
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_rows"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
