#!/usr/bin/env python3
"""Run a bounded Maigret web-service canary for Stage7 P1 candidates.

This talks only to a local Maigret HTTP service. Results are saved as reports
and remain breadth-discovery evidence; they do not prove identity and are not
promoted into graph stores by this script.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


DEFAULT_CANDIDATES = Path("reports/p1_maigret_candidates_20260514/maigret_candidates.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_maigret_canary_20260514")
DEFAULT_BASE_URL = "http://127.0.0.1:5050"
JSON_LINK_RE = re.compile(r'href="([^"]+report_([^"/]+)\.json)"', re.I)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Maigret canary: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows = []
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
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def pick_usernames(candidate_path: Path, limit: int) -> list[str]:
    rows = read_jsonl(candidate_path)
    usernames = []
    for row in rows:
        username = str(row.get("username") or "").strip()
        if username and username not in usernames:
            usernames.append(username)
        if limit and len(usernames) >= limit:
            break
    return usernames


def extract_status_path(response: requests.Response) -> str:
    location = response.headers.get("Location") or response.headers.get("location") or ""
    if location:
        return location
    match = re.search(r"/status/[A-Za-z0-9_-]+", response.text or "")
    return match.group(0) if match else ""


def is_complete(html: str) -> bool:
    text = re.sub(r"<[^>]+>", " ", html)
    return "搜索已完成" in text or "Search completed" in text or "各用户报告" in text


def extract_json_links(html: str) -> list[dict[str, str]]:
    rows = []
    seen = set()
    for match in JSON_LINK_RE.finditer(html):
        href = match.group(1)
        username = match.group(2)
        if href in seen:
            continue
        seen.add(href)
        rows.append({"username": username, "href": href})
    return rows


def parse_report_payload(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return json.loads(stripped)
    except ValueError:
        rows = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows


def summarize_report(username: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        reports = payload
    else:
        reports = [payload]
    found = []
    for item in reports:
        if not isinstance(item, dict):
            continue
        site = item.get("site") or {}
        status_payload = item.get("status")
        if isinstance(status_payload, dict):
            status = str(status_payload.get("status") or item.get("status_string") or "")
            site_name = str(status_payload.get("site_name") or item.get("sitename") or "")
            status_url = str(status_payload.get("url") or "")
        else:
            status = str(status_payload or item.get("status_string") or "")
            site_name = str(item.get("sitename") or "")
            status_url = ""
        url = str(item.get("url_user") or item.get("url") or "")
        is_found = item.get("found") is True or item.get("status") is True or status.casefold() in {"claimed", "found", "exists"}
        if is_found:
            found.append(
                {
                    "site_name": site.get("name") or site_name or site.get("urlMain") or "",
                    "url": status_url or url,
                    "tags": site.get("tags") or [],
                    "status": status or "present",
                }
            )
    return {"username": username, "found_count": len(found), "found": found[:20]}


def run_canary(
    candidate_path: Path,
    out_dir: Path,
    base_url: str,
    limit: int,
    top_sites: int,
    timeout_sec: int,
    poll_timeout: int,
) -> dict[str, Any]:
    reject_d_path(candidate_path, "candidate_path")
    reject_d_path(out_dir, "out_dir")
    usernames = pick_usernames(candidate_path, limit)
    if not usernames:
        raise ValueError("no usernames selected for Maigret canary")
    session = requests.Session()
    response = session.post(
        urljoin(base_url.rstrip("/") + "/", "search"),
        data={
            "usernames": " ".join(usernames),
            "top_sites": str(top_sites),
            "timeout": str(timeout_sec),
            "disable_recursive_search": "on",
            "disable_extracting": "on",
        },
        timeout=max(30, timeout_sec + 10),
        allow_redirects=False,
    )
    status_path = extract_status_path(response)
    if not status_path:
        raise RuntimeError(f"Maigret did not return status path: HTTP {response.status_code}")
    status_url = urljoin(base_url.rstrip("/") + "/", status_path.lstrip("/"))
    html = ""
    started = time.time()
    while time.time() - started <= poll_timeout:
        poll = session.get(status_url, timeout=20)
        html = poll.text
        if is_complete(html):
            break
        time.sleep(2)
    complete = is_complete(html)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text(out_dir / "maigret_status.html", html)
    links = extract_json_links(html)
    summaries = []
    for link in links:
        report_url = urljoin(base_url.rstrip("/") + "/", link["href"].lstrip("/"))
        report_response = session.get(report_url, timeout=30)
        report_path = out_dir / f"report_{link['username']}.json"
        write_text(report_path, report_response.text)
        try:
            payload = parse_report_payload(report_response.text)
        except ValueError:
            payload = {}
        summary = summarize_report(link["username"], payload)
        summary["report_path"] = str(report_path)
        summaries.append(summary)
    report = {
        "schema_version": "stage7_p1_maigret_http_canary.v1",
        "generated_at": now_iso(),
        "ok": complete and bool(links),
        "decision": "maigret_canary_completed" if complete and links else "maigret_canary_incomplete",
        "base_url": base_url,
        "status_path": status_path,
        "usernames": usernames,
        "top_sites": top_sites,
        "timeout_sec": timeout_sec,
        "complete": complete,
        "json_reports": len(links),
        "summaries": summaries,
        "writes": "reports_only",
        "warning": "Maigret hits are breadth evidence only, not identity proof.",
    }
    write_json(out_dir / "maigret_canary_summary.json", report)
    write_markdown(out_dir / "maigret_canary_summary.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# P1 Maigret HTTP Canary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- status_path: `{report['status_path']}`",
        f"- usernames: `{json.dumps(report['usernames'], ensure_ascii=False)}`",
        f"- top_sites: `{report['top_sites']}`",
        f"- timeout_sec: `{report['timeout_sec']}`",
        f"- json_reports: `{report['json_reports']}`",
        "",
        "## Found Counts",
        "",
    ]
    for item in report["summaries"]:
        lines.append(f"- `{item['username']}`: found_count=`{item['found_count']}`, report=`{item['report_path']}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Local Maigret HTTP service only.",
            "- Maigret hit is not identity proof.",
            "- No graph/vector/DB write.",
            "- No paid API.",
            "- No D: scan.",
            "- No publish.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = run_canary(
        args.candidates,
        args.out_dir,
        args.base_url,
        args.limit,
        args.top_sites,
        args.timeout,
        args.poll_timeout,
    )
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "json_reports": report["json_reports"], "summary": str(args.out_dir / "maigret_canary_summary.json")}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--top-sites", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--poll-timeout", type=int, default=120)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
