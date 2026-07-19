from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[3]
BAKE_SCRIPT = REPO / "services" / "weekly_activity_cloudrun" / "scripts" / "bake_and_deploy.py"
PUBLISH_WRAPPER = REPO / "tools" / "stage7_rewrite" / "run_openclaw_weekly_daily_publish.ps1"


def load_bake_module():
    spec = importlib.util.spec_from_file_location("weekly_publish_transaction_test", BAKE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_release(directory: Path, item_id: str, generated_at: str) -> None:
    item = {"id": item_id, "title": item_id}
    write_json(directory / "current.json", {"items": [item]})
    write_json(
        directory / "manifest.json",
        {
            "schema_version": "weekly_activity_miniprogram_api.v1",
            "generated_at": generated_at,
            "item_count": 1,
        },
    )
    write_json(directory / "column.json", {"items": [{"id": f"column-{item_id}"}]})
    for name in ("by-city", "by-date", "by-id"):
        (directory / name).mkdir(parents=True, exist_ok=True)
        write_json(directory / name / "index.json", {"item_id": item_id})
    write_json(
        directory / "llm" / "weekly_summary.json",
        {"itemCount": 1, "generatedAt": generated_at, "summary": {}},
    )
    write_json(
        directory / "llm" / "enrichment_index.json",
        {
            "itemCount": 1,
            "generatedAt": generated_at,
            "enrichments": [{"id": item_id}],
        },
    )
    write_json(
        directory / "llm" / "materialize_report.json",
        {
            "itemCount": 1,
            "enrichWritten": 1,
            "generatedAt": generated_at,
        },
    )
    write_json(
        directory / "club_overviews.json",
        {
            "schema_version": "club_overviews.v1",
            "generated_at": generated_at,
            "as_of_date": "2026-07-18",
            "source": "sanji.db (fixture)",
            "club_count": 1,
            "overview_count": 1,
            "kind_counts": {"week": 1},
            "by_club": {
                "Fixture Club": [
                    {
                        "record_type": "club_overview_parent",
                        "parent_aggregate": True,
                        "include_in_activity_feed": False,
                        "club": "Fixture Club",
                        "title": f"overview-{item_id}",
                        "publish_date": "2026-07-18",
                        "original_url": f"https://mp.weixin.qq.com/s/{item_id}",
                        "cover_url": f"https://mmbiz.qpic.cn/{item_id}.jpg",
                        "window_kind": "week",
                        "window_label": "7.18-7.24",
                        "window_start": "2026-07-18",
                        "window_end": "2026-07-24",
                    }
                ]
            },
        },
    )


def tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def configure_fixture(bake, tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    data_root = tmp_path / "state" / "data"
    work_root = tmp_path / "state" / "work"
    current_release = data_root / "current_release"
    candidate = tmp_path / "candidate"
    write_release(current_release, "old-event", "2026-07-17T00:00:00+08:00")
    write_release(candidate, "new-event", "2026-07-18T00:00:00+08:00")
    write_json(data_root / "source_actions" / "source_url_map.json", {"old-event": "https://old.invalid"})
    for name in bake.MINIAPP_ATLAS_INDEX_ITEMS:
        path = data_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"atlas:{name}".encode("utf-8"))
    source_map = candidate / "source_actions" / "source_url_map.json"
    write_json(source_map, {"new-event": "https://new.invalid"})
    bake.configure_runtime_paths(
        data_root=str(data_root),
        current_release_dir=str(current_release),
        work_root=str(work_root),
        production_write=True,
    )
    return data_root, work_root, current_release, candidate


def test_prepare_transaction_leaves_authoritative_release_byte_identical(tmp_path: Path) -> None:
    bake = load_bake_module()
    _data_root, work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    before = tree_digest(current_release)

    result = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-001",
        include_stage7_atlas=False,
        update_column_json=False,
    )

    assert tree_digest(current_release) == before
    assert json.loads((current_release / "current.json").read_text(encoding="utf-8"))["items"][0]["id"] == "old-event"
    assert result["status"] == "prepared"
    context_current = work_root / "publish_transactions" / "run-001" / "deploy_context" / "data" / "current_release" / "current.json"
    assert json.loads(context_current.read_text(encoding="utf-8"))["items"][0]["id"] == "new-event"


def test_prepare_blocks_candidate_that_cloudrun_would_normalize_to_missing_overviews(tmp_path: Path) -> None:
    bake = load_bake_module()
    _data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    before = tree_digest(current_release)
    club_path = candidate / "club_overviews.json"
    payload = json.loads(club_path.read_text(encoding="utf-8"))
    payload["by_club"]["Fixture Club"][0]["cover_url"] = ""
    write_json(club_path, payload)

    with pytest.raises(ValueError, match="club_count mismatch|overview_count mismatch"):
        bake.prepare_publish_transaction(
            release_dir=candidate,
            source_url_map=candidate / "source_actions" / "source_url_map.json",
            transaction_id="run-invalid-club-overviews",
            include_stage7_atlas=False,
            update_column_json=False,
        )

    assert tree_digest(current_release) == before


def test_promotion_is_blocked_when_remote_smoke_failed(tmp_path: Path) -> None:
    bake = load_bake_module()
    _data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-smoke-failed",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    before = tree_digest(current_release)
    evidence = tmp_path / "evidence"
    deploy_report = evidence / "deploy.json"
    smoke_report = evidence / "smoke.json"
    pagination_report = evidence / "pagination.json"
    club_overviews_report = evidence / "club-overviews.json"
    write_json(
        deploy_report,
        {"ok": True, "safety": {"cloud_deploy_executed": True}},
    )
    write_json(smoke_report, {"ok": False, "decision": "cloudrun_weekly_production_smoke_blocked"})
    write_json(
        pagination_report,
        {
            "ok": True,
            "decision": "cloudrun_remote_pagination_verified",
            "remote_item_id_count": prepared["candidate_item_count"],
        },
    )

    with pytest.raises(ValueError, match="smoke"):
        bake.promote_publish_transaction(
            transaction_id="run-smoke-failed",
            deploy_report_path=deploy_report,
            smoke_report_path=smoke_report,
            pagination_report_path=pagination_report,
            club_overviews_report_path=club_overviews_report,
        )

    assert tree_digest(current_release) == before
    report = json.loads(
        Path(prepared["paths"]["transaction_dir"])
        .joinpath("publish_transaction.json")
        .read_text(encoding="utf-8")
    )
    assert report["status"] == "promotion_blocked"


def write_success_evidence(root: Path, prepared: dict) -> tuple[Path, Path, Path, Path]:
    deploy_report = root / "deploy.json"
    smoke_report = root / "smoke.json"
    pagination_report = root / "pagination.json"
    club_overviews_report = root / "club-overviews.json"
    write_json(deploy_report, {"ok": True, "safety": {"cloud_deploy_executed": True}})
    write_json(smoke_report, {"ok": True, "decision": "cloudrun_weekly_production_smoke_ready"})
    ids = prepared["candidate_item_ids"]
    write_json(
        pagination_report,
        {
            "ok": True,
            "decision": "cloudrun_remote_pagination_verified",
            "scope": "package",
            "remote_item_id_count": ids["unique_item_id_count"],
            "remote_item_id_digest": ids["item_id_digest"],
            "digest_algorithm": ids["digest_algorithm"],
        },
    )
    club_candidate = prepared["candidate_club_overviews"]
    club_remote = {key: value for key, value in club_candidate.items() if key != "file_sha256"}
    club_remote["source"] = "remote"
    write_json(
        club_overviews_report,
        {
            "schema_version": "cloudrun_club_overviews_reconciliation.v1",
            "ok": True,
            "decision": "cloudrun_club_overviews_reconciled",
            "candidate": club_candidate,
            "remote": club_remote,
        },
    )
    return deploy_report, smoke_report, pagination_report, club_overviews_report


def test_successful_promotion_swaps_candidate_and_keeps_versioned_backup(tmp_path: Path) -> None:
    bake = load_bake_module()
    data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    old_column = (current_release / "column.json").read_bytes()
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-success",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    deploy_report, smoke_report, pagination_report, club_overviews_report = write_success_evidence(
        tmp_path / "evidence", prepared
    )

    promoted = bake.promote_publish_transaction(
        transaction_id="run-success",
        deploy_report_path=deploy_report,
        smoke_report_path=smoke_report,
        pagination_report_path=pagination_report,
        club_overviews_report_path=club_overviews_report,
    )

    current = json.loads((current_release / "current.json").read_text(encoding="utf-8"))
    assert current["items"][0]["id"] == "new-event"
    assert (current_release / "column.json").read_bytes() == old_column
    source_map = json.loads((data_root / "source_actions" / "source_url_map.json").read_text(encoding="utf-8"))
    assert source_map == {"new-event": "https://new.invalid"}
    assert promoted["status"] == "promoted"
    backup = Path(promoted["promotion"]["backup_dir"])
    assert json.loads((backup / "current_release" / "current.json").read_text(encoding="utf-8"))["items"][0]["id"] == "old-event"
    assert json.loads((backup / "source_actions" / "source_url_map.json").read_text(encoding="utf-8")) == {
        "old-event": "https://old.invalid"
    }


def test_promotion_error_restores_authoritative_package_and_source_map(tmp_path: Path, monkeypatch) -> None:
    bake = load_bake_module()
    data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-rollback",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    before_release = tree_digest(current_release)
    before_source = (data_root / "source_actions" / "source_url_map.json").read_bytes()
    deploy_report, smoke_report, pagination_report, club_overviews_report = write_success_evidence(
        tmp_path / "evidence", prepared
    )
    transaction_dir = Path(prepared["paths"]["transaction_dir"])
    staged_source = transaction_dir / "staged_data" / "source_actions" / "source_url_map.json"
    authoritative_source = data_root / "source_actions" / "source_url_map.json"
    original_replace = bake.os.replace
    injected = {"done": False}

    def fail_candidate_source_swap(source, destination):
        if Path(source) == staged_source and Path(destination) == authoritative_source and not injected["done"]:
            injected["done"] = True
            raise OSError("injected source promotion failure")
        return original_replace(source, destination)

    monkeypatch.setattr(bake.os, "replace", fail_candidate_source_swap)
    with pytest.raises(RuntimeError, match="baseline_restored=True"):
        bake.promote_publish_transaction(
            transaction_id="run-rollback",
            deploy_report_path=deploy_report,
            smoke_report_path=smoke_report,
            pagination_report_path=pagination_report,
            club_overviews_report_path=club_overviews_report,
        )

    assert tree_digest(current_release) == before_release
    assert authoritative_source.read_bytes() == before_source
    report = json.loads((transaction_dir / "publish_transaction.json").read_text(encoding="utf-8"))
    assert report["status"] == "promotion_failed_restored"
    assert report["baseline_restored"] is True


def test_prepare_refuses_to_reuse_named_transaction(tmp_path: Path) -> None:
    bake = load_bake_module()
    _data_root, _work_root, _current_release, candidate = configure_fixture(bake, tmp_path)
    kwargs = {
        "release_dir": candidate,
        "source_url_map": candidate / "source_actions" / "source_url_map.json",
        "transaction_id": "run-no-reuse",
        "include_stage7_atlas": False,
        "update_column_json": False,
    }
    bake.prepare_publish_transaction(**kwargs)
    with pytest.raises(FileExistsError, match="will not be silently reused"):
        bake.prepare_publish_transaction(**kwargs)


def test_same_remote_count_with_different_item_id_digest_cannot_promote(tmp_path: Path) -> None:
    bake = load_bake_module()
    _data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-digest-mismatch",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    before = tree_digest(current_release)
    deploy_report, smoke_report, pagination_report, club_overviews_report = write_success_evidence(
        tmp_path / "evidence", prepared
    )
    pagination = json.loads(pagination_report.read_text(encoding="utf-8"))
    pagination["remote_item_id_digest"] = "0" * 64
    write_json(pagination_report, pagination)

    with pytest.raises(ValueError, match="pagination_id_digest_matches_candidate"):
        bake.promote_publish_transaction(
            transaction_id="run-digest-mismatch",
            deploy_report_path=deploy_report,
            smoke_report_path=smoke_report,
            pagination_report_path=pagination_report,
            club_overviews_report_path=club_overviews_report,
        )
    assert tree_digest(current_release) == before


def test_matching_club_counts_with_different_summary_digest_cannot_promote(tmp_path: Path) -> None:
    bake = load_bake_module()
    _data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-club-digest-mismatch",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    before = tree_digest(current_release)
    deploy_report, smoke_report, pagination_report, club_overviews_report = write_success_evidence(
        tmp_path / "evidence", prepared
    )
    club_evidence = json.loads(club_overviews_report.read_text(encoding="utf-8"))
    club_evidence["remote"]["summary_sha256"] = "0" * 64
    write_json(club_overviews_report, club_evidence)

    with pytest.raises(ValueError, match="club-overviews evidence"):
        bake.promote_publish_transaction(
            transaction_id="run-club-digest-mismatch",
            deploy_report_path=deploy_report,
            smoke_report_path=smoke_report,
            pagination_report_path=pagination_report,
            club_overviews_report_path=club_overviews_report,
        )
    assert tree_digest(current_release) == before


def test_openclaw_wrapper_promotes_only_after_smoke_and_full_pagination() -> None:
    script = PUBLISH_WRAPPER.read_text(encoding="utf-8")
    prepare_at = script.index("--prepare-only")
    deploy_at = script.index("direct_cloudbase_deploy.py", prepare_at)
    smoke_at = script.index("smoke_cloudrun_weekly_production.py", deploy_at)
    pagination_at = script.index("Assert-RemotePagination", smoke_at)
    club_overviews_at = script.index("verify_weekly_club_overviews_remote.py", pagination_at)
    promote_at = script.index("--promote-transaction", club_overviews_at)

    assert prepare_at < deploy_at < smoke_at < pagination_at < club_overviews_at < promote_at
    assert "--transaction-id $RunId" in script
    assert "scope=package&limit=100" in script
    assert "lookbackDays=999" not in script
    assert 'scope = "package"' in script
    assert "--max-wait-seconds 900" in script
    assert "--timeout-seconds 30" in script
    assert "--no-timeout" not in script
    assert script.count("-TimeoutSec 30") >= 3
    assert "remote_item_id_digest" in script
    assert "cloudrun_remote_pagination.json" in script
    assert "--club-overviews-report $CloudRunClubOverviewsReportPath" in script
    assert 'decision = if ($deployMayHaveChangedRemote) { "remote_rollback_required" }' in script
    assert "automatic_rollback_executed = $false" in script
    assert "previous_server_identity" in script
    assert "post_update_server_identity" in script
