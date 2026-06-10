"""Materialize multiple Stage8 extract roots into one gate-ready root.

This helper is for sharded Stage7 outputs. It only reads
``extract.article.v1.json`` files and writes a merged ``llm_extract`` tree plus
manifest/report files. It does not embed vectors, write Qdrant, write Neo4j, or
touch production databases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stage7.atomic_io import safe_read_json


def extract_base(root: Path) -> Path:
    return root if root.name == "llm_extract" else root / "llm_extract"


def safe_part(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", str(value or "unknown")).strip("._-")
    return text[:120] or "unknown"


def source_slug(index: int, root: Path) -> str:
    raw = f"{index:03d}_{root.parent.name}_{root.name}"
    digest = hashlib.sha1(str(root.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{safe_part(raw)}_{digest}"


def iter_extracts(root: Path) -> list[Path]:
    base = extract_base(root)
    if not base.exists():
        return []
    return sorted(base.rglob("extract.article.v1.json"))


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir).resolve()
    llm_extract = out_dir / "llm_extract"
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_extract.mkdir(parents=True, exist_ok=True)

    copied = 0
    scanned = 0
    skipped_invalid = 0
    source_reports: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for idx, root_value in enumerate(args.output_root):
        root = Path(root_value).resolve()
        base = extract_base(root)
        files = iter_extracts(root)
        source_copied = 0
        slug = source_slug(idx, root)
        for source_path in files:
            if args.max_files > 0 and copied >= args.max_files:
                break
            scanned += 1
            article = safe_read_json(source_path, {})
            if not isinstance(article, dict) or not article:
                skipped_invalid += 1
                continue
            article.setdefault("schema_version", "article_extract.v1")
            rel = source_path.relative_to(base)
            dst = llm_extract / slug / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(article, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            copied += 1
            source_copied += 1
            rows.append(
                {
                    "source_root": str(root),
                    "source_path": str(source_path),
                    "merged_path": str(dst),
                    "article_id": str(article.get("article_uid") or article.get("article_id") or source_path.parent.name),
                    "source_account": str(article.get("source_account") or article.get("account") or ""),
                }
            )
        source_reports.append(
            {
                "source_root": str(root),
                "source_base": str(base),
                "source_files": len(files),
                "copied": source_copied,
            }
        )
        if args.max_files > 0 and copied >= args.max_files:
            break

    if args.fail_if_empty and copied == 0:
        raise ValueError("no extract.article.v1.json files were materialized")

    manifest_path = out_dir / "merged_extract_manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    report = {
        "schema_version": "stage8_merged_extract_roots.v1",
        "out_dir": str(out_dir),
        "merged_llm_extract": str(llm_extract),
        "source_roots": [str(Path(value).resolve()) for value in args.output_root],
        "source_reports": source_reports,
        "files_scanned": scanned,
        "files_copied": copied,
        "skipped_invalid": skipped_invalid,
        "max_files": args.max_files,
        "writes": "merged extract root only; no embeddings or database writes",
        "manifest_jsonl": str(manifest_path),
    }
    (out_dir / "merged_extract_roots_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_markdown(out_dir, report)
    return report


def write_markdown(out_dir: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage8 Merged Extract Roots",
        "",
        f"- files_scanned: `{report['files_scanned']}`",
        f"- files_copied: `{report['files_copied']}`",
        f"- skipped_invalid: `{report['skipped_invalid']}`",
        f"- merged_llm_extract: `{report['merged_llm_extract']}`",
        f"- writes: `{report['writes']}`",
        "",
        "| Source Root | Source Files | Copied |",
        "|---|---:|---:|",
    ]
    for item in report["source_reports"]:
        lines.append(f"| `{item['source_root']}` | {item['source_files']} | {item['copied']} |")
    lines.extend(
        [
            "",
            "## Next",
            "",
            "- Use this merged root only after confirming the source roots are stable.",
            "- Production mode remains blocked until gate dry-run, larger canary, and rollback evidence are green.",
            "",
        ]
    )
    (out_dir / "MERGED_EXTRACT_ROOTS_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", action="append", required=True, help="Stage8 root containing llm_extract")
    parser.add_argument("--out-dir", required=True, help="Merged Stage8 output root to create")
    parser.add_argument("--max-files", type=int, default=0, help="Maximum files to copy across all roots; 0 means all")
    parser.add_argument("--fail-if-empty", action="store_true")
    args = parser.parse_args(argv)
    report = materialize(args)
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
