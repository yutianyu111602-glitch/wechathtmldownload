#!/usr/bin/env python3
"""Build a report-only PRD-12 poster vector write gate packet.

The packet consumes verified poster text vector jobs and local Qdrant read-only
state. It does not call embedding endpoints, create Qdrant collections, upsert
points, change aliases, or write graph/DB/mem0 state.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_POSTER_JOBS = Path(
    "reports/dajiala_paid_wave01_04_verified_poster_text_vector_jobs_20260516/"
    "poster_text_vector_jobs_summary.json"
)
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_OUT_DIR = Path("reports/poster_vector_write_gate_packet_20260516")
DEFAULT_AUTH_CONFIG = Path("config/consumer_publish_gate.local.json")
DEFAULT_POSTER_STAGING_REPORT = Path("reports/qdrant_poster_staging_20260517/qdrant_poster_staging_report.json")
SCHEMA_VERSION = "stage7_poster_vector_write_gate_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for poster vector write gate packet: {path}")


def require_local_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for PRD-12 read-only checks: {url}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_production_authorization(path: Path) -> dict[str, Any]:
    return read_json(path).get("production_authorization") or {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def qdrant_read_state(qdrant_url: str, collection: str) -> dict[str, Any]:
    require_local_url(qdrant_url)
    state: dict[str, Any] = {
        "url": qdrant_url,
        "read_ok": False,
        "collection_count": 0,
        "target_collection": collection,
        "target_collection_exists": False,
        "global_alias_read_ok": False,
        "target_alias_present": False,
        "error": "",
    }
    try:
        collections_response = requests.get(f"{qdrant_url.rstrip('/')}/collections", timeout=10)
        collections_response.raise_for_status()
        collections = (collections_response.json().get("result") or {}).get("collections") or []
        collection_names = {str(item.get("name") or "") for item in collections if isinstance(item, dict)}
        state["read_ok"] = True
        state["collection_count"] = len(collection_names)
        state["target_collection_exists"] = collection in collection_names
        aliases_response = requests.get(f"{qdrant_url.rstrip('/')}/aliases", timeout=10)
        if aliases_response.status_code < 400:
            aliases = (aliases_response.json().get("result") or {}).get("aliases") or []
            state["global_alias_read_ok"] = True
            state["target_alias_present"] = any(
                str(item.get("alias_name") or "") == f"{collection}_current" for item in aliases if isinstance(item, dict)
            )
    except Exception as exc:  # pragma: no cover - exercised through integration command, not unit tests.
        state["error"] = str(exc)[:500]
    return state


def unique_nonempty(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def build_packet(
    *,
    poster_jobs_path: Path,
    qdrant_url: str,
    out_dir: Path,
    auth_config_path: Path = DEFAULT_AUTH_CONFIG,
    poster_staging_report_path: Path = DEFAULT_POSTER_STAGING_REPORT,
    qdrant_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    jobs = read_json(poster_jobs_path)
    staging_report = read_json(poster_staging_report_path)
    collection = str(jobs.get("collection") or "")
    qdrant = qdrant_state if qdrant_state is not None else qdrant_read_state(qdrant_url, collection)
    authorization = read_production_authorization(auth_config_path)
    qdrant_write_allowed = bool(authorization.get("qdrant_write_allowed"))
    alias_change_allowed = bool(authorization.get("qdrant_alias_change_allowed"))
    job_count = int(jobs.get("job_count") or 0)
    image_exists_count = int(jobs.get("image_exists_count") or 0)
    unique_text_sha1 = int(jobs.get("unique_text_sha1") or 0)
    local_ready_gates = {
        "poster_jobs_ready": jobs.get("decision") == "poster_text_vector_jobs_ready_report_only",
        "job_count_gate_met": job_count >= 20,
        "all_images_exist": job_count > 0 and image_exists_count == job_count,
        "unique_text_hashes": job_count > 0 and unique_text_sha1 == job_count,
        "qdrant_read_ok": bool(qdrant.get("read_ok")),
        "target_collection_named": bool(collection),
        "embedding_not_called": not bool((jobs.get("safety") or {}).get("embedding_calls")),
        "qdrant_write_not_executed": not bool((jobs.get("safety") or {}).get("qdrant_write")),
    }
    staging_plan = staging_report.get("plan") or {}
    staging_collection_status = staging_report.get("collection_status") or {}
    staging_verification = staging_report.get("verification") or {}
    staging_safety = staging_report.get("safety") or {}
    staging_written_count = int(staging_report.get("written_count") or 0)
    staging_evidence_ready = (
        staging_report.get("decision") == "qdrant_poster_staging_written"
        and bool(staging_report.get("ok"))
        and str(staging_plan.get("collection") or "") == collection
        and int(staging_plan.get("dim") or 0) == int(jobs.get("dim") or 0)
        and staging_written_count == job_count
        and bool(staging_collection_status.get("healthy"))
        and float(staging_verification.get("match_rate") or 0.0) == 1.0
        and bool(staging_safety.get("qdrant_write"))
    )
    hard_gates_remaining = unique_nonempty(
        [
            *(
                ["EMBEDDING_GATE is required before poster vectors can be materialized"]
                if not staging_evidence_ready
                else []
            ),
            *(["QDRANT_WRITE is globally forbidden for this run"] if not qdrant_write_allowed else []),
            *(["QDRANT_ALIAS_CHANGE is forbidden for this run"] if not alias_change_allowed else []),
            *(
                ["Qdrant read check failed"]
                if not local_ready_gates["qdrant_read_ok"]
                else []
            ),
            *(
                ["poster target collection does not exist yet"]
                if not qdrant_write_allowed and not bool(qdrant.get("target_collection_exists"))
                else []
            ),
            *(
                ["poster current alias is not present yet"]
                if not alias_change_allowed and not bool(qdrant.get("target_alias_present"))
                else []
            ),
        ]
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "poster_vector_write_gate_packet_ready_report_only",
        "poster_jobs_path": str(poster_jobs_path),
        "poster_staging_report_path": str(poster_staging_report_path),
        "qdrant_url": qdrant_url,
        "auth_config_path": str(auth_config_path),
        "production_authorization": authorization,
        "poster_jobs": {
            "decision": jobs.get("decision"),
            "job_count": job_count,
            "model": jobs.get("model"),
            "dim": jobs.get("dim"),
            "collection": collection,
            "jobs_path": jobs.get("jobs_path"),
            "duplicate_text_sha1_count": jobs.get("duplicate_text_sha1_count"),
        },
        "poster_staging_evidence": {
            "decision": staging_report.get("decision"),
            "ok": staging_report.get("ok"),
            "collection": staging_plan.get("collection"),
            "alias": staging_plan.get("alias"),
            "written_count": staging_written_count,
            "collection_status": staging_collection_status,
            "verification": {
                "checked": staging_verification.get("checked"),
                "matched": staging_verification.get("matched"),
                "match_rate": staging_verification.get("match_rate"),
            },
            "qdrant_write_executed": staging_safety.get("qdrant_write"),
            "alias_change_executed": staging_safety.get("alias_change"),
            "evidence_ready": staging_evidence_ready,
        },
        "qdrant_read_state": qdrant,
        "embedding_allowed": staging_evidence_ready,
        "qdrant_write_allowed": qdrant_write_allowed,
        "alias_change_allowed": alias_change_allowed,
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": hard_gates_remaining,
        "future_execution_gate": jobs.get("future_execution_gate") or {},
        "forbidden_next_actions": [
            "do_not_call_embedding_endpoint_from_this_packet",
            "do_not_mark_prd12_production_ready_without_embedding_and_qdrant_write_gates",
            *(
                []
                if qdrant_write_allowed
                else [
                    "do_not_create_qdrant_collection_from_this_packet",
                    "do_not_upsert_qdrant_points_from_this_packet",
                ]
            ),
            *([] if alias_change_allowed else ["do_not_promote_qdrant_alias_from_this_packet"]),
        ],
        "allowed_next_actions": [
            "use poster vector jobs as verified PRD-12 input",
            *(
                ["use qdrant poster staging evidence as PRD-12 materialization proof"]
                if staging_evidence_ready
                else [
                    "prepare a separate isolated embedding canary only after the embedding gate exists",
                    "prepare a separate Qdrant staging write canary only after the write gate exists",
                ]
            ),
        ],
        "safety": {
            "reports_only": True,
            "embedding_calls": False,
            "qdrant_write": False,
            "alias_change": False,
            "neo4j_write": False,
            "mem0_write": False,
            "production_write": False,
            "paid_api": False,
            "d_scan": False,
            "publish": False,
        },
        "writes": "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "poster_vector_write_gate_packet.json", packet)
    write_markdown(out_dir / "poster_vector_write_gate_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Poster Vector Write Gate Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- job_count: `{packet['poster_jobs']['job_count']}`",
        f"- collection: `{packet['poster_jobs']['collection']}`",
        f"- embedding_allowed: `{packet['embedding_allowed']}`",
        f"- qdrant_write_allowed: `{packet['qdrant_write_allowed']}`",
        f"- local_ready_gate_count: `{packet['local_ready_gate_count']}`",
        "",
        "## Hard Gates Remaining",
        "",
    ]
    for item in packet["hard_gates_remaining"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Local Ready Gates", ""])
    for key, value in packet["local_ready_gates"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poster-jobs", type=Path, default=DEFAULT_POSTER_JOBS)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--auth-config", type=Path, default=DEFAULT_AUTH_CONFIG)
    parser.add_argument("--poster-staging-report", type=Path, default=DEFAULT_POSTER_STAGING_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        poster_jobs_path=args.poster_jobs,
        qdrant_url=args.qdrant_url,
        out_dir=args.out_dir,
        auth_config_path=args.auth_config,
        poster_staging_report_path=args.poster_staging_report,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "job_count": packet["poster_jobs"]["job_count"],
                "local_ready_gate_count": packet["local_ready_gate_count"],
                "hard_gates_remaining": len(packet["hard_gates_remaining"]),
                "summary": str(args.out_dir / "poster_vector_write_gate_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
