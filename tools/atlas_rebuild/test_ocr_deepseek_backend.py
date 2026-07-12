"""Regression tests for the local-OCR then text-only DeepSeek backend."""
from __future__ import annotations

import pytest

from backends import LocalOcrDeepSeekBackend


class FakeTextBackend:
    def __init__(self):
        self.last_usage = (12, 3)
        self.calls = []

    def extract(self, system_prompt, user_text, image_paths, schema):
        self.calls.append((system_prompt, user_text, image_paths, schema))
        return {"events": [], "entities": {"djs": [], "venues": [], "orgs": [], "series": []}}


def test_local_ocr_text_is_sent_to_deepseek_without_images() -> None:
    text_backend = FakeTextBackend()
    ocr_engine = lambda _path: ([[None, "上海 7月12日 22:00", 0.98]], 0.1)
    backend = LocalOcrDeepSeekBackend(
        "ocr_deepseek",
        {},
        ocr_engine=ocr_engine,
        text_backend=text_backend,
    )

    result = backend.extract("system", "article body", ["poster.jpg"], {"type": "object"})

    assert result["events"] == []
    assert len(text_backend.calls) == 1
    assert "LOCAL_POSTER_OCR" in text_backend.calls[0][1]
    assert "上海 7月12日 22:00" in text_backend.calls[0][1]
    assert text_backend.calls[0][2] == []
    assert backend.last_usage == (12, 3)


def test_local_ocr_empty_result_fails_closed() -> None:
    backend = LocalOcrDeepSeekBackend(
        "ocr_deepseek",
        {},
        ocr_engine=lambda _path: ([], 0.1),
        text_backend=FakeTextBackend(),
    )

    with pytest.raises(RuntimeError, match="refusing text-only fallback"):
        backend.extract("system", "article body", ["poster.jpg"], {"type": "object"})


def test_local_ocr_empty_result_uses_explicit_title_date_only() -> None:
    text_backend = FakeTextBackend()
    backend = LocalOcrDeepSeekBackend(
        "ocr_deepseek",
        {},
        ocr_engine=lambda _path: ([], 0.1),
        text_backend=text_backend,
    )

    backend.extract(
        "system",
        "公众号文章标题：7.16 周四｜侧耳倾听\n\n正文：\n(正文为空，信息以海报为准)",
        ["decorative.gif"],
        {"type": "object"},
    )

    assert text_backend.calls[0][2] == []
    assert "extract only explicit facts from title/body" in text_backend.calls[0][1]
