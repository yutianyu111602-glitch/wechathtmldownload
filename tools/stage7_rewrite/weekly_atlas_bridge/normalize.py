"""Name normalization for entity matching."""
from __future__ import annotations

import re
import unicodedata

_STRIP_RE = re.compile(r"[\s\-_./\\'\u2018\u2019\u201c\u201d\u300c\u300d\uff08\uff09()\[\]{}]")
_NOISE_RE = re.compile(r"\b(?:dj|mc|live|pres|presents|sound|music|club|bar)\b", re.I)


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = _NOISE_RE.sub(" ", text)
    text = _STRIP_RE.sub("", text)
    return text.strip()


def atlas_entity_id(raw_id: str) -> str:
    rid = (raw_id or "").strip()
    if not rid:
        return ""
    if rid.startswith("atlas:entity:"):
        return rid
    return f"atlas:entity:{rid}"
