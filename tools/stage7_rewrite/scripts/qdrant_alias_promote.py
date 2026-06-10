"""Create or roll back Qdrant aliases for the verified Qwen3 full-staging collections.

Default mode is dry-run. Apply/rollback require an explicit confirmation token.
This script only manages Qwen3 Stage7 aliases; it never touches legacy stella
production aliases, writes points, starts Neo4j, touches production SQLite,
uses paid APIs, or scans D:.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_OUT_DIR = Path("reports/qdrant_alias_promote_qwen3_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
CONFIRM_TOKEN = "ENABLE_QDRANT_ALIAS_PROMOTE"
KINDS = ("article", "entity", "event")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def require_local_qdrant(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for alias promotion: {url}")


def slug_model(model: str) -> str:
    text = model.lower().replace("qwen/", "").replace("-", "_").replace("/", "_")
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")


def collection_name(kind: str, model: str, dim: int, stamp: str) -> str:
    return f"wechat_stage7_{kind}_{slug_model(model)}_{dim}_{stamp}_full_staging"


def alias_name(kind: str, model: str, dim: int) -> str:
    return f"wechat_stage7_{kind}_{slug_model(model)}_{dim}_current"


def qdrant_request(method: str, url: str, **kwargs):
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 60), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed {response.status_code}: {response.text[:500]}")
    return response.json() if response.text else {}


def aliases(qdrant_url: str) -> dict[str, str]:
    data = qdrant_request("GET", f"{qdrant_url.rstrip('/')}/aliases", timeout=30)
    rows = ((data.get("result") or {}).get("aliases") or [])
    return {row["alias_name"]: row["collection_name"] for row in rows}


def collection_info(qdrant_url: str, name: str) -> dict[str, Any]:
    response = requests.get(f"{qdrant_url.rstrip('/')}/collections/{quote(name)}", timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"GET collection {name} failed {response.status_code}: {response.text[:500]}")
    return response.json().get("result") or {}


def build_plan(args: argparse.Namespace, metadata: dict[str, Any]) -> dict[str, Any]:
    model = str(metadata.get("model") or args.model)
    dim = int(metadata.get("dim") or args.dim)
    collections = {kind: collection_name(kind, model, dim, args.stamp) for kind in KINDS}
    alias_map = {kind: alias_name(kind, model, dim) for kind in KINDS}
    expected_counts = {
        "article": int((metadata.get("card_stats") or {}).get("article") or 0),
        "entity": int((metadata.get("card_stats") or {}).get("entity") or 0),
        "event": int((metadata.get("card_stats") or {}).get("event") or 0),
    }
    return {
        "schema_version": "stage7_qdrant_alias_promote_plan.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "qdrant_url": args.qdrant_url,
        "vector_dir": str(args.vector_dir),
        "out_dir": str(args.out_dir),
        "model": model,
        "dim": dim,
        "collections": collections,
        "aliases": alias_map,
        "expected_counts": expected_counts,
        "confirm_token_required_for_writes": CONFIRM_TOKEN,
        "legacy_prod_aliases_untouched": True,
    }


def validate_plan(qdrant_url: str, plan: dict[str, Any], *, allow_replace: bool) -> dict[str, Any]:
    current_aliases = aliases(qdrant_url)
    collection_health = {}
    conflicts = {}
    for kind, collection in plan["collections"].items():
        info = collection_info(qdrant_url, collection)
        optimizer_status = info.get("optimizer_status")
        collection_health[kind] = {
            "status": info.get("status"),
            "optimizer_status": optimizer_status,
            "healthy": info.get("status") == "green" and (optimizer_status == "ok" or optimizer_status is None),
            "points_count": int(info.get("points_count") or 0),
            "expected_count": int(plan["expected_counts"][kind]),
        }
        alias = plan["aliases"][kind]
        existing_target = current_aliases.get(alias)
        if existing_target and existing_target != collection:
            conflicts[alias] = existing_target
    if conflicts and not allow_replace:
        raise RuntimeError(f"alias conflicts require --allow-replace: {json.dumps(conflicts, ensure_ascii=False)}")
    bad = {
        kind: item
        for kind, item in collection_health.items()
        if not item["healthy"] or item["points_count"] != item["expected_count"]
    }
    if bad:
        raise RuntimeError(f"collection health/count check failed: {json.dumps(bad, ensure_ascii=False)}")
    return {"aliases_before": current_aliases, "collection_health": collection_health, "conflicts": conflicts}


def build_actions(plan: dict[str, Any], validation: dict[str, Any], *, allow_replace: bool) -> list[dict[str, Any]]:
    actions = []
    aliases_before = validation["aliases_before"]
    for kind, alias in plan["aliases"].items():
        target = plan["collections"][kind]
        existing = aliases_before.get(alias)
        if existing == target:
            continue
        if existing and allow_replace:
            actions.append({"delete_alias": {"alias_name": alias}})
        actions.append({"create_alias": {"alias_name": alias, "collection_name": target}})
    return actions


def rollback_actions(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"delete_alias": {"alias_name": alias}} for alias in plan["aliases"].values()]


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    plan = report["plan"]
    lines = [
        "# Qdrant Qwen3 Alias Promotion",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{plan['mode']}`",
        f"- applied: `{report['applied']}`",
        f"- rolled_back: `{report['rolled_back']}`",
        f"- qdrant_url: `{plan['qdrant_url']}`",
        "",
        "## Aliases",
        "",
        "| Kind | Alias | Collection | Points |",
        "|---|---|---|---:|",
    ]
    for kind, alias in plan["aliases"].items():
        health = report["validation"]["collection_health"][kind]
        lines.append(f"| `{kind}` | `{alias}` | `{plan['collections'][kind]}` | {health['points_count']} |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Legacy `wechat_prod_*_stella_large_zh_v2_1024_current` aliases were not touched.",
            "- Rollback for this gate is deleting the three `wechat_stage7_*_qwen3_embedding_4b_1024_current` aliases.",
            "- No points, vectors, Neo4j, production SQLite, mem0, graph, OCR/Dajiala, paid API, or D: scan was touched.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    metadata = read_json(args.vector_dir / "metadata.json")
    plan = build_plan(args, metadata)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "qdrant_alias_promote_plan.json", plan)
    validation = validate_plan(args.qdrant_url, plan, allow_replace=args.allow_replace)
    actions = build_actions(plan, validation, allow_replace=args.allow_replace)
    rollback = rollback_actions(plan)

    applied = False
    rolled_back = False
    if args.mode in {"apply", "rollback"} and args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for alias mutations")
    if args.mode == "apply" and actions:
        qdrant_request("POST", f"{args.qdrant_url.rstrip('/')}/collections/aliases", json={"actions": actions}, timeout=60)
        applied = True
    if args.mode == "rollback":
        qdrant_request("POST", f"{args.qdrant_url.rstrip('/')}/collections/aliases", json={"actions": rollback}, timeout=60)
        rolled_back = True

    report = {
        "schema_version": "stage7_qdrant_alias_promote_report.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "plan": plan,
        "validation": validation,
        "actions": actions,
        "rollback_actions": rollback,
        "applied": applied,
        "rolled_back": rolled_back,
        "aliases_after": aliases(args.qdrant_url),
    }
    write_json(args.out_dir / "qdrant_alias_promote_report.json", report)
    write_markdown(args.out_dir / "qdrant_alias_promote_report.md", report)
    print(json.dumps({"ok": True, "applied": applied, "rolled_back": rolled_back, "report": str(args.out_dir / "qdrant_alias_promote_report.json")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "apply", "rollback"], default="dry-run")
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--stamp", default="20260514")
    parser.add_argument("--model", default="Qwen/Qwen3-Embedding-4B")
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--allow-replace", action="store_true")
    parser.add_argument("--confirm-token", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (args.vector_dir / "metadata.json").exists():
        raise SystemExit(f"metadata not found under {args.vector_dir}")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
