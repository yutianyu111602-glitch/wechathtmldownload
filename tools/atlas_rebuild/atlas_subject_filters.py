#!/usr/bin/env python3
"""Small shared semantic filters used by public ATLAS exporters."""

from __future__ import annotations

import re


PLACEHOLDER_NORMS = {
    "未知", "未明确", "未明确说明", "不详", "待定", "待公布", "敬请期待",
    "神秘嘉宾", "神秘", "嘉宾", "特邀嘉宾", "神秘dj", "惊喜嘉宾", "神秘客人",
    "unknown", "unk", "na", "none", "null", "tbd", "tba",
    "guest", "specialguest", "surpriseguest", "mysteryguest", "secretguest", "surprise",
}
B2B_RE = re.compile(r"(^|\s)(b\s*2\s*b|back\s*[- ]?to\s*[- ]?back)(\s|$)", re.I)


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[\s\-_·•|/\\:：,，.。()（）\[\]【】]+", "", str(value).strip().lower())


def is_placeholder_subject(subject_id: str, subject_type: str, name: str) -> str | None:
    sid = _norm(subject_id)
    sid_tail = _norm(str(subject_id or "").split(":")[-1])
    subject_kind = _norm(subject_type)
    normalized_name = _norm(name)
    if normalized_name in PLACEHOLDER_NORMS or sid_tail in PLACEHOLDER_NORMS:
        return "placeholder_subject"
    if subject_kind == "dj" and (sid == "djb2b" or sid.endswith(":b2b") or normalized_name == "b2b"):
        return "fake_b2b_dj_subject"
    if subject_kind == "dj" and B2B_RE.search(name or ""):
        return "compound_b2b_dj_subject"
    return None
