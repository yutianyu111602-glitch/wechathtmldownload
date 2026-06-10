#!/usr/bin/env python3
"""Build an isolated Stage7 manifest from an explicit artifact directory list.

This is a bridge from the 93k LLM intake audit into the existing Stage7 CLI.
It reads only paths listed in the input file and writes a normal
`manifests/article_manifest.v1.jsonl` under the requested output root.
It does not scan D: roots and does not run LLM/vector/graph/DB work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


DEFAULT_ARTIFACT_LIST = Path(
    r"D:\downstream_results\stage7_rewrite\longrun\LLM_INTAKE_MANIFEST_20260507"
    r"\INTAKE_QUALITY_AUDIT_20260507\ready_sample_artifact_dirs.txt"
)
DEFAULT_OUTPUT_ROOT = Path(
    r"D:\downstream_results\stage7_rewrite\longrun"
    r"\STAGE7_P2_READY_SAMPLE_20260507"
)
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        return default


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def iter_artifact_dirs(path: Path, limit: int | None) -> list[Path]:
    seen: set[str] = set()
    dirs: list[Path] = []
    for line in read_text(path).splitlines():
        raw = line.strip().strip('"')
        if not raw:
            continue
        artifact_dir = Path(raw)
        key = str(artifact_dir).lower()
        if key in seen:
            continue
        seen.add(key)
        dirs.append(artifact_dir)
        if limit is not None and len(dirs) >= limit:
            break
    return dirs


def build_record(artifact_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    llm_input_path = artifact_dir / "llm_input.md"
    meta_path = artifact_dir / "meta.json"
    poster_ocr_path = artifact_dir / "poster_ocr.json"

    if not artifact_dir.exists():
        return None, "missing_artifact_dir"
    if not llm_input_path.exists():
        return None, "missing_llm_input"

    text = read_text(llm_input_path)
    if not text.strip():
        return None, "empty_llm_input"

    meta = read_json(meta_path)
    source_account = artifact_dir.parent.name
    article_id = artifact_dir.name
    title = first_text(meta, "title", "msg_title", "article_title")
    publish_time = first_text(meta, "publish_time", "publish_time_text", "publishTime", "date")
    url = first_text(meta, "source_url", "url", "link")
    input_sha1 = sha1_text(text)
    article_uid = sha1_text(f"{source_account}:{article_id}:{artifact_dir}")

    empty_files = []
    if not meta_path.exists() or meta_path.stat().st_size == 0:
        empty_files.append("meta")
    if not poster_ocr_path.exists() or poster_ocr_path.stat().st_size == 0:
        empty_files.append("poster_ocr")

    return (
        {
            "article_uid": article_uid,
            "source_account": source_account,
            "article_id": article_id,
            "article_dir": str(artifact_dir),
            "llm_input_path": str(llm_input_path),
            "meta_path": str(meta_path) if meta_path.exists() else "",
            "poster_ocr_path": str(poster_ocr_path) if poster_ocr_path.exists() else "",
            "title": title,
            "publish_time": publish_time,
            "url": url,
            "input_chars": len(text),
            "input_sha1": input_sha1,
            "status": "pending",
            "empty_files": empty_files,
            "oversized": len(text) > 500_000,
            "encoding_ok": True,
        },
        None,
    )


def write_isolated_config(path: Path, output_root: Path) -> None:
    raw: dict[str, Any] = {}
    if DEFAULT_CONFIG.exists():
        with DEFAULT_CONFIG.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    raw["output_root"] = str(output_root)
    raw["input_root"] = str(output_root / "input_from_artifact_list")
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_outputs(out_root: Path, records: list[dict[str, Any]], rejects: list[dict[str, str]], source_list: Path) -> dict[str, str]:
    manifests_dir = out_root / "manifests"
    reports_dir = out_root / "reports"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = manifests_dir / "article_manifest.v1.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_artifact_list": str(source_list),
        "output_root": str(out_root),
        "article_count": len(records),
        "reject_count": len(rejects),
        "rejects": rejects[:200],
        "config_path": str(out_root / "config.stage7.yaml"),
        "manifest_path": str(manifest_path),
    }
    report_json = manifests_dir / "input_audit_report.json"
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report_md = manifests_dir / "input_audit_report.md"
    lines = [
        "# Stage7 Artifact List Manifest",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- source_artifact_list: `{source_list}`",
        f"- output_root: `{out_root}`",
        f"- article_count: `{len(records)}`",
        f"- reject_count: `{len(rejects)}`",
        f"- manifest_path: `{manifest_path}`",
        f"- config_path: `{out_root / 'config.stage7.yaml'}`",
        "",
        "## Sample Articles",
        "",
    ]
    for record in records[:20]:
        lines.append(
            f"- `{record['source_account']}` `{record['article_id']}` "
            f"chars=`{record['input_chars']}` title=`{record['title']}`"
        )
    if rejects:
        lines.extend(["", "## Rejects", ""])
        for row in rejects[:50]:
            lines.append(f"- `{row['reason']}` `{row['artifact_dir']}`")
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    write_isolated_config(out_root / "config.stage7.yaml", out_root)

    return {
        "manifest": str(manifest_path),
        "report_json": str(report_json),
        "report_md": str(report_md),
        "config": str(out_root / "config.stage7.yaml"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Stage7 manifest from explicit artifact dirs")
    parser.add_argument("--artifact-list", default=str(DEFAULT_ARTIFACT_LIST))
    parser.add_argument("--out-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    artifact_list = Path(args.artifact_list)
    if not artifact_list.exists():
        raise SystemExit(f"artifact list not found: {artifact_list}")

    out_root = Path(args.out_root)
    limit = args.limit if args.limit > 0 else None
    records: list[dict[str, Any]] = []
    rejects: list[dict[str, str]] = []
    for artifact_dir in iter_artifact_dirs(artifact_list, limit):
        record, reject_reason = build_record(artifact_dir)
        if record is None:
            rejects.append({"artifact_dir": str(artifact_dir), "reason": reject_reason or "unknown"})
            continue
        records.append(record)

    paths = write_outputs(out_root, records, rejects, artifact_list)
    print(json.dumps({"article_count": len(records), "reject_count": len(rejects), **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
