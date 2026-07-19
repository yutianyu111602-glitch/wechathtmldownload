import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_atlas_activity_source_sidecar.py"
spec = importlib.util.spec_from_file_location("build_atlas_activity_source_sidecar", SCRIPT)
sidecar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidecar)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_builds_activity_sidecar_without_raw_urls(tmp_path):
    current = tmp_path / "api" / "current.json"
    source_map = tmp_path / "api" / "source_actions" / "source_url_map.json"
    write_json(
        current,
        {
            "schema_version": "weekly_activity_miniprogram_api.v1",
            "items": [
                {
                    "id": "alkaline:abc123",
                    "event_id": "alkaline:abc123",
                    "title": "5.22 周五 | Artist A",
                    "event_date_text": ["2026-05-22"],
                    "event_date_start": "2026-05-22",
                    "event_time_text": "20:30 - Late",
                    "venue_name": "南碱alkaline酒吧",
                    "address": "广州市海珠区南泰路17号",
                    "lineup_artists": ["Artist A", "Artist B"],
                    "music_styles": ["ambient"],
                    "price": ["Door 70"],
                    "ticketing_text": "Door 70",
                    "description_original_lines": [
                        "05.22(Fri.)20:30~late 广州市海珠区南泰路17号 Door 70",
                        "Artist A / Artist B",
                    ],
                    "evidence": ["2026-05-22", "20:30-late", "Door 70"],
                    "source_action": {
                        "type": "wechat_article",
                        "available": True,
                        "url_hash": "abc123",
                    },
                    "source_article": {
                        "url_hash": "abc123",
                        "account_name": "南碱Alkaline",
                        "published_at": "2026-05-13",
                    },
                    "post_date": "2026-05-13",
                    "account_key": "alkaline",
                }
            ],
        },
    )
    write_json(
        source_map,
        {
            "schema_version": "weekly_source_url_map.v1",
            "sources": {
                "abc123": {
                    "type": "wechat_article",
                    "url": "https://mp.weixin.qq.com/s/raw-token?openid=secret",
                    "account_name": "南碱Alkaline",
                    "published_at": "2026-05-13",
                    "event_id": "alkaline:abc123",
                }
            },
        },
    )

    out_dir = tmp_path / "out"
    result = sidecar.build_activity_source_sidecar(
        current,
        out_dir,
        source_map_path=source_map,
        publish_package="weekly-current-test",
    )
    summary = result["summary"]

    assert summary["decision"] == "activity_source_sidecar_built"
    assert summary["activity_events"] == 1
    assert summary["evidence_refs"] >= 8
    assert summary["events_with_source_url_hash"] == 1
    assert summary["input_hashes"]["current_sha256"]
    assert summary["input_hashes"]["source_map_sha256"]
    assert summary["safety"]["raw_url_written"] is False
    assert summary["safety"]["llm_call_executed"] is False
    assert summary["safety"]["source_db_mutated"] is False

    events_text = (out_dir / "atlas_activity_events.jsonl").read_text(encoding="utf-8")
    refs_text = (out_dir / "atlas_activity_evidence_refs.jsonl").read_text(encoding="utf-8")
    assert "https://" not in events_text
    assert "mp.weixin.qq.com" not in refs_text
    assert "openid" not in events_text
    assert "Artist A" in events_text
    assert "Door 70" in refs_text

    conn = sqlite3.connect(out_dir / "atlas_activity_source_sidecar.sqlite")
    try:
        event_count = conn.execute("SELECT count(*) FROM activity_events").fetchone()[0]
        ref_count = conn.execute("SELECT count(*) FROM evidence_refs").fetchone()[0]
        row = conn.execute(
            "SELECT lineup_artists_json, ticketing_text, source_url_hash FROM activity_events"
        ).fetchone()
    finally:
        conn.close()

    assert event_count == 1
    assert ref_count == summary["evidence_refs"]
    assert json.loads(row[0]) == ["Artist A", "Artist B"]
    assert row[1] == "Door 70"
    assert row[2].startswith("sha256:")


def test_activity_identity_does_not_change_across_publish_packages():
    item = {"event_id": "stable-event", "title": "Stable"}
    first = sidecar.build_activity_event(
        item,
        publish_package="weekly-one",
        source_map={},
        generated_at="2026-07-19T00:00:00Z",
    )
    second = sidecar.build_activity_event(
        item,
        publish_package="weekly-two",
        source_map={},
        generated_at="2026-07-20T00:00:00Z",
    )
    assert first["activity_event_id"] == second["activity_event_id"]


def test_duplicate_source_event_ids_fail_closed(tmp_path):
    current = tmp_path / "api" / "current.json"
    write_json(
        current,
        {
            "items": [
                {"event_id": "duplicate", "title": "First"},
                {"event_id": "duplicate", "title": "Second"},
            ]
        },
    )
    with pytest.raises(ValueError, match="duplicate event_id"):
        sidecar.build_activity_source_sidecar(current, tmp_path / "out", publish_package="weekly-test")
