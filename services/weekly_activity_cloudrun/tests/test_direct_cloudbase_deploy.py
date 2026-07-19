import importlib.util
import hashlib
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "direct_cloudbase_deploy.py"
SPEC = importlib.util.spec_from_file_location("direct_cloudbase_deploy", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_valid_context(context: Path, extra_files: dict[str, str] | None = None) -> tuple[Path, dict, str]:
    generation_id = "sha256:" + "a" * 64
    release_manifest = context / "data" / "current_release" / "manifest.json"
    release_manifest.parent.mkdir(parents=True)
    release_manifest.write_text(json.dumps({"generation_id": generation_id}), encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        path = context / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    files = [path for path in context.rglob("*") if path.is_file()]
    rows = [
        {
            "dst": path.relative_to(context).as_posix(),
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(files)
    ]
    fingerprint_input = json.dumps(
        {
            "files": rows,
            "current_release_items": ["manifest.json"],
            "data_labels": ["data/current_release"],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    context_manifest = {
        "schema_version": "weekly_cloudrun_deploy_context_manifest.v1",
        "fingerprint": hashlib.sha256(fingerprint_input).hexdigest(),
        "file_count": len(rows),
        "current_release_items": ["manifest.json"],
        "data_labels": ["data/current_release"],
        "files": rows,
    }
    (context / "deploy_context_manifest.json").write_text(
        json.dumps(context_manifest), encoding="utf-8"
    )
    return release_manifest, context_manifest, generation_id


class UploadPackageTest(unittest.TestCase):
    def test_upload_bypasses_proxy_and_retries_reset(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        opener = mock.MagicMock()
        opener.open.side_effect = [ConnectionResetError("reset"), response]

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            MODULE.urllib.request, "build_opener", return_value=opener
        ) as build_opener, mock.patch.object(MODULE.time, "sleep") as sleep:
            package = Path(tmp) / "context.zip"
            package.write_bytes(b"package")

            MODULE.upload_package("https://upload.example.invalid/signed", package)

        proxy_handler = build_opener.call_args.args[0]
        self.assertEqual(proxy_handler.proxies, {})
        self.assertEqual(opener.open.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_upload_failure_never_retains_the_signed_url(self) -> None:
        secret_url = "not-a-url?X-Amz-Credential=SUPERSECRET"
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "context.zip"
            package.write_bytes(b"package")

            with mock.patch.object(MODULE.time, "sleep"), self.assertRaises(
                MODULE.SafeDeployError
            ) as raised:
                MODULE.upload_package(secret_url, package)

        self.assertEqual(raised.exception.code, "cloudrun_package_upload_failed")
        self.assertNotIn("SUPERSECRET", str(raised.exception))
        self.assertNotIn(secret_url, str(raised.exception))


class TcbApiTextDecodingTest(unittest.TestCase):
    def test_utf8_chinese_cli_output_is_independent_of_non_utf8_locale(self) -> None:
        payload = {"data": {"message": "部署成功"}}
        child_code = (
            "import sys; "
            f"sys.stdout.buffer.write({json.dumps(payload, ensure_ascii=False)!r}.encode('utf-8'))"
        )

        with mock.patch.object(MODULE, "TCB_CMD", [sys.executable, "-c", child_code]), mock.patch.object(
            MODULE.subprocess, "_text_encoding", return_value="gbk"
        ):
            result = MODULE.tcb_api("DescribeCloudRunServer", {})

        self.assertEqual(result, payload["data"])


class DeployEvidenceBindingTest(unittest.TestCase):
    def test_production_direct_deploy_requires_parent_service_lease_before_packaging(self) -> None:
        args = types.SimpleNamespace(
            transaction_id="run-no-lease",
            dry_run=False,
            publish_lease_path=None,
            publish_lease_token="",
            env_id=MODULE.ENV_ID,
            service_name=MODULE.SERVICE_NAME,
            data_root=MODULE.DEFAULT_DATA_ROOT,
        )

        with self.assertRaisesRegex(ValueError, "requires --publish-lease"):
            MODULE.run(args)

    def test_direct_deploy_binds_and_rechecks_same_service_lease_before_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = root / "context"
            write_valid_context(context)
            out_dir = root / "reports"
            lease_hash = "e" * 64
            lease_evidence = {
                "schema_version": "weekly_cloudrun_service_publish_lease.v1",
                "lease_path": str(root / "publish.lease"),
                "lease_token_sha256": lease_hash,
                "transaction_id": "run-bound-lease",
                "env_id": MODULE.ENV_ID,
                "service_name": MODULE.SERVICE_NAME,
                "owner_pid": 123,
            }
            args = types.SimpleNamespace(
                transaction_id="run-bound-lease",
                dry_run=False,
                publish_lease_path=root / "publish.lease",
                publish_lease_token="a" * 32,
                env_id=MODULE.ENV_ID,
                service_name=MODULE.SERVICE_NAME,
                data_root=root / "data",
                out_dir=out_dir,
                context_dir=context,
                max_wait_seconds=30,
                allow_unverified_task_poll=False,
            )
            identities = {
                "captured_at": MODULE.now_iso(),
                "base_url": "https://weekly.example.invalid",
                "active_version": "weekly-api-bound",
                "active_flow_ratio": 100,
            }
            build = {
                "PackageName": "fixture-package",
                "PackageVersion": "fixture-version",
                "UploadUrl": "https://upload.example.invalid/signed",
            }
            with mock.patch.object(
                MODULE,
                "validate_held_service_publish_lease",
                side_effect=[dict(lease_evidence), dict(lease_evidence)],
            ) as validate_lease, mock.patch.object(
                MODULE, "describe_cloudrun_server_identity", return_value=identities
            ), mock.patch.object(
                MODULE, "tcb_api", return_value=build
            ), mock.patch.object(
                MODULE, "upload_package"
            ), mock.patch.object(
                MODULE,
                "update_cloudrun_server",
                return_value={"TaskId": 7, "RequestId": "fixture-request"},
            ), mock.patch.object(
                MODULE,
                "poll_task",
                return_value={"ok": True, "status": "success", "version_name": "weekly-api-bound"},
            ):
                report = MODULE.run(args)

            self.assertEqual(validate_lease.call_count, 2)
            self.assertEqual(report["evidence_binding"]["publish_lease_token_sha256"], lease_hash)
            self.assertEqual(
                report["service_publish_lease_revalidated_before_update"]["lease_token_sha256"],
                lease_hash,
            )

    def test_previous_server_identity_is_a_hard_gate_before_remote_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = root / "context"
            write_valid_context(context)
            args = types.SimpleNamespace(
                transaction_id="run-no-rollback-target",
                dry_run=False,
                publish_lease_path=root / "publish.lease",
                publish_lease_token="a" * 32,
                env_id=MODULE.ENV_ID,
                service_name=MODULE.SERVICE_NAME,
                data_root=root / "data",
                out_dir=root / "reports",
                context_dir=context,
                max_wait_seconds=30,
                allow_unverified_task_poll=False,
            )
            lease = {"lease_token_sha256": "e" * 64}
            with mock.patch.object(
                MODULE, "validate_held_service_publish_lease", return_value=lease
            ), mock.patch.object(
                MODULE,
                "describe_cloudrun_server_identity",
                side_effect=RuntimeError("credential-bearing upstream error"),
            ), mock.patch.object(MODULE, "update_cloudrun_server") as update:
                report = MODULE.run(args)

            update.assert_not_called()
            self.assertFalse(report["ok"])
            self.assertEqual(report["decision"], "cloudrun_direct_api_blocked_previous_identity")
            serialized = json.dumps(report)
            self.assertNotIn("credential-bearing", serialized)
            self.assertFalse(report["remote_mutation"]["update_attempted"])

    def test_update_response_is_journaled_before_task_id_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = root / "context"
            write_valid_context(context)
            out_dir = root / "reports"
            args = types.SimpleNamespace(
                transaction_id="run-invalid-task-id",
                dry_run=False,
                publish_lease_path=root / "publish.lease",
                publish_lease_token="a" * 32,
                env_id=MODULE.ENV_ID,
                service_name=MODULE.SERVICE_NAME,
                data_root=root / "data",
                out_dir=out_dir,
                context_dir=context,
                max_wait_seconds=30,
                allow_unverified_task_poll=False,
            )
            lease = {"lease_token_sha256": "e" * 64}
            identity = {
                "captured_at": MODULE.now_iso(),
                "base_url": "https://weekly.example.invalid",
                "active_version": "weekly-api-old",
                "active_flow_ratio": 100,
            }
            build = {
                "PackageName": "fixture-package",
                "PackageVersion": "fixture-version",
                "UploadUrl": "https://upload.example.invalid/signed",
            }
            with mock.patch.object(
                MODULE,
                "validate_held_service_publish_lease",
                side_effect=[dict(lease), dict(lease)],
            ), mock.patch.object(
                MODULE, "describe_cloudrun_server_identity", return_value=identity
            ), mock.patch.object(
                MODULE, "tcb_api", return_value=build
            ), mock.patch.object(
                MODULE, "upload_package"
            ), mock.patch.object(
                MODULE,
                "update_cloudrun_server",
                return_value={"TaskId": "not-an-int", "RequestId": "remote-accepted"},
            ), mock.patch.object(MODULE, "poll_task") as poll:
                report = MODULE.run(args)

            poll.assert_not_called()
            self.assertFalse(report["ok"])
            self.assertTrue(report["safety"]["cloud_deploy_executed"])
            self.assertTrue(report["remote_mutation"]["update_attempted"])
            self.assertEqual(report["remote_mutation"]["state"], "update_response_received")
            self.assertEqual(report["deployment_identity"]["request_id"], "remote-accepted")
            self.assertEqual(report["previous_server_identity"]["active_version"], "weekly-api-old")
            persisted = json.loads(
                (out_dir / "cloudrun_direct_api_deploy_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["deployment_identity"]["request_id"], "remote-accepted")

    def test_main_preserves_mutation_journal_and_redacts_unexpected_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "reports"
            out_dir.mkdir(parents=True)
            report_path = out_dir / "cloudrun_direct_api_deploy_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "schema_version": "cloudrun_direct_api_deploy.v2",
                        "ok": False,
                        "decision": "cloudrun_direct_api_update_attempted",
                        "previous_server_identity": {"active_version": "weekly-api-old"},
                        "remote_mutation": {
                            "state": "update_attempted_unknown",
                            "update_attempted": True,
                        },
                        "safety": {"cloud_deploy_executed": True},
                    }
                ),
                encoding="utf-8",
            )
            args = types.SimpleNamespace(out_dir=out_dir, no_timeout=False)
            with mock.patch.object(MODULE, "parse_args", return_value=args), mock.patch.object(
                MODULE, "run", side_effect=ValueError("SUPERSECRET signed url")
            ), mock.patch("builtins.print"):
                rc = MODULE.main()

            self.assertEqual(rc, 2)
            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["previous_server_identity"]["active_version"], "weekly-api-old")
            self.assertTrue(persisted["remote_mutation"]["update_attempted"])
            self.assertNotIn("SUPERSECRET", json.dumps(persisted))
            self.assertEqual(persisted["failure"]["code"], "cloudrun_direct_api_unexpected_exception")

    def test_context_binding_verifies_file_hashes_and_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp) / "context"
            manifest_path, context_manifest, generation_id = write_valid_context(context)

            evidence = MODULE.validate_deploy_context(context)

            self.assertEqual(evidence["fingerprint"], context_manifest["fingerprint"])
            self.assertEqual(evidence["expected_generation_id"], generation_id)

            (context / "UNLISTED.mjs").write_text("export default 'unsafe';\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unlisted"):
                MODULE.validate_deploy_context(context)
            (context / "UNLISTED.mjs").unlink()

            manifest_path.write_text('{"generation_id":"tampered"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "(size|digest) mismatch"):
                MODULE.validate_deploy_context(context)

    def test_zip_context_records_content_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp) / "context"
            write_valid_context(context, {"server.mjs": "export default 1;\n"})
            zip_path = Path(tmp) / "context.zip"

            info = MODULE.zip_context(context, zip_path)

            self.assertEqual(info["zip_sha256"], hashlib.sha256(zip_path.read_bytes()).hexdigest())
            self.assertRegex(info["zip_sha256"], r"^[0-9a-f]{64}$")
            with zipfile.ZipFile(zip_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"data/current_release/manifest.json", "server.mjs", "deploy_context_manifest.json"},
                )


if __name__ == "__main__":
    unittest.main()
