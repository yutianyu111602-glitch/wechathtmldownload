from __future__ import annotations

import contextlib
import gzip
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
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
    generation_id = "sha256:" + hashlib.sha256(item_id.encode("utf-8")).hexdigest()
    item = {
        "id": item_id,
        "title": item_id,
        "city_key": "shanghai",
        "city_keys": ["shanghai"],
        "city": ["上海"],
        "event_date_start": "2026-07-24",
        "event_date_end": "2026-07-24",
        "event_date_iso_guess": "2026-07-24",
        "event_date_iso_guesses": ["2026-07-24"],
        "detail_path": f"by-id/{item_id}.json",
    }
    write_json(
        directory / "current.json",
        {"generated_at": generated_at, "generation_id": generation_id, "items": [item]},
    )
    write_json(
        directory / "manifest.json",
        {
            "schema_version": "weekly_activity_miniprogram_api.v1",
            "generated_at": generated_at,
            "generation_id": generation_id,
            "item_count": 1,
        },
    )
    write_json(directory / "column.json", {"items": [{"id": f"column-{item_id}"}]})
    write_json(directory / "by-id" / f"{item_id}.json", {
        "schema_version": "weekly_activity_miniprogram_detail.v1",
        "generated_at": generated_at,
        "generation_id": generation_id,
        "item": item,
    })
    write_json(directory / "by-city" / "shanghai.json", {
        "schema_version": "weekly_activity_miniprogram_city.v1",
        "generated_at": generated_at,
        "generation_id": generation_id,
        "scope": "package",
        "city_key": "shanghai",
        "city": "上海",
        "item_count": 1,
        "items": [item],
    })
    write_json(directory / "by-city" / "index.json", {
        "schema_version": "weekly_activity_miniprogram_city_index.v1",
        "generated_at": generated_at,
        "generation_id": generation_id,
        "scope": "package",
        "item_count": 1,
        "city_count": 1,
        "cities": [{"city_key": "shanghai", "city": "上海", "count": 1, "path": "by-city/shanghai.json"}],
    })
    write_json(directory / "by-date" / "2026-07-24.json", {
        "schema_version": "weekly_activity_miniprogram_date.v1",
        "generated_at": generated_at,
        "generation_id": generation_id,
        "scope": "package",
        "date": "2026-07-24",
        "item_count": 1,
        "items": [item],
    })
    write_json(directory / "by-date" / "index.json", {
        "schema_version": "weekly_activity_miniprogram_date_index.v1",
        "generated_at": generated_at,
        "generation_id": generation_id,
        "scope": "package",
        "item_count": 1,
        "date_count": 1,
        "dates": [{"date": "2026-07-24", "count": 1, "path": "by-date/2026-07-24.json"}],
    })
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
    write_json(
        data_root / "source_actions" / "source_url_map.json",
        {
            "schema_version": "weekly_activity_source_url_map.v1",
            "source_count": 1,
            "sources": {
                "a" * 16: {
                    "url": "https://old.invalid/article",
                    "event_id": "old-event",
                }
            },
        },
    )
    for name in bake.MINIAPP_ATLAS_INDEX_ITEMS:
        path = data_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"atlas:{name}".encode("utf-8"))
    source_map = candidate / "source_actions" / "source_url_map.json"
    write_json(
        source_map,
        {
            "schema_version": "weekly_activity_source_url_map.v1",
            "source_count": 1,
            "sources": {
                "b" * 16: {
                    "url": "https://new.invalid/article",
                    "event_id": "new-event",
                }
            },
        },
    )
    bake.configure_runtime_paths(
        data_root=str(data_root),
        current_release_dir=str(current_release),
        work_root=str(work_root),
        production_write=True,
    )
    return data_root, work_root, current_release, candidate


def configure_bio_assets(data_root: Path, *, include_db: bool = True) -> tuple[Path, Path]:
    index_path = data_root / "atlas_index.json.gz"
    db_path = data_root / "atlas_miniapp.sqlite"
    index_payload = {
        "profiles": {"dj:Alice": {"n": "Alice", "b": "", "bs": ""}},
        "bio_atoms": {
            "dj:Alice": [
                {
                    "t": "Alice is a Shanghai based producer and selector known for deep electronic music.",
                    "cf": 0.9,
                    "sr": "fixture:alice",
                    "lang": "en",
                }
            ]
        },
    }
    index_path.write_bytes(
        gzip.compress(
            json.dumps(index_payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            mtime=0,
        )
    )
    if include_db:
        connection = sqlite3.connect(db_path)
        connection.execute(
            """
            CREATE TABLE dj_profile (
                dj_id TEXT PRIMARY KEY,
                display_name TEXT,
                normalized_name TEXT,
                bio TEXT,
                bio_source TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?)",
            ("dj-alice", "Alice", "alice", "", ""),
        )
        connection.commit()
        connection.close()
    return index_path, db_path


def test_publish_promotion_lock_rejects_a_second_process(tmp_path: Path) -> None:
    bake = load_bake_module()
    lock_path = tmp_path / "state" / "publish-promotion.lock"
    child_code = """
import importlib.util
import sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("weekly_publish_lock_holder", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
with module.publish_promotion_lock(Path(sys.argv[2])):
    print("locked", flush=True)
    sys.stdin.readline()
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", child_code, str(BAKE_SCRIPT), str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(bake.PublishPromotionLockError, match="already held"):
            with bake.publish_promotion_lock(lock_path):
                pytest.fail("a second process must not enter the promotion lane")
    finally:
        if holder.poll() is None and holder.stdin is not None:
            holder.stdin.write("release\n")
            holder.stdin.flush()
        holder.wait(timeout=10)
    assert holder.returncode == 0, holder.stderr.read() if holder.stderr else ""


def test_service_publish_lease_is_scoped_and_validates_the_live_holder(tmp_path: Path) -> None:
    bake = load_bake_module()
    data_root = tmp_path / "runtime" / "data"
    transaction_id = "run-service-lease"
    token = "a" * 32
    lease_path = bake.service_publish_lease_path(
        data_root,
        bake.ENV_ID,
        bake.SERVICE_NAME,
    )
    other_path = bake.service_publish_lease_path(
        data_root,
        bake.ENV_ID,
        "another-service",
    )
    assert lease_path != other_path

    metadata_path = bake.service_publish_lease_metadata_path(lease_path)
    quote_ps = lambda value: "'" + str(value).replace("'", "''") + "'"
    child_code = f"""
$leasePath = {quote_ps(lease_path)}
$metadataPath = {quote_ps(metadata_path)}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $leasePath) | Out-Null
$stream = [System.IO.FileStream]::new($leasePath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::ReadWrite)
try {{
    if ($stream.Length -eq 0) {{ $stream.WriteByte(0); $stream.Flush($true) }}
    $stream.Position = 0
    $stream.Lock(0, 1)
    $metadata = [ordered]@{{
        schema_version = 'weekly_cloudrun_service_publish_lease.v1'
        lease_token = {quote_ps(token)}
        transaction_id = {quote_ps(transaction_id)}
        env_id = {quote_ps(bake.ENV_ID)}
        service_name = {quote_ps(bake.SERVICE_NAME)}
        owner_pid = $PID
    }}
    [System.IO.File]::WriteAllText($metadataPath, ($metadata | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
    [Console]::Out.WriteLine('locked')
    [Console]::Out.Flush()
    [Console]::In.ReadLine() | Out-Null
}} finally {{
    try {{ $stream.Unlock(0, 1) }} catch {{ }}
    $stream.Dispose()
}}
"""
    holder = subprocess.Popen(
        [
            shutil.which("powershell") or "powershell",
            "-NoProfile",
            "-Command",
            child_code,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        evidence = bake.validate_held_service_publish_lease(
            lease_path=lease_path,
            lease_token=token,
            transaction_id=transaction_id,
            env_id=bake.ENV_ID,
            service_name=bake.SERVICE_NAME,
            data_root=data_root,
        )
        assert evidence["transaction_id"] == transaction_id
        assert evidence["lease_token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
        with pytest.raises(ValueError, match="token"):
            bake.validate_held_service_publish_lease(
                lease_path=lease_path,
                lease_token="b" * 32,
                transaction_id=transaction_id,
                env_id=bake.ENV_ID,
                service_name=bake.SERVICE_NAME,
                data_root=data_root,
            )
    finally:
        if holder.poll() is None and holder.stdin is not None:
            holder.stdin.write("release\n")
            holder.stdin.flush()
        holder.wait(timeout=10)
    assert holder.returncode == 0, holder.stderr.read() if holder.stderr else ""

    with pytest.raises(ValueError, match="not held"):
        bake.validate_held_service_publish_lease(
            lease_path=lease_path,
            lease_token=token,
            transaction_id=transaction_id,
            env_id=bake.ENV_ID,
            service_name=bake.SERVICE_NAME,
            data_root=data_root,
        )


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


def test_prepare_rejects_candidate_with_public_local_path_leak(tmp_path: Path) -> None:
    bake = load_bake_module()
    _data_root, work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    before = tree_digest(current_release)
    leaked_files = [
        candidate / "current.json",
        candidate / "by-id" / "new-event.json",
        candidate / "by-city" / "shanghai.json",
        candidate / "by-date" / "2026-07-24.json",
    ]
    for path in leaked_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("items") if isinstance(payload.get("items"), list) else [payload["item"]]
        rows[0]["source_evidence_path"] = "/home/pipeline/private/article.json"
        write_json(path, payload)

    with pytest.raises(ValueError, match="internal_only_key|posix_absolute_path"):
        bake.validate_derived_route_closure(candidate)

    with pytest.raises(ValueError, match="release_derived_route_closure_failed"):
        bake.prepare_publish_transaction(
            release_dir=candidate,
            source_url_map=candidate / "source_actions" / "source_url_map.json",
            transaction_id="run-public-path-leak",
            include_stage7_atlas=False,
            update_column_json=False,
        )

    assert tree_digest(current_release) == before
    assert not (work_root / "publish_transactions" / "run-public-path-leak").exists()


def test_prepare_rejects_unsafe_public_source_map_before_transaction_creation(tmp_path: Path) -> None:
    bake = load_bake_module()
    _data_root, work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    before = tree_digest(current_release)
    source_map_path = candidate / "source_actions" / "source_url_map.json"
    source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    source_map["sources"]["b" * 16]["url"] = "file:///home/private/article.html"
    write_json(source_map_path, source_map)

    with pytest.raises(ValueError, match="unsafe public URL"):
        bake.validate_derived_route_closure(candidate)
    with pytest.raises(ValueError, match="release_derived_route_closure_failed"):
        bake.prepare_publish_transaction(
            release_dir=candidate,
            source_url_map=source_map_path,
            transaction_id="run-unsafe-source-map",
            include_stage7_atlas=False,
            update_column_json=False,
        )

    assert tree_digest(current_release) == before
    assert not (work_root / "publish_transactions" / "run-unsafe-source-map").exists()


def test_bio_promotion_is_staged_and_digest_bound_without_predeploy_mutation(tmp_path: Path) -> None:
    bake = load_bake_module()
    data_root, work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    index_path, db_path = configure_bio_assets(data_root)
    before_release = tree_digest(current_release)
    before_index = index_path.read_bytes()
    before_db = db_path.read_bytes()

    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-bio-staged",
        include_stage7_atlas=False,
        update_column_json=False,
        promote_dj_bio_atoms=True,
    )

    assert tree_digest(current_release) == before_release
    assert index_path.read_bytes() == before_index
    assert db_path.read_bytes() == before_db
    transaction = work_root / "publish_transactions" / "run-bio-staged"
    staged = transaction / "staged_data"
    evidence_path = staged / "dj_bio_promotion.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["matched_count"] == 1
    assert evidence["db_update_count"] == 1
    assert evidence["index_update_count"] == 1
    assert evidence["changed"] is True
    assert evidence["after"]["atlas_index.json.gz"]["sha256"] == bake.sha256_file(
        staged / "atlas_index.json.gz"
    )
    assert evidence["after"]["atlas_miniapp.sqlite"]["sha256"] == bake.sha256_file(
        staged / "atlas_miniapp.sqlite"
    )
    binding = json.loads((staged / "current_release" / "manifest.json").read_text(encoding="utf-8"))[
        "publish_transaction_evidence"
    ]["dj_bio_promotion"]
    assert binding["transaction_id"] == "run-bio-staged"
    assert binding["report_sha256"] == bake.sha256_file(evidence_path)
    context_manifest = prepared["deploy_context"]
    report_entry = bake.deploy_context_file_entry(
        context_manifest, "data/dj_bio_promotion.json"
    )
    index_entry = bake.deploy_context_file_entry(context_manifest, "data/atlas_index.json.gz")
    assert report_entry["sha256"] == binding["report_sha256"]
    assert index_entry["sha256"] == binding["atlas_index_sha256"]


def test_bio_promotion_prepare_hard_fails_when_runtime_database_is_missing(tmp_path: Path) -> None:
    bake = load_bake_module()
    data_root, work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    configure_bio_assets(data_root, include_db=False)
    before_release = tree_digest(current_release)

    with pytest.raises(FileNotFoundError, match="requires runtime Atlas asset"):
        bake.prepare_publish_transaction(
            release_dir=candidate,
            source_url_map=candidate / "source_actions" / "source_url_map.json",
            transaction_id="run-bio-missing-db",
            include_stage7_atlas=False,
            update_column_json=False,
            promote_dj_bio_atoms=True,
        )

    assert tree_digest(current_release) == before_release
    assert not (work_root / "publish_transactions" / "run-bio-missing-db").exists()


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
    deploy_report, smoke_report, pagination_report, club_overviews_report = write_success_evidence(
        tmp_path / "evidence", prepared
    )
    smoke = json.loads(smoke_report.read_text(encoding="utf-8"))
    smoke.update({"ok": False, "decision": "cloudrun_weekly_production_smoke_blocked"})
    write_json(smoke_report, smoke)

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


def test_promotion_rechecks_baseline_after_entering_the_process_lock(tmp_path: Path, monkeypatch) -> None:
    bake = load_bake_module()
    _data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-lock-baseline-race",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    evidence = write_success_evidence(tmp_path / "evidence", prepared)

    @contextlib.contextmanager
    def mutate_baseline_after_lock(_lock_path):
        write_release(current_release, "concurrent-event", "2026-07-19T00:00:00+08:00")
        yield

    monkeypatch.setattr(bake, "publish_promotion_lock", mutate_baseline_after_lock)
    with pytest.raises(ValueError, match="baseline_unchanged"):
        bake.promote_publish_transaction(
            transaction_id="run-lock-baseline-race",
            deploy_report_path=evidence[0],
            smoke_report_path=evidence[1],
            pagination_report_path=evidence[2],
            club_overviews_report_path=evidence[3],
        )


def write_success_evidence(root: Path, prepared: dict) -> tuple[Path, Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    deploy_report = root / "deploy.json"
    smoke_report = root / "smoke.json"
    pagination_report = root / "pagination.json"
    club_overviews_report = root / "club-overviews.json"
    zip_path = root / "cloudrun-direct-context.zip"
    zip_path.write_bytes(b"fixture immutable deploy zip")
    zip_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    base_url = "https://weekly.example.invalid"
    active_version = "weekly-api-fixture"
    core_binding = {
        "transaction_id": prepared["transaction_id"],
        "env_id": "huaidjweekly-d8g1go7-d0a07863e3e",
        "service_name": "weekly-api",
        "deploy_context_fingerprint": prepared["deploy_context"]["fingerprint"],
        "deploy_zip_sha256": zip_sha,
        "expected_generation_id": prepared["candidate_generation_id"],
        "publish_lease_token_sha256": "d" * 64,
    }
    full_binding = {
        **core_binding,
        "active_version": active_version,
        "base_url": base_url,
        "remote_generation_id": prepared["candidate_generation_id"],
    }
    write_json(
        deploy_report,
        {
            "schema_version": "cloudrun_direct_api_deploy.v2",
            "ok": True,
            "safety": {"cloud_deploy_executed": True},
            "evidence_binding": core_binding,
            "zip": {
                "zip_path": str(zip_path),
                "zip_sha256": zip_sha,
                "context_dir": prepared["paths"]["deploy_context"],
            },
            "deployment_identity": {
                "task_id": 123,
                "request_id": "fixture-request",
                "reported_version": active_version,
                "observed_active_version": active_version,
            },
            "post_update_server_identity": {
                "active_version": active_version,
                "base_url": base_url,
            },
        },
    )
    write_json(
        smoke_report,
        {
            "schema_version": "stage7_cloudrun_weekly_production_smoke.v2",
            "ok": True,
            "decision": "cloudrun_weekly_production_smoke_ready",
            "evidence_binding": full_binding,
        },
    )
    ids = prepared["candidate_item_ids"]
    write_json(
        pagination_report,
        {
            "schema_version": "cloudrun_remote_pagination.v2",
            "ok": True,
            "decision": "cloudrun_remote_pagination_verified",
            "scope": "package",
            "remote_item_id_count": ids["unique_item_id_count"],
            "remote_item_id_digest": ids["item_id_digest"],
            "digest_algorithm": ids["digest_algorithm"],
            "evidence_binding": full_binding,
        },
    )
    club_candidate = prepared["candidate_club_overviews"]
    club_remote = {key: value for key, value in club_candidate.items() if key != "file_sha256"}
    club_remote["source"] = "remote"
    write_json(
        club_overviews_report,
        {
            "schema_version": "cloudrun_club_overviews_reconciliation.v2",
            "ok": True,
            "decision": "cloudrun_club_overviews_reconciled",
            "candidate": club_candidate,
            "remote": club_remote,
            "evidence_binding": full_binding,
        },
    )
    return deploy_report, smoke_report, pagination_report, club_overviews_report


def test_successful_promotion_swaps_candidate_and_keeps_versioned_backup(tmp_path: Path, monkeypatch) -> None:
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
    monkeypatch.setattr(
        bake,
        "revalidate_remote_promotion_target",
        lambda **_kwargs: {
            "schema_version": "cloudrun_remote_promotion_revalidation.v1",
            "ok": True,
            "decision": "cloudrun_remote_promotion_target_revalidated",
            "checks": {"fixture": True},
        },
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
    assert source_map["source_count"] == 1
    assert source_map["sources"]["b" * 16] == {
        "url": "https://new.invalid/article",
        "event_id": "new-event",
    }
    assert promoted["status"] == "promoted"
    backup = Path(promoted["promotion"]["backup_dir"])
    assert json.loads((backup / "current_release" / "current.json").read_text(encoding="utf-8"))["items"][0]["id"] == "old-event"
    backup_source_map = json.loads(
        (backup / "source_actions" / "source_url_map.json").read_text(encoding="utf-8")
    )
    assert backup_source_map["sources"]["a" * 16] == {
        "url": "https://old.invalid/article",
        "event_id": "old-event",
    }


def test_bio_assets_promote_only_after_remote_proof_and_keep_versioned_backup(
    tmp_path: Path, monkeypatch
) -> None:
    bake = load_bake_module()
    data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    index_path, db_path = configure_bio_assets(data_root)
    old_index = index_path.read_bytes()
    old_db = db_path.read_bytes()
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-bio-success",
        include_stage7_atlas=False,
        update_column_json=False,
        promote_dj_bio_atoms=True,
    )
    paths = write_success_evidence(tmp_path / "evidence", prepared)
    monkeypatch.setattr(
        bake,
        "revalidate_remote_promotion_target",
        lambda **_kwargs: {
            "schema_version": "cloudrun_remote_promotion_revalidation.v1",
            "ok": True,
            "decision": "cloudrun_remote_promotion_target_revalidated",
            "checks": {"fixture": True},
        },
    )

    promoted = bake.promote_publish_transaction(
        transaction_id=prepared["transaction_id"],
        deploy_report_path=paths[0],
        smoke_report_path=paths[1],
        pagination_report_path=paths[2],
        club_overviews_report_path=paths[3],
    )

    assert index_path.read_bytes() != old_index
    assert db_path.read_bytes() != old_db
    promotion = promoted["promotion"]["dj_bio_promotion"]
    assert promotion["authoritative_changed"] is True
    assert promotion["matched_count"] == 1
    assert promotion["db_update_count"] == 1
    assert promotion["index_update_count"] == 1
    assert promotion["authoritative_after"]["fingerprint"] == prepared["dj_bio_promotion"][
        "staged_assets"
    ]["fingerprint"]
    backup = Path(promoted["promotion"]["backup_dir"])
    assert (backup / "atlas" / "atlas_index.json.gz").read_bytes() == old_index
    assert (backup / "atlas" / "atlas_miniapp.sqlite").read_bytes() == old_db
    assert json.loads((current_release / "current.json").read_text(encoding="utf-8"))["items"][0][
        "id"
    ] == "new-event"


def test_parent_held_lease_promotion_skips_reacquire_and_rechecks_before_swap(
    tmp_path: Path, monkeypatch
) -> None:
    bake = load_bake_module()
    data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-parent-held-lease",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    paths = write_success_evidence(tmp_path / "evidence", prepared)
    token = "a" * 32
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["evidence_binding"]["publish_lease_token_sha256"] = token_hash
        write_json(path, payload)
    lease_path = bake.service_publish_lease_path(data_root, bake.ENV_ID, bake.SERVICE_NAME)
    lease_evidence = {
        "schema_version": "weekly_cloudrun_service_publish_lease.v1",
        "lease_path": str(lease_path),
        "lease_token_sha256": token_hash,
        "transaction_id": prepared["transaction_id"],
        "env_id": bake.ENV_ID,
        "service_name": bake.SERVICE_NAME,
        "owner_pid": 123,
    }
    validations = {"count": 0}

    def validate_lease(**_kwargs):
        validations["count"] += 1
        return dict(lease_evidence)

    def must_not_reacquire(_path):
        raise AssertionError("promotion attempted to reacquire its parent-held lease")

    monkeypatch.setattr(bake, "validate_held_service_publish_lease", validate_lease)
    monkeypatch.setattr(bake, "publish_promotion_lock", must_not_reacquire)
    monkeypatch.setattr(
        bake,
        "revalidate_remote_promotion_target",
        lambda **_kwargs: {
            "schema_version": "cloudrun_remote_promotion_revalidation.v1",
            "ok": True,
            "decision": "cloudrun_remote_promotion_target_revalidated",
            "checks": {"fixture": True},
        },
    )

    promoted = bake.promote_publish_transaction(
        transaction_id=prepared["transaction_id"],
        deploy_report_path=paths[0],
        smoke_report_path=paths[1],
        pagination_report_path=paths[2],
        club_overviews_report_path=paths[3],
        held_lease_path=lease_path,
        held_lease_token=token,
    )

    assert validations["count"] == 2
    assert promoted["status"] == "promoted"
    assert promoted["service_publish_lease_revalidated_before_promotion"][
        "lease_token_sha256"
    ] == token_hash
    assert json.loads((current_release / "current.json").read_text(encoding="utf-8"))["items"][0]["id"] == "new-event"


@pytest.mark.parametrize(
    "mutation",
    ["cross_transaction", "wrong_service", "wrong_generation", "wrong_version", "tampered_zip"],
)
def test_promotion_rejects_mixed_or_tampered_deploy_evidence(
    tmp_path: Path, mutation: str
) -> None:
    bake = load_bake_module()
    _data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id=f"run-binding-{mutation}",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    before = tree_digest(current_release)
    paths = write_success_evidence(tmp_path / "evidence", prepared)
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if mutation == "cross_transaction":
        for payload in reports:
            payload["evidence_binding"]["transaction_id"] = "another-run"
    elif mutation == "wrong_service":
        for payload in reports:
            payload["evidence_binding"]["service_name"] = "another-service"
    elif mutation == "wrong_generation":
        other_generation = "sha256:" + "f" * 64
        for payload in reports:
            payload["evidence_binding"]["expected_generation_id"] = other_generation
            if "remote_generation_id" in payload["evidence_binding"]:
                payload["evidence_binding"]["remote_generation_id"] = other_generation
    elif mutation == "wrong_version":
        for payload in reports[1:]:
            payload["evidence_binding"]["active_version"] = "weekly-api-other"
    elif mutation == "tampered_zip":
        Path(reports[0]["zip"]["zip_path"]).write_bytes(b"tampered after deploy")
    for path, payload in zip(paths, reports):
        write_json(path, payload)

    with pytest.raises(ValueError, match="publish evidence binding failed"):
        bake.promote_publish_transaction(
            transaction_id=prepared["transaction_id"],
            deploy_report_path=paths[0],
            smoke_report_path=paths[1],
            pagination_report_path=paths[2],
            club_overviews_report_path=paths[3],
        )

    assert tree_digest(current_release) == before


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
    monkeypatch.setattr(
        bake,
        "revalidate_remote_promotion_target",
        lambda **_kwargs: {
            "schema_version": "cloudrun_remote_promotion_revalidation.v1",
            "ok": True,
            "decision": "cloudrun_remote_promotion_target_revalidated",
            "checks": {"fixture": True},
        },
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


def test_bio_asset_swap_failure_restores_release_source_db_and_index(
    tmp_path: Path, monkeypatch
) -> None:
    bake = load_bake_module()
    data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    index_path, db_path = configure_bio_assets(data_root)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-bio-rollback",
        include_stage7_atlas=False,
        update_column_json=False,
        promote_dj_bio_atoms=True,
    )
    before_release = tree_digest(current_release)
    before_source = (data_root / "source_actions" / "source_url_map.json").read_bytes()
    before_index = index_path.read_bytes()
    before_db = db_path.read_bytes()
    paths = write_success_evidence(tmp_path / "evidence", prepared)
    monkeypatch.setattr(
        bake,
        "revalidate_remote_promotion_target",
        lambda **_kwargs: {
            "schema_version": "cloudrun_remote_promotion_revalidation.v1",
            "ok": True,
            "decision": "cloudrun_remote_promotion_target_revalidated",
            "checks": {"fixture": True},
        },
    )
    transaction_dir = Path(prepared["paths"]["transaction_dir"])
    staged_index = transaction_dir / "staged_data" / "atlas_index.json.gz"
    original_replace = bake.os.replace
    injected = {"done": False}

    def fail_staged_index_swap(source, destination):
        if Path(source) == staged_index and Path(destination) == index_path and not injected["done"]:
            injected["done"] = True
            raise OSError("injected Atlas index promotion failure")
        return original_replace(source, destination)

    monkeypatch.setattr(bake.os, "replace", fail_staged_index_swap)
    with pytest.raises(RuntimeError, match="baseline_restored=True"):
        bake.promote_publish_transaction(
            transaction_id=prepared["transaction_id"],
            deploy_report_path=paths[0],
            smoke_report_path=paths[1],
            pagination_report_path=paths[2],
            club_overviews_report_path=paths[3],
        )

    assert tree_digest(current_release) == before_release
    assert (data_root / "source_actions" / "source_url_map.json").read_bytes() == before_source
    assert index_path.read_bytes() == before_index
    assert db_path.read_bytes() == before_db
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


def test_promotion_revalidates_remote_version_and_generation_before_local_swap(
    tmp_path: Path, monkeypatch
) -> None:
    bake = load_bake_module()
    _data_root, _work_root, current_release, candidate = configure_fixture(bake, tmp_path)
    prepared = bake.prepare_publish_transaction(
        release_dir=candidate,
        source_url_map=candidate / "source_actions" / "source_url_map.json",
        transaction_id="run-remote-revalidation-race",
        include_stage7_atlas=False,
        update_column_json=False,
    )
    before = tree_digest(current_release)
    evidence = write_success_evidence(tmp_path / "evidence", prepared)
    captured = {}

    def remote_drift(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "cloudrun_remote_promotion_revalidation.v1",
            "ok": False,
            "decision": "cloudrun_remote_promotion_target_changed",
            "checks": {
                "active_version_matches": False,
                "readyz_generation_matches": True,
            },
        }

    monkeypatch.setattr(bake, "revalidate_remote_promotion_target", remote_drift)

    with pytest.raises(ValueError, match="remote promotion revalidation"):
        bake.promote_publish_transaction(
            transaction_id=prepared["transaction_id"],
            deploy_report_path=evidence[0],
            smoke_report_path=evidence[1],
            pagination_report_path=evidence[2],
            club_overviews_report_path=evidence[3],
        )

    assert captured["transaction_id"] == prepared["transaction_id"]
    assert captured["candidate_generation_id"] == prepared["candidate_generation_id"]
    assert tree_digest(current_release) == before
    report = json.loads(
        Path(prepared["paths"]["transaction_dir"])
        .joinpath("publish_transaction.json")
        .read_text(encoding="utf-8")
    )
    assert report["status"] == "promotion_blocked"
    assert report["remote_promotion_revalidation"]["ok"] is False


def test_remote_promotion_revalidation_binds_service_version_generation_and_candidate(
    monkeypatch,
) -> None:
    bake = load_bake_module()
    generation_id = "sha256:" + "a" * 64
    item_digest = "b" * 64
    binding = {
        "transaction_id": "run-revalidation-exact",
        "env_id": bake.ENV_ID,
        "service_name": bake.SERVICE_NAME,
        "deploy_context_fingerprint": "c" * 64,
        "deploy_zip_sha256": "d" * 64,
        "publish_lease_token_sha256": "e" * 64,
        "expected_generation_id": generation_id,
        "active_version": "weekly-api-exact",
        "base_url": "https://weekly.example.invalid",
    }
    monkeypatch.setattr(
        bake,
        "describe_cloudrun_server_for_promotion",
        lambda *_args, **_kwargs: {
            "base_url": binding["base_url"],
            "status": "normal",
            "active_version": binding["active_version"],
            "active_flow_ratio": 100,
        },
    )
    monkeypatch.setattr(
        bake,
        "read_remote_readyz_for_promotion",
        lambda *_args, **_kwargs: {
            "status_code": 200,
            "payload": {
                "ok": True,
                "service": bake.SERVICE_NAME,
                "generationId": generation_id,
                "itemIdDigest": item_digest,
                "packageItemCount": 61,
            },
        },
    )

    report = bake.revalidate_remote_promotion_target(
        transaction_id=binding["transaction_id"],
        evidence_binding=binding,
        candidate_generation_id=generation_id,
        candidate_item_id_digest=item_digest,
        candidate_item_count=61,
    )

    assert report["ok"] is True
    assert report["evidence_binding"]["transaction_id"] == binding["transaction_id"]
    assert report["evidence_binding"]["candidate_generation_id"] == generation_id
    assert report["evidence_binding"]["candidate_item_id_digest"] == item_digest

    monkeypatch.setattr(
        bake,
        "describe_cloudrun_server_for_promotion",
        lambda *_args, **_kwargs: {
            "base_url": binding["base_url"],
            "status": "normal",
            "active_version": "weekly-api-overwritten",
            "active_flow_ratio": 100,
        },
    )
    drifted = bake.revalidate_remote_promotion_target(
        transaction_id=binding["transaction_id"],
        evidence_binding=binding,
        candidate_generation_id=generation_id,
        candidate_item_id_digest=item_digest,
        candidate_item_count=61,
    )
    assert drifted["ok"] is False
    assert drifted["checks"]["active_version_matches"] is False


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
    assert '[Guid]::NewGuid().ToString("N")' in script
    assert "_p${PID}_$RunNonce" in script
    assert "scope=package&limit=100" in script
    assert "lookbackDays=999" not in script
    assert 'scope = "package"' in script
    assert "--max-wait-seconds 900" in script
    assert "--timeout-seconds 30" in script
    assert "--deploy-report $CloudRunDeployReportPath" in script
    assert "--smoke-report $CloudRunSmokeReportPath" in script
    assert "--no-timeout" not in script
    assert script.count("-TimeoutSec 30") >= 3
    assert "remote_item_id_digest" in script
    assert "cloudrun_remote_pagination.json" in script
    assert "$bindingCoreFields" in script
    assert '"deploy_context_fingerprint"' in script
    assert "evidence_binding = $smokeBinding" in script
    assert "--club-overviews-report $CloudRunClubOverviewsReportPath" in script
    assert '"remote_rollback_verified"' in script
    assert '"remote_rollback_failed"' in script
    assert "automatic_rollback_executed = $automaticRollbackExecuted" in script
    assert "automatic_rollback_verified = $automaticRollbackVerified" in script
    assert "previous_server_identity" in script
    assert "post_update_server_identity" in script
    assert 'remote_mutation.update_attempted' in script
    assert 'remote_mutation = $remoteMutation' in script
    rollback_at = script.index("automatic_cloudbase_rollback.py", club_overviews_at)
    rollback_packet_at = script.index("Write-RemoteRollbackPacket", rollback_at)
    assert promote_at < rollback_at < rollback_packet_at
    assert "--transaction-report $CloudRunPublishTransactionReportPath" in script
    assert "--authoritative-release-dir $IncrementalBaseApiDir" in script
    assert "--report $CloudRunAutomaticRollbackReportPath" in script
    assert "--publish-lease-path $CloudRunPublishLeasePath" in script[rollback_at:rollback_packet_at]
    assert "--publish-lease-token $CloudRunPublishLeaseToken" in script[rollback_at:rollback_packet_at]
    assert "automatic rollback is not verified" in script
    lease_at = script.index("Enter-CloudRunServicePublishLease", deploy_at - 5000)
    release_lease_at = script.index("Exit-CloudRunServicePublishLease", promote_at)
    assert lease_at < deploy_at < smoke_at < pagination_at < club_overviews_at < promote_at < rollback_at < release_lease_at
    assert script.count("--publish-lease-path $CloudRunPublishLeasePath") >= 3
    assert script.count("--publish-lease-token $CloudRunPublishLeaseToken") >= 3
    assert "$seenCursors" in script
    assert "$MaxPages" in script
    assert "did not advance" in script
