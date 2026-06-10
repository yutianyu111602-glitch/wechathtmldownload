#!/usr/bin/env python3
"""Localize PRD-05a HTTP image candidates into a report-only evidence pack.

This script downloads bounded image candidates found by the PRD-05a HTTP fast
layer, records bytes/hash/dimensions, and writes only under reports. It does
not update the official OCR index, run OCR, mutate source archives, call paid
APIs, write graph/vector/DB state, scan D:, or publish.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, request


DEFAULT_EVIDENCE = Path("reports/prd05a_external_evidence_fast_20260516/external_evidence_fast.jsonl")
DEFAULT_OUT_DIR = Path("reports/prd05a_image_candidate_localization_20260516")
SCHEMA_VERSION = "stage7_prd05a_image_candidate_localization.v1"
MIN_OCR_DIMENSION = 480
EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
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


def iter_candidates(evidence_rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in evidence_rows:
        for idx, candidate in enumerate(row.get("asset_candidates") or []):
            if not isinstance(candidate, dict):
                continue
            url = first_text(candidate.get("url"))
            if not url or url in seen:
                continue
            seen.add(url)
            candidates.append(
                {
                    "source_prd": "PRD-05a",
                    "source_article_id": first_text(row.get("source_article_id")),
                    "source_account": first_text(row.get("source_account")),
                    "input_url": first_text(row.get("input_url")),
                    "image_url": url,
                    "image_domain": first_text(candidate.get("domain")),
                    "source_field": first_text(candidate.get("source_field")),
                    "candidate_index": idx,
                    "unsafe_action": False,
                }
            )
            if limit > 0 and len(candidates) >= limit:
                return candidates
    return candidates


def fetch_binary(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Stage7 PRD-05a image candidate localizer",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.8",
            "Referer": "https://mp.weixin.qq.com/",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            data = resp.read(max_bytes + 1)
            truncated = len(data) > max_bytes
            data = data[:max_bytes]
            return {
                "ok": True,
                "status_code": int(getattr(resp, "status", 0) or 0),
                "final_url": resp.geturl(),
                "content_type": first_text(resp.headers.get("content-type")).split(";")[0].casefold(),
                "data": data,
                "truncated": truncated,
                "error": "",
            }
    except error.HTTPError as exc:
        return {
            "ok": False,
            "status_code": exc.code,
            "final_url": exc.geturl(),
            "content_type": first_text(exc.headers.get("content-type")).split(";")[0].casefold(),
            "data": b"",
            "truncated": False,
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 - report-only evidence needs exact failure text.
        return {
            "ok": False,
            "status_code": 0,
            "final_url": url,
            "content_type": "",
            "data": b"",
            "truncated": False,
            "error": str(exc),
        }


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


def gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 10 and data[:6] in {b"GIF87a", b"GIF89a"}:
        return struct.unpack("<HH", data[6:10])
    return None


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    idx = 2
    while idx + 9 < len(data):
        if data[idx] != 0xFF:
            idx += 1
            continue
        marker = data[idx + 1]
        idx += 2
        if marker in {0xD8, 0xD9}:
            continue
        if idx + 2 > len(data):
            return None
        length = struct.unpack(">H", data[idx : idx + 2])[0]
        if length < 2 or idx + length > len(data):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if idx + 7 > len(data):
                return None
            height, width = struct.unpack(">HH", data[idx + 3 : idx + 7])
            return width, height
        idx += length
    return None


def detect_image(data: bytes) -> tuple[str, int, int]:
    for fmt, reader in (("png", png_dimensions), ("gif", gif_dimensions), ("jpeg", jpeg_dimensions)):
        dims = reader(data)
        if dims:
            return fmt, dims[0], dims[1]
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp", 0, 0
    return "unknown", 0, 0


def safe_file_stem(candidate: dict[str, Any]) -> str:
    raw = "|".join(
        [
            first_text(candidate.get("source_article_id")),
            first_text(candidate.get("image_url")),
            str(candidate.get("candidate_index", "")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def extension_for(content_type: str, image_format: str, url: str) -> str:
    if content_type in EXT_BY_CONTENT_TYPE:
        return EXT_BY_CONTENT_TYPE[content_type]
    if image_format == "jpeg":
        return ".jpg"
    if image_format in {"png", "gif", "webp"}:
        return "." + image_format
    suffix = Path(url.split("?", 1)[0]).suffix.casefold()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"} else ".bin"


def passes_ocr_size_gate(width: int, height: int) -> bool:
    return width >= MIN_OCR_DIMENSION and height >= MIN_OCR_DIMENSION


def localize_candidate(
    candidate: dict[str, Any],
    out_dir: Path,
    fetcher: Callable[[str, float, int], dict[str, Any]],
    timeout_sec: float,
    max_bytes: int,
) -> dict[str, Any]:
    fetched = fetcher(first_text(candidate.get("image_url")), timeout_sec, max_bytes)
    data = fetched.get("data") if isinstance(fetched.get("data"), bytes) else b""
    image_format, width, height = detect_image(data)
    sha256 = hashlib.sha256(data).hexdigest() if data else ""
    content_type = first_text(fetched.get("content_type"))
    ext = extension_for(content_type, image_format, first_text(candidate.get("image_url")))
    local_path = ""
    status = "download_failed"
    if data and image_format != "unknown":
        images_dir = out_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        local = images_dir / f"{safe_file_stem(candidate)}{ext}"
        with tempfile.NamedTemporaryFile("wb", dir=images_dir, delete=False) as handle:
            handle.write(data)
            tmp = Path(handle.name)
        tmp.replace(local)
        local_path = str(local)
        status = "downloaded_image"
    elif data:
        status = "downloaded_non_image"

    ocr_size_gate = passes_ocr_size_gate(width, height)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        **candidate,
        "download_status": status,
        "status_code": int(fetched.get("status_code") or 0),
        "final_url": first_text(fetched.get("final_url") or candidate.get("image_url")),
        "content_type": content_type,
        "bytes": len(data),
        "truncated": bool(fetched.get("truncated")),
        "sha256": sha256,
        "image_format": image_format,
        "width": width,
        "height": height,
        "ocr_size_gate": ocr_size_gate,
        "ocr_min_dimension": MIN_OCR_DIMENSION,
        "local_path": local_path,
        "error": first_text(fetched.get("error")),
        "ocr_ready_candidate": status == "downloaded_image" and ocr_size_gate,
        "official_ocr_index_updated": False,
        "unsafe_action": False,
        "write_scope": "reports_only",
    }


def build_localization_report(
    evidence_path: Path,
    out_dir: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Callable[[str, float, int], dict[str, Any]] = fetch_binary,
) -> dict[str, Any]:
    reject_broad_d_path(out_dir, "out_dir")
    rows = read_jsonl(evidence_path)
    candidates = iter_candidates(rows, limit)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "image_candidate_queue.jsonl", candidates)
    localized = [localize_candidate(row, out_dir, fetcher, timeout_sec, max_bytes) for row in candidates]
    write_jsonl(out_dir / "image_candidate_localization.jsonl", localized)

    status_counts = Counter(first_text(row.get("download_status")) for row in localized)
    localized_images = status_counts.get("downloaded_image", 0)
    ready_rows = sum(1 for row in localized if row.get("ocr_ready_candidate"))
    if ready_rows:
        decision = "image_candidate_localized_report_ready"
    elif localized_images:
        decision = "image_localized_but_below_ocr_size_gate"
    else:
        decision = "no_downloadable_image_candidates"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_prd": "PRD-05a",
        "decision": decision,
        "ok": True,
        "input_evidence_path": str(evidence_path),
        "out_dir": str(out_dir),
        "candidate_queue_path": str(out_dir / "image_candidate_queue.jsonl"),
        "localization_path": str(out_dir / "image_candidate_localization.jsonl"),
        "candidate_rows": len(candidates),
        "localized_rows": len(localized),
        "localized_image_rows": localized_images,
        "ocr_ready_candidate_rows": ready_rows,
        "ocr_min_dimension": MIN_OCR_DIMENSION,
        "download_status_counts": dict(status_counts),
        "official_ocr_index_updated": False,
        "next_gate": "PRD-05a review must accept the source-backed image contract before OCR index rebuild",
        "safety": [
            "reports_only",
            "bounded_image_candidates_only",
            "no_official_ocr_index_update",
            "no_ocr_execution",
            "no_paid_api",
            "no_opencli_browser_state",
            "no_graph_vector_db_write",
            "no_source_archive_mutation",
            "no_d_scan",
            "no_publish",
        ],
    }
    write_json(out_dir / "image_candidate_localization_summary.json", summary)
    write_markdown(out_dir / "image_candidate_localization_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-05a Image Candidate Localization",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- candidate_rows: `{summary['candidate_rows']}`",
        f"- localized_rows: `{summary['localized_rows']}`",
        f"- localized_image_rows: `{summary['localized_image_rows']}`",
        f"- ocr_ready_candidate_rows: `{summary['ocr_ready_candidate_rows']}`",
        f"- ocr_min_dimension: `{summary['ocr_min_dimension']}`",
        f"- official_ocr_index_updated: `{summary['official_ocr_index_updated']}`",
        f"- candidate_queue_path: `{summary['candidate_queue_path']}`",
        f"- localization_path: `{summary['localization_path']}`",
        "",
        "## Download Status",
        "",
    ]
    for key, value in sorted(summary["download_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Next Gate", "", f"- {summary['next_gate']}", "", "## Safety", ""])
    for item in summary["safety"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--max-bytes", type=int, default=10_000_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_localization_report(
        evidence_path=args.evidence,
        out_dir=args.out_dir,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
