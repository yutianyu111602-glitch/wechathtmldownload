#!/usr/bin/env python3
"""Split language-field vector jobs into per-model-role offline artifacts.

This is a preparation step for isolated embedding canaries. It copies only the
job text and routing metadata needed by an encoder. It does not call models,
write Qdrant, promote aliases, or touch production stores.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_VECTOR_JOBS = Path("reports/language_field_vector_jobs_full_20260517/vector_jobs.jsonl")
DEFAULT_OUT_DIR = Path("reports/vector_role_artifacts_20260517")
DEFAULT_ROLES = ["multilingual_baseline", "snowflake_canary", "english_sidecar", "ocr_baseline"]
SCHEMA_VERSION = "stage7_vector_role_artifacts.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for vector role artifacts: {path}")


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    reject_d_path(path, "vector_jobs")
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                yield line_no, row


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def compact_card(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["record_id"],
        "type": job["parent_kind"],
        "text": job["text"],
        "parent_id": job["parent_id"],
        "parent_kind": job["parent_kind"],
        "source_article_uid": job.get("source_article_uid") or "",
        "field_path": job["field_path"],
        "lang": job["lang"],
        "channel": job["channel"],
        "model_role": job["model_role"],
        "model": job["model"],
        "dim": job["dim"],
        "text_sha1": job["text_sha1"],
        "source_artifact": job["source_artifact"],
        "source_row_no": job["source_row_no"],
    }


class RoleWriter:
    def __init__(self, out_dir: Path, role: str, limit: int) -> None:
        self.role = role
        self.limit = limit
        self.dir = out_dir / role
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "card_texts.jsonl"
        self.handle = self.path.open("w", encoding="utf-8")
        self.counts_by_lang: Counter[str] = Counter()
        self.counts_by_parent_kind: Counter[str] = Counter()
        self.counts_by_field_path: Counter[str] = Counter()
        self.count = 0
        self.model = ""
        self.dim = None
        self.truncated = False

    def accepts_more(self) -> bool:
        return not self.limit or self.count < self.limit

    def write(self, job: dict[str, Any]) -> bool:
        if not self.accepts_more():
            self.truncated = True
            return False
        if not self.model:
            self.model = str(job.get("model") or "")
            self.dim = int(job.get("dim") or 0)
        row = compact_card(job)
        self.handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        self.count += 1
        self.counts_by_lang[str(job.get("lang") or "unknown")] += 1
        self.counts_by_parent_kind[str(job.get("parent_kind") or "unknown")] += 1
        self.counts_by_field_path[str(job.get("field_path") or "unknown")] += 1
        return True

    def close(self, source_vector_jobs: Path) -> dict[str, Any]:
        self.handle.close()
        metadata = {
            "schema_version": "stage7_vector_role_artifact.v1",
            "generated_at": now_iso(),
            "model_role": self.role,
            "model": self.model,
            "dim": self.dim,
            "card_count": self.count,
            "truncated_by_limit": self.truncated,
            "source_vector_jobs": str(source_vector_jobs),
            "card_texts": str(self.path),
            "counts_by_lang": dict(sorted(self.counts_by_lang.items())),
            "counts_by_parent_kind": dict(sorted(self.counts_by_parent_kind.items())),
            "counts_by_field_path": dict(sorted(self.counts_by_field_path.items())),
            "safety": {
                "model_call_executed": False,
                "qdrant_write_executed": False,
                "alias_promoted": False,
                "production_write_executed": False,
            },
        }
        write_json(self.dir / "metadata.json", metadata)
        return metadata


def build_role_artifacts(
    *,
    vector_jobs_path: Path,
    out_dir: Path,
    roles: list[str],
    limit_per_role: int,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    role_set = set(roles)
    writers = {role: RoleWriter(out_dir, role, limit_per_role) for role in roles}
    scanned = 0
    matched = Counter()
    skipped_roles = Counter()
    for _line_no, job in iter_jsonl(vector_jobs_path):
        scanned += 1
        role = str(job.get("model_role") or "")
        if role not in role_set:
            skipped_roles[role or "missing"] += 1
            continue
        if writers[role].write(job):
            matched[role] += 1
        if limit_per_role and all(not writer.accepts_more() for writer in writers.values()):
            for writer in writers.values():
                writer.truncated = True
            break
    role_metadata = {role: writers[role].close(vector_jobs_path) for role in roles}
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_vector_jobs": str(vector_jobs_path),
        "out_dir": str(out_dir),
        "roles": roles,
        "limit_per_role": limit_per_role,
        "scanned_jobs": scanned,
        "matched_jobs": dict(sorted(matched.items())),
        "skipped_roles": dict(sorted(skipped_roles.items())),
        "role_artifacts": role_metadata,
        "safety": {
            "reports_only": True,
            "model_call_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "role_artifacts_summary.json", report)
    write_markdown(out_dir / "role_artifacts_summary.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Vector Role Artifacts",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- scanned_jobs: `{report['scanned_jobs']}`",
        f"- limit_per_role: `{report['limit_per_role']}`",
        "",
        "| Role | Cards | Model | Dim |",
        "|---|---:|---|---:|",
    ]
    for role, meta in report["role_artifacts"].items():
        lines.append(f"| `{role}` | {meta['card_count']} | `{meta['model']}` | {meta['dim']} |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only artifact split. No model call, Qdrant write, alias promotion, production write, paid API, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-jobs", type=Path, default=DEFAULT_VECTOR_JOBS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--roles", nargs="+", default=DEFAULT_ROLES)
    parser.add_argument("--limit-per-role", type=int, default=0, help="0 means all matching jobs.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    report = build_role_artifacts(
        vector_jobs_path=args.vector_jobs,
        out_dir=args.out_dir,
        roles=args.roles,
        limit_per_role=args.limit_per_role,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "scanned_jobs": report["scanned_jobs"],
                "matched_jobs": report["matched_jobs"],
                "summary": str(args.out_dir / "role_artifacts_summary.json"),
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
