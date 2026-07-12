"""Poster selection regressions for decorative animated assets."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from stage1_clean import score_candidate


def test_animated_gif_is_ranked_below_static_poster(tmp_path: Path) -> None:
    gif_path = tmp_path / "decorative.gif"
    frames = [Image.new("RGB", (640, 666), color) for color in ("black", "white")]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    jpg_path = tmp_path / "poster.jpg"
    Image.new("RGB", (1080, 1440), "navy").save(jpg_path, quality=90)

    gif_score, _, gif_penalties, gif_stats = score_candidate(
        {"asset_id": "asset#9", "content_type": "image/gif"}, gif_path, 1_200_000, 9
    )
    jpg_score, _, _, _ = score_candidate(
        {"asset_id": "asset#10", "content_type": "image/jpeg"}, jpg_path, 160_000, 10
    )

    assert gif_stats["animated"] is True
    assert "animated_gif-30" in gif_penalties
    assert gif_score < jpg_score
