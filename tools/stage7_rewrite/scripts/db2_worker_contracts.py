from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_CONTRACT_DIR = Path(__file__).resolve().parents[1] / "db2_weapons" / "contracts"
FORBIDDEN_TEXT = re.compile(r"https?://|(?i:\bD:[\\/]|/mnt/d\b|DDownload|\baidata\b)")
REQUIRED_TOP_LEVEL = {
    "id",
    "version",
    "status",
    "openclaw_role",
    "execution_plane",
    "live_run_allowed",
    "cookie_policy",
    "db_boundary",
    "input_contract",
    "output_contract",
    "dedupe_contract",
    "stop_gates",
    "db2ctl_surface",
}


def contract_path(contract_id: str, contract_dir: Path = DEFAULT_CONTRACT_DIR) -> Path:
    if not re.fullmatch(r"[a-z0-9_]+", contract_id):
        raise ValueError(f"invalid contract id: {contract_id}")
    return contract_dir / f"{contract_id}.contract.json"


def load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validation = validate_contract(payload)
    if not validation["passed"]:
        raise ValueError(f"invalid contract {path}: {validation['errors']}")
    return payload


def validate_contract(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL - set(payload))
    if missing:
        errors.append(f"missing top-level fields: {', '.join(missing)}")

    if payload.get("openclaw_role") != "control_plane_only":
        errors.append("openclaw_role must be control_plane_only")
    if payload.get("execution_plane") != "docker_container_worker":
        errors.append("execution_plane must be docker_container_worker")
    if payload.get("live_run_allowed") is not False:
        errors.append("live_run_allowed must be false for future contracts")

    cookie_policy = payload.get("cookie_policy") or {}
    for field in ("cookies_allowed", "browser_profile_reads_allowed", "token_reads_allowed", "secret_mount_allowed"):
        if cookie_policy.get(field) is not False:
            errors.append(f"cookie_policy.{field} must be false")

    db_boundary = payload.get("db_boundary") or {}
    if db_boundary.get("live_db_mount") != "read_only":
        errors.append("db_boundary.live_db_mount must be read_only")
    if db_boundary.get("live_db_writes_allowed") is not False:
        errors.append("db_boundary.live_db_writes_allowed must be false")

    input_contract = payload.get("input_contract") or {}
    for field in ("raw_url_allowed", "raw_handle_allowed", "raw_cookie_allowed"):
        if input_contract.get(field) is not False:
            errors.append(f"input_contract.{field} must be false")

    output_contract = payload.get("output_contract") or {}
    for field in ("prints_raw_urls", "prints_raw_paths", "prints_raw_eids"):
        if output_contract.get(field) is not False:
            errors.append(f"output_contract.{field} must be false")

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if FORBIDDEN_TEXT.search(text):
        errors.append("contract must not contain raw URLs or D-drive paths")

    surface = payload.get("db2ctl_surface") or {}
    if surface.get("production"):
        errors.append("future contracts must not expose production commands")

    return {"passed": not errors, "errors": errors, "would_write": False, "read_only": True}


def list_contracts(contract_dir: Path = DEFAULT_CONTRACT_DIR) -> dict[str, Any]:
    contracts = []
    for path in sorted(contract_dir.glob("*.contract.json")):
        payload = load_contract(path)
        contracts.append(
            {
                "id": payload["id"],
                "status": payload["status"],
                "openclaw_role": payload["openclaw_role"],
                "execution_plane": payload["execution_plane"],
                "live_run_allowed": payload["live_run_allowed"],
            }
        )
    return {"contracts": contracts, "contract_dir": str(contract_dir), "read_only": True, "would_write": False}


def verify_contracts(contract_dir: Path = DEFAULT_CONTRACT_DIR) -> dict[str, Any]:
    results = []
    errors: list[str] = []
    live_run_allowed = False
    production_commands_exposed = False
    for path in sorted(contract_dir.glob("*.contract.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            validation = validate_contract(payload)
        except Exception as exc:  # pragma: no cover - CLI safety boundary
            payload = {"id": path.stem.removesuffix(".contract")}
            validation = {"passed": False, "errors": [str(exc)], "would_write": False, "read_only": True}
        live_run_allowed = live_run_allowed or payload.get("live_run_allowed") is True
        production_commands_exposed = production_commands_exposed or bool((payload.get("db2ctl_surface") or {}).get("production"))
        result = {
            "id": payload.get("id", path.stem.removesuffix(".contract")),
            "path": str(path),
            "passed": validation["passed"],
            "errors": validation["errors"],
            "read_only": True,
            "would_write": False,
        }
        results.append(result)
        errors.extend(f"{result['id']}: {error}" for error in validation["errors"])
    return {
        "passed": not errors,
        "contract_count": len(results),
        "results": results,
        "errors": errors,
        "contract_dir": str(contract_dir),
        "read_only": True,
        "would_write": False,
        "live_run_allowed": live_run_allowed,
        "production_commands_exposed": production_commands_exposed,
    }


def show_contract(contract_id: str, contract_dir: Path = DEFAULT_CONTRACT_DIR) -> dict[str, Any]:
    path = contract_path(contract_id, contract_dir)
    payload = load_contract(path)
    return {"contract": payload, "contract_path": str(path), "read_only": True, "would_write": False}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read DB2 worker contracts")
    parser.add_argument("--contract-dir", type=Path, default=DEFAULT_CONTRACT_DIR)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    sub.add_parser("verify-all")
    show = sub.add_parser("show")
    show.add_argument("contract_id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.action == "list":
        print(json.dumps(list_contracts(args.contract_dir), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.action == "verify-all":
        print(json.dumps(verify_contracts(args.contract_dir), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.action == "show":
        print(json.dumps(show_contract(args.contract_id, args.contract_dir), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    raise SystemExit(f"unknown action: {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())
