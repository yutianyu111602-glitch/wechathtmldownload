#!/usr/bin/env python3
"""Stage7 strict manifest classifier, preflight, and repair utility.

This is a no-model control-plane tool. It never calls LLM endpoints.
It is designed for C1000 authority candidate repair after deterministic
pre-LLM classification finds non-normal rows in a strict normal batch.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
import re
import statistics
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REQUIRED_FIELDS = ["article_uid", "source_account", "article_id", "article_dir", "llm_input_path", "meta_path"]
RULES_VERSION = "stage7_strict_manifest_control_20260501_v1"
NORMAL_CLASS = "normal_extractable"
TERMINAL_CLASSIFICATIONS = {
    "empty_input_shell",
    "media_url_inventory",
    "low_signal_text",
    "poster_only",
    "ultra_long",
    "blocked_missing_path",
    "blocked_schema_bad",
}


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def to_wsl_path(value: Any) -> Optional[Path]:
    if value is None:
        return None
    s = str(value)
    if s.startswith("/mnt/"):
        return Path(s)
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", s)
    if m:
        return Path("/mnt") / m.group(1).lower() / m.group(2).replace("\\", "/")
    return Path(s)


def md_path(path: Path) -> str:
    return str(path).replace("/mnt/d/", "D:\\").replace("/", "\\")


def read_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    total = 0
    if not path.exists():
        return rows, [{"line": 0, "error": "missing_file", "path": str(path)}], total
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            total += 1
            stripped = line.strip()
            if not stripped:
                errors.append({"line": line_no, "error": "empty_line"})
                continue
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    obj["_jsonl_line"] = line_no
                    rows.append(obj)
                else:
                    errors.append({"line": line_no, "error": "non_object_json", "type": type(obj).__name__})
            except Exception as exc:  # noqa: BLE001 - evidence capture
                errors.append({"line": line_no, "error": type(exc).__name__, "message": str(exc)[:500], "raw_preview": stripped[:300]})
    return rows, errors, total


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            out = {k: v for k, v in row.items() if k != "_jsonl_line"}
            f.write(json.dumps(out, ensure_ascii=False, sort_keys=False) + "\n")
            count += 1
    os.replace(tmp, path)
    return count


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_text_limited(path: Path, max_bytes: int = 5 * 1024 * 1024) -> str:
    if path.stat().st_size <= max_bytes:
        return path.read_text(encoding="utf-8", errors="replace")
    with path.open("rb") as f:
        return f.read(max_bytes).decode("utf-8", errors="replace")


def section_text(text: str, header: str) -> Optional[str]:
    # Match markdown level-2 sections such as "## Main Content".
    pattern = re.compile(r"(?im)^##\s+" + re.escape(header).replace(r"\ ", r"\s+") + r"\s*$")
    match = pattern.search(text)
    if not match:
        return None
    start = match.end()
    next_match = re.search(r"(?m)^##\s+", text[start:])
    end = start + next_match.start() if next_match else len(text)
    return text[start:end].strip()


def url_count(text: str) -> int:
    return len(re.findall(r"https?://|www\.|mmbiz\.qpic\.cn|mp\.weixin\.qq\.com", text, flags=re.I))


def entity_signal_score(text: str) -> int:
    no_urls = re.sub(r"https?://\S+|www\.\S+|mmbiz\.qpic\.cn\S*|mp\.weixin\.qq\.com\S*", " ", text, flags=re.I)
    no_md = re.sub(r"(?im)^#.*$|归档时间\s*:\s*\S+|Main Content|Poster OCR|Untitled|archive|source|url", " ", no_urls)
    cjk = re.findall(r"[\u4e00-\u9fff]", no_md)
    words = [w for w in re.findall(r"[A-Za-z0-9]{2,}", no_md) if w.lower() not in {"http", "https", "jpg", "png", "jpeg", "gif", "webp", "com", "cn", "www"}]
    return len(cjk) + sum(len(w) for w in words)


def meta_json_ok(path: Path) -> Tuple[Optional[bool], Optional[str]]:
    try:
        json.loads(read_text_limited(path, 1024 * 1024))
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:300]}"


def classify_row(row: Dict[str, Any]) -> Dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if not row.get(field)]
    article_dir = to_wsl_path(row.get("article_dir"))
    llm_path = to_wsl_path(row.get("llm_input_path"))
    meta_path = to_wsl_path(row.get("meta_path"))
    poster_path = to_wsl_path(row.get("poster_ocr_path")) if row.get("poster_ocr_path") else (article_dir / "poster_ocr.json" if article_dir else None)

    article_dir_exists = bool(article_dir and article_dir.exists() and article_dir.is_dir())
    llm_input_exists = bool(llm_path and llm_path.exists() and llm_path.is_file())
    meta_exists = bool(meta_path and meta_path.exists() and meta_path.is_file())
    poster_ocr_exists = bool(poster_path and poster_path.exists() and poster_path.is_file())

    actual_input_chars = None
    estimated_chunks = None
    main_empty = None
    poster_section_empty = None
    ucount = None
    signal = None
    meta_ok = None
    meta_error = None
    reason = "normal_lane_rules_pass"
    classification = NORMAL_CLASS
    terminal_state = "enter_c1000_normal"
    llm_allowed = True

    if missing:
        classification = "blocked_schema_bad"
        terminal_state = "blocked"
        llm_allowed = False
        reason = "manifest_required_fields_missing"
    elif not article_dir_exists:
        classification = "blocked_missing_path"
        terminal_state = "blocked"
        llm_allowed = False
        reason = "article_dir_missing"
    elif not llm_input_exists:
        classification = "blocked_missing_path"
        terminal_state = "blocked"
        llm_allowed = False
        reason = "llm_input_missing"
    elif not meta_exists:
        classification = "blocked_missing_path"
        terminal_state = "blocked"
        llm_allowed = False
        reason = "meta_missing"
    else:
        try:
            text = read_text_limited(llm_path)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            text = ""
            classification = "blocked_missing_path"
            terminal_state = "blocked"
            llm_allowed = False
            reason = f"llm_input_read_error:{type(exc).__name__}"
        else:
            meta_ok, meta_error = meta_json_ok(meta_path)  # type: ignore[arg-type]
            actual_input_chars = len(text)
            estimated_chunks = int(math.ceil(max(actual_input_chars, 1) / 1000.0))
            main = section_text(text, "Main Content")
            poster = section_text(text, "Poster OCR")
            main_stripped = (main or "").strip()
            poster_stripped = (poster or "").strip()
            main_empty = main is not None and len(main_stripped) == 0
            poster_section_empty = poster is not None and len(poster_stripped) == 0
            ucount = url_count(text)
            signal = entity_signal_score(text)
            if not meta_ok:
                classification = "blocked_schema_bad"
                terminal_state = "blocked"
                llm_allowed = False
                reason = "meta_json_parse_error"
            elif actual_input_chars <= 120 and ("Untitled" in text or main_empty):
                classification = "empty_input_shell"
                terminal_state = "skipped_empty_shell"
                llm_allowed = False
                reason = "tiny_untitled_or_empty_main_content"
            elif main_empty and (poster_ocr_exists or len(poster_stripped) > 0):
                classification = "poster_only"
                terminal_state = "review_or_skipped_low_signal"
                llm_allowed = False
                reason = "main_content_empty_with_poster_ocr"
            elif actual_input_chars < 500 and ucount >= 3 and signal == 0:
                classification = "media_url_inventory"
                terminal_state = "skipped_media_inventory"
                llm_allowed = False
                reason = "short_url_inventory_without_entity_signal"
            elif actual_input_chars >= 20000 or estimated_chunks >= 20:
                classification = "ultra_long"
                terminal_state = "ultra_lane"
                llm_allowed = False
                reason = "input_chars_or_chunks_exceed_normal_lane"
            elif actual_input_chars < 500 and signal == 0:
                classification = "low_signal_text"
                terminal_state = "review_or_skipped_low_signal"
                llm_allowed = False
                reason = "short_low_signal_text"

    return {
        "line": row.get("_jsonl_line"),
        "article_uid": row.get("article_uid"),
        "source_account": row.get("source_account"),
        "article_id": row.get("article_id"),
        "title": row.get("title"),
        "classification": classification,
        "terminal_state": terminal_state,
        "llm_allowed": llm_allowed,
        "reason": reason,
        "manifest_input_chars": row.get("input_chars"),
        "actual_input_chars": actual_input_chars,
        "estimated_chunks_1000_chars": estimated_chunks,
        "length_bucket": row.get("length_bucket"),
        "url_count": ucount,
        "entity_signal_score": signal,
        "main_content_empty": main_empty,
        "poster_section_empty": poster_section_empty,
        "poster_ocr_exists": poster_ocr_exists,
        "article_dir_exists": article_dir_exists,
        "llm_input_exists": llm_input_exists,
        "meta_exists": meta_exists,
        "meta_json_ok": meta_ok,
        "meta_error": meta_error,
        "article_dir": row.get("article_dir"),
        "llm_input_path": row.get("llm_input_path"),
        "meta_path": row.get("meta_path"),
        "poster_ocr_path": row.get("poster_ocr_path"),
        "_lane": row.get("_lane"),
        "_authority_source": row.get("_authority_source"),
        "rules_version": RULES_VERSION,
    }


def classify_rows(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {row.get("article_uid"): classify_row(row) for row in rows if row.get("article_uid")}


def is_ultra(row: Dict[str, Any], classification: Optional[Dict[str, Any]]) -> bool:
    # Correct bug: `_lane=normal_no_ultra` is explicitly normal and must not match substring "ultra".
    cls = (classification or {}).get("classification")
    lane = str(row.get("_lane") or row.get("lane") or "").strip().lower()
    quality = str(row.get("quality") or "").strip().lower()
    return cls == "ultra_long" or lane in {"ultra", "ultra_long", "er-m3-long"} or quality == "ultra"


def is_blocked(row: Dict[str, Any], classification: Optional[Dict[str, Any]]) -> bool:
    cls = (classification or {}).get("classification")
    lane = str(row.get("_lane") or row.get("lane") or "").strip().lower()
    quality = str(row.get("quality") or "").strip().lower()
    return cls in {"blocked_missing_path", "blocked_schema_bad"} or lane in {"blocked", "blocked_missing_path", "blocked_schema_bad"} or quality == "blocked"


def preflight_rows(
    rows: List[Dict[str, Any]],
    classifications: Dict[str, Dict[str, Any]],
    *,
    expected_count: Optional[int],
    c300_uids: Optional[set[str]] = None,
    historical_uids: Optional[set[str]] = None,
    historical_batch001_uids: Optional[set[str]] = None,
) -> Dict[str, Any]:
    c300_uids = c300_uids or set()
    historical_uids = historical_uids or set()
    historical_batch001_uids = historical_batch001_uids or set()
    duplicates = collections.Counter(row.get("article_uid") for row in rows)
    duplicate_uids = {uid: count for uid, count in duplicates.items() if uid and count > 1}
    bad_json = 0
    schema_bad = []
    missing_llm = []
    missing_meta = []
    missing_article = []
    c300_overlap = []
    historical_overlap = []
    historical_batch001_overlap = []
    blocked = []
    ultra = []
    unexpected_skip = []
    accounts = collections.Counter()
    buckets = collections.Counter()
    class_counts = collections.Counter()
    terminal_counts = collections.Counter()
    chars = []

    for idx, row in enumerate(rows, 1):
        uid = row.get("article_uid")
        cls = classifications.get(uid) or classify_row(row)
        classification = cls.get("classification")
        terminal_state = cls.get("terminal_state")
        class_counts[classification or "missing_classifier_row"] += 1
        terminal_counts[terminal_state or "missing_classifier_row"] += 1
        accounts[row.get("source_account") or ""] += 1
        buckets[row.get("length_bucket") or ""] += 1
        try:
            chars.append(int(row.get("input_chars") or cls.get("actual_input_chars") or 0))
        except Exception:  # noqa: BLE001
            pass
        missing = [field for field in REQUIRED_FIELDS if not row.get(field)]
        if missing:
            schema_bad.append({"line": row.get("_jsonl_line") or idx, "article_uid": uid, "missing_fields": missing})
        article_dir = to_wsl_path(row.get("article_dir"))
        llm_path = to_wsl_path(row.get("llm_input_path"))
        meta_path = to_wsl_path(row.get("meta_path"))
        if not (article_dir and article_dir.exists() and article_dir.is_dir()):
            missing_article.append({"line": row.get("_jsonl_line") or idx, "article_uid": uid, "article_dir": row.get("article_dir")})
        if not (llm_path and llm_path.exists() and llm_path.is_file()):
            missing_llm.append({"line": row.get("_jsonl_line") or idx, "article_uid": uid, "llm_input_path": row.get("llm_input_path")})
        if not (meta_path and meta_path.exists() and meta_path.is_file()):
            missing_meta.append({"line": row.get("_jsonl_line") or idx, "article_uid": uid, "meta_path": row.get("meta_path")})
        if uid in c300_uids:
            c300_overlap.append(uid)
        if uid in historical_uids:
            historical_overlap.append(uid)
        if uid in historical_batch001_uids:
            historical_batch001_overlap.append(uid)
        if is_blocked(row, cls):
            blocked.append({"line": row.get("_jsonl_line") or idx, "article_uid": uid, "classification": classification, "reason": cls.get("reason")})
        if is_ultra(row, cls):
            ultra.append({"line": row.get("_jsonl_line") or idx, "article_uid": uid, "classification": classification, "input_chars": row.get("input_chars"), "reason": cls.get("reason")})
        if classification != NORMAL_CLASS:
            unexpected_skip.append({
                "line": row.get("_jsonl_line") or idx,
                "article_uid": uid,
                "source_account": row.get("source_account"),
                "classification": classification,
                "terminal_state": terminal_state,
                "reason": cls.get("reason"),
                "input_chars": row.get("input_chars") or cls.get("actual_input_chars"),
                "title": row.get("title"),
            })

    checks = {
        "selected_rows": len(rows),
        "parseable_rows": len(rows),
        "bad_json": bad_json,
        "schema_bad": len(schema_bad),
        "duplicate_uid_count": len(duplicate_uids),
        "missing_llm_input": len(missing_llm),
        "missing_meta": len(missing_meta),
        "missing_article_dir": len(missing_article),
        "c300_overlap": len(c300_overlap),
        "historical_c1000_manifest_overlap": len(historical_overlap),
        "historical_c1000_batch001_overlap": len(historical_batch001_overlap),
        "blocked_included": len(blocked),
        "ultra_included": len(ultra),
        "unexpected_skip": len(unexpected_skip),
        "empty_shell_included": class_counts.get("empty_input_shell", 0),
        "media_url_inventory_included": class_counts.get("media_url_inventory", 0),
        "low_signal_text_included": class_counts.get("low_signal_text", 0),
        "poster_only_included": class_counts.get("poster_only", 0),
    }
    gates = {
        "selected_rows_eq_expected": expected_count is None or checks["selected_rows"] == expected_count,
        "bad_json_eq_0": checks["bad_json"] == 0,
        "schema_bad_eq_0": checks["schema_bad"] == 0,
        "duplicate_uid_count_eq_0": checks["duplicate_uid_count"] == 0,
        "missing_llm_input_eq_0": checks["missing_llm_input"] == 0,
        "missing_meta_eq_0": checks["missing_meta"] == 0,
        "missing_article_dir_eq_0": checks["missing_article_dir"] == 0,
        "c300_overlap_eq_0": checks["c300_overlap"] == 0,
        "historical_c1000_manifest_overlap_eq_0": checks["historical_c1000_manifest_overlap"] == 0,
        "blocked_included_eq_0": checks["blocked_included"] == 0,
        "ultra_included_eq_0": checks["ultra_included"] == 0,
        "unexpected_skip_eq_0": checks["unexpected_skip"] == 0,
    }
    red_reasons = [key for key, ok in gates.items() if not ok]
    return {
        "generated_at": now_text(),
        "rules_version": RULES_VERSION,
        "checks": checks,
        "required_green_checks": gates,
        "verdict": "GREEN" if not red_reasons else "RED",
        "red_reasons": red_reasons,
        "batch_class_counts": dict(class_counts),
        "batch_terminal_state_counts": dict(terminal_counts),
        "batch_account_count": len([a for a in accounts if a]),
        "batch_top_accounts": [{"source_account": a, "count": c, "share": round(c / max(1, len(rows)), 4)} for a, c in accounts.most_common(20)],
        "batch_length_bucket_counts": dict(buckets),
        "batch_input_chars": {
            "min": min(chars) if chars else None,
            "max": max(chars) if chars else None,
            "mean": round(statistics.mean(chars), 2) if chars else None,
            "median": statistics.median(chars) if chars else None,
        },
        "examples": {
            "schema_bad": schema_bad[:20],
            "missing_llm_input": missing_llm[:20],
            "missing_meta": missing_meta[:20],
            "missing_article_dir": missing_article[:20],
            "c300_overlap": c300_overlap[:20],
            "historical_c1000_manifest_overlap": historical_overlap[:20],
            "historical_c1000_batch001_overlap": historical_batch001_overlap[:20],
            "blocked_rows": blocked[:20],
            "ultra_rows": ultra[:20],
            "unexpected_skip_rows": unexpected_skip[:50],
        },
        "llm_called": False,
        "batch_started": False,
        "production_allowed": False,
        "batch_002_allowed": False,
        "direct_93k_allowed": False,
    }


def repair_batch_rows(
    batch_rows: List[Dict[str, Any]],
    full_rows: List[Dict[str, Any]],
    classifications: Dict[str, Dict[str, Any]],
    *,
    target_count: int,
    c300_uids: Optional[set[str]] = None,
    historical_uids: Optional[set[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    c300_uids = c300_uids or set()
    historical_uids = historical_uids or set()
    kept: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in batch_rows:
        uid = row.get("article_uid")
        cls = classifications.get(uid) or classify_row(row)
        if uid and uid not in seen and cls.get("classification") == NORMAL_CLASS and uid not in c300_uids and uid not in historical_uids and not is_ultra(row, cls) and not is_blocked(row, cls):
            kept.append(row)
            seen.add(uid)
        else:
            removed.append(row)

    supplements: List[Dict[str, Any]] = []
    current_bucket_counts = collections.Counter(r.get("length_bucket") or "" for r in kept)
    current_account_counts = collections.Counter(r.get("source_account") or "" for r in kept)

    def score_candidate(row: Dict[str, Any]) -> Tuple[int, int, int, str]:
        bucket = row.get("length_bucket") or ""
        account = row.get("source_account") or ""
        # Prefer underrepresented buckets and accounts to avoid introducing skew.
        return (current_bucket_counts[bucket], current_account_counts[account], int(row.get("input_chars") or 0), str(row.get("article_uid") or ""))

    pool: List[Dict[str, Any]] = []
    for row in full_rows:
        uid = row.get("article_uid")
        if not uid or uid in seen or uid in c300_uids or uid in historical_uids:
            continue
        cls = classifications.get(uid) or classify_row(row)
        if cls.get("classification") != NORMAL_CLASS:
            continue
        if is_ultra(row, cls) or is_blocked(row, cls):
            continue
        pool.append(row)

    while len(kept) + len(supplements) < target_count and pool:
        pool.sort(key=score_candidate)
        chosen = pool.pop(0)
        supplements.append(chosen)
        uid = chosen.get("article_uid")
        if uid:
            seen.add(uid)
        current_bucket_counts[chosen.get("length_bucket") or ""] += 1
        current_account_counts[chosen.get("source_account") or ""] += 1
        pool = [row for row in pool if row.get("article_uid") not in seen]

    repaired = kept + supplements
    return repaired, removed, supplements


def load_uids_from_result(path: Optional[Path]) -> set[str]:
    if not path or not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("results") or data.get("rows") or []
    else:
        rows = []
    return {r.get("article_uid") for r in rows if isinstance(r, dict) and r.get("article_uid")}


def load_uids_from_jsonl(path: Optional[Path]) -> set[str]:
    if not path or not path.exists():
        return set()
    rows, _errors, _total = read_jsonl(path)
    return {r.get("article_uid") for r in rows if r.get("article_uid")}


def write_md_report(path: Path, data: Dict[str, Any]) -> None:
    checks = data.get("preflight", {}).get("checks", {})
    lines = [
        f"# Stage7 Strict Manifest Control — {data.get('generated_at')}",
        "",
        f"STATUS: **{data.get('status')}**",
        f"PREFLIGHT_VERDICT: **{data.get('preflight', {}).get('verdict')}**",
        "",
        "## Scope",
        "No-model control-plane classifier/preflight/repair. `llm_called=false`; `batch_started=false`.",
        "",
        "## Inputs",
    ]
    for key in ["full_candidate_manifest", "input_batch_manifest", "old_c1000_manifest", "c300_result_json"]:
        if data.get(key):
            lines.append(f"- {key}: `{md_path(Path(data[key]))}`")
    if data.get("output_repaired_manifest"):
        lines.extend(["", "## Outputs", f"- repaired_manifest: `{md_path(Path(data['output_repaired_manifest']))}`"])
    lines.extend(["", "## Preflight checks"])
    for key, value in checks.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Removed rows"])
    for row in data.get("removed_rows", [])[:20]:
        lines.append(f"- `{row.get('article_uid')}` classification={row.get('classification')} reason={row.get('reason')}")
    lines.extend(["", "## Supplements"])
    for row in data.get("supplement_rows", [])[:20]:
        lines.append(f"- `{row.get('article_uid')}` account={row.get('source_account')} bucket={row.get('length_bucket')}")
    lines.extend(["", "## Gates", f"- red_reasons: `{data.get('preflight', {}).get('red_reasons')}`", "", "## Forbidden actions kept", "- No 93K", "- No old C1000 resume", "- No batch_002 auto-run", "- No night_queue mutation", "- No deletion/overwrite of old evidence"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-candidate", required=True, type=Path)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--out-manifest", required=True, type=Path)
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--report-md", required=True, type=Path)
    parser.add_argument("--classifier-jsonl", type=Path)
    parser.add_argument("--c300-result", type=Path)
    parser.add_argument("--old-c1000", type=Path)
    parser.add_argument("--old-c1000-batch001", type=Path)
    parser.add_argument("--expected-count", type=int, default=200)
    parser.add_argument("--allow-overwrite", action="store_true")
    args = parser.parse_args(argv)

    for target in [args.out_manifest, args.report_json, args.report_md]:
        if target.exists() and not args.allow_overwrite:
            raise SystemExit(f"Refusing to overwrite existing output: {target}")

    full_rows, full_errors, full_total = read_jsonl(args.full_candidate)
    batch_rows, batch_errors, batch_total = read_jsonl(args.batch)
    if full_errors or batch_errors:
        # Continue into report, but do not allow GREEN.
        pass
    classifications = classify_rows(full_rows)
    if args.classifier_jsonl:
        write_jsonl(args.classifier_jsonl, classifications.values())

    c300_uids = load_uids_from_result(args.c300_result)
    historical_uids = load_uids_from_jsonl(args.old_c1000)
    historical_batch001_uids = load_uids_from_jsonl(args.old_c1000_batch001)
    # Do not exclude the current old poisoned manifest rows when repairing a new authority candidate;
    # only use old overlap as a preflight signal. For the 20260501 authority candidate this is expected zero.
    repaired, removed, supplements = repair_batch_rows(
        batch_rows,
        full_rows,
        classifications,
        target_count=args.expected_count,
        c300_uids=c300_uids,
        historical_uids=historical_uids,
    )
    preflight = preflight_rows(
        repaired,
        classifications,
        expected_count=args.expected_count,
        c300_uids=c300_uids,
        historical_uids=historical_uids,
        historical_batch001_uids=historical_batch001_uids,
    )
    # Bad source JSONL is a hard RED even if repaired rows are otherwise clean.
    if full_errors or batch_errors:
        preflight["verdict"] = "RED"
        preflight.setdefault("red_reasons", []).append("source_jsonl_parse_errors")
        preflight["source_parse_errors"] = {"full_candidate": full_errors[:20], "batch": batch_errors[:20]}

    written = write_jsonl(args.out_manifest, repaired)
    data = {
        "generated_at": now_text(),
        "status": "GREEN" if preflight.get("verdict") == "GREEN" else "RED",
        "rules_version": RULES_VERSION,
        "full_candidate_manifest": str(args.full_candidate),
        "full_candidate_sha256": sha256_file(args.full_candidate),
        "input_batch_manifest": str(args.batch),
        "input_batch_sha256": sha256_file(args.batch),
        "output_repaired_manifest": str(args.out_manifest),
        "output_repaired_manifest_sha256": sha256_file(args.out_manifest),
        "report_json": str(args.report_json),
        "report_md": str(args.report_md),
        "classifier_jsonl": str(args.classifier_jsonl) if args.classifier_jsonl else None,
        "c300_result_json": str(args.c300_result) if args.c300_result else None,
        "old_c1000_manifest": str(args.old_c1000) if args.old_c1000 else None,
        "old_c1000_batch001_manifest": str(args.old_c1000_batch001) if args.old_c1000_batch001 else None,
        "full_candidate_lines": full_total,
        "input_batch_lines": batch_total,
        "repaired_rows_written": written,
        "removed_count": len(removed),
        "supplement_count": len(supplements),
        "removed_rows": [dict(row, **classifications.get(row.get("article_uid"), {})) for row in removed[:100]],
        "supplement_rows": [{k: row.get(k) for k in ["article_uid", "source_account", "article_id", "input_chars", "length_bucket", "title"]} for row in supplements],
        "preflight": preflight,
        "llm_called": False,
        "batch_started": False,
        "production_allowed": False,
        "batch_002_allowed": False,
        "direct_93k_allowed": False,
    }
    write_json(args.report_json, data)
    write_md_report(args.report_md, data)
    print(json.dumps({
        "status": data["status"],
        "preflight_verdict": preflight.get("verdict"),
        "checks": preflight.get("checks"),
        "removed_count": len(removed),
        "supplement_count": len(supplements),
        "out_manifest": str(args.out_manifest),
        "report_json": str(args.report_json),
        "report_md": str(args.report_md),
        "llm_called": False,
        "batch_started": False,
    }, ensure_ascii=False, indent=2))
    return 0 if preflight.get("verdict") == "GREEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
