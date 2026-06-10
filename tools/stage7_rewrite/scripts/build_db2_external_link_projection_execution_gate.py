#!/usr/bin/env python3
"""Build the DB2 external-link projection execution gate packet.

This consumes the report-only prewrite packet and live DB2 read-only evidence,
then emits report-local writer-event previews, snapshot work orders, and a
delivery manifest. It does not copy anything into the live DB2 spool and does
not mutate DB2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"

SCHEMA_VERSION = "db2_external_link_projection_execution_gate.v1"
REQUIRED_CONFIRM_TOKEN = "OPEN_DB2_EXTERNAL_LINK_PROJECTION_20260604"
DEFAULT_PREWRITE_DIR = REPORTS_ROOT / "db2_external_link_projection_prewrite_packet_20260604"
DEFAULT_PREWRITE_PACKET = DEFAULT_PREWRITE_DIR / "db2_external_link_projection_prewrite_packet.json"
DEFAULT_PREWRITE_CANDIDATES = DEFAULT_PREWRITE_DIR / "db2_external_link_projection_prewrite_candidates.jsonl"
DEFAULT_ROLLBACK_CONTRACTS = DEFAULT_PREWRITE_DIR / "db2_external_link_projection_rollback_contracts.jsonl"
DEFAULT_READBACK_CONTRACTS = DEFAULT_PREWRITE_DIR / "db2_external_link_projection_postwrite_readback_contracts.jsonl"
DEFAULT_OUT_DIR = REPORTS_ROOT / "db2_external_link_projection_execution_gate_20260604"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "DB2_EXTERNAL_LINK_PROJECTION_EXECUTION_GATE_20260604.md"

EXPECTED_DJ_OUTLINK_COLUMNS = {
    "outlink_id",
    "eid",
    "profile_id",
    "outlink_url",
    "outlink_platform",
    "entity_name",
    "source_layer",
    "source_profile_url",
    "profile_platform",
    "discovered_at",
    "source",
}
TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "igsh",
    "mc_cid",
    "mc_eid",
    "spm",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|api[_-]?key[\"']?\s*[:=]|authorization[\"']?\s*[:=]|"
    r"bearer\s+[A-Za-z0-9._-]+|cookie[\"']?\s*[:=]|password[\"']?\s*[:=]|"
    r"secret[\"']?\s*[:=]|token[\"']?\s*[:=]|BEGIN [A-Z ]*PRIVATE KEY)"
)
PRIVATE_PATH_RE = re.compile(
    r"(?i)([A-Z]:\\|\\\\wsl\.localhost\\|(?<![A-Za-z0-9._~:/-])(?:/home/|/Users/|/mnt/[cd]/))"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def load_json(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: expected JSON object")
        rows.append(payload)
    return rows


def text_value(value: Any, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def stable_hash(value: Any, length: int = 24) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def canonicalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "invalid-url:" + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = (parts.path or "/").lower()
    if path != "/":
        path = path.rstrip("/") + "/"
    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def url_key_hash(url: str) -> str:
    canonical = canonicalize_url(url)
    if not canonical:
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def platform_from_url(url: str, fallback: str = "") -> str:
    host = urlparse(url).netloc.lower()
    if "instagram.com" in host:
        return "instagram"
    if "soundcloud.com" in host:
        return "soundcloud"
    if "bandcamp.com" in host:
        return "bandcamp"
    if "mixcloud.com" in host:
        return "mixcloud"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "bilibili.com" in host:
        return "bilibili"
    if "spotify.com" in host:
        return "spotify"
    if "beatport.com" in host:
        return "beatport"
    if "ra.co" in host or "residentadvisor" in host:
        return "resident_advisor"
    if "facebook.com" in host:
        return "facebook"
    if "weibo.com" in host:
        return "weibo"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xhs"
    return text_value(fallback, 80) or "other"


def build_writer_row(candidate: dict[str, Any], generated_at: str) -> dict[str, Any]:
    eid = text_value(candidate.get("entity_search_id"), 120)
    url = text_value(candidate.get("safe_url"), 2000)
    platform = platform_from_url(url, text_value(candidate.get("platform"), 80))
    outlink_id = stable_hash({"eid": eid, "outlink_url": canonicalize_url(url), "source": "openclaw_db2_external_link"}, 16)
    return {
        "outlink_id": outlink_id,
        "eid": eid,
        "profile_id": None,
        "outlink_url": url,
        "outlink_platform": platform,
        "entity_name": text_value(candidate.get("entity_name"), 180),
        "source_layer": "openclaw_db2_external_link_l5",
        "source_profile_url": "",
        "profile_platform": "",
        "discovered_at": generated_at,
        "source": "openclaw_db2_external_link_projection",
    }


def build_writer_event(candidate: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "op": "insert_outlink",
        "mode": "ignore",
        **build_writer_row(candidate, generated_at),
    }


def iter_string_values(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        values: list[str] = []
        for child in payload.values():
            values.extend(iter_string_values(child))
        return values
    if isinstance(payload, list):
        values = []
        for child in payload:
            values.extend(iter_string_values(child))
        return values
    if isinstance(payload, str):
        return [payload]
    return []


def leak_findings(payload: Any) -> list[dict[str, str]]:
    text = "\n".join(iter_string_values(payload))
    findings: list[dict[str, str]] = []
    for name, pattern in [("secret_like", SECRET_RE), ("private_local_path", PRIVATE_PATH_RE)]:
        for match in pattern.finditer(text):
            findings.append({"kind": name, "sample": match.group(0)[:48]})
            if len(findings) >= 20:
                return findings
    return findings


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(str(path), timeout=10)
        conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
    return row is not None


def collect_target_audit(target_db: Path | None, candidates: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    if target_db is None:
        return {"audit_bound": False, "target_db": "", "error": "target_db_not_provided"}
    try:
        conn = connect_readonly(target_db)
    except Exception as exc:  # noqa: BLE001 - this is a report-only gate.
        return {"audit_bound": False, "target_db": str(target_db), "error": f"{type(exc).__name__}: {exc}"}
    try:
        if not table_exists(conn, "dj_outlinks"):
            return {"audit_bound": True, "target_db": str(target_db), "schema_ok": False, "error": "missing_table:dj_outlinks"}
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(dj_outlinks)").fetchall()}
        missing = sorted(EXPECTED_DJ_OUTLINK_COLUMNS - columns)
        rows = conn.execute("SELECT outlink_id, eid, outlink_url FROM dj_outlinks").fetchall()
        by_hash_any: Counter[str] = Counter()
        by_eid_hash: Counter[tuple[str, str]] = Counter()
        by_outlink_id: Counter[str] = Counter()
        for row in rows:
            hashed = url_key_hash(row["outlink_url"] or "")
            if hashed:
                by_hash_any[hashed] += 1
                by_eid_hash[(row["eid"] or "", hashed)] += 1
            by_outlink_id[row["outlink_id"] or ""] += 1

        candidate_audit: list[dict[str, Any]] = []
        same_eid_url = 0
        same_url_any = 0
        same_outlink_id = 0
        for candidate in candidates:
            event = build_writer_event(candidate, generated_at)
            hashed = url_key_hash(event["outlink_url"])
            eid = event["eid"]
            audit_row = {
                "projection_candidate_id": candidate["projection_candidate_id"],
                "eid": eid,
                "outlink_id": event["outlink_id"],
                "source_url_hash": candidate["source_url_hash"],
                "computed_url_key_hash": hashed,
                "same_eid_url_existing_rows": int(by_eid_hash[(eid, hashed)]),
                "same_url_any_eid_existing_rows": int(by_hash_any[hashed]),
                "deterministic_outlink_id_existing_rows": int(by_outlink_id[event["outlink_id"]]),
            }
            same_eid_url += audit_row["same_eid_url_existing_rows"]
            same_url_any += audit_row["same_url_any_eid_existing_rows"]
            same_outlink_id += audit_row["deterministic_outlink_id_existing_rows"]
            candidate_audit.append(audit_row)

        return {
            "audit_bound": True,
            "target_db": str(target_db),
            "schema_ok": not missing,
            "missing_columns": missing,
            "candidate_rows": len(candidates),
            "live_dj_outlinks_rows": len(rows),
            "same_eid_url_existing_rows": same_eid_url,
            "same_url_any_eid_existing_rows": same_url_any,
            "deterministic_outlink_id_existing_rows": same_outlink_id,
            "candidate_conflict_rows": sum(
                1
                for row in candidate_audit
                if row["same_eid_url_existing_rows"]
                or row["same_url_any_eid_existing_rows"]
                or row["deterministic_outlink_id_existing_rows"]
            ),
            "candidate_audit_rows": candidate_audit,
            "sample_conflicts": [
                row
                for row in candidate_audit
                if row["same_eid_url_existing_rows"]
                or row["same_url_any_eid_existing_rows"]
                or row["deterministic_outlink_id_existing_rows"]
            ][:20],
        }
    finally:
        conn.close()


def load_or_collect_target_audit(path: Path | None, target_db: Path | None, candidates: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    existing = load_json(path)
    if existing is not None:
        return existing
    return collect_target_audit(target_db, candidates, generated_at)


def status_writer_backlog(status: dict[str, Any] | None) -> int | None:
    if not isinstance(status, dict):
        return None
    writer = status.get("writer")
    if isinstance(writer, dict):
        try:
            return int(writer.get("spool_backlog"))
        except (TypeError, ValueError):
            return None
    return None


def health_rogue_count(health: dict[str, Any] | None) -> int | None:
    if not isinstance(health, dict):
        return None
    rogue = health.get("rogue_legacy_workers")
    if not isinstance(rogue, dict):
        return None
    workers = rogue.get("workers")
    return len(workers) if isinstance(workers, list) else None


def gate_checks(
    *,
    prewrite_packet: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    rollback_contracts: list[dict[str, Any]],
    readback_contracts: list[dict[str, Any]],
    status: dict[str, Any] | None,
    health: dict[str, Any] | None,
    target_audit: dict[str, Any],
    controller_open_requested: bool,
    release_live_spool: bool,
    confirm_token: str,
    findings: list[dict[str, str]],
    allow_candidate_subset: bool = False,
) -> tuple[dict[str, bool], list[str]]:
    writer_backlog = status_writer_backlog(status)
    stop_gates = health.get("stop_gates") if isinstance(health, dict) else None
    if not isinstance(stop_gates, list):
        stop_gates = []
    rogue_count = health_rogue_count(health)
    lock_probe = health.get("lock_probe") if isinstance(health, dict) else None
    lock_holder_signal = bool(lock_probe.get("holder_signal")) if isinstance(lock_probe, dict) else False
    prewrite_summary = prewrite_packet.get("summary") if isinstance(prewrite_packet, dict) else {}
    prewrite_candidate_rows = int(prewrite_summary.get("unique_prewrite_candidate_rows") or -1)
    target_conflicts = int(target_audit.get("candidate_conflict_rows") or 0)
    candidate_count_ok = prewrite_candidate_rows == len(candidates)
    if allow_candidate_subset:
        candidate_count_ok = 0 < len(candidates) <= prewrite_candidate_rows
    checks = {
        "prewrite_packet_ready": bool(
            isinstance(prewrite_packet, dict)
            and prewrite_packet.get("decision") == "db2_external_link_projection_prewrite_packet_ready_report_only"
        ),
        "candidate_rows_present": len(candidates) > 0,
        "candidate_count_matches_prewrite": candidate_count_ok,
        "rollback_contracts_present": len(rollback_contracts) == len(candidates),
        "postwrite_readback_contracts_present": len(readback_contracts) == len(candidates),
        "target_audit_bound": bool(target_audit.get("audit_bound")),
        "target_schema_ok": bool(target_audit.get("schema_ok")),
        "target_conflict_free": target_conflicts == 0,
        "status_bound": isinstance(status, dict),
        "live_db_integrity_ok": isinstance(status, dict) and status.get("integrity") == "ok",
        "writer_spool_backlog_zero": writer_backlog == 0,
        "health_bound": isinstance(health, dict),
        "no_health_stop_gates": not stop_gates,
        "no_lock_holder_signal": not lock_holder_signal,
        "no_rogue_legacy_workers": rogue_count == 0,
        "controller_open_requested": controller_open_requested,
        "confirm_token_verified": confirm_token == REQUIRED_CONFIRM_TOKEN,
        "live_spool_delivery_requested": release_live_spool,
        "leak_scan_clean": len(findings) == 0,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    for gate in stop_gates:
        blockers.append(f"db2ctl_health_stop_gate:{gate}")
    if lock_holder_signal:
        blockers.append("db2_lock_holder_signal_present")
    if rogue_count:
        blockers.append(f"rogue_legacy_worker_count:{rogue_count}")
    if target_conflicts:
        blockers.append(f"target_conflict_rows:{target_conflicts}")
    return checks, sorted(set(blockers))


def build_work_orders(candidates: list[dict[str, Any]], generated_at: str, execution_allowed: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    work_orders: list[dict[str, Any]] = []
    snapshot_orders: list[dict[str, Any]] = []
    writer_events: list[dict[str, Any]] = []
    for candidate in candidates:
        event = build_writer_event(candidate, generated_at)
        writer_events.append(event)
        selector = {
            "table": "dj_outlinks",
            "eid": event["eid"],
            "outlink_url_hash": url_key_hash(event["outlink_url"]),
            "outlink_id": event["outlink_id"],
        }
        snapshot_orders.append(
            {
                "schema_version": SCHEMA_VERSION + ".prewrite_snapshot_work_order",
                "projection_candidate_id": candidate["projection_candidate_id"],
                "selector": selector,
                "snapshot_required_before_live_spool_delivery": True,
                "db2_write_allowed_now": False,
            }
        )
        work_orders.append(
            {
                "schema_version": SCHEMA_VERSION + ".execution_work_order",
                "projection_candidate_id": candidate["projection_candidate_id"],
                "source_prewrite_candidate": candidate["projection_candidate_id"],
                "writer_event_preview": event,
                "prewrite_snapshot_selector": selector,
                "rollback_contract_required": True,
                "postwrite_readback_required": True,
                "write_execution_allowed_now": execution_allowed,
                "live_db2_spool_delivery_allowed_now": execution_allowed,
            }
        )
    return work_orders, snapshot_orders, writer_events


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DB2 External Link Projection Execution Gate 20260604",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Controller open requested: `{report['controller']['open_requested']}`",
        f"- Execute allowed now: `{report['execution_gate']['execute_allowed_now']}`",
        f"- Candidate rows: `{summary['candidate_rows']}`",
        f"- Work orders: `{summary['execution_work_order_rows']}`",
        f"- Writer event preview rows: `{summary['writer_event_preview_rows']}`",
        f"- Target conflict rows: `{summary['target_conflict_rows']}`",
        f"- Writer spool backlog: `{summary['writer_spool_backlog']}`",
        f"- Rogue legacy workers: `{summary['rogue_legacy_worker_count']}`",
        f"- Leak findings: `{summary['leak_finding_count']}`",
        "",
        "## Blockers",
        "",
    ]
    for blocker in report["execution_gate"]["blockers"]:
        lines.append(f"- `{blocker}`")
    lines.extend(["", "## Artifacts", ""])
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Boundary", ""])
    for key, value in report["safety"].items():
        if key != "leak_findings":
            lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def build_gate(
    *,
    prewrite_packet_path: Path,
    candidates_path: Path,
    rollback_contracts_path: Path,
    readback_contracts_path: Path,
    out_dir: Path,
    scorecard_path: Path,
    status_json: Path | None = None,
    health_json: Path | None = None,
    existing_data_json: Path | None = None,
    target_audit_json: Path | None = None,
    target_db: Path | None = None,
    controller_open_requested: bool = False,
    release_live_spool: bool = False,
    confirm_token: str = "",
    allow_candidate_subset: bool = False,
) -> dict[str, Any]:
    generated_at = now_iso()
    prewrite_packet = load_json(prewrite_packet_path)
    candidates = read_jsonl(candidates_path)
    rollback_contracts = read_jsonl(rollback_contracts_path)
    readback_contracts = read_jsonl(readback_contracts_path)
    status = load_json(status_json)
    health = load_json(health_json)
    existing_data = load_json(existing_data_json)
    target_audit = load_or_collect_target_audit(target_audit_json, target_db, candidates, generated_at)

    preliminary_findings = leak_findings({"candidates": candidates})
    checks, blockers = gate_checks(
        prewrite_packet=prewrite_packet,
        candidates=candidates,
        rollback_contracts=rollback_contracts,
        readback_contracts=readback_contracts,
        status=status,
        health=health,
        target_audit=target_audit,
        controller_open_requested=controller_open_requested,
        release_live_spool=release_live_spool,
        confirm_token=confirm_token,
        findings=preliminary_findings,
        allow_candidate_subset=allow_candidate_subset,
    )
    execution_allowed = all(checks.values())
    work_orders, snapshot_orders, writer_events = build_work_orders(candidates, generated_at, execution_allowed)
    final_findings = leak_findings({"work_orders": work_orders, "snapshot_orders": snapshot_orders, "writer_events": writer_events})
    if final_findings:
        execution_allowed = False
        checks["leak_scan_clean"] = False
        blockers = sorted(set(blockers + ["leak_scan_clean"]))
    findings = preliminary_findings + final_findings

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "db2_external_link_projection_execution_gate.json"
    work_orders_path = out_dir / "db2_external_link_projection_execution_work_orders.jsonl"
    snapshot_path = out_dir / "db2_external_link_projection_prewrite_snapshot_work_orders.jsonl"
    writer_preview_path = out_dir / "db2_writer_release_spool_preview" / "incoming" / "db2_external_link_projection_execution_events.jsonl"
    delivery_manifest_path = out_dir / "db2_external_link_projection_live_spool_delivery_manifest.json"

    write_jsonl(work_orders_path, work_orders)
    write_jsonl(snapshot_path, snapshot_orders)
    write_jsonl(writer_preview_path, writer_events)

    writer_backlog = status_writer_backlog(status)
    rogue_count = health_rogue_count(health)
    target_conflicts = int(target_audit.get("candidate_conflict_rows") or 0)
    summary = {
        "candidate_rows": len(candidates),
        "execution_work_order_rows": len(work_orders),
        "prewrite_snapshot_work_order_rows": len(snapshot_orders),
        "writer_event_preview_rows": len(writer_events),
        "target_conflict_rows": target_conflicts,
        "target_same_eid_url_existing_rows": int(target_audit.get("same_eid_url_existing_rows") or 0),
        "target_same_url_any_eid_existing_rows": int(target_audit.get("same_url_any_eid_existing_rows") or 0),
        "writer_spool_backlog": writer_backlog,
        "rogue_legacy_worker_count": rogue_count,
        "leak_finding_count": len(findings),
        "writer_events_by_platform": dict(Counter(event["outlink_platform"] for event in writer_events).most_common()),
    }
    delivery_manifest = {
        "schema_version": SCHEMA_VERSION + ".live_spool_delivery_manifest",
        "generated_at": generated_at,
        "execute_allowed_now": execution_allowed,
        "live_spool_delivery_requested": release_live_spool,
        "live_spool_delivery_performed": False,
        "source_report_local_spool_preview": rel_path(writer_preview_path),
        "expected_live_spool_dir": "/home/pc/swarm_data/write_spool/incoming",
        "event_rows": len(writer_events),
        "blockers": blockers,
    }
    write_json(delivery_manifest_path, delivery_manifest)

    decision = (
        "db2_external_link_projection_execution_gate_released_report_local_no_delivery"
        if execution_allowed
        else "db2_external_link_projection_execution_gate_blocked_report_only"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "controller": {
            "open_requested": controller_open_requested,
            "confirm_token_required": REQUIRED_CONFIRM_TOKEN,
            "confirm_token_verified": confirm_token == REQUIRED_CONFIRM_TOKEN,
            "live_spool_delivery_requested": release_live_spool,
            "allow_candidate_subset": allow_candidate_subset,
        },
        "inputs": {
            "prewrite_packet": rel_path(prewrite_packet_path),
            "prewrite_candidates": rel_path(candidates_path),
            "status_json": rel_path(status_json) if status_json else "",
            "health_json": rel_path(health_json) if health_json else "",
            "existing_data_json": rel_path(existing_data_json) if existing_data_json else "",
            "target_audit_json": rel_path(target_audit_json) if target_audit_json else "",
            "target_db": str(target_db or ""),
        },
        "artifacts": {
            "report_json": rel_path(report_path),
            "scorecard": rel_path(scorecard_path),
            "execution_work_orders_jsonl": rel_path(work_orders_path),
            "prewrite_snapshot_work_orders_jsonl": rel_path(snapshot_path),
            "report_local_writer_spool_preview_jsonl": rel_path(writer_preview_path),
            "live_spool_delivery_manifest": rel_path(delivery_manifest_path),
        },
        "summary": summary,
        "target_audit": target_audit,
        "existing_data_audit": existing_data or {},
        "execution_gate": {
            "checks": checks,
            "blockers": blockers,
            "execute_allowed_now": execution_allowed,
            "live_spool_delivery_performed": False,
        },
        "safety": {
            "report_only": True,
            "db2_mutation": False,
            "live_db2_spool_delivery": False,
            "network_fetch": False,
            "cookie_token_secret_read": False,
            "secret_values_printed": False,
            "leak_findings": findings,
        },
    }
    write_json(report_path, report)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prewrite-packet", type=Path, default=DEFAULT_PREWRITE_PACKET)
    parser.add_argument("--prewrite-candidates", type=Path, default=DEFAULT_PREWRITE_CANDIDATES)
    parser.add_argument("--rollback-contracts", type=Path, default=DEFAULT_ROLLBACK_CONTRACTS)
    parser.add_argument("--readback-contracts", type=Path, default=DEFAULT_READBACK_CONTRACTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--status-json", type=Path)
    parser.add_argument("--health-json", type=Path)
    parser.add_argument("--existing-data-json", type=Path)
    parser.add_argument("--target-audit-json", type=Path)
    parser.add_argument("--target-db", type=Path)
    parser.add_argument("--controller-open-requested", action="store_true")
    parser.add_argument("--release-live-spool", action="store_true")
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--allow-candidate-subset", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_gate(
        prewrite_packet_path=args.prewrite_packet,
        candidates_path=args.prewrite_candidates,
        rollback_contracts_path=args.rollback_contracts,
        readback_contracts_path=args.readback_contracts,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        status_json=args.status_json,
        health_json=args.health_json,
        existing_data_json=args.existing_data_json,
        target_audit_json=args.target_audit_json,
        target_db=args.target_db,
        controller_open_requested=args.controller_open_requested,
        release_live_spool=args.release_live_spool,
        confirm_token=args.confirm_token,
        allow_candidate_subset=args.allow_candidate_subset,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "execute_allowed_now": report["execution_gate"]["execute_allowed_now"],
                "summary": report["summary"],
                "blockers": report["execution_gate"]["blockers"],
                "artifacts": report["artifacts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["decision"] == "db2_external_link_projection_execution_gate_released_report_local_no_delivery" else 1


if __name__ == "__main__":
    raise SystemExit(main())
