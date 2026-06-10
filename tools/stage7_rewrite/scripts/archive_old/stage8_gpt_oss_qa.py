#!/usr/bin/env python3
"""Bounded GPT-OSS QA lane for Stage7/Stage8 vector quality.

This script is intentionally outside the embedding and production writer paths.
It can select low-confidence extracts, call the Mac gpt-oss wrapper over SSH,
sanitize stdout, parse JSON, and write a QA report. It does not write Qdrant,
Neo4j, SQLite, Mem0, or Stage7 roots.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_WRAPPER = "/Users/masher/.openclaw/workspace/model-runs/run-gpt-oss-20b-tq3"
NOISE_PREFIXES = (
    "[INFO]",
    "[transformers]",
    "The following generation flags",
)


@dataclass
class QaSample:
    sample_id: str
    extract_path: str
    category: str
    account: str
    title: str
    article_id: str
    entity_count: int
    event_count: int
    evidence_drop_count: int
    reasons: list[str]
    priority: str
    excerpt: str
    prompt: str


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def compact(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def entities(article: dict[str, Any]) -> list[Any]:
    value = article.get("entities")
    return value if isinstance(value, list) else []


def events(article: dict[str, Any]) -> list[Any]:
    value = article.get("events")
    return value if isinstance(value, list) else []


def quality(article: dict[str, Any]) -> dict[str, Any]:
    value = article.get("quality")
    return value if isinstance(value, dict) else {}


def evidence_drop_count(article: dict[str, Any]) -> int:
    q = quality(article)
    keys = (
        "evidence_non_exact_dropped_count",
        "items_dropped_after_evidence_prune_count",
        "evidence_dropped_count",
    )
    total = 0
    for key in keys:
        try:
            total += int(q.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def has_title_pseudoquote(article: dict[str, Any]) -> bool:
    text = json.dumps(article, ensure_ascii=False)
    return "文章标题:" in text


def classify_sample(article: dict[str, Any]) -> str | None:
    entity_count = len(entities(article))
    event_count = len(events(article))
    drops = evidence_drop_count(article)
    if entity_count == 0 and event_count == 0:
        return "zero_entity_event"
    if drops >= 2:
        return "high_evidence_drop"
    if has_title_pseudoquote(article):
        return "title_pseudoquote"
    if entity_count + event_count <= 2:
        return "low_confidence_map_candidate"
    return None


def build_prompt(sample: QaSample) -> str:
    return (
        "你是地下电子音乐地图的离线QA助手。只输出一行JSON，不要解释，不要analysis，不要Markdown。\n"
        "第一个字符必须是{，最后一个字符必须是}。reason_short最多20个汉字；信息不足就保守判定hold_low_signal。\n"
        "根据给定Stage7抽取摘要和原文片段判断它是否值得进入后续Qwen精确quote补救。\n"
        "JSON字段固定为: has_extractable_music_value(boolean), recommended_action(string), "
        "failure_cause(string), priority(string), scene_tags(array), reason_short(string)。\n"
        "recommended_action只能是 qwen_salvage, deterministic_cleanup, hold_low_signal 之一。\n"
        "failure_cause只能是 quote_not_exact, image_only, metadata_only, input_fragmented, "
        "model_underextracted, low_value 之一。\n"
        f"category={sample.category}\n"
        f"reasons={','.join(sample.reasons)}\n"
        f"priority={sample.priority}\n"
        f"account={sample.account}\n"
        f"title={sample.title}\n"
        f"article_id={sample.article_id}\n"
        f"entity_count={sample.entity_count}\n"
        f"event_count={sample.event_count}\n"
        f"evidence_drop_count={sample.evidence_drop_count}\n"
        f"excerpt={sample.excerpt}\n"
    )


def select_samples(roots: list[Path], *, limit: int, per_category: int) -> list[QaSample]:
    buckets: dict[str, list[QaSample]] = {}
    for root in roots:
        for path in sorted(root.rglob("extract.article.v1.json")):
            article = read_json(path)
            if not article:
                continue
            category = classify_sample(article)
            if not category:
                continue
            bucket = buckets.setdefault(category, [])
            if len(bucket) >= per_category:
                continue
            sample = QaSample(
                sample_id=f"{category}_{len(bucket) + 1:04d}",
                extract_path=str(path),
                category=category,
                account=compact(article.get("source_account") or article.get("account") or path.parent.parent.name, 120),
                title=compact(article.get("title"), 180),
                article_id=compact(article.get("article_uid") or article.get("article_id") or path.parent.name, 160),
                entity_count=len(entities(article)),
                event_count=len(events(article)),
                evidence_drop_count=evidence_drop_count(article),
                reasons=[category],
                priority="P2",
                excerpt="",
                prompt="",
            )
            sample.prompt = build_prompt(sample)
            bucket.append(sample)
            if sum(len(rows) for rows in buckets.values()) >= limit:
                return flatten_buckets(buckets, limit)
    return flatten_buckets(buckets, limit)


def flatten_buckets(buckets: dict[str, list[QaSample]], limit: int) -> list[QaSample]:
    rows: list[QaSample] = []
    for category in sorted(buckets):
        rows.extend(buckets[category])
    return rows[:limit]


def category_from_manifest(row: dict[str, Any]) -> str:
    reasons = row.get("reasons")
    reason_set = {str(item) for item in reasons} if isinstance(reasons, list) else set()
    if "title_pseudoquote" in reason_set or int(row.get("title_pseudoquote_count") or 0) > 0:
        return "title_pseudoquote"
    if "zero_both" in reason_set or (int(row.get("entity_count") or 0) == 0 and int(row.get("event_count") or 0) == 0):
        return "zero_entity_event"
    if "non_exact_evidence_drop" in reason_set or int(row.get("drop_non_exact") or 0) > 0:
        return "high_evidence_drop"
    return "low_confidence_map_candidate"


def priority_from_manifest(row: dict[str, Any]) -> str:
    tier = str(row.get("tier") or "")
    if tier.startswith("P0"):
        return "P0"
    if tier.startswith("P1"):
        return "P1"
    if tier.startswith("P2"):
        return "P2"
    if tier.startswith("P3"):
        return "P3"
    score = int(row.get("priority_score") or 0)
    if score >= 80:
        return "P0"
    if score >= 60:
        return "P1"
    if score >= 40:
        return "P2"
    return "P3"


def read_manifest_samples(manifests: list[Path], *, limit: int) -> list[QaSample]:
    samples: list[QaSample] = []
    for manifest in manifests:
        with manifest.open("r", encoding="utf-8") as handle:
            for line in handle:
                if len(samples) >= limit:
                    return samples
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                reasons = row.get("reasons")
                sample = QaSample(
                    sample_id=f"manifest_{len(samples) + 1:04d}",
                    extract_path=str(row.get("extract_path") or ""),
                    category=category_from_manifest(row),
                    account=compact(row.get("source_account"), 120),
                    title=compact(row.get("title"), 180),
                    article_id=compact(row.get("article_id") or row.get("article_uid"), 160),
                    entity_count=int(row.get("entity_count") or 0),
                    event_count=int(row.get("event_count") or 0),
                    evidence_drop_count=int(row.get("drop_non_exact") or 0) + int(row.get("drop_empty_after_prune") or 0),
                    reasons=[str(item) for item in reasons] if isinstance(reasons, list) else [],
                    priority=priority_from_manifest(row),
                    excerpt=compact(row.get("excerpt"), 1200),
                    prompt="",
                )
                sample.prompt = build_prompt(sample)
                samples.append(sample)
    return samples


def strip_analysis_markers(text: str) -> str:
    text = re.sub(r"(?is)<analysis>.*?</analysis>", "", text)
    text = re.sub(r"(?im)^analysis\s*:.*$", "", text)
    text = text.replace("<final>", "").replace("</final>", "")
    return text


def sanitize_stdout(text: str) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(prefix) for prefix in NOISE_PREFIXES):
            continue
        lines.append(stripped)
    return strip_analysis_markers("\n".join(lines)).strip()


def has_analysis_leak(text: str) -> bool:
    return bool(re.search(r"(?i)(<analysis>|</analysis>|\banalysis\s*:)", text or ""))


def extract_json_payload(text: str) -> dict[str, Any]:
    sanitized = sanitize_stdout(text)
    decoder = json.JSONDecoder()
    best_error: Exception | None = None
    last_dict: dict[str, Any] | None = None
    # Scan forward and keep the LAST valid dict (model often reasons first, outputs answer last)
    for index, char in enumerate(sanitized):
        if char not in "{[":
            continue
        try:
            payload, _end = decoder.raw_decode(sanitized[index:])
        except json.JSONDecodeError as exc:
            best_error = exc
            continue
        if isinstance(payload, dict):
            last_dict = payload
        else:
            best_error = ValueError("gpt-oss QA output JSON must be an object")
    if last_dict is not None:
        return last_dict
    raise ValueError(f"no JSON object found after sanitize: {best_error or sanitized[:120]}")


def run_gpt_oss(prompt: str, *, ssh_target: str, wrapper: str, temp: float, max_tokens: int, timeout_sec: int) -> tuple[str, str, int]:
    remote = " ".join(
        shlex.quote(part)
        for part in [
            wrapper,
            prompt,
            "--temp",
            str(temp),
            "--max-tokens",
            str(max_tokens),
        ]
    )
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", ssh_target, remote]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout_sec, encoding="utf-8", errors="replace")
    return proc.stdout, proc.stderr, int(proc.returncode)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# GPT-OSS Stage8 QA Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- samples_selected: `{report['samples_selected']}`",
        f"- parse_success: `{report['parse_success']}`",
        f"- parse_failures: `{report['parse_failures']}`",
        f"- parse_rate: `{report['parse_rate']}`",
        f"- analysis_leak_after_sanitize_count: `{report.get('analysis_leak_after_sanitize_count', 0)}`",
        f"- pass_gate: `{report.get('pass_gate')}`",
        f"- writes: `{report['writes']}`",
        "",
        "## Category Counts",
        "",
    ]
    for key, value in sorted(report["category_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    if report.get("sample_outputs"):
        lines.extend(["", "## Sample Outputs", ""])
        for row in report["sample_outputs"][:10]:
            parsed = row.get("parsed") if isinstance(row.get("parsed"), dict) else {}
            lines.append(
                f"- `{row['sample_id']}` `{row['category']}` parse={row['parse_ok']} "
                f"candidate={parsed.get('map_candidate')} risk={parsed.get('risk')}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    roots = [Path(value) for value in args.extract_root]
    manifests = [Path(value) for value in args.manifest_jsonl]
    samples = read_manifest_samples(manifests, limit=args.limit) if manifests else select_samples(roots, limit=args.limit, per_category=args.per_category)
    rows: list[dict[str, Any]] = []
    for sample in samples:
        row = asdict(sample)
        started = time.perf_counter()
        if args.mode == "select-only":
            row.update({"parse_ok": None, "parsed": None, "raw_stdout": "", "sanitized_stdout": "", "analysis_leak_after_sanitize": False, "stderr": "", "returncode": None})
        else:
            stdout = ""
            stderr = ""
            returncode: int | None = None
            try:
                stdout, stderr, returncode = run_gpt_oss(
                    sample.prompt,
                    ssh_target=args.ssh_target,
                    wrapper=args.wrapper,
                    temp=args.temp,
                    max_tokens=args.max_tokens,
                    timeout_sec=args.timeout_sec,
                )
                sanitized = sanitize_stdout(stdout)
                parsed = extract_json_payload(stdout)
                row.update({
                    "parse_ok": True,
                    "parsed": parsed,
                    "raw_stdout": stdout[:4000],
                    "sanitized_stdout": sanitized[:4000],
                    "analysis_leak_after_sanitize": has_analysis_leak(sanitized),
                    "stderr": stderr[:2000],
                    "returncode": returncode,
                })
            except Exception as exc:
                row.update({
                    "parse_ok": False,
                    "parsed": None,
                    "raw_stdout": stdout[:4000],
                    "sanitized_stdout": sanitize_stdout(stdout)[:4000],
                    "analysis_leak_after_sanitize": has_analysis_leak(sanitize_stdout(stdout)),
                    "stderr": stderr[:2000],
                    "returncode": returncode,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                })
        row["elapsed_sec"] = round(time.perf_counter() - started, 3)
        rows.append(row)
    parse_attempts = [row for row in rows if row.get("parse_ok") is not None]
    parse_success = sum(1 for row in parse_attempts if row.get("parse_ok"))
    parse_failures = sum(1 for row in parse_attempts if row.get("parse_ok") is False)
    analysis_leaks = sum(1 for row in parse_attempts if row.get("analysis_leak_after_sanitize"))
    category_counts: dict[str, int] = {}
    for sample in samples:
        category_counts[sample.category] = category_counts.get(sample.category, 0) + 1
    return {
        "schema_version": "stage8_gpt_oss_qa.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": args.mode,
        "writes": "report files only; no Qdrant/Neo4j/SQLite/Mem0/Stage7 writes",
        "extract_roots": [str(root) for root in roots],
        "manifest_jsonl": [str(path) for path in manifests],
        "samples_selected": len(samples),
        "parse_success": parse_success,
        "parse_failures": parse_failures,
        "parse_rate": round(parse_success / max(len(parse_attempts), 1), 4) if parse_attempts else None,
        "analysis_leak_after_sanitize_count": analysis_leaks,
        "pass_gate": bool(parse_attempts) and (parse_success / max(len(parse_attempts), 1)) >= 0.95 and analysis_leaks == 0,
        "category_counts": category_counts,
        "sample_outputs": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-root", action="append", default=[])
    parser.add_argument("--manifest-jsonl", action="append", default=[])
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mode", choices=["select-only", "qa"], default="select-only")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--per-category", type=int, default=25)
    parser.add_argument("--ssh-target", default="masher@192.168.8.234")
    parser.add_argument("--wrapper", default=DEFAULT_WRAPPER)
    parser.add_argument("--temp", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--timeout-sec", type=int, default=90)
    args = parser.parse_args(argv)
    if not args.extract_root and not args.manifest_jsonl:
        parser.error("provide --extract-root or --manifest-jsonl")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run(args)
    write_json(out_dir / "gpt_oss_qa_report.json", report)
    write_jsonl(out_dir / "gpt_oss_qa_rows.jsonl", report["sample_outputs"])
    write_jsonl(out_dir / "gpt_oss_qa_raw.jsonl", [
        {
            "sample_id": row.get("sample_id"),
            "raw_stdout": row.get("raw_stdout", ""),
            "stderr": row.get("stderr", ""),
            "returncode": row.get("returncode"),
            "error": row.get("error", ""),
        }
        for row in report["sample_outputs"]
    ])
    write_jsonl(out_dir / "gpt_oss_qa_sanitized.jsonl", [
        {
            "sample_id": row.get("sample_id"),
            "sanitized_stdout": row.get("sanitized_stdout", ""),
            "parse_ok": row.get("parse_ok"),
            "analysis_leak_after_sanitize": row.get("analysis_leak_after_sanitize"),
            "parsed": row.get("parsed"),
        }
        for row in report["sample_outputs"]
    ])
    write_markdown(out_dir / "GPT_OSS_QA_REPORT.md", report)
    print(json.dumps({"ok": True, "report": str(out_dir / "GPT_OSS_QA_REPORT.md"), **{k: report[k] for k in ("samples_selected", "parse_success", "parse_failures", "parse_rate", "analysis_leak_after_sanitize_count", "pass_gate")}}, ensure_ascii=False, indent=2))
    return 0 if report["parse_failures"] == 0 and report["analysis_leak_after_sanitize_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
