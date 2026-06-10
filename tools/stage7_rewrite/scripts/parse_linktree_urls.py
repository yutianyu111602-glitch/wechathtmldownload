#!/usr/bin/env python3
"""Parse public Linktree candidates for PRD-16.

The script is report-only. It fetches public Linktree pages, extracts outbound
HTTP links, classifies their platforms, and writes canary reports.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import parse


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_public_social_links as link_validator  # noqa: E402


DEFAULT_CANDIDATES = Path("reports/social_deep_candidates_20260515/linktree_urls.jsonl")
DEFAULT_OUT_DIR = Path("reports/linktree_canary_20260515")
SCHEMA_VERSION = "stage7_social_deep_linktree_parse.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for PRD-16 Linktree parse: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "candidates")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def extract_public_links(body: str, page_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    href_values = re.findall(r"""href=["']([^"']+)["']""", body, flags=re.I)
    raw_values = href_values + re.findall(r"https?://[^\s\"'<>]+", body, flags=re.I)
    for value in raw_values:
        url = parse.unquote(value).strip().rstrip("),.;")
        if url.startswith("/"):
            url = parse.urljoin(page_url, url)
        if not url.startswith(("http://", "https://")):
            continue
        platform = link_validator.platform_from_url(url)
        if platform == "linktree":
            continue
        normalized = link_validator.normalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(url)
    return links


def run_linktree_parse(
    candidates_path: Path,
    out_dir: Path,
    limit: int,
    expected_min_urls: int,
    timeout_sec: float,
    max_bytes: int,
    fetcher: Callable[[str, float, int], dict[str, Any]] = link_validator.fetch_url,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    candidates = [row for row in read_jsonl(candidates_path) if first_text(row.get("platform")) == "linktree"]
    if limit > 0:
        candidates = candidates[:limit]
    results: list[dict[str, Any]] = []
    platform_counts: Counter[str] = Counter()
    for candidate in candidates:
        url = first_text(candidate.get("url"))
        fetched = fetcher(url, timeout_sec, max_bytes)
        body = first_text(fetched.get("body"))
        page_title = link_validator.extract_title(body)
        soft_not_found = link_validator.looks_soft_not_found(fetched.get("status_code"), page_title, body)
        accessible = bool(fetched.get("ok")) and not soft_not_found
        outbound = extract_public_links(body, first_text(fetched.get("final_url")) or url) if accessible else []
        outbound_rows = [
            {
                "url": item,
                "normalized_url": link_validator.normalize_url(item),
                "platform": link_validator.platform_from_url(item),
                "link_kind": link_validator.link_kind(item),
            }
            for item in outbound
        ]
        for item in outbound_rows:
            platform_counts[item["platform"]] += 1
        results.append(
            {
                "schema_version": SCHEMA_VERSION + ".row",
                "checked_at": now_iso(),
                "source": first_text(candidate.get("source")) or "social_deep_candidates",
                "source_family": first_text(candidate.get("source_family")),
                "subject_name": first_text(candidate.get("subject_name")),
                "evidence_url": first_text(candidate.get("evidence_url")),
                "url": url,
                "normalized_url": first_text(candidate.get("normalized_url")) or link_validator.normalize_url(url),
                "accessible": accessible,
                "status_code": fetched.get("status_code"),
                "final_url": first_text(fetched.get("final_url")) or url,
                "page_title": page_title,
                "soft_not_found": soft_not_found,
                "error": first_text(fetched.get("error")),
                "outbound_link_count": len(outbound_rows),
                "outbound_links": outbound_rows,
                "graph_ready": False,
                "identity_proof": False,
            }
        )

    parsed_url_count = sum(row["outbound_link_count"] for row in results)
    gate_met = parsed_url_count >= expected_min_urls
    if gate_met:
        decision = "linktree_parse_gate_met"
    elif results and parsed_url_count:
        decision = "linktree_parse_partial"
    elif results:
        decision = "linktree_parse_no_outbound_links"
    else:
        decision = "linktree_parse_empty"

    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "linktree_parse_results.jsonl"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": bool(results),
        "candidates_path": str(candidates_path),
        "result_path": str(result_path),
        "candidate_rows_checked": len(results),
        "parsed_url_count": parsed_url_count,
        "expected_min_urls": expected_min_urls,
        "gate_met": gate_met,
        "outbound_platform_counts": dict(platform_counts),
        "graph_ready_links": 0,
        "identity_proof_links": 0,
        "safety": [
            "reports_only",
            "public_urls_only",
            "no_login",
            "no_cookies",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
            "linktree_outbound_links_are_not_identity_proof",
        ],
    }
    write_jsonl(result_path, results)
    write_json(out_dir / "linktree_parse_summary.json", summary)
    write_markdown(out_dir / "linktree_parse_summary.md", summary, results)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        "# PRD-16 Linktree Parse Canary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- candidate_rows_checked: `{summary['candidate_rows_checked']}`",
        f"- parsed_url_count: `{summary['parsed_url_count']}`",
        f"- expected_min_urls: `{summary['expected_min_urls']}`",
        f"- gate_met: `{summary['gate_met']}`",
        f"- result_path: `{summary['result_path']}`",
        "",
        "## Outbound Platform Counts",
        "",
    ]
    for key, value in sorted(summary["outbound_platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Rows", "", "| subject | status | outbound | url |", "|---|---|---:|---|"])
    for row in results:
        status = "reachable" if row["accessible"] else "blocked_or_unreachable"
        subject = first_text(row.get("subject_name")).replace("|", "/")
        lines.append(f"| {subject} | {status} | {row['outbound_link_count']} | {row['url']} |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Linktree outbound links are not identity proof.",
            "- No login, cookies, graph/vector/DB write, paid API, D: scan, or publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--expected-min-urls", type=int, default=10)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--max-bytes", type=int, default=256_000)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = run_linktree_parse(
        candidates_path=args.candidates,
        out_dir=args.out_dir,
        limit=args.limit,
        expected_min_urls=args.expected_min_urls,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "parsed_url_count": summary["parsed_url_count"],
                "summary": str(args.out_dir / "linktree_parse_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
