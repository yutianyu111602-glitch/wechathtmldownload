#!/usr/bin/env python3
"""Bounded DeepSeek Pro pilot for Stage7 extraction samples.

Writes only pilot report artifacts. Does not write Stage7 state, Qdrant,
Neo4j, PC SQLite production ledgers, or vector collections.

Supports manifest-driven, account/length balanced extraction with
deepseek-v4-pro and thinking disabled by default.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
if str(STAGE7_ROOT) not in sys.path:
    sys.path.insert(0, str(STAGE7_ROOT))

from stage7.chunker import chunk_article  # noqa: E402
from stage7.json_repair import parse_and_repair_json  # noqa: E402
from stage7.sanitize import sanitize_extract_limits  # noqa: E402
from stage7.schema_normalize import normalize_extract_schema  # noqa: E402
from stage7.validators import check_evidence_quotes, validate_extract  # noqa: E402


DEFAULT_PROMPT = STAGE7_ROOT / "config" / "prompt.extract.micro.zh.txt"
DEFAULT_ENDPOINT = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"
PRO_MODEL = "deepseek-v4-pro"
PRO_MAX_TOKENS = 1024
RAW_CONTENT_CAPTURE_CHARS = 8000


@dataclass
class PilotRow:
    sample_id: str
    article_uid: str
    source_account: str
    article_id: str
    title: str
    input_chars: int
    quality_grade: str
    local_image_count: int
    bucket: str
    llm_input_path: str
    meta_path: str


def _wsl_path(win_path: str) -> str:
    """Translate Windows path to WSL path when running under WSL."""
    path = str(win_path or "")
    if not path:
        return path
    if os.name != "posix" or not (
        os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP")
    ):
        return path
    # D:\foo → /mnt/d/foo, C:\foo → /mnt/c/foo
    if len(path) >= 2 and path[1] == ":":
        drive = path[0].lower()
        rest = path[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return path.replace("\\", "/")


def runtime_path(value: str | Path) -> Path:
    """Resolve manifest paths for the host running this worker."""
    raw = str(value or "")
    normalized = raw.replace("\\", "/")
    if os.name == "nt" and normalized.startswith("/mnt/") and len(normalized) > 7:
        drive = normalized[5]
        if normalized[6] == "/" and drive.isalpha():
            return Path(f"{drive.upper()}:/" + normalized[7:])
    return Path(raw)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(runtime_path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def compact(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def first_text(meta: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def clean_prompt_account(source_account: str) -> str:
    value = str(source_account or "").strip()
    if "__" in value:
        suffix = value.split("__", 1)[1].strip()
        if suffix:
            return suffix
    return value


def build_prompt_header(source_account: str, meta: dict[str, Any]) -> str:
    title = first_text(meta, "title")
    account = first_text(meta, "account_name", "account", "nickname", "source_account")
    publish_time = first_text(meta, "publishTime", "publish_time_text", "publish_time_iso")
    url = first_text(meta, "url", "source_url")
    account = clean_prompt_account(account or source_account)
    return (
        f"文章标题: {title}\n"
        f"公众号: {account}\n"
        f"发布时间: {publish_time}\n"
        f"URL: {url}\n"
    )


def char_bucket(chars: int) -> str:
    if chars <= 80:
        return "tiny"
    if chars <= 512:
        return "short"
    if chars <= 1800:
        return "medium"
    if chars <= 5000:
        return "long"
    return "xlong"


def bucket_key(row: dict[str, Any]) -> str:
    grade = compact(row.get("quality_grade") or "unknown", 40)
    image = "image" if int(row.get("local_image_count") or 0) > 0 else "text"
    chars = int(row.get("input_chars") or 0)
    return f"{grade}:{char_bucket(chars)}:{image}"


def iter_manifest_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                uid = str(row.get("article_uid") or "")
                if not uid or uid in seen:
                    continue
                if row.get("status") not in {None, "pending"}:
                    continue
                if not row.get("llm_input_path") or not row.get("meta_path"):
                    continue
                seen.add(uid)
                rows.append(row)
    return rows


def iter_pro_candidates(paths: list[Path]) -> tuple[list[PilotRow], list[dict[str, Any]]]:
    """Read pro_candidates.jsonl from the deterministic scorer.

    Returns (pilot_rows, candidate_metadata) where candidate_metadata
    preserves the original Flash routing/ metrics for each row.
    """
    pilot_rows: list[PilotRow] = []
    metadata: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                uid = str(row.get("article_uid") or "")
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                sample_id = str(row.get("sample_id") or f"pro_{uid[:12]}")
                pilot_rows.append(
                    PilotRow(
                        sample_id=sample_id,
                        article_uid=uid,
                        source_account=str(row.get("source_account") or ""),
                        article_id=str(row.get("article_id") or ""),
                        title=compact(row.get("title"), 200),
                        input_chars=int(row.get("input_chars") or 0),
                        quality_grade=str(row.get("quality_grade") or ""),
                        local_image_count=int(row.get("local_image_count") or 0),
                        bucket=str(row.get("bucket") or ""),
                        llm_input_path=_wsl_path(str(row.get("llm_input_path") or "")),
                        meta_path=_wsl_path(str(row.get("meta_path") or "")),
                    )
                )
                metadata.append(
                    {
                        "sample_id": sample_id,
                        "flash_routing": row.get("routing"),
                        "flash_metrics": row.get("metrics"),
                    }
                )
    return pilot_rows, metadata


def select_gold(rows: list[dict[str, Any]], *, limit: int, seed: int, max_per_account: int) -> list[PilotRow]:
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(bucket_key(row), []).append(row)
    for bucket_rows in buckets.values():
        rng.shuffle(bucket_rows)

    selected: list[PilotRow] = []
    per_account: dict[str, int] = {}
    bucket_names = sorted(buckets)
    bucket_index = 0
    while len(selected) < limit and bucket_names:
        name = bucket_names[bucket_index % len(bucket_names)]
        bucket_rows = buckets[name]
        row = bucket_rows.pop(0) if bucket_rows else None
        if not bucket_rows:
            bucket_names.remove(name)
            if bucket_names:
                bucket_index %= len(bucket_names)
        else:
            bucket_index += 1
        if not row:
            continue
        account = str(row.get("source_account") or "")
        if per_account.get(account, 0) >= max_per_account:
            continue
        per_account[account] = per_account.get(account, 0) + 1
        selected.append(
            PilotRow(
                sample_id=f"gold_{len(selected) + 1:04d}",
                article_uid=str(row.get("article_uid") or ""),
                source_account=account,
                article_id=str(row.get("article_id") or ""),
                title=compact(row.get("title"), 200),
                input_chars=int(row.get("input_chars") or 0),
                quality_grade=str(row.get("quality_grade") or ""),
                local_image_count=int(row.get("local_image_count") or 0),
                bucket=name,
                llm_input_path=_wsl_path(str(row.get("llm_input_path") or "")),
                meta_path=_wsl_path(str(row.get("meta_path") or "")),
            )
        )
    return selected


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp_path = Path(handle.name)
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    last_error: Exception | None = None
    for attempt in range(12):
        try:
            tmp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
    raise last_error or PermissionError(path)


def resolve_out_dir(args: argparse.Namespace) -> Path:
    base = Path(args.out_dir)
    root_name = str(getattr(args, "output_root_name", "") or "").strip()
    if not root_name:
        return base
    if Path(root_name).is_absolute() or "/" in root_name or "\\" in root_name:
        raise SystemExit("--output-root-name must be a single directory name, not a path")
    return base / root_name


def read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def deepseek_chat(
    client: httpx.Client,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    timeout_sec: int,
    max_retries: int,
    thinking: str = "disabled",
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "max_tokens": max_tokens,
    }
    # CRITICAL: Do NOT combine thinking=enabled with json_object response_format.
    # DeepSeek Pro with thinking enabled leaks reasoning tokens into content,
    # producing non-JSON output that parse_and_repair_json() cannot always fix.
    # When thinking is disabled, json_object is safe and improves JSON compliance.
    if thinking != "enabled":
        body["response_format"] = {"type": "json_object"}
    body["thinking"] = {"type": thinking}
    if reasoning_effort and thinking == "enabled":
        body["thinking"]["effort"] = reasoning_effort
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: dict[str, Any] = {}
    for attempt in range(max_retries + 1):
        try:
            response = client.post(
                f"{endpoint.rstrip('/')}/v1/chat/completions",
                json=body,
                headers=headers,
                timeout=timeout_sec,
            )
            if response.status_code in {429, 500, 503} and attempt < max_retries:
                time.sleep(min(60, 2 ** attempt * 5))
                continue
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            result: dict[str, Any] = {
                "ok": True,
                "content": message.get("content") or "",
                "usage": data.get("usage") or {},
                "model": data.get("model", model),
                "attempt": attempt + 1,
                "thinking": thinking,
            }
            return result
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            body_text = getattr(getattr(exc, "response", None), "text", "") or ""
            last_error = {
                "type": type(exc).__name__,
                "status": status,
                "message": str(exc)[:300],
                "body": body_text[:500],
            }
            if attempt < max_retries:
                time.sleep(min(60, 2 ** attempt * 5))
    return {"ok": False, "error": last_error}


def process_sample(
    sample: PilotRow,
    *,
    client: httpx.Client,
    endpoint: str,
    api_key: str,
    model: str,
    system_prompt: str,
    args: argparse.Namespace,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    row = asdict(sample)
    if extra_metadata:
        row["_pro_metadata"] = extra_metadata
    text = runtime_path(sample.llm_input_path).read_text(encoding="utf-8")
    meta = read_json(sample.meta_path)
    header = build_prompt_header(sample.source_account, meta)
    chunks = chunk_article(
        sample.article_uid,
        text,
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
    ).chunks
    if args.max_chunks_per_article > 0:
        chunks = chunks[: args.max_chunks_per_article]

    thinking = getattr(args, "thinking", "disabled") or "disabled"
    reasoning_effort = getattr(args, "reasoning_effort", None) or None

    chunk_rows: list[dict[str, Any]] = []
    totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "entities": 0,
        "events": 0,
        "relations": 0,
        "claims": 0,
        "evidence_total": 0,
        "evidence_hit": 0,
        "evidence_miss": 0,
    }
    parse_ok = 0
    schema_ok = 0
    for chunk in chunks:
        user_content = f"{header}\n---\nchunk_id: {chunk.chunk_id}\n\n{chunk.text}"
        call = deepseek_chat(
            client,
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            user_content=user_content,
            max_tokens=args.max_tokens,
            timeout_sec=args.timeout_sec,
            max_retries=args.max_retries,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )
        usage = call.get("usage") or {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                totals[key] += int(usage.get(key) or 0)
            except Exception:
                pass
        chunk_row: dict[str, Any] = {
            "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "chars": chunk.chars,
            "api_ok": bool(call.get("ok")),
            "usage": usage,
            "thinking": thinking,
        }
        if not call.get("ok"):
            chunk_row["error"] = call.get("error")
            chunk_rows.append(chunk_row)
            continue
        raw = str(call.get("content") or "")
        parsed = parse_and_repair_json(raw)
        chunk_row["parse_ok"] = parsed.ok
        chunk_row["parse_attempts"] = parsed.parse_attempts
        chunk_row["used_repair"] = parsed.used_repair
        chunk_row["raw_content"] = raw[:RAW_CONTENT_CAPTURE_CHARS]
        if not parsed.ok or not isinstance(parsed.value, dict):
            # Fallback: if thinking was enabled, retry with thinking disabled.
            # Thinking + json_object is a known incompatibility in DeepSeek API.
            if thinking == "enabled":
                fallback_call = deepseek_chat(
                    client,
                    endpoint=endpoint,
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    user_content=user_content,
                    max_tokens=args.max_tokens,
                    timeout_sec=args.timeout_sec,
                    max_retries=args.max_retries,
                    thinking="disabled",
                    reasoning_effort=None,
                )
                fallback_usage = fallback_call.get("usage") or {}
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    try:
                        totals[key] += int(fallback_usage.get(key) or 0)
                    except Exception:
                        pass
                chunk_row["fallback_retry"] = True
                chunk_row["fallback_usage"] = fallback_usage
                chunk_row["thinking"] = "enabled→disabled(fallback)"
                if fallback_call.get("ok"):
                    fallback_raw = str(fallback_call.get("content") or "")
                    fallback_parsed = parse_and_repair_json(fallback_raw)
                    chunk_row["parse_ok"] = fallback_parsed.ok
                    chunk_row["parse_attempts"] += fallback_parsed.parse_attempts
                    chunk_row["raw_content"] = fallback_raw[:RAW_CONTENT_CAPTURE_CHARS]
                    if fallback_parsed.ok and isinstance(fallback_parsed.value, dict):
                        parsed = fallback_parsed
                    else:
                        chunk_row["parse_error"] = f"fallback also failed: {fallback_parsed.error_message}"
                else:
                    chunk_row["fallback_error"] = fallback_call.get("error")
            if not parsed.ok or not isinstance(parsed.value, dict):
                chunk_row["parse_error"] = parsed.error_message
                chunk_rows.append(chunk_row)
                continue
        parse_ok += 1
        normalized, norm_stats = normalize_extract_schema(parsed.value)
        sanitized, sanitize_stats = sanitize_extract_limits(normalized, source_text=user_content)
        validation = validate_extract(sanitized, source_text=user_content)
        chunk_row["schema_ok"] = validation["ok"]
        chunk_row["validation_errors"] = validation.get("errors", [])[:10]
        chunk_row["validation_warnings"] = validation.get("warnings", [])[:10]
        chunk_row["normalize_stats"] = norm_stats
        chunk_row["sanitize_stats"] = {k: v for k, v in sanitize_stats.items() if v}
        if validation["ok"]:
            schema_ok += 1
            data = validation["data"]
        else:
            data = sanitized
        evidence = check_evidence_quotes(user_content, data)
        chunk_row["evidence"] = evidence
        for key, collection in (
            ("entities", data.get("entities", [])),
            ("events", data.get("events", [])),
            ("relations", data.get("relations", [])),
            ("claims", data.get("claims", [])),
        ):
            count = len(collection) if isinstance(collection, list) else 0
            chunk_row[f"{key}_count"] = count
            totals[key] += count
        for key in ("evidence_total", "evidence_hit", "evidence_miss"):
            totals[key] += int(evidence.get(key) or 0)
        chunk_rows.append(chunk_row)

    row.update(
        {
            "ok_chunks": sum(1 for item in chunk_rows if item.get("api_ok")),
            "chunk_count": len(chunks),
            "parse_ok_chunks": parse_ok,
            "schema_ok_chunks": schema_ok,
            "totals": totals,
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "chunks": chunk_rows,
        }
    )
    return row


def process_sample_with_client(
    sample: PilotRow,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    system_prompt: str,
    args: argparse.Namespace,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with httpx.Client() as client:
        return process_sample(
            sample,
            client=client,
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            args=args,
            extra_metadata=extra_metadata,
        )


def summarize(rows: list[dict[str, Any]], *, selected: list[PilotRow], args: argparse.Namespace) -> dict[str, Any]:
    chunk_count = sum(int(row.get("chunk_count") or 0) for row in rows)
    ok_chunks = sum(int(row.get("ok_chunks") or 0) for row in rows)
    parse_ok = sum(int(row.get("parse_ok_chunks") or 0) for row in rows)
    schema_ok = sum(int(row.get("schema_ok_chunks") or 0) for row in rows)
    prompt_tokens = sum(int((row.get("totals") or {}).get("prompt_tokens") or 0) for row in rows)
    completion_tokens = sum(int((row.get("totals") or {}).get("completion_tokens") or 0) for row in rows)
    # Use Pro pricing when in Pro mode
    if getattr(args, "pro_mode", False):
        input_price = 3.0
        output_price = 6.0
    else:
        input_price = 1.0
        output_price = 2.0
    estimated_cny = prompt_tokens / 1_000_000 * input_price + completion_tokens / 1_000_000 * output_price
    buckets: dict[str, int] = {}
    for sample in selected:
        buckets[sample.bucket] = buckets.get(sample.bucket, 0) + 1
    return {
        "schema_version": "stage7_deepseek_flash_pilot.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "pro" if getattr(args, "pro_mode", False) else args.mode,
        "model": args.model,
        "thinking": getattr(args, "thinking", "disabled"),
        "writes": "pilot artifacts only; no Stage7 state/Qdrant/Neo4j/production SQLite writes",
        "selected_samples": len(selected),
        "processed_samples": len(rows),
        "chunk_count": chunk_count,
        "api_ok_chunks": ok_chunks,
        "api_ok_rate": round(ok_chunks / max(chunk_count, 1), 4),
        "parse_ok_chunks": parse_ok,
        "parse_ok_rate": round(parse_ok / max(ok_chunks, 1), 4),
        "schema_ok_chunks": schema_ok,
        "schema_ok_rate": round(schema_ok / max(parse_ok, 1), 4),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cny": round(estimated_cny, 4),
        "bucket_counts": buckets,
    }


def _output_prefix(args: argparse.Namespace) -> str:
    """Return 'pro' when --pro-mode, otherwise 'flash'."""
    return "pro" if getattr(args, "pro_mode", False) else "flash"


def write_running_summary(out_dir: Path, rows: list[dict[str, Any]], *, selected: list[PilotRow], args: argparse.Namespace) -> None:
    summary = summarize(rows, selected=selected, args=args)
    prefix = _output_prefix(args)
    summary.update(
        {
            "status": "complete" if len(rows) >= len(selected) else "running",
            "pending_samples": max(0, len(selected) - len(rows)),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    write_json(out_dir / f"{prefix}_running_summary.json", summary)


def _build_pro_summary(rows: list[dict[str, Any]], selected: list[PilotRow], args: argparse.Namespace) -> dict[str, Any]:
    """Extended summary for Pro mode including before/after comparison."""
    base = summarize(rows, selected=selected, args=args)
    base["schema_version"] = "stage7_deepseek_pro_pilot.v1"

    # Count how many Pro candidates improved over Flash
    flash_schema_fails = 0
    pro_schema_ok = 0
    flash_zero_both = 0
    pro_has_output = 0
    for row in rows:
        meta = row.get("_pro_metadata") or {}
        flash_metrics = meta.get("flash_metrics") or {}
        if not (flash_metrics.get("schema_ok") or True):
            flash_schema_fails += 1
        if row.get("schema_ok_chunks", 0) == row.get("chunk_count", 1) and row.get("chunk_count", 0) > 0:
            pro_schema_ok += 1
        if flash_metrics.get("zero_both"):
            flash_zero_both += 1
        if (row.get("totals") or {}).get("entities", 0) + (row.get("totals") or {}).get("events", 0) > 0:
            pro_has_output += 1

    base["flash_schema_fail_count"] = flash_schema_fails
    base["pro_schema_pass_count"] = pro_schema_ok
    base["flash_zero_both_count"] = flash_zero_both
    base["pro_nonzero_output_count"] = pro_has_output
    base["pro_schema_rescue_rate"] = round(pro_schema_ok / max(flash_schema_fails, 1), 4)
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-jsonl", action="append", default=[])
    parser.add_argument("--pro-candidates-jsonl", action="append", default=[])
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--output-root-name", default="")
    parser.add_argument("--mode", choices=["select-only", "run"], default="select-only")
    parser.add_argument("--pro-mode", action="store_true", default=False)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260509)
    parser.add_argument("--max-per-account", type=int, default=20)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--prompt-path", default=str(DEFAULT_PROMPT))
    parser.add_argument("--target-chars", type=int, default=900)
    parser.add_argument("--max-chars", type=int, default=1800)
    parser.add_argument("--min-chars", type=int, default=300)
    parser.add_argument("--max-chunks-per-article", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--timeout-sec", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--resume-from", default="")
    parser.add_argument("--thinking", choices=["enabled", "disabled"], default="")
    parser.add_argument("--reasoning-effort", default="")
    args = parser.parse_args(argv)

    # Resolve mode
    pro_mode = args.pro_mode or bool(args.pro_candidates_jsonl)

    # Resolve model
    if not args.model:
        args.model = PRO_MODEL if pro_mode else DEFAULT_MODEL
    # Resolve max_tokens
    if args.max_tokens <= 0:
        args.max_tokens = PRO_MAX_TOKENS if pro_mode else 384
    # Resolve thinking
    # NOTE: Pro defaults to thinking=disabled because thinking+json_object
    # is a known incompatibility in DeepSeek API (57% parse failure rate
    # observed in smoke test). Fallback retry doubles cost and latency.
    # Use --thinking enabled explicitly if you want to test it.
    if not args.thinking:
        args.thinking = "disabled"
    # Ensure reasoning_effort is None when empty string
    if not args.reasoning_effort:
        args.reasoning_effort = None

    out_dir = resolve_out_dir(args)
    out_dir.mkdir(parents=True, exist_ok=True)

    selected: list[PilotRow] = []
    candidate_metadata: list[dict[str, Any]] = []

    if pro_mode:
        pro_paths = [Path(value) for value in args.pro_candidates_jsonl]
        if not pro_paths:
            # Try manifest_jsonl as fallback for pro_candidates
            pro_paths = [Path(value) for value in args.manifest_jsonl]
        missing = [str(path) for path in pro_paths if not path.exists()]
        if missing:
            raise SystemExit(f"missing pro candidates jsonl(s): {missing}")
        selected, candidate_metadata = iter_pro_candidates(pro_paths)
        if args.limit and len(selected) > args.limit:
            selected = selected[: args.limit]
            candidate_metadata = candidate_metadata[: args.limit]
        # Write selected manifest for traceability
        write_jsonl(out_dir / "selected_manifest.jsonl", [asdict(sample) for sample in selected])
    else:
        manifest_paths = [Path(value) for value in args.manifest_jsonl]
        if not manifest_paths:
            raise SystemExit("--manifest-jsonl is required in Flash mode (or use --pro-mode)")
        missing = [str(path) for path in manifest_paths if not path.exists()]
        if missing:
            raise SystemExit(f"missing manifest(s): {missing}")
        rows = iter_manifest_rows(manifest_paths)
        selected = select_gold(rows, limit=args.limit, seed=args.seed, max_per_account=args.max_per_account)
        write_jsonl(out_dir / "selected_manifest.jsonl", [asdict(sample) for sample in selected])

    write_running_summary(out_dir, [], selected=selected, args=args)

    # Build metadata lookup for Pro mode
    metadata_by_id: dict[str, dict[str, Any]] = {}
    if pro_mode:
        for meta in candidate_metadata:
            metadata_by_id[str(meta.get("sample_id") or "")] = meta

    selected_index = {sample.sample_id: index for index, sample in enumerate(selected)}
    outputs: list[dict[str, Any]] = []
    if args.resume_from:
        resumed_by_id: dict[str, dict[str, Any]] = {}
        for row in read_jsonl_rows(Path(args.resume_from)):
            sample_id = str(row.get("sample_id") or "")
            if sample_id in selected_index:
                resumed_by_id[sample_id] = row
        outputs = list(resumed_by_id.values())

    prefix = _output_prefix(args)

    if args.mode == "run":
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise SystemExit(f"{args.api_key_env} is not set")
        system_prompt = Path(args.prompt_path).read_text(encoding="utf-8")
        done_ids = {str(row.get("sample_id") or "") for row in outputs}
        pending = [sample for sample in selected if sample.sample_id not in done_ids]
        concurrency = max(1, int(args.concurrency or 1))
        if concurrency == 1:
            with httpx.Client() as client:
                for index, sample in enumerate(pending, start=1):
                    print(
                        f"[{len(outputs) + 1}/{len(selected)}] {sample.source_account} / {sample.article_id}",
                        flush=True,
                    )
                    try:
                        extra = metadata_by_id.get(sample.sample_id) if pro_mode else None
                        outputs.append(
                            process_sample(
                                sample,
                                client=client,
                                endpoint=args.endpoint,
                                api_key=api_key,
                                model=args.model,
                                system_prompt=system_prompt,
                                args=args,
                                extra_metadata=extra,
                            )
                        )
                    except Exception as exc:
                        row = asdict(sample)
                        if pro_mode:
                            extra = metadata_by_id.get(sample.sample_id)
                            if extra:
                                row["_pro_metadata"] = extra
                        row.update({"fatal_error": f"{type(exc).__name__}: {str(exc)[:500]}"})
                        outputs.append(row)
                    outputs.sort(key=lambda row: selected_index.get(str(row.get("sample_id") or ""), 10**9))
                    write_jsonl(out_dir / f"{prefix}_rows.partial.jsonl", outputs)
                    write_running_summary(out_dir, outputs, selected=selected, args=args)
        else:
            print(f"resumed={len(outputs)} pending={len(pending)} concurrency={concurrency}", flush=True)
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {}
                for sample in pending:
                    extra = metadata_by_id.get(sample.sample_id) if pro_mode else None
                    futures[
                        executor.submit(
                            process_sample_with_client,
                            sample,
                            endpoint=args.endpoint,
                            api_key=api_key,
                            model=args.model,
                            system_prompt=system_prompt,
                            args=args,
                            extra_metadata=extra,
                        )
                    ] = sample
                completed = len(outputs)
                for future in as_completed(futures):
                    sample = futures[future]
                    completed += 1
                    try:
                        row = future.result()
                    except Exception as exc:
                        row = asdict(sample)
                        if pro_mode:
                            extra = metadata_by_id.get(sample.sample_id)
                            if extra:
                                row["_pro_metadata"] = extra
                        row.update({"fatal_error": f"{type(exc).__name__}: {str(exc)[:500]}"})
                    outputs.append(row)
                    outputs.sort(key=lambda item: selected_index.get(str(item.get("sample_id") or ""), 10**9))
                    write_jsonl(out_dir / f"{prefix}_rows.partial.jsonl", outputs)
                    write_running_summary(out_dir, outputs, selected=selected, args=args)
                    print(
                        f"[{completed}/{len(selected)}] done {sample.source_account} / {sample.article_id}",
                        flush=True,
                    )

    write_jsonl(out_dir / f"{prefix}_rows.jsonl", outputs)
    summary = _build_pro_summary(outputs, selected=selected, args=args) if pro_mode else summarize(outputs, selected=selected, args=args)
    write_json(out_dir / f"{prefix}_summary.json", summary)
    write_running_summary(out_dir, outputs, selected=selected, args=args)
    print(json.dumps({"ok": True, "out_dir": str(out_dir), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
