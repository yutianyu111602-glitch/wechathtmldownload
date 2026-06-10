#!/usr/bin/env python3
"""Build overnight Stage7 extraction lanes from the full LLM intake manifest.

The lane builder is control-plane only: it reads the current intake manifest,
materializes multiple isolated Stage7 roots, writes per-lane configs, and emits
operator commands. It does not call the LLM and does not write vector/DB/graph
stores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml


DEFAULT_INTAKE = Path(
    r"D:\downstream_results\stage7_rewrite\longrun\LLM_INTAKE_MANIFEST_20260507"
    r"\llm_intake_manifest.jsonl"
)
DEFAULT_OUT_ROOT = Path(
    r"D:\downstream_results\stage7_rewrite\longrun"
    r"\STAGE7_OVERNIGHT_QWEN36_27B_20260507"
)
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


@dataclass(frozen=True)
class Lane:
    name: str
    description: str
    predicate: Callable[[dict[str, Any]], bool]
    chunking: dict[str, int]
    llm: dict[str, Any]
    priority: int


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def intake_chars(row: dict[str, Any]) -> int:
    try:
        return int(row.get("llm_chars") or 0)
    except (TypeError, ValueError):
        return 0


def as_stage7_record(row: dict[str, Any]) -> dict[str, Any] | None:
    artifact_dir = Path(str(row.get("artifact_dir") or ""))
    llm_input_path = Path(str(row.get("llm_input_path") or artifact_dir / "llm_input.md"))
    if not artifact_dir.exists() or not llm_input_path.exists():
        return None
    source_account = str(row.get("account_key") or artifact_dir.parent.name).strip()
    article_id = str(row.get("token") or artifact_dir.name).strip()
    article_uid = sha1_text(f"{source_account}:{article_id}:{artifact_dir}")
    chars = intake_chars(row)
    return {
        "article_uid": article_uid,
        "source_account": source_account,
        "article_id": article_id,
        "article_dir": str(artifact_dir),
        "llm_input_path": str(llm_input_path),
        "meta_path": str(artifact_dir / "meta.json") if (artifact_dir / "meta.json").exists() else "",
        "poster_ocr_path": str(artifact_dir / "poster_ocr.json") if (artifact_dir / "poster_ocr.json").exists() else "",
        "title": str(row.get("title") or ""),
        "publish_time": "",
        "url": str(row.get("source_url") or row.get("original_short_url") or ""),
        "input_chars": chars,
        "input_sha1": sha1_text(str(llm_input_path) + ":" + str(chars)),
        "status": "pending",
        "source_kind": str(row.get("source_kind") or ""),
        "source_name": str(row.get("source_name") or ""),
        "poster_ocr_exists": bool(row.get("poster_ocr_exists")),
        "sidecar_exists": bool(row.get("sidecar_exists")),
        "quality_report_exists": bool(row.get("quality_report_exists")),
        "empty_files": [],
        "oversized": chars > 500_000,
        "encoding_ok": True,
    }


def lane_defs() -> list[Lane]:
    return [
        Lane(
            name="core_short_all",
            description="All ready rows under 2500 chars. High-throughput lane for historical empty-link recovered material.",
            predicate=lambda r: r.get("verdict") == "ready" and intake_chars(r) < 2500,
            chunking={"target_chars": 900, "max_chars": 1800, "min_chars": 300, "hard_max_chars": 2400, "overlap_chars": 120},
            llm={"prompt_path": "config/prompt.extract.micro.zh.txt", "temperature": 0.0, "top_p": 0.75, "top_k": 10, "repeat_penalty": 1.05, "max_tokens": 384, "timeout_sec": 180, "concurrency": 1},
            priority=10,
        ),
        Lane(
            name="medium_balanced_all",
            description="All ready rows from 2500 to 7999 chars. Balanced chunk/output budget for normal articles.",
            predicate=lambda r: r.get("verdict") == "ready" and 2500 <= intake_chars(r) < 8000,
            chunking={"target_chars": 1200, "max_chars": 2800, "min_chars": 500, "hard_max_chars": 3600, "overlap_chars": 180},
            llm={"temperature": 0.02, "top_p": 0.75, "top_k": 20, "repeat_penalty": 1.05, "max_tokens": 1536, "timeout_sec": 300},
            priority=20,
        ),
        Lane(
            name="latest_long_all",
            description="All ready rows at 8000 chars and above. Smaller chunks and larger output budget for dense/long posts.",
            predicate=lambda r: r.get("verdict") == "ready" and intake_chars(r) >= 8000,
            chunking={"target_chars": 900, "max_chars": 1800, "min_chars": 400, "hard_max_chars": 2400, "overlap_chars": 160},
            llm={"temperature": 0.0, "top_p": 0.70, "top_k": 10, "repeat_penalty": 1.05, "max_tokens": 3072, "timeout_sec": 480},
            priority=30,
        ),
        Lane(
            name="review_salvage_ocr",
            description="Review rows with at least 500 chars or OCR sidecars. Salvage lane for partial value extraction.",
            predicate=lambda r: r.get("verdict") == "review" and (intake_chars(r) >= 500 or bool(r.get("poster_ocr_exists"))),
            chunking={"target_chars": 800, "max_chars": 1600, "min_chars": 250, "hard_max_chars": 2200, "overlap_chars": 120},
            llm={"prompt_path": "config/prompt.extract.micro.zh.txt", "temperature": 0.0, "top_p": 0.70, "top_k": 10, "repeat_penalty": 1.05, "max_tokens": 384, "timeout_sec": 180, "concurrency": 1},
            priority=40,
        ),
    ]


def load_base_config() -> dict[str, Any]:
    if not DEFAULT_CONFIG.exists():
        return {}
    with DEFAULT_CONFIG.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_config(path: Path, lane_root: Path, lane: Lane) -> None:
    raw = load_base_config()
    raw["output_root"] = str(lane_root)
    raw["input_root"] = str(lane_root / "input_from_intake")
    raw.setdefault("pipeline", {})["description"] = f"overnight_{lane.name}"
    raw.setdefault("chunking", {}).update(lane.chunking)
    raw.setdefault("llm", {}).update(lane.llm)
    raw["llm"]["model"] = raw["llm"].get("model") or "Qwen3.6-27B"
    raw["llm"]["api_style"] = raw["llm"].get("api_style") or "openai_compatible"
    raw["llm"]["no_thinking"] = True
    raw["llm"]["thinking"] = False
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_lane(lane: Lane, rows: list[dict[str, Any]], out_root: Path) -> dict[str, Any]:
    lane_root = out_root / "lanes" / lane.name
    manifest_dir = lane_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (lane_root / "logs").mkdir(parents=True, exist_ok=True)
    (lane_root / "reports").mkdir(parents=True, exist_ok=True)
    records = [r for r in (as_stage7_record(row) for row in rows) if r is not None]
    records.sort(key=lambda r: (int(r.get("input_chars") or 0), str(r.get("source_account") or ""), str(r.get("article_id") or "")))
    manifest_path = manifest_dir / "article_manifest.v1.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    config_path = lane_root / "config.stage7.yaml"
    write_config(config_path, lane_root, lane)
    chars = [int(r.get("input_chars") or 0) for r in records]
    source_counts: dict[str, int] = {}
    for record in records:
        source = str(record.get("source_kind") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "name": lane.name,
        "description": lane.description,
        "priority": lane.priority,
        "root": str(lane_root),
        "manifest": str(manifest_path),
        "config": str(config_path),
        "count": len(records),
        "min_chars": min(chars) if chars else 0,
        "max_chars": max(chars) if chars else 0,
        "avg_chars": round(sum(chars) / len(chars), 1) if chars else 0,
        "source_counts": source_counts,
        "chunking": lane.chunking,
        "llm": lane.llm,
    }


def write_runbook(out_root: Path, lane_reports: list[dict[str, Any]], source_manifest: Path) -> None:
    out_root.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_manifest": str(source_manifest),
        "out_root": str(out_root),
        "lanes": lane_reports,
        "policy": {
            "main_loop": "run lane -> quality report -> promote next lane or route failures to repair",
            "no_single_profile": True,
            "production_writes": "blocked until explicit write gate",
            "gpu_preflight_required": True,
            "persist_every_test": True,
        },
    }
    (out_root / "overnight_lane_plan.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Stage7 Overnight Qwen3.6-27B Lane Plan",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- source_manifest: `{source_manifest}`",
        f"- out_root: `{out_root}`",
        "- model: local `Qwen3.6-27B` via the lane config endpoint",
        "- principle: do not use one parameter set for every article; split by length/source and keep failures moving to repair lanes.",
        "- GPU/model-server readiness is not assumed. Every production-sized lane must record Qwen/Ollama/GPU preflight evidence before or with the run.",
        "- Every test/run must persist command lines, config paths, stdout/stderr logs, status, quality report, verdict, failure examples, parameter decision, and next cursor in the lane report directory.",
        "",
        "## Night Contract",
        "",
        "- Main objective: extract as much value as possible from recovered empty-link/latest/OCR intake, then prepare vector-knowledge-graph artifacts.",
        "- Samples are tuning tools, not the main work. Promote to larger segmented lanes when parse/schema/evidence gates are acceptable.",
        "- A bad article must move to repair/review; it must not stop the throughput lane.",
        "- Hard stops remain: secrets, dangerous git, broad D-root scans, blocked/captcha HTML merge, and production Qdrant/Neo4j/PC DB writes without an explicit gate.",
        "",
        "## Lane Order",
        "",
    ]
    for lane in sorted(lane_reports, key=lambda r: r["priority"]):
        lines.extend(
            [
                f"### {lane['name']}",
                "",
                f"- count: `{lane['count']}`",
                f"- chars: min `{lane['min_chars']}`, avg `{lane['avg_chars']}`, max `{lane['max_chars']}`",
                f"- root: `{lane['root']}`",
                f"- config: `{lane['config']}`",
                f"- chunking: `{lane['chunking']}`",
                f"- llm: `{lane['llm']}`",
                f"- source_counts: `{lane['source_counts']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Execution Commands",
            "",
            "Run one lane at a time against the local Qwen endpoint unless the model host is explicitly proven stable under multi-process load.",
            "",
            "```powershell",
            "Set-Location C:\\code\\githubstar\\wechathtmldownload\\tools\\stage7_rewrite",
            "python -m stage7.cli doctor | Tee-Object -FilePath D:\\downstream_results\\stage7_rewrite\\longrun\\STAGE7_OVERNIGHT_QWEN36_27B_20260507\\MODEL_PREFLIGHT.log",
        ]
    )
    for lane in sorted(lane_reports, key=lambda r: r["priority"]):
        lines.append(f"python -m stage7.cli build-manifest --output {lane['root']} --mode {lane['name']}")
        lines.append(
            f"python -m stage7.cli run-llm --mode {lane['name']} --output {lane['root']} --config {lane['config']} --run-id overnight_{lane['name']}"
        )
        lines.append(
            f"python scripts\\stage7_quality_report.py --output {lane['root']} --out-json {lane['root']}\\reports\\QUALITY.json --out-md {lane['root']}\\reports\\QUALITY.md"
        )
    lines.append("```")
    (out_root / "OVERNIGHT_RUN_STRATEGY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    ps1 = out_root / "run_overnight_lanes.ps1"
    ps_lines = [
        "$ErrorActionPreference = 'Stop'",
        "Set-Location 'C:\\code\\githubstar\\wechathtmldownload\\tools\\stage7_rewrite'",
    ]
    for lane in sorted(lane_reports, key=lambda r: r["priority"]):
        ps_lines.extend(
            [
                f"python -m stage7.cli build-manifest --output '{lane['root']}' --mode '{lane['name']}'",
                f"python -m stage7.cli run-llm --mode '{lane['name']}' --output '{lane['root']}' --config '{lane['config']}' --run-id 'overnight_{lane['name']}'",
                f"python scripts\\stage7_quality_report.py --output '{lane['root']}' --out-json '{lane['root']}\\reports\\QUALITY.json' --out-md '{lane['root']}\\reports\\QUALITY.md'",
            ]
        )
    ps1.write_text("\n".join(ps_lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build overnight Stage7 lane manifests")
    parser.add_argument("--intake-manifest", default=str(DEFAULT_INTAKE))
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    args = parser.parse_args(argv)

    source_manifest = Path(args.intake_manifest)
    out_root = Path(args.out_root)
    rows = read_jsonl(source_manifest)
    lane_reports = []
    for lane in lane_defs():
        selected = [row for row in rows if lane.predicate(row)]
        lane_reports.append(write_lane(lane, selected, out_root))
    write_runbook(out_root, lane_reports, source_manifest)
    print(json.dumps({"out_root": str(out_root), "lanes": lane_reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
