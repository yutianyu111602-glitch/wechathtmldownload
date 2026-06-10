"""Text chunker for Chinese articles."""
from __future__ import annotations
import re
import hashlib
from dataclasses import dataclass
from typing import List


@dataclass
class Chunk:
    chunk_id: str
    chunk_index: int
    char_start: int
    char_end: int
    text_sha1: str
    chars: int
    text: str


@dataclass
class ChunkPlan:
    article_uid: str
    chunk_count: int
    strategy: str
    chunks: List[Chunk]


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _split_long_paragraph(para: str, max_chars: int) -> list[str]:
    """Split a single overlong paragraph so chunk max_chars is a real cap."""
    para = para.strip()
    if len(para) <= max_chars:
        return [para] if para else []

    pieces: list[str] = []
    current = ""
    # Prefer semantic-ish boundaries but keep delimiters.
    parts = re.split(r"(?<=[。！？!?；;])|\n|(?<=\s)", para)
    for part in parts:
        if not part:
            continue
        # If a token itself is over max (common for URL walls), hard slice it.
        while len(part) > max_chars:
            head, part = part[:max_chars], part[max_chars:]
            if current:
                pieces.append(current.rstrip())
                current = ""
            pieces.append(head.rstrip())
        if not part:
            continue
        if current and len(current) + len(part) > max_chars:
            pieces.append(current.rstrip())
            current = part
        else:
            current += part
    if current.strip():
        pieces.append(current.strip())
    return [p for p in pieces if p]


def _split_paragraphs(text: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    out: list[str] = []
    for para in paragraphs:
        out.extend(_split_long_paragraph(para, max_chars=max_chars))
    return out


def chunk_article(article_uid: str, text: str, target_chars: int = 4200, max_chars: int = 6000, min_chars: int = 800) -> ChunkPlan:
    """Split article text into paragraph-aware chunks.

    Guarantees every emitted chunk is <= max_chars. Older code treated max_chars
    as a soft boundary; this caused giant URL/media paragraphs to exceed model
    context and made timeout/hit-limit behavior unpredictable.
    """
    if not text:
        return ChunkPlan(article_uid=article_uid, chunk_count=0, strategy="paragraph_aware_v2_hard_cap", chunks=[])

    max_chars = max(1, int(max_chars))
    target_chars = max(1, min(int(target_chars), max_chars))
    min_chars = max(0, min(int(min_chars), max_chars))
    paragraphs = _split_paragraphs(text, max_chars=max_chars)

    chunks: List[Chunk] = []
    current_text = ""
    current_start = 0
    consumed = 0
    chunk_index = 0

    def flush_current() -> None:
        nonlocal current_text, current_start, consumed, chunk_index
        if not current_text:
            return
        _finalize_chunk(chunks, article_uid, chunk_index, current_text, current_start)
        chunk_index += 1
        consumed += len(current_text)
        current_start = consumed
        current_text = ""

    for para in paragraphs:
        if not para:
            continue
        sep = "\n\n" if current_text else ""
        would_len = len(current_text) + len(sep) + len(para)
        if current_text and would_len > max_chars:
            flush_current()
            sep = ""
        if len(para) > max_chars:
            # Defensive; _split_paragraphs should already prevent this.
            for part in _split_long_paragraph(para, max_chars=max_chars):
                if current_text and len(current_text) + len(part) + 2 > max_chars:
                    flush_current()
                current_text = f"{current_text}\n\n{part}" if current_text else part
                if len(current_text) >= target_chars:
                    flush_current()
            continue
        current_text = f"{current_text}{sep}{para}" if current_text else para
        if len(current_text) >= target_chars:
            flush_current()

    if current_text:
        if len(current_text) < min_chars and chunks:
            last = chunks[-1]
            merged = last.text + "\n\n" + current_text
            if len(merged) <= max_chars:
                last.text = merged
                last.char_end = last.char_start + len(merged)
                last.chars = len(merged)
                last.text_sha1 = sha1_text(merged)
                last.chunk_id = f"{article_uid}:{last.chunk_index:03d}"
            else:
                flush_current()
        else:
            flush_current()

    return ChunkPlan(
        article_uid=article_uid,
        chunk_count=len(chunks),
        strategy="paragraph_aware_v2_hard_cap",
        chunks=chunks,
    )


def _finalize_chunk(chunks: List[Chunk], article_uid: str, chunk_index: int, text: str, char_start: int) -> None:
    if not text:
        return
    chunks.append(Chunk(
        chunk_id=f"{article_uid}:{chunk_index:03d}",
        chunk_index=chunk_index,
        char_start=char_start,
        char_end=char_start + len(text),
        text_sha1=sha1_text(text),
        chars=len(text),
        text=text,
    ))
