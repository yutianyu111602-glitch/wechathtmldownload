#!/usr/bin/env python3
"""Run DeepSeek over Atlas entity merge candidate clusters.

Default mode is a dry-run that validates prompts and writes sidecar decisions.
Use --execute for direct DeepSeek API calls. The runner is report-only and does
not mutate Atlas SQLite, Neo4j, Qdrant, mem0, or production pointers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEMA_VERSION = "atlas_entity_merge_deepseek_results.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_queue_current" / "entity_merge_llm_queue.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_results_current"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"


SYSTEM_PROMPT = """你是中国地下电子音乐 Atlas 的实体消歧裁决器。
任务：判断候选 subject 是否指向同一个真实世界实体。

严格规则：
1. 只根据输入 evidence pack 判断，不使用外部记忆，不编造。
2. DJ/个人 与 俱乐部/厂牌/电台 默认不能合并，除非证据明确说明同一主体。
3. 场地 venue 与 organizer/club brand 可以合并为同一 public scene entity，但必须标记 mixed_type_merge。
4. 例如 ALL、ALL Club、ALL俱乐部 若证据一致可 merge；Loopy、loopy Club、杭州 Loopy 若是同一俱乐部/主办实体可 merge。
5. 例如 loopy遗孀、akkoii [loopy]、Knock Knock Loopy 这类人名/成员/活动上下文不能因为包含 Loopy 就合并到 Loopy。
6. 不确定必须 review，不要强行 merge。
7. 输出严格 JSON object，不要 Markdown。

JSON schema:
{
  "decision":"merge|split|review",
  "canonical_subject_id":"string",
  "canonical_name":"string",
  "confidence":0.0,
  "merged_subject_ids":["string"],
  "blocked_subject_ids":["string"],
  "reason_zh":"不超过180字中文说明",
  "risk_flags":["mixed_type_merge"]
}"""

STRICT_SYSTEM_PROMPT = SYSTEM_PROMPT + """

额外严格规则：
8. 输出 decision=merge 时，merged_subject_ids 只能包含确定同一真实实体的 subject；不确定项必须放入 blocked_subject_ids 或 decision=review。
9. 如果同一个 block 中同时出现场地、主办、DJ、作品名、活动名，先分层：真实场地/俱乐部品牌可合并；DJ/个人、活动标题、合作项目、专场名不能因为共享词而合并。
10. city_text 不一致、名称只是包含同一个短词、或证据只来自活动标题时，优先 split/review。
11. 不要输出 decision=review 时再填写 merged_subject_ids；需要人工复核就把 merged_subject_ids 置空。
"""

SOUND_AWARE_SYSTEM_PROMPT = STRICT_SYSTEM_PROMPT + """

音响系统规则：
12. 音响系统是场地属性，不是实体合并依据。Funktion-One、L-Acoustics、d&b、Void、Martin Audio、音响系统、Sound System 等设备/配置名不能和俱乐部、DJ、主办实体合并。
13. 名称中包含 "soundsystem" 的 crew/DJ/项目，默认不是场地本体；只有 evidence pack 明确说明它就是同一俱乐部/主办品牌时才可与场地合并，否则 split/review。
14. 可以在 reason_zh 中说明“音响系统/设备证据应进入 venue attribute sidecar”，但不要把设备当 subject 合并。
"""

PROMPT_PROFILES = {
    "baseline": SYSTEM_PROMPT,
    "strict_v2": STRICT_SYSTEM_PROMPT,
    "sound_aware_v1": SOUND_AWARE_SYSTEM_PROMPT,
}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL object at {path}:{line_no}")
            rows.append(row)
    return rows


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def existing_decisions(path: Path, *, retry_errors: bool, target_execute: bool) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = read_jsonl(path)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        cluster_id = text(row.get("cluster_id"))
        if not cluster_id:
            continue
        if retry_errors and text(row.get("decision")) == "error":
            continue
        if target_execute and not bool(row.get("execute")):
            continue
        out[cluster_id] = row
    return out


def endpoint_from_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def build_user_prompt(cluster: dict[str, Any]) -> str:
    payload = {
        "task": cluster.get("llm_task"),
        "cluster_id": cluster.get("cluster_id"),
        "block_key": cluster.get("block_key"),
        "canonical_hint": cluster.get("canonical_hint"),
        "risk_flags": cluster.get("risk_flags") or [],
        "second_pass_context": cluster.get("second_pass_context") or {},
        "members": cluster.get("members") or [],
        "output_contract": cluster.get("output_contract") or {},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def system_prompt_for(args: argparse.Namespace) -> tuple[str, str]:
    prompt_path = text(getattr(args, "system_prompt_path", ""))
    if prompt_path:
        return Path(prompt_path).read_text(encoding="utf-8"), "custom_file"
    profile = text(getattr(args, "prompt_profile", "")) or "baseline"
    return PROMPT_PROFILES.get(profile, SYSTEM_PROMPT), profile if profile in PROMPT_PROFILES else "baseline"


def call_deepseek(*, cluster: dict[str, Any], api_key: str, base_url: str, model: str, timeout_s: int, max_tokens: int, temperature: float, system_prompt: str) -> tuple[dict[str, Any], dict[str, Any], float]:
    started = time.perf_counter()
    request_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(cluster)},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    req = Request(
        endpoint_from_base(base_url),
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API {exc.code}: {body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"DeepSeek API network error: {exc}") from exc
    payload = json.loads(raw)
    message = (payload.get("choices") or [{}])[0].get("message") or {}
    content = text(message.get("content"))
    if not content and message.get("reasoning_content"):
        reasoning = text(message.get("reasoning_content"))
        start = reasoning.rfind("{")
        end = reasoning.rfind("}")
        if start >= 0 and end > start:
            content = reasoning[start : end + 1]
    if not content:
        raise RuntimeError("DeepSeek response did not include JSON content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(content[start : end + 1])
    latency_ms = (time.perf_counter() - started) * 1000
    return parsed, payload.get("usage") or {}, latency_ms


def dry_run_decision(cluster: dict[str, Any]) -> dict[str, Any]:
    members = cluster.get("members") or []
    canonical = cluster.get("canonical_hint") or {}
    return {
        "decision": "dry_run",
        "canonical_subject_id": text(canonical.get("subject_id")),
        "canonical_name": text(canonical.get("display_name")),
        "confidence": 0.0,
        "merged_subject_ids": [text(item.get("subject_id")) for item in members if text(item.get("subject_id"))],
        "blocked_subject_ids": [],
        "reason_zh": "dry-run only; prompt/evidence pack validated, no DeepSeek call executed.",
        "risk_flags": cluster.get("risk_flags") or [],
    }


def text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        item_text = text(item)
        if item_text and item_text not in seen:
            seen.add(item_text)
            out.append(item_text)
    return out


def normalize_llm_decision(parsed: dict[str, Any], cluster: dict[str, Any], *, require_full_cluster_merge: bool = False) -> dict[str, Any]:
    members = cluster.get("members") or []
    member_ids = {text(item.get("subject_id")) for item in members if text(item.get("subject_id"))}
    flags = text_list(parsed.get("risk_flags"))
    raw_decision = text(parsed.get("decision")).casefold()
    decision = raw_decision if raw_decision in {"merge", "split", "review"} else "review"
    if decision != raw_decision:
        flags.append("llm_output_invalid_decision")

    merged = [item for item in text_list(parsed.get("merged_subject_ids")) if item in member_ids]
    blocked = [item for item in text_list(parsed.get("blocked_subject_ids")) if item in member_ids and item not in set(merged)]
    canonical_subject_id = text(parsed.get("canonical_subject_id"))
    if canonical_subject_id and canonical_subject_id not in member_ids:
        flags.append("llm_output_unknown_canonical_subject")
        canonical_subject_id = ""

    if decision == "merge":
        if canonical_subject_id and canonical_subject_id not in merged:
            merged.insert(0, canonical_subject_id)
        if len(merged) < 2:
            flags.append("llm_output_merge_without_multiple_members")
            decision = "review"
        elif require_full_cluster_merge and set(merged) != member_ids:
            flags.append("llm_output_partial_merge_not_allowed")
            decision = "review"
            merged = []
    elif merged:
        flags.append("llm_output_inconsistent_nonmerge_with_merged_ids")
        decision = "review"

    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
        flags.append("llm_output_invalid_confidence")
    confidence = max(0.0, min(1.0, confidence))

    return {
        **parsed,
        "decision": decision,
        "raw_llm_decision": raw_decision,
        "canonical_subject_id": canonical_subject_id,
        "canonical_name": text(parsed.get("canonical_name")),
        "confidence": confidence,
        "merged_subject_ids": merged,
        "blocked_subject_ids": blocked,
        "reason_zh": text(parsed.get("reason_zh"))[:240],
        "risk_flags": text_list(flags),
    }


def decision_for_cluster(cluster: dict[str, Any], args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    prompt = build_user_prompt(cluster)
    system_prompt, prompt_profile = system_prompt_for(args)
    request_retries = max(0, int(getattr(args, "request_retries", 0) or 0))
    retry_sleep_s = max(0.0, float(getattr(args, "retry_sleep_s", 0.0) or 0.0))
    base = {
        "schema_version": SCHEMA_VERSION + ".decision",
        "cluster_id": cluster.get("cluster_id"),
        "block_key": cluster.get("block_key"),
        "member_count": cluster.get("member_count"),
        "prompt_chars": len(prompt),
        "model": args.model,
        "prompt_profile": prompt_profile,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        "execute": bool(args.execute),
        "created_at": now_iso(),
    }
    try:
        if args.execute:
            errors: list[str] = []
            for attempt in range(request_retries + 1):
                try:
                    parsed, usage, latency_ms = call_deepseek(
                        cluster=cluster,
                        api_key=api_key,
                        base_url=args.base_url,
                        model=args.model,
                        timeout_s=int(args.timeout_s),
                        max_tokens=int(args.max_tokens),
                        temperature=float(args.temperature),
                        system_prompt=system_prompt,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - retry transient direct API failures.
                    errors.append(str(exc))
                    if attempt >= request_retries:
                        raise RuntimeError(" | ".join(errors[-3:])) from exc
                    if retry_sleep_s:
                        time.sleep(retry_sleep_s * (attempt + 1))
            parsed = normalize_llm_decision(
                parsed,
                cluster,
                require_full_cluster_merge=bool(getattr(args, "require_full_cluster_merge", False)),
            )
            return {**base, **parsed, "usage": usage, "latency_ms": latency_ms, "error": ""}
        return {**base, **dry_run_decision(cluster), "usage": {}, "latency_ms": 0, "error": ""}
    except Exception as exc:  # noqa: BLE001 - report-only batch must continue.
        return {**base, "decision": "error", "error": str(exc)}


def summary_payload(
    *,
    queue_path: Path,
    out_dir: Path,
    decisions_path: Path,
    errors_path: Path,
    args: argparse.Namespace,
    queue_rows: int,
    filtered_rows: int,
    offset_rows: int,
    resumable_rows: int,
    selected_rows: int,
    previous_count: int,
    counts: Counter,
    completed_rows: int,
    submitted_rows: int,
    concurrency: int,
    checkpoint_every: int,
    status: str,
    stop_reason: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_deepseek_results_ready_report_only",
        "status": status,
        "stop_reason": stop_reason,
        "queue_path": str(queue_path),
        "out_dir": str(out_dir),
        "execute": bool(args.execute),
        "model": args.model,
        "prompt_profile": "custom_file" if text(getattr(args, "system_prompt_path", "")) else (text(getattr(args, "prompt_profile", "")) or "baseline"),
        "require_full_cluster_merge": bool(getattr(args, "require_full_cluster_merge", False)),
        "queue_rows": queue_rows,
        "rows_after_filter": filtered_rows,
        "rows_after_offset": offset_rows,
        "rows_after_resume": resumable_rows,
        "rows": selected_rows,
        "submitted_rows": submitted_rows,
        "completed_rows": completed_rows,
        "previous_decisions_loaded": previous_count,
        "skipped_by_offset": filtered_rows - offset_rows,
        "skipped_by_resume": offset_rows - resumable_rows,
        "counts": dict(counts),
        "decisions_path": str(decisions_path),
        "errors_path": str(errors_path),
        "concurrency": concurrency,
        "checkpoint_every": checkpoint_every,
        "safety": {
            "report_only": True,
            "llm_call_executed": bool(args.execute),
            "direct_deepseek_only": True,
            "sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "raw_secret_printed": False,
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    out_dir = Path(args.out_dir)
    decisions_path = out_dir / "entity_merge_llm_decisions.jsonl"
    errors_path = out_dir / "entity_merge_llm_errors.jsonl"
    rows = read_jsonl(queue_path)
    queue_rows = len(rows)
    if text(getattr(args, "block_key", "")):
        selected = text(args.block_key)
        rows = [row for row in rows if text(row.get("block_key")) == selected]
    if text(getattr(args, "cluster_id", "")):
        selected = text(args.cluster_id)
        rows = [row for row in rows if text(row.get("cluster_id")) == selected]
    filtered_rows = len(rows)
    skip_clusters = max(0, int(getattr(args, "skip_clusters", 0) or 0))
    if skip_clusters:
        rows = rows[skip_clusters:]
    offset_rows = len(rows)
    previous = existing_decisions(
        decisions_path,
        retry_errors=bool(getattr(args, "retry_errors", False)),
        target_execute=bool(args.execute),
    ) if bool(getattr(args, "resume", False)) else {}
    if previous:
        done_ids = set(previous)
        rows = [row for row in rows if text(row.get("cluster_id")) not in done_ids]
    resumable_rows = len(rows)
    if args.max_clusters and int(args.max_clusters) > 0:
        rows = rows[: int(args.max_clusters)]
    selected_rows = len(rows)
    api_key = os.environ.get(args.api_key_env, "")
    if args.execute and not api_key:
        raise RuntimeError(f"{args.api_key_env} is not configured")

    out_dir.mkdir(parents=True, exist_ok=True)
    if not bool(getattr(args, "resume", False)):
        decisions_path.write_text("", encoding="utf-8")
        errors_path.write_text("", encoding="utf-8")

    counts = Counter()
    for decision in previous.values():
        counts[f"decision:{decision.get('decision')}"] += 1
    completed_rows = 0
    submitted_rows = 0
    concurrency = max(1, int(getattr(args, "concurrency", 1) or 1))
    checkpoint_every = max(0, int(getattr(args, "checkpoint_every", 25) or 0))
    stop_error_rate = float(getattr(args, "stop_error_rate", 0.20) or 0.0)
    min_error_rate_check = max(1, int(getattr(args, "min_error_rate_check", 50) or 50))
    sleep_s = float(getattr(args, "sleep_s", 0.0) or 0.0)
    summary_path = out_dir / "entity_merge_deepseek_results_summary.json"

    def record(decision: dict[str, Any]) -> None:
        nonlocal completed_rows
        counts[f"decision:{decision.get('decision')}"] += 1
        completed_rows += 1
        append_jsonl(decisions_path, decision)
        if decision.get("decision") == "error":
            append_jsonl(errors_path, decision)

    def checkpoint(status: str, stop_reason: str = "") -> dict[str, Any]:
        summary = summary_payload(
            queue_path=queue_path,
            out_dir=out_dir,
            decisions_path=decisions_path,
            errors_path=errors_path,
            args=args,
            queue_rows=queue_rows,
            filtered_rows=filtered_rows,
            offset_rows=offset_rows,
            resumable_rows=resumable_rows,
            selected_rows=selected_rows,
            previous_count=len(previous),
            counts=counts,
            completed_rows=completed_rows,
            submitted_rows=submitted_rows,
            concurrency=concurrency,
            checkpoint_every=checkpoint_every,
            status=status,
            stop_reason=stop_reason,
        )
        write_json(summary_path, summary)
        return summary

    checkpoint("running" if rows else "complete")
    stopped = False
    stop_reason = ""

    def should_stop_for_error_rate() -> bool:
        if not stop_error_rate or completed_rows < min_error_rate_check:
            return False
        error_count = counts.get("decision:error", 0)
        return (error_count / completed_rows) > stop_error_rate

    if concurrency <= 1:
        for index, cluster in enumerate(rows):
            submitted_rows += 1
            record(decision_for_cluster(cluster, args, api_key))
            if checkpoint_every and completed_rows % checkpoint_every == 0:
                checkpoint("running")
            if should_stop_for_error_rate():
                stopped = True
                stop_reason = f"error_rate_exceeded:{counts.get('decision:error', 0)}/{completed_rows}"
                break
            if sleep_s > 0 and index < len(rows) - 1:
                time.sleep(sleep_s)
    else:
        iterator = iter(rows)
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            pending = set()

            def submit_next() -> bool:
                nonlocal submitted_rows
                try:
                    cluster = next(iterator)
                except StopIteration:
                    return False
                pending.add(executor.submit(decision_for_cluster, cluster, args, api_key))
                submitted_rows += 1
                if sleep_s > 0:
                    time.sleep(sleep_s)
                return True

            while len(pending) < concurrency and submit_next():
                pass
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    record(future.result())
                    if checkpoint_every and completed_rows % checkpoint_every == 0:
                        checkpoint("running")
                    if should_stop_for_error_rate():
                        stopped = True
                        stop_reason = f"error_rate_exceeded:{counts.get('decision:error', 0)}/{completed_rows}"
                        break
                if stopped:
                    for future in pending:
                        future.cancel()
                    break
                while len(pending) < concurrency and submit_next():
                    pass

    status = "stopped" if stopped else "complete"
    summary = checkpoint(status, stop_reason)
    write_json(out_dir / "entity_merge_deepseek_results_summary.json", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prompt-profile", choices=sorted(PROMPT_PROFILES), default="baseline")
    parser.add_argument("--system-prompt-path", default="")
    parser.add_argument("--block-key", default="")
    parser.add_argument("--cluster-id", default="")
    parser.add_argument("--skip-clusters", type=int, default=0)
    parser.add_argument("--max-clusters", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--require-full-cluster-merge", action="store_true")
    parser.add_argument("--sleep-s", type=float, default=0.0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--stop-error-rate", type=float, default=0.20)
    parser.add_argument("--min-error-rate-check", type=int, default=50)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-s", type=int, default=90)
    parser.add_argument("--request-retries", type=int, default=0)
    parser.add_argument("--retry-sleep-s", type=float, default=0.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = run(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
