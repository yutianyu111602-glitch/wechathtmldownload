#!/usr/bin/env python3
"""Deterministic Flash routing scorer for the DeepSeek hybrid Stage7 plan.

Reads Flash pilot JSONL artifacts and writes report-only routing queues.
It does not call LLMs and does not write Stage7 state, Qdrant, Neo4j,
production SQLite, or vector collections.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def clean_prompt_account(source_account: str) -> str:
    """Normalize prefixed account names (e.g. full_empty_wave_...__AXIS -> AXIS)."""
    value = str(source_account or "").strip()
    if "__" in value:
        suffix = value.split("__", 1)[1].strip()
        if suffix:
            return suffix
    return value


DEFAULT_HIGH_VALUE_ACCOUNTS = {
    "44KW",
    "ALL Club",
    "All Club",
    "All俱乐部",
    "AXIS",
    "Dada Beijing",
    "Dada Shanghai",
    "Elevator",
    "OIL",
    "OIL油",
    "PILLBOX",
    "SYSTEM",
    "TAG",
    "ZhaoDai",
    "wigwam",
}

DECISION_FILES = {
    "accept_flash": "accepted.jsonl",
    "pro_reextract": "pro_candidates.jsonl",
    "mac_gpt_triage": "mac_gpt_triage_candidates.jsonl",
    "deterministic_repair": "repair_candidates.jsonl",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                rows.append(
                    {
                        "sample_id": f"json_error_{path.name}_{line_no}",
                        "fatal_error": "JSONDecodeError",
                        "_source_path": str(path),
                        "_source_line": line_no,
                    }
                )
                continue
            if isinstance(row, dict):
                row["_source_path"] = str(path)
                row["_source_line"] = line_no
                rows.append(row)
    return rows


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def compact_text(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def chunk_sum(row: dict[str, Any], key: str) -> int:
    total = 0
    for chunk in row.get("chunks") or []:
        if isinstance(chunk, dict):
            total += int_value(chunk.get(key))
    return total


def evidence_sum(row: dict[str, Any], key: str) -> int:
    total = 0
    for chunk in row.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        evidence = chunk.get("evidence") or {}
        if isinstance(evidence, dict):
            total += int_value(evidence.get(key))
    return total


def validation_errors(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for chunk in row.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        for error in chunk.get("validation_errors") or []:
            errors.append(str(error))
    return errors


def total_metric(row: dict[str, Any], key: str, *, fallback_chunk_key: str | None = None) -> int:
    totals = row.get("totals") or {}
    if isinstance(totals, dict) and key in totals:
        return int_value(totals.get(key))
    if fallback_chunk_key:
        return chunk_sum(row, fallback_chunk_key)
    return 0


def evidence_metric(row: dict[str, Any], key: str) -> int:
    totals = row.get("totals") or {}
    if isinstance(totals, dict) and key in totals:
        return int_value(totals.get(key))
    return evidence_sum(row, key)


def compute_metrics(row: dict[str, Any], *, high_value_accounts: set[str], image_heavy_min_images: int) -> dict[str, Any]:
    chunks = row.get("chunks") or []
    chunk_count = int_value(row.get("chunk_count"), len(chunks))
    ok_chunks = int_value(row.get("ok_chunks"), chunk_sum(row, "api_ok"))
    parse_ok_chunks = int_value(row.get("parse_ok_chunks"), chunk_sum(row, "parse_ok"))
    schema_ok_chunks = int_value(row.get("schema_ok_chunks"), chunk_sum(row, "schema_ok"))

    api_ok = not row.get("fatal_error") and chunk_count > 0 and ok_chunks == chunk_count
    parse_ok = api_ok and parse_ok_chunks == chunk_count
    schema_ok = parse_ok and schema_ok_chunks == chunk_count

    entities = total_metric(row, "entities", fallback_chunk_key="entities_count")
    events = total_metric(row, "events", fallback_chunk_key="events_count")
    relations = total_metric(row, "relations", fallback_chunk_key="relations_count")
    claims = total_metric(row, "claims", fallback_chunk_key="claims_count")
    evidence_total = evidence_metric(row, "evidence_total")
    evidence_hit = evidence_metric(row, "evidence_hit")
    evidence_miss = evidence_metric(row, "evidence_miss")
    evidence_hit_rate = 1.0 if evidence_total <= 0 else evidence_hit / max(evidence_total, 1)
    errors = validation_errors(row)
    title_pseudoquote_count = sum(1 for item in errors if "title_pseudoquote" in item)
    non_exact_evidence_count = sum(1 for item in errors if "evidence_not_exact_substring" in item)

    source_account = str(row.get("source_account") or "")
    output_count = entities + events
    local_image_count = int_value(row.get("local_image_count"))
    return {
        "api_ok": api_ok,
        "parse_ok": parse_ok,
        "schema_ok": schema_ok,
        "chunk_count": chunk_count,
        "ok_chunks": ok_chunks,
        "parse_ok_chunks": parse_ok_chunks,
        "schema_ok_chunks": schema_ok_chunks,
        "entities": entities,
        "events": events,
        "relations": relations,
        "claims": claims,
        "output_count": output_count,
        "zero_both": output_count == 0,
        "input_chars": int_value(row.get("input_chars")),
        "local_image_count": local_image_count,
        "image_heavy": local_image_count >= image_heavy_min_images,
        "evidence_total": evidence_total,
        "evidence_hit": evidence_hit,
        "evidence_miss": evidence_miss,
        "evidence_hit_rate": round(evidence_hit_rate, 6),
        "title_pseudoquote_count": title_pseudoquote_count,
        "non_exact_evidence_count": non_exact_evidence_count,
        "high_value_account": clean_prompt_account(source_account) in high_value_accounts,
    }


def route_row(
    row: dict[str, Any],
    *,
    high_value_accounts: set[str],
    long_chars: int,
    zero_both_min_chars: int,
    evidence_pro_threshold: float,
    accept_evidence_threshold: float,
    image_heavy_min_images: int,
) -> dict[str, Any]:
    metrics = compute_metrics(row, high_value_accounts=high_value_accounts, image_heavy_min_images=image_heavy_min_images)
    pro_reasons: list[str] = []
    if row.get("fatal_error") or not metrics["api_ok"]:
        pro_reasons.append("api_failed")
    elif not metrics["parse_ok"]:
        pro_reasons.append("parse_failed")
    if metrics["zero_both"] and metrics["input_chars"] > zero_both_min_chars:
        pro_reasons.append("zero_both_body")
    if metrics["high_value_account"] and metrics["output_count"] <= 1:
        pro_reasons.append("high_value_low_output")

    repair_reasons: list[str] = []
    if metrics["parse_ok"] and not metrics["schema_ok"]:
        repair_reasons.append("schema_repair_needed")
    if metrics["title_pseudoquote_count"]:
        repair_reasons.append("title_pseudoquote")
    if metrics["non_exact_evidence_count"]:
        repair_reasons.append("non_exact_evidence")
    if (
        metrics["parse_ok"]
        and metrics["output_count"] > 0
        and metrics["evidence_total"] > 0
        and metrics["evidence_hit_rate"] < evidence_pro_threshold
    ):
        repair_reasons.append("low_evidence_hit_rate")

    triage_reasons: list[str] = []
    if metrics["image_heavy"] and metrics["input_chars"] > zero_both_min_chars and metrics["output_count"] <= 1:
        triage_reasons.append("image_heavy_low_output")
    if metrics["input_chars"] > zero_both_min_chars and metrics["output_count"] <= 1:
        triage_reasons.append("entities_events_too_low")
    if metrics["input_chars"] > long_chars and metrics["output_count"] <= 1:
        triage_reasons.append("long_article_low_output")

    if pro_reasons:
        decision = "pro_reextract"
        reasons = pro_reasons
    elif repair_reasons:
        decision = "deterministic_repair"
        reasons = repair_reasons
    elif triage_reasons:
        decision = "mac_gpt_triage"
        reasons = triage_reasons
    elif metrics["parse_ok"] and metrics["schema_ok"] and metrics["evidence_hit_rate"] >= accept_evidence_threshold and metrics["output_count"] > 0:
        decision = "accept_flash"
        reasons = ["clean_nonempty"]
    else:
        decision = "mac_gpt_triage"
        reasons = ["boundary_uncertain"]

    return {
        "sample_id": str(row.get("sample_id") or ""),
        "article_uid": str(row.get("article_uid") or ""),
        "source_account": str(row.get("source_account") or ""),
        "article_id": str(row.get("article_id") or ""),
        "title": compact_text(row.get("title"), 240),
        "input_chars": metrics["input_chars"],
        "quality_grade": str(row.get("quality_grade") or ""),
        "local_image_count": metrics["local_image_count"],
        "bucket": str(row.get("bucket") or ""),
        "llm_input_path": str(row.get("llm_input_path") or ""),
        "meta_path": str(row.get("meta_path") or ""),
        "metrics": metrics,
        "routing": {
            "decision": decision,
            "reasons": reasons,
            "source_path": str(row.get("_source_path") or ""),
            "source_line": int_value(row.get("_source_line")),
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def decision_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        decision = str((record.get("routing") or {}).get("decision") or "")
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def aggregate_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    chunk_count = sum(int_value((item.get("metrics") or {}).get("chunk_count")) for item in records)
    ok_chunks = sum(int_value((item.get("metrics") or {}).get("ok_chunks")) for item in records)
    parse_ok_chunks = sum(int_value((item.get("metrics") or {}).get("parse_ok_chunks")) for item in records)
    schema_ok_chunks = sum(int_value((item.get("metrics") or {}).get("schema_ok_chunks")) for item in records)
    evidence_total = sum(int_value((item.get("metrics") or {}).get("evidence_total")) for item in records)
    evidence_hit = sum(int_value((item.get("metrics") or {}).get("evidence_hit")) for item in records)
    zero_both = sum(1 for item in records if (item.get("metrics") or {}).get("zero_both"))
    return {
        "rows": total,
        "chunk_count": chunk_count,
        "api_ok_rate": round(ok_chunks / max(chunk_count, 1), 4),
        "parse_ok_rate": round(parse_ok_chunks / max(ok_chunks, 1), 4),
        "schema_ok_rate": round(schema_ok_chunks / max(parse_ok_chunks, 1), 4),
        "evidence_hit_rate": round(evidence_hit / max(evidence_total, 1), 4) if evidence_total else 1.0,
        "zero_both_count": zero_both,
        "zero_both_rate": round(zero_both / max(total, 1), 4),
        "long_article_count": sum(1 for item in records if "long_article" in (item.get("routing") or {}).get("reasons", [])),
        "high_value_low_output_count": sum(
            1 for item in records if "high_value_low_output" in (item.get("routing") or {}).get("reasons", [])
        ),
    }


def write_markdown_summary(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# DeepSeek Hybrid Flash Score Summary",
        "",
        f"- generated_at: {summary['generated_at']}",
        f"- processed_rows: {summary['processed_rows']}",
        f"- pro_upgrade_ratio: {summary['pro_upgrade_ratio']}",
        f"- target_band_status: {summary['target_band_status']}",
        "",
        "## Decision Counts",
        "",
    ]
    for decision, count in summary["decision_counts"].items():
        lines.append(f"- {decision}: {count}")
    lines.extend(
        [
            "",
            "## Gates",
            "",
            f"- api_ok_rate: {summary['aggregate_metrics']['api_ok_rate']}",
            f"- parse_ok_rate: {summary['aggregate_metrics']['parse_ok_rate']}",
            f"- schema_ok_rate: {summary['aggregate_metrics']['schema_ok_rate']}",
            f"- evidence_hit_rate: {summary['aggregate_metrics']['evidence_hit_rate']}",
            f"- zero_both_rate: {summary['aggregate_metrics']['zero_both_rate']}",
            "",
            "## Writes",
            "",
        ]
    )
    for name, output_path in summary["outputs"].items():
        lines.append(f"- {name}: `{output_path}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def score_flash_jsonl(
    *,
    flash_jsonl_paths: list[Path],
    out_dir: Path,
    high_value_accounts: set[str],
    long_chars: int,
    zero_both_min_chars: int,
    evidence_pro_threshold: float,
    accept_evidence_threshold: float,
    image_heavy_min_images: int,
    target_pro_min: float = 0.10,
    target_pro_max: float = 0.20,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    seen_article_uids: set[str] = set()
    duplicate_article_uids = 0
    for path in flash_jsonl_paths:
        for row in read_jsonl(path):
            article_uid = str(row.get("article_uid") or "")
            if article_uid:
                if article_uid in seen_article_uids:
                    duplicate_article_uids += 1
                    continue
                seen_article_uids.add(article_uid)
            records.append(
                route_row(
                    row,
                    high_value_accounts=high_value_accounts,
                    long_chars=long_chars,
                    zero_both_min_chars=zero_both_min_chars,
                    evidence_pro_threshold=evidence_pro_threshold,
                    accept_evidence_threshold=accept_evidence_threshold,
                    image_heavy_min_images=image_heavy_min_images,
                )
            )

    by_decision: dict[str, list[dict[str, Any]]] = {decision: [] for decision in DECISION_FILES}
    for record in records:
        decision = str((record.get("routing") or {}).get("decision") or "mac_gpt_triage")
        by_decision.setdefault(decision, []).append(record)

    outputs: dict[str, str] = {}
    for decision, filename in DECISION_FILES.items():
        path = out_dir / filename
        write_jsonl(path, by_decision.get(decision, []))
        outputs[decision] = str(path)
    all_scored_path = out_dir / "all_scored.jsonl"
    write_jsonl(all_scored_path, records)
    outputs["all_scored"] = str(all_scored_path)

    counts = decision_counts(records)
    pro_ratio = counts.get("pro_reextract", 0) / max(len(records), 1)
    if pro_ratio < target_pro_min:
        target_status = "below_target"
    elif pro_ratio > target_pro_max:
        target_status = "above_target"
    else:
        target_status = "within_target"

    summary = {
        "schema_version": "deepseek_hybrid_scorer.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "writes": "report artifacts only; no Stage7 state/Qdrant/Neo4j/production SQLite writes",
        "source_files": [str(path) for path in flash_jsonl_paths],
        "processed_rows": len(records),
        "duplicate_article_uids_skipped": duplicate_article_uids,
        "decision_counts": counts,
        "pro_upgrade_ratio": round(pro_ratio, 4),
        "target_pro_min": target_pro_min,
        "target_pro_max": target_pro_max,
        "target_band_status": target_status,
        "thresholds": {
            "long_chars": long_chars,
            "zero_both_min_chars": zero_both_min_chars,
            "evidence_pro_threshold": evidence_pro_threshold,
            "accept_evidence_threshold": accept_evidence_threshold,
            "image_heavy_min_images": image_heavy_min_images,
        },
        "aggregate_metrics": aggregate_metrics(records),
        "outputs": outputs,
    }
    summary_path = out_dir / "hybrid_score_summary.json"
    write_json(summary_path, summary)
    outputs["summary_json"] = str(summary_path)
    summary_md_path = out_dir / "hybrid_score_summary.md"
    write_markdown_summary(summary_md_path, summary)
    outputs["summary_md"] = str(summary_md_path)
    write_json(summary_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flash-jsonl", action="append", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--high-value-account", action="append", default=[])
    parser.add_argument("--no-default-high-value-accounts", action="store_true")
    parser.add_argument("--long-chars", type=int, default=5000)
    parser.add_argument("--zero-both-min-chars", type=int, default=512)
    parser.add_argument("--evidence-pro-threshold", type=float, default=0.9)
    parser.add_argument("--accept-evidence-threshold", type=float, default=0.98)
    parser.add_argument("--image-heavy-min-images", type=int, default=2)
    parser.add_argument("--target-pro-min", type=float, default=0.10)
    parser.add_argument("--target-pro-max", type=float, default=0.20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = [Path(value) for value in args.flash_jsonl]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise SystemExit(f"missing flash jsonl(s): {missing}")
    high_value_accounts = set(args.high_value_account or [])
    if not args.no_default_high_value_accounts:
        high_value_accounts.update(DEFAULT_HIGH_VALUE_ACCOUNTS)
    summary = score_flash_jsonl(
        flash_jsonl_paths=paths,
        out_dir=Path(args.out_dir),
        high_value_accounts=high_value_accounts,
        long_chars=args.long_chars,
        zero_both_min_chars=args.zero_both_min_chars,
        evidence_pro_threshold=args.evidence_pro_threshold,
        accept_evidence_threshold=args.accept_evidence_threshold,
        image_heavy_min_images=args.image_heavy_min_images,
        target_pro_min=args.target_pro_min,
        target_pro_max=args.target_pro_max,
    )
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
