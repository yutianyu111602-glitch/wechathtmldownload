#!/usr/bin/env python3
"""Build a Stage7 LLM manifest from successful Dajiala archive exports."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def rel_key(*parts: str) -> str:
    return "\\".join(str(part or "").strip().strip("\\/") for part in parts if str(part or "").strip()).lower()


def load_export_index(status_path: Path) -> dict[str, dict[str, Any]]:
    status = read_json(status_path)
    items = status.get("items") or []
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "succeeded":
            continue
        key = rel_key(str(item.get("relativeInputPath") or ""))
        if key:
            index[key] = item
    return index


def build_manifest(success_manifest: Path, export_status: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    export_index = load_export_index(export_status)
    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in iter_jsonl(success_manifest):
        account = str(source.get("account_key") or source.get("source_account") or "").strip()
        token = str(source.get("token") or "").strip()
        article_uid = str(source.get("article_uid") or "").strip()
        key = rel_key(account, token)
        item = export_index.get(key)
        if not item:
            missing.append({"article_uid": article_uid, "reason": "missing_export_status_item", "key": key})
            continue
        out_dir = Path(str(item.get("outDir") or ""))
        llm_input_path = out_dir / "llm_input.md"
        meta_path = out_dir / "meta.json"
        if not llm_input_path.exists() or not meta_path.exists():
            missing.append(
                {
                    "article_uid": article_uid,
                    "reason": "missing_llm_input_or_meta",
                    "llm_input_path": str(llm_input_path),
                    "meta_path": str(meta_path),
                }
            )
            continue
        if not article_uid or article_uid in seen:
            missing.append({"article_uid": article_uid, "reason": "missing_or_duplicate_article_uid"})
            continue
        seen.add(article_uid)
        meta = read_json(meta_path)
        text = llm_input_path.read_text(encoding="utf-8")
        rows.append(
            {
                "article_uid": article_uid,
                "source_account": account,
                "article_id": token,
                "title": str(source.get("title") or meta.get("title") or ""),
                "input_chars": len(text),
                "quality_grade": "dajiala_recovered",
                "local_image_count": 0,
                "bucket": "dajiala_success130_recovered",
                "llm_input_path": str(llm_input_path),
                "meta_path": str(meta_path),
                "source_url": str(source.get("source_url") or meta.get("source_url") or ""),
                "status": "pending",
            }
        )
    summary = {
        "schema_version": "dajiala_success_llm_manifest.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "success_manifest": str(success_manifest),
        "export_status": str(export_status),
        "input_success_rows": len(list(iter_jsonl(success_manifest))),
        "manifest_rows": len(rows),
        "missing_rows": len(missing),
        "missing": missing[:100],
    }
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--success-manifest", required=True)
    parser.add_argument("--export-status", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    rows, summary = build_manifest(Path(args.success_manifest), Path(args.export_status))
    write_jsonl(out_dir / "dajiala_success130_llm_manifest.jsonl", rows)
    summary["outputs"] = {
        "manifest": str(out_dir / "dajiala_success130_llm_manifest.jsonl"),
        "summary": str(out_dir / "dajiala_success130_llm_manifest_summary.json"),
    }
    write_json(out_dir / "dajiala_success130_llm_manifest_summary.json", summary)
    print(json.dumps({"ok": summary["missing_rows"] == 0, **summary}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["missing_rows"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
