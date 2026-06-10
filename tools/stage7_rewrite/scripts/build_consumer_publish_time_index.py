"""Build a bounded publish-time evidence index for Stage7 consumer release packs.

The script follows known paths already present in `stable_articles.jsonl`; it
does not walk D: or scan archive roots. It distinguishes true WeChat publish
time from archive capture time so the release gate cannot accidentally treat a
2026 capture timestamp as article publication time.
"""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_STABLE_ARTICLES = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_articles.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/consumer_publish_time_index_canary_20260514")
SCHEMA_VERSION = "stage7_consumer_publish_time_index.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def resolve_known_path(raw_path: str | Path) -> Path:
    text = str(raw_path)
    if text.startswith("/mnt/d/"):
        return Path("D:/" + text[len("/mnt/d/") :])
    if text.startswith("/mnt/c/"):
        return Path("C:/" + text[len("/mnt/c/") :])
    return Path(text)


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def true_publish_time_from(data: dict[str, Any], prefix: str) -> tuple[str, str]:
    candidates = [
        ("publish_time_iso", data.get("publish_time_iso")),
        ("publish_time_text", data.get("publish_time_text")),
        ("publish_time", data.get("publish_time")),
        ("post_date", data.get("post_date")),
        ("published_at", data.get("published_at")),
        ("create_time", data.get("create_time")),
    ]
    for key, value in candidates:
        text = first_text(value)
        if text:
            return text, f"{prefix}.{key}"
    nested = data.get("meta")
    if isinstance(nested, dict):
        return true_publish_time_from(nested, f"{prefix}.meta")
    return "", ""


def archive_time_from(data: dict[str, Any], prefix: str) -> tuple[str, str]:
    for key in ("archived_at", "generatedAt", "captured_at", "capture_time"):
        text = first_text(data.get(key))
        if text:
            return text, f"{prefix}.{key}"
    return "", ""


def artifact_manifest_path(meta_path: Path) -> Path:
    return meta_path.parent / "artifact_manifest.json"


def sidecar_path(meta_path: Path) -> Path:
    return meta_path.parent / "sidecar.json"


def archive_meta_path_from_artifact(artifact: dict[str, Any]) -> Path | None:
    input_path = first_text(artifact.get("inputPath"), artifact.get("input_path"))
    if not input_path:
        return None
    raw_html = resolve_known_path(input_path)
    return raw_html.parent / "archive_meta.json"


def extract_date_row(article: dict[str, Any]) -> dict[str, Any]:
    article_uid = first_text(article.get("article_uid"))
    meta_raw = first_text(article.get("meta_path"))
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "article_uid": article_uid,
        "article_id": first_text(article.get("article_id")),
        "source_account": first_text(article.get("source_account")),
        "title": first_text(article.get("title")),
        "meta_path": meta_raw,
        "publish_time": "",
        "publish_time_source": "",
        "source_archived_at": "",
        "source_archived_at_source": "",
        "status": "missing_all_dates",
        "files_checked": [],
        "files_missing": [],
    }
    meta_path = resolve_known_path(meta_raw) if meta_raw else Path()
    if not meta_raw:
        return result

    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    meta = read_json_if_exists(meta_path)
    if meta:
        candidates.append(("meta", meta_path, meta))
    else:
        result["files_missing"].append(str(meta_path))

    sidecar = read_json_if_exists(sidecar_path(meta_path))
    if sidecar:
        candidates.append(("sidecar", sidecar_path(meta_path), sidecar))
    else:
        result["files_missing"].append(str(sidecar_path(meta_path)))

    artifact_path = artifact_manifest_path(meta_path)
    artifact = read_json_if_exists(artifact_path)
    if artifact:
        candidates.append(("artifact_manifest", artifact_path, artifact))
    else:
        result["files_missing"].append(str(artifact_path))

    for label, path, data in candidates:
        result["files_checked"].append(str(path))
        publish_time, source = true_publish_time_from(data, label)
        if publish_time:
            result["publish_time"] = publish_time
            result["publish_time_source"] = source
            result["status"] = "publish_time_found"
            return result

    archive_meta_path = archive_meta_path_from_artifact(artifact) if artifact else None
    if archive_meta_path is not None:
        archive_meta = read_json_if_exists(archive_meta_path)
        if archive_meta:
            result["files_checked"].append(str(archive_meta_path))
            archive_time, archive_source = archive_time_from(archive_meta, "archive_meta")
            if archive_time:
                result["source_archived_at"] = archive_time
                result["source_archived_at_source"] = archive_source
                result["status"] = "archive_time_only"
                return result
        else:
            result["files_missing"].append(str(archive_meta_path))

    for label, path, data in candidates:
        archive_time, archive_source = archive_time_from(data, label)
        if archive_time:
            result["source_archived_at"] = archive_time
            result["source_archived_at_source"] = archive_source
            result["status"] = "archive_time_only"
            return result

    return result


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Consumer Publish-Time Index",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source: `{summary['source_stable_articles']}`",
        f"- limit: `{summary['limit']}`",
        f"- rows: `{summary['rows']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reads only stable rows and directly referenced files.",
            "- Does not walk D: roots.",
            "- Does not treat archive capture time as publish time.",
            "- No publish, no DB writes, no paid API.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_index(stable_articles: Path, out_dir: Path, limit: int = 1000) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "publish_time_index.jsonl"
    tmp_path = index_path.with_suffix(index_path.suffix + ".tmp")
    status_counts: Counter[str] = Counter()
    rows = 0
    checked_files = 0
    missing_files = 0
    with stable_articles.open("r", encoding="utf-8") as source, tmp_path.open("w", encoding="utf-8") as out:
        for line in source:
            if limit and rows >= limit:
                break
            stripped = line.strip()
            if not stripped:
                continue
            article = json.loads(stripped)
            date_row = extract_date_row(article)
            status_counts[date_row["status"]] += 1
            checked_files += len(date_row["files_checked"])
            missing_files += len(date_row["files_missing"])
            out.write(json.dumps(date_row, ensure_ascii=False, sort_keys=True) + "\n")
            rows += 1
    tmp_path.replace(index_path)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_stable_articles": str(stable_articles),
        "out_dir": str(out_dir),
        "limit": limit,
        "rows": rows,
        "status_counts": dict(sorted(status_counts.items())),
        "checked_files": checked_files,
        "missing_files": missing_files,
        "index_path": str(index_path),
        "writes": "reports_only",
    }
    write_json(out_dir / "publish_time_index_summary.json", summary)
    write_summary_md(out_dir / "publish_time_index_summary.md", summary)
    return summary


def run(args: argparse.Namespace) -> int:
    summary = build_index(args.stable_articles, args.out_dir, args.limit)
    print(
        json.dumps(
            {
                "rows": summary["rows"],
                "status_counts": summary["status_counts"],
                "index": summary["index_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-articles", type=Path, default=DEFAULT_STABLE_ARTICLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=1000, help="0 means all rows; default is a bounded canary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
