#!/usr/bin/env python3
"""Bake a new weekly release into the CloudRun image and deploy it.

Workflow
--------
1. (Optional) Check / apply tcb CLI envId patch.
2. Stage release data, source_url_map, and a self-contained deploy context in a
   unique external publish transaction. Authoritative current_release is not
   changed by prepare or deploy.
3. Deploy the staged context (or let the OpenClaw wrapper use its direct API).
4. After remote smoke, full item-ID pagination, and exact club-overviews
   reconciliation succeed, explicitly promote the named transaction with all
   evidence reports.
5. Promotion keeps a versioned rollback backup and restores the old local
   baseline if the filesystem swap fails.

This backend workflow never rewrites mini-program offlineSnapshot.js and never
uploads a mini-program version. Activity updates reach clients through the
online API and the persisted last-good response cache.

Usage examples
--------------
# Stage the latest named release without changing current_release:
python scripts/bake_and_deploy.py \
    --release-dir "E:\\weekly_activity_pipeline\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD" \
    --source-url-map "E:\\weekly_activity_pipeline\\longrun\\source_actions\\source_url_map.json" \
    --transaction-id weekly-YYYYMMDD --prepare-only

# Dry-run (show what would be copied/run, make no changes):
python scripts/bake_and_deploy.py --release-dir ... --dry-run

# Skip QR generation (CI / headless):
python scripts/bake_and_deploy.py --release-dir ... --no-qr
"""
import argparse
import contextlib
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config defaults (override via CLI args)
# ---------------------------------------------------------------------------
ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
SERVICE_NAME = "weekly-api"
TCB_CMD = "npm exec --yes --package @cloudbase/cli@3.3.1 -- tcb"
DEFAULT_DEPLOY_MODE = "source-upload"
DEVTOOLS_CLI = Path(r"C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat")
ROUTE_PROPAGATION_DELAY = 70  # seconds — CloudRun needs ~60s after deploy

# Paths relative to this script's project root (services/weekly_activity_cloudrun/)
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _SCRIPT_DIR.parent
_REPO_ROOT = _PROJECT_DIR.parents[1]
_STAGE7_SCRIPTS_DIR = _REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
if str(_STAGE7_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_STAGE7_SCRIPTS_DIR))

from verify_weekly_club_overviews_remote import build_snapshot as build_club_overviews_snapshot  # noqa: E402
from stamp_weekly_api_generation import validate_derived_route_closure  # noqa: E402
from weekly_public_projection import assert_public_payload, scrub_public_package_payload  # noqa: E402
from promote_dj_bio_atoms import (  # noqa: E402
    DB_NAME as DJ_BIO_ATLAS_DB_NAME,
    INDEX_NAME as DJ_BIO_ATLAS_INDEX_NAME,
    REPORT_SCHEMA_VERSION as DJ_BIO_PROMOTION_SCHEMA_VERSION,
    promote_dj_bio_atoms as apply_dj_bio_promotion,
)

MINIPROGRAM_DIR = _REPO_ROOT / "apps" / "weekly_activity_miniprogram"
DEFAULT_RUNTIME_DATA_ROOT = Path(
    r"F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data"
)
DATA_ROOT = _PROJECT_DIR / "data"
DATA_CURRENT_RELEASE = DATA_ROOT / "current_release"
DATA_SOURCE_ACTIONS = DATA_ROOT / "source_actions"
DATA_STAGE7_ATLAS = DATA_ROOT / "stage7_atlas"
WORK_ROOT = _PROJECT_DIR / "tmp"
DEPLOY_CONTEXT_DIR = WORK_ROOT / "cloudrun_deploy_context"
DEPLOY_CONTEXT_MANIFEST = "deploy_context_manifest.json"
PUBLISH_TRANSACTIONS_DIR = "publish_transactions"
PUBLISH_TRANSACTION_REPORT = "publish_transaction.json"
DJ_BIO_PROMOTION_REPORT_ITEM = "dj_bio_promotion.json"
DEPLOY_CONTEXT_TOP_ITEMS = ["package.json", "package-lock.json", "Dockerfile", "assets", "src", "scripts"]
MINIAPP_ATLAS_INDEX_ITEMS = [
    "atlas_index.json.gz",
    "atlas_neighborhood.json.gz",
    "atlas_starmap_lenses.json.gz",
    "dj_relation_trajectory_lens.json.gz",
    "dj_external_links_accepted_candidate.json.gz",
    "scene_clusters_candidate.json.gz",
    "radio_programs_candidate.json.gz",
    "radio_external_links_public_seed_candidate.json.gz",
]

# Files / dirs to copy from release dir into current_release
RELEASE_ITEMS = [
    "current.json",
    "manifest.json",
    "column.json",
    "by-city",
    "by-date",
    "by-id",
]
# SUMMARY.md, materialized LLM outputs, and the read-only weekly Atlas bridge
# files are optional for older releases, but when present they must ship with
# the release. The public API exposes /weekly/llm/materialized-* and
# /weekly/atlas-events/:id from these baked static files; CloudRun must not call
# live LLM/vector/graph services at request time.
OPTIONAL_RELEASE_ITEMS = [
    "SUMMARY.md",
    "club_overviews.json",
    "llm",
    "weekly_entity_snapshot.json",
    "weekly_entity_observations.jsonl",
]
CLUB_OVERVIEWS_SCHEMA_VERSION = "club_overviews.v1"
DIRECT_DEPLOY_REPORT_SCHEMA_VERSION = "cloudrun_direct_api_deploy.v2"
SMOKE_REPORT_SCHEMA_VERSION = "stage7_cloudrun_weekly_production_smoke.v2"
PAGINATION_REPORT_SCHEMA_VERSION = "cloudrun_remote_pagination.v2"
CLUB_OVERVIEWS_REPORT_SCHEMA_VERSION = "cloudrun_club_overviews_reconciliation.v2"
CLUB_OVERVIEWS_REPORT_DECISION = "cloudrun_club_overviews_reconciled"
EVIDENCE_BINDING_CORE_FIELDS = (
    "transaction_id",
    "env_id",
    "service_name",
    "deploy_context_fingerprint",
    "deploy_zip_sha256",
    "expected_generation_id",
    "publish_lease_token_sha256",
)
CLUB_OVERVIEWS_DIGEST_ALGORITHM = "sha256(canonical_backend_normalized_club_overviews_json)"


class PublishPromotionLockError(RuntimeError):
    """Another process owns the local authoritative promotion lane."""


SERVICE_PUBLISH_LEASE_SCHEMA_VERSION = "weekly_cloudrun_service_publish_lease.v1"


def _safe_lease_segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    if not normalized:
        raise ValueError("service publish lease scope cannot be empty")
    return normalized.lower()


def service_publish_lease_path(data_root: Path, env_id: str, service_name: str) -> Path:
    """Return the one kernel-lock lane for a CloudRun env/service pair."""

    env_scope = _safe_lease_segment(env_id)
    service_scope = _safe_lease_segment(service_name)
    return _resolved(Path(data_root)) / ".locks" / f"cloudrun_publish_{env_scope}_{service_scope}.lease"


def service_publish_lease_metadata_path(lease_path: Path) -> Path:
    selected = Path(lease_path)
    return selected.with_name(selected.name + ".json")


def validate_held_service_publish_lease(
    *,
    lease_path: Path,
    lease_token: str,
    transaction_id: str,
    env_id: str,
    service_name: str,
    data_root: Path,
) -> dict:
    """Validate that the wrapper still owns the exact service-scoped OS lease.

    The coordination token is stored in a sidecar only after the wrapper has
    obtained the byte-range lock.  A contender cannot publish a new sidecar
    without first owning that same lock.  This function deliberately attempts
    the non-blocking lock and succeeds only when another process still holds it.
    """

    transaction_id = validate_transaction_id(transaction_id)
    token = str(lease_token or "").strip()
    if not re.fullmatch(r"[A-Fa-f0-9]{32,128}", token):
        raise ValueError("service publish lease token must be a 32-128 character hex nonce")
    selected = _resolved(Path(lease_path))
    expected = service_publish_lease_path(Path(data_root), env_id, service_name)
    if selected != expected:
        raise ValueError(f"service publish lease path mismatch: expected={expected} actual={selected}")
    metadata_path = service_publish_lease_metadata_path(selected)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"service publish lease metadata missing or invalid: {metadata_path}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("service publish lease metadata must be an object")
    checks = {
        "schema": metadata.get("schema_version") == SERVICE_PUBLISH_LEASE_SCHEMA_VERSION,
        "token": metadata.get("lease_token") == token,
        "transaction": metadata.get("transaction_id") == transaction_id,
        "env": metadata.get("env_id") == env_id,
        "service": metadata.get("service_name") == service_name,
        "owner_pid": int(metadata.get("owner_pid") or 0) > 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("service publish lease metadata mismatch: " + ", ".join(failed))

    try:
        with publish_promotion_lock(selected):
            pass
    except PublishPromotionLockError:
        pass
    else:
        raise ValueError("service publish lease is not held by another process")

    return {
        "schema_version": SERVICE_PUBLISH_LEASE_SCHEMA_VERSION,
        "lease_path": str(selected),
        "lease_token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "transaction_id": transaction_id,
        "env_id": env_id,
        "service_name": service_name,
        "owner_pid": int(metadata.get("owner_pid") or 0),
    }


@contextlib.contextmanager
def publish_promotion_lock(lock_path: Path):
    """Hold a kernel-enforced, non-blocking lock for one complete promotion."""

    selected = _resolved(Path(lock_path))
    selected.parent.mkdir(parents=True, exist_ok=True)
    handle = selected.open("a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (OSError, BlockingIOError) as exc:
            raise PublishPromotionLockError(
                f"publish promotion lock is already held: {selected}"
            ) from exc
        yield selected
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        else:
            handle.close()


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
    except ValueError:
        return False
    return True


def configure_runtime_paths(
    *,
    data_root: str = "",
    current_release_dir: str = "",
    work_root: str = "",
    production_write: bool,
) -> tuple[Path, Path, Path]:
    """Configure mutable CloudRun state outside the immutable source checkout."""

    global DATA_ROOT, DATA_CURRENT_RELEASE, DATA_SOURCE_ACTIONS, DATA_STAGE7_ATLAS  # noqa: PLW0603
    global WORK_ROOT, DEPLOY_CONTEXT_DIR  # noqa: PLW0603

    selected_data = str(data_root or os.environ.get("HUAIDJ_CLOUDRUN_DATA_ROOT") or "").strip()
    selected_current = str(
        current_release_dir or os.environ.get("HUAIDJ_CURRENT_RELEASE_DIR") or ""
    ).strip()
    selected_work = str(work_root or os.environ.get("HUAIDJ_CLOUDRUN_WORK_ROOT") or "").strip()
    runtime_configured = bool(selected_data or selected_current)

    if selected_current and not selected_data:
        selected_data = str(Path(selected_current).parent)
    if not selected_data:
        selected_data = str(DEFAULT_RUNTIME_DATA_ROOT)
    if not selected_current:
        selected_current = str(Path(selected_data) / "current_release")
    if (
        not production_write
        and not runtime_configured
        and not Path(selected_current).exists()
    ):
        selected_data = str(_PROJECT_DIR / "data")
        selected_current = str(Path(selected_data) / "current_release")
        if not selected_work:
            selected_work = str(_PROJECT_DIR / "tmp")
    if not selected_work:
        selected_work = str(Path(selected_data).parent / "work")

    resolved_data = _resolved(Path(selected_data))
    resolved_current = _resolved(Path(selected_current))
    resolved_work = _resolved(Path(selected_work))
    if resolved_current != resolved_data / "current_release":
        raise ValueError(
            "current_release_dir must equal <data_root>/current_release for an atomic runtime layout"
        )
    if production_write:
        if _is_within(resolved_data, _REPO_ROOT):
            raise ValueError("production CloudRun data root must be outside the source checkout")
        if _is_within(resolved_work, _REPO_ROOT):
            raise ValueError("production CloudRun work root must be outside the source checkout")

    DATA_ROOT = resolved_data
    DATA_CURRENT_RELEASE = resolved_current
    DATA_SOURCE_ACTIONS = DATA_ROOT / "source_actions"
    DATA_STAGE7_ATLAS = DATA_ROOT / "stage7_atlas"
    WORK_ROOT = resolved_work
    DEPLOY_CONTEXT_DIR = WORK_ROOT / "cloudrun_deploy_context"
    return DATA_ROOT, DATA_CURRENT_RELEASE, WORK_ROOT
MATERIALIZED_LLM_REQUIRED_ITEMS = [
    Path("llm") / "weekly_summary.json",
    Path("llm") / "enrichment_index.json",
]
REQUIRED_STAGE7_STATIC_ITEMS = [
    "release_pointer.staging.json",
    "recommendations.json",
    "graph_rag_answer_drafts.jsonl",
    "vector_collection_router_smoke.json",
    "identity_review_workbench.json",
    "package_manifest.json",
]


def run(cmd: list[str], cwd: Path | None = None, dry_run: bool = False) -> int:
    label = " ".join(str(c) for c in cmd)
    if dry_run:
        print(f"[DRY-RUN] {label}")
        return 0
    resolved = shutil.which(cmd[0])
    if resolved:
        cmd = [resolved, *cmd[1:]]
    print(f"$ {label}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


def run_capture(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    resolved = shutil.which(cmd[0])
    if resolved:
        cmd = [resolved, *cmd[1:]]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def run_capture_checked(cmd: list[str], cwd: Path | None = None) -> str:
    label = " ".join(str(c) for c in cmd)
    resolved = shutil.which(cmd[0])
    if resolved:
        cmd = [resolved, *cmd[1:]]
    print(f"$ {label}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError(f"command exited {result.returncode}: {label}")
    return result.stdout.strip()


def parse_first_json_object(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def detect_active_version() -> str:
    cmd = TCB_CMD.split() + [
        "run:deprecated",
        "version",
        "list",
        "--envId",
        ENV_ID,
        "--serviceName",
        SERVICE_NAME,
        "--limit",
        "30",
        "--json",
    ]
    result = run_capture(cmd, cwd=_PROJECT_DIR)
    payload = parse_first_json_object((result.stdout or "") + "\n" + (result.stderr or ""))
    versions = payload.get("data") if isinstance(payload.get("data"), list) else []
    active = [item for item in versions if int(item.get("flowRatio") or 0) == 100 and item.get("versionName")]
    if active:
        return str(active[-1]["versionName"])
    normal = [item for item in versions if item.get("status") == "Normal" and item.get("versionName")]
    return str(normal[-1]["versionName"]) if normal else ""


def describe_cloudrun_server_for_promotion(
    env_id: str,
    service_name: str,
    *,
    timeout_seconds: int = 30,
) -> dict:
    """Read the authoritative active CloudRun version immediately before promotion."""

    cmd = TCB_CMD.split() + [
        "api",
        "tcbr",
        "DescribeCloudRunServerDetail",
        "--api-version",
        "2022-02-17",
        "--body",
        json.dumps(
            {"EnvId": env_id, "ServerName": service_name},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "--json",
    ]
    resolved = shutil.which(cmd[0])
    if resolved:
        cmd = [resolved, *cmd[1:]]
    result = subprocess.run(
        cmd,
        cwd=_PROJECT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    payload = parse_first_json_object((result.stdout or "") + "\n" + (result.stderr or ""))
    if result.returncode != 0:
        raise RuntimeError(
            f"CloudBase active-version revalidation failed with returncode={result.returncode}"
        )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    base = data.get("BaseInfo") if isinstance(data.get("BaseInfo"), dict) else {}
    versions = data.get("OnlineVersionInfos") if isinstance(data.get("OnlineVersionInfos"), list) else []
    normalized_versions = []
    for item in versions:
        if not isinstance(item, dict):
            continue
        normalized_versions.append(
            {
                "version_name": str(item.get("VersionName") or item.get("versionName") or ""),
                "flow_ratio": item.get("FlowRatio", item.get("flowRatio", "")),
            }
        )
    def is_full_flow(value: object) -> bool:
        try:
            return float(value) == 100.0
        except (TypeError, ValueError):
            return False

    active = next(
        (item for item in normalized_versions if is_full_flow(item.get("flow_ratio"))),
        normalized_versions[0] if normalized_versions else {},
    )
    return {
        "base_url": str(base.get("DefaultDomainName") or "").rstrip("/"),
        "status": str(base.get("Status") or ""),
        "active_version": str(active.get("version_name") or ""),
        "active_flow_ratio": active.get("flow_ratio", ""),
    }


def read_remote_readyz_for_promotion(
    base_url: str,
    *,
    proxy_url: str = "",
    timeout_seconds: int = 30,
) -> dict:
    url = f"{str(base_url).rstrip('/')}/readyz"
    handlers = []
    if str(proxy_url or "").strip():
        handlers.append(
            urllib.request.ProxyHandler(
                {"http": str(proxy_url).strip(), "https": str(proxy_url).strip()}
            )
        )
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "huaidj-promotion-revalidation/1.0"},
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_000)
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read(256_000)
        status_code = int(exc.code)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        payload = {}
    return {
        "status_code": status_code,
        "payload": payload if isinstance(payload, dict) else {},
    }


def revalidate_remote_promotion_target(
    *,
    transaction_id: str,
    evidence_binding: dict,
    candidate_generation_id: str,
    candidate_item_id_digest: str,
    candidate_item_count: int,
    proxy_url: str = "",
    timeout_seconds: int = 30,
) -> dict:
    """Re-read version routing and /readyz as the last gate before local swap."""

    server = describe_cloudrun_server_for_promotion(
        ENV_ID,
        SERVICE_NAME,
        timeout_seconds=timeout_seconds,
    )
    bound_base_url = str(evidence_binding.get("base_url") or "").rstrip("/")
    ready_response = read_remote_readyz_for_promotion(
        bound_base_url,
        proxy_url=proxy_url,
        timeout_seconds=timeout_seconds,
    )
    ready = ready_response.get("payload") if isinstance(ready_response.get("payload"), dict) else {}
    observed_generation = str(ready.get("generationId") or "")
    observed_digest = str(ready.get("itemIdDigest") or "")
    checks = {
        "transaction_id_bound": evidence_binding.get("transaction_id") == transaction_id,
        "env_id_bound": evidence_binding.get("env_id") == ENV_ID,
        "service_name_bound": evidence_binding.get("service_name") == SERVICE_NAME,
        "candidate_generation_bound": evidence_binding.get("expected_generation_id")
        == candidate_generation_id,
        "active_version_matches": bool(evidence_binding.get("active_version"))
        and server.get("active_version") == evidence_binding.get("active_version"),
        "active_flow_is_100": str(server.get("active_flow_ratio")) in {"100", "100.0"},
        "server_is_normal": str(server.get("status") or "").lower() == "normal",
        "base_url_matches": bool(bound_base_url)
        and str(server.get("base_url") or "").rstrip("/") == bound_base_url,
        "readyz_http_200": ready_response.get("status_code") == 200,
        "readyz_ok": ready.get("ok") is True,
        "readyz_service_matches": ready.get("service") == SERVICE_NAME,
        "readyz_generation_matches": observed_generation == candidate_generation_id,
        "readyz_item_digest_matches": observed_digest == candidate_item_id_digest,
        "readyz_item_count_matches": int(ready.get("packageItemCount") or -1)
        == int(candidate_item_count),
    }
    ok = all(checks.values())
    return {
        "schema_version": "cloudrun_remote_promotion_revalidation.v1",
        "generated_at": now_iso(),
        "ok": ok,
        "decision": (
            "cloudrun_remote_promotion_target_revalidated"
            if ok
            else "cloudrun_remote_promotion_target_changed"
        ),
        "checks": checks,
        "evidence_binding": {
            "transaction_id": transaction_id,
            "env_id": ENV_ID,
            "service_name": SERVICE_NAME,
            "deploy_context_fingerprint": evidence_binding.get("deploy_context_fingerprint"),
            "deploy_zip_sha256": evidence_binding.get("deploy_zip_sha256"),
            "publish_lease_token_sha256": evidence_binding.get("publish_lease_token_sha256"),
            "candidate_generation_id": candidate_generation_id,
            "candidate_item_id_digest": candidate_item_id_digest,
            "candidate_item_count": int(candidate_item_count),
            "expected_active_version": evidence_binding.get("active_version"),
            "observed_active_version": server.get("active_version"),
            "base_url": bound_base_url,
            "observed_readyz_generation_id": observed_generation,
            "observed_readyz_item_id_digest": observed_digest,
        },
    }


def copy_item(src: Path, dst: Path, dry_run: bool) -> None:
    if not src.exists():
        print(f"  SKIP (not found): {src}")
        return
    if dry_run:
        kind = "dir" if src.is_dir() else "file"
        print(f"  [DRY-RUN] copy {kind}: {src}  →  {dst}")
        return
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"  copied: {dst.name}")


def materialized_llm_complete(data_dir: Path) -> bool:
    return all((data_dir / item).is_file() for item in MATERIALIZED_LLM_REQUIRED_ITEMS)


def read_json_file(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def package_item_count(data_dir: Path) -> tuple[int, list[str]]:
    failures: list[str] = []
    manifest = read_json_file(data_dir / "manifest.json")
    current = read_json_file(data_dir / "current.json")
    try:
        manifest_count = int(manifest.get("item_count") or 0)
    except (TypeError, ValueError):
        manifest_count = 0
    items = current.get("items")
    current_count = len(items) if isinstance(items, list) else 0
    if manifest_count <= 0:
        failures.append("manifest_item_count_not_positive")
    if current_count <= 0:
        failures.append("current_item_count_not_positive")
    if manifest_count and current_count and manifest_count != current_count:
        failures.append("manifest_current_item_count_mismatch")
    return current_count, failures


def validate_production_bake_input(release_dir: Path) -> tuple[bool, list[str]]:
    """Prevent a stale candidate from replacing a larger authoritative base."""

    base_count, base_failures = package_item_count(DATA_CURRENT_RELEASE)
    release_count, release_failures = package_item_count(release_dir)
    failures = [f"base_{item}" for item in base_failures]
    failures.extend(f"release_{item}" for item in release_failures)
    if base_count > 0 and release_count > 0 and release_count < base_count:
        failures.append("release_item_count_below_authoritative_base")
    # Only inspect closure once the basic package/count contract is plausible;
    # this keeps the primary blocker concise for obviously truncated releases.
    if not release_failures and "release_item_count_below_authoritative_base" not in failures:
        try:
            validate_derived_route_closure(release_dir)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"  ERROR: candidate derived route closure failed: {error}")
            failures.append("release_derived_route_closure_failed")
    return not failures, sorted(set(failures))


def parse_iso_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.astimezone(timezone.utc)


def materialized_llm_current(data_dir: Path) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not materialized_llm_complete(data_dir):
        reasons.append("missing_required_llm_files")
        return False, reasons

    current = read_json_file(data_dir / "current.json")
    items = current.get("items")
    if not isinstance(items, list) or not items:
        reasons.append("missing_current_items")
        return False, reasons
    item_ids = {str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")}
    if len(item_ids) != len(items):
        reasons.append("current_item_ids_incomplete")

    expected_count = len(items)
    summary = read_json_file(data_dir / "llm" / "weekly_summary.json")
    index = read_json_file(data_dir / "llm" / "enrichment_index.json")
    report = read_json_file(data_dir / "llm" / "materialize_report.json")
    enrichments = index.get("enrichments") if isinstance(index.get("enrichments"), list) else []
    enrichment_ids = {str(item.get("id")) for item in enrichments if isinstance(item, dict) and item.get("id")}

    if int(summary.get("itemCount") or 0) != expected_count:
        reasons.append("summary_item_count_mismatch")
    if int(index.get("itemCount") or 0) != expected_count:
        reasons.append("enrichment_index_item_count_mismatch")
    if len(enrichments) != expected_count:
        reasons.append("enrichment_count_mismatch")
    if enrichment_ids != item_ids:
        reasons.append("enrichment_id_set_mismatch")
    if report:
        if int(report.get("itemCount") or 0) != expected_count:
            reasons.append("materialize_report_item_count_mismatch")
        if int(report.get("enrichWritten") or 0) != expected_count:
            reasons.append("materialize_report_enrich_count_mismatch")

    manifest_time = parse_iso_time(read_json_file(data_dir / "manifest.json").get("generated_at"))
    generated_time = parse_iso_time(report.get("generatedAt") or index.get("generatedAt") or summary.get("generatedAt"))
    if manifest_time and generated_time and generated_time < manifest_time:
        reasons.append("materialized_llm_older_than_manifest")

    return not reasons, reasons


def ensure_source_grounded_llm_materialized(
    dry_run: bool,
    data_dir: Path | None = None,
) -> bool:
    """Ensure release ships deterministic materialized LLM files for runtime fallback."""
    target_dir = data_dir or DATA_CURRENT_RELEASE
    current, reasons = materialized_llm_current(target_dir)
    if current:
        print("  OK materialized llm outputs current")
        return True
    reason_text = ", ".join(reasons) if reasons else "unknown"
    script = _SCRIPT_DIR / "materialize_source_grounded_outputs.mjs"
    cmd = [
        "node",
        str(script),
        "--data-dir",
        str(target_dir),
        "--all-release-items",
        "--force",
    ]
    label = " ".join(str(c) for c in cmd)
    if dry_run:
        print(f"  [DRY-RUN] refresh source-grounded materialized llm outputs ({reason_text}): {label}")
        return True
    if not script.exists():
        print(f"  ERROR: materialized llm fallback script missing: {script}")
        return False
    print(f"  refreshing source-grounded materialized llm outputs ({reason_text})")
    result = subprocess.run(cmd, cwd=_PROJECT_DIR)
    if result.returncode != 0:
        print(f"  ERROR: materialized llm generation exited {result.returncode}")
        return False
    current, reasons = materialized_llm_current(target_dir)
    if not current:
        print(f"  ERROR: materialized llm outputs stale after generation: {', '.join(reasons)}")
        return False
    print("  OK materialized llm outputs refreshed")
    return True


def copy_context_item(src: Path, dst: Path) -> None:
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_club_overviews_snapshot(release_dir: Path) -> dict:
    path = release_dir / "club_overviews.json"
    if not path.is_file():
        raise FileNotFoundError(f"required club_overviews.json missing: {path}")
    payload = read_json_file(path)
    snapshot = build_club_overviews_snapshot(payload, source="candidate")
    snapshot["file_sha256"] = sha256_file(path)
    return snapshot


def iter_context_files(src: Path, dst_rel: Path) -> list[dict]:
    if src.is_file():
        stat = src.stat()
        return [{
            "dst": dst_rel.as_posix(),
            "src": src.as_posix(),
            "size": stat.st_size,
            "sha256": sha256_file(src),
        }]
    rows = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src)
        stat = path.stat()
        rows.append({
            "dst": (dst_rel / rel).as_posix(),
            "src": path.as_posix(),
            "size": stat.st_size,
            "sha256": sha256_file(path),
        })
    return rows


def build_deploy_context_manifest(
    current_release_items: list[str],
    data_items: list[tuple[str, Path, list[str] | None]],
) -> dict:
    files = []
    for item in DEPLOY_CONTEXT_TOP_ITEMS:
        src = _PROJECT_DIR / item
        if not src.exists():
            raise FileNotFoundError(f"deploy context source missing: {src}")
        files.extend(iter_context_files(src, Path(item)))
    for label, src_dir, names in data_items:
        if names is None:
            if not src_dir.exists():
                raise FileNotFoundError(f"deploy context source missing: {src_dir}")
            files.extend(iter_context_files(src_dir, Path(label)))
            continue
        for name in names:
            src = src_dir / name
            if not src.exists():
                raise FileNotFoundError(f"deploy context source missing: {src}")
            files.extend(iter_context_files(src, Path(label) / name))

    fingerprint_input = json.dumps(
        {
            "files": [{k: row[k] for k in ("dst", "size", "sha256")} for row in files],
            "current_release_items": current_release_items,
            "data_labels": [label for label, _src, _names in data_items],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return {
        "schema_version": "weekly_cloudrun_deploy_context_manifest.v1",
        "fingerprint": hashlib.sha256(fingerprint_input).hexdigest(),
        "file_count": len(files),
        "total_bytes": sum(int(row["size"]) for row in files),
        "current_release_items": current_release_items,
        "data_labels": [label for label, _src, _names in data_items],
        "files": files,
    }


def read_deploy_context_manifest(context_dir: Path | None = None) -> dict:
    path = (context_dir or DEPLOY_CONTEXT_DIR) / DEPLOY_CONTEXT_MANIFEST
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def deploy_context_matches(manifest: dict, context_dir: Path | None = None) -> bool:
    selected_context = context_dir or DEPLOY_CONTEXT_DIR
    if not selected_context.exists():
        return False
    existing = read_deploy_context_manifest(selected_context)
    if existing.get("fingerprint") != manifest.get("fingerprint"):
        return False
    for row in manifest.get("files", []):
        dst = selected_context / str(row.get("dst", ""))
        if not dst.is_file():
            return False
        try:
            if dst.stat().st_size != int(row.get("size", -1)):
                return False
        except OSError:
            return False
    return True


def prepare_deploy_context(
    dry_run: bool,
    include_stage7_atlas: bool = False,
    *,
    context_dir: Path | None = None,
    data_root: Path | None = None,
    current_release_dir: Path | None = None,
    source_actions_dir: Path | None = None,
    stage7_atlas_dir: Path | None = None,
) -> Path:
    """Build a minimal CloudRun deploy context for source upload and image build."""
    selected_context = context_dir or DEPLOY_CONTEXT_DIR
    selected_data = data_root or DATA_ROOT
    selected_current = current_release_dir or DATA_CURRENT_RELEASE
    selected_source_actions = source_actions_dir or DATA_SOURCE_ACTIONS
    selected_stage7 = stage7_atlas_dir or DATA_STAGE7_ATLAS
    print(f"\n--- prepare deploy context: {selected_context} ---")
    if not dry_run:
        # The deploy context is the last filesystem boundary before source
        # upload.  Refuse any raw item/debug path even when callers bypass the
        # higher-level publish-transaction helper.
        validate_derived_route_closure(selected_current)
    current_release_items = [
        *RELEASE_ITEMS,
        *[item for item in OPTIONAL_RELEASE_ITEMS if (selected_current / item).exists()],
    ]
    atlas_context_items = [
        *MINIAPP_ATLAS_INDEX_ITEMS,
        *(
            [DJ_BIO_PROMOTION_REPORT_ITEM]
            if (selected_data / DJ_BIO_PROMOTION_REPORT_ITEM).is_file()
            else []
        ),
    ]
    data_items = [
        ("data", selected_data, atlas_context_items),
        ("data/current_release", selected_current, current_release_items),
        ("data/source_actions", selected_source_actions, ["source_url_map.json"]),
    ]
    if include_stage7_atlas:
        data_items.append(("data/stage7_atlas", selected_stage7, None))
    manifest = None
    if not dry_run:
        manifest = build_deploy_context_manifest(current_release_items, data_items)
        if deploy_context_matches(manifest, selected_context):
            print(
                "  reused deploy context: "
                f"fingerprint={manifest['fingerprint'][:12]} files={manifest['file_count']} "
                f"bytes={manifest['total_bytes']}"
            )
            return selected_context

    if dry_run:
        for item in DEPLOY_CONTEXT_TOP_ITEMS:
            print(f"  [DRY-RUN] stage {item}")
        for label, _src_dir, names in data_items:
            if names is None:
                print(f"  [DRY-RUN] stage {label}/")
            else:
                for name in names:
                    print(f"  [DRY-RUN] stage {label}/{name}")
        return selected_context

    if selected_context.exists():
        shutil.rmtree(selected_context)
    selected_context.mkdir(parents=True, exist_ok=True)
    for item in DEPLOY_CONTEXT_TOP_ITEMS:
        src = _PROJECT_DIR / item
        if not src.exists():
            raise FileNotFoundError(f"deploy context source missing: {src}")
        copy_context_item(src, selected_context / item)
        print(f"  staged: {item}")
    for label, src_dir, names in data_items:
        if names is None:
            if not src_dir.exists():
                raise FileNotFoundError(f"deploy context source missing: {src_dir}")
            copy_context_item(src_dir, selected_context / label)
            print(f"  staged: {label}/")
            continue
        for name in names:
            src = src_dir / name
            if not src.exists():
                raise FileNotFoundError(f"deploy context source missing: {src}")
            copy_context_item(src, selected_context / label / name)
            print(f"  staged: {label}/{name}")
    if manifest is not None:
        (selected_context / DEPLOY_CONTEXT_MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(
            "  wrote deploy context manifest: "
            f"fingerprint={manifest['fingerprint'][:12]} files={manifest['file_count']} "
            f"bytes={manifest['total_bytes']}"
        )
    return selected_context


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def directory_snapshot(path: Path) -> dict:
    files = []
    if path.exists():
        for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
            files.append(
                {
                    "path": item.relative_to(path).as_posix(),
                    "size": item.stat().st_size,
                    "sha256": sha256_file(item),
                }
            )
    encoded = json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "exists": path.exists(),
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
        "file_count": len(files),
        "total_bytes": sum(int(item["size"]) for item in files),
        "files": files,
    }


def authoritative_runtime_snapshot() -> dict:
    current = directory_snapshot(DATA_CURRENT_RELEASE)
    source_map = DATA_SOURCE_ACTIONS / "source_url_map.json"
    source = {
        "exists": source_map.is_file(),
        "size": source_map.stat().st_size if source_map.is_file() else 0,
        "sha256": sha256_file(source_map) if source_map.is_file() else "",
    }
    encoded = json.dumps(
        {"current_release": current["fingerprint"], "source_url_map": source},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return {
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
        "current_release": current,
        "source_url_map": source,
    }


def package_item_id_snapshot(data_dir: Path) -> dict:
    current = read_json_file(data_dir / "current.json")
    items = current.get("items") if isinstance(current.get("items"), list) else []
    ids = [str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")]
    unique_ids = sorted(set(ids))
    digest = hashlib.sha256(
        "\n".join(unique_ids).encode("utf-8")
    ).hexdigest()
    return {
        "item_count": len(items),
        "item_id_count": len(ids),
        "unique_item_id_count": len(unique_ids),
        "duplicate_item_id_count": len(ids) - len(unique_ids),
        "digest_algorithm": "sha256(sorted_unique_item_ids_utf8_lf)",
        "item_id_digest": digest,
    }


def normalize_release_manifest_at(
    current_release_dir: Path,
    release_dir: Path,
    deployed_current_release_dir: Path,
) -> None:
    manifest_path = current_release_dir / "manifest.json"
    manifest = read_json_file(manifest_path)
    if not manifest:
        raise ValueError(f"manifest.json missing or invalid after staging: {manifest_path}")
    manifest["source_release_name"] = release_dir.name
    manifest["deployed_release_name"] = deployed_current_release_dir.name
    manifest = scrub_public_package_payload(manifest)
    assert_public_payload(manifest, label="staged weekly manifest.json")
    write_json_atomic(manifest_path, manifest)


def resolve_source_url_map(release_dir: Path, source_url_map: Path | None) -> Path:
    candidates = []
    if source_url_map:
        candidates.append(Path(source_url_map))
    candidates.extend(
        [
            release_dir / "source_actions" / "source_url_map.json",
            release_dir.parent / "source_actions" / "source_url_map.json",
        ]
    )
    selected = next((candidate for candidate in candidates if candidate.is_file()), None)
    if selected is None:
        raise FileNotFoundError("source_url_map.json is required for a publish transaction")
    return selected


def validate_transaction_id(transaction_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", transaction_id):
        raise ValueError("transaction_id must be a safe 1-128 character path label")
    return transaction_id


def atlas_bio_asset_snapshot(data_root: Path, *, required: bool) -> dict:
    """Digest the two local assets owned by an optional bio promotion."""

    selected = Path(data_root)
    assets = {}
    for name in (DJ_BIO_ATLAS_INDEX_NAME, DJ_BIO_ATLAS_DB_NAME):
        path = selected / name
        if not path.is_file():
            if required:
                raise FileNotFoundError(f"DJ bio promotion requires runtime Atlas asset: {path}")
            assets[name] = {"exists": False, "size": 0, "sha256": ""}
            continue
        assets[name] = {
            "exists": True,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    fingerprint_input = json.dumps(assets, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "fingerprint": hashlib.sha256(fingerprint_input).hexdigest(),
        "assets": assets,
    }


def bind_dj_bio_evidence_to_release_manifest(
    *,
    current_release_dir: Path,
    transaction_id: str,
    report_sha256: str,
    evidence: dict,
) -> dict:
    """Bind staged bio evidence into the candidate package manifest."""

    manifest_path = Path(current_release_dir) / "manifest.json"
    manifest = read_json_file(manifest_path)
    if not manifest:
        raise ValueError(f"candidate manifest missing before bio evidence binding: {manifest_path}")
    binding = {
        "schema_version": DJ_BIO_PROMOTION_SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "report_item": DJ_BIO_PROMOTION_REPORT_ITEM,
        "report_sha256": report_sha256,
        "selected_count": int(evidence.get("selected_count") or 0),
        "matched_count": int(evidence.get("matched_count") or 0),
        "db_update_count": int(evidence.get("db_update_count") or 0),
        "index_update_count": int(evidence.get("index_update_count") or 0),
        "changed": evidence.get("changed") is True,
        "atlas_index_sha256": str(
            ((evidence.get("after") or {}).get(DJ_BIO_ATLAS_INDEX_NAME) or {}).get("sha256")
            or ""
        ),
        "atlas_db_sha256": str(
            ((evidence.get("after") or {}).get(DJ_BIO_ATLAS_DB_NAME) or {}).get("sha256")
            or ""
        ),
    }
    manifest.setdefault("publish_transaction_evidence", {})["dj_bio_promotion"] = binding
    write_json_atomic(manifest_path, manifest)
    return binding


def deploy_context_file_entry(manifest: dict, destination: str) -> dict:
    for row in manifest.get("files") or []:
        if isinstance(row, dict) and row.get("dst") == destination:
            return row
    return {}


def prepare_publish_transaction(
    *,
    release_dir: Path,
    source_url_map: Path | None,
    transaction_id: str,
    include_stage7_atlas: bool,
    update_column_json: bool,
    promote_dj_bio_atoms: bool = False,
) -> dict:
    """Stage one immutable publish candidate without changing the authoritative baseline."""
    transaction_id = validate_transaction_id(transaction_id)
    if DATA_ROOT.anchor.lower() != WORK_ROOT.anchor.lower():
        raise ValueError("publish work root and runtime data root must be on the same volume")
    release_dir = _resolved(Path(release_dir))
    if not release_dir.is_dir():
        raise FileNotFoundError(f"release-dir not found: {release_dir}")
    valid_bake, bake_failures = validate_production_bake_input(release_dir)
    if not valid_bake:
        raise ValueError("authoritative base/candidate validation failed: " + ", ".join(bake_failures))
    bio_baseline = atlas_bio_asset_snapshot(DATA_ROOT, required=promote_dj_bio_atoms)

    transaction_dir = WORK_ROOT / PUBLISH_TRANSACTIONS_DIR / transaction_id
    if transaction_dir.exists():
        raise FileExistsError(
            f"publish transaction already exists and will not be silently reused: {transaction_dir}"
        )
    staged_data = transaction_dir / "staged_data"
    staged_current = staged_data / "current_release"
    staged_source_actions = staged_data / "source_actions"
    staged_stage7 = staged_data / "stage7_atlas"
    context_dir = transaction_dir / "deploy_context"
    report_path = transaction_dir / PUBLISH_TRANSACTION_REPORT
    transaction_dir.mkdir(parents=True, exist_ok=False)
    baseline = authoritative_runtime_snapshot()
    report = {
        "schema_version": "weekly_cloudrun_publish_transaction.v1",
        "transaction_id": transaction_id,
        "status": "preparing",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "paths": {
            "transaction_dir": str(transaction_dir),
            "staged_data": str(staged_data),
            "deploy_context": str(context_dir),
            "authoritative_current_release": str(DATA_CURRENT_RELEASE),
        },
        "release_dir": str(release_dir),
        "include_stage7_atlas": bool(include_stage7_atlas),
        "update_column_json": bool(update_column_json),
        "promote_dj_bio_atoms": bool(promote_dj_bio_atoms),
        "baseline": baseline,
    }
    if promote_dj_bio_atoms:
        report["atlas_bio_baseline"] = bio_baseline
    write_json_atomic(report_path, report)

    try:
        staged_current.mkdir(parents=True, exist_ok=False)
        for name in RELEASE_ITEMS:
            if name == "column.json" and not update_column_json:
                source = DATA_CURRENT_RELEASE / name
            else:
                source = release_dir / name
            if not source.exists():
                raise FileNotFoundError(f"required staged release item missing: {source}")
            copy_context_item(source, staged_current / name)
        for name in OPTIONAL_RELEASE_ITEMS:
            source = release_dir / name
            if source.exists():
                copy_context_item(source, staged_current / name)
        candidate_club_overviews = candidate_club_overviews_snapshot(staged_current)

        selected_source_map = resolve_source_url_map(release_dir, source_url_map)
        copy_context_item(selected_source_map, staged_source_actions / "source_url_map.json")
        copy_context_item(
            selected_source_map,
            staged_current / "source_actions" / "source_url_map.json",
        )
        normalize_release_manifest_at(staged_current, release_dir, DATA_CURRENT_RELEASE)

        for name in MINIAPP_ATLAS_INDEX_ITEMS:
            source = DATA_ROOT / name
            if not source.is_file():
                raise FileNotFoundError(f"activity deploy context dependency missing: {source}")
            copy_context_item(source, staged_data / name)
        bio_promotion = None
        bio_manifest_binding = None
        bio_report_sha256 = ""
        if promote_dj_bio_atoms:
            copy_context_item(
                DATA_ROOT / DJ_BIO_ATLAS_DB_NAME,
                staged_data / DJ_BIO_ATLAS_DB_NAME,
            )
            bio_report_path = staged_data / DJ_BIO_PROMOTION_REPORT_ITEM
            bio_promotion = apply_dj_bio_promotion(
                index_path=staged_data / DJ_BIO_ATLAS_INDEX_NAME,
                db_path=staged_data / DJ_BIO_ATLAS_DB_NAME,
                write=True,
                transaction_id=transaction_id,
                report_path=bio_report_path,
            )
            if bio_promotion.get("schema_version") != DJ_BIO_PROMOTION_SCHEMA_VERSION:
                raise ValueError("DJ bio promotion returned an unsupported evidence schema")
            if bio_promotion.get("committed") is not True and int(
                bio_promotion.get("matched_count") or 0
            ) > 0:
                raise RuntimeError("DJ bio promotion matched profiles without committing staged assets")
            bio_report_sha256 = sha256_file(bio_report_path)
            bio_manifest_binding = bind_dj_bio_evidence_to_release_manifest(
                current_release_dir=staged_current,
                transaction_id=transaction_id,
                report_sha256=bio_report_sha256,
                evidence=bio_promotion,
            )

        validate_derived_route_closure(staged_current)
        if not ensure_source_grounded_llm_materialized(False, staged_current):
            raise RuntimeError("staged materialized LLM outputs are incomplete")
        if include_stage7_atlas:
            if not DATA_STAGE7_ATLAS.is_dir():
                raise FileNotFoundError(f"Stage7 atlas package missing: {DATA_STAGE7_ATLAS}")
            if not validate_stage7_atlas(True, DATA_STAGE7_ATLAS):
                raise ValueError("Stage7 atlas package failed required-item validation")
            copy_context_item(DATA_STAGE7_ATLAS, staged_stage7)

        prepare_deploy_context(
            False,
            include_stage7_atlas,
            context_dir=context_dir,
            data_root=staged_data,
            current_release_dir=staged_current,
            source_actions_dir=staged_source_actions,
            stage7_atlas_dir=staged_stage7,
        )
        candidate = directory_snapshot(staged_current)
        staged_manifest = read_json_file(staged_current / "manifest.json")
        candidate_generation_id = str(
            staged_manifest.get("generation_id") or staged_manifest.get("generationId") or ""
        )
        if not candidate_generation_id:
            raise ValueError("staged candidate manifest is missing generation_id")
        item_count, item_failures = package_item_count(staged_current)
        if item_failures:
            raise ValueError("staged candidate package invalid: " + ", ".join(item_failures))
        report.update(
            {
                "status": "prepared",
                "updated_at": now_iso(),
                "prepared_at": now_iso(),
                "candidate": candidate,
                "candidate_generation_id": candidate_generation_id,
                "candidate_item_count": item_count,
                "candidate_item_ids": package_item_id_snapshot(staged_current),
                "candidate_club_overviews": candidate_club_overviews,
                "source_url_map": {
                    "size": (staged_source_actions / "source_url_map.json").stat().st_size,
                    "sha256": sha256_file(staged_source_actions / "source_url_map.json"),
                },
                "deploy_context": read_deploy_context_manifest(context_dir),
            }
        )
        if promote_dj_bio_atoms:
            report["dj_bio_promotion"] = {
                "requested": True,
                "report_item": DJ_BIO_PROMOTION_REPORT_ITEM,
                "report_sha256": bio_report_sha256,
                "evidence": bio_promotion,
                "manifest_binding": bio_manifest_binding,
                "staged_assets": atlas_bio_asset_snapshot(staged_data, required=True),
            }
        write_json_atomic(report_path, report)
        return report
    except Exception as exc:
        report.update(
            {
                "status": "prepare_failed",
                "updated_at": now_iso(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        write_json_atomic(report_path, report)
        raise


def read_required_report(path: Path, label: str) -> dict:
    value = read_json_file(Path(path))
    if not value:
        raise ValueError(f"{label} report missing or invalid: {path}")
    return value


def block_publish_promotion(report_path: Path, report: dict, reason: str) -> None:
    report.update(
        {
            "status": "promotion_blocked",
            "updated_at": now_iso(),
            "promotion_blocked_reason": reason,
        }
    )
    write_json_atomic(report_path, report)


def promote_publish_transaction(
    *,
    transaction_id: str,
    deploy_report_path: Path,
    smoke_report_path: Path,
    pagination_report_path: Path,
    club_overviews_report_path: Path,
    held_lease_path: Path | None = None,
    held_lease_token: str = "",
    promotion_proxy_url: str = "",
    promotion_timeout_seconds: int = 30,
) -> dict:
    """Promote inside the wrapper's deploy-to-promotion service lease.

    Direct callers without an external lease retain the narrow internal lock for
    unit-level/local compatibility.  The production CLI requires the external
    token so bake does not deadlock trying to reacquire its parent's lock.
    """

    if held_lease_path is not None or held_lease_token:
        if held_lease_path is None or not held_lease_token:
            raise ValueError("held service publish lease requires both path and token")
        lease_evidence = validate_held_service_publish_lease(
            lease_path=Path(held_lease_path),
            lease_token=held_lease_token,
            transaction_id=transaction_id,
            env_id=ENV_ID,
            service_name=SERVICE_NAME,
            data_root=DATA_ROOT,
        )
        return _promote_publish_transaction_locked(
            transaction_id=transaction_id,
            deploy_report_path=deploy_report_path,
            smoke_report_path=smoke_report_path,
            pagination_report_path=pagination_report_path,
            club_overviews_report_path=club_overviews_report_path,
            lease_evidence=lease_evidence,
            held_lease_path=Path(held_lease_path),
            held_lease_token=held_lease_token,
            promotion_proxy_url=promotion_proxy_url,
            promotion_timeout_seconds=promotion_timeout_seconds,
        )

    lock_path = service_publish_lease_path(DATA_ROOT, ENV_ID, SERVICE_NAME)
    with publish_promotion_lock(lock_path):
        return _promote_publish_transaction_locked(
            transaction_id=transaction_id,
            deploy_report_path=deploy_report_path,
            smoke_report_path=smoke_report_path,
            pagination_report_path=pagination_report_path,
            club_overviews_report_path=club_overviews_report_path,
            lease_evidence=None,
            held_lease_path=None,
            held_lease_token="",
            promotion_proxy_url=promotion_proxy_url,
            promotion_timeout_seconds=promotion_timeout_seconds,
        )


def _promote_publish_transaction_locked(
    *,
    transaction_id: str,
    deploy_report_path: Path,
    smoke_report_path: Path,
    pagination_report_path: Path,
    club_overviews_report_path: Path,
    lease_evidence: dict | None,
    held_lease_path: Path | None,
    held_lease_token: str,
    promotion_proxy_url: str,
    promotion_timeout_seconds: int,
) -> dict:
    """Promote only after the caller owns the process-wide promotion lock."""
    transaction_id = validate_transaction_id(transaction_id)
    transaction_dir = WORK_ROOT / PUBLISH_TRANSACTIONS_DIR / transaction_id
    report_path = transaction_dir / PUBLISH_TRANSACTION_REPORT
    report = read_required_report(report_path, "publish transaction")
    if report.get("status") not in {"prepared", "promotion_failed_restored"}:
        reason = f"transaction status is not promotable: {report.get('status')}"
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    deploy_report = read_required_report(deploy_report_path, "deploy")
    if not deploy_report.get("ok") or not bool(
        (deploy_report.get("safety") or {}).get("cloud_deploy_executed")
    ):
        reason = "deploy evidence is not successful"
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    smoke_report = read_required_report(smoke_report_path, "smoke")
    if not smoke_report.get("ok") or smoke_report.get("decision") != "cloudrun_weekly_production_smoke_ready":
        reason = "smoke evidence is not successful"
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    pagination_report = read_required_report(pagination_report_path, "pagination")
    if (
        not pagination_report.get("ok")
        or pagination_report.get("decision") != "cloudrun_remote_pagination_verified"
    ):
        reason = "pagination evidence is not successful"
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    club_overviews_report = read_required_report(club_overviews_report_path, "club-overviews")
    deploy_binding = (
        deploy_report.get("evidence_binding")
        if isinstance(deploy_report.get("evidence_binding"), dict)
        else {}
    )
    smoke_binding = (
        smoke_report.get("evidence_binding")
        if isinstance(smoke_report.get("evidence_binding"), dict)
        else {}
    )
    pagination_binding = (
        pagination_report.get("evidence_binding")
        if isinstance(pagination_report.get("evidence_binding"), dict)
        else {}
    )
    club_binding = (
        club_overviews_report.get("evidence_binding")
        if isinstance(club_overviews_report.get("evidence_binding"), dict)
        else {}
    )
    deploy_identity = (
        deploy_report.get("deployment_identity")
        if isinstance(deploy_report.get("deployment_identity"), dict)
        else {}
    )
    post_update_identity = (
        deploy_report.get("post_update_server_identity")
        if isinstance(deploy_report.get("post_update_server_identity"), dict)
        else {}
    )
    deploy_zip = deploy_report.get("zip") if isinstance(deploy_report.get("zip"), dict) else {}
    expected_context_fingerprint = str((report.get("deploy_context") or {}).get("fingerprint") or "")
    expected_generation_id = str(report.get("candidate_generation_id") or "")
    active_version = str(smoke_binding.get("active_version") or "")
    reported_version = str(deploy_identity.get("reported_version") or "")
    observed_active_version = str(deploy_identity.get("observed_active_version") or "")
    zip_path = Path(str(deploy_zip.get("zip_path") or ""))
    zip_sha = str(deploy_binding.get("deploy_zip_sha256") or "")
    binding_checks = {
        "deploy_report_schema": deploy_report.get("schema_version")
        == DIRECT_DEPLOY_REPORT_SCHEMA_VERSION,
        "smoke_report_schema": smoke_report.get("schema_version") == SMOKE_REPORT_SCHEMA_VERSION,
        "pagination_report_schema": pagination_report.get("schema_version")
        == PAGINATION_REPORT_SCHEMA_VERSION,
        "club_report_schema": club_overviews_report.get("schema_version")
        == CLUB_OVERVIEWS_REPORT_SCHEMA_VERSION,
        "transaction_id_matches": deploy_binding.get("transaction_id") == transaction_id,
        "target_env_matches": deploy_binding.get("env_id") == ENV_ID,
        "target_service_matches": deploy_binding.get("service_name") == SERVICE_NAME,
        "context_fingerprint_matches_prepared": bool(expected_context_fingerprint)
        and deploy_binding.get("deploy_context_fingerprint") == expected_context_fingerprint,
        "generation_matches_prepared": bool(expected_generation_id)
        and deploy_binding.get("expected_generation_id") == expected_generation_id,
        "generation_format": bool(
            re.fullmatch(r"sha256:[0-9a-f]{64}", expected_generation_id)
        ),
        "zip_sha_format": bool(re.fullmatch(r"[0-9a-f]{64}", zip_sha)),
        "zip_report_digest_matches_binding": deploy_zip.get("zip_sha256") == zip_sha,
        "zip_artifact_digest_matches_binding": zip_path.is_file()
        and sha256_file(zip_path) == zip_sha,
        "deploy_context_path_matches_transaction": _resolved(
            Path(str(deploy_zip.get("context_dir") or "."))
        )
        == _resolved(transaction_dir / "deploy_context"),
        "deploy_operation_bound": bool(
            deploy_identity.get("task_id") or deploy_identity.get("request_id")
        ),
        "active_version_matches_deploy": bool(active_version)
        and bool(reported_version)
        and bool(observed_active_version)
        and active_version == reported_version
        and observed_active_version == reported_version,
        "base_url_matches_deploy": bool(smoke_binding.get("base_url"))
        and str(smoke_binding.get("base_url") or "").rstrip("/")
        == str(post_update_identity.get("base_url") or "").rstrip("/"),
        "remote_generation_matches_expected": smoke_binding.get("remote_generation_id")
        == expected_generation_id,
        "smoke_binding_extends_exact_deploy_core": all(
            smoke_binding.get(field) == deploy_binding.get(field)
            for field in EVIDENCE_BINDING_CORE_FIELDS
        ),
        "pagination_binding_matches_smoke": pagination_binding == smoke_binding,
        "club_binding_matches_smoke": club_binding == smoke_binding,
        "held_publish_lease_matches_deploy": lease_evidence is None
        or (
            deploy_binding.get("publish_lease_token_sha256")
            == lease_evidence.get("lease_token_sha256")
            and lease_evidence.get("transaction_id") == transaction_id
            and lease_evidence.get("env_id") == ENV_ID
            and lease_evidence.get("service_name") == SERVICE_NAME
        ),
    }
    failed_binding_checks = [name for name, passed in binding_checks.items() if not passed]
    if failed_binding_checks:
        reason = "publish evidence binding failed: " + ", ".join(failed_binding_checks)
        report["publish_evidence_binding_checks"] = binding_checks
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    club_candidate_evidence = club_overviews_report.get("candidate") or {}
    club_remote_evidence = club_overviews_report.get("remote") or {}
    club_evidence_checks = {
        "club_report_schema": binding_checks["club_report_schema"],
        "club_report_ok": club_overviews_report.get("ok") is True,
        "club_report_decision": club_overviews_report.get("decision")
        == CLUB_OVERVIEWS_REPORT_DECISION,
        "club_candidate_schema": club_candidate_evidence.get("schema_version")
        == CLUB_OVERVIEWS_SCHEMA_VERSION,
        "club_remote_schema": club_remote_evidence.get("schema_version")
        == CLUB_OVERVIEWS_SCHEMA_VERSION,
        "club_candidate_digest_format": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(club_candidate_evidence.get("summary_sha256") or ""))
        ),
        "club_remote_digest_format": bool(
            re.fullmatch(r"[0-9a-f]{64}", str(club_remote_evidence.get("summary_sha256") or ""))
        ),
        "club_summary_digest_matches": club_candidate_evidence.get("summary_sha256")
        == club_remote_evidence.get("summary_sha256"),
        "club_digest_algorithm_matches": club_candidate_evidence.get("digest_algorithm")
        == CLUB_OVERVIEWS_DIGEST_ALGORITHM
        and club_remote_evidence.get("digest_algorithm") == CLUB_OVERVIEWS_DIGEST_ALGORITHM,
        "club_count_matches": club_candidate_evidence.get("club_count")
        == club_remote_evidence.get("club_count"),
        "club_overview_count_matches": club_candidate_evidence.get("overview_count")
        == club_remote_evidence.get("overview_count"),
        "club_kind_counts_match": club_candidate_evidence.get("kind_counts")
        == club_remote_evidence.get("kind_counts"),
    }
    failed_club_evidence = [name for name, passed in club_evidence_checks.items() if not passed]
    if failed_club_evidence:
        reason = "club-overviews evidence is not successful: " + ", ".join(failed_club_evidence)
        report["club_overviews_evidence_checks"] = club_evidence_checks
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    staged_data = transaction_dir / "staged_data"
    staged_current = staged_data / "current_release"
    staged_source = staged_data / "source_actions" / "source_url_map.json"
    candidate_snapshot = directory_snapshot(staged_current)
    candidate_ids = package_item_id_snapshot(staged_current)
    staged_club_overviews = candidate_club_overviews_snapshot(staged_current)
    prepared_ids = report.get("candidate_item_ids") or {}
    prepared_club_overviews = report.get("candidate_club_overviews") or {}
    bio_requested = report.get("promote_dj_bio_atoms") is True
    bio_integrity_checks = {}
    bio_evidence = {}
    bio_staged_snapshot = {}
    if bio_requested:
        bio_transaction = report.get("dj_bio_promotion") or {}
        bio_report_path = staged_data / DJ_BIO_PROMOTION_REPORT_ITEM
        bio_evidence = read_json_file(bio_report_path)
        bio_staged_snapshot = atlas_bio_asset_snapshot(staged_data, required=True)
        bio_manifest = read_json_file(staged_current / "manifest.json")
        bio_manifest_binding = (
            (bio_manifest.get("publish_transaction_evidence") or {}).get("dj_bio_promotion")
            or {}
        )
        context_manifest = report.get("deploy_context") or {}
        context_bio_report = deploy_context_file_entry(
            context_manifest, f"data/{DJ_BIO_PROMOTION_REPORT_ITEM}"
        )
        context_bio_index = deploy_context_file_entry(
            context_manifest, f"data/{DJ_BIO_ATLAS_INDEX_NAME}"
        )
        expected_after = bio_evidence.get("after") or {}
        expected_before = bio_evidence.get("before") or {}
        prepared_bio_baseline = report.get("atlas_bio_baseline") or {}
        prepared_bio_staged = bio_transaction.get("staged_assets") or {}
        current_bio_snapshot = atlas_bio_asset_snapshot(DATA_ROOT, required=True)
        selected_count = int(bio_evidence.get("selected_count") or 0)
        matched_count = int(bio_evidence.get("matched_count") or 0)
        db_update_count = int(bio_evidence.get("db_update_count") or 0)
        index_update_count = int(bio_evidence.get("index_update_count") or 0)
        bio_integrity_checks = {
            "bio_evidence_schema": bio_evidence.get("schema_version")
            == DJ_BIO_PROMOTION_SCHEMA_VERSION,
            "bio_evidence_transaction": bio_evidence.get("transaction_id") == transaction_id,
            "bio_evidence_report_digest_unchanged": bio_report_path.is_file()
            and sha256_file(bio_report_path) == bio_transaction.get("report_sha256"),
            "bio_evidence_bound_to_candidate_manifest": bio_manifest_binding
            == bio_transaction.get("manifest_binding"),
            "bio_evidence_bound_to_deploy_context": context_bio_report.get("sha256")
            == bio_transaction.get("report_sha256"),
            "bio_index_bound_to_deploy_context": context_bio_index.get("sha256")
            == ((expected_after.get(DJ_BIO_ATLAS_INDEX_NAME) or {}).get("sha256")),
            "bio_authoritative_baseline_unchanged": current_bio_snapshot.get("fingerprint")
            == prepared_bio_baseline.get("fingerprint"),
            "bio_staged_assets_unchanged": bio_staged_snapshot.get("fingerprint")
            == prepared_bio_staged.get("fingerprint"),
            "bio_index_before_matches_authoritative": (
                (expected_before.get(DJ_BIO_ATLAS_INDEX_NAME) or {}).get("sha256")
                == ((prepared_bio_baseline.get("assets") or {}).get(DJ_BIO_ATLAS_INDEX_NAME) or {}).get("sha256")
            ),
            "bio_db_before_matches_authoritative": (
                (expected_before.get(DJ_BIO_ATLAS_DB_NAME) or {}).get("sha256")
                == ((prepared_bio_baseline.get("assets") or {}).get(DJ_BIO_ATLAS_DB_NAME) or {}).get("sha256")
            ),
            "bio_index_after_matches_staged": (
                (expected_after.get(DJ_BIO_ATLAS_INDEX_NAME) or {}).get("sha256")
                == ((bio_staged_snapshot.get("assets") or {}).get(DJ_BIO_ATLAS_INDEX_NAME) or {}).get("sha256")
            ),
            "bio_db_after_matches_staged": (
                (expected_after.get(DJ_BIO_ATLAS_DB_NAME) or {}).get("sha256")
                == ((bio_staged_snapshot.get("assets") or {}).get(DJ_BIO_ATLAS_DB_NAME) or {}).get("sha256")
            ),
            "bio_match_counts_valid": (
                0 <= db_update_count <= matched_count <= selected_count
                and 0 <= index_update_count <= matched_count
            ),
            "bio_selected_candidates_have_database_match": selected_count == 0
            or matched_count > 0,
            "bio_matched_candidates_committed": matched_count == 0
            or (
                bio_evidence.get("committed") is True
                and bio_evidence.get("write_applied") is True
            ),
        }
    evidence_checks = {
        "baseline_unchanged": authoritative_runtime_snapshot().get("fingerprint")
        == (report.get("baseline") or {}).get("fingerprint"),
        "candidate_unchanged": candidate_snapshot.get("fingerprint")
        == (report.get("candidate") or {}).get("fingerprint"),
        "candidate_ids_complete": (
            candidate_ids.get("item_count") == candidate_ids.get("item_id_count")
            and candidate_ids.get("duplicate_item_id_count") == 0
        ),
        "candidate_id_digest_unchanged": candidate_ids.get("item_id_digest")
        == prepared_ids.get("item_id_digest"),
        "pagination_id_count_matches_candidate": int(
            pagination_report.get("remote_item_id_count") or -1
        )
        == int(candidate_ids.get("unique_item_id_count") or 0),
        "pagination_id_digest_matches_candidate": pagination_report.get(
            "remote_item_id_digest"
        )
        == candidate_ids.get("item_id_digest"),
        "pagination_scope_is_package": pagination_report.get("scope") == "package",
        "pagination_digest_algorithm_matches": pagination_report.get("digest_algorithm")
        == candidate_ids.get("digest_algorithm"),
        "club_candidate_digest_matches_prepared": club_candidate_evidence.get("summary_sha256")
        == prepared_club_overviews.get("summary_sha256"),
        "club_candidate_digest_matches_staged": club_candidate_evidence.get("summary_sha256")
        == staged_club_overviews.get("summary_sha256"),
        "club_candidate_file_digest_matches_staged": club_candidate_evidence.get("file_sha256")
        == staged_club_overviews.get("file_sha256"),
        "club_candidate_count_matches_prepared": club_candidate_evidence.get("club_count")
        == prepared_club_overviews.get("club_count")
        and club_candidate_evidence.get("overview_count")
        == prepared_club_overviews.get("overview_count"),
        "staged_source_url_map_unchanged": staged_source.is_file()
        and sha256_file(staged_source) == (report.get("source_url_map") or {}).get("sha256"),
        **bio_integrity_checks,
    }
    failed_checks = [name for name, passed in evidence_checks.items() if not passed]
    if failed_checks:
        reason = "promotion integrity evidence failed: " + ", ".join(failed_checks)
        report["promotion_evidence_checks"] = evidence_checks
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    try:
        remote_revalidation = revalidate_remote_promotion_target(
            transaction_id=transaction_id,
            evidence_binding=smoke_binding,
            candidate_generation_id=expected_generation_id,
            candidate_item_id_digest=str(candidate_ids.get("item_id_digest") or ""),
            candidate_item_count=int(candidate_ids.get("unique_item_id_count") or 0),
            proxy_url=promotion_proxy_url,
            timeout_seconds=promotion_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        remote_revalidation = {
            "schema_version": "cloudrun_remote_promotion_revalidation.v1",
            "generated_at": now_iso(),
            "ok": False,
            "decision": "cloudrun_remote_promotion_revalidation_failed",
            "checks": {},
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
        }
    report["remote_promotion_revalidation"] = remote_revalidation
    if not remote_revalidation.get("ok"):
        failed_remote_checks = [
            name
            for name, passed in (remote_revalidation.get("checks") or {}).items()
            if not passed
        ]
        reason = "remote promotion revalidation failed"
        if failed_remote_checks:
            reason += ": " + ", ".join(failed_remote_checks)
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    if lease_evidence is not None:
        lease_before_promotion = validate_held_service_publish_lease(
            lease_path=Path(held_lease_path),
            lease_token=held_lease_token,
            transaction_id=transaction_id,
            env_id=ENV_ID,
            service_name=SERVICE_NAME,
            data_root=DATA_ROOT,
        )
        if (
            lease_before_promotion.get("lease_token_sha256")
            != lease_evidence.get("lease_token_sha256")
        ):
            reason = "service publish lease changed before local promotion"
            block_publish_promotion(report_path, report, reason)
            raise ValueError(reason)
        report["service_publish_lease_revalidated_before_promotion"] = {
            **lease_before_promotion,
            "validated_at": now_iso(),
        }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = DATA_ROOT / "publish_backups" / f"{timestamp}-{transaction_id}"
    rollback_current = DATA_ROOT / f".current_release.rollback-{transaction_id}"
    rollback_source = DATA_SOURCE_ACTIONS / f".source_url_map.rollback-{transaction_id}.json"
    bio_changed = bio_requested and bio_evidence.get("changed") is True
    staged_bio_index = staged_data / DJ_BIO_ATLAS_INDEX_NAME
    staged_bio_db = staged_data / DJ_BIO_ATLAS_DB_NAME
    authoritative_bio_index = DATA_ROOT / DJ_BIO_ATLAS_INDEX_NAME
    authoritative_bio_db = DATA_ROOT / DJ_BIO_ATLAS_DB_NAME
    rollback_bio_index = DATA_ROOT / f".{DJ_BIO_ATLAS_INDEX_NAME}.rollback-{transaction_id}"
    rollback_bio_db = DATA_ROOT / f".{DJ_BIO_ATLAS_DB_NAME}.rollback-{transaction_id}"
    if (
        backup_dir.exists()
        or rollback_current.exists()
        or rollback_source.exists()
        or (bio_changed and (rollback_bio_index.exists() or rollback_bio_db.exists()))
    ):
        reason = "promotion backup/rollback target already exists"
        block_publish_promotion(report_path, report, reason)
        raise ValueError(reason)

    report.update(
        {
            "status": "promoting",
            "updated_at": now_iso(),
            "promotion_evidence_checks": evidence_checks,
            "publish_evidence_binding_checks": binding_checks,
            "evidence": {
                "deploy_report": str(Path(deploy_report_path).resolve()),
                "smoke_report": str(Path(smoke_report_path).resolve()),
                "pagination_report": str(Path(pagination_report_path).resolve()),
                "club_overviews_report": str(Path(club_overviews_report_path).resolve()),
                "remote_item_id_digest": pagination_report.get("remote_item_id_digest"),
                "remote_club_overviews_digest": club_remote_evidence.get("summary_sha256"),
                "evidence_binding": smoke_binding,
                "service_publish_lease": lease_evidence,
                "remote_promotion_revalidation": remote_revalidation,
                "dj_bio_promotion": (
                    {
                        "report_sha256": (report.get("dj_bio_promotion") or {}).get("report_sha256"),
                        "matched_count": bio_evidence.get("matched_count"),
                        "db_update_count": bio_evidence.get("db_update_count"),
                        "index_update_count": bio_evidence.get("index_update_count"),
                        "changed": bio_evidence.get("changed") is True,
                        "after": bio_evidence.get("after"),
                    }
                    if bio_requested
                    else None
                ),
            },
        }
    )
    write_json_atomic(report_path, report)

    try:
        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        backup_dir.mkdir(parents=False, exist_ok=False)
        shutil.copytree(DATA_CURRENT_RELEASE, backup_dir / "current_release")
        (backup_dir / "source_actions").mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            DATA_SOURCE_ACTIONS / "source_url_map.json",
            backup_dir / "source_actions" / "source_url_map.json",
        )
        if bio_changed:
            (backup_dir / "atlas").mkdir(parents=True, exist_ok=False)
            shutil.copy2(authoritative_bio_index, backup_dir / "atlas" / DJ_BIO_ATLAS_INDEX_NAME)
            shutil.copy2(authoritative_bio_db, backup_dir / "atlas" / DJ_BIO_ATLAS_DB_NAME)
        backup_snapshot = directory_snapshot(backup_dir / "current_release")
        backup_source_sha = sha256_file(backup_dir / "source_actions" / "source_url_map.json")
        if backup_snapshot.get("fingerprint") != (
            report.get("baseline") or {}
        ).get("current_release", {}).get("fingerprint"):
            raise RuntimeError("versioned current_release backup digest mismatch")
        if backup_source_sha != (
            report.get("baseline") or {}
        ).get("source_url_map", {}).get("sha256"):
            raise RuntimeError("versioned source_url_map backup digest mismatch")
        if bio_changed:
            backup_bio_snapshot = atlas_bio_asset_snapshot(backup_dir / "atlas", required=True)
            if backup_bio_snapshot.get("fingerprint") != (
                report.get("atlas_bio_baseline") or {}
            ).get("fingerprint"):
                raise RuntimeError("versioned Atlas bio asset backup digest mismatch")
        write_json_atomic(
            backup_dir / "backup_manifest.json",
            {
                "schema_version": "weekly_cloudrun_publish_backup.v1",
                "transaction_id": transaction_id,
                "created_at": now_iso(),
                "baseline": report.get("baseline"),
                "atlas_bio_baseline": report.get("atlas_bio_baseline") if bio_requested else None,
            },
        )
    except Exception as exc:
        report.update(
            {
                "status": "promotion_backup_failed_baseline_unchanged",
                "updated_at": now_iso(),
                "promotion_error": f"{type(exc).__name__}: {exc}",
                "promotion": {"backup_dir": str(backup_dir)},
            }
        )
        write_json_atomic(report_path, report)
        raise RuntimeError(f"versioned backup failed before promotion: {exc}") from exc

    current_swapped = False
    source_swapped = False
    bio_db_swapped = False
    bio_index_swapped = False
    try:
        os.replace(DATA_CURRENT_RELEASE, rollback_current)
        os.replace(staged_current, DATA_CURRENT_RELEASE)
        current_swapped = True
        os.replace(DATA_SOURCE_ACTIONS / "source_url_map.json", rollback_source)
        os.replace(staged_source, DATA_SOURCE_ACTIONS / "source_url_map.json")
        source_swapped = True
        if bio_changed:
            os.replace(authoritative_bio_db, rollback_bio_db)
            os.replace(staged_bio_db, authoritative_bio_db)
            bio_db_swapped = True
            os.replace(authoritative_bio_index, rollback_bio_index)
            os.replace(staged_bio_index, authoritative_bio_index)
            bio_index_swapped = True

        promoted_ids = package_item_id_snapshot(DATA_CURRENT_RELEASE)
        promoted_source_sha = sha256_file(DATA_SOURCE_ACTIONS / "source_url_map.json")
        if promoted_ids.get("item_id_digest") != candidate_ids.get("item_id_digest"):
            raise RuntimeError("promoted current_release item ID digest mismatch")
        if promoted_source_sha != (report.get("source_url_map") or {}).get("sha256"):
            raise RuntimeError("promoted source_url_map digest mismatch")
        if bio_changed:
            promoted_bio = atlas_bio_asset_snapshot(DATA_ROOT, required=True)
            if promoted_bio.get("fingerprint") != bio_staged_snapshot.get("fingerprint"):
                raise RuntimeError("promoted Atlas bio asset digest mismatch")
    except Exception as exc:
        restore_errors = []
        if bio_changed:
            try:
                if bio_index_swapped and authoritative_bio_index.exists():
                    staged_bio_index.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(authoritative_bio_index, staged_bio_index)
                if rollback_bio_index.exists():
                    os.replace(rollback_bio_index, authoritative_bio_index)
            except Exception as restore_exc:  # noqa: BLE001
                restore_errors.append(f"atlas_index: {restore_exc}")
            try:
                if bio_db_swapped and authoritative_bio_db.exists():
                    staged_bio_db.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(authoritative_bio_db, staged_bio_db)
                if rollback_bio_db.exists():
                    os.replace(rollback_bio_db, authoritative_bio_db)
            except Exception as restore_exc:  # noqa: BLE001
                restore_errors.append(f"atlas_miniapp_db: {restore_exc}")
        try:
            if source_swapped and (DATA_SOURCE_ACTIONS / "source_url_map.json").exists():
                staged_source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(DATA_SOURCE_ACTIONS / "source_url_map.json", staged_source)
            if rollback_source.exists():
                os.replace(rollback_source, DATA_SOURCE_ACTIONS / "source_url_map.json")
        except Exception as restore_exc:  # noqa: BLE001
            restore_errors.append(f"source_url_map: {restore_exc}")
        try:
            if current_swapped and DATA_CURRENT_RELEASE.exists():
                os.replace(DATA_CURRENT_RELEASE, staged_current)
            if rollback_current.exists():
                os.replace(rollback_current, DATA_CURRENT_RELEASE)
        except Exception as restore_exc:  # noqa: BLE001
            restore_errors.append(f"current_release: {restore_exc}")

        bio_baseline_restored = True
        if bio_requested:
            try:
                bio_baseline_restored = (
                    atlas_bio_asset_snapshot(DATA_ROOT, required=True).get("fingerprint")
                    == (report.get("atlas_bio_baseline") or {}).get("fingerprint")
                )
            except Exception as restore_exc:  # noqa: BLE001
                bio_baseline_restored = False
                restore_errors.append(f"atlas_baseline_verification: {restore_exc}")
        restored = (
            not restore_errors
            and authoritative_runtime_snapshot().get("fingerprint")
            == (report.get("baseline") or {}).get("fingerprint")
            and bio_baseline_restored
        )
        report.update(
            {
                "status": "promotion_failed_restored" if restored else "promotion_failed_restore_error",
                "updated_at": now_iso(),
                "promotion_error": f"{type(exc).__name__}: {exc}",
                "restore_errors": restore_errors,
                "baseline_restored": restored,
                "promotion": {"backup_dir": str(backup_dir)},
            }
        )
        write_json_atomic(report_path, report)
        raise RuntimeError(
            f"publish promotion failed; baseline_restored={restored}: {exc}"
        ) from exc

    cleanup_warnings = []
    try:
        if rollback_current.exists():
            shutil.rmtree(rollback_current)
    except OSError as exc:
        cleanup_warnings.append(f"rollback_current_cleanup: {exc}")
    try:
        if rollback_source.exists():
            rollback_source.unlink()
    except OSError as exc:
        cleanup_warnings.append(f"rollback_source_cleanup: {exc}")
    if bio_changed:
        for label, path in (
            ("rollback_bio_index_cleanup", rollback_bio_index),
            ("rollback_bio_db_cleanup", rollback_bio_db),
        ):
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                cleanup_warnings.append(f"{label}: {exc}")

    promoted_bio_snapshot = (
        atlas_bio_asset_snapshot(DATA_ROOT, required=True) if bio_requested else None
    )

    report.update(
        {
            "status": "promoted",
            "updated_at": now_iso(),
            "promoted_at": now_iso(),
            "promotion": {
                "backup_dir": str(backup_dir),
                "candidate_item_id_digest": candidate_ids.get("item_id_digest"),
                "dj_bio_promotion": (
                    {
                        "requested": True,
                        "authoritative_changed": bio_changed,
                        "selected_count": bio_evidence.get("selected_count"),
                        "matched_count": bio_evidence.get("matched_count"),
                        "db_update_count": bio_evidence.get("db_update_count"),
                        "index_update_count": bio_evidence.get("index_update_count"),
                        "report_sha256": (report.get("dj_bio_promotion") or {}).get("report_sha256"),
                        "authoritative_after": promoted_bio_snapshot,
                    }
                    if bio_requested
                    else None
                ),
                "cleanup_warnings": cleanup_warnings,
            },
        }
    )
    write_json_atomic(report_path, report)
    return report


def apply_tcb_patch(dry_run: bool) -> bool:
    """Return True if patch is confirmed applied after this call."""
    patch_script = _SCRIPT_DIR / "patch_tcb_cli.py"
    if not patch_script.exists():
        print("WARNING: patch_tcb_cli.py not found — skipping tcb patch check.")
        return True  # optimistic, let deploy fail loudly if broken

    print("\n--- tcb CLI patch ---")
    if dry_run:
        print("[DRY-RUN] python scripts/patch_tcb_cli.py")
        return True

    result = subprocess.run([sys.executable, str(patch_script)], capture_output=False)
    return result.returncode in (0,)  # 0 = ok (also ok if already applied)


def normalize_current_release_manifest(release_dir: Path, dry_run: bool) -> bool:
    """Keep the baked current_release manifest self-describing after copy."""
    manifest_path = DATA_CURRENT_RELEASE / "manifest.json"
    if dry_run:
        print(f"  [DRY-RUN] normalize manifest out_dir for deployed copy: {manifest_path}")
        return True
    if not manifest_path.exists():
        print(f"  ERROR: manifest.json missing after copy: {manifest_path}")
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"  ERROR: cannot read manifest.json after copy: {error}")
        return False
    if not isinstance(manifest, dict):
        print("  ERROR: manifest.json root must be an object")
        return False
    manifest["source_release_name"] = release_dir.name
    manifest["deployed_release_name"] = DATA_CURRENT_RELEASE.name
    manifest = scrub_public_package_payload(manifest)
    assert_public_payload(manifest, label="baked weekly manifest.json")
    try:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        print(f"  ERROR: cannot write normalized manifest.json: {error}")
        return False
    print("  normalized manifest out_dir for current_release")
    return True


def regenerate_neighborhood_bundle(dry_run: bool) -> bool:
    """Rebuild atlas_neighborhood.json.gz from the live atlas_miniapp.sqlite.

    Keeps the star-map neighborhood in lock-step with the deployed serving DB
    (including identity merges), instead of a periodic atlas_serving_v2 snapshot
    that drifts stale. The bundle is keyed by the same hash subject ids as
    atlas_index, so the API resolves nodes natively. Skipped quietly if the
    miniapp DB is absent (older release layouts that ship no atlas).
    """
    repo_root = MINIPROGRAM_DIR.parent.parent
    builder = repo_root / "tools" / "atlas_rebuild" / "build_neighbor_bundle_from_miniapp.py"
    miniapp_db = DATA_ROOT / "atlas_miniapp.sqlite"
    index_gz = DATA_ROOT / "atlas_index.json.gz"
    out_gz = DATA_ROOT / "atlas_neighborhood.json.gz"

    def read_dataset_id(artifact: Path) -> str:
        with gzip.open(artifact, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        return str(payload.get("datasetId") or "").strip()

    try:
        dataset_id = read_dataset_id(index_gz)
    except (OSError, json.JSONDecodeError) as error:
        print(f"  ERROR: cannot read ATLAS dataset identity from {index_gz.name}: {error}")
        return False
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", dataset_id):
        print(f"  ERROR: {index_gz.name} has no valid public datasetId; refusing a mixed-generation rebuild")
        return False
    if not miniapp_db.exists():
        if not out_gz.exists():
            print("  SKIP neighborhood rebuild: no atlas_miniapp.sqlite and no neighborhood artifact")
            return True
        try:
            existing_dataset_id = read_dataset_id(out_gz)
        except (OSError, json.JSONDecodeError) as error:
            print(f"  ERROR: cannot verify {out_gz.name} without atlas_miniapp.sqlite: {error}")
            return False
        if existing_dataset_id != dataset_id:
            print("  ERROR: existing index/neighborhood datasetId mismatch and no miniapp DB is available to rebuild")
            return False
        print("  SKIP neighborhood rebuild: existing index/neighborhood datasetId handshake is valid")
        return True
    if not builder.exists():
        print(f"  ERROR: neighborhood builder missing: {builder}")
        return False
    cmd = [
        sys.executable,
        str(builder),
        "--miniapp-db",
        str(miniapp_db),
        "--out",
        str(out_gz),
        "--dataset-id",
        dataset_id,
    ]
    if dry_run:
        print(f"  [DRY-RUN] regenerate neighborhood bundle: {' '.join(cmd)}")
        return True
    print("  regenerating star-map neighborhood bundle from atlas_miniapp.sqlite")
    result = subprocess.run(cmd, cwd=str(builder.parent))
    if result.returncode != 0:
        print(f"  ERROR: neighborhood bundle rebuild exited {result.returncode}")
        return False
    try:
        rebuilt_dataset_id = read_dataset_id(out_gz)
    except (OSError, json.JSONDecodeError) as error:
        print(f"  ERROR: cannot verify rebuilt {out_gz.name}: {error}")
        return False
    if rebuilt_dataset_id != dataset_id:
        print("  ERROR: rebuilt index/neighborhood datasetId handshake failed")
        return False
    print("  OK neighborhood bundle aligned with atlas_miniapp.sqlite")
    return True


def bake_data(
    release_dir: Path,
    source_url_map: Path | None,
    dry_run: bool,
    *,
    update_column_json: bool = False,
) -> bool:
    print(f"\n--- bake data: {release_dir.name} ---")
    ok = True

    try:
        validate_derived_route_closure(release_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"  ERROR: refusing to bake incoherent derived routes: {error}")
        return False

    # 1. Copy release items into current_release
    for item in RELEASE_ITEMS:
        if item == "column.json" and not update_column_json:
            existing = DATA_CURRENT_RELEASE / item
            if existing.exists():
                print(f"  preserve existing column.json (use --update-column-json to replace)")
            else:
                print(f"  skip column.json update by default; existing column.json not found")
            continue
        src = release_dir / item
        dst = DATA_CURRENT_RELEASE / item
        copy_item(src, dst, dry_run)
        if not dry_run and not dst.exists():
            print(f"  ERROR: {item} not found after copy")
            ok = False

    for item in OPTIONAL_RELEASE_ITEMS:
        src = release_dir / item
        if src.exists():
            copy_item(src, DATA_CURRENT_RELEASE / item, dry_run)
        else:
            stale = DATA_CURRENT_RELEASE / item
            if dry_run:
                print(f"  [DRY-RUN] remove stale optional item if present: {stale}")
            elif stale.exists():
                if stale.is_dir():
                    shutil.rmtree(stale)
                else:
                    stale.unlink()
                print(f"  removed stale optional item: {stale.name}")

    if not normalize_current_release_manifest(release_dir, dry_run):
        ok = False

    # 2. Copy source_url_map
    if source_url_map:
        src_map = Path(source_url_map)
    else:
        # Fall back to source_actions/ inside the release dir
        src_map = release_dir / "source_actions" / "source_url_map.json"
        if not src_map.exists():
            # Try sibling source_actions dir (stage7 convention)
            src_map = release_dir.parent / "source_actions" / "source_url_map.json"

    copy_item(src_map, DATA_SOURCE_ACTIONS / "source_url_map.json", dry_run)
    # Keep a compatibility copy next to current_release for local release guards
    # and older tooling that probes release_dir/source_actions first.
    copy_item(src_map, DATA_CURRENT_RELEASE / "source_actions" / "source_url_map.json", dry_run)
    if not dry_run and not (DATA_SOURCE_ACTIONS / "source_url_map.json").exists():
        print("  ERROR: source_url_map.json not found after copy — source links will 404")
        ok = False

    if not ensure_source_grounded_llm_materialized(dry_run):
        ok = False

    # Backend activity releases never mutate mini-program source. Successful
    # online weekly responses are persisted by api.js; offlineSnapshot.js is a
    # separately maintained first-install disaster seed, not a release artifact.
    print("  mini-program disaster seed unchanged (online API + persisted last-good cache carry activity updates)")

    if not regenerate_neighborhood_bundle(dry_run):
        ok = False

    return ok


def validate_stage7_atlas(required: bool, stage7_atlas_dir: Path | None = None) -> bool:
    print("\n--- Stage7 atlas package ---")
    selected_stage7 = stage7_atlas_dir or DATA_STAGE7_ATLAS
    missing = []
    for item in REQUIRED_STAGE7_STATIC_ITEMS:
        path = selected_stage7 / item
        if path.exists():
            print(f"  OK {item} bytes={path.stat().st_size}")
        else:
            print(f"  MISSING {item}")
            missing.append(item)
    pointer_path = selected_stage7 / "release_pointer.staging.json"
    if pointer_path.exists():
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pointer = {}
            missing.append("release_pointer_json_parse")
        files = pointer.get("files") if isinstance(pointer.get("files"), dict) else {}
        for key in ["articles", "entities", "events"]:
            item = files.get(key) if isinstance(files.get(key), dict) else {}
            rel_path = item.get("path") or ""
            path = selected_stage7 / str(rel_path)
            if rel_path and path.exists():
                print(f"  OK {key} payload {rel_path} bytes={path.stat().st_size}")
            else:
                print(f"  MISSING {key} payload {rel_path}")
                missing.append(f"{key}_payload")
    if missing and required:
        print("ERROR: Stage7 atlas package is required but incomplete.")
        print("Run: python scripts/bake_stage7_atlas.py")
        return False
    if missing:
        print("WARNING: Stage7 atlas package incomplete; weekly endpoints can deploy, Stage7 endpoints may fail in CloudRun.")
    return True


def deploy_source_upload(dry_run: bool, deploy_context: Path) -> bool:
    print(f"\n--- deploy CloudRun source-upload: {SERVICE_NAME} -> {ENV_ID} ---")
    cmd = TCB_CMD.split() + [
        "run",
        "deploy",
        "--envId",
        ENV_ID,
        "--serviceName",
        SERVICE_NAME,
        "--path",
        str(deploy_context),
        "--containerPort",
        "8787",
        "--cpu",
        "1",
        "--mem",
        "2",
        "--minNum",
        "1",
        "--maxNum",
        "2",
        "--dockerfile",
        "Dockerfile",
        "--remark",
        f"stage7-full-pipeline source {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "--noConfirm",
    ]
    rc = run(cmd, cwd=_PROJECT_DIR, dry_run=dry_run)
    if rc == 0:
        return True
    if dry_run:
        print(f"ERROR: deploy exited {rc}")
        return False
    print(f"WARNING: modern deploy exited {rc}; trying deprecated CloudRun rolling-update fallback.")
    active_version = detect_active_version()
    if active_version:
        print(f"Deprecated fallback active version: {active_version}")
        legacy_cmd = TCB_CMD.split() + [
            "run:deprecated",
            "version",
            "update",
            "--envId",
            ENV_ID,
            "--serviceName",
            SERVICE_NAME,
            "--versionName",
            active_version,
            "--path",
            str(deploy_context),
            "--port",
            "8787",
            "--flow",
            "100",
            "--cpu",
            "1",
            "--mem",
            "2",
            "--copy",
            "0~2",
            "--dockerFile",
            "Dockerfile",
            "--remark",
            f"stage7-full-pipeline {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        legacy_rc = run(legacy_cmd, cwd=_PROJECT_DIR, dry_run=False)
        if legacy_rc == 0:
            return True
        print(f"WARNING: deprecated version update exited {legacy_rc}; trying version create as last fallback.")
    legacy_cmd = TCB_CMD.split() + [
        "run:deprecated",
        "version",
        "create",
        "--envId",
        ENV_ID,
        "--serviceName",
        SERVICE_NAME,
        "--path",
        str(deploy_context),
        "--port",
        "8787",
        "--flow",
        "100",
        "--cpu",
        "1",
        "--mem",
        "2",
        "--copy",
        "0~2",
        "--dockerFile",
        "Dockerfile",
        "--remark",
        f"stage7-full-pipeline {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    legacy_rc = run(legacy_cmd, cwd=_PROJECT_DIR, dry_run=False)
    if legacy_rc != 0:
        print(f"ERROR: deprecated version create exited {legacy_rc}")
        return False
    return True


def docker_image_id(image_tag: str) -> str:
    image_id = run_capture_checked(["docker", "image", "inspect", image_tag, "--format", "{{.Id}}"], cwd=_PROJECT_DIR)
    if not image_id:
        raise RuntimeError(f"docker image inspect returned empty image id for {image_tag}")
    return image_id


def deploy_image_upload(dry_run: bool, deploy_context: Path) -> bool:
    print(f"\n--- deploy CloudRun image-upload: {SERVICE_NAME} -> {ENV_ID} ---")
    image_tag = f"{SERVICE_NAME}-stage7-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    build_cmd = ["docker", "build", "-t", image_tag, "."]
    if run(build_cmd, cwd=deploy_context, dry_run=dry_run) != 0:
        print("ERROR: docker build failed")
        return False
    if dry_run:
        image_id = f"dry-run-{image_tag}"
    else:
        try:
            image_id = docker_image_id(image_tag)
        except RuntimeError as exc:
            print(f"ERROR: {exc}")
            return False
    upload_cmd = TCB_CMD.split() + [
        "run:deprecated",
        "image",
        "upload",
        "--envId",
        ENV_ID,
        "--serviceName",
        SERVICE_NAME,
        "--imageId",
        image_id,
        "--imageTag",
        image_tag,
        "--json",
    ]
    if run(upload_cmd, cwd=_PROJECT_DIR, dry_run=dry_run) != 0:
        print("ERROR: deprecated image upload failed")
        return False
    active_version = detect_active_version()
    if not active_version:
        print("ERROR: no active CloudRun version found for image deployment")
        return False
    print(f"Deprecated image fallback active version: {active_version}")
    update_cmd = TCB_CMD.split() + [
        "run:deprecated",
        "version",
        "update",
        "--envId",
        ENV_ID,
        "--serviceName",
        SERVICE_NAME,
        "--versionName",
        active_version,
        "--image",
        image_tag,
        "--port",
        "8787",
        "--flow",
        "100",
        "--cpu",
        "1",
        "--mem",
        "2",
        "--copy",
        "0~2",
        "--remark",
        f"stage7-full-pipeline image {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if run(update_cmd, cwd=_PROJECT_DIR, dry_run=dry_run) == 0:
        return True
    print("WARNING: deprecated image update failed; trying image create as last fallback.")
    create_cmd = TCB_CMD.split() + [
        "run:deprecated",
        "version",
        "create",
        "--envId",
        ENV_ID,
        "--serviceName",
        SERVICE_NAME,
        "--image",
        image_tag,
        "--port",
        "8787",
        "--flow",
        "100",
        "--cpu",
        "1",
        "--mem",
        "2",
        "--copy",
        "0~2",
        "--remark",
        f"stage7-full-pipeline image {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    rc = run(create_cmd, cwd=_PROJECT_DIR, dry_run=dry_run)
    if rc != 0:
        print(f"ERROR: deprecated image version create exited {rc}")
        return False
    return True


def deploy(dry_run: bool, deploy_mode: str, deploy_context: Path) -> bool:
    if deploy_mode == "source-upload":
        return deploy_source_upload(dry_run, deploy_context)
    if deploy_mode == "image-upload":
        return deploy_image_upload(dry_run, deploy_context)
    print(f"\n--- deploy CloudRun auto: source-upload then image-upload fallback ---")
    if deploy_source_upload(dry_run, deploy_context):
        return True
    return deploy_image_upload(dry_run, deploy_context)


def wait_for_route(dry_run: bool) -> None:
    if dry_run:
        print(f"[DRY-RUN] sleep {ROUTE_PROPAGATION_DELAY}s (route propagation)")
        return
    print(f"\nWaiting {ROUTE_PROPAGATION_DELAY}s for CloudRun route propagation...", end="", flush=True)
    for _ in range(ROUTE_PROPAGATION_DELAY):
        time.sleep(1)
        print(".", end="", flush=True)
    print(" done")


def generate_qr(desc: str, dry_run: bool) -> Path | None:
    if not DEVTOOLS_CLI.exists():
        print("WARNING: WeChat DevTools CLI not found — skipping QR generation")
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    qr_path = MINIPROGRAM_DIR / f"preview-qr-{ts}.png"
    print(f"\n--- generate preview QR: {qr_path.name} ---")
    cmd = [
        str(DEVTOOLS_CLI),
        "preview",
        "--project", str(MINIPROGRAM_DIR),
        "--qr-format", "image",
        "--qr-output", str(qr_path),
        "--desc", desc,
    ]
    rc = run(cmd, dry_run=dry_run)
    if rc == 0 and not dry_run:
        print(f"QR saved: {qr_path}")
        return qr_path
    return None


def main() -> int:
    global ENV_ID, SERVICE_NAME  # noqa: PLW0603
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release-dir", default="", help="Path to the built release directory")
    parser.add_argument("--source-url-map", default=None, help="Path to source_url_map.json (optional, auto-detected from release)")
    parser.add_argument(
        "--data-root",
        default="",
        help="Mutable CloudRun data root (or HUAIDJ_CLOUDRUN_DATA_ROOT).",
    )
    parser.add_argument(
        "--current-release-dir",
        default="",
        help="Authoritative current_release directory (or HUAIDJ_CURRENT_RELEASE_DIR).",
    )
    parser.add_argument(
        "--work-root",
        default="",
        help="Mutable deploy work root (or HUAIDJ_CLOUDRUN_WORK_ROOT).",
    )
    parser.add_argument("--env-id", default=ENV_ID, help=f"CloudBase env ID (default: {ENV_ID})")
    parser.add_argument(
        "--service-name",
        default=SERVICE_NAME,
        help=f"CloudBase Run service name (default: {SERVICE_NAME})",
    )
    parser.add_argument("--no-qr", action="store_true", help="Skip QR generation")
    parser.add_argument("--dry-run", action="store_true", help="Print steps without making changes")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Stage a fresh publish transaction and deploy context without changing current_release or deploying.",
    )
    parser.add_argument("--transaction-id", default="", help="Unique publish transaction/run ID; an existing ID is never reused.")
    parser.add_argument(
        "--promote-transaction",
        action="store_true",
        help="Promote only after verified deploy, smoke, full-pagination, and club-overviews reports.",
    )
    parser.add_argument("--deploy-report", default="", help="Verified direct deploy report for --promote-transaction.")
    parser.add_argument("--smoke-report", default="", help="Successful production smoke report for --promote-transaction.")
    parser.add_argument("--pagination-report", default="", help="Successful full item-ID pagination report for --promote-transaction.")
    parser.add_argument(
        "--club-overviews-report",
        default="",
        help="Successful exact club-overviews reconciliation report for --promote-transaction.",
    )
    parser.add_argument(
        "--publish-lease-path",
        default="",
        help="Service-scoped lease file already held by the parent release wrapper.",
    )
    parser.add_argument(
        "--publish-lease-token",
        default="",
        help="Coordination nonce for the already-held service publish lease.",
    )
    parser.add_argument(
        "--promotion-proxy-url",
        default="",
        help="Optional proxy used only for the final read-only /readyz revalidation.",
    )
    parser.add_argument(
        "--promotion-timeout-seconds",
        type=int,
        default=30,
        help="Bounded timeout for final active-version and /readyz revalidation.",
    )
    parser.add_argument("--skip-patch-check", action="store_true", help="Skip tcb CLI patch verification")
    parser.add_argument("--require-stage7-atlas", action="store_true", help="Abort if data/stage7_atlas is incomplete")
    parser.add_argument("--include-stage7-atlas", action="store_true", help="Include data/stage7_atlas in the deploy context")
    parser.add_argument(
        "--update-column-json",
        action="store_true",
        help="Also replace current_release/column.json. Off by default so activity releases do not overwrite column articles.",
    )
    parser.add_argument(
        "--promote-dj-bio-atoms",
        action="store_true",
        help=(
            "Copy the runtime Atlas DB/index into this publish transaction, apply bio atoms only "
            "to those staged copies, bind the evidence to the deploy context, and locally promote "
            "them only after the same remote proof gates succeed."
        ),
    )
    parser.add_argument(
        "--deploy-mode",
        choices=("source-upload", "image-upload", "auto"),
        default=DEFAULT_DEPLOY_MODE,
        help=(
            "CloudRun deploy transport. source-upload preserves the original tcb source upload path; "
            "image-upload builds a local Docker image, uploads it with tcb run:deprecated image upload, "
            "then updates the active version by image tag."
        ),
    )
    parser.add_argument("--desc", default="", help="Preview description label")
    args = parser.parse_args()

    ENV_ID = args.env_id
    SERVICE_NAME = args.service_name

    try:
        configure_runtime_paths(
            data_root=args.data_root,
            current_release_dir=args.current_release_dir,
            work_root=args.work_root,
            production_write=not args.dry_run,
        )
    except ValueError as exc:
        print(f"ERROR: invalid CloudRun runtime path contract: {exc}")
        return 2

    if args.promote_transaction:
        if args.dry_run:
            print("ERROR: --promote-transaction cannot be combined with --dry-run")
            return 2
        missing = [
            name
            for name, value in (
                ("--transaction-id", args.transaction_id),
                ("--deploy-report", args.deploy_report),
                ("--smoke-report", args.smoke_report),
                ("--pagination-report", args.pagination_report),
                ("--club-overviews-report", args.club_overviews_report),
                ("--publish-lease-path", args.publish_lease_path),
                ("--publish-lease-token", args.publish_lease_token),
            )
            if not value
        ]
        if missing:
            print("ERROR: promotion requires " + ", ".join(missing))
            return 2
        try:
            report = promote_publish_transaction(
                transaction_id=args.transaction_id,
                deploy_report_path=Path(args.deploy_report),
                smoke_report_path=Path(args.smoke_report),
                pagination_report_path=Path(args.pagination_report),
                club_overviews_report_path=Path(args.club_overviews_report),
                held_lease_path=Path(args.publish_lease_path),
                held_lease_token=args.publish_lease_token,
                promotion_proxy_url=args.promotion_proxy_url,
                promotion_timeout_seconds=args.promotion_timeout_seconds,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"ERROR: publish transaction promotion failed: {exc}")
            return 2
        print(
            json.dumps(
                {
                    "transaction_id": report.get("transaction_id"),
                    "status": report.get("status"),
                    "backup_dir": (report.get("promotion") or {}).get("backup_dir"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.release_dir:
        print("ERROR: --release-dir is required unless --promote-transaction is used")
        return 2
    release_dir = Path(args.release_dir)
    if not release_dir.exists():
        print(f"ERROR: release-dir not found: {release_dir}")
        return 1

    ts_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    desc = args.desc or f"deploy {release_dir.name} @ {ts_label}"
    transaction_id = args.transaction_id or (
        "publish-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )

    print(f"=== bake_and_deploy ===")
    print(f"  release : {release_dir}")
    print(f"  env     : {ENV_ID}")
    print(f"  service : {SERVICE_NAME}")
    print(f"  mode    : {args.deploy_mode}")
    print(f"  data    : {DATA_ROOT}")
    print(f"  current : {DATA_CURRENT_RELEASE}")
    print(f"  work    : {WORK_ROOT}")
    print(f"  dry-run : {args.dry_run}")
    print(f"  prepare : {args.prepare_only}")
    print(f"  tx      : {transaction_id}")
    print()

    # Step 1: tcb patch
    if not args.skip_patch_check:
        if not apply_tcb_patch(args.dry_run):
            print("ERROR: tcb CLI patch failed. Deploy aborted.")
            return 1

    if args.dry_run:
        if args.promote_dj_bio_atoms:
            atlas_bio_asset_snapshot(DATA_ROOT, required=True)
        if not bake_data(
            release_dir,
            Path(args.source_url_map) if args.source_url_map else None,
            True,
            update_column_json=args.update_column_json,
        ):
            return 1
        deploy_context = prepare_deploy_context(
            True,
            args.include_stage7_atlas or args.require_stage7_atlas,
        )
    else:
        try:
            transaction = prepare_publish_transaction(
                release_dir=release_dir,
                source_url_map=Path(args.source_url_map) if args.source_url_map else None,
                transaction_id=transaction_id,
                include_stage7_atlas=args.include_stage7_atlas or args.require_stage7_atlas,
                update_column_json=args.update_column_json,
                promote_dj_bio_atoms=args.promote_dj_bio_atoms,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"ERROR: publish transaction prepare failed: {exc}")
            return 2
        deploy_context = Path(transaction["paths"]["deploy_context"])
        print(
            "  prepared transaction: "
            f"status={transaction['status']} context={deploy_context} "
            f"item_id_digest={transaction['candidate_item_ids']['item_id_digest']}"
        )

    if args.prepare_only:
        print("\n=== Prepared publish transaction only; authoritative baseline unchanged ===")
        return 0

    # Step 3: deploy
    if not deploy(args.dry_run, args.deploy_mode, deploy_context):
        return 1

    # Step 4: wait
    wait_for_route(args.dry_run)

    # Step 5: QR
    if not args.no_qr:
        generate_qr(desc, args.dry_run)

    print("\n=== Deploy complete; transaction remains prepared pending remote smoke/pagination promotion ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
