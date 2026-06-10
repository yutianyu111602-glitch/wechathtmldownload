#!/usr/bin/env python3
"""Auto-continue Full93K extraction lanes without approving release quality.

This controller is intentionally narrow:
- it watches one active shard parent;
- when that lane is complete enough, it runs a final read-only quality checkpoint;
- if hard structural gates are clean, it builds and starts the next Stage7 lane.

It does not run vector, Qdrant, Neo4j, PC DB, or knowledge-graph writers.
Quality RED caused only by title pseudoquotes blocks release/next-lane quality
approval in docs, but does not block keeping the GPU busy when --launch is used.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


SAFETY = {
    "starts_vector_graph_db": False,
    "starts_qwen_salvage": False,
    "edits_prompt_runner_chunker": False,
}


def run_command(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd), text=True, capture_output=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, decision: dict[str, Any]) -> None:
    lines = [
        "# Full93K Auto Continue Decision",
        "",
        f"- generated_at: `{decision['generated_at']}`",
        f"- current_mode: `{decision['current_mode']}`",
        f"- next_mode: `{decision['next_mode']}`",
        f"- decision: `{decision['decision']}`",
        f"- reason: `{decision['reason']}`",
        f"- launch_requested: `{decision['launch_requested']}`",
        f"- launched: `{decision['launched']}`",
        f"- current_extracts: `{decision['current_totals'].get('extract_count', 0)}/{decision['current_totals'].get('manifest_records', 0)}`",
        f"- current_running: `{decision['current_totals'].get('running', 0)}`",
        f"- failed_retryable/final: `{decision['current_totals'].get('failed_retryable', 0)}/{decision['current_totals'].get('failed_final', 0)}`",
        f"- remaining_estimate: `{decision['current_totals'].get('remaining_estimate', 0)}`",
        f"- checkpoint: `{decision.get('checkpoint_dir', '')}`",
        f"- next_shard_parent: `{decision.get('next_shard_parent', '')}`",
        "",
        "## Hard Gates",
        "",
    ]
    for name, value in decision.get("hard_gates", {}).items():
        lines.append(f"- {name}: `{value}`")
    lines.extend(["", "## Safety", ""])
    for name, value in decision.get("safety", {}).items():
        lines.append(f"- {name}: `{value}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def is_lane_complete(totals: dict[str, Any]) -> bool:
    if int(totals.get("running") or 0) != 0:
        return False
    if int(totals.get("remaining_estimate") or 0) != 0:
        return False
    return True


def structural_gates(checkpoint_summary: dict[str, Any], totals: dict[str, Any]) -> dict[str, bool]:
    audit = checkpoint_summary.get("audit", {})
    return {
        "failed_final_zero": int(totals.get("failed_final") or 0) == 0,
        "parse_errors_zero": int(audit.get("parse_errors") or 0) == 0,
        "schema_invalid_zero": int(audit.get("schema_invalid") or 0) == 0,
        "all_chunks_failed_zero": int(audit.get("all_chunks_failed") or 0) == 0,
        "context_exceeded_zero": int(audit.get("context_exceeded_files") or 0) == 0,
    }


def already_launched(state_path: Path, next_mode: str) -> bool:
    if not state_path.exists():
        return False
    state = read_json(state_path)
    launched_modes = state.get("launched_modes", {})
    return bool(launched_modes.get(next_mode, {}).get("launched"))


def update_state(state_path: Path, decision: dict[str, Any]) -> None:
    state: dict[str, Any] = {"schema_version": "full93k_auto_continue_state.v1", "launched_modes": {}}
    if state_path.exists():
        state = read_json(state_path)
    state.setdefault("launched_modes", {})
    if decision.get("launched"):
        state["launched_modes"][decision["next_mode"]] = {
            "launched": True,
            "launched_at": decision["generated_at"],
            "next_shard_parent": decision.get("next_shard_parent", ""),
            "decision_path": decision.get("decision_json", ""),
        }
    state["last_decision"] = decision
    write_json(state_path, state)


def build_decision(
    *,
    generated_at: str,
    current_mode: str,
    next_mode: str,
    status: dict[str, Any],
    checkpoint_summary: dict[str, Any] | None,
    state_path: Path,
    launch_requested: bool,
) -> dict[str, Any]:
    totals = status.get("totals", {})
    complete = is_lane_complete(totals)
    if not complete:
        return {
            "generated_at": generated_at,
            "current_mode": current_mode,
            "next_mode": next_mode,
            "decision": "keep_current_running",
            "reason": "current lane still has running work or remaining_estimate is nonzero",
            "launch_requested": launch_requested,
            "launched": False,
            "current_totals": totals,
            "hard_gates": {},
            "safety": SAFETY,
        }

    if already_launched(state_path, next_mode):
        return {
            "generated_at": generated_at,
            "current_mode": current_mode,
            "next_mode": next_mode,
            "decision": "next_already_launched",
            "reason": f"{next_mode} is already recorded in auto-continue state",
            "launch_requested": launch_requested,
            "launched": False,
            "current_totals": totals,
            "hard_gates": {},
            "safety": SAFETY,
        }

    if checkpoint_summary is None:
        return {
            "generated_at": generated_at,
            "current_mode": current_mode,
            "next_mode": next_mode,
            "decision": "need_final_checkpoint",
            "reason": "current lane is complete enough but checkpoint summary is missing",
            "launch_requested": launch_requested,
            "launched": False,
            "current_totals": totals,
            "hard_gates": {},
            "safety": SAFETY,
        }

    gates = structural_gates(checkpoint_summary, totals)
    if not all(gates.values()):
        return {
            "generated_at": generated_at,
            "current_mode": current_mode,
            "next_mode": next_mode,
            "decision": "blocked_by_structural_gate",
            "reason": "hard structural gates are not clean",
            "launch_requested": launch_requested,
            "launched": False,
            "current_totals": totals,
            "hard_gates": gates,
            "safety": SAFETY,
        }

    return {
        "generated_at": generated_at,
        "current_mode": current_mode,
        "next_mode": next_mode,
        "decision": "approve_next_extraction_lane",
        "reason": "current lane complete enough and hard structural gates are clean; quality debt remains tracked separately",
        "launch_requested": launch_requested,
        "launched": False,
        "current_totals": totals,
        "hard_gates": gates,
        "safety": SAFETY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--current-parent", required=True)
    parser.add_argument("--current-mode", default="full_ready_short_core")
    parser.add_argument("--next-mode", default="full_ready_medium_core")
    parser.add_argument("--next-lane-root", required=True)
    parser.add_argument("--next-config", required=True)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()

    script_root = Path(__file__).resolve().parents[1]
    root = Path(args.root)
    current_parent = Path(args.current_parent)
    generated_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    decisions_dir = root / "auto_continue"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    decision_json = decisions_dir / f"AUTO_CONTINUE_DECISION_{stamp}.json"
    decision_md = decisions_dir / f"AUTO_CONTINUE_DECISION_{stamp}.md"
    state_path = decisions_dir / "AUTO_CONTINUE_STATE.json"
    status_json = current_parent / "SHARDED_RUN_STATUS_LATEST.json"
    status_md = current_parent / "SHARDED_RUN_STATUS_LATEST.md"
    history_jsonl = current_parent / "SHARDED_RUN_METRICS_HISTORY.jsonl"

    status_cmd = [
        "python",
        str(script_root / "scripts" / "summarize_stage7_shards.py"),
        "--parent",
        str(current_parent),
        "--mode",
        args.current_mode,
        "--out-json",
        str(status_json),
        "--out-md",
        str(status_md),
        "--history-jsonl",
        str(history_jsonl),
    ]
    status_proc = run_command(status_cmd, cwd=script_root)
    if status_proc.returncode != 0:
        decision = {
            "generated_at": generated_at,
            "current_mode": args.current_mode,
            "next_mode": args.next_mode,
            "decision": "status_refresh_failed",
            "reason": status_proc.stderr.strip() or status_proc.stdout.strip(),
            "launch_requested": args.launch,
            "launched": False,
            "current_totals": {},
            "hard_gates": {},
            "safety": SAFETY,
        }
        decision["decision_json"] = str(decision_json)
        decision["decision_md"] = str(decision_md)
        write_json(decision_json, decision)
        write_markdown(decision_md, decision)
        update_state(state_path, decision)
        print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    status = read_json(status_json)
    checkpoint_summary: dict[str, Any] | None = None
    checkpoint_dir = ""
    if is_lane_complete(status.get("totals", {})) and not already_launched(state_path, args.next_mode):
        checkpoint_dir = str(root / f"QUALITY_CHECKPOINT_FINAL_{args.current_mode}_{stamp}")
        checkpoint_cmd = [
            "python",
            str(script_root / "scripts" / "full93k_quality_checkpoint.py"),
            "--shard-parent",
            str(current_parent),
            "--out-dir",
            checkpoint_dir,
            "--sample-per-bucket",
            "8",
        ]
        checkpoint_proc = run_command(checkpoint_cmd, cwd=script_root)
        summary_path = Path(checkpoint_dir) / "QUALITY_CHECKPOINT_SUMMARY.json"
        if summary_path.exists():
            checkpoint_summary = read_json(summary_path)
        elif checkpoint_proc.returncode != 0:
            checkpoint_summary = None
    decision = build_decision(
        generated_at=generated_at,
        current_mode=args.current_mode,
        next_mode=args.next_mode,
        status=status,
        checkpoint_summary=checkpoint_summary,
        state_path=state_path,
        launch_requested=args.launch,
    )
    decision["checkpoint_dir"] = checkpoint_dir

    if decision["decision"] == "approve_next_extraction_lane":
        next_parent = root / "lane_shards" / f"{args.next_mode}_shards{args.shards}_c1_auto_{datetime.now().strftime('%Y%m%d_%H%M')}"
        decision["next_shard_parent"] = str(next_parent)
        if args.launch:
            build_cmd = [
                "python",
                str(script_root / "scripts" / "build_stage7_lane_shards.py"),
                "--source-lane-root",
                str(Path(args.next_lane_root)),
                "--source-config",
                str(Path(args.next_config)),
                "--mode",
                args.next_mode,
                "--out-root",
                str(next_parent),
                "--shards",
                str(args.shards),
            ]
            build_proc = run_command(build_cmd, cwd=script_root)
            decision["build_stdout"] = build_proc.stdout[-4000:]
            decision["build_stderr"] = build_proc.stderr[-4000:]
            decision["build_exit_code"] = build_proc.returncode
            if build_proc.returncode == 0:
                launch_cmd = [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(next_parent / "run_shards.ps1"),
                ]
                launch_proc = subprocess.Popen(launch_cmd, cwd=str(script_root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                decision["launch_pid"] = launch_proc.pid
                decision["launched"] = True
                decision["reason"] = f"{decision['reason']}; launched {args.next_mode}"
            else:
                decision["decision"] = "next_build_failed"
                decision["reason"] = "failed to build next lane shards"
                decision["launched"] = False
    decision["decision_json"] = str(decision_json)
    decision["decision_md"] = str(decision_md)
    write_json(decision_json, decision)
    write_markdown(decision_md, decision)
    update_state(state_path, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision["decision"] not in {"status_refresh_failed", "blocked_by_structural_gate", "next_build_failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
