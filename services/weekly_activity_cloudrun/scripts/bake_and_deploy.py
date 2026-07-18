#!/usr/bin/env python3
"""Bake a new weekly release into the CloudRun image and deploy it.

Workflow
--------
1. (Optional) Check / apply tcb CLI envId patch.
2. Copy release data  →  services/weekly_activity_cloudrun/data/current_release/
   Copy source_url_map  →  data/source_actions/source_url_map.json
3. tcb run deploy weekly-api --envId <ENV_ID>
4. Wait ROUTE_PROPAGATION_DELAY seconds for CloudRun route propagation.
5. Generate a dated preview QR via WeChat DevTools CLI.

This backend workflow never rewrites mini-program offlineSnapshot.js and never
uploads a mini-program version. Activity updates reach clients through the
online API and the persisted last-good response cache.

Usage examples
--------------
# Bake the latest named release and deploy:
python scripts/bake_and_deploy.py \
    --release-dir "E:\\weekly_activity_pipeline\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD" \
    --source-url-map "E:\\weekly_activity_pipeline\\longrun\\source_actions\\source_url_map.json"

# Dry-run (show what would be copied/run, make no changes):
python scripts/bake_and_deploy.py --release-dir ... --dry-run

# Skip QR generation (CI / headless):
python scripts/bake_and_deploy.py --release-dir ... --no-qr
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
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
MINIPROGRAM_DIR = _REPO_ROOT / "apps" / "weekly_activity_miniprogram"
DATA_CURRENT_RELEASE = _PROJECT_DIR / "data" / "current_release"
DATA_SOURCE_ACTIONS = _PROJECT_DIR / "data" / "source_actions"
DATA_STAGE7_ATLAS = _PROJECT_DIR / "data" / "stage7_atlas"
DATA_ROOT = _PROJECT_DIR / "data"
DEPLOY_CONTEXT_DIR = _PROJECT_DIR / "tmp" / "cloudrun_deploy_context"
DEPLOY_CONTEXT_MANIFEST = "deploy_context_manifest.json"
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


def ensure_source_grounded_llm_materialized(dry_run: bool) -> bool:
    """Ensure release ships deterministic materialized LLM files for runtime fallback."""
    current, reasons = materialized_llm_current(DATA_CURRENT_RELEASE)
    if current:
        print("  OK materialized llm outputs current")
        return True
    reason_text = ", ".join(reasons) if reasons else "unknown"
    script = _SCRIPT_DIR / "materialize_source_grounded_outputs.mjs"
    cmd = [
        "node",
        str(script),
        "--data-dir",
        str(DATA_CURRENT_RELEASE),
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
    current, reasons = materialized_llm_current(DATA_CURRENT_RELEASE)
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


def read_deploy_context_manifest() -> dict:
    path = DEPLOY_CONTEXT_DIR / DEPLOY_CONTEXT_MANIFEST
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def deploy_context_matches(manifest: dict) -> bool:
    if not DEPLOY_CONTEXT_DIR.exists():
        return False
    existing = read_deploy_context_manifest()
    if existing.get("fingerprint") != manifest.get("fingerprint"):
        return False
    for row in manifest.get("files", []):
        dst = DEPLOY_CONTEXT_DIR / str(row.get("dst", ""))
        if not dst.is_file():
            return False
        try:
            if dst.stat().st_size != int(row.get("size", -1)):
                return False
        except OSError:
            return False
    return True


def prepare_deploy_context(dry_run: bool, include_stage7_atlas: bool = False) -> Path:
    """Build a minimal CloudRun deploy context for source upload and image build."""
    print(f"\n--- prepare deploy context: {DEPLOY_CONTEXT_DIR} ---")
    current_release_items = [
        *RELEASE_ITEMS,
        *[item for item in OPTIONAL_RELEASE_ITEMS if (DATA_CURRENT_RELEASE / item).exists()],
    ]
    data_items = [
        ("data", DATA_ROOT, MINIAPP_ATLAS_INDEX_ITEMS),
        ("data/current_release", DATA_CURRENT_RELEASE, current_release_items),
        ("data/source_actions", DATA_SOURCE_ACTIONS, ["source_url_map.json"]),
    ]
    if include_stage7_atlas:
        data_items.append(("data/stage7_atlas", DATA_STAGE7_ATLAS, None))
    manifest = None
    if not dry_run:
        manifest = build_deploy_context_manifest(current_release_items, data_items)
        if deploy_context_matches(manifest):
            print(
                "  reused deploy context: "
                f"fingerprint={manifest['fingerprint'][:12]} files={manifest['file_count']} "
                f"bytes={manifest['total_bytes']}"
            )
            return DEPLOY_CONTEXT_DIR

    if dry_run:
        for item in DEPLOY_CONTEXT_TOP_ITEMS:
            print(f"  [DRY-RUN] stage {item}")
        for label, _src_dir, names in data_items:
            if names is None:
                print(f"  [DRY-RUN] stage {label}/")
            else:
                for name in names:
                    print(f"  [DRY-RUN] stage {label}/{name}")
        return DEPLOY_CONTEXT_DIR

    if DEPLOY_CONTEXT_DIR.exists():
        shutil.rmtree(DEPLOY_CONTEXT_DIR)
    DEPLOY_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    for item in DEPLOY_CONTEXT_TOP_ITEMS:
        src = _PROJECT_DIR / item
        if not src.exists():
            raise FileNotFoundError(f"deploy context source missing: {src}")
        copy_context_item(src, DEPLOY_CONTEXT_DIR / item)
        print(f"  staged: {item}")
    for label, src_dir, names in data_items:
        if names is None:
            if not src_dir.exists():
                raise FileNotFoundError(f"deploy context source missing: {src_dir}")
            copy_context_item(src_dir, DEPLOY_CONTEXT_DIR / label)
            print(f"  staged: {label}/")
            continue
        for name in names:
            src = src_dir / name
            if not src.exists():
                raise FileNotFoundError(f"deploy context source missing: {src}")
            copy_context_item(src, DEPLOY_CONTEXT_DIR / label / name)
            print(f"  staged: {label}/{name}")
    if manifest is not None:
        (DEPLOY_CONTEXT_DIR / DEPLOY_CONTEXT_MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(
            "  wrote deploy context manifest: "
            f"fingerprint={manifest['fingerprint'][:12]} files={manifest['file_count']} "
            f"bytes={manifest['total_bytes']}"
        )
    return DEPLOY_CONTEXT_DIR


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
    manifest.setdefault("source_pack_dir", str(release_dir))
    manifest["out_dir"] = str(DATA_CURRENT_RELEASE)
    manifest["deployed_current_release_dir"] = str(DATA_CURRENT_RELEASE)
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
    out_gz = DATA_ROOT / "atlas_neighborhood.json.gz"
    if not miniapp_db.exists():
        print(f"  SKIP neighborhood rebuild: no atlas_miniapp.sqlite at {miniapp_db}")
        return True
    if not builder.exists():
        print(f"  ERROR: neighborhood builder missing: {builder}")
        return False
    cmd = [sys.executable, str(builder), "--miniapp-db", str(miniapp_db), "--out", str(out_gz)]
    if dry_run:
        print(f"  [DRY-RUN] regenerate neighborhood bundle: {' '.join(cmd)}")
        return True
    print("  regenerating star-map neighborhood bundle from atlas_miniapp.sqlite")
    result = subprocess.run(cmd, cwd=str(builder.parent))
    if result.returncode != 0:
        print(f"  ERROR: neighborhood bundle rebuild exited {result.returncode}")
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


def validate_stage7_atlas(required: bool) -> bool:
    print("\n--- Stage7 atlas package ---")
    missing = []
    for item in REQUIRED_STAGE7_STATIC_ITEMS:
        path = DATA_STAGE7_ATLAS / item
        if path.exists():
            print(f"  OK {item} bytes={path.stat().st_size}")
        else:
            print(f"  MISSING {item}")
            missing.append(item)
    pointer_path = DATA_STAGE7_ATLAS / "release_pointer.staging.json"
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
            path = DATA_STAGE7_ATLAS / str(rel_path)
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
    global ENV_ID  # noqa: PLW0603
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release-dir", required=True, help="Path to the built release directory")
    parser.add_argument("--source-url-map", default=None, help="Path to source_url_map.json (optional, auto-detected from release)")
    parser.add_argument("--env-id", default=ENV_ID, help=f"CloudBase env ID (default: {ENV_ID})")
    parser.add_argument("--no-qr", action="store_true", help="Skip QR generation")
    parser.add_argument("--dry-run", action="store_true", help="Print steps without making changes")
    parser.add_argument("--prepare-only", action="store_true", help="Bake data and prepare deploy context without deploying")
    parser.add_argument("--skip-patch-check", action="store_true", help="Skip tcb CLI patch verification")
    parser.add_argument("--require-stage7-atlas", action="store_true", help="Abort if data/stage7_atlas is incomplete")
    parser.add_argument("--include-stage7-atlas", action="store_true", help="Include data/stage7_atlas in the deploy context")
    parser.add_argument(
        "--update-column-json",
        action="store_true",
        help="Also replace current_release/column.json. Off by default so activity releases do not overwrite column articles.",
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

    release_dir = Path(args.release_dir)
    if not release_dir.exists():
        print(f"ERROR: release-dir not found: {release_dir}")
        return 1

    ts_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    desc = args.desc or f"deploy {release_dir.name} @ {ts_label}"

    print(f"=== bake_and_deploy ===")
    print(f"  release : {release_dir}")
    print(f"  env     : {ENV_ID}")
    print(f"  service : {SERVICE_NAME}")
    print(f"  mode    : {args.deploy_mode}")
    print(f"  dry-run : {args.dry_run}")
    print(f"  prepare : {args.prepare_only}")
    print()

    # Step 1: tcb patch
    if not args.skip_patch_check:
        if not apply_tcb_patch(args.dry_run):
            print("ERROR: tcb CLI patch failed. Deploy aborted.")
            return 1

    # Step 2: bake data
    if not bake_data(
        release_dir,
        args.source_url_map,
        args.dry_run,
        update_column_json=args.update_column_json,
    ):
        print("ERROR: Data bake incomplete. Deploy aborted.")
        return 1

    # Step 2b: Stage7 atlas package is part of the full-pipeline CloudRun surface.
    if not validate_stage7_atlas(args.require_stage7_atlas):
        return 1

    deploy_context = prepare_deploy_context(args.dry_run, args.include_stage7_atlas or args.require_stage7_atlas)

    if args.prepare_only:
        print("\n=== Prepared deploy context only ===")
        return 0

    # Step 3: deploy
    if not deploy(args.dry_run, args.deploy_mode, deploy_context):
        return 1

    # Step 4: wait
    wait_for_route(args.dry_run)

    # Step 5: QR
    if not args.no_qr:
        generate_qr(desc, args.dry_run)

    print("\n=== Done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
