#!/usr/bin/env python3
"""Repair V6 P1 OCR-empty rows with local image evidence.

This runner consumes the bounded locator queue produced by
build_v6_p1_existing_ocr_locator.py. It does not scan D: broadly, download
images, call paid APIs, or touch graph/vector stores.

Default mode is dry-run. Real writes require:
  --execute --confirm-token ENABLE_STAGE7_V6_P1_LOCAL_OCR_REPAIR

For real OCR, run this under WSL Python 3.12 where cnocr/easyocr are installed.
Windows Python 3.13 may still run dry-runs and unit tests.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


DEFAULT_INPUT = Path("reports/v6_p1_existing_ocr_locator_20260518/v6_p1_existing_ocr_rerun_needed.jsonl")
DEFAULT_OUT_DIR = Path("reports/v6_p1_local_ocr_repair_20260518")
CONFIRM_TOKEN = "ENABLE_STAGE7_V6_P1_LOCAL_OCR_REPAIR"
SCHEMA_VERSION = "stage7_v6_p1_local_ocr_repair.v1"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
ANIMATED_SUFFIXES = {".gif", ".webp"}
BACKUP_SUFFIX = ".before_v6p1_local_ocr_20260518.json"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                row["_source_line"] = line_no
                yield row


def path_from_any(value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        return Path()
    text = text.replace("/", "\\") if re.match(r"^[A-Za-z]:/", text) else text
    match = re.match(r"^([A-Za-z]):\\(.*)$", text)
    if os.name != "nt" and match:
        drive = match.group(1).lower()
        rest = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")
    if text.startswith("/mnt/") and os.name == "nt" and len(text) > 6 and text[6] == "/":
        drive = text[5].upper()
        rest = text[7:].replace("/", "\\")
        return Path(f"{drive}:\\{rest}")
    return Path(text)


def display_path(path: Path) -> str:
    text = str(path)
    match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", text)
    if os.name != "nt" and match:
        rest = match.group(2).replace("/", "\\")
        return f"{match.group(1).upper()}:\\{rest}"
    return text


def text_from_ocr(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("plain_text"), str) and payload["plain_text"].strip():
        return payload["plain_text"].strip()
    parts = []
    for block in payload.get("blocks") or []:
        if isinstance(block, dict) and str(block.get("text") or "").strip():
            parts.append(str(block["text"]).strip())
    return "\n".join(parts)


def existing_ocr_has_text(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = read_json(path)
    except Exception:
        return False
    return bool(isinstance(payload, dict) and text_from_ocr(payload))


def meaningful_char_count(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-z\u4e00-\u9fff]", text or ""))


def normalize_line(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def dedupe_lines(lines: list[str]) -> list[str]:
    seen = set()
    out = []
    for line in lines:
        key = normalize_line(line)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line.strip())
    return out


def recovered_from_text(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    date_texts = [
        line
        for line in lines
        if re.search(r"\d{4}[-./年]\d{1,2}|\d{1,2}[-./月]\d{1,2}|\b\d{1,2}:\d{2}\b", line)
    ]
    lineup = [line for line in lines if re.search(r"\b(DJ|LIVE|B2B|LINEUP|VJ|ACT)\b|演出|阵容", line, re.I)]
    venue = ""
    for line in lines:
        if re.search(r"club|venue|room|space|live|house|bar|俱乐部|场地|现场|厂牌|舞台", line, re.I):
            venue = line
            break
    return {"venue_name_candidate": venue, "date_texts": date_texts[:8], "lineup_lines": lineup[:16]}


def image_files(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    return sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES)


def row_image_candidates(row: dict[str, Any], max_images: int) -> list[Path]:
    candidates: list[Path] = []
    first = path_from_any(row.get("poster_ocr_image_path"))
    if first and first.exists() and first.is_file():
        candidates.append(first)
    image_dir = path_from_any(row.get("poster_ocr_image_dir"))
    candidates.extend(image_files(image_dir))
    unique: list[Path] = []
    seen = set()
    for path in candidates:
        key = str(path.resolve() if path.exists() else path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
        if max_images and len(unique) >= max_images:
            break
    return unique


def frame_indices(frame_count: int, max_frames: int) -> list[int]:
    if frame_count <= 0:
        return []
    candidates = [0, frame_count // 2, frame_count - 1]
    out: list[int] = []
    for idx in candidates:
        if idx not in out:
            out.append(idx)
        if len(out) >= max_frames:
            break
    return out


def extract_static_frames(image_path: Path, article_dir: Path, max_frames: int) -> tuple[list[Path], list[str]]:
    warnings: list[str] = []
    if image_path.suffix.lower() not in ANIMATED_SUFFIXES:
        return [image_path], warnings
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - depends on host packages
        return [], [f"PIL unavailable for static frame extraction: {type(exc).__name__}: {exc}"]

    out_dir = article_dir / ".poster_ocr_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    try:
        with Image.open(image_path) as im:
            count = int(getattr(im, "n_frames", 1) or 1)
            for idx in frame_indices(count, max_frames):
                im.seek(idx)
                frame = im.convert("RGB")
                out_path = out_dir / f"{image_path.stem}_frame{idx:04d}.png"
                frame.save(out_path)
                out_paths.append(out_path)
    except Exception as exc:
        warnings.append(f"static frame extraction failed for {display_path(image_path)}: {type(exc).__name__}: {exc}")
    return out_paths, warnings


def modes_for_row(row: dict[str, Any]) -> list[str]:
    mode = str(row.get("recommended_ocr_mode") or "mix").strip().lower()
    if mode == "en":
        return ["en"]
    if mode == "cn":
        return ["cn"]
    return ["mix", "en"]


def load_ocr_func() -> Callable[[str, str | None], dict[str, Any]]:
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from ocr_gpu import ocr_image  # type: ignore

    return ocr_image


def run_ocr_on_image(
    ocr_func: Callable[[str, str | None], dict[str, Any]],
    image_path: Path,
    mode: str,
) -> dict[str, Any]:
    lang = {"cn": "ch_sim", "en": "en", "mix": "mix"}.get(mode, "mix")
    payload = ocr_func(str(image_path), lang)
    return payload if isinstance(payload, dict) else {"backend": "invalid", "plain_text": "", "blocks": [], "warnings": []}


def build_poster_payload(
    *,
    row: dict[str, Any],
    article_dir: Path,
    ocr_runs: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    lines: list[str] = []
    backend_parts: list[str] = []
    for run in ocr_runs:
        backend = str(run.get("backend") or "unknown")
        backend_parts.append(f"{run.get('mode')}:{backend}")
        run_text = text_from_ocr(run)
        lines.extend([line.strip() for line in run_text.splitlines() if line.strip()])
        for block in run.get("blocks") or []:
            if not isinstance(block, dict) or not str(block.get("text") or "").strip():
                continue
            enriched = dict(block)
            enriched["engine_mode"] = run.get("mode")
            enriched["engine_backend"] = backend
            enriched["image_path"] = run.get("image_path")
            blocks.append(enriched)

    plain_text = "\n".join(dedupe_lines(lines)).strip()
    primary_candidate = candidates[0] if candidates else {}
    primary_image_path = primary_candidate.get("source_image_path") or primary_candidate.get("ocr_image_path") or ""
    return {
        "schema_version": f"{SCHEMA_VERSION}.poster_ocr",
        "backend": "stage7-local-v6p1-" + "+".join(dedupe_lines(backend_parts)),
        "image_path": primary_image_path,
        "plain_text": plain_text,
        "blocks": blocks,
        "imageHeavy": len(plain_text) < 100,
        "candidates": candidates,
        "recovered": recovered_from_text(plain_text),
        "warnings": warnings,
        "quality": {
            "meaningful_chars": meaningful_char_count(plain_text),
            "accepted": meaningful_char_count(plain_text) >= 12,
            "ocr_run_count": len(ocr_runs),
            "recommended_ocr_mode": row.get("recommended_ocr_mode") or "mix",
        },
        "source": {
            "article_uid": row.get("article_uid"),
            "article_id": row.get("article_id"),
            "source_account": row.get("source_account"),
            "title": row.get("title"),
            "article_dir": display_path(article_dir),
            "locator_source_line": row.get("source_line") or row.get("_source_line"),
        },
    }


def process_row(
    row: dict[str, Any],
    *,
    execute: bool,
    ocr_func: Callable[[str, str | None], dict[str, Any]] | None,
    max_images: int,
    max_frames: int,
    timeout_note: str = "",
) -> dict[str, Any]:
    article_dir = path_from_any(row.get("article_dir"))
    poster_ocr_path = path_from_any(row.get("poster_ocr_path")) or (article_dir / "poster_ocr.json")
    images = row_image_candidates(row, max_images=max_images)
    result: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "article_uid": row.get("article_uid"),
        "article_id": row.get("article_id"),
        "source_account": row.get("source_account"),
        "title": row.get("title"),
        "article_dir": display_path(article_dir),
        "poster_ocr_path": display_path(poster_ocr_path),
        "recommended_ocr_mode": row.get("recommended_ocr_mode") or "mix",
        "static_frame_required": bool(row.get("static_frame_required")),
        "candidate_image_count": len(images),
        "candidate_images": [display_path(path) for path in images],
        "executed": execute,
        "ok": False,
        "plain_text_chars": 0,
        "meaningful_chars": 0,
        "frames_extracted": 0,
        "ocr_run_count": 0,
        "warnings": [],
        "write_executed": False,
        "backup_path": "",
    }
    if timeout_note:
        result["warnings"].append(timeout_note)
    if not article_dir.exists() or not images:
        result["warnings"].append("article_dir_or_images_missing")
        return result
    if not execute:
        return result
    if ocr_func is None:
        raise ValueError("ocr_func is required when execute=True")

    candidates: list[dict[str, Any]] = []
    ocr_runs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for image_path in images:
        ocr_paths, frame_warnings = extract_static_frames(image_path, article_dir, max_frames)
        warnings.extend(frame_warnings)
        if image_path.suffix.lower() in ANIMATED_SUFFIXES:
            result["frames_extracted"] += len(ocr_paths)
        for ocr_path in ocr_paths:
            candidates.append(
                {
                    "source_image_path": display_path(image_path),
                    "ocr_image_path": display_path(ocr_path),
                    "is_extracted_frame": image_path != ocr_path,
                    "source_suffix": image_path.suffix.lower(),
                }
            )
            for mode in modes_for_row(row):
                t0 = time.perf_counter()
                try:
                    run = run_ocr_on_image(ocr_func, ocr_path, mode)
                    run["duration_sec"] = round(time.perf_counter() - t0, 3)
                    run["mode"] = mode
                    run["image_path"] = display_path(ocr_path)
                    ocr_runs.append(run)
                except Exception as exc:  # pragma: no cover - real OCR host dependent
                    warnings.append(f"OCR failed mode={mode} image={display_path(ocr_path)}: {type(exc).__name__}: {exc}")

    poster_payload = build_poster_payload(row=row, article_dir=article_dir, ocr_runs=ocr_runs, candidates=candidates, warnings=warnings)
    text = poster_payload["plain_text"]
    result["plain_text_chars"] = len(text)
    result["meaningful_chars"] = meaningful_char_count(text)
    result["ocr_run_count"] = len(ocr_runs)
    result["warnings"].extend(warnings)
    result["ok"] = bool(poster_payload["quality"]["accepted"])

    if poster_ocr_path.exists():
        backup_path = poster_ocr_path.with_name(poster_ocr_path.stem + BACKUP_SUFFIX)
        if not backup_path.exists():
            shutil.copy2(poster_ocr_path, backup_path)
        result["backup_path"] = display_path(backup_path)
    write_json(poster_ocr_path, poster_payload)
    result["write_executed"] = True
    return result


def build_summary(args: argparse.Namespace, rows: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "input_rows_seen": len(rows),
        "selected_rows": len(results),
        "executed_rows": sum(1 for row in results if row.get("executed")),
        "ok_text_rows": sum(1 for row in results if row.get("ok")),
        "no_text_rows": sum(1 for row in results if row.get("executed") and not row.get("ok")),
        "write_rows": sum(1 for row in results if row.get("write_executed")),
        "frames_extracted": sum(int(row.get("frames_extracted") or 0) for row in results),
        "static_frame_required_rows": sum(1 for row in results if row.get("static_frame_required")),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "v6_p1_local_ocr_repair_executed" if args.execute else "v6_p1_local_ocr_repair_dry_run_ready",
        "input_path": str(args.input),
        "out_dir": str(args.out_dir),
        "mode": "execute" if args.execute else "dry-run",
        "limit": args.limit,
        "max_images": args.max_images,
        "max_frames": args.max_frames,
        "counts": counts,
        "mode_counts": dict(Counter(str(row.get("recommended_ocr_mode") or "mix") for row in results)),
        "top_accounts": dict(Counter(str(row.get("source_account") or "") for row in results).most_common(20)),
        "safety": {
            "bounded_locator_manifest_only": True,
            "d_broad_scan_executed": False,
            "paid_api_used": False,
            "deepseek_api_used": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "poster_ocr_write_executed": bool(args.execute),
            "confirm_token_required_for_write": True,
            "existing_poster_ocr_backup_created": bool(args.execute),
        },
    }


def live_state(results: list[dict[str, Any]], selected_seen: int) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.live_state",
        "updated_at": now_iso(),
        "selected_seen": selected_seen,
        "processed_rows": len(results),
        "ok_text_rows": sum(1 for row in results if row.get("ok")),
        "no_text_rows": sum(1 for row in results if row.get("executed") and not row.get("ok")),
        "write_rows": sum(1 for row in results if row.get("write_executed")),
        "frames_extracted": sum(int(row.get("frames_extracted") or 0) for row in results),
        "last_article_uid": results[-1].get("article_uid") if results else "",
        "last_ok": results[-1].get("ok") if results else None,
    }


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    lines = [
        "# V6 P1 Local OCR Repair",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- mode: `{summary['mode']}`",
        f"- selected_rows: `{counts['selected_rows']}`",
        f"- executed_rows: `{counts['executed_rows']}`",
        f"- ok_text_rows: `{counts['ok_text_rows']}`",
        f"- no_text_rows: `{counts['no_text_rows']}`",
        f"- frames_extracted: `{counts['frames_extracted']}`",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-images", type=int, default=3)
    parser.add_argument("--max-frames", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--include-existing-text", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.execute and args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--execute requires --confirm-token {CONFIRM_TOKEN}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    source_rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    ocr_func = load_ocr_func() if args.execute else None
    live_rows_path = args.out_dir / "local_ocr_repair_rows.live.jsonl"
    live_state_path = args.out_dir / "local_ocr_repair_state.json"
    if args.execute and live_rows_path.exists():
        live_rows_path.unlink()

    for row in iter_jsonl(args.input):
        poster_path = path_from_any(row.get("poster_ocr_path"))
        if not args.include_existing_text and existing_ocr_has_text(poster_path):
            continue
        if args.limit and len(results) >= args.limit:
            break
        source_rows.append(row)
        result = process_row(
            row,
            execute=bool(args.execute),
            ocr_func=ocr_func,
            max_images=args.max_images,
            max_frames=args.max_frames,
        )
        results.append(result)
        if args.execute:
            append_jsonl(live_rows_path, result)
            write_json(live_state_path, live_state(results, len(source_rows)))
            print(
                f"[{len(results)}] ok={result['ok']} chars={result['plain_text_chars']} "
                f"frames={result['frames_extracted']} account={result.get('source_account')} title={str(result.get('title') or '')[:40]}",
                flush=True,
            )

    summary = build_summary(args, source_rows, results)
    write_json(args.out_dir / "local_ocr_repair_summary.json", summary)
    write_jsonl(args.out_dir / "local_ocr_repair_rows.jsonl", results)
    write_markdown(args.out_dir / "local_ocr_repair_summary.md", summary)
    print(json.dumps({"ok": summary["ok"], "decision": summary["decision"], "counts": summary["counts"], "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
