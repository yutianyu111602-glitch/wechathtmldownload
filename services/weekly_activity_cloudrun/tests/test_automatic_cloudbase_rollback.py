import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "automatic_cloudbase_rollback.py"
)
SPEC = importlib.util.spec_from_file_location("automatic_cloudbase_rollback", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def fixture_files(root: Path) -> types.SimpleNamespace:
    release = root / "current_release"
    items = [
        {"id": "event-a", "title": "A"},
        {"id": "event-b", "title": "B"},
    ]
    generation = "sha256:" + "1" * 64
    write_json(
        release / "manifest.json",
        {
            "schema_version": "weekly_activity_miniprogram_api.v1",
            "generation_id": generation,
            "item_count": len(items),
        },
    )
    write_json(release / "current.json", {"items": items})
    club_payload = {
        "schema_version": "club_overviews.v1",
        "generated_at": "2026-07-19T12:00:00+08:00",
        "as_of_date": "2026-07-19",
        "source": "fixture",
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
                    "title": "Fixture week",
                    "publish_date": "2026-07-19",
                    "original_url": "https://example.invalid/article",
                    "cover_url": "cloud://fixture/cover.jpg",
                    "window_kind": "week",
                    "window_label": "this week",
                    "window_start": "2026-07-19",
                    "window_end": "2026-07-25",
                }
            ]
        },
    }
    write_json(release / "club_overviews.json", club_payload)

    transaction_id = "rollback-fixture"
    env_id = "fixture-env"
    service_name = "weekly-api"
    lease_hash = "a" * 64
    context_fingerprint = "b" * 64
    transaction_report = root / "publish_transaction.json"
    write_json(
        transaction_report,
        {
            "schema_version": "weekly_cloudrun_publish_transaction.v1",
            "transaction_id": transaction_id,
            "status": "prepared",
            "candidate_generation_id": "sha256:" + "2" * 64,
            "deploy_context": {"fingerprint": context_fingerprint},
            "baseline": {
                "current_release": MODULE.directory_snapshot(release),
            },
        },
    )
    deploy_report = root / "cloudrun_direct_api_deploy_report.json"
    write_json(
        deploy_report,
        {
            "schema_version": "cloudrun_direct_api_deploy.v2",
            "ok": True,
            "env_id": env_id,
            "service_name": service_name,
            "evidence_binding": {
                "transaction_id": transaction_id,
                "env_id": env_id,
                "service_name": service_name,
                "deploy_context_fingerprint": context_fingerprint,
                "expected_generation_id": "sha256:" + "2" * 64,
                "publish_lease_token_sha256": lease_hash,
            },
            "previous_server_identity": {
                "base_url": "https://weekly.example.invalid",
                "active_version": "weekly-api-old",
                "active_flow_ratio": 100,
            },
            "post_update_server_identity": {
                "base_url": "https://weekly.example.invalid",
                "active_version": "weekly-api-candidate",
                "active_flow_ratio": 100,
            },
            "deployment_identity": {
                "reported_version": "weekly-api-candidate",
                "observed_active_version": "weekly-api-candidate",
            },
            "remote_mutation": {"update_attempted": True},
            "safety": {"cloud_deploy_executed": True},
        },
    )
    report = root / "automatic_rollback.json"
    args = types.SimpleNamespace(
        transaction_id=transaction_id,
        env_id=env_id,
        service_name=service_name,
        deploy_report=deploy_report,
        transaction_report=transaction_report,
        authoritative_release_dir=release,
        publish_lease_path=root / "publish.lease",
        publish_lease_token="lease-secret-value",
        data_root=root / "data",
        report=report,
        proxy_url="",
        max_wait_seconds=30,
        verification_timeout_seconds=2.0,
        verification_poll_interval_seconds=0.01,
        request_timeout_seconds=1.0,
        max_pages=10,
    )
    lease = {
        "schema_version": "weekly_cloudrun_service_publish_lease.v1",
        "lease_token_sha256": lease_hash,
        "transaction_id": transaction_id,
        "env_id": env_id,
        "service_name": service_name,
    }
    return types.SimpleNamespace(
        release=release,
        club_payload=club_payload,
        transaction_id=transaction_id,
        env_id=env_id,
        service_name=service_name,
        lease=lease,
        args=args,
    )


def identity(version: str, ratio: int = 100) -> dict:
    return {
        "base_url": "https://weekly.example.invalid",
        "active_version": version,
        "active_flow_ratio": ratio,
    }


class AutomaticRollbackSafetyTest(unittest.TestCase):
    def test_unknown_or_third_party_active_version_is_never_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = fixture_files(Path(tmp))
            with mock.patch.object(
                MODULE, "validate_held_service_publish_lease", return_value=fx.lease
            ), mock.patch.object(
                MODULE,
                "describe_cloudrun_server_identity",
                return_value=identity("weekly-api-third-party"),
            ), mock.patch.object(MODULE, "tcb_api") as api:
                report = MODULE.run(fx.args)

            api.assert_not_called()
            self.assertFalse(report["ok"])
            self.assertEqual(
                report["failure"]["code"], "live_active_version_not_owned_by_transaction"
            )
            self.assertFalse(report["automatic_rollback_executed"])
            self.assertFalse(report["automatic_rollback_verified"])

    def test_candidate_is_rolled_back_only_after_intent_journal_is_durable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = fixture_files(Path(tmp))
            seen_journal = {}

            def api(action, body, **kwargs):
                persisted = json.loads(fx.args.report.read_text(encoding="utf-8"))
                seen_journal.update(persisted)
                self.assertEqual(persisted["stage"], "rollback_intent_journaled")
                self.assertEqual(action, "SubmitServerRollback")
                self.assertEqual(body["CurrentVersionName"], "weekly-api-candidate")
                self.assertEqual(body["RollbackVersionName"], "weekly-api-old")
                return {"TaskId": 42, "RequestId": "rollback-request"}

            verification = {
                "ok": True,
                "generation_id": "sha256:" + "1" * 64,
                "item_count": 2,
                "item_id_digest": MODULE.item_id_snapshot(fx.release)["item_id_digest"],
                "club_overviews_verified": True,
            }
            with mock.patch.object(
                MODULE,
                "validate_held_service_publish_lease",
                return_value=fx.lease,
            ) as validate_lease, mock.patch.object(
                MODULE,
                "describe_cloudrun_server_identity",
                side_effect=[
                    identity("weekly-api-candidate"),
                    identity("weekly-api-old"),
                ],
            ), mock.patch.object(MODULE, "tcb_api", side_effect=api), mock.patch.object(
                MODULE,
                "poll_task",
                return_value={"ok": True, "status": "success", "version_name": "weekly-api-old"},
            ), mock.patch.object(
                MODULE, "verify_authoritative_release", return_value=verification
            ) as verify:
                report = MODULE.run(fx.args)

            self.assertTrue(seen_journal)
            self.assertGreaterEqual(validate_lease.call_count, 3)
            verify.assert_called_once()
            self.assertTrue(report["ok"])
            self.assertTrue(report["automatic_rollback_executed"])
            self.assertTrue(report["automatic_rollback_verified"])
            self.assertEqual(report["decision"], "cloudrun_automatic_rollback_verified")
            self.assertNotIn("lease-secret-value", json.dumps(report))

    def test_already_restored_previous_version_is_idempotently_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = fixture_files(Path(tmp))
            with mock.patch.object(
                MODULE, "validate_held_service_publish_lease", return_value=fx.lease
            ), mock.patch.object(
                MODULE,
                "describe_cloudrun_server_identity",
                return_value=identity("weekly-api-old"),
            ), mock.patch.object(MODULE, "tcb_api") as api, mock.patch.object(
                MODULE,
                "verify_authoritative_release",
                return_value={"ok": True, "club_overviews_verified": True},
            ):
                report = MODULE.run(fx.args)

            api.assert_not_called()
            self.assertTrue(report["ok"])
            self.assertFalse(report["automatic_rollback_executed"])
            self.assertTrue(report["automatic_rollback_verified"])
            self.assertTrue(report["idempotent_previous_version_already_active"])

    def test_poll_failure_remains_blocked_and_never_claims_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = fixture_files(Path(tmp))
            with mock.patch.object(
                MODULE, "validate_held_service_publish_lease", return_value=fx.lease
            ), mock.patch.object(
                MODULE,
                "describe_cloudrun_server_identity",
                return_value=identity("weekly-api-candidate"),
            ), mock.patch.object(
                MODULE,
                "tcb_api",
                return_value={"TaskId": 42, "RequestId": "rollback-request"},
            ), mock.patch.object(
                MODULE, "poll_task", return_value={"ok": False, "status": "failed"}
            ):
                report = MODULE.run(fx.args)

            self.assertFalse(report["ok"])
            self.assertTrue(report["automatic_rollback_executed"])
            self.assertFalse(report["automatic_rollback_verified"])
            self.assertEqual(report["failure"]["code"], "rollback_task_failed")

    def test_successful_task_waits_for_previous_version_to_reach_100_percent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = fixture_files(Path(tmp))
            verification = {"ok": True, "club_overviews_verified": True}
            with mock.patch.object(
                MODULE, "validate_held_service_publish_lease", return_value=fx.lease
            ), mock.patch.object(
                MODULE,
                "describe_cloudrun_server_identity",
                side_effect=[
                    identity("weekly-api-candidate"),
                    identity("weekly-api-candidate"),
                    identity("weekly-api-old"),
                ],
            ), mock.patch.object(
                MODULE,
                "tcb_api",
                return_value={"TaskId": 42, "RequestId": "rollback-request"},
            ), mock.patch.object(
                MODULE,
                "poll_task",
                return_value={"ok": True, "status": "success", "version_name": "weekly-api-old"},
            ), mock.patch.object(
                MODULE, "verify_authoritative_release", return_value=verification
            ), mock.patch.object(MODULE.time, "sleep"):
                report = MODULE.run(fx.args)

            self.assertTrue(report["ok"])
            self.assertEqual(report["live_identity_after"]["attempt_count"], 2)


class RestoredPackageVerificationTest(unittest.TestCase):
    def test_health_generation_full_pagination_ids_and_clubs_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = fixture_files(Path(tmp))
            ids = MODULE.item_id_snapshot(fx.release)

            def get_json(base_url, path, *, proxy_url, timeout_seconds):
                self.assertEqual(base_url, "https://weekly.example.invalid")
                if path == "/healthz":
                    return 200, {"ok": True, "service": fx.service_name}
                if path == "/readyz":
                    return 200, {
                        "ok": True,
                        "service": fx.service_name,
                        "generationId": "sha256:" + "1" * 64,
                        "packageItemCount": 2,
                        "derivedDetailCount": 2,
                        "itemIdDigest": ids["item_id_digest"],
                    }
                if path == "/api/v1/weekly/manifest":
                    return 200, {
                        "schema_version": "weekly_activity_miniprogram_api.v1",
                        "generation_id": "sha256:" + "1" * 64,
                        "item_count": 2,
                    }
                if path == "/api/v1/weekly/current?scope=package&limit=100":
                    return 200, {
                        "items": [{"id": "event-a"}],
                        "page": {"total": 2, "nextCursor": "1"},
                        "filters": {"scope": "package"},
                    }
                if path == "/api/v1/weekly/current?scope=package&limit=100&cursor=1":
                    return 200, {
                        "items": [{"id": "event-b"}],
                        "page": {"total": 2, "nextCursor": None},
                        "filters": {"scope": "package"},
                    }
                if path == "/api/v1/weekly/club-overviews":
                    return 200, fx.club_payload
                raise AssertionError(path)

            with mock.patch.object(MODULE, "get_json", side_effect=get_json):
                evidence = MODULE.verify_authoritative_release(
                    base_url="https://weekly.example.invalid",
                    service_name=fx.service_name,
                    authoritative_release_dir=fx.release,
                    proxy_url="",
                    request_timeout_seconds=1.0,
                    max_pages=10,
                )

            self.assertTrue(evidence["ok"])
            self.assertEqual(evidence["pagination"]["pages_fetched"], 2)
            self.assertEqual(evidence["pagination"]["item_id_digest"], ids["item_id_digest"])
            self.assertTrue(evidence["club_overviews"]["verified"])

    def test_duplicate_or_missing_remote_ids_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = fixture_files(Path(tmp))

            def get_json(_base_url, path, **_kwargs):
                if path == "/healthz":
                    return 200, {"ok": True, "service": fx.service_name}
                if path == "/readyz":
                    local = MODULE.item_id_snapshot(fx.release)
                    return 200, {
                        "ok": True,
                        "service": fx.service_name,
                        "generationId": "sha256:" + "1" * 64,
                        "packageItemCount": 2,
                        "derivedDetailCount": 2,
                        "itemIdDigest": local["item_id_digest"],
                    }
                if path == "/api/v1/weekly/manifest":
                    return 200, {
                        "schema_version": "weekly_activity_miniprogram_api.v1",
                        "generation_id": "sha256:" + "1" * 64,
                        "item_count": 2,
                    }
                if path.startswith("/api/v1/weekly/current?"):
                    return 200, {
                        "items": [{"id": "event-a"}, {"id": "event-a"}],
                        "page": {"total": 2, "nextCursor": None},
                        "filters": {"scope": "package"},
                    }
                if path == "/api/v1/weekly/club-overviews":
                    return 200, fx.club_payload
                raise AssertionError(path)

            with mock.patch.object(MODULE, "get_json", side_effect=get_json), self.assertRaisesRegex(
                MODULE.SafeRollbackError, "remote_item_ids_do_not_match_authoritative_release"
            ):
                MODULE.verify_authoritative_release(
                    base_url="https://weekly.example.invalid",
                    service_name=fx.service_name,
                    authoritative_release_dir=fx.release,
                    proxy_url="",
                    request_timeout_seconds=1.0,
                    max_pages=10,
                )


if __name__ == "__main__":
    unittest.main()
