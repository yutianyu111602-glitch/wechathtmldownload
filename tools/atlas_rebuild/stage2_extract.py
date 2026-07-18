"""Stage 2 — Multimodal structured extraction (pluggable backend).

For each cleaned article: feed clean_text + selected poster image(s) to a model,
get strict JSON validated against schema.ArticleExtraction. Provenance
(source_token, model_tier) is attached by THIS driver, not the model.

Backends (--backend): mock | local-vllm | mimo | deepseek | ocr_deepseek | stepfun | router_no_glm | vl_direct_router
  (see config.py)
  - mock        : offline stub, no GPU/API (validates plumbing)
  - local-vllm  : 4090 vLLM OpenAI server, guided_json (bulk tier)
  - mimo        : MiMo v2.5 multimodal (verified baseline / escalation tier)
  - deepseek    : text-only tier for route=text_complete
  - ocr_deepseek : local poster OCR followed by text-only DeepSeek extraction
  - stepfun     : StepFun Step 3.7 Flash VL canary only; not the bulk default
  - router_no_glm : legacy qwen-vl-ocr -> qwen-turbo -> qwen3-vl-flash -> MiMo v2.5 route
  - vl_direct_router : no-OCR route, qwen3-vl-flash -> MiMo v2.5, recommended for new 14w canaries

Routing: by default only route=needs_vision goes to a vision backend; pass
--route both to run everything. --escalate re-runs low-confidence items on
config.ESCALATE_BACKEND.

Usage:
  python stage2_extract.py --backend mock --limit 5
  python stage2_extract.py --backend router_no_glm --route needs_vision --limit 10
  python stage2_extract.py --backend vl_direct_router --route needs_vision --limit 10
  python stage2_extract.py --backend router_no_glm --route needs_vision --skip-failed
  python stage2_extract.py --backend local-vllm --route needs_vision --escalate
  python stage2_extract.py --backend local-vllm --rerun --limit 10   # force re-extract
"""
from __future__ import annotations
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
import sqlite3
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from schema import ArticleExtraction, SYSTEM_PROMPT, extraction_json_schema
from backends import get_backend

SCHEMA = """
CREATE TABLE IF NOT EXISTS extractions (
  token TEXT PRIMARY KEY,
  account_key TEXT, model_tier TEXT,
  valid INTEGER, event_count INTEGER, max_conf REAL,
  payload TEXT,        -- validated {events, entities, source_token, model_tier}
  error TEXT, ms INTEGER, status TEXT
);
CREATE INDEX IF NOT EXISTS ix_ext_conf ON extractions(max_conf);
CREATE INDEX IF NOT EXISTS ix_ext_status ON extractions(status);
"""


def build_user_text(title, clean_text, posters, source_published_at=""):
    lines = [f"公众号文章标题：{title}", ""]
    if source_published_at:
        lines.append(f"文章来源时间：{source_published_at}")
        lines.append(
            "时间解释规则：仅当标题、正文或海报明确出现“今天/今晚/本周”等相对时间时，"
            "才可用文章来源时间换算；不得把文章来源时间直接当作活动日期。"
        )
        lines.append("")
    if posters:
        ids = ", ".join(p["asset_id"] for p in posters)
        lines.append(f"附带 {len(posters)} 张海报图（顺序对应 {ids}）。请优先从海报读取演出信息。")
        lines.append("")
    lines.append("正文：")
    lines.append(clean_text or "(正文为空，信息以海报为准)")
    return "\n".join(lines)


def expand_failure_posters(poster_json, candidate_json, max_total):
    """Add high-ranked source candidates only for an explicit failure retry.

    The normal route remains limited to Stage1's SSD-staged poster selection.
    Failure recovery may read a small number of additional source assets so an
    early high-resolution portrait cannot hide a later, information-rich poster.
    """
    selected = json.loads(poster_json or "[]")
    if max_total <= 0:
        return selected
    seen = {str(item.get("asset_id") or "") for item in selected if isinstance(item, dict)}
    expanded = list(selected)
    for candidate in json.loads(candidate_json or "[]"):
        if len(expanded) >= max_total:
            break
        if not isinstance(candidate, dict):
            continue
        asset_id = str(candidate.get("asset_id") or "")
        path = str(candidate.get("path") or "")
        if not asset_id or asset_id in seen or not path or not os.path.isfile(path):
            continue
        expanded.append(candidate)
        seen.add(asset_id)
    return expanded


def _first_text(*values):
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    text = item.strip()
                    if text:
                        return text
    return None


def repair_entity_surfaces(raw):
    """Backfill required entity surface from common model-emitted name fields."""
    if not isinstance(raw, dict):
        return raw
    entities = raw.get("entities")
    if not isinstance(entities, dict):
        return raw
    for group in ("djs", "venues", "orgs", "series"):
        items = entities.get(group)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or _first_text(item.get("surface")):
                continue
            surface = _first_text(
                item.get("name"),
                item.get("name_zh"),
                item.get("name_en"),
                item.get("title"),
                item.get("label"),
                item.get("aliases"),
            )
            if surface:
                item["surface"] = surface
    return raw


def run_one(backend, schema_dict, title, clean_text, posters, source_published_at=""):
    img_paths = [p["path"] for p in posters] if backend.vision else []
    raw = backend.extract(
        SYSTEM_PROMPT,
        build_user_text(title, clean_text, posters, source_published_at),
        img_paths,
        schema_dict,
    )
    raw = repair_entity_surfaces(raw)
    obj = ArticleExtraction.model_validate(raw)          # liberal capture validation
    for ev in obj.events:                                # driver backfills missing title
        if not ev.title:
            ev.title = (title or "").strip() or "(untitled)"
    return obj


_THREAD_LOCAL = threading.local()


def _thread_backend(name: str):
    if getattr(_THREAD_LOCAL, "backend_name", None) != name:
        _THREAD_LOCAL.backend = get_backend(name)
        _THREAD_LOCAL.backend_name = name
    return _THREAD_LOCAL.backend


def _thread_escalation_backend(name: str):
    if getattr(_THREAD_LOCAL, "esc_backend_name", None) != name:
        _THREAD_LOCAL.esc_backend = get_backend(name)
        _THREAD_LOCAL.esc_backend_name = name
    return _THREAD_LOCAL.esc_backend


def extract_row(row_data, backend_name, esc_name, schema_dict):
    token, acct, title, source_published_at, clean_text, poster_json = row_data
    posters = json.loads(poster_json or "[]")
    t0 = time.time()
    tier = backend_name
    try:
        backend = _thread_backend(backend_name)
        obj = run_one(backend, schema_dict, title, clean_text, posters, source_published_at)
        max_conf = max([e.confidence for e in obj.events], default=0.0)
        prompt_tokens, completion_tokens = backend.last_usage
        if esc_name and max_conf < config.LOW_CONF_THRESHOLD:
            esc = _thread_escalation_backend(esc_name)
            obj = run_one(esc, schema_dict, title, clean_text, posters, source_published_at)
            tier = esc_name
            max_conf = max([e.confidence for e in obj.events], default=0.0)
            prompt_tokens += esc.last_usage[0]
            completion_tokens += esc.last_usage[1]
        payload = obj.model_dump()
        payload["source_token"] = token
        payload["model_tier"] = tier
        return {
            "token": token,
            "acct": acct,
            "tier": tier,
            "valid": 1,
            "event_count": len(obj.events),
            "max_conf": max_conf,
            "payload": json.dumps(payload, ensure_ascii=False),
            "error": "",
            "ms": int((time.time() - t0) * 1000),
            "status": "extracted",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    except Exception as e:
        return {
            "token": token,
            "acct": acct,
            "tier": tier,
            "valid": 0,
            "event_count": 0,
            "max_conf": 0.0,
            "payload": "",
            "error": f"{type(e).__name__}: {e}"[:500],
            "ms": int((time.time() - t0) * 1000),
            "status": "failed",
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="mock", choices=list(config.BACKENDS))
    ap.add_argument("--route", default="needs_vision", choices=["needs_vision", "text_complete", "both"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--escalate", action="store_true", help="re-run low-conf on ESCALATE_BACKEND")
    ap.add_argument("--rerun", action="store_true", help="include already extracted valid rows")
    ap.add_argument("--skip-failed", action="store_true", help="also skip existing failed rows during resume")
    ap.add_argument("--max-cost-rmb", type=float, default=0.0, help="global budget cap in RMB; stops with cost_halt when exceeded")
    ap.add_argument("--cost-per-article-rmb", type=float, default=0.0, help="cost estimate per article in RMB (default: 0.0017 for router_no_glm)")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("ATLAS_STAGE2_WORKERS", "1")),
                    help="parallel model calls; SQLite remains single-writer (default: 1)")
    ap.add_argument("--submit-delay-sec", type=float, default=float(os.environ.get("ATLAS_STAGE2_SUBMIT_DELAY_SEC", "-1")),
                    help="delay between parallel submissions; default 0.25 sec when workers>1")
    ap.add_argument(
        "--poster-candidate-fallback-count",
        type=int,
        default=0,
        help="failure-retry only: expand selected posters with ranked Stage1 candidates up to this total",
    )
    args = ap.parse_args()

    config.ensure_dirs()
    schema_dict = extraction_json_schema()
    workers = max(1, int(args.workers or 1))
    submit_delay = args.submit_delay_sec
    if submit_delay < 0:
        submit_delay = 0.25 if workers > 1 else 0.0
    if workers == 1:
        backend = get_backend(args.backend)
        esc = get_backend(config.ESCALATE_BACKEND) if args.escalate and config.ESCALATE_BACKEND != args.backend else None
    else:
        backend = None
        esc = None
    esc_name = config.ESCALATE_BACKEND if args.escalate and config.ESCALATE_BACKEND != args.backend else ""
    backend_vision = bool(config.BACKENDS[args.backend].get("vision", False)) if backend is None else backend.vision

    clean = sqlite3.connect(config.DB_CLEAN)
    con = sqlite3.connect(config.DB_EXTRACT)
    con.executescript(SCHEMA)
    existing = set()
    if not args.rerun:
        where = "status='extracted' AND valid=1"
        if args.skip_failed:
            where = f"({where}) OR status='failed'"
        existing = {
            row[0]
            for row in con.execute(
                f"SELECT token FROM extractions WHERE {where}"
            ).fetchall()
        }

    # Query with classification columns (defensive: detect if ALL required cols exist)
    clean_cols = {row[1] for row in clean.execute("PRAGMA table_info(clean)").fetchall()}
    _required_classification_cols = {
        "article_type", "should_process_text", "should_process_images", "image_route_reason"
    }
    has_classification = _required_classification_cols.issubset(clean_cols)
    source_published_expr = "source_published_at" if "source_published_at" in clean_cols else "''"
    candidate_expr = "poster_candidates_json" if "poster_candidates_json" in clean_cols else "'[]'"
    extra_cols = ", article_type, should_process_text, should_process_images, image_route_reason" if has_classification else ""
    q = (
        f"SELECT token, account_key, title, {source_published_expr}, clean_text, "
        f"poster_json, {candidate_expr}{extra_cols} FROM clean"
    )
    if args.route != "both":
        q += f" WHERE route = '{args.route}'"
    rows = clean.execute(q).fetchall()

    ok = fail = skipped = classification_skipped = attempted = 0
    tot_p = tot_c = 0
    spent_rmb = 0.0
    # Auto-derive cost-per-article when unset and using a known production backend
    cost_per = args.cost_per_article_rmb
    if cost_per <= 0 and args.backend in ("router_no_glm", "vl_direct_router"):
        cost_per = 0.0017   # measured: ¥111/66k articles
    if cost_per <= 0 and args.backend in ("mimo", "local-vllm", "deepseek", "ocr_deepseek"):
        cost_per = 0.0017   # safe default for any real backend; mock overrides to whatever
    if not args.rerun and args.max_cost_rmb > 0 and cost_per > 0 and args.backend != "mock":
        already_costed = con.execute(
            "SELECT COUNT(*) FROM extractions WHERE model_tier=? AND status IN ('extracted','failed')",
            (args.backend,),
        ).fetchone()[0]
        spent_rmb = already_costed * cost_per
    def write_result(result):
        con.execute(
            "INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                result["token"],
                result["acct"],
                result["tier"],
                result["valid"],
                result["event_count"],
                result["max_conf"],
                result["payload"],
                result["error"],
                result["ms"],
                result["status"],
            ),
        )
        con.commit()

    def apply_result(result, precharged: bool):
        nonlocal ok, fail, spent_rmb, tot_p, tot_c
        write_result(result)
        if result["status"] == "extracted":
            ok += 1
            if not precharged:
                spent_rmb += cost_per
            tot_p += result["prompt_tokens"]
            tot_c += result["completion_tokens"]
        elif result["status"] == "failed":
            fail += 1
            if not precharged:
                spent_rmb += cost_per

    futures = set()
    executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
    budget_stopped = False
    max_in_flight = max(workers * 2, 1)

    def drain_completed(done):
        for fut in done:
            apply_result(fut.result(), precharged=True)

    for row in rows:
        if has_classification:
            (token, acct, title, source_published_at, clean_text, poster_json,
             poster_candidates_json, article_type, should_proc_text,
             should_proc_images, img_route_reason) = row
        else:
            token, acct, title, source_published_at, clean_text, poster_json, poster_candidates_json = row
            article_type = should_proc_text = should_proc_images = img_route_reason = None
        if token in existing:
            skipped += 1
            continue
        if args.limit and attempted >= args.limit:
            break
        attempted += 1

        # Classification-based routing guard
        if has_classification and backend_vision and not should_proc_images:
            classification_skipped += 1
            t0 = time.time()
            con.execute(
                "INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (token, acct, args.backend, 1, 0, 0.0,
                 json.dumps({"source_token": token, "model_tier": args.backend, "events": [],
                             "classification_skip": True,
                             "article_type": article_type,
                             "image_route_reason": img_route_reason},
                            ensure_ascii=False),
                 "", int((time.time()-t0)*1000), "classification_skip"),
            )
            con.commit()
            continue
        if has_classification and not backend_vision and not should_proc_text:
            classification_skipped += 1
            t0 = time.time()
            con.execute(
                "INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (token, acct, args.backend, 1, 0, 0.0,
                 json.dumps({"source_token": token, "model_tier": args.backend, "events": [],
                             "classification_skip": True,
                             "article_type": article_type,
                             "image_route_reason": img_route_reason},
                            ensure_ascii=False),
                 "", int((time.time()-t0)*1000), "classification_skip"),
            )
            con.commit()
            continue

        # Budget gate runs before every real model call. In parallel mode we
        # reserve the estimated article cost before submitting the request.
        if args.max_cost_rmb > 0 and spent_rmb + cost_per > args.max_cost_rmb:
            t0 = time.time()
            con.execute(
                "INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (token, acct, args.backend, 0, 0, 0.0,
                 "", f"cost_halt: spent={spent_rmb:.4f} + est_next={cost_per:.4f} > cap={args.max_cost_rmb:.4f}",
                 int((time.time()-t0)*1000), "cost_halt"),
            )
            con.commit()
            print(f"BUDGET STOP: spent RMB {spent_rmb:.4f} + next {cost_per:.4f} > cap {args.max_cost_rmb:.4f} -> cost_halt, remaining articles skipped")
            budget_stopped = True
            break

        posters = expand_failure_posters(
            poster_json,
            poster_candidates_json,
            max(0, int(args.poster_candidate_fallback_count or 0)),
        )
        row_data = (
            token,
            acct,
            title,
            source_published_at,
            clean_text,
            json.dumps(posters, ensure_ascii=False),
        )
        if executor is None:
            apply_result(extract_row(row_data, args.backend, esc_name, schema_dict), precharged=False)
        else:
            spent_rmb += cost_per
            futures.add(executor.submit(extract_row, row_data, args.backend, esc_name, schema_dict))
            if len(futures) >= max_in_flight:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                drain_completed(done)
            if submit_delay > 0:
                time.sleep(submit_delay)

    if executor is not None:
        try:
            while futures:
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                drain_completed(done)
        finally:
            executor.shutdown(wait=True)
    if budget_stopped and futures:
        print(f"  in-flight parallel requests completed before exit: {len(futures)}")
    cost_halted = con.execute(
        "SELECT COUNT(*) FROM extractions WHERE status='cost_halt'").fetchone()
    con.close(); clean.close()
    print(f"Stage2 done [{args.backend}]: ok={ok} fail={fail} skipped={skipped} classification_skipped={classification_skipped}")
    if ok and (tot_p or tot_c):
        avg = (tot_p + tot_c) / ok
        print(f"  tokens: prompt={tot_p} completion={tot_c} total={tot_p + tot_c} avg/article={avg:.0f}")
        print(f"  project 66020 articles: ~{avg * 66020 / 1e6:.1f}M tokens")
    if args.max_cost_rmb > 0 or cost_per > 0:
        print(f"  cost: spent_rmb={spent_rmb:.4f} per_article={cost_per:.4f} cap={args.max_cost_rmb:.4f} cost_halted={cost_halted[0] if cost_halted else 0}")
    print(f"  -> {config.DB_EXTRACT}")


if __name__ == "__main__":
    main()
