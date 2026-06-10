#!/usr/bin/env python3
"""Build a report-only Atlas serving production execution packet.

The packet turns a locally verified public-safe atlas_serving.sqlite candidate
into an explicit promote/verify/rollback checklist. It does not copy SQLite
files, update serving pointers, deploy services, or write Neo4j/Qdrant.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CANDIDATE_DB = Path(
    "reports/atlas_serving_field_repair_fullcomplete_strict_20260523-1658/atlas_serving.sqlite"
)
DEFAULT_MANIFEST = Path("reports/atlas_serving_field_repair_fullcomplete_strict_20260523-1658/manifest.json")
DEFAULT_PREFLIGHT = Path(
    "reports/atlas_serving_field_repair_fullcomplete_strict_20260523-1658/preflight_vs_participant_v3/promotion_preflight.json"
)
DEFAULT_API_SMOKE = Path("reports/atlas_serving_field_repair_fullcomplete_strict_20260523-1658/api_smoke/api_smoke.json")
DEFAULT_BROWSER_SMOKE = Path(
    "reports/atlas_serving_field_repair_fullcomplete_strict_20260523-1658/api_smoke/browser_smoke.json"
)
DEFAULT_OUT_DIR = Path("reports/atlas_serving_production_execution_packet_20260523")
SCHEMA_VERSION = "atlas_serving_production_execution_packet.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas serving production execution packet: {path}")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check(name: str, ok: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def all_check_values_true(payload: dict[str, Any]) -> bool:
    checks = payload.get("checks")
    if isinstance(checks, dict):
        return all(bool(value) for value in checks.values())
    return bool(payload.get("ok"))


def preflight_failed_checks(preflight: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    for item in preflight.get("checks") or []:
        if isinstance(item, dict) and not item.get("ok"):
            failed.append(str(item.get("name") or "unnamed_check"))
    return failed


def build_packet(
    *,
    candidate_db: Path,
    manifest_path: Path,
    preflight_path: Path,
    api_smoke_path: Path,
    browser_smoke_path: Path,
    out_dir: Path,
    public_target: str,
) -> dict[str, Any]:
    for label, path in {
        "candidate_db": candidate_db,
        "manifest": manifest_path,
        "preflight": preflight_path,
        "api_smoke": api_smoke_path,
        "browser_smoke": browser_smoke_path,
        "out_dir": out_dir,
    }.items():
        reject_d_path(path, label)

    manifest = read_json(manifest_path)
    preflight = read_json(preflight_path)
    api_smoke = read_json(api_smoke_path)
    browser_smoke = read_json(browser_smoke_path)
    failed_preflight = preflight_failed_checks(preflight)
    candidate_exists = candidate_db.exists() and candidate_db.is_file()
    candidate_sha256 = sha256_file(candidate_db) if candidate_exists else ""
    gates = [
        check("candidate_db_exists", candidate_exists, str(candidate_db)),
        check("manifest_deployable_public", bool((manifest.get("safety") or {}).get("deployable_public")), manifest_path.as_posix()),
        check("manifest_public_rollup_only", bool((manifest.get("safety") or {}).get("serving_db_is_public_rollup_only")), manifest_path.as_posix()),
        check(
            "preflight_passed_local_only",
            preflight.get("decision") == "promotion_preflight_passed_local_only" and not failed_preflight,
            {"decision": preflight.get("decision"), "failed_checks": failed_preflight},
        ),
        check("api_smoke_ok", bool(api_smoke.get("ok")) and all_check_values_true(api_smoke), api_smoke_path.as_posix()),
        check(
            "browser_smoke_ok",
            bool(browser_smoke.get("ok")) and all_check_values_true(browser_smoke),
            browser_smoke_path.as_posix(),
        ),
    ]
    gate_ok = all(item["ok"] for item in gates)
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_serving_production_execution_packet_ready_report_only"
        if gate_ok
        else "atlas_serving_production_execution_packet_blocked",
        "public_target": public_target,
        "candidate": {
            "path": str(candidate_db),
            "size_bytes": candidate_db.stat().st_size if candidate_exists else 0,
            "sha256": candidate_sha256,
            "counts": counts,
            "field_missing_counts": manifest.get("field_missing_counts") or {},
        },
        "input_evidence": {
            "manifest": str(manifest_path),
            "preflight": str(preflight_path),
            "api_smoke": str(api_smoke_path),
            "browser_smoke": str(browser_smoke_path),
        },
        "gates": gates,
        "execution_sequence": [
            "Capture current production pointer/env/artifact identity and save it as rollback_previous_pointer.json.",
            "Stage the candidate as a new immutable atlas_serving.sqlite artifact without replacing the active pointer.",
            "Run size, sha256, manifest, preflight, and local read-only API smoke against the staged artifact.",
            "Switch only the intended public serving pointer/env to the staged artifact.",
            "Restart or reload only the intended Atlas public-serving process.",
            "Run remote-effective health, manifest, search, profile, graph-window, anti-scrape/session, and honey-endpoint checks.",
            "Record post-write verification and the active artifact sha256 separately from local readiness.",
        ],
        "rollback_sequence": [
            "Restore the captured previous pointer/env/artifact identity.",
            "Restart or reload only the intended Atlas public-serving process.",
            "Rerun remote health, manifest, and representative search/profile/graph checks against the restored artifact.",
            "Keep the failed promoted artifact quarantined for audit; do not delete evidence during the incident window.",
        ],
        "post_write_verification": {
            "required_remote_checks": [
                "GET /healthz",
                "GET /api/v1/stage7/manifest must show serving_read_model and expected counts.",
                "GET /api/v1/stage7/search?q=MaFoL",
                "GET /api/v1/stage7/graph/profile?q=DaRou",
                "GET /api/v1/stage7/graph/seed?q=SHCR",
                "GET /atlas must render the Atlas title and serving counts.",
                "Honey endpoints such as /atlas.sqlite and /api/v1/stage7/export must not expose bulk data.",
            ],
            "must_record": [
                "previous pointer identity",
                "new pointer identity",
                "candidate sha256",
                "remote smoke results",
                "rollback result or rollback-not-needed decision",
            ],
        },
        "safety": {
            "report_only": True,
            "candidate_copied": False,
            "serving_pointer_update_executed": False,
            "cloudrun_deploy_executed": False,
            "vps_deploy_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_production_write_executed": False,
            "mini_program_upload_executed": False,
            "memory_write_executed": False,
            "secret_read_executed": False,
            "paid_api_used": False,
            "d_root_scan_executed": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "atlas_serving_production_execution_packet.json", packet)
    write_text(out_dir / "atlas_serving_production_execution_packet.md", markdown_report(packet))
    return packet


def markdown_report(packet: dict[str, Any]) -> str:
    candidate = packet["candidate"]
    lines = [
        "# Atlas Serving Production Execution Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- public_target: `{packet['public_target']}`",
        f"- candidate: `{candidate['path']}`",
        f"- candidate_sha256: `{candidate['sha256']}`",
        f"- candidate_size_bytes: `{candidate['size_bytes']}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in sorted((candidate.get("counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Gates", ""])
    for item in packet["gates"]:
        status = "PASS" if item["ok"] else "FAIL"
        lines.append(f"- `{status}` {item['name']}: `{json.dumps(item['detail'], ensure_ascii=False)}`")
    lines.extend(["", "## Execution Sequence", ""])
    for index, item in enumerate(packet["execution_sequence"], start=1):
        lines.append(f"{index}. {item}")
    lines.extend(["", "## Rollback Sequence", ""])
    for index, item in enumerate(packet["rollback_sequence"], start=1):
        lines.append(f"{index}. {item}")
    lines.extend(["", "## Post-Write Verification", ""])
    for item in packet["post_write_verification"]["required_remote_checks"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Boundary", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--api-smoke", type=Path, default=DEFAULT_API_SMOKE)
    parser.add_argument("--browser-smoke", type=Path, default=DEFAULT_BROWSER_SMOKE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--public-target", default="atlas.huaidj.club public Atlas serving surface")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(
        candidate_db=resolve_repo_path(args.candidate_db),
        manifest_path=resolve_repo_path(args.manifest),
        preflight_path=resolve_repo_path(args.preflight),
        api_smoke_path=resolve_repo_path(args.api_smoke),
        browser_smoke_path=resolve_repo_path(args.browser_smoke),
        out_dir=resolve_repo_path(args.out_dir),
        public_target=args.public_target,
    )
    print(
        json.dumps(
            {
                "decision": packet["decision"],
                "candidate": packet["candidate"]["path"],
                "failed_gates": [item["name"] for item in packet["gates"] if not item["ok"]],
                "json": str(resolve_repo_path(args.out_dir) / "atlas_serving_production_execution_packet.json"),
                "markdown": str(resolve_repo_path(args.out_dir) / "atlas_serving_production_execution_packet.md"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0 if packet["decision"] == "atlas_serving_production_execution_packet_ready_report_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
