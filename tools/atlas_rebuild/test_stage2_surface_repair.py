"""Smoke test for Stage2 entity surface repair."""
from __future__ import annotations

from schema import ArticleExtraction
import json
import tempfile
from pathlib import Path

from stage2_extract import build_user_text, expand_failure_posters, repair_entity_surfaces


def main() -> None:
    raw = {
        "events": [
            {
                "title": "Test Event",
                "date_start": "2026-06-19",
                "venue": "Test Club",
                "lineup": [{"name": "夜航西飞"}],
                "confidence": 0.9,
            }
        ],
        "entities": {
            "djs": [{"name_zh": "夜航西飞", "roles": ["live"]}],
            "venues": [{"name_en": "Test Club", "city": "上海"}],
            "orgs": [{"name": "Test Crew", "org_type": "crew"}],
            "series": [{"title": "Test Series"}],
        },
    }
    fixed = repair_entity_surfaces(raw)
    obj = ArticleExtraction.model_validate(fixed)
    assert obj.entities.djs[0].surface == "夜航西飞"
    assert obj.entities.venues[0].surface == "Test Club"
    assert obj.entities.orgs[0].surface == "Test Crew"
    assert obj.entities.series[0].surface == "Test Series"

    drift = {
        "events": [{"title": "Surface Drift", "confidence": 0.8}],
        "entities": {
            "djs": [
                {"surface": ["DJ List"]},
                {"surface": {"bad": True}, "name_en": "Fallback DJ"},
                {"surface": {"bad": True}},
            ],
            "venues": [{"surface": 404}],
        },
    }
    drift_obj = ArticleExtraction.model_validate(drift)
    assert [x.surface for x in drift_obj.entities.djs] == ["DJ List", "Fallback DJ"]
    assert drift_obj.entities.venues[0].surface == "404"

    prompt = build_user_text("今晚演出", "", [], "2026-07-09T14:39:03+08:00")
    assert "文章来源时间：2026-07-09T14:39:03+08:00" in prompt
    assert "不得把文章来源时间直接当作活动日期" in prompt

    with tempfile.TemporaryDirectory(prefix="atlas_stage2_candidates_") as td:
        root = Path(td)
        selected_path = root / "portrait.jpg"
        candidate_path = root / "poster.jpg"
        selected_path.touch()
        candidate_path.touch()
        selected = [{"asset_id": "a#1", "path": str(selected_path)}]
        candidates = [
            {"asset_id": "a#1", "path": str(selected_path)},
            {"asset_id": "a#7", "path": str(candidate_path)},
        ]
        expanded = expand_failure_posters(json.dumps(selected), json.dumps(candidates), 8)
        assert [item["asset_id"] for item in expanded] == ["a#1", "a#7"]
    print("stage2 surface repair smoke OK")


if __name__ == "__main__":
    main()
