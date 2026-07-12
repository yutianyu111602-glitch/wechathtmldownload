"""Smoke test for Stage2 entity surface repair."""
from __future__ import annotations

from schema import ArticleExtraction
from stage2_extract import repair_entity_surfaces


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
    print("stage2 surface repair smoke OK")


if __name__ == "__main__":
    main()
