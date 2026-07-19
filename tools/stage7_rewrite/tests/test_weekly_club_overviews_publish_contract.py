from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "tools" / "stage7_rewrite" / "scripts"
MERGER_SCRIPT = SCRIPTS / "merge_weekly_incremental_api_package.py"
VERIFY_SCRIPT = SCRIPTS / "verify_weekly_club_overviews_remote.py"
PUBLISH_WRAPPER = REPO / "tools" / "stage7_rewrite" / "run_openclaw_weekly_daily_publish.ps1"


def load_module(name: str, path: Path):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def overview_payload(club: str, url_suffix: str, *, generated_at: str) -> dict:
    item = {
        "record_type": "club_overview_parent",
        "parent_aggregate": True,
        "include_in_activity_feed": False,
        "source_table": "wechat_article",
        "club_fakeid": "private-fixture-id",
        "club": club,
        "title": f"{club} weekly",
        "publish_date": "2026-07-18",
        "original_url": f"https://mp.weixin.qq.com/s/{url_suffix}",
        "cover_url": f"https://mmbiz.qpic.cn/{url_suffix}.jpg",
        "window_kind": "week",
        "window_label": "7.18-7.24",
        "window_start": "2026-07-18",
        "window_end": "2026-07-24",
    }
    return {
        "schema_version": "club_overviews.v1",
        "generated_at": generated_at,
        "as_of_date": "2026-07-18",
        "source": "sanji.db (fixture)",
        "club_count": 1,
        "overview_count": 1,
        "kind_counts": {"week": 1},
        "by_club": {club: [item]},
    }


def write_release(directory: Path, item_id: str, overview: dict) -> None:
    item = {
        "id": item_id,
        "title": item_id,
        "city": "上海",
        "event_date": "2026-07-18",
        "poster": "cloud://fixture/weekly-posters/20260718/poster.jpg",
    }
    write_json(
        directory / "current.json",
        {
            "schema_version": "weekly_activity_miniprogram_current.v1",
            "generated_at": "2026-07-18T00:00:00+08:00",
            "item_count": 1,
            "items": [item],
        },
    )
    write_json(
        directory / "manifest.json",
        {
            "schema_version": "weekly_activity_miniprogram_api.v1",
            "generated_at": "2026-07-18T00:00:00+08:00",
            "item_count": 1,
        },
    )
    write_json(directory / "club_overviews.json", overview)


def test_incremental_merge_replaces_stale_base_club_overviews(tmp_path: Path) -> None:
    merger = load_module("weekly_incremental_merge_club_overviews_test", MERGER_SCRIPT)
    base = tmp_path / "base"
    incremental = tmp_path / "incremental"
    merged = tmp_path / "merged"
    base_overview = overview_payload("Stale Club", "stale", generated_at="2026-07-17T00:00:00+08:00")
    incremental_overview = overview_payload("Fresh Club", "fresh", generated_at="2026-07-18T00:00:00+08:00")
    write_release(base, "base-event", base_overview)
    write_release(incremental, "incremental-event", incremental_overview)

    report = merger.merge_package(base, incremental, merged, None, overwrite=False)

    assert json.loads((merged / "club_overviews.json").read_text(encoding="utf-8")) == incremental_overview
    assert report["club_overviews"]["schema_version"] == "club_overviews.v1"
    assert report["club_overviews"]["club_count"] == 1
    assert report["club_overviews"]["overview_count"] == 1
    assert report["club_overviews"]["source"] == str(incremental / "club_overviews.json")


@pytest.mark.parametrize(
    "broken_payload, message",
    [
        ({"schema_version": "club_overviews.v0", "by_club": {}}, "schema_version"),
        ({"schema_version": "club_overviews.v1", "by_club": []}, "by_club"),
    ],
)
def test_incremental_merge_rejects_invalid_club_overviews_before_output_mutation(
    tmp_path: Path, broken_payload: dict, message: str
) -> None:
    merger = load_module(f"weekly_incremental_merge_invalid_{message}_test", MERGER_SCRIPT)
    base = tmp_path / "base"
    incremental = tmp_path / "incremental"
    merged = tmp_path / "merged"
    write_release(base, "base-event", overview_payload("Stale Club", "stale", generated_at="old"))
    write_release(incremental, "incremental-event", broken_payload)
    merged.mkdir()
    sentinel = merged / "must-remain.txt"
    sentinel.write_text("unchanged", encoding="utf-8")

    with pytest.raises(SystemExit, match=message):
        merger.merge_package(base, incremental, merged, None, overwrite=True)

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_incremental_merge_rejects_overview_that_backend_would_filter_out(tmp_path: Path) -> None:
    merger = load_module("weekly_incremental_merge_filtered_overview_test", MERGER_SCRIPT)
    base = tmp_path / "base"
    incremental = tmp_path / "incremental"
    merged = tmp_path / "merged"
    write_release(base, "base-event", overview_payload("Stale Club", "stale", generated_at="old"))
    broken = overview_payload("Fresh Club", "fresh", generated_at="new")
    broken["by_club"]["Fresh Club"][0]["cover_url"] = ""
    write_release(incremental, "incremental-event", broken)

    with pytest.raises(SystemExit, match="cover_url"):
        merger.merge_package(base, incremental, merged, None, overwrite=False)

    assert not merged.exists()


def test_remote_verifier_compares_backend_normalized_exact_summary() -> None:
    verifier = load_module("weekly_club_overviews_remote_verifier_test", VERIFY_SCRIPT)
    candidate = overview_payload("Fresh Club", "fresh", generated_at="2026-07-18T00:00:00+08:00")
    remote = verifier.normalize_club_overviews(candidate)

    candidate_snapshot = verifier.build_snapshot(candidate, source="candidate")
    remote_snapshot = verifier.build_snapshot(remote, source="remote")

    verifier.assert_matching_snapshots(candidate_snapshot, remote_snapshot)
    assert candidate_snapshot["club_count"] == 1
    assert candidate_snapshot["overview_count"] == 1
    assert candidate_snapshot["summary_sha256"] == remote_snapshot["summary_sha256"]


def test_remote_verifier_candidate_report_carries_raw_file_digest(tmp_path: Path) -> None:
    verifier = load_module("weekly_club_overviews_candidate_file_digest_test", VERIFY_SCRIPT)
    candidate = overview_payload("Fresh Club", "fresh", generated_at="2026-07-18T00:00:00+08:00")
    candidate_path = tmp_path / "club_overviews.json"
    write_json(candidate_path, candidate)

    loaded_path, _payload, snapshot = verifier.load_candidate(tmp_path)

    assert loaded_path == candidate_path
    assert snapshot["file_sha256"] == verifier.sha256_file(candidate_path)
    assert len(snapshot["file_sha256"]) == 64


def test_remote_verifier_requires_bound_successful_smoke(tmp_path: Path) -> None:
    verifier = load_module("weekly_club_overviews_smoke_binding_test", VERIFY_SCRIPT)
    binding = {
        "transaction_id": "weekly-run-003",
        "env_id": "env-test",
        "service_name": "weekly-api",
        "deploy_context_fingerprint": "a" * 64,
        "deploy_zip_sha256": "b" * 64,
        "publish_lease_token_sha256": "d" * 64,
        "expected_generation_id": "sha256:" + "c" * 64,
        "remote_generation_id": "sha256:" + "c" * 64,
        "active_version": "weekly-api-126",
        "base_url": "https://weekly.example.invalid",
    }
    smoke_path = tmp_path / "smoke.json"
    write_json(
        smoke_path,
        {
            "schema_version": "stage7_cloudrun_weekly_production_smoke.v2",
            "ok": True,
            "decision": "cloudrun_weekly_production_smoke_ready",
            "evidence_binding": binding,
        },
    )

    assert verifier.load_smoke_binding(smoke_path) == binding
    verifier.assert_base_url_binding("https://weekly.example.invalid/", binding)
    with pytest.raises(ValueError, match="base URL"):
        verifier.assert_base_url_binding("https://wrong.example.invalid", binding)

    broken = dict(binding)
    broken["remote_generation_id"] = "sha256:" + "d" * 64
    write_json(
        smoke_path,
        {
            "schema_version": "stage7_cloudrun_weekly_production_smoke.v2",
            "ok": True,
            "decision": "cloudrun_weekly_production_smoke_ready",
            "evidence_binding": broken,
        },
    )
    with pytest.raises(ValueError, match="generation"):
        verifier.load_smoke_binding(smoke_path)


def test_remote_verifier_rejects_same_count_with_different_overview_summary() -> None:
    verifier = load_module("weekly_club_overviews_remote_mismatch_test", VERIFY_SCRIPT)
    candidate = overview_payload("Fresh Club", "fresh", generated_at="2026-07-18T00:00:00+08:00")
    remote = verifier.normalize_club_overviews(candidate)
    remote["by_club"]["Fresh Club"][0]["original_url"] = "https://mp.weixin.qq.com/s/different"

    with pytest.raises(ValueError, match="summary digest"):
        verifier.assert_matching_snapshots(
            verifier.build_snapshot(candidate, source="candidate"),
            verifier.build_snapshot(remote, source="remote"),
        )


def test_publish_wrapper_verifies_club_overviews_before_transaction_promotion() -> None:
    script = PUBLISH_WRAPPER.read_text(encoding="utf-8")
    deploy_at = script.index("direct_cloudbase_deploy.py")
    pagination_at = script.index("Assert-RemotePagination", deploy_at)
    club_at = script.index("verify_weekly_club_overviews_remote.py", pagination_at)
    promote_at = script.index("--promote-transaction", club_at)

    assert deploy_at < pagination_at < club_at < promote_at
    assert '"/api/v1/weekly/club-overviews"' in (
        VERIFY_SCRIPT.read_text(encoding="utf-8") if VERIFY_SCRIPT.exists() else ""
    )
    assert "club_overviews_report = $CloudRunClubOverviewsReportPath" in script
    assert "Assert-NativeSuccess \"CloudRun club-overviews reconciliation\"" in script
