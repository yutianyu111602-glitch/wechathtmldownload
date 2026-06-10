"""Promote full Stage8 Qdrant collections to stable read aliases.

This gate is intentionally narrow: it verifies already-built full per-kind
collections, plans alias changes, writes rollback instructions, and only swaps
aliases in explicit apply mode. It never embeds, rewrites vectors, or deletes
collections.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_MODEL_SLUG = "stella_large_zh_v2"
DEFAULT_DIM = 1024
KINDS = ["article", "claim", "entity_identity", "entity_mention", "event", "relation"]
APPLY_CONFIRM_TOKEN = "ENABLE_QDRANT_ALIAS_PROMOTION_93K"


def target_collection(kind: str, target_release_id: str, model_slug: str, dim: int) -> str:
    return f"wechat_prod_{kind}_{model_slug}_{dim}_{target_release_id}_full_staging"


def alias_name(kind: str, model_slug: str, dim: int) -> str:
    return f"wechat_prod_{kind}_{model_slug}_{dim}_current"


def load_expected_counts(report_path: Path | None) -> dict[str, int]:
    if not report_path:
        return {}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for row in data.get("target_collections") or []:
        kind = row.get("kind")
        if kind:
            counts[str(kind)] = int(row.get("points_count") or 0)
    if counts:
        return counts
    for kind, count in (data.get("source_counts_by_kind") or {}).items():
        counts[str(kind)] = int(count)
    return counts


def parse_expected_count(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected count must be KIND=COUNT, got {value!r}")
        kind, count = value.split("=", 1)
        counts[kind.strip()] = int(count.strip())
    return counts


def alias_map(client: Any) -> dict[str, str]:
    response = client.get_aliases()
    aliases = getattr(response, "aliases", None)
    if aliases is None and isinstance(response, dict):
        aliases = response.get("aliases")
    result: dict[str, str] = {}
    for row in aliases or []:
        if isinstance(row, dict):
            alias = row.get("alias_name")
            collection = row.get("collection_name")
        else:
            alias = getattr(row, "alias_name", None)
            collection = getattr(row, "collection_name", None)
        if alias and collection:
            result[str(alias)] = str(collection)
    return result


def vector_size(info: Any) -> int | None:
    try:
        vectors = info.config.params.vectors
    except AttributeError:
        return None
    if isinstance(vectors, dict):
        first = next(iter(vectors.values()), None)
        return int(getattr(first, "size", 0) or 0) if first is not None else None
    size = getattr(vectors, "size", None)
    return int(size) if size is not None else None


def vector_distance(info: Any) -> str:
    try:
        vectors = info.config.params.vectors
    except AttributeError:
        return ""
    distance = getattr(vectors, "distance", "")
    value = getattr(distance, "value", distance)
    return str(value)


def collection_status(info: Any) -> str:
    status = getattr(info, "status", "")
    return str(getattr(status, "value", status))


def collection_row(client: Any, kind: str, collection: str, expected: int | None, dim: int) -> dict[str, Any]:
    exists = bool(client.collection_exists(collection))
    row: dict[str, Any] = {
        "kind": kind,
        "collection": collection,
        "exists": exists,
        "expected_count": expected,
        "points_count": None,
        "status": None,
        "vector_size": None,
        "distance": None,
        "green": False,
        "count_ok": False,
        "vector_ok": False,
    }
    if not exists:
        return row
    info = client.get_collection(collection)
    points_count = int(getattr(info, "points_count", 0) or 0)
    size = vector_size(info)
    row.update(
        {
            "points_count": points_count,
            "status": collection_status(info),
            "vector_size": size,
            "distance": vector_distance(info),
            "green": collection_status(info).lower() == "green",
            "count_ok": expected is None or points_count == expected,
            "vector_ok": size == dim,
        }
    )
    return row


def build_plan(args: argparse.Namespace, client: Any) -> dict[str, Any]:
    expected = load_expected_counts(Path(args.full_builder_report) if args.full_builder_report else None)
    expected.update(parse_expected_count(args.expected_count or []))
    current_aliases = alias_map(client)

    target_rows = []
    alias_actions = []
    rollback_order = []
    blockers = []
    kinds = args.kind or KINDS
    for kind in kinds:
        target = target_collection(kind, args.target_release_id, args.model_slug, args.dim)
        alias = alias_name(kind, args.model_slug, args.dim)
        expected_count = expected.get(kind)
        row = collection_row(client, kind, target, expected_count, args.dim)
        target_rows.append(row)
        if not row["exists"]:
            blockers.append(f"{kind}: target collection missing: {target}")
        if row["exists"] and not row["green"]:
            blockers.append(f"{kind}: target collection not green: {target}")
        if row["exists"] and not row["vector_ok"]:
            blockers.append(f"{kind}: vector dim mismatch: {target} has {row['vector_size']} expected {args.dim}")
        if row["exists"] and not row["count_ok"]:
            blockers.append(
                f"{kind}: point count mismatch: {target} has {row['points_count']} expected {expected_count}"
            )
        if row["exists"] and row["points_count"] == 0:
            blockers.append(f"{kind}: target collection is empty: {target}")

        current = current_aliases.get(alias)
        if current is None:
            action = "create"
            rollback = {"action": "delete_alias", "alias": alias}
        elif current == target:
            action = "noop"
            rollback = {"action": "noop", "alias": alias, "collection": target}
        else:
            action = "replace"
            rollback = {"action": "restore_alias", "alias": alias, "restore_collection": current}
        alias_actions.append(
            {
                "kind": kind,
                "alias": alias,
                "current_collection": current,
                "target_collection": target,
                "action": action,
            }
        )
        rollback_order.insert(0, rollback)

    return {
        "schema_version": "stage8_vector_alias_promotion_gate.v1",
        "mode": args.mode,
        "qdrant_url": args.qdrant_url,
        "target_release_id": args.target_release_id,
        "model_slug": args.model_slug,
        "dim": args.dim,
        "alias_prefix": f"wechat_prod_<kind>_{args.model_slug}_{args.dim}_current",
        "existing_aliases": current_aliases,
        "expected_counts_by_kind": expected,
        "target_collections": target_rows,
        "planned_alias_actions": alias_actions,
        "rollback_order": rollback_order,
        "blockers": blockers,
        "applied": False,
        "applied_alias_actions": [],
        "post_apply_alias_readback": [],
        "ok": not blockers,
    }


def alias_operations(actions: list[dict[str, Any]]) -> list[Any]:
    from qdrant_client import models

    ops: list[Any] = []
    for action in actions:
        alias = action["alias"]
        target = action["target_collection"]
        if action["action"] == "noop":
            continue
        if action["action"] == "replace":
            ops.append(models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias)))
        ops.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(collection_name=target, alias_name=alias)
            )
        )
    return ops


def verify_aliases(client: Any, actions: list[dict[str, Any]], expected: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for action in actions:
        alias = action["alias"]
        kind = action["kind"]
        expected_count = expected.get(kind)
        try:
            count_result = client.count(collection_name=alias, exact=True)
            points_count = int(getattr(count_result, "count", 0) or 0)
            rows.append(
                {
                    "kind": kind,
                    "alias": alias,
                    "target_collection": action["target_collection"],
                    "expected_count": expected_count,
                    "points_count": points_count,
                    "count_ok": expected_count is None or points_count == expected_count,
                    "ok": expected_count is None or points_count == expected_count,
                }
            )
        except Exception as exc:  # pragma: no cover - qdrant/network specific
            rows.append(
                {
                    "kind": kind,
                    "alias": alias,
                    "target_collection": action["target_collection"],
                    "expected_count": expected_count,
                    "points_count": None,
                    "count_ok": False,
                    "ok": False,
                    "error": str(exc),
                }
            )
    return rows


def apply_aliases(args: argparse.Namespace, client: Any, report: dict[str, Any]) -> None:
    if args.confirm_token != APPLY_CONFIRM_TOKEN:
        report["blockers"].append("apply mode requires --confirm-token ENABLE_QDRANT_ALIAS_PROMOTION_93K")
        report["ok"] = False
        return
    if report["blockers"]:
        report["ok"] = False
        return
    ops = alias_operations(report["planned_alias_actions"])
    if ops:
        client.update_collection_aliases(change_aliases_operations=ops, timeout=args.alias_timeout)
    report["applied"] = True
    report["applied_alias_actions"] = [row for row in report["planned_alias_actions"] if row["action"] != "noop"]
    readback = verify_aliases(client, report["planned_alias_actions"], report["expected_counts_by_kind"])
    report["post_apply_alias_readback"] = readback
    if any(not row.get("ok") for row in readback):
        report["blockers"].append("post-apply alias readback failed")
        report["ok"] = False


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage8 Qdrant Alias Promotion Gate",
        "",
        f"- mode: `{report['mode']}`",
        f"- ok: `{report['ok']}`",
        f"- applied: `{report['applied']}`",
        f"- target_release_id: `{report['target_release_id']}`",
        f"- model_slug: `{report['model_slug']}`",
        f"- dim: `{report['dim']}`",
        f"- blockers: `{len(report['blockers'])}`",
        "",
        "## Planned Alias Actions",
        "",
        "| Kind | Alias | Current | Target | Action |",
        "|---|---|---|---|---|",
    ]
    for row in report["planned_alias_actions"]:
        current = row["current_collection"] or ""
        lines.append(
            f"| `{row['kind']}` | `{row['alias']}` | `{current}` | `{row['target_collection']}` | `{row['action']}` |"
        )
    lines.extend(["", "## Target Collections", "", "| Kind | Collection | Points | Expected | Status | Dim |", "|---|---|---:|---:|---|---:|"])
    for row in report["target_collections"]:
        lines.append(
            f"| `{row['kind']}` | `{row['collection']}` | {row['points_count']} | {row['expected_count']} | `{row['status']}` | {row['vector_size']} |"
        )
    if report["post_apply_alias_readback"]:
        lines.extend(["", "## Post Apply Alias Readback", "", "| Kind | Alias | Points | Expected | OK |", "|---|---|---:|---:|---|"])
        for row in report["post_apply_alias_readback"]:
            lines.append(
                f"| `{row['kind']}` | `{row['alias']}` | {row['points_count']} | {row['expected_count']} | `{row['ok']}` |"
            )
    lines.extend(["", "## Rollback Order", "", "```json", json.dumps(report["rollback_order"], ensure_ascii=False, indent=2), "```"])
    if report["blockers"]:
        lines.extend(["", "## Blockers", ""])
        for blocker in report["blockers"]:
            lines.append(f"- {blocker}")
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=args.qdrant_url, timeout=args.alias_timeout)
    report = build_plan(args, client)
    if args.mode == "apply":
        apply_aliases(args, client, report)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "alias_promotion_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_markdown(out_dir / "ALIAS_PROMOTION_REPORT.md", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--target-release-id", required=True)
    parser.add_argument("--model-slug", default=DEFAULT_MODEL_SLUG)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--kind", action="append", choices=KINDS)
    parser.add_argument("--full-builder-report")
    parser.add_argument("--expected-count", action="append")
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--alias-timeout", type=int, default=60)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    report = run(args)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "mode": report["mode"],
                "applied": report["applied"],
                "out_dir": args.out_dir,
                "blockers": report["blockers"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
