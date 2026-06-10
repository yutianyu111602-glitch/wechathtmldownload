"""Report-only Qdrant collection inventory and guarded snapshot helper.

Default usage is read-only:

    python scripts/snapshot_qdrant_collections.py --mode list-candidates

The write modes are intentionally guarded. They require a local Qdrant URL, an
explicit confirmation token, and they refuse to operate on the current Stage7
Qwen3 alias targets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse

import requests


DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_OUT_DIR = Path("reports/storage_migration_20260515")
DEFAULT_SNAPSHOT_DIR = Path("D:/DJ_DATA/databases/qdrant_snapshots")
SNAPSHOT_CONFIRM_TOKEN = "ENABLE_QDRANT_SNAPSHOT_WRITE"
DELETE_CONFIRM_TOKEN = "ENABLE_QDRANT_COLLECTION_DELETE"
SERVER_SNAPSHOT_CLEANUP_CONFIRM_TOKEN = "ENABLE_QDRANT_SERVER_SNAPSHOT_CLEANUP"
CURRENT_STAGE7_ALIASES = {
    "article": "wechat_stage7_article_qwen3_embedding_4b_1024_current",
    "entity": "wechat_stage7_entity_qwen3_embedding_4b_1024_current",
    "event": "wechat_stage7_event_qwen3_embedding_4b_1024_current",
}
PROTECTED_STAGE7_SIGNAL = "qwen3_embedding_4b_1024"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def require_local_qdrant(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for storage migration: {url}")


def normalized_windows_path(path: Path) -> str:
    return str(path.resolve(strict=False)).replace("/", "\\").rstrip("\\").casefold()


def require_safe_snapshot_dir(snapshot_dir: Path) -> Path:
    normalized = normalized_windows_path(snapshot_dir)
    forbidden = {"d:", "d:\\", "d:\\ddownload", "d:\\aidata"}
    if normalized in forbidden:
        raise ValueError(f"snapshot-dir is too broad or forbidden: {snapshot_dir}")
    allowed = normalized_windows_path(DEFAULT_SNAPSHOT_DIR)
    if normalized != allowed and not normalized.startswith(allowed + "\\"):
        raise ValueError(f"snapshot-dir must be under {DEFAULT_SNAPSHOT_DIR}: {snapshot_dir}")
    return snapshot_dir


def qdrant_request(method: str, qdrant_url: str, path: str, **kwargs: Any) -> dict[str, Any]:
    url = f"{qdrant_url.rstrip('/')}{path}"
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 60), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant {method} {path} failed {response.status_code}: {response.text[:500]}")
    if not response.text:
        return {}
    return response.json()


def qdrant_download(qdrant_url: str, path: str, destination: Path) -> int:
    response = requests.get(f"{qdrant_url.rstrip('/')}{path}", timeout=600, stream=True)
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant GET {path} failed {response.status_code}: {response.text[:500]}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    total = 0
    with tmp.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            handle.write(chunk)
            total += len(chunk)
    tmp.replace(destination)
    return total


def collection_names(qdrant_url: str) -> list[str]:
    data = qdrant_request("GET", qdrant_url, "/collections", timeout=30)
    rows = ((data.get("result") or {}).get("collections") or [])
    return sorted(str(row.get("name") or "") for row in rows if row.get("name"))


def alias_map(qdrant_url: str) -> dict[str, str]:
    data = qdrant_request("GET", qdrant_url, "/aliases", timeout=30)
    rows = ((data.get("result") or {}).get("aliases") or [])
    return {str(row["alias_name"]): str(row["collection_name"]) for row in rows if row.get("alias_name") and row.get("collection_name")}


def collection_info(qdrant_url: str, collection: str) -> dict[str, Any]:
    data = qdrant_request("GET", qdrant_url, f"/collections/{quote(collection, safe='')}", timeout=30)
    return data.get("result") or {}


def collection_snapshots(qdrant_url: str, collection: str) -> list[dict[str, Any]]:
    data = qdrant_request("GET", qdrant_url, f"/collections/{quote(collection, safe='')}/snapshots", timeout=30)
    result = data.get("result") or []
    return [row for row in result if isinstance(row, dict)]


def aliases_by_collection(aliases: dict[str, str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for alias, collection in aliases.items():
        result.setdefault(collection, []).append(alias)
    return {collection: sorted(names) for collection, names in result.items()}


def classify_collection(name: str, aliases_for_collection: list[str], active_targets: set[str]) -> dict[str, Any]:
    lower = name.casefold()
    alias_lowers = [alias.casefold() for alias in aliases_for_collection]
    protected_reasons = []
    if name in active_targets:
        protected_reasons.append("current_stage7_qwen3_alias_target")
    if name in CURRENT_STAGE7_ALIASES.values():
        protected_reasons.append("current_stage7_qwen3_alias_name")
    if name.startswith("wechat_stage7_") and PROTECTED_STAGE7_SIGNAL in lower:
        protected_reasons.append("stage7_qwen3_collection_name")
    legacy_signal = (
        "stella" in lower
        or "_mac_" in lower
        or lower.endswith("_mac")
        or any("stella" in alias for alias in alias_lowers)
        or any(alias.startswith("wechat_prod_") for alias in alias_lowers)
    )
    snapshot_candidate = not protected_reasons
    if not snapshot_candidate:
        reason = "protected_current_stage7_qwen3"
    elif legacy_signal:
        reason = "legacy_stella_or_mac_non_current"
    else:
        reason = "non_current_alias_target_needs_manual_review"
    return {
        "protected": bool(protected_reasons),
        "protected_reasons": protected_reasons,
        "legacy_signal": legacy_signal,
        "snapshot_candidate": snapshot_candidate,
        "candidate_reason": reason,
    }


def vector_size(info: dict[str, Any]) -> Any:
    vectors = (info.get("config") or {}).get("params", {}).get("vectors")
    if isinstance(vectors, dict) and "size" in vectors:
        return vectors.get("size")
    if isinstance(vectors, dict):
        sizes = sorted({value.get("size") for value in vectors.values() if isinstance(value, dict) and value.get("size")})
        return sizes[0] if len(sizes) == 1 else sizes
    return None


def build_inventory(collections: list[str], aliases: dict[str, str], infos: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_collection = aliases_by_collection(aliases)
    active_targets = {target for alias, target in aliases.items() if alias in CURRENT_STAGE7_ALIASES.values()}
    missing_current_aliases = sorted(alias for alias in CURRENT_STAGE7_ALIASES.values() if alias not in aliases)
    rows = []
    for name in sorted(collections):
        info = infos.get(name) or {}
        row = {
            "name": name,
            "aliases": by_collection.get(name, []),
            "points_count": int(info.get("points_count") or 0),
            "indexed_vectors_count": info.get("indexed_vectors_count"),
            "status": info.get("status"),
            "optimizer_status": info.get("optimizer_status"),
            "vector_size": vector_size(info),
        }
        row.update(classify_collection(name, row["aliases"], active_targets))
        rows.append(row)

    protected = [row for row in rows if row["protected"]]
    candidates = [row for row in rows if row["snapshot_candidate"]]
    legacy_candidates = [row for row in candidates if row["legacy_signal"]]
    return {
        "schema_version": "stage7_storage_migration_inventory.v1",
        "generated_at": now_iso(),
        "current_stage7_aliases": CURRENT_STAGE7_ALIASES,
        "current_stage7_alias_targets": {
            alias: aliases.get(alias) for alias in CURRENT_STAGE7_ALIASES.values()
        },
        "missing_current_stage7_aliases": missing_current_aliases,
        "alias_count": len(aliases),
        "collection_count": len(rows),
        "protected_count": len(protected),
        "snapshot_candidate_count": len(candidates),
        "legacy_stella_or_mac_candidate_count": len(legacy_candidates),
        "collections": rows,
        "safety": {
            "mutation_executed": False,
            "delete_executed": False,
            "d_drive_recursive_scan": False,
            "current_qwen3_aliases_untouched": True,
            "docker_vhdx_untouched": True,
            "neo4j_untouched": True,
        },
    }


def fetch_inventory(qdrant_url: str) -> dict[str, Any]:
    require_local_qdrant(qdrant_url)
    aliases = alias_map(qdrant_url)
    collections = collection_names(qdrant_url)
    infos = {name: collection_info(qdrant_url, name) for name in collections}
    return build_inventory(collections, aliases, infos)


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "snapshot"


def snapshot_destination(snapshot_dir: Path, collection: str, snapshot_name: str) -> Path:
    digest = hashlib.sha1(f"{collection}\0{snapshot_name}".encode("utf-8")).hexdigest()[:12]
    collection_slug = sanitize_filename(collection)[:96].rstrip("._") or "collection"
    suffix = ".snapshot" if snapshot_name.casefold().endswith(".snapshot") else ".snapshot"
    return snapshot_dir / f"{collection_slug}__{digest}{suffix}"


def write_inventory_reports(out_dir: Path, inventory: dict[str, Any]) -> None:
    candidates = [row for row in inventory["collections"] if row["snapshot_candidate"]]
    write_json(out_dir / "storage_migration_summary.json", inventory)
    write_json(out_dir / "qdrant_collection_inventory.json", inventory["collections"])
    write_jsonl(out_dir / "qdrant_collection_candidates.jsonl", candidates)
    write_markdown(out_dir / "snapshot_report.md", inventory)


def write_markdown(path: Path, inventory: dict[str, Any]) -> None:
    lines = [
        "# Qdrant Storage Migration Report",
        "",
        f"- generated_at: `{inventory['generated_at']}`",
        f"- collection_count: `{inventory['collection_count']}`",
        f"- alias_count: `{inventory['alias_count']}`",
        f"- protected_count: `{inventory['protected_count']}`",
        f"- snapshot_candidate_count: `{inventory['snapshot_candidate_count']}`",
        f"- legacy_stella_or_mac_candidate_count: `{inventory['legacy_stella_or_mac_candidate_count']}`",
        f"- missing_current_stage7_aliases: `{json.dumps(inventory['missing_current_stage7_aliases'], ensure_ascii=False)}`",
        "",
        "## Current Stage7 Qwen3 Alias Targets",
        "",
        "| Alias | Target Collection |",
        "|---|---|",
    ]
    for alias, target in sorted(inventory["current_stage7_alias_targets"].items()):
        lines.append(f"| `{alias}` | `{target or ''}` |")
    lines.extend(["", "## Snapshot Candidates", "", "| Collection | Points | Status | Aliases | Reason |", "|---|---:|---|---|---|"])
    for row in inventory["collections"]:
        if not row["snapshot_candidate"]:
            continue
        aliases = ", ".join(f"`{alias}`" for alias in row["aliases"])
        lines.append(
            f"| `{row['name']}` | {row['points_count']} | `{row.get('status') or ''}` | {aliases} | `{row['candidate_reason']}` |"
        )
    lines.extend(["", "## Protected Collections", "", "| Collection | Points | Reasons |", "|---|---:|---|"])
    for row in inventory["collections"]:
        if not row["protected"]:
            continue
        reasons = ", ".join(row["protected_reasons"])
        lines.append(f"| `{row['name']}` | {row['points_count']} | `{reasons}` |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This report is read-only: no snapshot, alias change, delete, Neo4j write, production DB write, paid API, or D: recursive scan was executed.",
            "- `snapshot` and `delete` modes require explicit confirmation tokens and refuse current Stage7 Qwen3 alias targets.",
            "- Docker VHDX, active WSL model cache, current Qwen3 aliases, and Neo4j staging are outside this operation.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_snapshot_allowed(collection: str, inventory: dict[str, Any]) -> dict[str, Any]:
    rows = {row["name"]: row for row in inventory["collections"]}
    if collection not in rows:
        raise ValueError(f"collection not found in Qdrant inventory: {collection}")
    row = rows[collection]
    if row["protected"]:
        raise ValueError(f"refusing protected current collection: {collection} reasons={row['protected_reasons']}")
    return row


def create_and_download_snapshot(qdrant_url: str, collection: str, snapshot_dir: Path) -> dict[str, Any]:
    require_safe_snapshot_dir(snapshot_dir)
    created = qdrant_request(
        "POST",
        qdrant_url,
        f"/collections/{quote(collection, safe='')}/snapshots",
        timeout=600,
    ).get("result") or {}
    snapshot_name = str(created.get("name") or "")
    if not snapshot_name:
        snapshots = collection_snapshots(qdrant_url, collection)
        snapshot_name = str((snapshots[-1] if snapshots else {}).get("name") or "")
    if not snapshot_name:
        raise RuntimeError(f"Qdrant did not return a snapshot name for {collection}")
    destination = snapshot_destination(snapshot_dir, collection, snapshot_name)
    bytes_written = qdrant_download(
        qdrant_url,
        f"/collections/{quote(collection, safe='')}/snapshots/{quote(snapshot_name, safe='')}",
        destination,
    )
    return {
        "collection": collection,
        "snapshot_name": snapshot_name,
        "snapshot_file": str(destination),
        "file_size_bytes": bytes_written,
        "qdrant_result": created,
    }


def build_snapshot_manifest(snapshot_dir: Path) -> dict[str, Any]:
    require_safe_snapshot_dir(snapshot_dir)
    rows = []
    if snapshot_dir.exists():
        for item in sorted(snapshot_dir.iterdir()):
            if not item.is_file() or item.suffix != ".snapshot":
                continue
            rows.append(
                {
                    "file": item.name,
                    "path": str(item),
                    "file_size_bytes": item.stat().st_size,
                    "non_empty": item.stat().st_size > 0,
                    "last_write_time": datetime.fromtimestamp(item.stat().st_mtime).isoformat(timespec="seconds"),
                }
            )
    return {
        "schema_version": "stage7_storage_snapshot_manifest.v1",
        "generated_at": now_iso(),
        "snapshot_dir": str(snapshot_dir),
        "snapshot_file_count": len(rows),
        "all_non_empty": all(row["non_empty"] for row in rows),
        "files": rows,
        "safety": {
            "d_drive_recursive_scan": False,
            "one_level_listing_only": True,
            "delete_executed": False,
        },
    }


def write_manifest_reports(out_dir: Path, manifest: dict[str, Any]) -> None:
    write_json(out_dir / "snapshot_manifest.json", manifest)
    lines = [
        "# Qdrant Snapshot Manifest",
        "",
        f"- generated_at: `{manifest['generated_at']}`",
        f"- snapshot_dir: `{manifest['snapshot_dir']}`",
        f"- snapshot_file_count: `{manifest['snapshot_file_count']}`",
        f"- all_non_empty: `{manifest['all_non_empty']}`",
        "",
        "| File | Size Bytes | Non Empty |",
        "|---|---:|---|",
    ]
    for row in manifest["files"]:
        lines.append(f"| `{row['file']}` | {row['file_size_bytes']} | `{row['non_empty']}` |")
    (out_dir / "snapshot_manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def delete_collection(qdrant_url: str, collection: str) -> dict[str, Any]:
    data = qdrant_request("DELETE", qdrant_url, f"/collections/{quote(collection, safe='')}", timeout=600)
    return {"collection": collection, "qdrant_result": data.get("result"), "delete_executed": True}


def delete_server_snapshot(qdrant_url: str, collection: str, snapshot_name: str) -> dict[str, Any]:
    data = qdrant_request(
        "DELETE",
        qdrant_url,
        f"/collections/{quote(collection, safe='')}/snapshots/{quote(snapshot_name, safe='')}",
        timeout=300,
    )
    return {"collection": collection, "snapshot_name": snapshot_name, "qdrant_result": data.get("result")}


def cleanup_server_snapshots(qdrant_url: str, collection: str, snapshot_name: str = "") -> dict[str, Any]:
    snapshots = collection_snapshots(qdrant_url, collection)
    selected = [row for row in snapshots if not snapshot_name or row.get("name") == snapshot_name]
    deleted = []
    for row in selected:
        name = str(row.get("name") or "")
        if not name:
            continue
        deleted.append(delete_server_snapshot(qdrant_url, collection, name))
    remaining = collection_snapshots(qdrant_url, collection)
    return {
        "collection": collection,
        "requested_snapshot_name": snapshot_name,
        "server_snapshot_count_before": len(snapshots),
        "deleted_count": len(deleted),
        "deleted": deleted,
        "server_snapshot_count_after": len(remaining),
        "remaining_snapshot_names": [row.get("name") for row in remaining],
        "collection_deleted": False,
        "alias_changed": False,
    }


def run(args: argparse.Namespace) -> int:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "manifest":
        manifest = build_snapshot_manifest(args.snapshot_dir)
        write_manifest_reports(args.out_dir, manifest)
        print(json.dumps({"ok": True, "mode": args.mode, "manifest": str(args.out_dir / "snapshot_manifest.json")}, ensure_ascii=False, indent=2))
        return 0

    require_local_qdrant(args.qdrant_url)
    inventory = fetch_inventory(args.qdrant_url)
    write_inventory_reports(args.out_dir, inventory)

    if args.mode == "list-candidates":
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": args.mode,
                    "collection_count": inventory["collection_count"],
                    "snapshot_candidate_count": inventory["snapshot_candidate_count"],
                    "legacy_stella_or_mac_candidate_count": inventory["legacy_stella_or_mac_candidate_count"],
                    "summary": str(args.out_dir / "storage_migration_summary.json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.collection:
        raise SystemExit(f"--collection is required for mode {args.mode}")
    ensure_snapshot_allowed(args.collection, inventory)

    if args.mode == "snapshot":
        if args.confirm_token != SNAPSHOT_CONFIRM_TOKEN:
            raise SystemExit(f"--confirm-token {SNAPSHOT_CONFIRM_TOKEN} required for snapshot mode")
        result = {
            "schema_version": "stage7_storage_snapshot_result.v1",
            "generated_at": now_iso(),
            "mutation_executed": True,
            "delete_executed": False,
            "result": create_and_download_snapshot(args.qdrant_url, args.collection, args.snapshot_dir),
        }
        write_json(args.out_dir / "snapshot_result.json", result)
        manifest = build_snapshot_manifest(args.snapshot_dir)
        write_manifest_reports(args.out_dir, manifest)
        print(json.dumps({"ok": True, "mode": args.mode, "result": str(args.out_dir / "snapshot_result.json")}, ensure_ascii=False, indent=2))
        return 0

    if args.mode == "verify":
        manifest = build_snapshot_manifest(args.snapshot_dir)
        write_manifest_reports(args.out_dir, manifest)
        print(json.dumps({"ok": manifest["all_non_empty"], "mode": args.mode, "manifest": str(args.out_dir / "snapshot_manifest.json")}, ensure_ascii=False, indent=2))
        return 0 if manifest["all_non_empty"] else 1

    if args.mode == "delete":
        if args.confirm_token != DELETE_CONFIRM_TOKEN:
            raise SystemExit(f"--confirm-token {DELETE_CONFIRM_TOKEN} required for delete mode")
        result = {
            "schema_version": "stage7_storage_delete_result.v1",
            "generated_at": now_iso(),
            "mutation_executed": True,
            "delete_executed": True,
            "result": delete_collection(args.qdrant_url, args.collection),
        }
        write_json(args.out_dir / "delete_result.json", result)
        print(json.dumps({"ok": True, "mode": args.mode, "result": str(args.out_dir / "delete_result.json")}, ensure_ascii=False, indent=2))
        return 0

    if args.mode == "cleanup-server-snapshots":
        if args.confirm_token != SERVER_SNAPSHOT_CLEANUP_CONFIRM_TOKEN:
            raise SystemExit(f"--confirm-token {SERVER_SNAPSHOT_CLEANUP_CONFIRM_TOKEN} required for cleanup-server-snapshots mode")
        result = {
            "schema_version": "stage7_storage_server_snapshot_cleanup.v1",
            "generated_at": now_iso(),
            "mutation_executed": True,
            "server_snapshot_cleanup_executed": True,
            "delete_collection_executed": False,
            "result": cleanup_server_snapshots(args.qdrant_url, args.collection, args.snapshot_name),
        }
        write_json(args.out_dir / "server_snapshot_cleanup.json", result)
        print(json.dumps({"ok": True, "mode": args.mode, "result": str(args.out_dir / "server_snapshot_cleanup.json")}, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit(f"unsupported mode: {args.mode}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["list-candidates", "snapshot", "manifest", "verify", "delete", "cleanup-server-snapshots"],
        default="list-candidates",
    )
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--collection", default="")
    parser.add_argument("--snapshot-name", default="")
    parser.add_argument("--confirm-token", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
