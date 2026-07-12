#!/usr/bin/env python3
"""Merge Sanji manifest/token checkpoints for future delta exports.

Use this after a full export or a verified daily delta export is accepted into
the extraction queue. The output token file is then passed to
`export_sanji_appdata_manifest.py --exclude-token-file` so later daily exports
do not repackage already exported articles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def token_for(fakeid: str, aid: str) -> str:
    return "sanji_" + hashlib.sha1(f"{fakeid}:{aid}".encode("utf-8")).hexdigest()[:20]


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"bad jsonl at {path}:{line_no}: {exc}") from exc


def tokens_from_manifest_root(root: Path) -> set[str]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"manifest.json not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    articles_path = root / (manifest.get("articles_jsonl") or "articles.jsonl")
    if not articles_path.is_file():
        raise SystemExit(f"articles.jsonl not found: {articles_path}")
    tokens = set()
    for _line_no, row in iter_jsonl(articles_path):
        article = row.get("article") or {}
        account = row.get("account") or {}
        fakeid = article.get("account_fakeid") or account.get("fakeid") or ""
        aid = str(article.get("aid") or "")
        if fakeid and aid:
            tokens.add(token_for(fakeid, aid))
    return tokens


def tokens_from_file(path: Path) -> set[str]:
    if not path.is_file():
        raise SystemExit(f"token file not found: {path}")
    tokens = set()
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            token = line.strip()
            if token and not token.startswith("#"):
                tokens.add(token)
    return tokens


def atomic_token_file(path: Path, tokens: list[str]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".txt", dir=str(path.parent))
    sha = hashlib.sha256()
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for token in tokens:
                line = token + "\n"
                sha.update(line.encode("utf-8"))
                f.write(line)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return {"path": str(path), "count": len(tokens), "sha256": sha.hexdigest()}


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def merge(manifest_roots: list[Path], token_files: list[Path], out_token_file: Path, out_report: Path) -> dict:
    sources = []
    all_tokens: set[str] = set()
    for root in manifest_roots:
        tokens = tokens_from_manifest_root(root)
        all_tokens.update(tokens)
        sources.append({"type": "manifest_root", "path": str(root), "token_count": len(tokens)})
    for token_file in token_files:
        tokens = tokens_from_file(token_file)
        all_tokens.update(tokens)
        sources.append({"type": "token_file", "path": str(token_file), "token_count": len(tokens)})

    sorted_tokens = sorted(all_tokens)
    token_info = atomic_token_file(out_token_file, sorted_tokens)
    report = {
        "schema": "sanji.seen_tokens_merged.v1",
        "generated_at": utc_now(),
        "sources": sources,
        "output": token_info,
        "boundary": "candidate_only_token_checkpoint_no_db_write",
    }
    atomic_json(out_report, report)
    return report


def create_self_check_fixture(root: Path) -> tuple[Path, Path]:
    a = root / "a"
    b = root / "b"
    a.mkdir()
    b.mkdir()
    for manifest_root, rows in (
        (a, [("fakeid_a", "1"), ("fakeid_a", "2")]),
        (b, [("fakeid_a", "2"), ("fakeid_b", "1")]),
    ):
        (manifest_root / "manifest.json").write_text(
            json.dumps({"schema": "sanji.cache.manifest.v1", "articles_jsonl": "articles.jsonl"}, indent=2) + "\n",
            encoding="utf-8",
        )
        with (manifest_root / "articles.jsonl").open("w", encoding="utf-8", newline="\n") as f:
            for fakeid, aid in rows:
                f.write(json.dumps({"account": {"fakeid": fakeid}, "article": {"account_fakeid": fakeid, "aid": aid}}) + "\n")
    return a, b


def self_check() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_sanji_seen_tokens_") as td:
        root = Path(td)
        a, b = create_self_check_fixture(root)
        report = merge([a, b], [], root / "seen.txt", root / "seen.json")
        assert report["output"]["count"] == 3
        assert (root / "seen.txt").read_text(encoding="utf-8").count("\n") == 3
    print("self-check OK: merged Sanji seen token checkpoint")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--manifest-root", action="append", default=[], help="repeatable")
    ap.add_argument("--token-file", action="append", default=[], help="repeatable")
    ap.add_argument("--out-token-file", default="")
    ap.add_argument("--out-report", default="")
    args = ap.parse_args()
    if args.self_check:
        self_check()
        return 0
    if not args.out_token_file:
        ap.error("--out-token-file is required unless --self-check is used")
    out_token_file = Path(args.out_token_file).resolve()
    out_report = Path(args.out_report).resolve() if args.out_report else out_token_file.with_suffix(".json")
    report = merge(
        [Path(p).resolve() for p in args.manifest_root],
        [Path(p).resolve() for p in args.token_file],
        out_token_file,
        out_report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
