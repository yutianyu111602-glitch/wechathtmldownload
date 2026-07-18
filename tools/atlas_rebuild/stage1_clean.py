"""Stage 1 — Clean / select posters / dedup / route  (deterministic, no LLM).

For each ingested article:
  * parse raw.html -> clean text (drop script/style/nav boilerplate)
  * score poster candidates from assets_local.json by file_size, article order,
    dimensions/aspect/entropy, and obvious non-poster path hints; keep top
    POSTER_MAX_COUNT with an auditable reason trail
  * stage selected posters to the SSD work dir so Stage2 never random-reads D:
  * dedup: same event reposted across accounts -> dup_group (title+account hash)
  * route: text_complete (skip vision) vs needs_vision

Writes clean.sqlite. Idempotent (upsert by token).

Usage:
  python stage1_clean.py --limit 5
  python stage1_clean.py --no-stage-posters     # keep poster paths on D: (debug)
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from classify_article_type import classify_full, NON_EVENT, UNKNOWN, EVENT, MULTI, RECAP, VENUE_INTRO, ARTIST_INTRO, LABEL_INTRO

# Data-backed cost guard from the true manifest canary: these accounts produced
# non-event prose/social commentary with poster-like images. Keep the guard
# reversible: strong event signals still pass through.
NON_EVENT_ACCOUNT_HINTS = {
    "No8Pawnshop",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS clean (
  token TEXT PRIMARY KEY,
  account_key TEXT, title TEXT,
  source_published_at TEXT,
  clean_text TEXT, text_len INTEGER,
  poster_json TEXT,           -- [{asset_id, path, bytes}]
  poster_candidates_json TEXT,
  poster_selection_report_json TEXT,
  poster_count INTEGER,
  dup_group TEXT, route TEXT, status TEXT,
  article_type TEXT,
  should_process_text INTEGER,
  should_process_images INTEGER,
  image_route_reason TEXT,
  classification_confidence REAL,
  classification_reasons TEXT
);
CREATE INDEX IF NOT EXISTS ix_clean_route ON clean(route);
CREATE INDEX IF NOT EXISTS ix_clean_dup ON clean(dup_group);
CREATE INDEX IF NOT EXISTS ix_clean_article_type ON clean(article_type);
"""

_WS = re.compile(r"[ \t ]+")
_NL = re.compile(r"\n{3,}")
_ASSET_NUM = re.compile(r"(\d+)$")
SQLITE_BUSY_TIMEOUT_MS = 60000
_NON_POSTER_HINT = re.compile(
    r"(logo|avatar|qr|qrcode|code|map|地图|address|地址|location|定位|menu|菜单|drink|酒水|rule|须知|notice|公告|hours|营业|wechat|weixin|微信|contact|联系)",
    re.I,
)


def ensure_clean_schema(con):
    cols = {row[1] for row in con.execute("PRAGMA table_info(clean)").fetchall()}
    for name in ("poster_candidates_json", "poster_selection_report_json"):
        if name not in cols:
            con.execute(f"ALTER TABLE clean ADD COLUMN {name} TEXT")
    for name, col_type in (
        ("source_published_at", "TEXT"),
        ("article_type", "TEXT"),
        ("should_process_text", "INTEGER"),
        ("should_process_images", "INTEGER"),
        ("image_route_reason", "TEXT"),
        ("classification_confidence", "REAL"),
        ("classification_reasons", "TEXT"),
    ):
        if name not in cols:
            con.execute(f"ALTER TABLE clean ADD COLUMN {name} {col_type}")


def connect_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    con.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    return con


def html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = _WS.sub(" ", text)
    text = "\n".join(ln.strip() for ln in text.splitlines())
    text = _NL.sub("\n\n", text).strip()
    return text


def asset_index(asset_id):
    m = _ASSET_NUM.search(asset_id or "")
    return int(m.group(1)) if m else 999


def image_stats(path):
    info = {
        "width": None,
        "height": None,
        "aspect": None,
        "area": None,
        "entropy": None,
        "animated": False,
        "frame_count": 1,
        "decode_error": "",
    }
    try:
        from PIL import Image
        with Image.open(path) as im:
            info["animated"] = bool(getattr(im, "is_animated", False))
            info["frame_count"] = int(getattr(im, "n_frames", 1) or 1)
            if info["animated"]:
                im.seek(0)
            w, h = im.size
            info.update({"width": w, "height": h, "aspect": round(w / h, 4) if h else None, "area": w * h})
            thumb = im.convert("L")
            thumb.thumbnail((96, 96))
            hist = thumb.histogram()
            total = sum(hist) or 1
            entropy = 0.0
            for count in hist:
                if count:
                    p = count / total
                    entropy -= p * math.log2(p)
            info["entropy"] = round(entropy, 3)
    except Exception as exc:
        info["decode_error"] = f"{type(exc).__name__}: {exc}"[:160]
    return info


def score_candidate(im, path, size, idx):
    stats = image_stats(path)
    score = 0.0
    reasons = []
    penalties = []

    if size >= config.POSTER_MIN_BYTES:
        bump = min(42.0, math.log(max(size, 1) / config.POSTER_MIN_BYTES, 1.45) * 4.0)
        score += bump
        reasons.append(f"size+{bump:.1f}")
    if idx < 999:
        bump = max(0.0, 24.0 - idx * 4.0)
        score += bump
        reasons.append(f"early_asset+{bump:.1f}")

    area = stats.get("area") or 0
    width = stats.get("width") or 0
    height = stats.get("height") or 0
    aspect = stats.get("aspect")
    entropy = stats.get("entropy")

    if area >= 250000:
        score += 16; reasons.append("large_canvas+16")
    elif area and area < 120000:
        score -= 14; penalties.append("small_canvas-14")
    if min(width, height) >= 480:
        score += 8; reasons.append("readable_dimension+8")
    if aspect:
        if 0.45 <= aspect <= 1.35:
            score += 14; reasons.append("poster_aspect+14")
        elif 1.35 < aspect <= 1.95:
            score += 6; reasons.append("wide_event_card+6")
        elif aspect < 0.32 or aspect > 2.35:
            score -= 22; penalties.append("extreme_aspect-22")
    if entropy is not None:
        if 3.2 <= entropy <= 7.4:
            score += 6; reasons.append("moderate_entropy+6")
        elif entropy < 2.4:
            score -= 12; penalties.append("flat_image-12")

    hint_text = " ".join(str(im.get(k) or "") for k in ("asset_id", "local_path", "remote_url", "content_type"))
    if _NON_POSTER_HINT.search(hint_text):
        score -= 24; penalties.append("non_poster_path_hint-24")
    is_gif = str(im.get("content_type") or "").lower() == "image/gif" or str(path).lower().endswith(".gif")
    if stats.get("animated"):
        score -= 30; penalties.append("animated_gif-30")
    elif is_gif:
        score -= 12; penalties.append("gif_review-12")

    return score, reasons, penalties, stats


def select_posters(assets_path, token):
    """Rank likely event posters; resolve to absolute local files and explain decisions."""
    if not assets_path or not os.path.isfile(assets_path):
        return [], [], {
            "strategy": "deterministic_poster_score_v1",
            "candidate_count": 0,
            "selected_asset_ids": [],
            "needs_review": False,
            "review_reasons": ["missing_assets_json"],
        }
    base = os.path.dirname(assets_path)
    try:
        with open(assets_path, "r", encoding="utf-8", errors="replace") as f:
            images = json.load(f).get("images", [])
    except Exception:
        return [], [], {
            "strategy": "deterministic_poster_score_v1",
            "candidate_count": 0,
            "selected_asset_ids": [],
            "needs_review": True,
            "review_reasons": ["bad_assets_json"],
        }
    cand = []
    for im in images:
        if im.get("status") != "downloaded":
            continue
        lp = im.get("local_path")
        size = int(im.get("file_size") or 0)
        if not lp or size < config.POSTER_MIN_BYTES:
            continue
        ap = os.path.join(base, lp)
        if os.path.isfile(ap):
            idx = asset_index(im.get("asset_id", ""))
            score, reasons, penalties, stats = score_candidate(im, ap, size, idx)
            cand.append({
                "asset_id": im.get("asset_id", ""),
                "path": ap,
                "bytes": size,
                "score": round(score, 2),
                "reasons": reasons,
                "penalties": penalties,
                "width": stats.get("width"),
                "height": stats.get("height"),
                "aspect": stats.get("aspect"),
                "entropy": stats.get("entropy"),
                "decode_error": stats.get("decode_error", ""),
            })
    cand.sort(key=lambda x: (x["score"], x["bytes"], -asset_index(x["asset_id"])), reverse=True)
    selected = cand[: config.POSTER_MAX_COUNT]
    top_score = selected[0]["score"] if selected else 0.0
    gap = top_score - (cand[1]["score"] if len(cand) > 1 else 0.0)
    review_reasons = []
    if not selected and images:
        review_reasons.append("no_candidate_after_filter")
    if selected and top_score < config.POSTER_REVIEW_SCORE:
        review_reasons.append("low_top_score")
    if len(cand) > 1 and gap < config.POSTER_REVIEW_GAP:
        review_reasons.append("ambiguous_top_gap")
    if selected and selected[0].get("penalties"):
        review_reasons.append("top_has_penalties")
    report = {
        "strategy": "deterministic_poster_score_v1",
        "candidate_count": len(cand),
        "selected_asset_ids": [p["asset_id"] for p in selected],
        "top_score": top_score,
        "top_gap": round(gap, 2),
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
    }
    return selected, cand, report


def stage_posters(posters, token):
    """Copy selected posters to SSD staging/<token>/ so Stage2 reads from SSD."""
    out = os.path.join(config.STAGING_DIR, token)
    os.makedirs(out, exist_ok=True)
    staged = []
    for p in posters:
        dst = os.path.join(out, f"{p['asset_id'] or 'img'}{os.path.splitext(p['path'])[1] or '.jpg'}")
        if not os.path.isfile(dst):
            shutil.copy2(p["path"], dst)
        item = dict(p)
        item["path"] = dst
        staged.append(item)
    return staged


def dup_group(title: str, account: str) -> str:
    key = re.sub(r"\s+", "", (title or "").lower()) + "|" + (account or "")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def route_of(text_len: int, poster_count: int) -> str:
    # Fallback when classifier is not available; kept for backward compatibility.
    if text_len >= config.TEXT_COMPLETE_MIN_CHARS and poster_count == 0:
        return "text_complete"
    return "needs_vision"


def compute_classification_routing(title: str, clean_text: str, image_count: int,
                                    poster_count: int, text_len: int) -> dict:
    """Run classifier and return both classification + routing fields for Stage1 output."""
    try:
        result = classify_full(
            title=title or "",
            snippet=clean_text or "",
            image_count=image_count,
            poster_count=poster_count,
            text_len=text_len,
            text_complete_min_chars=config.TEXT_COMPLETE_MIN_CHARS,
        )
    except Exception:
        # If classifier fails, fall back to UNKNOWN with conservative routing
        result = {
            "article_type": UNKNOWN,
            "should_process_text": True,
            "should_process_images": bool(poster_count),
            "image_route_reason": "classifier error — fallback to unknown",
            "classification_confidence": 0.0,
            "classification_reasons": ["classifier_failure"],
            "route": route_of(text_len, poster_count),
        }
    # If classifier returned needs_vision but no posters exist, downgrade
    if result.get("should_process_images") and poster_count == 0:
        result["should_process_images"] = False
        result["image_route_reason"] = (result.get("image_route_reason", "")
                                        + " — downgraded: no posters available")
        if result.get("route") == "needs_vision":
            result["route"] = "text_complete"
    return result


def apply_account_cost_guard(account_key: str, result: dict) -> dict:
    """Skip known prose accounts unless the article has strong event signals."""
    if account_key not in NON_EVENT_ACCOUNT_HINTS:
        return result
    reasons = set(result.get("classification_reasons") or result.get("signals") or [])
    has_strong_event_signal = bool(reasons & {"lineup", "ticket", "event_kw"})
    if has_strong_event_signal:
        return result
    guarded = dict(result)
    guarded["article_type"] = NON_EVENT
    guarded["type"] = NON_EVENT
    guarded["should_process_text"] = False
    guarded["should_process_images"] = False
    guarded["route"] = "skip"
    guarded["classification_confidence"] = max(float(guarded.get("classification_confidence") or 0.0), 0.85)
    guarded["image_route_reason"] = "non_event_account_hint: no strong event signal"
    guarded["classification_reasons"] = list(reasons | {"non_event_account_hint"})
    guarded["signals"] = guarded["classification_reasons"]
    guarded["needs_extraction"] = False
    return guarded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-stage-posters", action="store_true")
    args = ap.parse_args()

    config.ensure_dirs()
    src = connect_db(config.DB_INGEST)
    con = connect_db(config.DB_CLEAN)
    con.executescript(SCHEMA)
    ensure_clean_schema(con)

    q = "SELECT token, account_key, title, archived_at, raw_html_path, assets_json_path, img_count FROM ingest"
    if args.limit:
        q += f" LIMIT {int(args.limit)}"
    rows = src.execute(q).fetchall()
    n = 0
    audit = {
        "strategy": "deterministic_poster_score_v1",
        "processed": 0,
        "with_candidates": 0,
        "selected": 0,
        "needs_review": 0,
        "review_reasons": {},
        "article_types": {},
        "skip_count": 0,
        "vision_count": 0,
        "text_count": 0,
    }
    for token, acct, title, source_published_at, raw_html_path, assets_path, img_count in rows:
        try:
            with open(raw_html_path, "r", encoding="utf-8", errors="replace") as f:
                text = html_to_text(f.read())
        except Exception:
            text = ""
        text = text[: config.CLEAN_TEXT_MAX_CHARS]
        posters, candidates, selection_report = select_posters(assets_path, token)
        if posters and not args.no_stage_posters:
            posters = stage_posters(posters, token)
        # Run article-type classifier and compute routing
        cr = compute_classification_routing(title, text, img_count or 0, len(posters), len(text))
        cr = apply_account_cost_guard(acct, cr)
        route = cr["route"]
        article_type = cr["article_type"]
        audit["article_types"][article_type] = audit["article_types"].get(article_type, 0) + 1
        if route == "skip":
            audit["skip_count"] += 1
        elif route == "needs_vision":
            audit["vision_count"] += 1
        else:
            audit["text_count"] += 1
        audit["processed"] += 1
        audit["with_candidates"] += int(bool(candidates))
        audit["selected"] += len(posters)
        if selection_report.get("needs_review"):
            audit["needs_review"] += 1
            for reason in selection_report.get("review_reasons", []):
                audit["review_reasons"][reason] = audit["review_reasons"].get(reason, 0) + 1
        con.execute(
            """
            INSERT OR REPLACE INTO clean
              (token, account_key, title, source_published_at, clean_text, text_len, poster_json,
               poster_candidates_json, poster_selection_report_json,
               poster_count, dup_group, route, status,
               article_type, should_process_text, should_process_images,
               image_route_reason, classification_confidence, classification_reasons)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (token, acct, title, source_published_at, text, len(text), json.dumps(posters, ensure_ascii=False),
             json.dumps(candidates, ensure_ascii=False), json.dumps(selection_report, ensure_ascii=False),
             len(posters), dup_group(title, acct), route, "cleaned",
             article_type,
             int(cr["should_process_text"]),
             int(cr["should_process_images"]),
             cr["image_route_reason"],
             cr["classification_confidence"],
             json.dumps(cr["classification_reasons"], ensure_ascii=False)),
        )
        n += 1
        if n % 1000 == 0:
            con.commit(); print(f"  cleaned {n}...")
    con.commit()
    # quick report
    by_route = dict(con.execute("SELECT route, COUNT(*) FROM clean GROUP BY route").fetchall())
    by_type = dict(con.execute("SELECT article_type, COUNT(*) FROM clean GROUP BY article_type").fetchall())
    total = con.execute("SELECT COUNT(*) FROM clean").fetchone()[0]
    audit_path = os.path.join(config.WORK_DIR, "poster_selection_audit.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    con.close(); src.close()
    print(f"Stage1 done: +{n} this run, clean total={total}, routes={by_route}")
    print(f"  article types: {by_type}")
    print(f"  skip={audit['skip_count']} vision={audit['vision_count']} text={audit['text_count']}")
    print(f"  -> {config.DB_CLEAN}")
    print(f"  poster audit -> {audit_path}")


if __name__ == "__main__":
    main()
