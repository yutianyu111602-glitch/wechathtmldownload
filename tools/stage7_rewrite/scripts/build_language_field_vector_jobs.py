#!/usr/bin/env python3
"""Build field-level language-routed vector jobs for Stage7 retrieval canaries.

This is Phase 1 of the embedding replacement plan. It produces a JSONL job
manifest only. It does not encode vectors, write Qdrant, promote aliases, call
models, touch Neo4j/SQLite/mem0, or scan D:.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_RELEASE_PACK = Path("reports/consumer_release_pack_full_unknown_time_20260517")
DEFAULT_POSTER_CANDIDATES = Path("reports/poster_ocr_text_gate_refresh_20260515/poster_ocr_text_candidates.jsonl")
DEFAULT_OUT_DIR = Path("reports/language_field_vector_jobs_20260517")
SCHEMA_VERSION = "stage7_language_field_vector_jobs.v1"
JOB_SCHEMA_VERSION = "stage7_language_field_vector_job.v1"

MODEL_ROLES = {
    "multilingual_baseline": {
        "model": "BAAI/bge-m3",
        "dim": 1024,
        "channel": "multilingual",
    },
    "snowflake_canary": {
        "model": "Snowflake/snowflake-arctic-embed-l-v2.0",
        "dim": 1024,
        "channel": "snowflake_canary",
    },
    "english_sidecar": {
        "model": "BAAI/bge-large-en-v1.5",
        "dim": 1024,
        "channel": "english_sidecar",
    },
    "ocr_baseline": {
        "model": "BAAI/bge-m3",
        "dim": 1024,
        "channel": "ocr",
    },
}

ENGLISH_SIDECAR_ALLOWLIST = {
    "article.title",
    "entity.name",
    "entity.bio",
    "entity.profile",
    "event.name",
    "event.summary",
    "event.lineup",
    "poster.ocr_text",
    "social.profile",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 4000) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:24]


def cjk_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def latin_count(text: str) -> int:
    return sum(1 for char in text if ("a" <= char.lower() <= "z"))


def digit_count(text: str) -> int:
    return sum(1 for char in text if char.isdigit())


def meaningful_count(text: str) -> int:
    return cjk_count(text) + latin_count(text) + digit_count(text)


def is_short_latin_name(text: str) -> bool:
    raw = compact(text, 80)
    if not raw or len(raw) > 32:
        return False
    if cjk_count(raw) > 0:
        return False
    return latin_count(raw) >= 2 and re.fullmatch(r"[A-Za-z0-9 ._&'/-]+", raw) is not None


def detect_language(text: str) -> str:
    raw = compact(text)
    if meaningful_count(raw) < 2:
        return "unknown"
    cjk = cjk_count(raw)
    latin = latin_count(raw)
    if cjk >= 2 and latin >= 3:
        return "mixed"
    if cjk >= 2:
        return "zh"
    if latin >= 3:
        return "en"
    return "unknown"


def usable_text(text: str) -> bool:
    raw = compact(text)
    if meaningful_count(raw) < 2:
        return False
    return bool(re.search(r"[\w\u4e00-\u9fff]", raw))


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for vector job planning: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def iter_jsonl(path: Path, *, limit: int = 0) -> Iterable[tuple[int, dict[str, Any]]]:
    reject_d_path(path, "jsonl")
    with path.open("r", encoding="utf-8") as handle:
        emitted = 0
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                yield line_no, row
                emitted += 1
            if limit and emitted >= limit:
                break


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def append_job(
    jobs: list[dict[str, Any]],
    *,
    parent_kind: str,
    parent_id: str,
    field_path: str,
    text: str,
    source_artifact: str,
    source_row_no: int,
    model_role: str,
    source_article_uid: str = "",
    routing_reason: str = "",
) -> None:
    raw = compact(text)
    if not usable_text(raw):
        return
    role = MODEL_ROLES[model_role]
    lang = detect_language(raw)
    sha1 = text_sha1(raw)
    jobs.append(
        {
            "schema_version": JOB_SCHEMA_VERSION,
            "record_id": stable_id(parent_kind, parent_id, field_path, model_role, sha1),
            "parent_kind": parent_kind,
            "parent_id": parent_id,
            "source_article_uid": source_article_uid,
            "field_path": field_path,
            "lang": lang,
            "channel": role["channel"],
            "model_role": model_role,
            "model": role["model"],
            "dim": role["dim"],
            "text": raw,
            "text_length": len(raw),
            "text_sha1": sha1,
            "source_artifact": source_artifact,
            "source_row_no": source_row_no,
            "routing_reason": routing_reason,
        }
    )


def add_multilingual_and_snowflake(
    jobs: list[dict[str, Any]],
    *,
    parent_kind: str,
    parent_id: str,
    field_path: str,
    text: str,
    source_artifact: str,
    source_row_no: int,
    source_article_uid: str = "",
) -> None:
    append_job(
        jobs,
        parent_kind=parent_kind,
        parent_id=parent_id,
        field_path=field_path,
        text=text,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        model_role="multilingual_baseline",
        source_article_uid=source_article_uid,
        routing_reason="default_multilingual_fallback",
    )
    append_job(
        jobs,
        parent_kind=parent_kind,
        parent_id=parent_id,
        field_path=field_path,
        text=text,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        model_role="snowflake_canary",
        source_article_uid=source_article_uid,
        routing_reason="isolated_snowflake_canary",
    )


def maybe_add_english_sidecar(
    jobs: list[dict[str, Any]],
    *,
    parent_kind: str,
    parent_id: str,
    field_path: str,
    text: str,
    source_artifact: str,
    source_row_no: int,
    source_article_uid: str = "",
) -> None:
    if field_path not in ENGLISH_SIDECAR_ALLOWLIST:
        return
    lang = detect_language(text)
    if lang not in {"en", "mixed"} and not is_short_latin_name(text):
        return
    append_job(
        jobs,
        parent_kind=parent_kind,
        parent_id=parent_id,
        field_path=field_path,
        text=text,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        model_role="english_sidecar",
        source_article_uid=source_article_uid,
        routing_reason="english_or_mixed_allowlisted_field",
    )


def build_article_jobs(row: dict[str, Any], source_artifact: str, source_row_no: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    parent_id = compact(row.get("article_uid") or row.get("article_id"), 240)
    if not parent_id:
        return jobs
    title_raw = compact(row.get("title"), 1000)
    title_text = compact(row.get("vector_text") or title_raw, 1000)
    add_multilingual_and_snowflake(
        jobs,
        parent_kind="article",
        parent_id=parent_id,
        field_path="article.title",
        text=title_text,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        source_article_uid=parent_id,
    )
    maybe_add_english_sidecar(
        jobs,
        parent_kind="article",
        parent_id=parent_id,
        field_path="article.title",
        text=title_raw,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        source_article_uid=parent_id,
    )
    return jobs


def build_entity_jobs(row: dict[str, Any], source_artifact: str, source_row_no: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    parent_id = compact(row.get("eid") or row.get("name"), 240)
    if not parent_id:
        return jobs
    profile_text = compact(row.get("vector_text") or " | ".join([compact(row.get("name"), 200), compact(row.get("type"), 80), compact(row.get("bio"), 1000)]), 1500)
    add_multilingual_and_snowflake(
        jobs,
        parent_kind="entity",
        parent_id=parent_id,
        field_path="entity.profile",
        text=profile_text,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        source_article_uid=compact(row.get("source_article_uid"), 240),
    )
    for field_path, value in [("entity.name", row.get("name")), ("entity.bio", row.get("bio"))]:
        maybe_add_english_sidecar(
            jobs,
            parent_kind="entity",
            parent_id=parent_id,
            field_path=field_path,
            text=compact(value, 1000),
            source_artifact=source_artifact,
            source_row_no=source_row_no,
            source_article_uid=compact(row.get("source_article_uid"), 240),
        )
    return jobs


def build_event_jobs(row: dict[str, Any], source_artifact: str, source_row_no: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    parent_id = compact(row.get("evid") or row.get("name"), 240)
    if not parent_id:
        return jobs
    participants = row.get("participants") if isinstance(row.get("participants"), list) else []
    organizers = row.get("organizers") if isinstance(row.get("organizers"), list) else []
    lineup_text = "、".join(compact(item, 120) for item in participants if compact(item, 120))
    summary = compact(
        row.get("vector_text")
        or " | ".join(
            part
            for part in [
                compact(row.get("name"), 240),
                compact(row.get("time_text") or row.get("time_iso"), 120),
                compact(row.get("place"), 160),
                lineup_text,
                "、".join(compact(item, 120) for item in organizers if compact(item, 120)),
            ]
            if part
        ),
        1500,
    )
    add_multilingual_and_snowflake(
        jobs,
        parent_kind="event",
        parent_id=parent_id,
        field_path="event.summary",
        text=summary,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        source_article_uid=compact(row.get("source_article_uid"), 240),
    )
    for field_path, value in [("event.name", row.get("name")), ("event.lineup", lineup_text)]:
        maybe_add_english_sidecar(
            jobs,
            parent_kind="event",
            parent_id=parent_id,
            field_path=field_path,
            text=compact(value, 1000),
            source_artifact=source_artifact,
            source_row_no=source_row_no,
            source_article_uid=compact(row.get("source_article_uid"), 240),
        )
    return jobs


def poster_text_from_ocr(path_text: str) -> str:
    if not path_text:
        return ""
    path = Path(path_text)
    reject_d_path(path, "poster_ocr_path")
    if not path.exists():
        return ""
    payload = read_json(path)
    text = compact(payload.get("plain_text"), 4000)
    if text:
        return text
    blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    return "\n".join(compact(block.get("text"), 200) for block in blocks if isinstance(block, dict) and compact(block.get("text"), 200))


def build_poster_jobs(row: dict[str, Any], source_artifact: str, source_row_no: int) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    parent_id = compact(row.get("source_article_uid") or row.get("relative_dir"), 240)
    if not parent_id:
        return jobs
    text = poster_text_from_ocr(str(row.get("poster_ocr_path") or ""))
    if not usable_text(text):
        return jobs
    append_job(
        jobs,
        parent_kind="poster",
        parent_id=parent_id,
        field_path="poster.ocr_text",
        text=text,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        model_role="ocr_baseline",
        source_article_uid=compact(row.get("source_article_uid"), 240),
        routing_reason="poster_ocr_noise_prefers_bge_m3",
    )
    maybe_add_english_sidecar(
        jobs,
        parent_kind="poster",
        parent_id=parent_id,
        field_path="poster.ocr_text",
        text=text,
        source_artifact=source_artifact,
        source_row_no=source_row_no,
        source_article_uid=compact(row.get("source_article_uid"), 240),
    )
    return jobs


def build_jobs(
    *,
    release_pack_dir: Path,
    poster_candidates: Path | None,
    limit_per_kind: int,
    include_posters: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    articles_path = release_pack_dir / "articles.jsonl"
    entities_path = release_pack_dir / "entities.jsonl"
    events_path = release_pack_dir / "events.jsonl"
    for path in [articles_path, entities_path, events_path]:
        if not path.exists():
            raise FileNotFoundError(path)

    jobs: list[dict[str, Any]] = []
    source_rows = Counter()
    skipped = Counter()
    builders = [
        ("articles", articles_path, build_article_jobs),
        ("entities", entities_path, build_entity_jobs),
        ("events", events_path, build_event_jobs),
    ]
    for kind, path, builder in builders:
        for line_no, row in iter_jsonl(path, limit=limit_per_kind):
            source_rows[kind] += 1
            before = len(jobs)
            jobs.extend(builder(row, str(path), line_no))
            if len(jobs) == before:
                skipped[f"{kind}:no_jobs"] += 1

    if include_posters and poster_candidates and poster_candidates.exists():
        for line_no, row in iter_jsonl(poster_candidates, limit=limit_per_kind):
            source_rows["posters"] += 1
            before = len(jobs)
            jobs.extend(build_poster_jobs(row, str(poster_candidates), line_no))
            if len(jobs) == before:
                skipped["posters:no_jobs"] += 1

    # The same field can be routed to multiple models, but exact duplicate jobs
    # indicate source duplication and should not inflate downstream canaries.
    unique: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for job in jobs:
        key = job["record_id"]
        if key in unique:
            duplicate_count += 1
            continue
        unique[key] = job
    jobs = list(unique.values())
    stats = {
        "source_rows": dict(source_rows),
        "skipped": {**dict(skipped), "duplicate_jobs": duplicate_count},
    }
    return jobs, stats


def summarize_jobs(jobs: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
    by_role = Counter(job["model_role"] for job in jobs)
    by_channel = Counter(job["channel"] for job in jobs)
    by_lang = Counter(job["lang"] for job in jobs)
    by_kind = Counter(job["parent_kind"] for job in jobs)
    by_field = Counter(job["field_path"] for job in jobs)
    english_bad = [
        job
        for job in jobs
        if job["model_role"] == "english_sidecar" and job["field_path"] not in ENGLISH_SIDECAR_ALLOWLIST
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "job_count": len(jobs),
        "source_rows": stats.get("source_rows") or {},
        "skipped": stats.get("skipped") or {},
        "counts_by_model_role": dict(sorted(by_role.items())),
        "counts_by_channel": dict(sorted(by_channel.items())),
        "counts_by_lang": dict(sorted(by_lang.items())),
        "counts_by_parent_kind": dict(sorted(by_kind.items())),
        "counts_by_field_path": dict(sorted(by_field.items())),
        "english_sidecar_allowlist": sorted(ENGLISH_SIDECAR_ALLOWLIST),
        "model_roles": MODEL_ROLES,
        "validation": {
            "english_sidecar_allowlist_violations": len(english_bad),
            "all_jobs_have_text_sha1": all(bool(job.get("text_sha1")) for job in jobs),
            "all_jobs_have_parent_id": all(bool(job.get("parent_id")) for job in jobs),
            "all_jobs_have_source_artifact": all(bool(job.get("source_artifact")) for job in jobs),
        },
        "safety": {
            "reports_only": True,
            "model_call_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "production_alias_promoted": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def write_markdown(path: Path, summary: dict[str, Any], jobs: list[dict[str, Any]], sample_limit: int) -> None:
    lines = [
        "# Language Field Vector Jobs",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- job_count: `{summary['job_count']}`",
        f"- source_rows: `{json.dumps(summary['source_rows'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Counts By Model Role",
        "",
    ]
    for key, value in summary["counts_by_model_role"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Counts By Lang", ""])
    for key, value in summary["counts_by_lang"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Sample Jobs", "", "| parent_kind | field_path | lang | model_role | text |", "|---|---|---|---|---|"])
    for job in jobs[:sample_limit]:
        sample_text = job["text"].replace("|", "/")[:120]
        lines.append(f"| `{job['parent_kind']}` | `{job['field_path']}` | `{job['lang']}` | `{job['model_role']}` | {sample_text} |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only job manifest. No model calls, Qdrant writes, Neo4j writes, mem0 writes, paid API calls, alias promotion, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-pack-dir", type=Path, default=DEFAULT_RELEASE_PACK)
    parser.add_argument("--poster-candidates", type=Path, default=DEFAULT_POSTER_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit-per-kind", type=int, default=1000, help="0 means full source files.")
    parser.add_argument("--include-posters", action="store_true", default=True)
    parser.add_argument("--sample-limit", type=int, default=30)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    reject_d_path(args.out_dir, "out_dir")
    jobs, stats = build_jobs(
        release_pack_dir=args.release_pack_dir,
        poster_candidates=args.poster_candidates,
        limit_per_kind=args.limit_per_kind,
        include_posters=args.include_posters,
    )
    summary = summarize_jobs(jobs, stats)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "vector_jobs.jsonl", jobs)
    write_json(args.out_dir / "schema_report.json", summary)
    write_markdown(args.out_dir / "sample_review.md", summary, jobs, args.sample_limit)
    print(
        json.dumps(
            {
                "ok": True,
                "job_count": summary["job_count"],
                "counts_by_model_role": summary["counts_by_model_role"],
                "counts_by_lang": summary["counts_by_lang"],
                "report": str(args.out_dir / "schema_report.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
