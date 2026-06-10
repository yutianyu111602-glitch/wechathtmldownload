#!/usr/bin/env python3
"""Run DeepSeek adjudication over the Atlas participant LLM queue.

The runner consumes the private queue produced by
``build_atlas_participant_llm_adjudication_queue.py`` and writes decisions to a
sidecar only. It never mutates the source Atlas SQLite or the public serving DB.
Use ``--execute`` to make live DeepSeek API calls; without it the script is a
dry-run prompt/package validator.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEMA_VERSION = "atlas_participant_llm_adjudication_results.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_llm_adjudication_queue_v2_20260522"
    / "participant_llm_queue.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_participant_llm_adjudication_results_v2_20260522"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_TIMEOUT_S = 90
DEFAULT_MAX_TOKENS = 900
DEFAULT_TEMPERATURE = 0.0


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def parse_json(value: Any, default: Any) -> Any:
    raw = text(value)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def open_queue_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create_results_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS participant_llm_decision (
            queue_id TEXT PRIMARY KEY,
            llm_lane TEXT,
            source_article_uid TEXT,
            event_id TEXT,
            event_name TEXT,
            model TEXT,
            decision TEXT,
            confidence REAL,
            accepted_participants_json TEXT,
            rejected_candidates_json TEXT,
            public_graph_ready INTEGER,
            relationship_basis TEXT,
            evidence_quote TEXT,
            risk_flags_json TEXT,
            reasoning_zh TEXT,
            raw_response_json TEXT,
            prompt_chars INTEGER,
            latency_ms REAL,
            usage_json TEXT,
            error TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS adjudication_run (
            run_id TEXT PRIMARY KEY,
            started_at TEXT,
            finished_at TEXT,
            schema_version TEXT,
            queue_db TEXT,
            model TEXT,
            execute INTEGER,
            summary_json TEXT,
            safety_json TEXT
        )
        """
    )
    return conn


def existing_decisions(conn: sqlite3.Connection) -> set[str]:
    try:
        return {text(row["queue_id"]) for row in conn.execute("SELECT queue_id FROM participant_llm_decision")}
    except sqlite3.OperationalError:
        return set()


def iter_queue_rows(
    queue_conn: sqlite3.Connection,
    *,
    lanes: set[str],
    max_rows: int | None,
    skip_queue_ids: set[str],
) -> Iterable[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if lanes:
        placeholders = ",".join("?" for _ in lanes)
        where.append(f"q.llm_lane IN ({placeholders})")
        params.extend(sorted(lanes))
    sql = """
        SELECT q.*, c.article_text_excerpt, c.article_vector_text,
               c.post_date, c.source_hash, c.raw_html_text_available,
               c.source_url_available, c.context_chars
        FROM participant_llm_queue q
        LEFT JOIN article_context c ON c.article_context_id = q.article_context_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY q.priority_score DESC, q.queue_id"
    emitted = 0
    for row in queue_conn.execute(sql, params):
        item = row_dict(row)
        queue_id = text(item.get("queue_id"))
        if queue_id in skip_queue_ids:
            continue
        yield item
        emitted += 1
        if max_rows is not None and emitted >= max_rows:
            break


SYSTEM_PROMPT = """你是中国地下电子音乐 Atlas 的 DJ 历史演出数据裁决器。
目标：从公开文章证据中判断某场活动的真实 DJ/artist 参与者。

严格规则：
1. 只接受能被活动标题、活动段落、lineup/阵容/嘉宾/with/b2b 等上下文支持的人名或艺名。
2. 同一篇文章共同出现但不是该活动 lineup，只能判 same_article_only，不能进 public graph。
3. 场地、厂牌、电台、酒水、菜单、票价、城市、概念词不能当 DJ 参与者。
   已知非 DJ 主体包括但不限于：OIL, ALL, DADA, TAG, SHCR, BYYB, BAIHUI, CDCR,
   BO LIVE, Elevator, THE WINDOW, EchoBay, AXIS, JAR, FOUNDATION, SYSTEM, ZhaoDai,
   Heim, Hum, 44KW, POTENT。除非上下文明示它是 DJ/artist 艺名，否则必须拒绝。
4. 如果 event_name 本身只是票务/行政/报名/福利/场地通知片段，例如“预售”“预售截止”“早鸟”
   “门票”“购票”“报名”“福利”“抽奖”“入场须知”“观演须知”“场地更换”，不能把它当演出活动节点。
   即使标题里出现艺人名，也必须 reject 或 needs_more_context，并且 public_graph_ready=false。
5. 一字名、明显标题残片、票务词、城市/场地词不能当参与者。
6. 不确定就 needs_more_context 或 reject；不要为了补全而编造。
7. 输出必须是严格 JSON object，不要 Markdown，不要解释性正文。

JSON schema:
{
  "decision":"accept|reject|needs_more_context",
  "confidence":0.0,
  "accepted_participants":["DJ/artist name"],
  "rejected_candidates":["name"],
  "relationship_basis":"same_event|lineup_text|same_article_only|not_participant|insufficient_context",
  "public_graph_ready":false,
  "evidence_quote":"不超过120字的证据片段",
  "risk_flags":["ambiguous_name"],
  "reasoning_zh":"不超过160字中文说明"
}"""


def build_prompt(row: dict[str, Any]) -> str:
    candidate_names = parse_json(row.get("candidate_names_json"), [])
    same_article_entities = parse_json(row.get("same_article_entities_json"), [])
    decision_schema = parse_json(row.get("decision_schema_json"), {})
    basis = parse_json(row.get("basis_json"), {})
    article_text = text(row.get("article_text_excerpt")) or text(row.get("article_vector_text"))
    event_text = text(row.get("event_vector_text"))
    lane = text(row.get("llm_lane"))
    task = (
        "判断候选名单是否为这场活动的真实参与 DJ/artist。"
        if lane != "llm_reextract_no_candidate"
        else "没有候选名单，请从文章上下文为这场活动抽取真实 DJ/artist 参与者。"
    )
    payload = {
        "task": task,
        "llm_lane": lane,
        "event": {
            "name": text(row.get("event_name")),
            "time_text": text(row.get("time_text")),
            "place": text(row.get("place")),
            "city": text(row.get("city")),
            "event_vector_text": event_text,
        },
        "source": {
            "account": text(row.get("source_account")),
            "title": text(row.get("source_title")),
            "post_date": text(row.get("post_date")),
            "source_hash": text(row.get("source_hash")),
            "raw_html_text_available": bool(row.get("raw_html_text_available")),
        },
        "candidate_names": candidate_names,
        "same_article_dj_person_entities": same_article_entities[:80],
        "sidecar_basis": basis,
        "expected_decision_schema": decision_schema,
        "article_context_excerpt": article_text[:10000],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def endpoint_from_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def call_deepseek(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout_s: int,
    max_retries: int,
    retry_backoff_s: float,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    if model.startswith("deepseek-v4"):
        payload["thinking"] = {"type": "disabled"}
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    endpoint = endpoint_from_base(base_url)
    last_error = ""
    started = time.monotonic()
    for attempt in range(max_retries + 1):
        request = Request(
            endpoint,
            data=encoded,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_s) as response:
                body = json.loads(response.read().decode("utf-8"))
            choice = (body.get("choices") or [{}])[0]
            content = text((choice.get("message") or {}).get("content"))
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = {"decision": "needs_more_context", "parse_error": True, "raw": content[:1000]}
            return {
                "parsed": parsed if isinstance(parsed, dict) else {"raw": content[:1000]},
                "model": body.get("model", model),
                "usage": body.get("usage") or {},
                "finish_reason": choice.get("finish_reason"),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "error": "",
            }
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:400]}"
        except URLError as exc:
            last_error = f"URL error: {exc.reason}"
        except Exception as exc:  # pragma: no cover - network edge.
            last_error = str(exc)[:400]
        if attempt < max_retries:
            time.sleep(retry_backoff_s * (attempt + 1))
    return {
        "parsed": {},
        "model": model,
        "usage": {},
        "finish_reason": "",
        "latency_ms": round((time.monotonic() - started) * 1000, 2),
        "error": last_error,
    }


def dry_run_decision(row: dict[str, Any], prompt: str) -> dict[str, Any]:
    return {
        "parsed": {
            "decision": "dry_run",
            "confidence": 0.0,
            "accepted_participants": [],
            "rejected_candidates": parse_json(row.get("candidate_names_json"), []),
            "relationship_basis": "dry_run",
            "public_graph_ready": False,
            "evidence_quote": "",
            "risk_flags": ["dry_run_no_model_call"],
            "reasoning_zh": "dry-run 只校验输入包和 prompt，不调用模型。",
        },
        "model": "dry-run",
        "usage": {},
        "finish_reason": "dry_run",
        "latency_ms": 0.0,
        "error": "",
        "prompt_chars": len(prompt),
    }


def normalize_decision(raw: dict[str, Any], row: dict[str, Any], prompt_chars: int) -> dict[str, Any]:
    parsed = raw.get("parsed") or {}
    accepted = parsed.get("accepted_participants")
    rejected = parsed.get("rejected_candidates")
    risks = parsed.get("risk_flags")
    if not isinstance(accepted, list):
        accepted = []
    if not isinstance(rejected, list):
        rejected = []
    if not isinstance(risks, list):
        risks = []
    decision = text(parsed.get("decision")) or ("error" if raw.get("error") else "needs_more_context")
    confidence = parsed.get("confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0
    public_ready = bool(parsed.get("public_graph_ready")) and decision == "accept" and bool(accepted)
    return {
        "queue_id": text(row.get("queue_id")),
        "llm_lane": text(row.get("llm_lane")),
        "source_article_uid": text(row.get("source_article_uid")),
        "event_id": text(row.get("event_id")),
        "event_name": text(row.get("event_name")),
        "model": text(raw.get("model")),
        "decision": decision,
        "confidence": max(0.0, min(1.0, confidence_value)),
        "accepted_participants_json": json_dumps([text(item) for item in accepted if text(item)]),
        "rejected_candidates_json": json_dumps([text(item) for item in rejected if text(item)]),
        "public_graph_ready": 1 if public_ready else 0,
        "relationship_basis": text(parsed.get("relationship_basis")),
        "evidence_quote": text(parsed.get("evidence_quote"))[:240],
        "risk_flags_json": json_dumps([text(item) for item in risks if text(item)]),
        "reasoning_zh": text(parsed.get("reasoning_zh"))[:320],
        "raw_response_json": json_dumps(parsed),
        "prompt_chars": prompt_chars,
        "latency_ms": float(raw.get("latency_ms") or 0.0),
        "usage_json": json_dumps(raw.get("usage") or {}),
        "error": text(raw.get("error")),
        "created_at": now_iso(),
    }


def insert_decision(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO participant_llm_decision (
            queue_id, llm_lane, source_article_uid, event_id, event_name,
            model, decision, confidence, accepted_participants_json,
            rejected_candidates_json, public_graph_ready, relationship_basis,
            evidence_quote, risk_flags_json, reasoning_zh, raw_response_json,
            prompt_chars, latency_ms, usage_json, error, created_at
        )
        VALUES (
            :queue_id, :llm_lane, :source_article_uid, :event_id, :event_name,
            :model, :decision, :confidence, :accepted_participants_json,
            :rejected_candidates_json, :public_graph_ready, :relationship_basis,
            :evidence_quote, :risk_flags_json, :reasoning_zh, :raw_response_json,
            :prompt_chars, :latency_ms, :usage_json, :error, :created_at
        )
        """,
        row,
    )


def process_one(row: dict[str, Any], args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    prompt = build_prompt(row)
    if not args.execute:
        raw = dry_run_decision(row, prompt)
    else:
        raw = call_deepseek(
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            prompt=prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            timeout_s=args.timeout_s,
            max_retries=args.max_retries,
            retry_backoff_s=args.retry_backoff_s,
        )
        raw["prompt_chars"] = len(prompt)
    return normalize_decision(raw, row, len(prompt))


def run(args: argparse.Namespace) -> dict[str, Any]:
    queue_db = Path(args.queue_db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_db = out_dir / "participant_llm_decisions.sqlite"
    jsonl_path = out_dir / "participant_llm_decisions.jsonl"
    if args.reset and results_db.exists():
        results_db.unlink()
    if args.reset and jsonl_path.exists():
        jsonl_path.unlink()

    queue_conn = open_queue_db(queue_db)
    results_conn = create_results_db(results_db)
    run_id = f"participant_llm_run:{int(time.time())}"
    started_at = now_iso()
    api_key = text(os.environ.get(args.api_key_env))
    if args.execute and not api_key:
        raise SystemExit(f"{args.api_key_env} is not set; refusing live LLM call.")
    lanes = {lane.strip() for lane in args.lanes.split(",") if lane.strip()}
    skip = existing_decisions(results_conn) if args.resume else set()
    rows = iter_queue_rows(queue_conn, lanes=lanes, max_rows=args.max_rows, skip_queue_ids=skip)

    counters: Counter = Counter()
    safety = {
        "report_only_sidecar": True,
        "execute_llm_calls": bool(args.execute),
        "source_sqlite_write_executed": False,
        "production_write_executed": False,
        "graph_vector_write_executed": False,
        "deploy_or_upload_executed": False,
        "api_key_printed": False,
    }

    def handle_result(decision: dict[str, Any]) -> None:
        insert_decision(results_conn, decision)
        append_jsonl(jsonl_path, decision)
        counters["rows"] += 1
        counters[f"decision:{decision['decision']}"] += 1
        counters[f"lane:{decision['llm_lane']}"] += 1
        if decision["public_graph_ready"]:
            counters["public_graph_ready"] += 1
        if decision["error"]:
            counters["errors"] += 1
        if counters["rows"] % args.commit_every == 0:
            results_conn.commit()

    pending = set()
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            for row in rows:
                pending.add(executor.submit(process_one, row, args, api_key))
                if len(pending) >= max(1, args.workers) * 2:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        handle_result(future.result())
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    handle_result(future.result())
        results_conn.commit()
    finally:
        finished_at = now_iso()
        summary = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "queue_db": str(queue_db),
            "results_db": str(results_db),
            "results_jsonl": str(jsonl_path),
            "model": args.model if args.execute else "dry-run",
            "execute": bool(args.execute),
            "max_rows": args.max_rows,
            "workers": args.workers,
            "lanes": sorted(lanes),
            "counts": dict(counters),
            "safety": safety,
        }
        results_conn.execute(
            """
            INSERT OR REPLACE INTO adjudication_run (
                run_id, started_at, finished_at, schema_version, queue_db,
                model, execute, summary_json, safety_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                started_at,
                finished_at,
                SCHEMA_VERSION,
                str(queue_db),
                args.model if args.execute else "dry-run",
                1 if args.execute else 0,
                json_dumps(summary),
                json_dumps(safety),
            ),
        )
        results_conn.commit()
        results_conn.close()
        queue_conn.close()
    write_json(out_dir / "summary.json", summary)
    write_summary_md(out_dir / "summary.md", summary)
    return summary


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    counts = summary.get("counts") or {}
    lines = [
        "# Atlas Participant LLM Adjudication Results V2",
        "",
        f"Started: `{summary['started_at']}`",
        f"Finished: `{summary['finished_at']}`",
        f"Mode: `{'execute' if summary['execute'] else 'dry-run'}`",
        f"Model: `{summary['model']}`",
        "",
        "## Counts",
        "",
        f"- Rows processed: `{counts.get('rows', 0)}`",
        f"- Public-graph-ready accepted rows: `{counts.get('public_graph_ready', 0)}`",
        f"- Errors: `{counts.get('errors', 0)}`",
        "",
        "## Decisions",
        "",
    ]
    for key, value in sorted(counts.items()):
        if key.startswith("decision:"):
            lines.append(f"- `{key.removeprefix('decision:')}`: `{value}`")
    lines.extend(["", "## Lanes", ""])
    for key, value in sorted(counts.items()):
        if key.startswith("lane:"):
            lines.append(f"- `{key.removeprefix('lane:')}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Results are sidecar-only.",
            "- Source Atlas SQLite and public serving DB are not mutated.",
            "- No graph/vector write, deploy, or upload is performed.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-db", default=str(DEFAULT_QUEUE_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--max-rows", type=int, default=20)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--lanes", default="")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-s", type=float, default=2.0)
    parser.add_argument("--commit-every", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    summary = run(parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
