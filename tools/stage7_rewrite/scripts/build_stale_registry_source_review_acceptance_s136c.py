#!/usr/bin/env python3
"""Review S136 source-pack candidates and optionally apply strict freshness writes.

This S136C gate upgrades only review candidates that have:

- fresh source-pack evidence;
- source URL present;
- venue/account proof for the same venue;
- a source address related to the registry address by same street/number or
  same POI anchor; and
- coordinate drift no greater than the taxi-grade threshold.

It never changes address/coordinate fields. Optional writes are limited to
`last_verified_at` and `source_note` with backup, file lock, atomic replace,
and postwrite readback.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "stale_registry_source_review_acceptance_s136c.v1"
DEFAULT_TASKS = (
    STAGE7_ROOT
    / "reports"
    / "stale_registry_source_acquisition_queue_s136_20260601"
    / "stale_registry_source_acquisition_tasks_s136.jsonl"
)
DEFAULT_S132_REPORT = STAGE7_ROOT / "reports" / "db_write_lock_gate_s132_20260601" / "db_write_lock_gate.json"
DEFAULT_REGISTRY = STAGE7_ROOT / "registries" / "weekly_venues_seed.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "stale_registry_source_review_acceptance_s136c_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_STALE_REGISTRY_SOURCE_REVIEW_ACCEPTANCE_S136C_20260601.md"
DEFAULT_FRESH_AFTER = "2026-05-22"
TAXI_GRADE_DRIFT_METERS = 120.0
CITY_SUFFIXES = (
    "_shanghai",
    "_beijing",
    "_chengdu",
    "_kunming",
    "_nanjing",
    "_chongqing",
    "_xian",
    "_xiamen",
    "_shenyang",
    "_shenzhen",
    "_hangzhou",
    "_urumqi",
    "_suzhou",
    "_fuzhou",
    "_nanning",
    "_qingdao",
)
POI_KEYWORDS = ("购物中心", "街区", "文化区", "艺术区", "广场", "大厦", "园区", "公园", "club", "bar")
ADMIN_ONLY_RE = re.compile(r"^(中国)?([\u4e00-\u9fff]{1,8}省)?[\u4e00-\u9fff]{1,8}市[\u4e00-\u9fff]{1,8}(区|县)$")


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def today_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_json(path: Path, payload: Any) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    write_text_atomic(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def first(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    replacements = {
        "臺": "台",
        "號": "号",
        "樓": "楼",
        "層": "层",
        "，": "",
        ",": "",
        "。": "",
        ".": "",
        " ": "",
        "\t": "",
        "\n": "",
        "（": "(",
        "）": ")",
        "-": "",
        "－": "",
        "_": "",
        "·": "",
        "&amp;": "&",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def strip_city_suffix(value: str) -> str:
    text = str(value or "").lower()
    for suffix in CITY_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def longest_common_substring(a: str, b: str) -> str:
    if not a or not b:
        return ""
    previous = [0] * (len(b) + 1)
    best_len = 0
    best_end = 0
    for i, char_a in enumerate(a, 1):
        current = [0] * (len(b) + 1)
        for j, char_b in enumerate(b, 1):
            if char_a == char_b:
                current[j] = previous[j - 1] + 1
                if current[j] > best_len:
                    best_len = current[j]
                    best_end = i
        previous = current
    return a[best_end - best_len : best_end]


def best_significant_anchor(a: str, b: str) -> str:
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    best = ""
    for start in range(len(shorter)):
        for end in range(start + 5, len(shorter) + 1):
            candidate = shorter[start:end]
            if len(candidate) <= len(best) or candidate not in longer:
                continue
            has_digit = bool(re.search(r"\d", candidate))
            has_poi = any(keyword in candidate for keyword in POI_KEYWORDS)
            if not (has_digit or has_poi):
                continue
            if ADMIN_ONLY_RE.match(candidate):
                continue
            best = candidate
    return best


def significant_common_address(registry_address: str, source_address: str) -> tuple[bool, str, str]:
    reg = normalize_text(registry_address)
    src = normalize_text(source_address)
    if not reg or not src:
        return False, "", "missing_address"
    if reg == src:
        return True, src, "normalized_exact"
    if len(src) >= 10 and src in reg:
        return True, src, "source_address_contained_in_registry"
    if len(reg) >= 10 and reg in src:
        return True, reg, "registry_address_contained_in_source"
    anchor = best_significant_anchor(reg, src)
    if len(anchor) >= 5:
        return True, anchor, "significant_common_poi_or_number_anchor"
    common = longest_common_substring(reg, src)
    has_digit = bool(re.search(r"\d", common))
    has_poi = any(keyword in common for keyword in POI_KEYWORDS)
    if len(common) >= 6 and (has_digit or has_poi):
        return True, common, "significant_common_address_anchor"
    return False, common, "address_not_equivalent"


def venue_proof(task: dict[str, Any], hit: dict[str, Any]) -> tuple[bool, str]:
    venue_id = first(task.get("venue_id"))
    canonical = first(task.get("canonical_name"))
    account = first(hit.get("account_key"))
    venue = first(hit.get("venue"))
    title = first(hit.get("title"))
    stripped_id = strip_city_suffix(venue_id)
    norm_account = normalize_text(account)
    norm_id = normalize_text(stripped_id)
    norm_canonical = normalize_text(canonical)
    norm_venue = normalize_text(venue)
    norm_title = normalize_text(title)
    if norm_account and norm_id and (norm_account == norm_id or norm_account in norm_id or norm_id in norm_account):
        return True, "account_key_matches_venue_id"
    if norm_canonical and norm_venue and (norm_canonical in norm_venue or norm_venue in norm_canonical):
        return True, "source_venue_matches_canonical_name"
    if norm_canonical and norm_title and norm_canonical in norm_title:
        return True, "title_mentions_canonical_name"
    return False, "no_same_venue_proof"


def hit_review(task: dict[str, Any], hit: dict[str, Any], *, fresh_after_date: date) -> dict[str, Any]:
    source_date = parse_date(first(hit.get("source_evidence_date"), hit.get("post_date")))
    source_url_present = hit.get("source_url_present") is True
    source_address = first(hit.get("address"))
    registry_address = first((task.get("registry") or {}).get("address"))
    drift = finite_float(hit.get("drift_meters"))
    has_venue_proof, venue_basis = venue_proof(task, hit)
    address_ok, common_anchor, address_basis = significant_common_address(registry_address, source_address)
    drift_ok = drift is not None and drift <= TAXI_GRADE_DRIFT_METERS
    reasons: list[str] = []
    if source_date is None or source_date < fresh_after_date:
        reasons.append("not_fresh_source_evidence")
    if not source_url_present:
        reasons.append("source_url_missing")
    if not has_venue_proof:
        reasons.append("same_venue_proof_missing")
    if not source_address:
        reasons.append("source_address_missing")
    elif not address_ok:
        reasons.append("source_address_not_equivalent_to_registry")
    if drift is None:
        reasons.append("source_coordinate_missing")
    elif not drift_ok:
        reasons.append("source_coordinate_drift_exceeds_120m")
    accepted = not reasons
    return {
        "article_id": first(hit.get("article_id"), hit.get("queue_id")),
        "queue_id": first(hit.get("queue_id")),
        "account_key": first(hit.get("account_key")),
        "title": first(hit.get("title"))[:180],
        "source_evidence_date": source_date.isoformat() if source_date else "",
        "source_url_present": source_url_present,
        "city": first(hit.get("city")),
        "venue": first(hit.get("venue")),
        "source_address": source_address,
        "registry_address": registry_address,
        "source_geo_lng": finite_float(hit.get("geo_lng")),
        "source_geo_lat": finite_float(hit.get("geo_lat")),
        "drift_meters": drift,
        "venue_proof_basis": venue_basis,
        "address_basis": address_basis,
        "address_common_anchor": common_anchor,
        "accepted": accepted,
        "blocking_reasons": reasons,
    }


def review_task(task: dict[str, Any], *, fresh_after_date: date) -> dict[str, Any]:
    if task.get("status") != "needs_source_review_before_write_gate":
        return {
            "task_id": task.get("task_id"),
            "venue_id": task.get("venue_id"),
            "status": "not_source_review_task",
            "accepted": False,
            "hit_reviews": [],
        }
    hits = ((task.get("local_source_pack") or {}).get("hits") or [])
    reviews = [hit_review(task, hit, fresh_after_date=fresh_after_date) for hit in hits]
    accepted_hits = [row for row in reviews if row["accepted"]]
    if accepted_hits:
        status = "ready_for_s136c_registry_freshness_write"
        next_action = "apply S136C guarded registry freshness write or rerun report-only first"
    else:
        reason_counts = Counter(reason for row in reviews for reason in row["blocking_reasons"])
        if reason_counts.get("source_coordinate_missing"):
            status = "blocked_pending_coordinate_or_provider_crosscheck"
            next_action = "run bounded provider/source address coordinate crosscheck before any freshness write"
        elif reason_counts.get("source_coordinate_drift_exceeds_120m") or reason_counts.get("source_address_not_equivalent_to_registry"):
            status = "blocked_pending_address_conflict_resolution"
            next_action = "treat as address conflict; do not refresh registry until provider/current official source resolves venue address"
        else:
            status = "blocked_pending_stronger_source_evidence"
            next_action = "fetch current official source evidence through OpenClaw/exporter lane"
    return {
        "task_id": task.get("task_id"),
        "venue_id": task.get("venue_id"),
        "canonical_name": task.get("canonical_name", ""),
        "city": task.get("city", ""),
        "status": status,
        "accepted": bool(accepted_hits),
        "registry": task.get("registry", {}),
        "accepted_hits": accepted_hits[:6],
        "hit_reviews": reviews,
        "write_allowed_now": False,
        "write_fields_after_gate": ["last_verified_at", "source_note"],
        "preserve_fields": ["address_full", "geo_lng", "geo_lat", "geo_source", "geo_coord_system"],
        "rollback_selector": task.get("rollback_selector", {"venue_id": task.get("venue_id"), "path": "$.venues[*]"}),
        "next_action": next_action,
    }


def s132_contract_ready(s132: dict[str, Any]) -> bool:
    summary = s132.get("summary", {})
    required_controls = set((s132.get("gate_contract") or {}).get("required_controls", []))
    return bool(
        s132.get("decision") == "db_write_lock_gate_ready_report_only"
        and summary.get("all_fixture_scenarios_passed") is True
        and any("backup" in item for item in required_controls)
        and any("readback" in item for item in required_controls)
        and any("rollback" in item for item in required_controls)
    )


class FileLock:
    def __init__(self, path: Path, *, attempts: int = 3, sleep_ms: int = 50) -> None:
        self.path = path
        self.attempts = attempts
        self.sleep_ms = sleep_ms
        self.fd: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.attempts + 1):
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"pid={os.getpid()} acquired_at={now_cst()}\n".encode("utf-8"))
                return self
            except FileExistsError:
                if attempt == self.attempts:
                    raise TimeoutError(f"lock busy after {self.attempts} attempts: {self.path}")
                time.sleep(self.sleep_ms / 1000.0)
        raise TimeoutError(f"lock busy: {self.path}")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def source_note(row: dict[str, Any], *, previous_last_verified_at: str) -> str:
    accepted = row.get("accepted_hits") or []
    article_ids = [first(hit.get("article_id"), hit.get("queue_id")) for hit in accepted]
    article_ids = [value for value in article_ids if value]
    note_ids = ", ".join(article_ids[:3])
    if len(article_ids) > 3:
        note_ids += f", +{len(article_ids) - 3} more"
    anchors = sorted({first(hit.get("address_common_anchor")) for hit in accepted if first(hit.get("address_common_anchor"))})
    anchor_note = "; anchors=" + ", ".join(anchors[:3]) if anchors else ""
    return (
        f"{today_cst()} S136C source-review acceptance: {len(article_ids)} accepted source row(s) "
        f"confirmed same venue address alias and coordinate drift <= {TAXI_GRADE_DRIFT_METERS:.0f}m; "
        f"article_ids={note_ids}{anchor_note}; previous_last_verified_at={previous_last_verified_at or 'empty'}."
    )


def apply_registry_write(*, registry_path: Path, accepted_rows: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    if not accepted_rows:
        return {"applied": False, "reason": "no_s136c_accepted_rows", "write_count": 0}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = out_dir / f"backup_before_stale_registry_source_review_acceptance_s136c_{stamp}.json"
    lock_path = registry_path.with_name(registry_path.name + ".s136c.lock")
    shutil.copy2(registry_path, backup_path)
    accepted_by_id = {first(row.get("venue_id")): row for row in accepted_rows}
    changed_ids: list[str] = []
    with FileLock(lock_path):
        registry = read_json(registry_path)
        for venue in registry.get("venues", []):
            venue_id = first(venue.get("venue_id"))
            row = accepted_by_id.get(venue_id)
            if not row:
                continue
            previous_note = first(venue.get("source_note"))
            previous_last = first(venue.get("last_verified_at"), venue.get("geo_verified_at"))
            note = source_note(row, previous_last_verified_at=previous_last)
            venue["last_verified_at"] = today_cst()
            venue["source_note"] = f"{previous_note} | {note}" if previous_note else note
            changed_ids.append(venue_id)
        write_json(registry_path, registry)

    readback = read_json(registry_path)
    readback_by_id = {first(row.get("venue_id")): row for row in readback.get("venues", [])}
    failed_ids = [
        venue_id
        for venue_id in changed_ids
        if first(readback_by_id.get(venue_id, {}).get("last_verified_at")) != today_cst()
        or "S136C source-review acceptance" not in first(readback_by_id.get(venue_id, {}).get("source_note"))
    ]
    return {
        "applied": True,
        "write_count": len(changed_ids),
        "backup_path": rel_path(backup_path),
        "lock_path": rel_path(lock_path),
        "readback_ok": not failed_ids and len(changed_ids) == len(accepted_rows),
        "changed_venue_ids": changed_ids,
        "failed_readback_venue_ids": failed_ids,
    }


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Stale Registry Source-Review Acceptance S136C",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Source-review tasks inspected: `{summary['source_review_tasks']}`",
        f"- Accepted rows: `{summary['accepted_rows']}`",
        f"- Blocked rows: `{summary['blocked_rows']}`",
        f"- Registry write requested: `{summary['registry_write_requested']}`",
        f"- Registry write applied: `{report['registry_write'].get('applied', False)}`",
        f"- Registry write count: `{report['registry_write'].get('write_count', 0)}`",
        f"- Readback OK: `{report['registry_write'].get('readback_ok', False)}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Boundary", ""])
    lines.append(
        "- Optional registry writes are limited to `last_verified_at` and `source_note`; address, coordinate, coordinate system, and source fields are preserved."
    )
    lines.append(
        "- No DB1/DB2/DB3/SQLite mutation, no release JSON write, no deploy/upload/review, no external crawl, no provider call, no model call, no cookie/token value read."
    )
    lines.extend(["", "## Next", ""])
    if summary["accepted_rows"]:
        lines.append("- Rerun S133, coordinate freshness, and the S136 acquisition queue after any applied write.")
    if summary["blocked_rows"]:
        lines.append("- Continue acquisition for blocked rows using source review, provider crosscheck, or OpenClaw current-source fetch as listed in the row output.")
    return "\n".join(lines) + "\n"


def build_report(
    *,
    tasks_path: Path,
    s132_report_path: Path,
    registry_path: Path,
    out_dir: Path,
    scorecard_path: Path,
    apply_write: bool,
    fresh_after: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = read_jsonl(tasks_path)
    s132 = read_json(s132_report_path)
    fresh_after_date = parse_date(fresh_after)
    if fresh_after_date is None:
        raise ValueError(f"invalid fresh_after: {fresh_after}")
    review_rows = [
        review_task(task, fresh_after_date=fresh_after_date)
        for task in tasks
        if task.get("status") == "needs_source_review_before_write_gate"
    ]
    accepted_rows = [row for row in review_rows if row["accepted"]]
    blocked_rows = [row for row in review_rows if not row["accepted"]]
    findings: list[dict[str, Any]] = []
    if accepted_rows and not s132_contract_ready(s132):
        findings.append({"finding": "s132_lock_contract_not_ready_for_source_review_acceptance"})

    registry_write = {"applied": False, "write_count": 0}
    if apply_write and accepted_rows and not findings:
        registry_write = apply_registry_write(registry_path=registry_path, accepted_rows=accepted_rows, out_dir=out_dir)
        if not registry_write.get("readback_ok"):
            findings.append({"finding": "registry_write_readback_failed", "details": registry_write})
    elif apply_write and findings:
        registry_write = {"applied": False, "write_count": 0, "reason": "findings_blocked_write"}

    status_counts = Counter(row["status"] for row in review_rows)
    if registry_write.get("applied"):
        decision = "stale_registry_source_review_acceptance_registry_write_applied"
    elif accepted_rows:
        decision = "stale_registry_source_review_acceptance_ready_report_only"
    else:
        decision = "stale_registry_source_review_acceptance_no_ready_rows"

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_cst(),
        "decision": decision,
        "inputs": {
            "tasks": rel_path(tasks_path),
            "s132_report": rel_path(s132_report_path),
            "registry": rel_path(registry_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "stale_registry_source_review_acceptance_s136c.json"),
            "rows": rel_path(out_dir / "stale_registry_source_review_acceptance_rows_s136c.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "freshness_policy": {
            "fresh_after": fresh_after,
            "taxi_grade_drift_meters": TAXI_GRADE_DRIFT_METERS,
            "accepted_review_rule": "fresh source URL + same-venue proof + related source/registry address + coordinate drift <= 120m",
        },
        "summary": {
            "source_review_tasks": len(review_rows),
            "accepted_rows": len(accepted_rows),
            "blocked_rows": len(blocked_rows),
            "status_counts": dict(status_counts),
            "registry_write_requested": apply_write,
            "s132_lock_contract_ready": s132_contract_ready(s132),
        },
        "registry_write": registry_write,
        "accepted_venue_ids": [row["venue_id"] for row in accepted_rows],
        "blocked_venue_ids": [row["venue_id"] for row in blocked_rows],
        "boundary": {
            "report_only": not registry_write.get("applied"),
            "registry_mutation": bool(registry_write.get("applied")),
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "sqlite_mutation": False,
            "release_json_mutation": False,
            "deploy_upload_review": False,
            "provider_or_geocode_call": False,
            "external_crawl": False,
            "model_call": False,
            "cookie_values_read": False,
            "token_values_read": False,
            "broad_disk_scan": False,
        },
        "next_safe_action": "rerun S133, coordinate freshness, and S136 acquisition queue after write" if accepted_rows else "continue source/provider acquisition for blocked rows",
        "findings": findings,
        "finding_count": len(findings),
    }
    write_json(out_dir / "stale_registry_source_review_acceptance_s136c.json", report)
    write_jsonl(out_dir / "stale_registry_source_review_acceptance_rows_s136c.jsonl", review_rows)
    write_text_atomic(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--s132-report", type=Path, default=DEFAULT_S132_REPORT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--fresh-after", default=DEFAULT_FRESH_AFTER)
    parser.add_argument("--apply-registry-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        tasks_path=args.tasks,
        s132_report_path=args.s132_report,
        registry_path=args.registry,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        apply_write=args.apply_registry_write,
        fresh_after=args.fresh_after,
    )
    print(json.dumps({"decision": report["decision"], "summary": report["summary"], "registry_write": report["registry_write"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
