import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_cloudrun_weekly_production.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("smoke_cloudrun_weekly_production", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_tcb_cwd_is_owned_by_the_current_checkout():
    smoke = load_script_module()

    expected = ROOT.parents[1] / "services" / "weekly_activity_cloudrun"
    assert smoke.DEFAULT_TCB_CWD == expected
    assert smoke.resolve_tcb_cwd(None) == expected.resolve()
    assert r"C:\code\githubstar\wechathtmldownload" not in SCRIPT.read_text(encoding="utf-8")


def test_explicit_tcb_cwd_is_passed_to_cloudbase_cli(monkeypatch, tmp_path):
    smoke = load_script_module()
    explicit = tmp_path / "cloudrun"
    explicit.mkdir()
    (explicit / "package.json").write_text("{}\n", encoding="utf-8")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, stdout='{"data": {"ok": true}}', stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    payload = smoke.tcb_api("DescribeCloudRunServerDetail", {}, 30, tcb_cwd=explicit)

    assert payload == {"ok": True}
    assert captured["cwd"] == explicit.resolve()


def test_explicit_tcb_cwd_must_be_a_cloudrun_project(tmp_path):
    smoke = load_script_module()
    invalid = tmp_path / "not-a-project"
    invalid.mkdir()

    try:
        smoke.resolve_tcb_cwd(invalid)
    except ValueError as exc:
        assert "package.json" in str(exc)
    else:
        raise AssertionError("invalid TCB cwd was accepted")


def test_weekly_smoke_requires_package_readiness_not_only_process_liveness():
    smoke = load_script_module()
    source = SCRIPT.read_text(encoding="utf-8")

    assert '("readyz", "/readyz")' in source
    assert smoke.endpoint_ok(
        "readyz",
        {
            "status_code": 200,
            "json_object": True,
            "ok_field": True,
            "service": smoke.SERVICE_NAME,
            "generation_id": "weekly-sha256-test",
            "package_item_count": 60,
            "derived_detail_count": 60,
            "item_id_digest": "a" * 64,
        },
    )
    assert not smoke.endpoint_ok(
        "readyz",
        {
            "status_code": 503,
            "json_object": True,
            "ok_field": False,
            "service": smoke.SERVICE_NAME,
        },
    )


def test_smoke_binds_remote_generation_and_active_version_to_deploy(tmp_path):
    smoke = load_script_module()
    deploy_report = tmp_path / "deploy.json"
    binding = {
        "transaction_id": "weekly-run-001",
        "env_id": smoke.ENV_ID,
        "service_name": smoke.SERVICE_NAME,
        "deploy_context_fingerprint": "a" * 64,
        "deploy_zip_sha256": "b" * 64,
        "publish_lease_token_sha256": "d" * 64,
        "expected_generation_id": "sha256:" + "c" * 64,
    }
    deploy_report.write_text(
        json.dumps(
            {
                "schema_version": "cloudrun_direct_api_deploy.v2",
                "ok": True,
                "safety": {"cloud_deploy_executed": True},
                "evidence_binding": binding,
                "deployment_identity": {
                    "task_id": 123,
                    "reported_version": "weekly-api-124",
                    "observed_active_version": "weekly-api-124",
                },
                "post_update_server_identity": {"base_url": "https://weekly.example.invalid"},
            }
        ),
        encoding="utf-8",
    )
    report = {
        "schema_version": "stage7_cloudrun_weekly_production_smoke.v1",
        "ok": True,
        "decision": "cloudrun_weekly_production_smoke_ready",
        "server": {
            "active_version": "weekly-api-124",
            "base_url": "https://weekly.example.invalid",
        },
        "endpoints": [
            {"name": "readyz", "generation_id": binding["expected_generation_id"]}
        ],
        "blockers": [],
    }

    bound = smoke.bind_report_to_deploy(
        report,
        deploy_report,
        expected_env_id=smoke.ENV_ID,
        expected_service_name=smoke.SERVICE_NAME,
    )

    assert bound["ok"] is True
    assert bound["schema_version"] == "stage7_cloudrun_weekly_production_smoke.v2"
    assert bound["evidence_binding"]["remote_generation_id"] == binding["expected_generation_id"]
    assert bound["evidence_binding"]["active_version"] == "weekly-api-124"
    assert bound["evidence_binding"]["base_url"] == "https://weekly.example.invalid"


def test_smoke_binding_fails_closed_on_generation_mismatch(tmp_path):
    smoke = load_script_module()
    deploy_report = tmp_path / "deploy.json"
    deploy_report.write_text(
        json.dumps(
            {
                "schema_version": "cloudrun_direct_api_deploy.v2",
                "ok": True,
                "safety": {"cloud_deploy_executed": True},
                "evidence_binding": {
                    "transaction_id": "weekly-run-002",
                    "env_id": smoke.ENV_ID,
                    "service_name": smoke.SERVICE_NAME,
                    "deploy_context_fingerprint": "a" * 64,
                    "deploy_zip_sha256": "b" * 64,
                    "publish_lease_token_sha256": "d" * 64,
                    "expected_generation_id": "sha256:" + "c" * 64,
                },
                "deployment_identity": {
                    "task_id": 123,
                    "reported_version": "weekly-api-125",
                },
                "post_update_server_identity": {"base_url": "https://weekly.example.invalid"},
            }
        ),
        encoding="utf-8",
    )
    report = {
        "schema_version": "stage7_cloudrun_weekly_production_smoke.v1",
        "ok": True,
        "decision": "cloudrun_weekly_production_smoke_ready",
        "server": {
            "active_version": "weekly-api-125",
            "base_url": "https://weekly.example.invalid",
        },
        "endpoints": [{"name": "readyz", "generation_id": "wrong-generation"}],
        "blockers": [],
    }

    bound = smoke.bind_report_to_deploy(
        report,
        deploy_report,
        expected_env_id=smoke.ENV_ID,
        expected_service_name=smoke.SERVICE_NAME,
    )

    assert bound["ok"] is False
    assert bound["decision"] == "cloudrun_weekly_production_smoke_blocked"
    assert "deploy_expected_generation_mismatch" in bound["blockers"]


def test_smoke_does_not_accept_the_previous_active_version_when_task_reports_new(tmp_path):
    smoke = load_script_module()
    deploy_report = tmp_path / "deploy.json"
    generation_id = "sha256:" + "c" * 64
    deploy_report.write_text(
        json.dumps(
            {
                "schema_version": "cloudrun_direct_api_deploy.v2",
                "ok": True,
                "safety": {"cloud_deploy_executed": True},
                "evidence_binding": {
                    "transaction_id": "weekly-run-version-race",
                    "env_id": smoke.ENV_ID,
                    "service_name": smoke.SERVICE_NAME,
                    "deploy_context_fingerprint": "a" * 64,
                    "deploy_zip_sha256": "b" * 64,
                    "publish_lease_token_sha256": "d" * 64,
                    "expected_generation_id": generation_id,
                },
                "deployment_identity": {
                    "task_id": 456,
                    "reported_version": "weekly-api-new",
                    "observed_active_version": "weekly-api-old",
                },
                "post_update_server_identity": {
                    "base_url": "https://weekly.example.invalid",
                    "active_version": "weekly-api-old",
                },
            }
        ),
        encoding="utf-8",
    )
    report = {
        "schema_version": "stage7_cloudrun_weekly_production_smoke.v1",
        "ok": True,
        "decision": "cloudrun_weekly_production_smoke_ready",
        "server": {
            "active_version": "weekly-api-old",
            "base_url": "https://weekly.example.invalid",
        },
        "endpoints": [{"name": "readyz", "generation_id": generation_id}],
        "blockers": [],
    }

    bound = smoke.bind_report_to_deploy(
        report,
        deploy_report,
        expected_env_id=smoke.ENV_ID,
        expected_service_name=smoke.SERVICE_NAME,
    )

    assert bound["ok"] is False
    assert "active_version_not_bound_to_deploy" in bound["blockers"]


def test_paginated_current_fails_closed_when_cursor_does_not_advance(monkeypatch):
    smoke = load_script_module()

    def fake_get_json(_base_url, path, _timeout):
        cursor = ""
        if "cursor=" in path:
            cursor = path.split("cursor=", 1)[1].split("&", 1)[0]
        return {
            "url_path": path,
            "status_code": 200,
            "payload": {
                "items": [{"id": cursor or "first"}],
                "page": {"nextCursor": "same"},
            },
        }

    monkeypatch.setattr(smoke, "get_json", fake_get_json)

    with pytest.raises(RuntimeError, match="cursor.*(repeat|advance)"):
        smoke.get_paginated_current("https://weekly.example.invalid", 30)


def test_paginated_current_fails_closed_at_maximum_page_count(monkeypatch):
    smoke = load_script_module()
    calls = {"count": 0}

    def fake_get_json(_base_url, path, _timeout):
        calls["count"] += 1
        return {
            "url_path": path,
            "status_code": 200,
            "payload": {
                "items": [{"id": f"event-{calls['count']}"}],
                "page": {"nextCursor": str(calls["count"])},
            },
        }

    monkeypatch.setattr(smoke, "get_json", fake_get_json)

    with pytest.raises(RuntimeError, match="maximum page count"):
        smoke.get_paginated_current(
            "https://weekly.example.invalid",
            30,
            max_pages=2,
        )


def test_paginated_current_does_not_return_partial_data_after_later_page_failure(monkeypatch):
    smoke = load_script_module()
    calls = {"count": 0}

    def fake_get_json(_base_url, path, _timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "url_path": path,
                "status_code": 200,
                "payload": {
                    "items": [{"id": "first"}],
                    "page": {"nextCursor": "next"},
                },
            }
        return {
            "url_path": path,
            "status_code": 503,
            "payload": {"error": {"code": "TEMPORARY"}},
        }

    monkeypatch.setattr(smoke, "get_json", fake_get_json)

    with pytest.raises(RuntimeError, match="page request failed"):
        smoke.get_paginated_current("https://weekly.example.invalid", 30)
