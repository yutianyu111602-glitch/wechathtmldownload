#!/usr/bin/env python3
"""Build a Stage7 data-directory inventory from live outputs and script paths.

This is a read-only audit/report script. It scans bounded Stage7 data roots,
extracts output path references from historical scripts, and writes a compact
directory ledger for takeover and longrun planning.

Safety boundaries:
- Does not read secrets, env files, cookies, browser stores, or token files.
- Does not call paid APIs or external services.
- Does not mutate Qdrant, Neo4j, SQLite, mem0, CloudRun, or source data.
- Only scans explicit Stage7/project roots; D: access is limited to known
  Stage7/research subdirectories.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
DEFAULT_OUT_DIR = ROOT / "reports" / "stage7_full_data_directory_inventory_20260518"
SCHEMA_VERSION = "stage7_full_data_directory_inventory.v1"

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

SECRET_NAME_PARTS = (
    ".env",
    "secret",
    "secrets",
    "token",
    "cookie",
    "cookies",
    "oauth",
    "password",
    "passwd",
    "credential",
    "credentials",
    "private_key",
    "id_rsa",
)

CODE_EXTS = {".py", ".ps1", ".mjs", ".mts", ".js", ".ts", ".bat", ".cmd", ".md"}
DATA_EXTS = {
    ".json",
    ".jsonl",
    ".csv",
    ".sqlite",
    ".db",
    ".parquet",
    ".txt",
    ".md",
    ".html",
    ".log",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".gz",
}

PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\(?:[^\\\r\n\"'`]+\\)*[^\\\r\n\"'`]+"),
    re.compile(r"(?:tools[/\\]stage7_rewrite[/\\])?reports[/\\][A-Za-z0-9_.=\- /\\]+"),
    re.compile(r"D:\\downstream_results\\stage7_rewrite(?:\\[^\\\r\n\"'`]+)*", re.IGNORECASE),
    re.compile(r"D:\\agent-comm\\runtime\\reports\\research(?:\\[^\\\r\n\"'`]+)*", re.IGNORECASE),
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_secret_like(path: Path) -> bool:
    lowered_parts = [part.casefold() for part in path.parts]
    lowered_name = path.name.casefold()
    if any(part in SKIP_DIR_NAMES for part in lowered_parts):
        return True
    return any(part in lowered_name for part in SECRET_NAME_PARTS)


def safe_rel(path: Path, base: Path | None = None) -> str:
    try:
        if base is not None:
            return path.resolve().relative_to(base.resolve()).as_posix()
    except (OSError, ValueError):
        pass
    return str(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def classify_phase(path_text: str) -> str:
    low = path_text.casefold().replace("\\", "/")
    if any(key in low for key in ("dajiala", "ocr", "poster", "asset", "image", "gif", "webp")):
        return "phase_a_assets_ocr_paid"
    if any(key in low for key in ("fullmap", "mptext", "archive", "where_to_rave", "recapture", "download")):
        return "phase_a_archive_capture"
    if any(key in low for key in ("flash", "deepseek", "stable_extract", "score", "llm_extract", "v6", "93k")):
        return "phase_b_llm_extract"
    if any(key in low for key in ("merge", "canonical", "stable_coverage", "publish_time")):
        return "phase_c_stable_merge"
    if any(key in low for key in ("vector", "qdrant", "embed", "rerank", "snowflake", "english_sidecar")):
        return "phase_d_vector_retrieval"
    if any(key in low for key in ("neo4j", "graph", "rag", "recommend", "social_edge", "maigret", "opencli", "camofox", "radio")):
        return "phase_d_graph_external_evidence"
    if any(key in low for key in ("consumer", "weekly", "miniprogram", "cloudrun", "release_pack", "api")):
        return "phase_e_consumer_publish"
    if any(key in low for key in ("prefect", "hermes", "longrun", "handoff", "prd", "gate", "readiness", "operation")):
        return "ops_control_handoff"
    if any(key in low for key in ("research", "source_pack", "local-deep-research", "library_upload")):
        return "research_layer"
    return "unclassified_or_misc"


USER_PROVIDED_ROOTS = [
    (r"C:\Users\pc\code\dj-dataset", 6),
    (r"C:\Users\pc\code\huaidj-submit", 6),
    (r"D:\rawwechat_archive_mptext", 4),
    (r"D:\weixinoutput", 4),
    (r"D:\HTML_retry_rate_limited", 4),
    (r"D:\rawwechat_md_smoke_input", 4),
    (r"D:\rawwechat_md_smoke", 4),
    (r"D:\rawwechat", 4),
    (r"D:\HTML", 4),
    (r"D:\rawwechat_discovery", 4),
    (r"D:\rawwechat_md", 4),
    (r"D:\artifacts", 4),
]


def choose_roots(include_known_d_roots: bool, include_user_roots: bool, max_files_per_root: int) -> list[dict[str, Any]]:
    roots = [
        {
            "id": "stage7_project",
            "path": ROOT,
            "max_depth": 9,
            "allow_d": False,
            "max_files": max_files_per_root,
        },
        {
            "id": "local_deep_research_wechat",
            "path": Path(r"C:\code\local-deep-research-wechat"),
            "max_depth": 6,
            "allow_d": False,
            "max_files": max_files_per_root,
        },
    ]
    if include_known_d_roots:
        roots.extend(
            [
                {
                    "id": "d_downstream_stage7_rewrite",
                    "path": Path(r"D:\downstream_results\stage7_rewrite"),
                    "max_depth": 5,
                    "allow_d": True,
                    "max_files": max_files_per_root,
                },
                {
                    "id": "d_agent_comm_research_reports",
                    "path": Path(r"D:\agent-comm\runtime\reports\research"),
                    "max_depth": 3,
                    "allow_d": True,
                    "max_files": max_files_per_root,
                },
            ]
        )
    if include_user_roots:
        for raw_path, max_depth in USER_PROVIDED_ROOTS:
            path = Path(raw_path)
            roots.append(
                {
                    "id": "user_root_" + re.sub(r"[^A-Za-z0-9]+", "_", raw_path).strip("_").casefold(),
                    "path": path,
                    "max_depth": max_depth,
                    "allow_d": str(path).casefold().startswith("d:\\"),
                    "max_files": max_files_per_root,
                }
            )
    return roots


def depth_from(root: Path, path: Path) -> int:
    try:
        return len(path.resolve().relative_to(root.resolve()).parts)
    except (OSError, ValueError):
        return 0


def scan_directory_root(root_spec: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(root_spec["path"])
    max_depth = root_spec.get("max_depth")
    max_files = int(root_spec.get("max_files") or 0)
    root_summary: dict[str, Any] = {
        "root_id": root_spec["id"],
        "root_path": str(root),
        "exists": root.exists(),
        "max_depth": max_depth,
        "max_files": max_files,
        "scanned_dirs": 0,
        "total_files": 0,
        "total_size_bytes": 0,
        "skipped_secret_like": 0,
        "skipped_depth_dirs": 0,
        "truncated_by_file_cap": False,
        "phase_counts": Counter(),
        "ext_counts": Counter(),
        "latest_mtime": None,
    }
    if not root.exists():
        return [], root_summary

    rows: list[dict[str, Any]] = []
    for current, dirnames, filenames in os.walk(root):
        if max_files and root_summary["total_files"] >= max_files:
            root_summary["truncated_by_file_cap"] = True
            dirnames[:] = []
            break
        current_path = Path(current)
        current_depth = depth_from(root, current_path)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in SKIP_DIR_NAMES and not is_secret_like(current_path / name)
        ]
        if max_depth is not None and current_depth >= max_depth:
            root_summary["skipped_depth_dirs"] += len(dirnames)
            dirnames[:] = []

        ext_counts: Counter[str] = Counter()
        phase_counts: Counter[str] = Counter()
        data_file_count = 0
        file_count = 0
        size_bytes = 0
        latest_mtime = 0.0
        largest_files: list[dict[str, Any]] = []

        for filename in filenames:
            if max_files and root_summary["total_files"] + file_count >= max_files:
                root_summary["truncated_by_file_cap"] = True
                break
            path = current_path / filename
            if is_secret_like(path):
                root_summary["skipped_secret_like"] += 1
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            ext = path.suffix.casefold() or "<none>"
            file_count += 1
            size_bytes += stat.st_size
            latest_mtime = max(latest_mtime, stat.st_mtime)
            ext_counts[ext] += 1
            root_summary["ext_counts"][ext] += 1
            if ext in DATA_EXTS:
                data_file_count += 1
            phase = classify_phase(path.as_posix())
            phase_counts[phase] += 1
            largest_files.append(
                {
                    "name": filename,
                    "size_bytes": stat.st_size,
                    "ext": ext,
                    "phase": phase,
                }
            )

        if file_count or current_depth == 0:
            phase = classify_phase(current_path.as_posix())
            row = {
                "root_id": root_spec["id"],
                "root_path": str(root),
                "path": str(current_path),
                "relative_path": safe_rel(current_path, root),
                "depth": current_depth,
                "phase": phase,
                "file_count": file_count,
                "data_file_count": data_file_count,
                "size_bytes": size_bytes,
                "latest_mtime": datetime.fromtimestamp(latest_mtime).isoformat(timespec="seconds") if latest_mtime else None,
                "extensions": dict(ext_counts.most_common()),
                "file_phase_counts": dict(phase_counts.most_common()),
                "largest_files": sorted(largest_files, key=lambda item: item["size_bytes"], reverse=True)[:5],
            }
            rows.append(row)
            root_summary["scanned_dirs"] += 1
            root_summary["total_files"] += file_count
            root_summary["total_size_bytes"] += size_bytes
            root_summary["phase_counts"][phase] += 1
            if latest_mtime:
                root_summary["latest_mtime"] = max(root_summary.get("latest_mtime") or 0, latest_mtime)

    if isinstance(root_summary.get("latest_mtime"), float):
        root_summary["latest_mtime"] = datetime.fromtimestamp(root_summary["latest_mtime"]).isoformat(timespec="seconds")
    root_summary["phase_counts"] = dict(root_summary["phase_counts"].most_common())
    root_summary["ext_counts"] = dict(root_summary["ext_counts"].most_common(30))
    return rows, root_summary


def code_files() -> list[Path]:
    files: list[Path] = []
    for base in (ROOT, REPO_ROOT / "services" / "weekly_activity_cloudrun"):
        if not base.exists():
            continue
        for current, dirnames, filenames in os.walk(base):
            current_path = Path(current)
            dirnames[:] = [
                name
                for name in dirnames
                if name not in SKIP_DIR_NAMES
                and name != "reports"
                and not is_secret_like(current_path / name)
            ]
            for filename in filenames:
                path = current_path / filename
                if path.suffix.casefold() in CODE_EXTS and not is_secret_like(path):
                    files.append(path)
    unique = {str(path.resolve()): path for path in files}
    return sorted(unique.values(), key=lambda item: item.as_posix().casefold())


def normalize_path_reference(raw: str) -> str:
    value = raw.strip().strip("\"'`),]")
    value = re.sub(r"\s+", " ", value)
    if value.startswith("tools/stage7_rewrite/") or value.startswith("tools\\stage7_rewrite\\"):
        return str(REPO_ROOT / value.replace("/", "\\"))
    if value.startswith("reports/") or value.startswith("reports\\"):
        return str(ROOT / value.replace("/", "\\"))
    return value


def extract_script_path_references() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in code_files():
        try:
            if path.stat().st_size > 2_500_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen: set[tuple[int, str]] = set()
        for idx, line in enumerate(text.splitlines(), start=1):
            if not any(token in line for token in ("reports", "D:\\", "downstream_results", "agent-comm", "out_dir", "REPORT_ROOT", "DEFAULT_OUT_DIR")):
                continue
            for pattern in PATH_PATTERNS:
                for match in pattern.finditer(line):
                    raw = match.group(0)
                    normalized = normalize_path_reference(raw)
                    key = (idx, normalized)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "script": safe_rel(path, ROOT),
                            "line": idx,
                            "raw_reference": raw,
                            "normalized_reference": normalized,
                            "phase": classify_phase(normalized),
                            "exists": Path(normalized).exists() if re.match(r"^[A-Za-z]:\\", normalized) else None,
                            "context": line.strip()[:300],
                        }
                    )
    return rows


def summarize_output_roots(ref_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in ref_rows:
        normalized = str(row["normalized_reference"])
        candidate = normalized
        if "reports" in normalized.replace("\\", "/"):
            path = Path(normalized)
            parts = path.parts
            try:
                report_idx = [part.casefold() for part in parts].index("reports")
                if len(parts) > report_idx + 1:
                    candidate = str(Path(*parts[: report_idx + 2]))
            except ValueError:
                pass
        elif normalized.casefold().startswith("d:\\downstream_results\\stage7_rewrite"):
            parts = Path(normalized).parts
            candidate = str(Path(*parts[: min(len(parts), 4)]))
        key = candidate
        item = grouped.setdefault(
            key,
            {
                "output_root": key,
                "phase": classify_phase(key),
                "exists": Path(key).exists() if re.match(r"^[A-Za-z]:\\", key) else None,
                "reference_count": 0,
                "scripts": Counter(),
            },
        )
        item["reference_count"] += 1
        item["scripts"][row["script"]] += 1
    output_rows: list[dict[str, Any]] = []
    for item in grouped.values():
        item = dict(item)
        item["scripts"] = dict(item["scripts"].most_common(20))
        output_rows.append(item)
    return sorted(output_rows, key=lambda item: (-int(item["reference_count"]), str(item["output_root"]).casefold()))


def phase_map(directory_rows: list[dict[str, Any]], ref_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    files_by_phase: dict[str, int] = defaultdict(int)
    data_files_by_phase: dict[str, int] = defaultdict(int)
    size_by_phase: dict[str, int] = defaultdict(int)
    dirs_by_phase: dict[str, int] = defaultdict(int)
    roots_by_phase: dict[str, set[str]] = defaultdict(set)
    for row in directory_rows:
        phase = str(row["phase"])
        dirs_by_phase[phase] += 1
        files_by_phase[phase] += int(row["file_count"])
        data_files_by_phase[phase] += int(row["data_file_count"])
        size_by_phase[phase] += int(row["size_bytes"])
        roots_by_phase[phase].add(str(row["root_id"]))
    script_refs = Counter(str(row["phase"]) for row in ref_rows)
    phases = sorted(set(dirs_by_phase) | set(script_refs))
    return [
        {
            "phase": phase,
            "directory_count": dirs_by_phase[phase],
            "file_count": files_by_phase[phase],
            "data_file_count": data_files_by_phase[phase],
            "size_bytes": size_by_phase[phase],
            "script_reference_count": script_refs[phase],
            "roots": sorted(roots_by_phase[phase]),
        }
        for phase in phases
    ]


def render_markdown(summary: dict[str, Any], phase_rows: list[dict[str, Any]], output_roots: list[dict[str, Any]]) -> str:
    lines = [
        "# Stage7 Full Data Directory Inventory",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- schema_version: `{summary['schema_version']}`",
        f"- directory_rows: `{summary['directory_rows']}`",
        f"- script_path_references: `{summary['script_path_references']}`",
        f"- script_output_roots: `{summary['script_output_roots']}`",
        f"- total_files: `{summary['totals']['total_files']}`",
        f"- total_size_bytes: `{summary['totals']['total_size_bytes']}`",
        "",
        "## Scope",
        "",
        "Read-only scan. Secret-like filenames, virtualenvs, caches and node_modules were skipped. D: access was bounded to known Stage7/research subdirectories only.",
        "",
        "## Root Summary",
        "",
        "| root | exists | dirs | files | bytes | latest_mtime |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for root in summary["roots"]:
        lines.append(
            f"| `{root['root_id']}` | `{root['exists']}` | {root['scanned_dirs']} | {root['total_files']} | {root['total_size_bytes']} | `{root.get('latest_mtime')}` |"
        )
    lines.extend(["", "## Phase Map", "", "| phase | dirs | files | data_files | bytes | script_refs | roots |", "|---|---:|---:|---:|---:|---:|---|"])
    for row in sorted(phase_rows, key=lambda item: (-item["file_count"], item["phase"])):
        lines.append(
            f"| `{row['phase']}` | {row['directory_count']} | {row['file_count']} | {row['data_file_count']} | {row['size_bytes']} | {row['script_reference_count']} | `{', '.join(row['roots'])}` |"
        )
    lines.extend(["", "## Top Script-Derived Output Roots", "", "| output_root | phase | exists | refs | top scripts |", "|---|---|---:|---:|---|"])
    for row in output_roots[:40]:
        scripts = ", ".join(f"{name}:{count}" for name, count in list(row["scripts"].items())[:3])
        lines.append(
            f"| `{row['output_root']}` | `{row['phase']}` | `{row['exists']}` | {row['reference_count']} | `{scripts}` |"
        )
    lines.extend(
        [
            "",
            "## Next Use",
            "",
            "- Use `directory_inventory.jsonl` as the data-directory ledger.",
            "- Use `script_path_references.jsonl` to trace which historical scripts produced or consumed each path.",
            "- Use `script_output_roots.jsonl` before starting new longrun work to avoid duplicating old paid/API runs.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_inventory(
    out_dir: Path,
    include_known_d_roots: bool,
    include_user_roots: bool,
    max_files_per_root: int,
) -> dict[str, Any]:
    directory_rows: list[dict[str, Any]] = []
    root_summaries: list[dict[str, Any]] = []
    for root_spec in choose_roots(
        include_known_d_roots=include_known_d_roots,
        include_user_roots=include_user_roots,
        max_files_per_root=max_files_per_root,
    ):
        rows, root_summary = scan_directory_root(root_spec)
        directory_rows.extend(rows)
        root_summaries.append(root_summary)

    ref_rows = extract_script_path_references()
    output_roots = summarize_output_roots(ref_rows)
    phases = phase_map(directory_rows, ref_rows)
    totals = {
        "total_files": sum(int(root.get("total_files") or 0) for root in root_summaries),
        "total_size_bytes": sum(int(root.get("total_size_bytes") or 0) for root in root_summaries),
        "skipped_secret_like": sum(int(root.get("skipped_secret_like") or 0) for root in root_summaries),
        "skipped_depth_dirs": sum(int(root.get("skipped_depth_dirs") or 0) for root in root_summaries),
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "root": str(ROOT),
        "include_known_d_roots": include_known_d_roots,
        "include_user_roots": include_user_roots,
        "max_files_per_root": max_files_per_root,
        "directory_rows": len(directory_rows),
        "script_path_references": len(ref_rows),
        "script_output_roots": len(output_roots),
        "phase_rows": len(phases),
        "totals": totals,
        "roots": root_summaries,
        "outputs": {
            "summary_json": str(out_dir / "directory_inventory_summary.json"),
            "summary_md": str(out_dir / "directory_inventory_summary.md"),
            "directory_inventory_jsonl": str(out_dir / "directory_inventory.jsonl"),
            "script_path_references_jsonl": str(out_dir / "script_path_references.jsonl"),
            "script_output_roots_jsonl": str(out_dir / "script_output_roots.jsonl"),
            "phase_map_jsonl": str(out_dir / "data_phase_map.jsonl"),
        },
    }

    write_jsonl(out_dir / "directory_inventory.jsonl", directory_rows)
    write_jsonl(out_dir / "script_path_references.jsonl", ref_rows)
    write_jsonl(out_dir / "script_output_roots.jsonl", output_roots)
    write_jsonl(out_dir / "data_phase_map.jsonl", phases)
    write_json(out_dir / "directory_inventory_summary.json", summary)
    write_text(out_dir / "directory_inventory_summary.md", render_markdown(summary, phases, output_roots))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage7 full data-directory inventory.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--skip-known-d-roots", action="store_true")
    parser.add_argument("--skip-user-roots", action="store_true")
    parser.add_argument("--max-files-per-root", type=int, default=120_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_inventory(
        args.out_dir,
        include_known_d_roots=not args.skip_known_d_roots,
        include_user_roots=not args.skip_user_roots,
        max_files_per_root=args.max_files_per_root,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
