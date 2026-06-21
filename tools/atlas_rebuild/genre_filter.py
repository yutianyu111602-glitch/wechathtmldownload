"""Genre gate — keep underground electronic, drop the rest. Rule-based, no API.

The article-type classifier (classify_article_type.py) only tells event vs
non-event. It does NOT tell electronic vs folk/rock/wedding/standup. This module
reads the model's already-extracted `styles` (plus a text blob) and tags an event
electronic | non_electronic | unknown via keyword allowlist. No extra API call.

# ponytail: substring keyword allowlist. Good enough as a genre gate.
# Ceiling: "house" matches "warehouse", bare "电子" is broad. If false-positive
# rate matters, hand styles+title to DeepSeek text for one is_electronic bool
# (no schema change). Don't until a regression shows it's needed.

CLI:  python genre_filter.py --self-check
"""
from __future__ import annotations
import argparse

# Hit any of these -> electronic. Mixed zh/en, lowercased before match.
ELECTRONIC = {
    "techno", "house", "trance", "dnb", "drum and bass", "dubstep", "bass music",
    "ambient", "experimental", "electro", "acid", "breakbeat", "breaks", "hardgroove",
    "psytrance", "goa", "downtempo", "idm", "minimal", "deep house", "tech house",
    "disco", "italo", "ebm", "industrial", "gabber", "hardcore", "garage", "ukg",
    "jungle", "footwork", "juke", "leftfield", "electronic", "club night", "rave",
    "afterhours", "wave", "synth", "modular", "edm", "hard techno", "progressive house",
    "电子", "浩室", "铁克诺", "锐舞", "实验音乐", "氛围", "迷幻电子",
}
# No electronic word AND one of these -> non_electronic.
NON_ELECTRONIC = {
    "民谣", "folk", "摇滚乐队", "rock band", "乐队专场", "说唱专场", "rap show",
    "爵士现场", "jazz night", "婚礼", "wedding", "相声", "脱口秀", "stand-up",
    "古典", "classical", "合唱", "民歌", "流行演唱会", "livehouse 流行",
    "non_electronic", "non-electronic", "non electronic",
    "hiphop", "hip-hop", "嘻哈", "说唱", "rap", "jazz", "爵士", "rock", "摇滚",
    "乐队", "post-rock", "后摇", "器乐摇滚", "math rock", "instrumental rock",
    "punk", "朋克", "emo", "pop", "流行", "film", "screening", "放映",
    "tango", "acg", "funk", "swing",
    # non-music-event class that leaked into the feed (mirror in utils/genreFilter.js):
    "鸡尾酒", "cocktail", "酒节", "市集", "漫展", "喜剧", "comedy",
    "长笛", "flute", "话剧", "音乐剧", "脱口秀大会",
}


def genre_of(styles_list, text_blob=""):
    """('electronic'|'non_electronic'|'unknown', reason).

    styles_list: list of style strings already extracted by the model.
    text_blob:   optional extra context (title + event styles).
    """
    blob = (" ".join(styles_list or []) + " " + (text_blob or "")).lower()
    blob_e = (blob.replace("non_electronic", " ")
                  .replace("non-electronic", " ")
                  .replace("non electronic", " "))
    hit_e = [w for w in ELECTRONIC if w in blob_e]
    if hit_e:
        return "electronic", "style:" + ",".join(sorted(hit_e)[:3])
    hit_n = [w for w in NON_ELECTRONIC if w in blob]
    if hit_n:
        return "non_electronic", "neg:" + ",".join(sorted(hit_n)[:3])
    # ponytail: no signal -> don't drop (could be poster-only). Keep, not featured.
    return "unknown", "no_genre_signal"


def _self_check():
    assert genre_of(["Techno"])[0] == "electronic", genre_of(["Techno"])
    assert genre_of(["House", "Disco"])[0] == "electronic"
    assert genre_of(["Hiphop", "Breaks"])[0] == "electronic"
    assert genre_of(["non_electronic"])[0] == "non_electronic"
    assert genre_of(["hiphop"])[0] == "non_electronic"
    assert genre_of(["jazz"])[0] == "non_electronic"
    assert genre_of(["rock"])[0] == "non_electronic"
    assert genre_of(["民谣"], "乐队专场")[0] == "non_electronic", genre_of(["民谣"], "乐队专场")
    assert genre_of(["folk"], "wedding party")[0] == "non_electronic"
    assert genre_of([])[0] == "unknown", genre_of([])
    assert genre_of(["未知风格"])[0] == "unknown"
    print("self-check OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--styles", default="", help="comma-separated styles")
    ap.add_argument("--text", default="")
    a = ap.parse_args()
    if a.self_check:
        _self_check()
    else:
        import json
        styles = [s for s in a.styles.split(",") if s.strip()]
        print(json.dumps(genre_of(styles, a.text), ensure_ascii=False))
