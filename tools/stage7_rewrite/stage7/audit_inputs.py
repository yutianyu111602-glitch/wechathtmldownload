"""Input audit: scan the article pack and report stats."""
from __future__ import annotations
import os
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any

from .paths import ensure_output_dirs
from .atomic_io import atomic_write_json, safe_read_text
from .logging_setup import setup_logging


@dataclass
class ArticleEntry:
    article_uid: str
    source_account: str
    article_id: str
    article_dir: str
    llm_input_path: str
    meta_path: str
    poster_ocr_path: str
    title: str
    publish_time: str
    url: str
    input_chars: int
    input_sha1: str
    status: str = "pending"
    empty_files: list[str] = None
    oversized: bool = False
    encoding_ok: bool = True

    def __post_init__(self):
        if self.empty_files is None:
            self.empty_files = []


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def audit_inputs(input_root: Path, output_root: Path) -> dict[str, Any]:
    logger = setup_logging(output_root / "logs", "audit")
    ensure_output_dirs(output_root)

    logger.info("Starting input audit: %s", input_root)

    if not input_root.exists():
        raise FileNotFoundError(f"Input root does not exist: {input_root}")

    article_dirs = sorted({p.parent for p in input_root.rglob("llm_input.md") if p.is_file()})
    logger.info("Found %d article directories with llm_input.md", len(article_dirs))

    total_llm_input = 0
    total_meta = 0
    total_poster_ocr = 0
    empty_files = 0
    oversized_files = 0
    encoding_errors = 0
    duplicate_uids: dict[str, list[str]] = {}
    account_counts: dict[str, int] = {}

    manifest_records: list[dict] = []
    sample_records: list[dict] = []

    for article_dir in article_dirs:
        rel_parts = article_dir.relative_to(input_root).parts
        article_id = rel_parts[-1] if rel_parts else article_dir.name
        account_name = "__".join(rel_parts[:-1]) if len(rel_parts) > 1 else input_root.name
        account_counts[account_name] = account_counts.get(account_name, 0) + 1
        llm_input_path = article_dir / "llm_input.md"
        meta_path = article_dir / "meta.json"
        poster_ocr_path = article_dir / "poster_ocr.json"

        entry_empty: list[str] = []

        # Check files
        for p, label in [(llm_input_path, "llm_input"), (meta_path, "meta"), (poster_ocr_path, "poster_ocr")]:
            if p.exists():
                size = p.stat().st_size
                if size == 0:
                    empty_files += 1
                    entry_empty.append(label)
                elif size > 10 * 1024 * 1024:  # 10MB
                    oversized_files += 1
            else:
                empty_files += 1
                entry_empty.append(label)

        if llm_input_path.exists():
            total_llm_input += 1
        if meta_path.exists():
            total_meta += 1
        if poster_ocr_path.exists():
            total_poster_ocr += 1

        # Read llm_input for stats
        text = ""
        chars = 0
        input_sha1 = ""
        record_encoding_ok = True
        try:
            text = safe_read_text(llm_input_path, "")
            chars = len(text)
            if text:
                input_sha1 = sha1_text(text)
        except UnicodeDecodeError:
            encoding_errors += 1
            record_encoding_ok = False

        # Read meta
        title = ""
        publish_time = ""
        url = ""
        try:
            meta = json.loads(safe_read_text(meta_path, "{}"))
            title = meta.get("title", "") or meta.get("ogTitle", "")
            publish_time = meta.get("publish_time_iso", "") or meta.get("publish_time_text", "") or meta.get("publishTime", "") or meta.get("date", "")
            url = meta.get("source_url", "") or meta.get("url", "") or meta.get("link", "")
        except Exception:
            pass

        uid = sha1_text(f"{account_name}:{article_id}:{str(article_dir)}")

        if uid in duplicate_uids:
            duplicate_uids[uid].append(str(article_dir))
        else:
            duplicate_uids[uid] = [str(article_dir)]

        record = ArticleEntry(
            article_uid=uid,
            source_account=account_name,
            article_id=article_id,
            article_dir=str(article_dir),
            llm_input_path=str(llm_input_path) if llm_input_path.exists() else "",
            meta_path=str(meta_path) if meta_path.exists() else "",
            poster_ocr_path=str(poster_ocr_path) if poster_ocr_path.exists() else "",
            title=title,
            publish_time=publish_time,
            url=url,
            input_chars=chars,
            input_sha1=input_sha1,
            empty_files=entry_empty,
            oversized=(chars > 500_000),
            encoding_ok=record_encoding_ok,
        )
        manifest_records.append(asdict(record))

        # Collect samples (first 10)
        if len(sample_records) < 10:
            sample_records.append(asdict(record))

    # Deduplicate report
    duplicate_count = sum(1 for v in duplicate_uids.values() if len(v) > 1)

    report = {
        "audit_timestamp": __import__("datetime").datetime.now().isoformat(),
        "input_root": str(input_root),
        "account_count": len(account_counts),
        "article_count": len(article_dirs),
        "llm_input_count": total_llm_input,
        "meta_count": total_meta,
        "poster_ocr_count": total_poster_ocr,
        "empty_file_count": empty_files,
        "oversized_count": oversized_files,
        "encoding_error_count": encoding_errors,
        "duplicate_uid_count": duplicate_count,
        "account_distribution": account_counts,
        "samples": sample_records,
    }

    # Write outputs
    manifest_path = output_root / "manifests" / "article_manifest.v1.jsonl"
    with open(manifest_path, "w", encoding="utf-8") as f:
        for r in manifest_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    atomic_write_json(output_root / "manifests" / "input_audit_report.json", report)

    # Markdown report
    md_lines = [
        "# Input Audit Report",
        f"\n**Timestamp:** {report['audit_timestamp']}",
        f"**Input Root:** `{input_root}`",
        "",
        "## Summary",
        f"- Accounts: {report['account_count']}",
        f"- Articles: {report['article_count']}",
        f"- llm_input.md: {report['llm_input_count']}",
        f"- meta.json: {report['meta_count']}",
        f"- poster_ocr.json: {report['poster_ocr_count']}",
        f"- Empty files: {report['empty_file_count']}",
        f"- Oversized: {report['oversized_count']}",
        f"- Encoding errors: {report['encoding_error_count']}",
        f"- Duplicate UIDs: {report['duplicate_uid_count']}",
        "",
        "## Account Distribution",
    ]
    for acc, cnt in sorted(account_counts.items(), key=lambda x: -x[1]):
        md_lines.append(f"- {acc}: {cnt}")

    md_lines += ["", "## Sample Articles (first 10)", ""]
    for s in sample_records:
        md_lines.append(f"- `{s['article_uid'][:16]}...` | {s['source_account']} | {s['article_id']} | chars={s['input_chars']} | title={s['title'][:60]}")

    md_path = output_root / "manifests" / "input_audit_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    logger.info("Audit complete. Manifest: %s, Report: %s", manifest_path, md_path)
    return report
