"""Layer-1 article-type classifier — rule-based, no API.

Cheaply tags each article so the pipeline skips paying a vision model on
non-events (menus / notices / recruiting / QR / venue-or-artist intros).
Input is title + a body snippet + image count; output is a type + confidence.

# ponytail: naive keyword/regex classifier. Good enough as a pre-filter.
# Upgrade path: if precision on borderline cases matters, hand the snippet to
# DeepSeek text with the same label set (see atlas_deepseek_task_pack.md task 4).

CLI:  python classify_article_type.py --self-check
      python classify_article_type.py --title "..." --snippet "..." --images 12
"""
from __future__ import annotations
import argparse
import re

# label set (event-ish vs non-event vs intro)
EVENT = "event"            # party / show / 演出 / 预告
MULTI = "event_multi"      # 合集 / 多活动
PARENT_AGGREGATE = "parent_aggregate"  # weekly/monthly guide or schedule parent article
RECAP = "recap"            # 回顾 / aftermovie
VENUE_INTRO = "venue_intro"
ARTIST_INTRO = "artist_intro"
LABEL_INTRO = "label_intro"
NON_EVENT = "non_event"    # menu / notice / recruit / qr / ad
UNKNOWN = "unknown"

_DATE = re.compile(
    r"(20\d{2}[ \t]*[-/.][ \t]*\d{1,2}[ \t]*[-/.][ \t]*\d{1,2}|"
    r"20\d{2}[ \t]*年[ \t]*\d{1,2}[ \t]*月[ \t]*\d{1,2}[ \t]*日?|"
    r"\d{1,2}[ \t]*[\./月][ \t]*\d{1,2}[ \t]*日?|"
    r"周[一二三四五六日天]|今晚|明晚|本周[末五六日]|周末|tonight|fri|sat|sun)",
    re.I,
)
_PUBLISH_DATE_LINE = re.compile(
    r"^\s*(20\d{2}[ \t]*[-/.][ \t]*\d{1,2}[ \t]*[-/.][ \t]*\d{1,2}|"
    r"20\d{2}[ \t]*年[ \t]*\d{1,2}[ \t]*月[ \t]*\d{1,2}[ \t]*日?)"
    r"[ \t]+\d{1,2}:\d{2}(?::\d{2})?\s*$"
)
_LINEUP = re.compile(r"(line\s*-?up|阵容|b2b|\bdj\b|live\s*act|嘉宾阵容|特邀嘉宾|演出阵容)", re.I)
_TICKET = re.compile(r"(门票|票价|预售|presale|\bdoor\b|秀动|票星球|rmb|入场)", re.I)
_EVENT_CORE = re.compile(
    r"(派对|活动|演出|预告|开票|购票|club\s*night|rave|party|showcase|"
    r"live\s*set|dj\s*set|音乐节|巡演|专场|after\s*party|afterparty|厂牌之夜|舞池)",
    re.I,
)
_NONEVENT = re.compile(r"(招聘|招募|hiring|we\s*are\s*hiring|菜单|酒水单|drink\s*menu|营业时间|暂停营业|停业|closed|放假|二维码|扫码关注|公告|通知|顺延|招商|广告合作)", re.I)
_PROSE_NONEVENT = re.compile(
    r"(电影|剧集|电视剧|热播|版本解读|读后感|书评|战争|疫情|恋爱|结婚|离婚|"
    r"出轨|维权|观点|感想|随笔|小说|综艺|歌手|微信视频|点击观看微信视频|"
    r"公众号|发文|吃瓜|新闻|城市|菜谱|情绪|唠嗑|生活|旅行|游客|记录\d?|"
    r"读书|渣男|女强人)",
    re.I,
)
_VENUE = re.compile(r"(场地介绍|关于我们|about\s*us|空间介绍|新店|开业)", re.I)
_ARTIST = re.compile(r"(专访|访谈|interview|艺人介绍|dj\s*介绍|人物|profile)", re.I)
_LABEL = re.compile(r"(厂牌|label|crew|collective|主理|成立)", re.I)
_RECAP = re.compile(r"(回顾|recap|aftermovie|past|上周|现场图|返图)", re.I)
_PARENT_AGGREGATE = re.compile(
    r"(本周\s*(活动|派对|演出|排期|指南|预告)|"
    r"本月\s*(活动|派对|演出|排期|指南|预告)|"
    r"(一|二|三|四|五|六|七|八|九|十|十一|十二)月\s*(活动|派对|演出|排期|指南|预告)|"
    r"weekly|monthly|dance\s*plan|活动一览|活动排期|排期|节目单|"
    r"蹦迪指南|活动指南|派对指南|schedule\s*overview)",
    re.I,
)
_MULTI = re.compile(r"(本周\s*(活动|派对)|weekly|排期|节目单|时间表|本月|这周末.*(和|&|、).*)", re.I)


def classify(title: str, snippet: str, image_count: int = 0) -> dict:
    """Return classification dict with type, confidence, signals, needs_extraction."""
    return _classify_impl(title, snippet, image_count)


def classify_full(title: str, snippet: str, image_count: int = 0, poster_count: int = 0,
                  text_len: int = 0, text_complete_min_chars: int = 400) -> dict:
    """Return full classification + routing dict for Stage1 integration.

    Adds should_process_text, should_process_images, image_route_reason,
    and a suggested route value on top of the base classify() output.
    """
    base = _classify_impl(title, snippet, image_count)
    article_type = base["type"]
    confidence = base["confidence"]
    signals = base["signals"]

    should_process_text = bool(base.get("needs_extraction", True))
    should_process_images = False
    image_route_reason = ""

    if article_type == NON_EVENT:
        should_process_text = False
        should_process_images = False
        image_route_reason = "non_event: menu/notice/recruiting/ad — no extraction needed"
    elif article_type in (EVENT, MULTI, PARENT_AGGREGATE, RECAP):
        should_process_text = True
        if poster_count > 0:
            should_process_images = True
            image_route_reason = f"{article_type} with {poster_count} poster(s)"
        else:
            image_route_reason = f"{article_type} but no posters available"
    elif article_type in (VENUE_INTRO, ARTIST_INTRO, LABEL_INTRO):
        should_process_text = True
        if poster_count > 0:
            should_process_images = True
            image_route_reason = f"{article_type} with {poster_count} poster(s)"
        else:
            image_route_reason = f"{article_type} but no posters available"
    elif article_type == UNKNOWN:
        # Heuristic: enough images may indicate a poster-only event
        if image_count >= 3 and poster_count > 0:
            should_process_text = True
            should_process_images = True
            image_route_reason = f"unknown with {image_count} images + posters — possible poster-only event"
        elif poster_count > 0:
            should_process_text = True
            should_process_images = True
            image_route_reason = "unknown with posters — low-confidence visual candidate"
        elif text_len >= text_complete_min_chars:
            should_process_text = True
            image_route_reason = "unknown but sufficient text — text-only"
        else:
            should_process_text = True
            image_route_reason = "unknown with insufficient data — text-only fallback"

    # Determine stage2 route
    if not should_process_text and not should_process_images:
        route = "skip"
    elif should_process_images:
        route = "needs_vision"
    else:
        route = "text_complete"

    base.update({
        "article_type": article_type,
        "should_process_text": should_process_text,
        "should_process_images": should_process_images,
        "image_route_reason": image_route_reason,
        "classification_confidence": confidence,
        "classification_reasons": signals,
        "route": route,
    })
    return base


def _classify_impl(title: str, snippet: str, image_count: int = 0) -> dict:
    t = f"{title}\n{_strip_wechat_publish_header(snippet or '')}"[:1200]
    sig = []
    has_date = bool(_DATE.search(t)); sig += ["date"] if has_date else []
    has_lineup = bool(_LINEUP.search(t)); sig += ["lineup"] if has_lineup else []
    has_ticket = bool(_TICKET.search(t)); sig += ["ticket"] if has_ticket else []
    has_event_core = bool(_EVENT_CORE.search(t)); sig += ["event_kw"] if has_event_core else []

    if _NONEVENT.search(t) and not (has_lineup and has_date):
        return {"type": NON_EVENT, "confidence": 0.8, "signals": sig + ["nonevent_kw"], "needs_extraction": False}
    if _PROSE_NONEVENT.search(t) and not (has_date or has_lineup or has_ticket or has_event_core):
        return {"type": NON_EVENT, "confidence": 0.7, "signals": sig + ["prose_nonevent_kw"], "needs_extraction": False}
    if _RECAP.search(t) and not has_ticket:
        return {"type": RECAP, "confidence": 0.6, "signals": sig + ["recap_kw"], "needs_extraction": True}
    if _PARENT_AGGREGATE.search(t):
        return {"type": PARENT_AGGREGATE, "confidence": 0.68, "signals": sig + ["parent_aggregate_kw"], "needs_extraction": True}
    if _MULTI.search(t):
        return {"type": MULTI, "confidence": 0.6, "signals": sig + ["multi_kw"], "needs_extraction": True}
    # strong event: date + (lineup or ticket)
    score = has_date + has_lineup + has_ticket
    if has_date and (has_lineup or has_ticket):
        return {"type": EVENT, "confidence": min(0.6 + 0.15 * score, 0.95), "signals": sig, "needs_extraction": True}
    # intros (no date, descriptive)
    if not has_date:
        if _VENUE.search(t):
            return {"type": VENUE_INTRO, "confidence": 0.55, "signals": sig + ["venue_kw"], "needs_extraction": True}
        if _ARTIST.search(t):
            return {"type": ARTIST_INTRO, "confidence": 0.55, "signals": sig + ["artist_kw"], "needs_extraction": True}
        if _LABEL.search(t):
            return {"type": LABEL_INTRO, "confidence": 0.55, "signals": sig + ["label_kw"], "needs_extraction": True}
    # weak event: date alone, or lineup alone with images (poster-only)
    if (has_date and (has_event_core or image_count >= 3)) or (has_lineup and image_count >= 3):
        return {"type": EVENT, "confidence": 0.45, "signals": sig + ["weak"], "needs_extraction": True}
    return {"type": UNKNOWN, "confidence": 0.3, "signals": sig, "needs_extraction": image_count >= 3}


def _strip_wechat_publish_header(snippet: str) -> str:
    """Remove common WeChat publish timestamp lines from the header only."""
    lines = snippet.splitlines()
    out = []
    for idx, line in enumerate(lines):
        if idx < 24 and _PUBLISH_DATE_LINE.match(line):
            continue
        out.append(line)
    return "\n".join(out)


def _self_check():
    cases = [
        ("今晚 | OIL x Techno Night", "5月13日 周五 22:00 lineup: COLA REN b2b Mika 门票 80rmb", 5, EVENT),
        ("ALL 招聘调酒师", "我们正在招募有经验的 bartender，菜单培训提供", 2, NON_EVENT),
        ("关于 fRUITYSPACE 空间介绍", "我们是一家位于北京的 livehouse", 1, VENUE_INTRO),
        ("本周活动排期", "周四 A 周五 B 周六 C 时间表见海报", 8, PARENT_AGGREGATE),
        ("Elevator Shanghai Dance Plan", "June weekly schedule overview and party guide", 10, PARENT_AGGREGATE),
        ("上周回顾 | aftermovie", "现场图返图，感谢大家", 20, RECAP),
        ("2024《歌手》发癫，是我得连夜发文的程度", "No8Pawnshop\n2024年5月16日 19:45\n电影综艺评论与个人感想", 2, NON_EVENT),
        ("他说，他要结婚了。", "No8Pawnshop\n2021-06-16 22:15\n点击观看微信视频，推荐歌曲《嘉宾》", 1, NON_EVENT),
    ]
    for title, snip, imgs, want in cases:
        got = classify(title, snip, imgs)["type"]
        assert got == want, f"{title!r}: got {got}, want {want}"
    print("self-check OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--title", default="")
    ap.add_argument("--snippet", default="")
    ap.add_argument("--images", type=int, default=0)
    a = ap.parse_args()
    if a.self_check:
        _self_check()
    else:
        import json
        print(json.dumps(classify(a.title, a.snippet, a.images), ensure_ascii=False))
