#!/usr/bin/env python3
"""Run remaining paid Dajiala waves and consume successes downstream.

This is a controlled long-run executor for the Stage7 paid-image lane. It only
selects unconsumed signed long-link queue rows, never retries failed rows, and
keeps all write surfaces explicit: Dajiala archive output, local report files,
Qdrant poster staging, and Neo4j OCR entity staging.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from build_dajiala_paid_wave_execution_packet import build_packet  # noqa: E402
from select_dajiala_archive_successes import select_successes  # noqa: E402


DEFAULT_OUT_DIR = Path("reports/dajiala_paid_remaining_superlongrun_20260518")
DEFAULT_QUEUE = Path("reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_prioritized_queue.jsonl")
DEFAULT_BASE_POINTER = Path(
    "reports/dajiala_paid_wave01_07_verified_combined_ocr_index_20260518/ocr_file_index_latest.json"
)
DEFAULT_UNIT_COST = 0.03
DEFAULT_WAVE_SIZE = 100
DEFAULT_EMBED_ENDPOINT = "http://127.0.0.1:11441"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> Path:
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path


def tool_rel(path: Path) -> str:
    return (Path("tools/stage7_rewrite") / rel(path)).as_posix()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def wave_no(text: str) -> int:
    match = re.search(r"wave(\d+)", text)
    return int(match.group(1)) if match else 0


def recursive_contains(value: Any, needles: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        low = value.casefold()
        return any(needle.casefold() in low for needle in needles)
    if isinstance(value, dict):
        return any(recursive_contains(item, needles) for item in value.values())
    if isinstance(value, list):
        return any(recursive_contains(item, needles) for item in value)
    return False


def status_has_balance_blocker(status: dict[str, Any]) -> bool:
    return recursive_contains(status, ("amount_not_enough", "not enough", "金额不足", "余额不足", "请充值", "recharge"))


def discover_wave_queue_paths() -> list[Path]:
    paths: list[Path] = []
    base = ROOT / "reports/dajiala_paid_prioritized_queue_20260516"
    paths.extend(base.glob("dajiala_paid_next100*.jsonl"))
    for path in (ROOT / "reports").glob("dajiala_paid_wave*_execution_packet_*/dajiala_paid_wave*.jsonl"):
        paths.append(path)
    unique = {str(path.resolve()): path for path in paths if path.exists()}
    return sorted(unique.values(), key=lambda item: (wave_no(item.as_posix()), item.as_posix()))


def next_wave_id() -> str:
    numbers = [wave_no(path.as_posix()) for path in discover_wave_queue_paths()]
    return f"wave{max(numbers + [7]) + 1:02d}"


def latest_incomplete_packet() -> dict[str, Any] | None:
    packet_paths = sorted(
        (ROOT / "reports").glob("dajiala_paid_wave*_execution_packet_20260518/dajiala_paid_wave_execution_packet.json"),
        key=lambda item: wave_no(item.as_posix()),
    )
    for packet_path in packet_paths:
        packet = read_json(packet_path)
        if int(packet.get("selected_rows") or 0) <= 0:
            continue
        status = read_json(ROOT / str(packet.get("status_path") or ""))
        wave_id = str(packet.get("wave_id") or "")
        archive_root = ROOT / str(packet.get("archive_out_dir") or "")
        downstream_index = ROOT / f"reports/dajiala_paid_{wave_id}_ocr_index_20260518/ocr_file_index_summary.json"
        image_split = archive_root / "dajiala_success_image_split_summary.json"
        if status.get("status") != "completed":
            return packet
        if int(status.get("succeededCount") or 0) > 0 and (not image_split.exists() or not downstream_index.exists()):
            return packet
    return None


def normalized_executable(args: list[str]) -> list[str]:
    if os.name == "nt" and args:
        if args[0].lower() == "npm":
            resolved = shutil.which("npm.cmd") or shutil.which("npm")
            if resolved:
                return [resolved, *args[1:]]
        if args[0].lower() == "npx":
            resolved = shutil.which("npx.cmd") or shutil.which("npx")
            if resolved:
                return [resolved, *args[1:]]
    return args


def run_cmd(args: list[str], *, cwd: Path, log_path: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    args = normalized_executable(args)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write("\n\n## %s\n" % now_iso())
        log.write("cwd=%s\n" % cwd)
        log.write("cmd=%s\n" % " ".join(args))
        log.flush()
        result = subprocess.run(args, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, text=True)
        log.write("exit_code=%s\n" % result.returncode)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed rc={result.returncode}; log={log_path}")
    return result


def account_name(row: dict[str, Any]) -> str:
    return str(
        row.get("account_key")
        or row.get("source_account")
        or row.get("account")
        or row.get("accountKey")
        or ""
    ).strip()


def filter_queue_path(queue_path: Path, excluded_accounts: set[str], out_dir: Path) -> Path:
    if not excluded_accounts:
        return queue_path
    rows = read_jsonl(ROOT / queue_path if not queue_path.is_absolute() else queue_path)
    kept = [row for row in rows if account_name(row) not in excluded_accounts]
    filtered_path = out_dir / "filtered_queue" / "dajiala_paid_filtered_queue.jsonl"
    write_jsonl(filtered_path, kept)
    return rel(filtered_path)


def packet_accounts(packet: dict[str, Any]) -> Counter[str]:
    queue_path = ROOT / str(packet.get("selected_queue_path") or "")
    rows = read_jsonl(queue_path)
    return Counter(account_name(row) for row in rows if account_name(row))


def build_or_resume_wave(
    limit: int,
    unit_cost: float,
    paid_authorized: bool,
    queue_path: Path,
    excluded_accounts: set[str],
    out_dir: Path,
) -> dict[str, Any]:
    pending = latest_incomplete_packet()
    if pending:
        accounts = packet_accounts(pending)
        excluded_count = sum(count for account, count in accounts.items() if account in excluded_accounts)
        total_count = sum(accounts.values())
        if accounts and excluded_accounts and total_count and excluded_count / total_count >= 0.8:
            # Do not resume a packet dominated by a now-excluded low-ROI
            # account segment. It remains on disk as evidence.
            pending = None
    if pending:
        return pending
    wave_id = next_wave_id()
    out_dir = Path(f"reports/dajiala_paid_{wave_id}_execution_packet_20260518")
    return build_packet(
        queue_path=queue_path,
        used_queue_paths=[rel(path) for path in discover_wave_queue_paths()],
        out_dir=out_dir,
        wave_id=wave_id,
        limit=limit,
        unit_cost=unit_cost,
        paid_authorized=paid_authorized,
    )


def split_image_manifest(
    *,
    success_manifest: Path,
    archive_status: dict[str, Any],
    archive_root: Path,
    with_images: Path,
    no_images: Path,
    summary_path: Path,
) -> dict[str, Any]:
    rows = read_jsonl(success_manifest)
    items = {
        (str(item.get("accountKey") or ""), str(item.get("token") or "")): item
        for item in archive_status.get("items") or []
        if isinstance(item, dict)
    }
    image_rows: list[dict[str, Any]] = []
    empty_rows: list[dict[str, Any]] = []
    image_counts: list[int] = []
    for row in rows:
        key = (str(row.get("account_key") or row.get("source_account") or row.get("account") or ""), str(row.get("token") or ""))
        item = items.get(key) or {}
        out_dir = Path(str(item.get("outDir") or ""))
        if not out_dir:
            out_dir = archive_root / key[0] / key[1]
        assets = read_json(out_dir / "assets_local.json")
        images = assets.get("images") if isinstance(assets.get("images"), list) else []
        count = len(images)
        image_counts.append(count)
        enriched = {**row, "archive_out_dir": str(out_dir), "archive_asset_image_count": count}
        if count > 0:
            image_rows.append(enriched)
        else:
            empty_rows.append(enriched)
    write_jsonl(with_images, image_rows)
    write_jsonl(no_images, empty_rows)
    summary = {
        "schema_version": "stage7_dajiala_success_image_split.v1",
        "generated_at": now_iso(),
        "input_success_rows": len(rows),
        "with_images": len(image_rows),
        "no_images": len(empty_rows),
        "image_bearing_rate": round(len(image_rows) / len(rows), 6) if rows else 0.0,
        "min_images": min(image_counts) if image_counts else 0,
        "max_images": max(image_counts) if image_counts else 0,
        "outputs": {
            "with_images": str(with_images),
            "no_images": str(no_images),
            "summary": str(summary_path),
        },
    }
    write_json(summary_path, summary)
    return summary


def consume_wave(packet: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    wave_id = str(packet["wave_id"])
    wave_log = out_dir / "logs" / f"{wave_id}.log"
    runner = ROOT / str(packet["runner_path"])
    run_cmd(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner)], cwd=ROOT, log_path=wave_log)

    archive_root = ROOT / str(packet["archive_out_dir"])
    status_path = ROOT / str(packet["status_path"])
    status = read_json(status_path)
    if status.get("status") != "completed":
        raise RuntimeError(f"{wave_id} archive did not complete: {status_path}")
    if status_has_balance_blocker(status):
        raise RuntimeError(f"{wave_id} hit current Dajiala balance/recharge blocker; status={status_path}")

    total = int(status.get("totalItems") or 0)
    succeeded = int(status.get("succeededCount") or 0)
    failed = int(status.get("failedCount") or 0)
    success_rate = (succeeded / total) if total else 0.0

    success_manifest = archive_root / "dajiala_success_manifest.jsonl"
    rejected_manifest = archive_root / "dajiala_rejected_manifest.jsonl"
    select_successes(
        ROOT / str(packet["selected_queue_path"]),
        status_path,
        success_manifest,
        rejected_manifest,
        archive_root / "dajiala_success_selection_summary.json",
    )

    if succeeded:
        run_cmd(
            [
                "npm",
                "run",
                "download-archive-assets-batch",
                "--",
                "--inputDir",
                tool_rel(archive_root),
                "--manifestPath",
                tool_rel(success_manifest),
                "--statusPath",
                tool_rel(archive_root / "asset-retention-status.json"),
                "--resultLogPath",
                tool_rel(archive_root / "asset-retention-results.jsonl"),
                "--resume",
            ],
            cwd=REPO_ROOT,
            log_path=wave_log,
        )

    split = split_image_manifest(
        success_manifest=success_manifest,
        archive_status=status,
        archive_root=archive_root,
        with_images=archive_root / "dajiala_success_with_images_manifest.jsonl",
        no_images=archive_root / "dajiala_success_no_images_manifest.jsonl",
        summary_path=archive_root / "dajiala_success_image_split_summary.json",
    )

    process_root = ROOT / f"reports/dajiala_paid_{wave_id}_process_20260518"
    if split["with_images"]:
        run_cmd(
            [
                "npm",
                "run",
                "process-batch",
                "--",
                "--inputDir",
                tool_rel(archive_root),
                "--outDir",
                tool_rel(process_root),
                "--inputMode",
                "archive",
                "--manifestPath",
                tool_rel(archive_root / "dajiala_success_with_images_manifest.jsonl"),
                "--statusPath",
                tool_rel(process_root / "batch-status.json"),
                "--concurrency",
                "2",
                "--resume",
            ],
            cwd=REPO_ROOT,
            log_path=wave_log,
        )
        run_cmd(
            [
                "npm",
                "run",
                "ocr-poster-batch",
                "--",
                "--artifactRoot",
                tool_rel(process_root),
                "--archiveRoot",
                tool_rel(archive_root),
                "--onlyQuality",
                "ready,review,blocked",
                "--statusPath",
                tool_rel(process_root / "poster-ocr-status.json"),
                "--resultLogPath",
                tool_rel(process_root / "poster-ocr-results.jsonl"),
                "--concurrency",
                "1",
                "--resume",
            ],
            cwd=REPO_ROOT,
            log_path=wave_log,
        )
        manifest_dir = ROOT / f"reports/dajiala_paid_{wave_id}_ocr_manifest_20260518"
        index_dir = ROOT / f"reports/dajiala_paid_{wave_id}_ocr_index_20260518"
        entity_dir = ROOT / f"reports/dajiala_paid_{wave_id}_ocr_entity_extraction_20260518"
        run_cmd(
            [
                sys.executable,
                "scripts/build_recovered_artifact_manifest.py",
                "--process-root",
                str(rel(process_root)),
                "--out-dir",
                str(rel(manifest_dir)),
            ],
            cwd=ROOT,
            log_path=wave_log,
        )
        run_cmd(
            [
                sys.executable,
                "scripts/build_ocr_file_index.py",
                "--manifest",
                str(rel(manifest_dir / "recovered_manifest.jsonl")),
                "--processed-root",
                str(rel(process_root)),
                "--archive-root",
                str(rel(archive_root)),
                "--out-dir",
                str(rel(index_dir)),
                "--latest-pointer",
                str(rel(index_dir / "ocr_file_index_latest.json")),
                "--build-index",
            ],
            cwd=ROOT,
            log_path=wave_log,
        )
        run_cmd(
            [
                sys.executable,
                "scripts/extract_ocr_entities.py",
                "--pointer",
                str(rel(index_dir / "ocr_file_index_latest.json")),
                "--out-dir",
                str(rel(entity_dir)),
            ],
            cwd=ROOT,
            log_path=wave_log,
        )

    return {
        "wave_id": wave_id,
        "selected_rows": int(packet.get("selected_rows") or 0),
        "estimated_wave_cost": packet.get("estimated_wave_cost"),
        "status_path": str(rel(status_path)),
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "success_rate": round(success_rate, 6),
        "image_rows": split["with_images"],
        "process_root": str(rel(process_root)),
    }


def run_aggregate(out_dir: Path, wave_results: list[dict[str, Any]], embed_endpoint: str) -> dict[str, Any]:
    log_path = out_dir / "logs" / "aggregate.log"
    pointers = [DEFAULT_BASE_POINTER]
    for result in wave_results:
        wave_id = result["wave_id"]
        pointer = ROOT / f"reports/dajiala_paid_{wave_id}_ocr_index_20260518/ocr_file_index_latest.json"
        if pointer.exists():
            pointers.append(rel(pointer))

    combined_dir = ROOT / "reports/dajiala_paid_latest_verified_combined_ocr_index_20260518"
    cmd = [sys.executable, "scripts/combine_ocr_file_indexes.py"]
    for pointer in pointers:
        cmd.extend(["--pointer", str(pointer)])
    cmd.extend(["--out-dir", str(rel(combined_dir))])
    run_cmd(cmd, cwd=ROOT, log_path=log_path)

    jobs_dir = ROOT / "reports/dajiala_paid_latest_verified_poster_text_vector_jobs_20260518"
    run_cmd(
        [
            sys.executable,
            "scripts/build_poster_text_vector_jobs.py",
            "--pointer",
            str(rel(combined_dir / "ocr_file_index_latest.json")),
            "--out-dir",
            str(rel(jobs_dir)),
            "--min-text-chars",
            "4",
            "--endpoint",
            embed_endpoint,
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    previous_embeddings = ROOT / "reports/dajiala_paid_wave01_07_verified_poster_text_vector_jobs_20260518/poster_text_embeddings.jsonl"
    latest_embeddings = jobs_dir / "poster_text_embeddings.jsonl"
    if previous_embeddings.exists() and not latest_embeddings.exists():
        shutil.copyfile(previous_embeddings, latest_embeddings)
    run_cmd(
        [
            sys.executable,
            "-m",
            "stage7.vector_plan.embed_runner",
            "--jobs",
            str(rel(jobs_dir / "poster_text_vector_jobs.jsonl")),
            "--embeddings",
            str(rel(latest_embeddings)),
            "--failures",
            str(rel(jobs_dir / "poster_text_embedding_failures.jsonl")),
            "--resume",
            "--batch-size",
            "1",
            "--concurrency",
            "4",
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    qdrant_dir = ROOT / "reports/qdrant_poster_staging_latest_20260518"
    run_cmd(
        [
            sys.executable,
            "scripts/qdrant_poster_staging_writer.py",
            "--mode",
            "build",
            "--embeddings",
            str(rel(latest_embeddings)),
            "--out-dir",
            str(rel(qdrant_dir)),
            "--confirm-token",
            "ENABLE_QDRANT_POSTER_STAGING_WRITE",
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    poster_gate_dir = ROOT / "reports/poster_vector_write_gate_packet_latest_20260518"
    run_cmd(
        [
            sys.executable,
            "scripts/build_poster_vector_write_gate_packet.py",
            "--poster-jobs",
            str(rel(jobs_dir / "poster_text_vector_jobs_summary.json")),
            "--poster-staging-report",
            str(rel(qdrant_dir / "qdrant_poster_staging_report.json")),
            "--out-dir",
            str(rel(poster_gate_dir)),
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    entity_dir = ROOT / "reports/dajiala_paid_latest_verified_ocr_entity_extraction_20260518"
    run_cmd(
        [
            sys.executable,
            "scripts/extract_ocr_entities.py",
            "--pointer",
            str(rel(combined_dir / "ocr_file_index_latest.json")),
            "--out-dir",
            str(rel(entity_dir)),
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    merge_plan_dir = ROOT / "reports/dajiala_paid_latest_verified_ocr_entity_merge_plan_20260518"
    run_id = "stage7_dajiala_paid_latest_20260518"
    run_cmd(
        [
            sys.executable,
            "scripts/merge_ocr_entities_to_neo4j.py",
            "--mode",
            "dry-run",
            "--ocr-entities",
            str(rel(entity_dir / "ocr_entities.jsonl")),
            "--neo4j-run-id",
            run_id,
            "--out-dir",
            str(rel(merge_plan_dir)),
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    review_dir = ROOT / "reports/dajiala_paid_latest_verified_ocr_entity_merge_review_packet_20260518"
    run_cmd(
        [
            sys.executable,
            "scripts/build_ocr_entity_merge_review_packet.py",
            "--entity-extraction",
            str(rel(entity_dir / "ocr_entity_extraction_summary.json")),
            "--merge-report",
            str(rel(merge_plan_dir / "ocr_entity_merge_report.json")),
            "--out-dir",
            str(rel(review_dir)),
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    merge_apply_dir = ROOT / "reports/dajiala_paid_latest_verified_ocr_entity_merge_20260518"
    run_cmd(
        [
            sys.executable,
            "scripts/merge_ocr_entities_to_neo4j.py",
            "--mode",
            "apply",
            "--ocr-entities",
            str(rel(entity_dir / "ocr_entities.jsonl")),
            "--neo4j-run-id",
            run_id,
            "--review-packet",
            str(rel(review_dir / "ocr_entity_merge_review_packet.json")),
            "--out-dir",
            str(rel(merge_apply_dir)),
            "--confirm-token",
            "ENABLE_NEO4J_OCR_ENTITY_STAGING_WRITE",
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    entity_gate_dir = ROOT / "reports/ocr_entity_merge_write_gate_packet_latest_20260518"
    run_cmd(
        [
            sys.executable,
            "scripts/build_ocr_entity_merge_write_gate_packet.py",
            "--entity-extraction",
            str(rel(entity_dir / "ocr_entity_extraction_summary.json")),
            "--merge-report",
            str(rel(merge_plan_dir / "ocr_entity_merge_report.json")),
            "--review-packet",
            str(rel(review_dir / "ocr_entity_merge_review_packet.json")),
            "--staging-report",
            str(rel(merge_apply_dir / "ocr_entity_merge_report.json")),
            "--out-dir",
            str(rel(entity_gate_dir)),
        ],
        cwd=ROOT,
        log_path=log_path,
    )

    combined_summary = read_json(combined_dir / "ocr_file_index_summary.json")
    jobs_summary = read_json(jobs_dir / "poster_text_vector_jobs_summary.json")
    qdrant_summary = read_json(qdrant_dir / "qdrant_poster_staging_report.json")
    entity_summary = read_json(entity_dir / "ocr_entity_extraction_summary.json")
    merge_summary = read_json(merge_apply_dir / "ocr_entity_merge_report.json")
    return {
        "combined_index_records": combined_summary.get("record_count"),
        "poster_vector_jobs": jobs_summary.get("job_count"),
        "qdrant_written_count": qdrant_summary.get("written_count"),
        "qdrant_self_hit_rate": qdrant_summary.get("self_hit_rate"),
        "ocr_entity_count": entity_summary.get("entity_count"),
        "neo4j_nodes_written": merge_summary.get("nodes_written"),
        "paths": {
            "combined_index": str(rel(combined_dir / "ocr_file_index_summary.json")),
            "poster_jobs": str(rel(jobs_dir / "poster_text_vector_jobs_summary.json")),
            "qdrant": str(rel(qdrant_dir / "qdrant_poster_staging_report.json")),
            "poster_gate": str(rel(poster_gate_dir / "poster_vector_write_gate_packet.json")),
            "ocr_entities": str(rel(entity_dir / "ocr_entity_extraction_summary.json")),
            "neo4j_merge": str(rel(merge_apply_dir / "ocr_entity_merge_report.json")),
            "entity_gate": str(rel(entity_gate_dir / "ocr_entity_merge_write_gate_packet.json")),
        },
    }


def build_summary(out_dir: Path, payload: dict[str, Any]) -> None:
    write_json(out_dir / "dajiala_paid_remaining_superlongrun_status.json", payload)
    lines = [
        "# Dajiala Paid Remaining Superlongrun",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- decision: `{payload['decision']}`",
        f"- waves_executed: `{len(payload['waves'])}`",
        f"- selected_rows: `{payload['totals']['selected_rows']}`",
        f"- succeeded: `{payload['totals']['succeeded']}`",
        f"- failed: `{payload['totals']['failed']}`",
        f"- estimated_cost: `{payload['totals']['estimated_cost']}`",
        "",
        "## Waves",
        "",
    ]
    for wave in payload["waves"]:
        lines.append(
            f"- `{wave['wave_id']}` selected=`{wave['selected_rows']}` succeeded=`{wave['succeeded']}` "
            f"failed=`{wave['failed']}` success_rate=`{wave['success_rate']}`"
        )
    lines.extend(["", "## Aggregate", ""])
    for key, value in (payload.get("aggregate") or {}).items():
        if key != "paths":
            lines.append(f"- `{key}`: `{value}`")
    (out_dir / "dajiala_paid_remaining_superlongrun_status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--wave-size", type=int, default=DEFAULT_WAVE_SIZE)
    parser.add_argument("--unit-cost", type=float, default=DEFAULT_UNIT_COST)
    parser.add_argument("--max-waves", type=int, default=0, help="0 means run until no unconsumed rows remain")
    parser.add_argument("--embed-endpoint", default=DEFAULT_EMBED_ENDPOINT)
    parser.add_argument("--paid-authorized", action="store_true")
    parser.add_argument("--skip-aggregate", action="store_true")
    parser.add_argument("--queue-path", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--exclude-account", action="append", default=[])
    parser.add_argument("--max-consecutive-zero-success-waves", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    os.chdir(ROOT)
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    waves: list[dict[str, Any]] = []
    decision = "running"
    started = now_iso()
    excluded_accounts = {str(item).strip() for item in args.exclude_account if str(item).strip()}
    queue_path = filter_queue_path(args.queue_path, excluded_accounts, out_dir)
    consecutive_zero_success = 0

    try:
        executed = 0
        while True:
            if args.max_waves and executed >= args.max_waves:
                decision = "stopped_by_max_waves"
                break
            if args.max_consecutive_zero_success_waves and consecutive_zero_success >= args.max_consecutive_zero_success_waves:
                decision = "stopped_by_zero_success_stop_loss"
                break
            packet = build_or_resume_wave(
                args.wave_size,
                args.unit_cost,
                args.paid_authorized,
                queue_path,
                excluded_accounts,
                out_dir,
            )
            if not packet.get("next_paid_wave_allowed"):
                decision = "no_more_ready_paid_rows" if not packet.get("selected_rows") else str(packet.get("decision"))
                break
            result = consume_wave(packet, out_dir)
            waves.append(result)
            executed += 1
            consecutive_zero_success = consecutive_zero_success + 1 if int(result["succeeded"]) == 0 else 0
            payload = {
                "schema_version": "stage7_dajiala_paid_remaining_superlongrun.v1",
                "generated_at": now_iso(),
                "started_at": started,
                "decision": "wave_loop_running",
                "waves": waves,
                "totals": {
                    "selected_rows": sum(int(item["selected_rows"]) for item in waves),
                    "succeeded": sum(int(item["succeeded"]) for item in waves),
                    "failed": sum(int(item["failed"]) for item in waves),
                    "estimated_cost": round(sum(float(item["estimated_wave_cost"] or 0) for item in waves), 4),
                },
                "aggregate": {},
                "safety": {
                    "secrets_printed": False,
                    "failed_rows_retried": False,
                    "d_scan": False,
                    "paid_authorized": bool(args.paid_authorized),
                    "excluded_accounts": sorted(excluded_accounts),
                    "queue_path": str(queue_path),
                    "max_consecutive_zero_success_waves": args.max_consecutive_zero_success_waves,
                },
            }
            build_summary(out_dir, payload)
            print(
                json.dumps(
                    {
                        "wave_id": result["wave_id"],
                        "selected": result["selected_rows"],
                        "succeeded": result["succeeded"],
                        "failed": result["failed"],
                        "success_rate": result["success_rate"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            time.sleep(1)

        aggregate: dict[str, Any] = {}
        if waves and not args.skip_aggregate:
            aggregate = run_aggregate(out_dir, waves, args.embed_endpoint)
        payload = {
            "schema_version": "stage7_dajiala_paid_remaining_superlongrun.v1",
            "generated_at": now_iso(),
            "started_at": started,
            "decision": "completed" if decision in {"no_more_ready_paid_rows", "stopped_by_max_waves"} else decision,
            "waves": waves,
            "totals": {
                "selected_rows": sum(int(item["selected_rows"]) for item in waves),
                "succeeded": sum(int(item["succeeded"]) for item in waves),
                "failed": sum(int(item["failed"]) for item in waves),
                "estimated_cost": round(sum(float(item["estimated_wave_cost"] or 0) for item in waves), 4),
            },
            "aggregate": aggregate,
            "safety": {
                "secrets_printed": False,
                "failed_rows_retried": False,
                "d_scan": False,
                "paid_authorized": bool(args.paid_authorized),
                "excluded_accounts": sorted(excluded_accounts),
                "queue_path": str(queue_path),
                "max_consecutive_zero_success_waves": args.max_consecutive_zero_success_waves,
            },
        }
        build_summary(out_dir, payload)
        print(json.dumps({"decision": payload["decision"], "totals": payload["totals"], "aggregate": aggregate}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        payload = {
            "schema_version": "stage7_dajiala_paid_remaining_superlongrun.v1",
            "generated_at": now_iso(),
            "started_at": started,
            "decision": "blocked",
            "error": str(exc),
            "waves": waves,
            "totals": {
                "selected_rows": sum(int(item["selected_rows"]) for item in waves),
                "succeeded": sum(int(item["succeeded"]) for item in waves),
                "failed": sum(int(item["failed"]) for item in waves),
                "estimated_cost": round(sum(float(item["estimated_wave_cost"] or 0) for item in waves), 4),
            },
            "aggregate": {},
            "safety": {
                "secrets_printed": False,
                "failed_rows_retried": False,
                "d_scan": False,
                "paid_authorized": bool(args.paid_authorized),
                "excluded_accounts": sorted(excluded_accounts),
                "queue_path": str(queue_path),
                "max_consecutive_zero_success_waves": args.max_consecutive_zero_success_waves,
            },
        }
        build_summary(out_dir, payload)
        print(json.dumps({"decision": "blocked", "error": str(exc), "status": str(out_dir / "dajiala_paid_remaining_superlongrun_status.json")}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
