#!/usr/bin/env python3
"""Build the S123 Docker/exporter login-state diagnostic.

Default mode is metadata/no-secret. It may probe localhost exporter endpoints,
but it does not print token/cookie values, perform account actions, upload, or
deploy. Pass --allow-auth-probe to send a discovered local auth key to the
local exporter API while still redacting the value from reports.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.stage7_rewrite.scripts.diagnose_weekly_exporter_session import (
        DEFAULT_COOKIE_DIR,
        DEFAULT_ENDPOINT,
        DEFAULT_REGISTRY,
        build_report as build_no_secret_session_report,
    )
    from tools.stage7_rewrite.scripts.manage_weekly_exporter_auth import build_status_report
except ModuleNotFoundError:  # pragma: no cover
    from diagnose_weekly_exporter_session import (  # type: ignore
        DEFAULT_COOKIE_DIR,
        DEFAULT_ENDPOINT,
        DEFAULT_REGISTRY,
        build_report as build_no_secret_session_report,
    )
    from manage_weekly_exporter_auth import build_status_report  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "docker_exporter_login_state_diagnostic_s123.v1"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "docker_exporter_login_state_s123_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_DOCKER_EXPORTER_LOGIN_STATE_S123_20260601.md"
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|api_key\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)
SECRET_KEYS = {"api_key", "auth_key", "cookie", "token", "password", "secret", "value", "data"}
SAFE_SECRET_NAMED_KEYS = {
    "no_secret_mode",
    "auth_lookup_skipped",
    "cookie_dir_lookup_skipped",
    "docker_cookie_key_present",
    "auth_env_present",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in SAFE_SECRET_NAMED_KEYS:
                out[key] = redact(item)
            elif key_text in SECRET_KEYS or any(token in key_text for token in ("token", "cookie", "secret", "password")):
                out[key] = "<redacted>"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and SECRET_RE.search(value):
        return SECRET_RE.sub("<redacted>", value)
    return value


def docker_ps() -> dict[str, Any]:
    command = ["docker", "ps", "--format", "{{json .}}"]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc)[:240], "containers": []}
    containers = []
    for line in completed.stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = str(payload.get("Names") or payload.get("Name") or "")
        image = str(payload.get("Image") or "")
        ports = str(payload.get("Ports") or "")
        if re.search(r"wechat|exporter|mptext|weekly", f"{name} {image} {ports}", re.I):
            containers.append(
                {
                    "name": name,
                    "image": image,
                    "status": str(payload.get("Status") or ""),
                    "ports": ports,
                }
            )
    return {
        "available": completed.returncode == 0,
        "returncode": completed.returncode,
        "error": (completed.stderr or "")[:240],
        "containers": containers,
    }


def namespace(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def no_secret_probe(endpoint: str, registry: Path, timeout_sec: int) -> dict[str, Any]:
    args = namespace(
        registry=registry,
        endpoint=endpoint,
        auth_env="MPTEXT_AUTH_KEY",
        auth_source="auto",
        cookie_dir=DEFAULT_COOKIE_DIR,
        timeout_sec=timeout_sec,
        no_secret=True,
    )
    return redact(build_no_secret_session_report(args))


def auth_probe(endpoint: str, registry: Path, cookie_dir: Path, auth_source: str, timeout_sec: int) -> dict[str, Any]:
    args = namespace(
        endpoint=endpoint,
        registry=registry,
        cookie_dir=cookie_dir,
        auth_env="MPTEXT_AUTH_KEY",
        auth_source=auth_source,
        timeout_sec=timeout_sec,
        print_key=False,
    )
    return redact(build_status_report(args))


def classify_state(docker: dict[str, Any], session: dict[str, Any], auth: dict[str, Any] | None) -> dict[str, Any]:
    containers = docker.get("containers") or []
    if docker.get("available") is False:
        return {"state": "docker_unavailable", "confidence": "medium", "reason": docker.get("error") or "docker command unavailable"}
    if not containers:
        return {"state": "docker_exporter_not_running", "confidence": "high", "reason": "no exporter-like Docker container found"}

    if auth:
        decision = str(auth.get("auth_lifecycle_decision") or auth.get("decision") or "")
        if auth.get("auth_lifecycle_ok") and auth.get("session_ok"):
            return {"state": "authenticated", "confidence": "high", "reason": decision or "auth lifecycle and article probe ok"}
        if auth.get("auth_lifecycle_ok") and auth.get("article_probe_soft_block"):
            return {"state": "api_progress_soft_blocked", "confidence": "high", "reason": decision}
        if decision == "exporter_auth_key_missing":
            return {"state": "auth_key_missing", "confidence": "high", "reason": decision}
        if decision == "exporter_session_invalid":
            return {"state": "session_invalid_needs_qr", "confidence": "high", "reason": decision}
        if "authkey_endpoint_unavailable" in decision:
            return {"state": "authkey_endpoint_unavailable", "confidence": "medium", "reason": decision}

    session_decision = str(session.get("decision") or "")
    error_text = f"{session.get('error') or ''} {session.get('err_msg') or ''}".lower()
    if session_decision == "exporter_session_requires_auth_or_fresh_session":
        return {"state": "auth_required_unverified", "confidence": "medium", "reason": session_decision}
    if session_decision == "exporter_session_ok":
        return {"state": "authenticated_without_secret_probe", "confidence": "medium", "reason": session_decision}
    if "connection refused" in error_text or "timed out" in error_text or "urlopen error" in error_text:
        return {"state": "endpoint_unreachable", "confidence": "medium", "reason": error_text[:180]}
    return {"state": "unknown_exporter_state", "confidence": "low", "reason": session_decision or error_text[:180]}


def next_actions(state: str) -> list[str]:
    if state == "docker_exporter_not_running":
        return ["Start or inspect the wechat-article-exporter container before API/login probing."]
    if state in {"auth_required_unverified", "session_invalid_needs_qr"}:
        return ["Generate a QR with manage_weekly_exporter_auth.py --mode qr, then verify authkey hash only.", "Do not print or persist the raw API key."]
    if state == "api_progress_soft_blocked":
        return ["Keep auth lifecycle as valid; inspect exporter article API rate/frequency controls with bounded retries."]
    if state == "authenticated":
        return ["Proceed to a tiny bounded exporter API smoke before any large download queue."]
    if state == "endpoint_unreachable":
        return ["Check Docker port mapping for 127.0.0.1:17300 and container health logs without reading credentials."]
    return ["Collect a bounded status report and keep raw credentials redacted."]


def secret_findings(report: dict[str, Any]) -> list[dict[str, str]]:
    text = json.dumps(report, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly Docker Exporter Login-State Diagnostic S123",
        "",
        f"- Decision: `{report['decision']}`",
        f"- State: `{report['state']['state']}`",
        f"- Confidence: `{report['state']['confidence']}`",
        f"- Secret-like findings: `{report['finding_count']}`",
        f"- Allow auth probe: `{report['inputs']['allow_auth_probe']}`",
        "",
        "## Docker",
        "",
        f"- Available: `{report['docker'].get('available')}`",
        f"- Containers matched: `{len(report['docker'].get('containers') or [])}`",
    ]
    for container in report["docker"].get("containers") or []:
        lines.append(f"- `{container.get('name')}` image `{container.get('image')}` status `{container.get('status')}` ports `{container.get('ports')}`")
    lines.extend(["", "## Probe Summary", ""])
    lines.append(f"- No-secret decision: `{report['session_probe'].get('decision')}`")
    if report.get("auth_probe"):
        lines.append(f"- Auth lifecycle decision: `{report['auth_probe'].get('auth_lifecycle_decision')}`")
        lines.append(f"- Auth lifecycle ok: `{report['auth_probe'].get('auth_lifecycle_ok')}`")
        lines.append(f"- API key hash present: `{bool(report['auth_probe'].get('api_key_hash'))}`")
    lines.extend(["", "## Next Actions", ""])
    for action in report["next_actions"]:
        lines.append(f"- {action}")
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- No upload, deploy, review submission, account action, browser credential read, or raw secret printing.",
            "- Raw cookie/token/API-key values are redacted from JSON and Markdown outputs.",
            "- QR generation is not performed by this diagnostic; it only recommends the existing bounded QR tool when needed.",
            "",
        ]
    )
    return "\n".join(lines)


def build_diagnostic(
    endpoint: str,
    registry: Path,
    cookie_dir: Path,
    out_dir: Path,
    scorecard: Path,
    timeout_sec: int,
    allow_auth_probe: bool,
    auth_source: str,
) -> dict[str, Any]:
    docker = redact(docker_ps())
    session = no_secret_probe(endpoint, registry, timeout_sec)
    auth = auth_probe(endpoint, registry, cookie_dir, auth_source, timeout_sec) if allow_auth_probe else None
    state = classify_state(docker, session, auth)
    report_path = out_dir / "docker_exporter_login_state_diagnostic.json"
    markdown_path = out_dir / "docker_exporter_login_state_diagnostic.md"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "docker_exporter_login_state_diagnostic_ready",
        "inputs": {
            "endpoint": endpoint.rstrip("/"),
            "registry": rel_path(registry),
            "cookie_dir": rel_path(cookie_dir),
            "allow_auth_probe": allow_auth_probe,
            "auth_source": auth_source,
            "timeout_sec": timeout_sec,
        },
        "docker": docker,
        "session_probe": session,
        "auth_probe": auth,
        "state": state,
        "next_actions": next_actions(state["state"]),
        "boundaries": {
            "read_only_diagnostic": True,
            "docker_ps_only": True,
            "qr_generated": False,
            "account_action": False,
            "upload_or_deploy": False,
            "browser_credential_read": False,
            "raw_secret_output": False,
            "cookie_values_printed": False,
            "token_values_printed": False,
        },
        "outputs": {
            "report": rel_path(report_path),
            "markdown": rel_path(markdown_path),
            "scorecard": rel_path(scorecard),
        },
        "next_story": "S124",
    }
    findings = secret_findings(report)
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings:
        report["decision"] = "docker_exporter_login_state_diagnostic_blocked_secret_like_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_path, report)
    markdown = render_markdown(report)
    atomic_write_text(markdown_path, markdown)
    atomic_write_text(scorecard, markdown)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cookie-dir", type=Path, default=DEFAULT_COOKIE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--timeout-sec", type=int, default=5)
    parser.add_argument("--allow-auth-probe", action="store_true")
    parser.add_argument("--auth-source", choices=["auto", "env", "docker-data"], default="auto")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_diagnostic(
        endpoint=args.endpoint,
        registry=args.registry,
        cookie_dir=args.cookie_dir,
        out_dir=args.out_dir,
        scorecard=args.scorecard,
        timeout_sec=args.timeout_sec,
        allow_auth_probe=args.allow_auth_probe,
        auth_source=args.auth_source,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "state": report["state"],
                "finding_count": report["finding_count"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
