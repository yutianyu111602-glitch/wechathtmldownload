"""Split a Stage7 lane into independent output roots for process-level parallelism."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


DONE_STATUSES = {"done", "done_with_warnings", "failed_final", "skipped"}


@dataclass
class ShardPlan:
    shard_root: Path
    record_count: int
    first_article_uid: str
    last_article_uid: str


def safe_name(name: str) -> str:
    unsafe = '<>:"/\\|?*'
    for ch in unsafe:
        name = name.replace(ch, "_")
    return name.strip(". ")


def article_extract_path(output_root: Path, row: dict[str, Any]) -> Path:
    return (
        output_root
        / "llm_extract"
        / safe_name(str(row.get("source_account") or ""))
        / safe_name(str(row.get("article_id") or ""))
        / "extract.article.v1.json"
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def expand_exclude_roots(roots: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        candidates = [root]
        if root.exists():
            candidates.extend([child for child in sorted(root.iterdir()) if child.is_dir() and (child / "llm_extract").exists()])
        for candidate in candidates:
            key = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if key not in seen:
                seen.add(key)
                expanded.append(candidate)
    return expanded


def load_done_statuses(exclude_roots: list[Path], mode: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for root in exclude_roots:
        db_path = root / "state" / "pipeline.sqlite"
        if not db_path.exists():
            continue
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT article_uid, status FROM article_status WHERE mode = ?",
                (mode,),
            ).fetchall()
        for article_uid, status in rows:
            statuses[str(article_uid)] = str(status)
    return statuses


def has_existing_extract(exclude_roots: list[Path], row: dict[str, Any]) -> bool:
    return any(article_extract_path(root, row).exists() for root in exclude_roots)


def select_remaining(
    source_lane_root: Path,
    mode: str,
    source_manifest: Path | None = None,
    exclude_roots: list[Path] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    roots = expand_exclude_roots([source_lane_root] + list(exclude_roots or []))
    manifest = source_manifest or source_lane_root / "manifests" / "article_manifest.v1.jsonl"
    rows = load_jsonl(manifest)
    statuses = load_done_statuses(roots, mode)
    remaining: list[dict[str, Any]] = []
    skipped_by_status = 0
    skipped_by_extract = 0
    skipped_non_pending = 0
    for row in rows:
        uid = str(row.get("article_uid") or "")
        status = statuses.get(uid, str(row.get("status") or "pending"))
        if status in DONE_STATUSES:
            skipped_by_status += 1
            continue
        if has_existing_extract(roots, row):
            skipped_by_extract += 1
            continue
        if row.get("status") not in ("", None, "pending"):
            skipped_non_pending += 1
            continue
        item = dict(row)
        item["status"] = "pending"
        remaining.append(item)
    stats = {
        "source_total": len(rows),
        "remaining": len(remaining),
        "skipped_by_status": skipped_by_status,
        "skipped_by_extract": skipped_by_extract,
        "skipped_non_pending": skipped_non_pending,
        "exclude_roots": [str(root) for root in roots],
    }
    return remaining, stats


def split_round_robin(rows: list[dict[str, Any]], shard_count: int) -> list[list[dict[str, Any]]]:
    shards = [[] for _ in range(shard_count)]
    for idx, row in enumerate(rows):
        shards[idx % shard_count].append(row)
    return shards


def write_config(source_config: Path, shard_root: Path) -> None:
    raw = yaml.safe_load(source_config.read_text(encoding="utf-8")) or {}
    raw["output_root"] = str(shard_root)
    raw["input_root"] = str(shard_root / "input_from_intake")
    target = shard_root / "config.stage7.yaml"
    target.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_plan_md(path: Path, plan: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Lane Shard Plan",
        "",
        f"- created_at: {plan['created_at']}",
        f"- source_lane_root: {plan['source_lane_root']}",
        f"- mode: {plan['mode']}",
        f"- shard_count: {plan['shard_count']}",
        f"- remaining_records: {plan['remaining_records']}",
        f"- skipped_by_status: {plan['selection_stats']['skipped_by_status']}",
        f"- skipped_by_extract: {plan['selection_stats']['skipped_by_extract']}",
        "",
        "## Shards",
        "",
    ]
    for shard in plan["shards"]:
        lines.extend(
            [
                f"### {shard['name']}",
                f"- root: {shard['root']}",
                f"- records: {shard['records']}",
                f"- first_article_uid: {shard['first_article_uid']}",
                f"- last_article_uid: {shard['last_article_uid']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_shards(
    source_lane_root: Path,
    source_config: Path,
    mode: str,
    out_root: Path,
    shard_count: int,
    exclude_roots: list[Path] | None = None,
) -> dict[str, Any]:
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    remaining, selection_stats = select_remaining(source_lane_root, mode, exclude_roots=exclude_roots)
    shards = split_round_robin(remaining, shard_count)
    out_root.mkdir(parents=True, exist_ok=True)

    shard_plans: list[ShardPlan] = []
    for idx, rows in enumerate(shards):
        shard_root = out_root / f"shard_{idx:02d}"
        for sub in ("manifests", "state", "llm_extract", "graph_candidates", "vectors", "reports", "logs"):
            (shard_root / sub).mkdir(parents=True, exist_ok=True)
        write_jsonl(shard_root / "manifests" / "article_manifest.v1.jsonl", rows)
        write_config(source_config, shard_root)
        shard_plans.append(
            ShardPlan(
                shard_root=shard_root,
                record_count=len(rows),
                first_article_uid=str(rows[0].get("article_uid") or "") if rows else "",
                last_article_uid=str(rows[-1].get("article_uid") or "") if rows else "",
            )
        )

    plan = {
        "created_at": datetime.now().isoformat(),
        "source_lane_root": str(source_lane_root),
        "source_config": str(source_config),
        "mode": mode,
        "shard_count": shard_count,
        "remaining_records": len(remaining),
        "selection_stats": selection_stats,
        "shards": [
            {
                "name": f"shard_{idx:02d}",
                "root": str(item.shard_root),
                "records": item.record_count,
                "first_article_uid": item.first_article_uid,
                "last_article_uid": item.last_article_uid,
            }
            for idx, item in enumerate(shard_plans)
        ],
    }
    (out_root / "SHARD_PLAN.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    write_plan_md(out_root / "SHARD_PLAN.md", plan)

    runner = Path(__file__).with_name("run_stage7_lane_with_evidence.ps1")
    lines = [
        "$ErrorActionPreference = \"Stop\"",
        f"$Mode = \"{mode}\"",
        "",
    ]
    for idx, item in enumerate(shard_plans):
        run_id = f"{mode}_shard_{idx:02d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        lines.extend(
            [
                f"$LaneRoot{idx} = \"{item.shard_root}\"",
                f"$Config{idx} = Join-Path $LaneRoot{idx} \"config.stage7.yaml\"",
                f"$RunId{idx} = \"{run_id}\"",
                f"Start-Process -FilePath \"powershell.exe\" -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','{runner}','-LaneRoot',$LaneRoot{idx},'-Mode',$Mode,'-Config',$Config{idx},'-RunId',$RunId{idx},'-Resume') -WorkingDirectory \"{runner.parent}\" -WindowStyle Hidden",
                "",
            ]
        )
    (out_root / "run_shards.ps1").write_text("\n".join(lines), encoding="utf-8")
    shutil.copy2(source_config, out_root / "source_config.stage7.yaml")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-lane-root", required=True)
    parser.add_argument("--source-config", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--shards", type=int, default=2)
    parser.add_argument("--exclude-root", action="append", default=[])
    args = parser.parse_args()

    plan = build_shards(
        source_lane_root=Path(args.source_lane_root),
        source_config=Path(args.source_config),
        mode=args.mode,
        out_root=Path(args.out_root),
        shard_count=args.shards,
        exclude_roots=[Path(p) for p in args.exclude_root],
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
