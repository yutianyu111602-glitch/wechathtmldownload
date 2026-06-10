#!/usr/bin/env python3
"""Build segmented Stage7 lanes from the 93k release index.

This is a control-plane builder. It reads the bounded release index, writes
isolated Stage7 lane manifests/configs, and emits a runbook. It does not call
the LLM and does not write vector, graph, Qdrant, Neo4j, or PC DB stores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml


DEFAULT_RELEASE_ROOT = Path(r"D:\DDownload\_llm_release_v2")
DEFAULT_INDEX = DEFAULT_RELEASE_ROOT / "index.jsonl"
DEFAULT_OUT_ROOT = Path(
    r"D:\downstream_results\stage7_rewrite\longrun"
    r"\STAGE7_FULL93K_QWEN36_27B_20260508"
)
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


@dataclass(frozen=True)
class ReleaseLane:
    name: str
    description: str
    predicate: Callable[[dict[str, Any]], bool]
    chunking: dict[str, int]
    llm: dict[str, Any]
    priority: int


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def quality(row: dict[str, Any]) -> str:
    return str(row.get("quality_grade") or "").strip().lower()


def estimated_chars(row: dict[str, Any]) -> int:
    # The release index is the fast source of truth for 93k segmentation. The
    # worker still reads the real llm_input.md at runtime.
    main = as_int(row.get("main_content_chars"))
    background = as_int(row.get("background_recall_chars"))
    return main + background


def local_images(row: dict[str, Any]) -> int:
    return as_int(row.get("local_image_count"))


def warning_count(row: dict[str, Any]) -> int:
    return as_int(row.get("warning_count"))


def is_platform_or_empty(row: dict[str, Any]) -> bool:
    title = str(row.get("title") or "").strip()
    main = as_int(row.get("main_content_chars"))
    return title == "微信公众平台" or (main < 80 and local_images(row) == 0)


def lane_defs() -> list[ReleaseLane]:
    return [
        ReleaseLane(
            name="full_ready_short_core",
            description="93k release ready rows under 2500 estimated chars; primary high-throughput lane.",
            predicate=lambda r: quality(r) == "ready" and not is_platform_or_empty(r) and estimated_chars(r) < 2500,
            chunking={"target_chars": 900, "max_chars": 1800, "min_chars": 300, "hard_max_chars": 2400, "overlap_chars": 120},
            llm={"prompt_path": "config/prompt.extract.micro.zh.txt", "temperature": 0.0, "top_p": 0.75, "top_k": 10, "repeat_penalty": 1.05, "max_tokens": 384, "timeout_sec": 180, "concurrency": 1},
            priority=10,
        ),
        ReleaseLane(
            name="full_ready_medium_core",
            description="93k release ready rows from 2500 to 7999 estimated chars; normal article lane.",
            predicate=lambda r: quality(r) == "ready" and not is_platform_or_empty(r) and 2500 <= estimated_chars(r) < 8000,
            chunking={"target_chars": 1000, "max_chars": 2200, "min_chars": 500, "hard_max_chars": 3000, "overlap_chars": 160},
            llm={"prompt_path": "config/prompt.extract.micro.zh.txt", "temperature": 0.0, "top_p": 0.75, "top_k": 10, "repeat_penalty": 1.05, "max_tokens": 512, "timeout_sec": 240, "concurrency": 1},
            priority=20,
        ),
        ReleaseLane(
            name="full_ready_long_safe",
            description="93k release ready rows at 8000 estimated chars and above; safer long-text chunks.",
            predicate=lambda r: quality(r) == "ready" and not is_platform_or_empty(r) and estimated_chars(r) >= 8000,
            chunking={"target_chars": 750, "max_chars": 1400, "min_chars": 350, "hard_max_chars": 1800, "overlap_chars": 120},
            llm={"prompt_path": "config/prompt.extract.micro.zh.txt", "temperature": 0.0, "top_p": 0.70, "top_k": 10, "repeat_penalty": 1.05, "max_tokens": 384, "timeout_sec": 360, "concurrency": 1},
            priority=30,
        ),
        ReleaseLane(
            name="full_review_ocr_salvage",
            description="93k release review rows that still contain text or local images; salvage lane.",
            predicate=lambda r: quality(r) == "review" and not is_platform_or_empty(r) and (estimated_chars(r) >= 500 or local_images(r) > 0),
            chunking={"target_chars": 800, "max_chars": 1600, "min_chars": 250, "hard_max_chars": 2200, "overlap_chars": 120},
            llm={"prompt_path": "config/prompt.extract.micro.zh.txt", "temperature": 0.0, "top_p": 0.70, "top_k": 10, "repeat_penalty": 1.05, "max_tokens": 384, "timeout_sec": 210, "concurrency": 1},
            priority=40,
        ),
        ReleaseLane(
            name="full_low_value_quarantine",
            description="Blocked/platform/near-empty release rows; do not run in the main Qwen lane.",
            predicate=lambda r: quality(r) == "blocked" or is_platform_or_empty(r),
            chunking={"target_chars": 800, "max_chars": 1600, "min_chars": 250, "hard_max_chars": 2200, "overlap_chars": 120},
            llm={"prompt_path": "config/prompt.extract.micro.zh.txt", "temperature": 0.0, "top_p": 0.70, "top_k": 10, "repeat_penalty": 1.05, "max_tokens": 256, "timeout_sec": 180, "concurrency": 1},
            priority=90,
        ),
    ]


def build_record(row: dict[str, Any], release_root: Path, verify_paths: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    account = str(row.get("account") or "").strip()
    token = str(row.get("token") or "").strip()
    markdown_rel = str(row.get("markdown_path") or "").strip()
    if not account or not token:
        return None, "missing_account_or_token"
    if not markdown_rel:
        return None, "missing_markdown_path"

    llm_input_path = release_root / markdown_rel
    article_dir = llm_input_path.parent
    if verify_paths and not llm_input_path.exists():
        return None, "missing_llm_input"

    meta_path = release_root / str(row.get("sidecar_path") or "").strip()
    quality_path = release_root / str(row.get("quality_report_path") or "").strip()
    poster_ocr_path = article_dir / "poster_ocr.json"
    input_chars = estimated_chars(row)
    article_uid = sha1_text(f"release_v2:{account}:{token}:{article_dir}")

    return (
        {
            "article_uid": article_uid,
            "source_account": account,
            "article_id": token,
            "article_dir": str(article_dir),
            "llm_input_path": str(llm_input_path),
            "meta_path": str(article_dir / "meta.json"),
            "poster_ocr_path": str(poster_ocr_path),
            "title": str(row.get("title") or ""),
            "publish_time": str(row.get("post_date") or ""),
            "url": str(row.get("source_url") or ""),
            "input_chars": input_chars,
            "input_sha1": sha1_text(f"{llm_input_path}:{input_chars}:{row.get('processed_at', '')}"),
            "status": "pending",
            "source_kind": "release_v2",
            "source_name": "release_v2_index",
            "quality_grade": quality(row),
            "warning_count": warning_count(row),
            "local_image_count": local_images(row),
            "main_content_chars": as_int(row.get("main_content_chars")),
            "background_recall_chars": as_int(row.get("background_recall_chars")),
            "quality_report_path": str(quality_path) if quality_path.exists() else "",
            "empty_files": [],
            "oversized": input_chars > 500_000,
            "encoding_ok": True,
        },
        None,
    )


def load_base_config() -> dict[str, Any]:
    if not DEFAULT_CONFIG.exists():
        return {}
    return yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8")) or {}


def write_config(path: Path, lane_root: Path, lane: ReleaseLane) -> None:
    raw = load_base_config()
    raw["output_root"] = str(lane_root)
    raw["input_root"] = str(lane_root / "input_from_release_index")
    raw.setdefault("pipeline", {})["description"] = f"full93k_{lane.name}"
    raw.setdefault("chunking", {}).update(lane.chunking)
    raw.setdefault("llm", {}).update(lane.llm)
    raw["llm"]["model"] = raw["llm"].get("model") or "Qwen3.6-27B"
    raw["llm"]["api_style"] = raw["llm"].get("api_style") or "openai_compatible"
    raw["llm"]["no_thinking"] = True
    raw["llm"]["thinking"] = False
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_lane(
    lane: ReleaseLane,
    rows: list[dict[str, Any]],
    out_root: Path,
    release_root: Path,
    verify_paths: bool = False,
) -> dict[str, Any]:
    lane_root = out_root / "lanes" / lane.name
    records = sorted(rows, key=lambda r: (estimated_chars(r), str(r.get("account") or ""), str(r.get("token") or "")))

    built: list[dict[str, Any]] = []
    rejects: list[dict[str, str]] = []
    for row in records:
        record, reason = build_record(row, release_root, verify_paths=verify_paths)
        if record is None:
            rejects.append({"reason": reason or "unknown", "account": str(row.get("account") or ""), "token": str(row.get("token") or "")})
            continue
        built.append(record)

    for sub in ("manifests", "logs", "reports"):
        (lane_root / sub).mkdir(parents=True, exist_ok=True)
    manifest_path = lane_root / "manifests" / "article_manifest.v1.jsonl"
    write_jsonl(manifest_path, built)
    reject_path = lane_root / "manifests" / "rejects.jsonl"
    write_jsonl(reject_path, rejects)
    config_path = lane_root / "config.stage7.yaml"
    write_config(config_path, lane_root, lane)

    chars = [int(r.get("input_chars") or 0) for r in built]
    accounts = Counter(str(r.get("source_account") or "") for r in built)
    quality_counts = Counter(str(r.get("quality_grade") or "") for r in built)
    return {
        "name": lane.name,
        "description": lane.description,
        "priority": lane.priority,
        "root": str(lane_root),
        "manifest": str(manifest_path),
        "config": str(config_path),
        "count": len(built),
        "reject_count": len(rejects),
        "min_chars": min(chars) if chars else 0,
        "max_chars": max(chars) if chars else 0,
        "avg_chars": round(sum(chars) / len(chars), 1) if chars else 0,
        "quality_counts": dict(quality_counts),
        "top_accounts": dict(accounts.most_common(20)),
        "chunking": lane.chunking,
        "llm": lane.llm,
    }


def write_runbook(
    out_root: Path,
    index_path: Path,
    release_root: Path,
    lane_reports: list[dict[str, Any]],
    index_summary: dict[str, Any],
) -> None:
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_index": str(index_path),
        "release_root": str(release_root),
        "out_root": str(out_root),
        "index_summary": index_summary,
        "lanes": lane_reports,
        "policy": {
            "scope": "PC-side Stage7 link/article/OCR/LLM extraction only",
            "no_vector_graph_db_writes": True,
            "segmented_profiles": True,
            "quarantine_is_not_main_lane": True,
            "first_execution_lane": "full_ready_short_core",
        },
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "full93k_lane_plan.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Stage7 Full 93k Qwen Lane Plan",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- source_index: `{index_path}`",
        f"- release_root: `{release_root}`",
        f"- out_root: `{out_root}`",
        "- scope: PC-side WeChat URL extraction only; no vector/Qdrant/Neo4j/PC DB writes.",
        "- principle: split by quality and length; do not use one LLM profile for all 93000 articles.",
        "",
        "## Index Summary",
        "",
        f"- total: `{index_summary['total']}`",
        f"- quality_counts: `{index_summary['quality_counts']}`",
        f"- likely_platform_or_empty: `{index_summary['likely_platform_or_empty']}`",
        "",
        "## Lanes",
        "",
    ]
    for lane in sorted(lane_reports, key=lambda item: item["priority"]):
        lines.extend(
            [
                f"### {lane['name']}",
                "",
                f"- count: `{lane['count']}`",
                f"- rejects: `{lane['reject_count']}`",
                f"- chars: min `{lane['min_chars']}`, avg `{lane['avg_chars']}`, max `{lane['max_chars']}`",
                f"- root: `{lane['root']}`",
                f"- config: `{lane['config']}`",
                f"- chunking: `{lane['chunking']}`",
                f"- llm: `{lane['llm']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Execution Policy",
            "",
            "1. Start `full_ready_short_core` first with 4 process shards and `llm.concurrency=1`.",
            "2. Keep `full_ready_medium_core`, `full_ready_long_safe`, and `full_review_ocr_salvage` queued until the previous lane has GREEN or explained AMBER evidence.",
            "3. Do not run `full_low_value_quarantine` in the main lane; inspect or recapture it separately.",
            "4. Increase shard count only after a timed comparison proves at least 20% extract/min gain with zero new failures.",
            "5. Every shard run must use `scripts\\run_stage7_lane_with_evidence.ps1` so stdout, stderr, GPU samples, status, and quality reports are preserved.",
            "",
        ]
    )
    (out_root / "FULL93K_LANE_PLAN.md").write_text("\n".join(lines), encoding="utf-8")


def select_lane(row: dict[str, Any], lanes: list[ReleaseLane]) -> str:
    for lane in lanes:
        if lane.predicate(row):
            return lane.name
    return "full_low_value_quarantine"


def build_lanes(index_path: Path, out_root: Path, verify_paths: bool = False) -> dict[str, Any]:
    release_root = index_path.parent
    rows = read_jsonl(index_path)
    lanes = lane_defs()
    rows_by_lane: dict[str, list[dict[str, Any]]] = {lane.name: [] for lane in lanes}
    for row in rows:
        rows_by_lane[select_lane(row, lanes)].append(row)
    quality_counts = Counter(quality(row) for row in rows)
    index_summary = {
        "total": len(rows),
        "quality_counts": dict(quality_counts),
        "likely_platform_or_empty": sum(1 for row in rows if is_platform_or_empty(row)),
    }
    reports = [
        write_lane(lane, rows_by_lane[lane.name], out_root, release_root, verify_paths=verify_paths)
        for lane in lanes
    ]
    write_runbook(out_root, index_path, release_root, reports, index_summary)
    return {
        "source_index": str(index_path),
        "release_root": str(release_root),
        "out_root": str(out_root),
        "index_summary": index_summary,
        "lanes": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build segmented full-93k Stage7 lanes from release index")
    parser.add_argument("--index", default=str(DEFAULT_INDEX))
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--verify-paths", action="store_true", help="Check every llm_input.md exists; slower on HDD.")
    args = parser.parse_args(argv)

    result = build_lanes(Path(args.index), Path(args.out_root), verify_paths=bool(args.verify_paths))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
