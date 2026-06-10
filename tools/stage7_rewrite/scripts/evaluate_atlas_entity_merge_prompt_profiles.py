#!/usr/bin/env python3
"""Evaluate Atlas entity merge prompt profiles on the same sample queue.

This script builds a fixed high-risk sample from the full entity merge queue,
then runs the DeepSeek runner once per prompt profile. Default mode is dry-run;
use --execute to call direct DeepSeek. Outputs are report-only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_entity_merge_prompt_profile_eval.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_queue_ocr_full_current" / "entity_merge_llm_queue.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_prompt_profile_eval_current"
RUNNER_SCRIPT = Path(__file__).resolve().with_name("run_atlas_entity_merge_deepseek.py")

runner_spec = importlib.util.spec_from_file_location("run_atlas_entity_merge_deepseek", RUNNER_SCRIPT)
runner = importlib.util.module_from_spec(runner_spec)
assert runner_spec.loader is not None
runner_spec.loader.exec_module(runner)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL object at {path}:{line_no}")
            rows.append(row)
    return rows


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def cluster_text(row: dict[str, Any]) -> str:
    parts = [text(row.get("block_key")), " ".join(text(flag) for flag in row.get("risk_flags") or [])]
    for member in row.get("members") or []:
        parts.append(text(member.get("display_name")))
        parts.append(" ".join(text(alias) for alias in member.get("aliases") or []))
    return " ".join(parts).casefold()


def pick_samples(
    rows: list[dict[str, Any]],
    *,
    max_samples: int,
    block_keys: list[str],
    max_per_block_key: int,
) -> list[dict[str, Any]]:
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(row: dict[str, Any]) -> None:
        cluster_id = text(row.get("cluster_id"))
        if not cluster_id or cluster_id in seen or len(picked) >= max_samples:
            return
        seen.add(cluster_id)
        picked.append(row)

    key_set = {text(item) for item in block_keys if text(item)}
    picked_per_key: Counter[str] = Counter()
    for row in rows:
        block_key = text(row.get("block_key"))
        if block_key in key_set and picked_per_key[block_key] < max_per_block_key:
            add(row)
            picked_per_key[block_key] += 1

    selectors = [
        lambda row: "member_or_memorial_suffix" in set(row.get("risk_flags") or []),
        lambda row: "dj_place_org_mix" in set(row.get("risk_flags") or []),
        lambda row: "ocr_confusable_key" in set(row.get("risk_flags") or []),
        lambda row: any(term in cluster_text(row) for term in ["soundsystem", "sound system", "音响", "funktion", "void", "l-acoustics", "martin audio", "d&b"]),
        lambda row: int(row.get("block_member_count") or row.get("member_count") or 0) >= 24,
    ]
    for selector in selectors:
        for row in rows:
            if len(picked) >= max_samples:
                break
            if selector(row):
                add(row)
    return picked


def run_profile(args: argparse.Namespace, sample_queue: Path, profile: str, out_dir: Path) -> dict[str, Any]:
    return runner.run(
        argparse.Namespace(
            queue=str(sample_queue),
            out_dir=str(out_dir / profile),
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            execute=bool(args.execute),
            block_key="",
            cluster_id="",
            skip_clusters=0,
            max_clusters=0,
            resume=False,
            retry_errors=False,
            sleep_s=float(args.sleep_s),
            concurrency=int(args.concurrency),
            checkpoint_every=1,
            stop_error_rate=0.50,
            min_error_rate_check=4,
            max_tokens=int(args.max_tokens),
            temperature=float(args.temperature),
            timeout_s=int(args.timeout_s),
            prompt_profile=profile,
            system_prompt_path="",
        )
    )


def build_eval(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    out_dir = Path(args.out_dir)
    profiles = [text(item) for item in str(args.profiles).split(",") if text(item)]
    block_keys = [text(item) for item in str(args.block_keys).split(",") if text(item)]
    rows = read_jsonl(queue_path)
    samples = pick_samples(
        rows,
        max_samples=max(1, int(args.max_samples)),
        block_keys=block_keys,
        max_per_block_key=max(1, int(args.max_per_block_key)),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_queue = out_dir / "prompt_matrix_sample_queue.jsonl"
    write_jsonl(sample_queue, samples)

    profile_summaries = []
    for profile in profiles:
        profile_summaries.append(run_profile(args, sample_queue, profile, out_dir))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_prompt_profile_eval_ready_report_only",
        "queue_path": str(queue_path),
        "out_dir": str(out_dir),
        "sample_queue": str(sample_queue),
        "execute": bool(args.execute),
        "profiles": profiles,
        "sample_count": len(samples),
        "max_per_block_key": max(1, int(args.max_per_block_key)),
        "sample_cluster_ids": [row.get("cluster_id") for row in samples],
        "sample_block_keys": [row.get("block_key") for row in samples],
        "profile_summaries": profile_summaries,
        "counts_by_profile": {
            summary.get("prompt_profile", profiles[index] if index < len(profiles) else ""): dict(Counter(summary.get("counts") or {}))
            for index, summary in enumerate(profile_summaries)
        },
        "safety": {
            "report_only": True,
            "direct_deepseek_only": True,
            "llm_call_executed": bool(args.execute),
            "sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "production_pointer_updated": False,
        },
    }
    write_json(out_dir / "prompt_profile_eval_summary.json", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--profiles", default="baseline,strict_v2,sound_aware_v1")
    parser.add_argument("--block-keys", default="oil,all,loopy")
    parser.add_argument("--max-per-block-key", type=int, default=3)
    parser.add_argument("--max-samples", type=int, default=18)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--model", default=runner.DEFAULT_MODEL)
    parser.add_argument("--base-url", default=runner.DEFAULT_BASE_URL)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--sleep-s", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=1400)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-s", type=int, default=90)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = build_eval(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
