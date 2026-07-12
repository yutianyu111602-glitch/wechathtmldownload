#!/usr/bin/env python3
"""Adjudicate weak-key merge candidates into a persistent decision store (W1: deterministic tiers).

Plan: `C:\\code\\mavelpoint-cn-v2\\docs\\site-clone\\ATLAS_V2_WEAK_KEY_AND_COUNT_CONVERGENCE_PLAN_2026-07-08.md` §2.

Reads `canonical_event_merge_review_candidate` pairs from a Phase 3 candidate DB and writes
one decision row per pair into a sidecar decision store keyed by a run-stable `pair_key`
(`event_date|venue_id|sorted(title_norm_a,title_norm_b)`) — canonical_event_ids change
between runs, the pair_key does not, so nightly reruns only ever adjudicate NEW pairs.

Deterministic tiers implemented here (W1):
  BLOCK  conflicting explicit dates in the two titles      -> keep_separate (0.99)
  BLOCK  room/floor/stage or session-word mismatch          -> keep_separate (0.95)
  A      punctuation/space/emoji-insensitive title equality -> merge (0.99)
  B1     containment where the longer title's extra tokens are ALL safe decorations
         (a date matching event_date, weekday words, the venue's own name)  -> merge (0.95)
  B2/C/D everything else                                    -> pending_llm (W3 takes these)

Never merges anything itself — only records decisions. Application happens in
build_canonical_event_candidates.py --merge-decisions-db (W4).

Usage:
  python adjudicate_weak_key_candidates.py --candidates-db <phase3.sqlite> --decisions-db <store.sqlite>
  python adjudicate_weak_key_candidates.py --self-check
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE7_SCRIPTS = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
if str(STAGE7_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(STAGE7_SCRIPTS))

from build_atlas_dj_first_canary import norm_key, norm_text, now_iso, write_json  # noqa: E402

SCHEMA_VERSION = "atlas_v2_weak_key_decision.v1"
DEFAULT_DECISIONS_DB = Path(r"E:\atlas_v2_import_runs\weak_key_decisions.sqlite")

RE_TITLE_DATE = re.compile(r"(\d{1,2})\s*[月./]\s*(\d{1,2})\s*[日号]?")
RE_WEEKDAY = re.compile(r"周[一二三四五六日天]|星期[一二三四五六日天]|礼拜[一二三四五六日天]|\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.IGNORECASE)
RE_ROOM = re.compile(r"room\s*\d|(?:^|\D)[b]\d(?:\D|$)|\d+\s*楼|\d+\s*层|[二三四]号?厅|stage\s*[a-z0-9]", re.IGNORECASE)
SESSION_WORDS = ("午夜场", "早场", "日场", "夜场", "下午场", "白天场", "通宵场")


def agg_norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in ("L", "N"))


def title_dates(text: str) -> set[tuple[int, int]]:
    out = set()
    for m in RE_TITLE_DATE.finditer(text or ""):
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.add((mo, d))
    return out


def room_session_signature(text: str) -> tuple[frozenset[str], frozenset[str]]:
    rooms = frozenset(agg_norm(m.group(0)) for m in RE_ROOM.finditer(text or ""))
    sessions = frozenset(w for w in SESSION_WORDS if w in (text or ""))
    return rooms, sessions


def event_date_month_day(event_date: str) -> tuple[int, int] | None:
    try:
        return int(event_date[5:7]), int(event_date[8:10])
    except (ValueError, IndexError):
        return None


def tokenize_display(text: str) -> list[str]:
    """Split a display title into content tokens: contiguous runs of letters/numbers
    (NFKC+casefolded). CJK characters become single-char tokens so partial word overlap
    doesn't hide extra content."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    tokens: list[str] = []
    current = ""
    for ch in text:
        cat = unicodedata.category(ch)[0]
        if cat in ("L", "N"):
            if unicodedata.east_asian_width(ch) in ("W", "F") and not ch.isdigit():
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(ch)
            else:
                current += ch
        else:
            if current:
                tokens.append(current)
                current = ""
    if current:
        tokens.append(current)
    return tokens


def extra_tokens_are_safe(
    extra: list[str],
    event_date: str,
    venue_token_pool: set[str],
    longer_display: str,
) -> bool:
    """True when every extra token in the longer title is a safe decoration."""
    md = event_date_month_day(event_date)
    matched_dates = title_dates(longer_display)
    weekday_blob = agg_norm(" ".join(m.group(0) for m in RE_WEEKDAY.finditer(longer_display)))

    i = 0
    while i < len(extra):
        token = extra[i]
        if token in venue_token_pool:
            i += 1
            continue
        if token in weekday_blob and not token.isdigit():
            i += 1
            continue
        if token.isdigit():
            # digits are safe only when they belong to a date matching the event_date
            if md and md in matched_dates and int(token) in (md[0], md[1]):
                i += 1
                continue
            return False
        # single CJK chars composing weekday words already covered above; anything else is content
        return False
    return True


def classify_pair(
    event_date: str,
    a_display: str,
    b_display: str,
    similarity: float,
    venue_token_pool: set[str],
) -> tuple[str, str, float, str]:
    """Returns (tier, decision, confidence, reason)."""
    dates_a, dates_b = title_dates(a_display), title_dates(b_display)
    if dates_a and dates_b and not (dates_a & dates_b):
        return "block_conflicting_dates", "keep_separate", 0.99, f"explicit dates disagree: {sorted(dates_a)} vs {sorted(dates_b)}"

    rooms_a, sessions_a = room_session_signature(a_display)
    rooms_b, sessions_b = room_session_signature(b_display)
    if rooms_a != rooms_b or sessions_a != sessions_b:
        return "block_room_session", "keep_separate", 0.95, f"room/session mismatch: {sorted(rooms_a | sessions_a)} vs {sorted(rooms_b | sessions_b)}"

    na, nb = agg_norm(a_display), agg_norm(b_display)
    if na and na == nb:
        return "a_norm_equal", "merge", 0.99, "titles identical after punctuation/space/symbol normalization"

    if na and nb and (na in nb or nb in na):
        shorter_display, longer_display = (a_display, b_display) if len(na) <= len(nb) else (b_display, a_display)
        shorter_tokens = Counter(tokenize_display(shorter_display))
        longer_tokens = Counter(tokenize_display(longer_display))
        extra = list((longer_tokens - shorter_tokens).elements())
        if extra_tokens_are_safe(extra, event_date, venue_token_pool, longer_display):
            return "b1_safe_containment", "merge", 0.95, f"extra tokens all safe decorations: {extra}"
        return "b2_containment", "pending_llm", 0.0, f"containment with content extra tokens: {extra[:8]}"

    if similarity >= 0.92:
        return "c_high_sim", "pending_llm", 0.0, f"similarity {similarity}"
    return "d_low_sim", "pending_llm", 0.0, f"similarity {similarity}"


def ensure_store(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS weak_key_merge_decision (
          pair_key TEXT PRIMARY KEY,
          event_date TEXT,
          venue_id TEXT,
          title_norm_a TEXT,
          title_norm_b TEXT,
          title_display_a TEXT,
          title_display_b TEXT,
          title_similarity REAL,
          tier TEXT,
          decision TEXT,
          method TEXT,
          confidence REAL,
          reason TEXT,
          llm_verdict_raw TEXT,
          decided_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_wkd_decision ON weak_key_merge_decision(decision);
        CREATE INDEX IF NOT EXISTS idx_wkd_tier ON weak_key_merge_decision(tier);
        """
    )


def make_pair_key(event_date: str, venue_id: str, title_norm_a: str, title_norm_b: str) -> str:
    lo, hi = sorted((title_norm_a, title_norm_b))
    return f"{event_date}|{venue_id}|{lo}|{hi}"


def adjudicate(candidates_db: Path, decisions_db: Path, report_path: Path | None) -> dict[str, Any]:
    src = sqlite3.connect(f"file:{candidates_db.resolve().as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        """
        SELECT r.*, ca.title_norm AS title_norm_a, cb.title_norm AS title_norm_b,
               ca.venue_name AS venue_name_a, cb.venue_name AS venue_name_b
        FROM canonical_event_merge_review_candidate r
        JOIN canonical_event ca ON ca.canonical_event_id = r.canonical_event_id_a
        JOIN canonical_event cb ON cb.canonical_event_id = r.canonical_event_id_b
        """
    ).fetchall()
    src.close()

    decisions_db.parent.mkdir(parents=True, exist_ok=True)
    store = sqlite3.connect(str(decisions_db))
    ensure_store(store)
    existing = {r[0] for r in store.execute("SELECT pair_key FROM weak_key_merge_decision")}

    counts: Counter[str] = Counter()
    counts["input_pairs"] = len(rows)
    inserted: list[tuple] = []
    seen_this_run: set[str] = set()

    for r in rows:
        pair_key = make_pair_key(r["event_date"], r["venue_id"], r["title_norm_a"], r["title_norm_b"])
        if pair_key in existing or pair_key in seen_this_run:
            counts["already_decided_or_duplicate"] += 1
            continue
        seen_this_run.add(pair_key)

        venue_token_pool = set(tokenize_display(r["venue_name_a"])) | set(tokenize_display(r["venue_name_b"]))
        tier, decision, confidence, reason = classify_pair(
            r["event_date"], r["title_display_a"], r["title_display_b"], r["title_similarity"], venue_token_pool
        )
        counts[f"tier_{tier}"] += 1
        counts[f"decision_{decision}"] += 1
        inserted.append(
            (
                pair_key, r["event_date"], r["venue_id"], r["title_norm_a"], r["title_norm_b"],
                r["title_display_a"], r["title_display_b"], r["title_similarity"],
                tier, decision, "deterministic" if decision != "pending_llm" else "",
                confidence, reason, "", now_iso() if decision != "pending_llm" else "",
            )
        )

    store.executemany(
        "INSERT INTO weak_key_merge_decision VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", inserted
    )
    store.commit()
    counts["newly_inserted"] = len(inserted)
    totals = dict(store.execute("SELECT decision, COUNT(*) FROM weak_key_merge_decision GROUP BY decision").fetchall())
    store.close()

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "candidates_db": str(candidates_db),
        "decisions_db": str(decisions_db),
        "run_counts": dict(counts),
        "store_totals_by_decision": totals,
    }
    if report_path:
        write_json(report_path, report)
    return report


def _self_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cdb = tmp_path / "phase3.sqlite"
        conn = sqlite3.connect(str(cdb))
        conn.executescript(
            """
            CREATE TABLE canonical_event (
              canonical_event_id TEXT PRIMARY KEY, event_date TEXT, start_time TEXT, venue_id TEXT,
              venue_name TEXT, city_norm TEXT, title_norm TEXT, title_display TEXT,
              merge_key_strong TEXT, merge_key_medium TEXT, confidence REAL, status TEXT,
              member_count INTEGER, created_at TEXT, merge_version TEXT
            );
            CREATE TABLE canonical_event_merge_review_candidate (
              canonical_event_id_a TEXT, canonical_event_id_b TEXT, event_date TEXT, venue_id TEXT,
              title_display_a TEXT, title_display_b TEXT, title_similarity REAL, review_state TEXT
            );
            """
        )

        def add_pair(idx, date, venue_name, disp_a, disp_b, sim):
            ida, idb = f"ce{idx}a", f"ce{idx}b"
            for cid, disp in ((ida, disp_a), (idb, disp_b)):
                conn.execute(
                    "INSERT INTO canonical_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, date, "", "venue1", venue_name, "shanghai", norm_key(disp), disp, "k", "", 0.9, "active", 2, "", "v"),
                )
            conn.execute(
                "INSERT INTO canonical_event_merge_review_candidate VALUES (?,?,?,?,?,?,?,?)",
                (ida, idb, date, "venue1", disp_a, disp_b, sim, "needs_review"),
            )
            return norm_key(disp_a), norm_key(disp_b)

        # 1: conflicting dates -> BLOCK keep_separate
        add_pair(1, "2026-10-23", "JAR", "JAR SELECT 10.23", "JAR SELECT 10.24", 0.95)
        # 2: norm-equal -> A merge
        add_pair(2, "2026-12-31", "Venue One", "NYE跨年夜", "NYE 跨年夜!", 0.92)
        # 3: safe containment (date prefix matches event_date + weekday) -> B1 merge
        add_pair(3, "2026-12-14", "Venue One", "12.14 周六 A.D.H.D 高速节拍", "A.D.H.D 高速节拍", 0.86)
        # 4: containment with real content extra token -> B2 pending_llm
        add_pair(4, "2026-12-14", "Venue One", "A.D.H.D 多元化派对代表", "A.D.H.D 多元化派对", 0.93)
        # 5: room mismatch -> BLOCK keep_separate
        add_pair(5, "2026-12-14", "OIL", "Soy Sauce Project Room 2", "Soy Sauce Project", 0.9)
        # 6: high-sim NON-containment (inner word differs: night vs nite) -> C pending_llm
        add_pair(6, "2026-12-14", "Venue One", "Warehouse Night Chengdu", "Warehouse Nite Chengdu", 0.93)
        # 7: date prefix NOT matching event_date -> extra digit unsafe -> B2 (not B1)
        add_pair(7, "2026-12-14", "Venue One", "11.03 A.D.H.D 高速节拍", "A.D.H.D 高速节拍", 0.87)
        conn.commit()
        conn.close()

        ddb = tmp_path / "decisions.sqlite"
        report = adjudicate(cdb, ddb, None)
        rc = report["run_counts"]
        assert rc["input_pairs"] == 7, rc
        assert rc["tier_block_conflicting_dates"] == 1, rc
        assert rc["tier_a_norm_equal"] == 1, rc
        assert rc["tier_b1_safe_containment"] == 1, rc
        assert rc["tier_block_room_session"] == 1, rc
        assert rc["tier_c_high_sim"] == 1, rc
        assert rc.get("tier_b2_containment", 0) == 2, rc  # case 4 (content word extra) + case 7 (non-matching date digit)

        # idempotency: rerun inserts nothing new
        report2 = adjudicate(cdb, ddb, None)
        assert report2["run_counts"]["newly_inserted"] == 0, report2["run_counts"]
        assert report2["run_counts"]["already_decided_or_duplicate"] == 7

        store = sqlite3.connect(str(ddb))
        decisions = dict(store.execute("SELECT tier, decision FROM weak_key_merge_decision").fetchall())
        store.close()
        assert decisions["block_conflicting_dates"] == "keep_separate"
        assert decisions["a_norm_equal"] == "merge"
        assert decisions["b1_safe_containment"] == "merge"
        assert decisions["block_room_session"] == "keep_separate"
        assert decisions["b2_containment"] == "pending_llm"

        print("self-check OK: conflicting-date block, norm-equal merge, safe/unsafe containment split, room-session block, and idempotent rerun all verified")


# --- W3: LLM adjudication of pending_llm pairs -------------------------------------------

LLM_SYSTEM_PROMPT = """你是中国电子音乐活动数据的审核员。每对记录来自同一天、同一场地，但活动标题写法不同。
判断每对标题是否指同一场真实活动：
- 同一活动的不同写法（缩写、日期/星期装饰、场地名后缀、别称、标点差异、翻译）→ "same"
- 不同场次（早场/午夜场）、不同活动名、主角艺人不同、Vol/期数/编号不同 → "diff"
- 信息不足无法确定 → "unsure"
只输出 JSON 对象：{"verdicts":[{"id":<int>,"v":"same"|"diff"|"unsure"}]}，不要解释。"""

# conservative per-token guard prices (RMB per 1k tokens); real spend is typically lower
LLM_PRICE_IN_PER_1K = 0.004
LLM_PRICE_OUT_PER_1K = 0.012


def make_llm_client():
    import os

    from openai import OpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY not set")
    return (
        OpenAI(
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            api_key=api_key,
            timeout=90,
            max_retries=1,
        ),
        os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    )


def llm_judge_batch(client, model: str, batch: list[sqlite3.Row]) -> tuple[dict[str, str], str, int, int]:
    """Returns (pair_key -> verdict, raw_response_text, prompt_tokens, completion_tokens)."""
    payload = [
        {"id": i, "date": r["event_date"], "title_a": r["title_display_a"], "title_b": r["title_display_b"]}
        for i, r in enumerate(batch)
    ]
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=2048,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    raw = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    p_tok = getattr(usage, "prompt_tokens", 0) or 0
    c_tok = getattr(usage, "completion_tokens", 0) or 0
    verdicts: dict[str, str] = {}
    try:
        parsed = json.loads(raw)
        for item in parsed.get("verdicts", []):
            idx = item.get("id")
            v = item.get("v")
            if isinstance(idx, int) and 0 <= idx < len(batch) and v in ("same", "diff", "unsure"):
                verdicts[batch[idx]["pair_key"]] = v
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return verdicts, raw, p_tok, c_tok


def llm_adjudicate(
    decisions_db: Path,
    limit: int,
    batch_size: int,
    max_cost_rmb: float,
    report_path: Path | None,
    workers: int = 4,
) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    store = sqlite3.connect(str(decisions_db))
    store.row_factory = sqlite3.Row
    query = "SELECT * FROM weak_key_merge_decision WHERE decision = 'pending_llm' ORDER BY pair_key"
    if limit:
        query += f" LIMIT {int(limit)}"
    pending = store.execute(query).fetchall()

    counts: Counter[str] = Counter()
    counts["pending_selected"] = len(pending)
    spent_rmb = 0.0
    client = None
    model = "not_called"
    if pending and max_cost_rmb > 0:
        client, model = make_llm_client()
    verdict_map = {"same": ("merge", "llm", 0.85), "diff": ("keep_separate", "llm", 0.85), "unsure": ("needs_human", "llm", 0.0)}

    batches = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]
    done_rows = 0
    budget_stopped = False
    if pending and client is None:
        budget_stopped = True
    elif client is not None:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        # submit in waves so the budget check applies between waves, not after everything is in flight
            wave_size = max(1, workers) * 4
            for wave_start in range(0, len(batches), wave_size):
                if spent_rmb >= max_cost_rmb:
                    budget_stopped = True
                    break
                wave = batches[wave_start : wave_start + wave_size]
                futures = {pool.submit(llm_judge_batch, client, model, b): b for b in wave}
                for fut in as_completed(futures):
                    batch = futures[fut]
                    try:
                        verdicts, raw, p_tok, c_tok = fut.result()
                    except Exception as exc:  # transient API failure: leave rows pending for retry
                        counts["batch_errors"] += 1
                        print(f"  batch error: {exc}")
                        continue
                    spent_rmb += p_tok / 1000 * LLM_PRICE_IN_PER_1K + c_tok / 1000 * LLM_PRICE_OUT_PER_1K
                    for row in batch:
                        v = verdicts.get(row["pair_key"])
                        if v is None:
                            counts["verdict_missing_left_pending"] += 1
                            continue
                        decision, method, confidence = verdict_map[v]
                        counts[f"verdict_{v}"] += 1
                        store.execute(
                            "UPDATE weak_key_merge_decision SET decision=?, method=?, confidence=?, llm_verdict_raw=?, decided_at=? "
                            "WHERE pair_key=?",
                            (decision, method, confidence, v, now_iso(), row["pair_key"]),
                        )
                    done_rows += len(batch)
                store.commit()
                print(f"  progress {min(done_rows, len(pending))}/{len(pending)} spent≈¥{spent_rmb:.2f}")
    if budget_stopped:
        counts["budget_stopped"] = 1

    totals = dict(store.execute("SELECT decision, COUNT(*) FROM weak_key_merge_decision GROUP BY decision").fetchall())
    store.close()

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": "llm",
        "model": model,
        "run_counts": dict(counts),
        "spent_rmb_estimate": round(spent_rmb, 4),
        "store_totals_by_decision": totals,
    }
    if report_path:
        write_json(report_path, report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["deterministic", "llm"], default="deterministic")
    ap.add_argument("--candidates-db", type=Path)
    ap.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS_DB)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=0, help="llm mode: max pending pairs this run (0 = all)")
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--max-cost-rmb", type=float, default=25.0)
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    if args.self_check:
        _self_check()
        return 0

    if args.mode == "llm":
        report = llm_adjudicate(args.decisions_db, args.limit, args.batch_size, args.max_cost_rmb, args.report)
        print(json.dumps(report["run_counts"], indent=2, ensure_ascii=False))
        print(f"spent ≈ ¥{report['spent_rmb_estimate']}")
        print("store totals:", report["store_totals_by_decision"])
        return 0

    if not args.candidates_db or not args.candidates_db.exists():
        raise SystemExit(f"--candidates-db not found: {args.candidates_db}")

    report = adjudicate(args.candidates_db, args.decisions_db, args.report)
    print(json.dumps(report["run_counts"], indent=2, ensure_ascii=False))
    print("store totals:", report["store_totals_by_decision"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
