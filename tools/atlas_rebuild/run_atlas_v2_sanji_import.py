#!/usr/bin/env python3
"""Phase 4 orchestrator: Sanji delta -> extraction -> merge -> canonical candidate.

Atlas v2 dedupe/freshness design
(`C:\\code\\mavelpoint-cn-v2\\docs\\site-clone\\ATLAS_V2_DEDUP_SANJI_AUTOMATION_DEEP_DESIGN_2026-07-06.md`).

Chains, in order, everything verified manually this session:
  1. export_sanji_appdata_manifest.py --exclude-token-file <checkpoint>   (delta only, read-only Sanji)
  2. stage0_ingest_sanji_manifest.py --manifest-root <delta manifest>
  3. stage1_clean.py                                                     (deterministic routing, no LLM)
  4. stage2_extract.py --route text_complete --backend deepseek          (text-only articles)
     stage2_extract.py --route needs_vision  --backend ocr_deepseek      (local OCR + text-only DeepSeek)
  5. stage3_resolve.py
  6. stage4_rollup.py                                                    -> shard candidate (new articles only)
  7. merge_stage4_shard_into_base.py                                     -> copy of base + shard, base untouched
  8. build_serving_identity_redirects.py / build_serving_venue_redirects.py
  9. build_date_venue_repair_candidates.py                               -> Phase 2 repair candidates
 10. build_canonical_event_candidates.py --repair-db ...                 -> Phase 3 review candidate
 11. adjudicate_weak_key_candidates.py                                   -> persistent decisions
 12. build_canonical_event_candidates.py                                 -> rebuild with current decisions
 13. materialize_canonical_serving.py                                    -> complete serving candidate
 14. materialize_canonical_serving.py --verify-candidate                 -> promotion gate
 15. merge_sanji_seen_tokens.py                                          -> checkpoint only after all gates

Every stage runs against an isolated `ATLAS_WORK_DIR` under the run's own directory — never
the shared default `_work/`, so concurrent or repeated runs never collide. On any stage
failure, the run stops immediately and the Sanji token checkpoint is NOT advanced (so the
same delta articles are retried next run, per the design's "fail不推进token checkpoint"
rule). No promotion, no Hermes, no VPS — this only ever writes to `--out-dir` and reads
Sanji read-only.

Usage:
  python run_atlas_v2_sanji_import.py --limit 20 --max-cost-rmb 1
  python run_atlas_v2_sanji_import.py --limit 20 --max-cost-rmb 1 --dry-run-backend
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STAGE7_SCRIPTS = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
if str(STAGE7_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(STAGE7_SCRIPTS))

from build_atlas_dj_first_canary import now_iso, write_json  # noqa: E402

DEFAULT_SEEN_TOKENS = Path(r"E:\atlas_manifest_exports\sanji_pipeline_seen_tokens_latest.txt")
DEFAULT_RUN_ROOT = Path(r"E:\atlas_v2_import_runs")
DEFAULT_CUMULATIVE_STATE = DEFAULT_RUN_ROOT / "latest_cumulative_candidate.json"
DEFAULT_WEAK_DECISIONS = DEFAULT_RUN_ROOT / "weak_key_decisions.sqlite"
DEFAULT_HISTORICAL_VENUE_GEO = Path(
    os.environ.get(
        "ATLAS_HISTORICAL_VENUE_GEO",
        r"C:\code\githubstar\wechathtmldownload\tools\atlas_rebuild\_serve_20260623\historical_venue_geo.json",
    )
)
CUMULATIVE_STATE_SCHEMA = "atlas_v2.cumulative_candidate_state.v1"
CANONICAL_LLM_BATCH_SIZE = 10
CANONICAL_PIPELINE_ORDER = [
    "merge_shard",
    "build_dj_identity",
    "build_venue_identity",
    "phase2_repair",
    "phase3_canonical",
    "adjudicate_deterministic",
    "adjudicate_llm",
    "phase3_rebuild_with_decisions",
    "materialize_canonical_serving",
    "canonical_gate",
    "advance_checkpoint",
]


def ordered_subset(actual: list[str], expected: list[str]) -> bool:
    """Return whether known stage names occur once and in expected order."""
    positions = {name: index for index, name in enumerate(expected)}
    known = [name for name in actual if name in positions]
    return len(known) == len(set(known)) and all(
        positions[left] < positions[right] for left, right in zip(known, known[1:])
    )


def canonical_pipeline_ready(steps: list[dict[str, Any]], gate_report: dict[str, Any]) -> bool:
    """Fail closed unless every pre-checkpoint canonical stage succeeded in order."""
    required = CANONICAL_PIPELINE_ORDER[:-1]
    canonical_steps = [step for step in steps if step.get("name") in required]
    names = [str(step.get("name")) for step in canonical_steps]
    return (
        names == required
        and ordered_subset(names, CANONICAL_PIPELINE_ORDER)
        and all(step.get("returncode") == 0 for step in canonical_steps)
        and gate_report.get("pass") is True
    )


def optional_existing_path(path: Path | None) -> Path | None:
    return path if path is not None and path.is_file() else None


def promote_seen_tokens_checkpoint(candidate: Path, target: Path) -> None:
    """Atomically copy a verified run checkpoint into the shared delta cursor."""
    if not candidate.is_file():
        raise FileNotFoundError(f"updated checkpoint not found: {candidate}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.tmp-{os.getpid()}"
    try:
        shutil.copyfile(candidate, tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def resolve_base_serving_db(explicit_base: Path | None, state_file: Path, checkpoint: Path) -> Path:
    """Resolve the cumulative base, failing closed when no verified state exists."""
    if explicit_base is not None:
        if not explicit_base.is_file():
            raise SystemExit(f"base serving DB not found: {explicit_base}")
        return explicit_base
    if not state_file.is_file():
        raise SystemExit(f"cumulative candidate state not found: {state_file}")
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid cumulative candidate state: {state_file}: {exc}") from exc
    if state.get("schema_version") != CUMULATIVE_STATE_SCHEMA:
        raise SystemExit(f"unsupported cumulative candidate state schema: {state.get('schema_version')!r}")
    candidate = Path(str(state.get("candidate_db") or ""))
    if not candidate.is_file():
        raise SystemExit(f"cumulative candidate DB not found: {candidate}")
    recorded_checkpoint = Path(str(state.get("checkpoint_path") or ""))
    if recorded_checkpoint.resolve() != checkpoint.resolve():
        raise SystemExit(
            f"cumulative candidate checkpoint path mismatch: state={recorded_checkpoint} current={checkpoint}"
        )
    if not checkpoint.is_file():
        raise SystemExit(f"seen-token checkpoint not found: {checkpoint}")
    checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if state.get("checkpoint_sha256") != checkpoint_sha256:
        raise SystemExit(
            "cumulative candidate checkpoint SHA mismatch: "
            f"state={state.get('checkpoint_sha256')} current={checkpoint_sha256}"
        )
    return candidate


def promote_cumulative_candidate_state(
    candidate_db: Path,
    checkpoint: Path,
    state_file: Path,
    run_dir: Path,
) -> dict[str, Any]:
    """Atomically publish the candidate that exactly matches the shared checkpoint."""
    if not candidate_db.is_file():
        raise FileNotFoundError(f"cumulative candidate DB not found: {candidate_db}")
    if not checkpoint.is_file():
        raise FileNotFoundError(f"seen-token checkpoint not found: {checkpoint}")
    checkpoint_count = sum(
        1
        for line in checkpoint.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.startswith("#")
    )
    state = {
        "schema_version": CUMULATIVE_STATE_SCHEMA,
        "generated_at": now_iso(),
        "run_dir": str(run_dir),
        "candidate_db": str(candidate_db),
        "checkpoint_path": str(checkpoint),
        "checkpoint_count": checkpoint_count,
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
    }
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.parent / f".{state_file.name}.tmp-{os.getpid()}"
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, state_file)
    finally:
        tmp.unlink(missing_ok=True)
    return state


def promote_checkpoint_and_candidate_state(
    run_checkpoint: Path,
    shared_checkpoint: Path,
    candidate_db: Path,
    state_file: Path,
    run_dir: Path,
) -> dict[str, Any]:
    """Advance the cursor and state together, restoring both on a write failure."""
    for path, label in ((run_checkpoint, "run checkpoint"), (candidate_db, "candidate DB")):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    checkpoint_before = shared_checkpoint.read_bytes() if shared_checkpoint.is_file() else None
    state_before = state_file.read_bytes() if state_file.is_file() else None

    def restore(path: Path, content: bytes | None) -> None:
        if content is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{path.name}.rollback-{os.getpid()}"
        try:
            tmp.write_bytes(content)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    try:
        promote_seen_tokens_checkpoint(run_checkpoint, shared_checkpoint)
        return promote_cumulative_candidate_state(candidate_db, shared_checkpoint, state_file, run_dir)
    except Exception:
        restore(shared_checkpoint, checkpoint_before)
        restore(state_file, state_before)
        raise


def run_step(name: str, cmd: list[str], env: dict[str, str], log_dir: Path) -> dict[str, Any]:
    log_path = log_dir / f"{name}.log"
    print(f"[{name}] {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    log_path.write_text((result.stdout or "") + "\n" + (result.stderr or ""), encoding="utf-8")
    tail = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()[-2000:]
    print(tail)
    return {"name": name, "cmd": [str(c) for c in cmd], "returncode": result.returncode, "log": str(log_path)}


def extraction_completion_report(clean_db: Path, extraction_db: Path) -> dict[str, Any]:
    """Prove every processable Stage1 token has a terminal valid extraction."""
    clean = sqlite3.connect(f"file:{clean_db.as_posix()}?mode=ro", uri=True)
    extracted = sqlite3.connect(f"file:{extraction_db.as_posix()}?mode=ro", uri=True)
    try:
        expected_rows = clean.execute(
            "SELECT token, route FROM clean WHERE route IN ('text_complete', 'needs_vision')"
        ).fetchall()
        result_rows = {
            row[0]: (row[1], int(row[2] or 0), row[3] or "")
            for row in extracted.execute(
                "SELECT token, status, valid, error FROM extractions"
            ).fetchall()
        }
    finally:
        clean.close()
        extracted.close()

    missing = []
    invalid = []
    status_counts: dict[str, int] = {}
    route_counts: dict[str, int] = {}
    for token, route in expected_rows:
        route_counts[route] = route_counts.get(route, 0) + 1
        result = result_rows.get(token)
        if result is None:
            missing.append(token)
            continue
        status, valid, error = result
        status_counts[status] = status_counts.get(status, 0) + 1
        if valid != 1 or status not in ("extracted", "classification_skip"):
            invalid.append({"token": token, "status": status, "error": error[:240]})
    return {
        "expected_count": len(expected_rows),
        "route_counts": route_counts,
        "status_counts": status_counts,
        "missing_count": len(missing),
        "missing_tokens": missing[:20],
        "invalid_count": len(invalid),
        "invalid": invalid[:20],
        "gate_pass": not missing and not invalid,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seen-tokens-file", type=Path, default=DEFAULT_SEEN_TOKENS)
    ap.add_argument("--base-serving-db", type=Path, default=None)
    ap.add_argument("--candidate-state-file", type=Path, default=DEFAULT_CUMULATIVE_STATE)
    ap.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    ap.add_argument("--weak-decisions-db", type=Path, default=DEFAULT_WEAK_DECISIONS)
    ap.add_argument(
        "--historical-venue-geo",
        type=Path,
        default=optional_existing_path(DEFAULT_HISTORICAL_VENUE_GEO),
    )
    ap.add_argument("--limit", type=int, default=20, help="max NEW articles this run (0 = all delta)")
    ap.add_argument("--max-cost-rmb", type=float, default=1.0, help="budget cap PER stage2 backend invocation")
    ap.add_argument(
        "--dry-run-backend",
        action="store_true",
        help="use --backend mock for stage2 (zero cost, proves wiring, not real data quality)",
    )
    ap.add_argument("--advance-checkpoint", action="store_true", help="on full success, write a new seen-tokens file")
    ap.add_argument("--vision-workers", type=int, default=1, help="parallel workers for the needs_vision stage2 pass")
    ap.add_argument("--canonical-llm-budget-rmb", type=float, default=5.0)
    ap.add_argument(
        "--run-id",
        default="",
        help="reuse an existing run directory (crash resume): every stage is token-idempotent, "
        "so already-exported/-ingested/-extracted articles are skipped, not re-paid",
    )
    args = ap.parse_args()

    if args.historical_venue_geo is not None and not args.historical_venue_geo.is_file():
        ap.error(f"--historical-venue-geo not found: {args.historical_venue_geo}")

    base_serving_db = resolve_base_serving_db(
        args.base_serving_db,
        args.candidate_state_file,
        args.seen_tokens_file,
    )

    run_id = args.run_id or f"run_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = args.run_root / run_id
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    work_dir = run_dir / "_work"
    env = os.environ.copy()
    env["ATLAS_WORK_DIR"] = str(work_dir)

    steps: list[dict[str, Any]] = []

    manifest_dir = run_dir / "manifest"
    steps.append(
        run_step(
            "export_delta",
            [
                sys.executable,
                str(HERE / "export_sanji_appdata_manifest.py"),
                "--exclude-token-file",
                str(args.seen_tokens_file),
                "--limit",
                str(args.limit),
                "--out",
                str(manifest_dir),
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "export_delta_failed")

    export_report = json.loads((manifest_dir / "export_report.json").read_text(encoding="utf-8"))
    if export_report.get("article_count", 0) == 0:
        return finish(run_dir, steps, "noop_no_new_articles", extra={"export_report": export_report})

    steps.append(
        run_step(
            "stage0_ingest",
            [sys.executable, str(HERE / "stage0_ingest_sanji_manifest.py"), "--manifest-root", str(manifest_dir)],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "stage0_failed")

    steps.append(run_step("stage1_clean", [sys.executable, str(HERE / "stage1_clean.py")], env, log_dir))
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "stage1_failed")

    text_backend, vision_backend = ("mock", "mock") if args.dry_run_backend else ("deepseek", "ocr_deepseek")
    steps.append(
        run_step(
            "stage2_extract_text",
            [
                sys.executable,
                str(HERE / "stage2_extract.py"),
                "--backend",
                text_backend,
                "--route",
                "text_complete",
                "--max-cost-rmb",
                str(args.max_cost_rmb),
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "stage2_text_failed")

    steps.append(
        run_step(
            "stage2_extract_vision",
            [
                sys.executable,
                str(HERE / "stage2_extract.py"),
                "--backend",
                vision_backend,
                "--route",
                "needs_vision",
                "--max-cost-rmb",
                str(args.max_cost_rmb),
                "--workers",
                str(args.vision_workers),
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "stage2_vision_failed")

    extraction_gate = extraction_completion_report(
        work_dir / "clean.sqlite",
        work_dir / "extractions.sqlite",
    )
    if not extraction_gate["gate_pass"]:
        return finish(
            run_dir,
            steps,
            "stage2_completion_gate_failed",
            extra={"export_report": export_report, "extraction_completion_gate": extraction_gate},
        )

    steps.append(
        run_step("stage3_resolve", [sys.executable, str(HERE / "stage3_resolve.py"), "--source", "extractions"], env, log_dir)
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "stage3_failed")

    shard_db = work_dir / "shard_candidate.sqlite"  # stage4_rollup.py refuses to write outside ATLAS_WORK_DIR
    steps.append(
        run_step("stage4_rollup", [sys.executable, str(HERE / "stage4_rollup.py"), "--output", str(shard_db)], env, log_dir)
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "stage4_failed")

    merged_db = run_dir / "merged_base.sqlite"
    steps.append(
        run_step(
            "merge_shard",
            [
                sys.executable,
                str(HERE / "merge_stage4_shard_into_base.py"),
                "--base-serving-db",
                str(base_serving_db),
                "--shard-db",
                str(shard_db),
                "--out",
                str(merged_db),
                "--report",
                str(run_dir / "merge_report.json"),
                "--identity-manifest",
                str(run_dir / "incoming_identity_manifest.json"),
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "merge_shard_failed")

    identity_dir = run_dir / "phase_identity"
    identity_dir.mkdir(parents=True, exist_ok=True)
    identity_db = identity_dir / "identity_redirects.sqlite"
    venue_redirect_db = identity_dir / "venue_redirects.sqlite"
    steps.append(
        run_step(
            "build_dj_identity",
            [
                sys.executable,
                str(HERE / "build_serving_identity_redirects.py"),
                "--source-serving-db",
                str(merged_db),
                "--out",
                str(identity_db),
                "--report",
                str(identity_dir / "identity_report.json"),
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "build_dj_identity_failed")

    venue_identity_cmd = [
        sys.executable,
        str(HERE / "build_serving_venue_redirects.py"),
        "--source-serving-db",
        str(merged_db),
        "--out",
        str(venue_redirect_db),
        "--report",
        str(identity_dir / "venue_report.json"),
    ]
    if args.historical_venue_geo is not None:
        venue_identity_cmd += ["--historical-geo", str(args.historical_venue_geo)]
    steps.append(
        run_step(
            "build_venue_identity",
            venue_identity_cmd,
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "build_venue_identity_failed")

    phase2_dir = run_dir / "phase2"
    steps.append(
        run_step(
            "phase2_repair",
            [
                sys.executable,
                str(HERE / "build_date_venue_repair_candidates.py"),
                "--source-serving-db",
                str(merged_db),
                "--out-dir",
                str(phase2_dir),
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "phase2_failed")

    decisions_db = args.weak_decisions_db
    phase3_dir = run_dir / "phase3"
    phase3_cmd = [
        sys.executable,
        str(HERE / "build_canonical_event_candidates.py"),
        "--source-serving-db",
        str(merged_db),
        "--repair-db",
        str(phase2_dir / "date_venue_repair_candidates.sqlite"),
        "--out-dir",
        str(phase3_dir),
        "--identity-db",
        str(identity_db),
        "--venue-redirect-db",
        str(venue_redirect_db),
    ]
    if decisions_db.exists():
        phase3_cmd += ["--merge-decisions-db", str(decisions_db)]
    steps.append(run_step("phase3_canonical", phase3_cmd, env, log_dir))
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "phase3_failed")

    # Adjudicate this run's review pairs, then rebuild immediately so accepted decisions
    # are present in the candidate promoted by this same run.
    steps.append(
        run_step(
            "adjudicate_deterministic",
            [
                sys.executable,
                str(HERE / "adjudicate_weak_key_candidates.py"),
                "--candidates-db",
                str(phase3_dir / "canonical_event_candidates.sqlite"),
                "--decisions-db",
                str(decisions_db),
                "--report",
                str(run_dir / "adjudicate_deterministic_report.json"),
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "adjudicate_deterministic_failed")

    steps.append(
        run_step(
            "adjudicate_llm",
            [
                sys.executable,
                str(HERE / "adjudicate_weak_key_candidates.py"),
                "--mode",
                "llm",
                "--decisions-db",
                str(decisions_db),
                "--batch-size",
                str(CANONICAL_LLM_BATCH_SIZE),
                "--max-cost-rmb",
                str(0 if args.dry_run_backend else args.canonical_llm_budget_rmb),
                "--report",
                str(run_dir / "adjudicate_llm_report.json"),
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "adjudicate_llm_failed")

    phase3_rebuild_cmd = list(phase3_cmd)
    if "--merge-decisions-db" not in phase3_rebuild_cmd:
        phase3_rebuild_cmd += ["--merge-decisions-db", str(decisions_db)]
    steps.append(run_step("phase3_rebuild_with_decisions", phase3_rebuild_cmd, env, log_dir))
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "phase3_rebuild_failed")

    phase3_report = json.loads((phase3_dir / "collapse_report.json").read_text(encoding="utf-8"))
    phase3_gate = phase3_report.get("gate") or {}
    phase3_gate_failures = [
        key
        for key, value in phase3_gate.items()
        if key.endswith("_gate_pass") and value is not True
    ]
    if phase3_gate_failures:
        return finish(
            run_dir,
            steps,
            "phase3_gate_failed",
            extra={
                "export_report": export_report,
                "merged_candidate_db": str(merged_db),
                "phase3_candidate_db": str(phase3_dir / "canonical_event_candidates.sqlite"),
                "phase3_gate": phase3_gate,
                "phase3_gate_failures": phase3_gate_failures,
                "phase3_counts": phase3_report.get("counts"),
            },
        )

    canonical_events_db = phase3_dir / "canonical_event_candidates.sqlite"
    materialized_db = run_dir / "canonical_serving_candidate.sqlite"
    materialize_report_path = run_dir / "canonical_materialize_report.json"
    steps.append(
        run_step(
            "materialize_canonical_serving",
            [
                sys.executable,
                str(HERE / "materialize_canonical_serving.py"),
                "--candidate-serving-db",
                str(merged_db),
                "--canonical-events-db",
                str(canonical_events_db),
                "--identity-db",
                str(identity_db),
                "--venue-redirect-db",
                str(venue_redirect_db),
                "--out",
                str(materialized_db),
                "--report",
                str(materialize_report_path),
                "--replace",
            ],
            env,
            log_dir,
        )
    )
    if steps[-1]["returncode"] != 0:
        return finish(run_dir, steps, "materialize_canonical_serving_failed")

    canonical_gate_path = run_dir / "canonical_gate_report.json"
    steps.append(
        run_step(
            "canonical_gate",
            [
                sys.executable,
                str(HERE / "materialize_canonical_serving.py"),
                "--verify-candidate",
                str(materialized_db),
                "--report",
                str(canonical_gate_path),
            ],
            env,
            log_dir,
        )
    )
    canonical_gate = (
        json.loads(canonical_gate_path.read_text(encoding="utf-8"))
        if canonical_gate_path.is_file()
        else {"pass": False, "failures": ["gate_report_missing"]}
    )
    if steps[-1]["returncode"] != 0 or not canonical_pipeline_ready(steps, canonical_gate):
        return finish(
            run_dir,
            steps,
            "canonical_gate_failed",
            extra={
                "canonical_serving_candidate": str(materialized_db),
                "canonical_gate": canonical_gate,
            },
        )

    if args.advance_checkpoint:
        new_checkpoint = run_dir / "seen_tokens_updated.txt"
        steps.append(
            run_step(
                "advance_checkpoint",
                [
                    sys.executable,
                    str(HERE / "merge_sanji_seen_tokens.py"),
                    "--token-file",
                    str(args.seen_tokens_file),
                    "--manifest-root",
                    str(manifest_dir),
                    "--out-token-file",
                    str(new_checkpoint),
                ],
                env,
                log_dir,
            )
        )
        if steps[-1]["returncode"] != 0:
            return finish(run_dir, steps, "checkpoint_advance_failed")
        try:
            cumulative_state = promote_checkpoint_and_candidate_state(
                new_checkpoint,
                args.seen_tokens_file,
                materialized_db,
                args.candidate_state_file,
                run_dir,
            )
            steps.append(
                {
                    "name": "promote_checkpoint",
                    "returncode": 0,
                    "source": str(new_checkpoint),
                    "target": str(args.seen_tokens_file),
                }
            )
            steps.append(
                {
                    "name": "promote_cumulative_candidate_state",
                    "returncode": 0,
                    "candidate_db": str(materialized_db),
                    "state_file": str(args.candidate_state_file),
                }
            )
        except OSError as exc:
            steps.append(
                {
                    "name": "promote_checkpoint_and_candidate_state",
                    "returncode": 1,
                    "source": str(new_checkpoint),
                    "target": str(args.seen_tokens_file),
                    "candidate_db": str(materialized_db),
                    "state_file": str(args.candidate_state_file),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return finish(run_dir, steps, "cumulative_state_promote_failed")

    return finish(
        run_dir,
        steps,
        "ok",
        extra={
            "export_report": export_report,
            "merged_candidate_db": str(merged_db),
            "phase3_candidate_db": str(phase3_dir / "canonical_event_candidates.sqlite"),
            "canonical_serving_candidate": str(materialized_db),
            "canonical_gate": canonical_gate,
            "phase3_gate": phase3_report.get("gate"),
            "phase3_counts": phase3_report.get("counts"),
            "extraction_completion_gate": extraction_gate,
            "base_serving_db": str(base_serving_db),
            "candidate_state_file": str(args.candidate_state_file),
            **({"cumulative_candidate_state": cumulative_state} if args.advance_checkpoint else {}),
        },
    )


def finish(run_dir: Path, steps: list[dict[str, Any]], status: str, extra: dict[str, Any] | None = None) -> int:
    summary = {
        "schema_version": "atlas_v2_sanji_import_run.v1",
        "generated_at": now_iso(),
        "run_dir": str(run_dir),
        "status": status,
        "steps": steps,
        **(extra or {}),
    }
    write_json(run_dir / "run_summary.json", summary)
    print(f"\n=== run {status} === summary: {run_dir / 'run_summary.json'}")
    return 0 if status in ("ok", "noop_no_new_articles") else 1


if __name__ == "__main__":
    sys.exit(main())
