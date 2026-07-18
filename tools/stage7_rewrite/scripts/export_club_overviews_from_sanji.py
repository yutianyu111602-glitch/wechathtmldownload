#!/usr/bin/env python3
"""Export CURRENT/FUTURE club "活动一览" roundup posts from the 公号三刀 (sanji) DB.

Report-only read of sanji.db. Picks only roundups whose window still covers today
or later (historical ones are dropped -- they were only useful for structure
analysis), classifies the window attribute (week / month / holiday) and the date
range from the title, and writes a static JSON the venue/club page can render.

This is the "C" validation feed; the eventual "A" path reads sanji.db directly.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

DEFAULT_DB = Path.home() / "AppData/Roaming/sanji/sanji.db"

# Keep the SQL side broad enough to catch newly named roundup posts, then apply
# the stricter Python parent-aggregate filter below so single-event posts do not
# enter the venue overview feed.
TITLE_MATCH = (
    "%活动一览%",
    "%活动全览%",
    "%活动预览%",
    "%活动预告%",
    "%本周%",
    "%本月%",
    "%月%一览%",
    "%月%活动%",
    "%端午%",
    "%假期%",
    "%holiday%",
    "%weekly%",
    "%周刊%",
)
HOLIDAY_RE = re.compile(r"(端午|五一|劳动节|清明|国庆|中秋|春节|元旦|假期|长假)")
WEEK_RE = re.compile(r"(本周末|本周|这周|今周|周末|weekly)", re.I)
MONTH_RE = re.compile(r"(本月|月度|当月|[0-9一二三四五六七八九十]{1,3}\s*月活动|[0-9一二三四五六七八九十]{1,3}\s*月一览|[0-9一二三四五六七八九十]{1,3}\s*月\s*活动一览)")
ROUNDUP_PATTERNS = (
    re.compile(r"活动(?:一览|全览|预览|预告|安排)", re.I),
    re.compile(r"(?:本周|这周|今周|周末).*(?:活动|安排|预告|预览|一览|来|蛮夯|两晚|三晚|四日|三日)", re.I),
    re.compile(r"(?:本月|月度|当月|[0-9一二三四五六七八九十]{1,3}\s*月).*(?:活动一览|活动全览|活动预览|活动预告|一览)", re.I),
    re.compile(r"(?:端午|假期|holiday).*(?:活动一览|活动全览|活动预览|活动预告|计划|周刊|四日|三日|\d{1,2}\s*[./]\s*\d{1,2}\s*[-—~～到至])", re.I),
    re.compile(r"(?:weekly|周刊).*(?:端午|活动|club|party|rave|holiday|周刊|\d{1,2}\s*[./]\s*\d{1,2}\s*[-—~～到至])", re.I),
)
# date range in title: "6.18—6.21", "6.8-6.13", "4/30 - 5/4", "10.11～10.12"
RANGE_RE = re.compile(r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[-—~～到至]\s*(?:(\d{1,2})\s*[./]\s*)?(\d{1,2})")
CN_MONTH = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


def month_end(year: int, month: int) -> dt.date:
    return (dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1))


def is_roundup_title(title: str) -> bool:
    return any(pattern.search(title or "") for pattern in ROUNDUP_PATTERNS)


def normalize_url(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("http://mmbiz.qpic.cn/") or text.startswith("http://mp.weixin.qq.com/"):
        return "https://" + text[len("http://") :]
    return text


def snapshot_sanji_db(db_path: Path, snapshot_path: Path) -> None:
    """Copy the live WAL-backed Sanji DB into a stable read snapshot."""
    src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(snapshot_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def classify(title: str, publish: dt.date) -> dict:
    """Return {window_kind, window_label, window_start, window_end} for a roundup."""
    y = publish.year
    m = RANGE_RE.search(title)
    if m:
        m1, d1, m2, d2 = m.group(1), m.group(2), m.group(3), m.group(4)
        start = dt.date(y, int(m1), int(d1))
        end = dt.date(y, int(m2 or m1), int(d2))
        if end < start:  # range crossed into next month written sloppily
            end = dt.date(y, int(m2 or m1) % 12 + 1, int(d2))
        kind = "holiday" if HOLIDAY_RE.search(title) else "week"
        return {"window_kind": kind, "window_label": f"{start.month}.{start.day}-{end.month}.{end.day}",
                "window_start": start.isoformat(), "window_end": end.isoformat()}
    if HOLIDAY_RE.search(title):
        # holiday without explicit range -> assume the week of publish covers it
        start, end = publish, publish + dt.timedelta(days=7)
        return {"window_kind": "holiday", "window_label": "假期", "window_start": start.isoformat(), "window_end": end.isoformat()}
    # monthly: find a month token
    mon = None
    cn = re.search(r"([一二三四五六七八九十]{1,3})\s*月", title)
    ar = re.search(r"(\d{1,2})\s*月", title)
    if ar:
        mon = int(ar.group(1))
    elif cn:
        mon = CN_MONTH.get(cn.group(1))
    if mon and MONTH_RE.search(title):
        yr = y if mon >= publish.month - 1 else y + (mon < publish.month)
        start = dt.date(yr, mon, 1)
        return {"window_kind": "month", "window_label": f"{mon}月", "window_start": start.isoformat(), "window_end": month_end(yr, mon).isoformat()}
    # default: weekly window starting at publish
    start, end = publish, publish + dt.timedelta(days=6)
    return {"window_kind": "week", "window_label": "本周", "window_start": start.isoformat(), "window_end": end.isoformat()}


def export(db_path: Path, today: dt.date) -> dict:
    with tempfile.TemporaryDirectory(prefix="sanji_club_overviews_") as tmp:
        snapshot_path = Path(tmp) / "sanji.snapshot.db"
        snapshot_sanji_db(db_path, snapshot_path)
        con = sqlite3.connect(snapshot_path)
        con.text_factory = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else b
        where = " OR ".join("ar.title LIKE ?" for _ in TITLE_MATCH)
        rows = con.execute(
            f"""SELECT a.nickname, a.fakeid, ar.title, ar.publish_time, ar.link, ar.cover
                FROM wechat_article ar LEFT JOIN wechat_account a ON ar.account_fakeid=a.fakeid
                WHERE ({where}) AND ar.link != '' AND ar.cover != ''
                ORDER BY ar.publish_time DESC""",
            TITLE_MATCH,
        ).fetchall()
        con.close()
    by_club: dict[str, list] = {}
    for nick, fakeid, title, pt, link, cover in rows:
        if not pt:
            continue
        title_text = str(title).strip()
        if not is_roundup_title(title_text):
            continue
        publish = dt.date.fromtimestamp(pt)
        win = classify(title_text, publish)
        if dt.date.fromisoformat(win["window_end"]) < today:
            continue  # historical -- drop (only current/future roundups matter)
        entry = {
            "record_type": "club_overview_parent",
            "parent_aggregate": True,
            "include_in_activity_feed": False,
            "source_table": "wechat_article",
            "club": nick, "club_fakeid": fakeid, "title": title_text,
            "publish_date": publish.isoformat(), "original_url": normalize_url(link), "cover_url": normalize_url(cover),
            **win,
        }
        by_club.setdefault(nick or "(unknown)", []).append(entry)
    # dedupe by title (same roundup re-published) keeping newest, then sort by window_end desc
    for club in list(by_club):
        seen: dict[str, dict] = {}
        for e in sorted(by_club[club], key=lambda e: e["publish_date"], reverse=True):
            seen.setdefault(e["title"], e)
        by_club[club] = sorted(seen.values(), key=lambda e: e["window_end"], reverse=True)
    return {
        "schema_version": "club_overviews.v1",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "as_of_date": today.isoformat(),
        "source": "sanji.db (公号三刀)",
        "club_count": len(by_club),
        "overview_count": sum(len(v) for v in by_club.values()),
        "kind_counts": dict(Counter(e["window_kind"] for items in by_club.values() for e in items)),
        "by_club": by_club,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--out-js", type=Path, help="Optional CommonJS module for the mini-program runtime.")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    args = ap.parse_args(argv)
    data = export(args.db, dt.date.fromisoformat(args.today))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.out_js:
        args.out_js.parent.mkdir(parents=True, exist_ok=True)
        args.out_js.write_text(
            "// Generated from sanji.db by tools/stage7_rewrite/scripts/export_club_overviews_from_sanji.py.\n"
            "// Static C-stage validation data: only current/future roundup articles.\n"
            f"module.exports = {json.dumps(data, ensure_ascii=False, indent=2)};\n",
            encoding="utf-8",
        )
    print(f"clubs={data['club_count']} overviews={data['overview_count']} -> {args.out}")
    for club, items in sorted(data["by_club"].items()):
        for e in items:
            print(f"  [{e['window_kind']:7}] {e['window_label']:10} end={e['window_end']} | {club} | {e['title'][:42]}")
    return 0


def _selfcheck() -> None:
    assert classify("端午假期活动一览 6.18—6.21丨...", dt.date(2026, 6, 16))["window_kind"] == "holiday"
    assert classify("loopy 六月活动一览", dt.date(2026, 5, 31))["window_kind"] == "month"
    assert classify("6.8-6.13｜本周活动一览 🧩", dt.date(2026, 6, 8))["window_kind"] == "week"
    r = classify("端午假期活动一览 6.18—6.21", dt.date(2026, 6, 16))
    assert r["window_end"] == "2026-06-21", r
    assert dt.date.fromisoformat(classify("loopy 六月活动一览", dt.date(2026, 5, 31))["window_end"]) == dt.date(2026, 6, 30)
    assert is_roundup_title("6.18-6.20端午节变电所活动全览")
    assert is_roundup_title("TRUST｜holiday 🧭 端午 6.18～6.21")
    assert is_roundup_title("JARO 本周蛮夯的两晚")
    assert is_roundup_title("AURORA 森｜weekly 端午周刊 🪴 6.17～6.21 @ belo park 彼落公园")
    assert not is_roundup_title("今晚6月19日 - 京城Bass团体Badness...")
    assert not is_roundup_title("6月19日 周五 ｜Popasuda! Vibe sup party！")
    print("selfcheck ok")


if __name__ == "__main__":
    import sys
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        raise SystemExit(main())
