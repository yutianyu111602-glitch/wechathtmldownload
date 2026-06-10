#!/usr/bin/env python3
"""Build a hashed/redacted T6 sidecar manifest for Atlas DJ merge gates.

This report-only builder consumes the WSL2 outlink/avatar scratch SQLite and a
selected Atlas serving SQLite in read-only mode. It writes only sanitized,
hash-addressed manifest files for T5 validation. It never emits raw URLs or
local filesystem paths and never mutates Atlas DB, serving DB, graph/vector, or
public state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_SCRATCH_DB = Path(r"\\wsl.localhost\Ubuntu\tmp\swarm_scratch.sqlite")
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_CONTRACT = STAGE7_ROOT / "reports" / "atlas_dj_completion_effect_audit_t5_t6_20260526" / "t6_outlink_avatar_sidecar_contract.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_redacted_manifest_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_SIDECAR_REDACTED_MANIFEST_20260526.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_redacted_manifest.v1"
PRODUCER = "codex_t6_sidecar_redacted_manifest_builder"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer|pass_ticket|openid)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = URL_RE.sub("[url-redacted]", text)
    text = LOCAL_PATH_RE.sub("[path-redacted]", text)
    text = SECRET_RE.sub("[key-redacted]", text)
    return text[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_unbounded_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} must not be an unbounded D: root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata") or raw.startswith("/mnt/d/ddownload") or raw.startswith("/mnt/d/aidata"):
        raise ValueError(f"{label} must not scan cold D: data roots: {path}")


def path_ref(path: Path | None) -> dict[str, Any]:
    if not path:
        return {"present": False}
    present = path.exists()
    return {
        "present": present,
        "basename": path.name,
        "path_sha256_12": sha256_text(str(path))[:12],
        "bytes": path.stat().st_size if present and path.is_file() else 0,
    }


def connect_readonly(path: Path) -> sqlite3.Connection:
    reject_unbounded_d_root(path, "sqlite_input")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def copy_unc_sqlite_if_needed(path: Path) -> tuple[tempfile.TemporaryDirectory[str] | None, Path]:
    if str(path).startswith("\\\\"):
        tmpdir = tempfile.TemporaryDirectory()
        snapshot = Path(tmpdir.name) / "sidecar_scratch_snapshot.sqlite"
        shutil.copy2(path, snapshot)
        return tmpdir, snapshot
    return None, path


def read_json(path: Path | None, default: Any = None) -> Any:
    if not path or not path.exists():
        return default
    reject_unbounded_d_root(path, "json_input")
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (table,)).fetchone() is not None


def table_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not table_exists(conn, table):
        return []
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]


def serving_name_index(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute("SELECT dj_id, display_name, normalized_name, city_primary FROM dj_profile"):
        payload = {
            "dj_id": row["dj_id"],
            "display_name": row["display_name"],
            "normalized_name": row["normalized_name"],
            "city_primary": row["city_primary"],
        }
        for value in [row["display_name"], row["normalized_name"]]:
            key = normalize(value)
            if key:
                index[key].append(payload)
    return index


def resolve_entity(name: Any, index: dict[str, list[dict[str, Any]]]) -> tuple[str, str, str]:
    key = normalize(name)
    matches = index.get(key, [])
    unique = {match["dj_id"]: match for match in matches}
    if len(unique) == 1:
        match = next(iter(unique.values()))
        return str(match["dj_id"]), compact(match["display_name"], 160), ""
    if len(unique) > 1:
        return "", compact(name, 160), "ambiguous_serving_name_join"
    return "", compact(name, 160), "missing_serving_name_join"


def url_parts(url: Any) -> dict[str, str]:
    value = str(url or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError:
        return {
            "host": "",
            "url_sha256": sha256_text(value),
            "path_sha256_12": sha256_text(value)[:12],
            "canonical_url_key": f"invalid|{sha256_text(value)[:24]}",
            "url_redacted": f"host=invalid;url_sha256_12={sha256_text(value)[:12]};path_sha256_12={sha256_text(value)[:12]}",
        }
    host = (parsed.netloc or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    path_key = f"{parsed.path or ''}?{parsed.query or ''}#{parsed.fragment or ''}"
    return {
        "host": host,
        "url_sha256": sha256_text(value),
        "path_sha256_12": sha256_text(path_key)[:12],
        "canonical_url_key": f"{host}|{sha256_text(value)[:24]}",
        "url_redacted": f"host={host};url_sha256_12={sha256_text(value)[:12]};path_sha256_12={sha256_text(path_key)[:12]}",
    }


def evidence_hash(*values: Any) -> str:
    return sha256_text("|".join(str(value or "") for value in values))


def safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def leak_counts_for(payloads: Iterable[Any]) -> dict[str, int]:
    counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in payloads:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        counts["public_url_hits"] += len(URL_RE.findall(text))
        counts["sensitive_key_hits"] += len(SECRET_RE.findall(text))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return counts


def resolve_avatar_binary(local_path: Any) -> tuple[str, dict[str, Any]]:
    raw = str(local_path or "").strip()
    if not raw:
        return "", {"status": "blocked_no_local_ref"}

    candidates: list[Path] = []
    if raw.startswith("/"):
        candidates.append(Path(r"\\wsl.localhost\Ubuntu") / raw.lstrip("/").replace("/", "\\"))
    elif re.match(r"^[A-Za-z]:[\\/]", raw):
        candidates.append(Path(raw))

    for candidate in candidates[:2]:
        try:
            if candidate.exists() and candidate.is_file():
                return sha256_file(candidate), {
                    "status": "content_hash_ready",
                    "byte_size": candidate.stat().st_size,
                    "mime_type": mimetypes.guess_type(candidate.name)[0] or "application/octet-stream",
                }
        except (OSError, PermissionError):
            continue
    return "", {"status": "blocked_avatar_binary_unreadable"}


def build_candidate(
    *,
    candidate_kind: str,
    source_id: Any,
    entity_name: Any,
    platform: Any,
    url: Any,
    handle: Any,
    evidence_text: Any,
    confidence: Any,
    name_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    parts = url_parts(url)
    entity_id, display_name, join_blocker = resolve_entity(entity_name, name_index)
    candidate_id = f"t6:{candidate_kind}:{parts['url_sha256'][:20]}"
    blocked_reason = join_blocker or ("" if parts["host"] else "invalid_or_non_url_candidate")
    row = {
        "accepted_for_graph": False,
        "blocked_reason": blocked_reason,
        "candidate_id": candidate_id,
        "candidate_kind": candidate_kind,
        "canonical_url_key": parts["canonical_url_key"],
        "confidence": safe_float(confidence),
        "entity_id": entity_id,
        "evidence_text_hash": evidence_hash(evidence_text, source_id, platform),
        "evidence_text_summary": compact(evidence_text, 240),
        "handle": compact(handle, 120),
        "host": parts["host"],
        "identity_match_signals": ["serving_name_exact_or_normalized"] if entity_id else [],
        "platform": compact(platform, 80),
        "public_serving_field_allowed": False,
        "source_context_hashes": [],
        "url_redacted": parts["url_redacted"],
        "url_sha256": parts["url_sha256"],
    }
    if blocked_reason:
        return None, {
            "blocked_reason": blocked_reason,
            "blocked_stage": "candidate_precheck",
            "candidate_id": candidate_id,
            "entity_id": entity_id,
            "required_next_evidence": "valid URL host and unique Atlas serving/source entity join",
        }
    return row, None


def build_packet(
    scratch_db: Path,
    serving_db: Path,
    contract_path: Path | None,
    out_dir: Path,
    report_path: Path,
    row_limit: int | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpdir, scratch_path = copy_unc_sqlite_if_needed(scratch_db)
    scratch_conn: sqlite3.Connection | None = None
    serving_conn: sqlite3.Connection | None = None
    try:
        scratch_conn = connect_readonly(scratch_path)
        serving_conn = connect_readonly(serving_db)
        name_index = serving_name_index(serving_conn)

        table_counts = {
            table: table_count(scratch_conn, table)
            for table in ["dj_social_profiles", "dj_outlinks", "dj_identity_candidates", "dj_avatars"]
        }
        social_rows = rows(scratch_conn, "dj_social_profiles")
        outlink_rows = rows(scratch_conn, "dj_outlinks")
        identity_rows = rows(scratch_conn, "dj_identity_candidates")
        avatar_rows = rows(scratch_conn, "dj_avatars")
    finally:
        if scratch_conn is not None:
            scratch_conn.close()
        if serving_conn is not None:
            serving_conn.close()
        if tmpdir is not None:
            tmpdir.cleanup()

    if row_limit is not None:
        social_rows = social_rows[:row_limit]
        outlink_rows = outlink_rows[:row_limit]
        identity_rows = identity_rows[:row_limit]
        avatar_rows = avatar_rows[:row_limit]

    candidate_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for source in social_rows:
        row, blocker = build_candidate(
            candidate_kind="profile",
            source_id=source.get("profile_id"),
            entity_name=source.get("entity_name"),
            platform=source.get("platform"),
            url=source.get("profile_url"),
            handle=source.get("handle"),
            evidence_text=source.get("source_title") or source.get("search_query"),
            confidence=source.get("confidence"),
            name_index=name_index,
        )
        if row:
            if row["canonical_url_key"] not in seen_keys:
                candidate_rows.append(row)
                seen_keys.add(row["canonical_url_key"])
        elif blocker:
            blocked_rows.append(blocker)

    for source in outlink_rows:
        row, blocker = build_candidate(
            candidate_kind="outlink",
            source_id=source.get("outlink_id"),
            entity_name=source.get("entity_name"),
            platform=source.get("outlink_platform"),
            url=source.get("outlink_url"),
            handle="",
            evidence_text=source.get("source_layer") or source.get("source"),
            confidence=0.0,
            name_index=name_index,
        )
        if row:
            if row["canonical_url_key"] not in seen_keys:
                candidate_rows.append(row)
                seen_keys.add(row["canonical_url_key"])
        elif blocker:
            blocked_rows.append(blocker)

    for source in identity_rows:
        row, blocker = build_candidate(
            candidate_kind="identity_candidate",
            source_id=source.get("sidecar_id"),
            entity_name=source.get("display_name"),
            platform=source.get("platform"),
            url=source.get("url_normalized"),
            handle=source.get("handle"),
            evidence_text=source.get("bio_snippet") or source.get("evidence_text") or source.get("evidence_source_title"),
            confidence=source.get("confidence"),
            name_index=name_index,
        )
        if row:
            signals = [source.get("match_type"), "identity_candidate_row"]
            row["identity_match_signals"] = [compact(signal, 80) for signal in signals if compact(signal, 80)]
            row["blocked_reason"] = "source_context_not_verified_identity_review_only"
            if row["canonical_url_key"] not in seen_keys:
                candidate_rows.append(row)
                seen_keys.add(row["canonical_url_key"])
        elif blocker:
            blocked_rows.append(blocker)

    entity_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        entity_groups[row["entity_id"]].append(row)

    avatar_manifest: list[dict[str, Any]] = []
    avatar_entity_name_by_eid: dict[str, str] = {}
    for source in social_rows:
        eid = str(source.get("eid") or "")
        if eid and source.get("entity_name"):
            avatar_entity_name_by_eid.setdefault(eid, str(source.get("entity_name")))
    for source in avatar_rows:
        entity_id, display_name, join_blocker = resolve_entity(avatar_entity_name_by_eid.get(str(source.get("eid") or "")), name_index)
        parts = url_parts(source.get("avatar_url"))
        content_sha256, binary = resolve_avatar_binary(source.get("local_path"))
        candidate_id = f"t6:avatar:{parts['url_sha256'][:20]}"
        blocked_reason = ""
        if join_blocker:
            blocked_reason = join_blocker
        elif not content_sha256:
            blocked_reason = binary["status"]
        avatar_manifest.append(
            {
                "avatar_asset_id": f"avatar:{parts['url_sha256'][:20]}",
                "blocked_reason": blocked_reason,
                "byte_size": int(binary.get("byte_size") or source.get("file_size") or 0),
                "candidate_id": candidate_id,
                "content_sha256": content_sha256,
                "download_status": "hash_ready" if content_sha256 else "blocked",
                "entity_id": entity_id,
                "height": 0,
                "mime_type": compact(binary.get("mime_type") or "", 120),
                "perceptual_hash": "",
                "storage_ref_hash": sha256_text(source.get("local_path")) if source.get("local_path") else "",
                "width": 0,
            }
        )
        if blocked_reason:
            blocked_rows.append(
                {
                    "blocked_reason": blocked_reason,
                    "blocked_stage": "avatar_artifact",
                    "candidate_id": candidate_id,
                    "entity_id": entity_id,
                    "required_next_evidence": "readable avatar binary content hash and serving/source entity join",
                }
            )

    entity_rollups = []
    for entity_id, rows_for_entity in sorted(entity_groups.items()):
        kinds = Counter(row["candidate_kind"] for row in rows_for_entity)
        first = rows_for_entity[0]
        profile = next((row for row in rows_for_entity if row["candidate_kind"] == "profile"), rows_for_entity[0])
        avatar = next((row for row in avatar_manifest if row["entity_id"] == entity_id and row["content_sha256"]), None)
        entity_rollups.append(
            {
                "best_avatar_asset_hash": avatar["content_sha256"] if avatar else "",
                "best_profile_url_hash": profile["url_sha256"],
                "blockers": sorted({row["blocked_reason"] for row in rows_for_entity if row.get("blocked_reason")}),
                "candidate_counts_by_kind": dict(kinds),
                "display_name": first["evidence_text_summary"][:120],
                "entity_id": entity_id,
                "entity_kind": "dj",
                "merge_status": "candidate_review_only",
                "normalized_name": normalize(first["evidence_text_summary"]),
                "source_context_hashes": [],
            }
        )

    contract = read_json(contract_path, {}) if contract_path else {}
    write_guards = {
        "report_only": True,
        "source_raw_db_write_executed": False,
        "serving_sqlite_write_executed": False,
        "serving_rebuild_executed": False,
        "neo4j_write_executed": False,
        "qdrant_write_executed": False,
        "public_pointer_updated": False,
        "huaidj_club_upload_executed": False,
        "memory_write_executed": False,
    }

    leak_payloads = [candidate_rows, avatar_manifest, entity_rollups, blocked_rows, write_guards]
    leak_scan = leak_counts_for(leak_payloads)
    failed_checks: list[str] = []
    if any(leak_scan.values()):
        failed_checks.append("redacted_manifest_leak_scan_hits")
    if not candidate_rows:
        failed_checks.append("no_joined_candidate_rows")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "producer": PRODUCER,
        "run_id": "atlas_t6_sidecar_redacted_manifest_20260526",
        "generated_at": now_iso(),
        "input_entity_count": len(entity_groups),
        "candidate_count": len(candidate_rows),
        "avatar_artifact_count": len(avatar_manifest),
        "blocked_count": len(blocked_rows),
        "leak_scan": leak_scan,
        "write_guards": write_guards,
    }
    provenance = {
        "schema_version": f"{SCHEMA_VERSION}.provenance",
        "source_inputs": {
            "scratch_db": path_ref(scratch_db),
            "serving_db": path_ref(serving_db),
            "contract": path_ref(contract_path),
        },
        "source_input_hashes": {
            "scratch_path_sha256_12": sha256_text(str(scratch_db))[:12],
            "serving_path_sha256_12": sha256_text(str(serving_db))[:12],
        },
        "runtime": {
            "generated_at": manifest["generated_at"],
            "snapshot_mode": "temporary_copy_from_wsl_unc" if str(scratch_db).startswith("\\\\") else "direct_read_only",
        },
        "safety": {
            "raw_url_emitted": False,
            "local_path_emitted": False,
            "report_only": True,
            "contract_schema_version": contract.get("schema_version", ""),
        },
        "counts": {
            "scratch_table_counts": table_counts,
            "joined_candidates": len(candidate_rows),
            "entity_rollups": len(entity_rollups),
            "avatar_artifacts": len(avatar_manifest),
            "blocked_rows": len(blocked_rows),
        },
    }

    decision = "atlas_t6_sidecar_redacted_manifest_ready_report_only" if not failed_checks else "atlas_t6_sidecar_redacted_manifest_blocked_report_only"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": manifest["generated_at"],
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": provenance["counts"],
        "leak_scan": leak_scan,
        "manifest": manifest,
        "provenance_summary": provenance,
        "write_guards": write_guards,
        "next_resume_pointer": "tools/stage7_rewrite/reports/atlas_t6_sidecar_redacted_manifest_20260526/manifest.json",
    }

    write_json(out_dir / "manifest.json", manifest)
    write_jsonl(out_dir / "entity_rollups.jsonl", entity_rollups)
    write_jsonl(out_dir / "candidate_evidence.jsonl", candidate_rows)
    write_jsonl(out_dir / "avatar_artifacts_manifest.jsonl", avatar_manifest)
    write_jsonl(out_dir / "blocked_rows.jsonl", blocked_rows)
    write_json(out_dir / "leak_scan.json", leak_scan)
    write_json(out_dir / "provenance_summary.json", provenance)
    write_json(out_dir / "sidecar_redacted_manifest_summary.json", summary)
    write_text(report_path, render_report(summary))
    return summary


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_scan"]
    lines = [
        "# Atlas T6 Sidecar Redacted Manifest",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- failed_checks: `{summary['failed_checks']}`",
        f"- scratch_table_counts: `{counts['scratch_table_counts']}`",
        f"- joined_candidates: `{counts['joined_candidates']}`",
        f"- entity_rollups: `{counts['entity_rollups']}`",
        f"- avatar_artifacts: `{counts['avatar_artifacts']}`",
        f"- blocked_rows: `{counts['blocked_rows']}`",
        f"- leak_scan public_url/sensitive_key/local_path: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        "- `manifest.json`",
        "- `entity_rollups.jsonl`",
        "- `candidate_evidence.jsonl`",
        "- `avatar_artifacts_manifest.jsonl`",
        "- `blocked_rows.jsonl`",
        "- `leak_scan.json`",
        "- `provenance_summary.json`",
        "",
        "## Boundary",
        "",
        "- This packet is report-only candidate evidence for T5 validation.",
        "- It emits no raw URL and no local path.",
        "- It does not write Atlas source/raw DB, serving SQLite, Neo4j, Qdrant, public pointer, huaidj.club, mini-program, or memory.",
        "",
        f"- next_resume_pointer: `{summary['next_resume_pointer']}`",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-db", type=Path, default=DEFAULT_SCRATCH_DB)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--row-limit", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.scratch_db, args.serving_db, args.contract, args.out_dir, args.report, args.row_limit)
    print(json.dumps({"decision": summary["decision"], "failed_checks": summary["failed_checks"], "summary": str(args.out_dir / "sidecar_redacted_manifest_summary.json")}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
