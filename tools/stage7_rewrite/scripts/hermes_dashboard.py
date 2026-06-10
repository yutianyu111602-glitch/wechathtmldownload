"""Build or serve a static local Hermes dashboard from report artifacts."""

from __future__ import annotations

import argparse
import html
import json
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hermes_monitor_common import now_iso, read_json_if_exists, reject_d_path, write_text


DEFAULT_OUT_DIR = Path("reports/hermes_dashboard_20260515")
SCHEMA_VERSION = "stage7_hermes_dashboard.v1"


def card(title: str, rows: list[tuple[str, Any]]) -> str:
    items = "\n".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
    return f"<section class='card'><h2>{html.escape(title)}</h2><table>{items}</table></section>"


def build_dashboard(root: Path, out_dir: Path) -> Path:
    reject_d_path(root, "root")
    reject_d_path(out_dir, "out_dir")
    heartbeat = read_json_if_exists(root / "reports/hermes_heartbeat_20260515/heartbeat_latest.json")
    metrics = read_json_if_exists(root / "reports/hermes_metrics_20260515/metrics_snapshot.json")
    alerts = read_json_if_exists(root / "reports/hermes_alerts_20260515/alerts.json")
    costs = read_json_if_exists(root / "reports/hermes_cost_20260515/cost_summary.json")

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage7 Hermes Dashboard</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f6f7f9; color: #1f2933; }}
    header {{ padding: 24px 32px; background: #17212b; color: white; }}
    main {{ padding: 24px 32px; display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
    .card {{ background: white; border: 1px solid #d9dee7; border-radius: 8px; padding: 16px; }}
    h1 {{ margin: 0; font-size: 24px; }}
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 8px 0; border-top: 1px solid #edf0f4; text-align: left; vertical-align: top; }}
    th {{ width: 44%; color: #52616f; font-weight: 600; }}
  </style>
</head>
<body>
  <header>
    <h1>Stage7 Hermes Dashboard</h1>
    <p>Generated {html.escape(now_iso())}. Local report-only view.</p>
  </header>
  <main>
    {card("Heartbeat", [
        ("last round", heartbeat.get("longrun_last_round", "")),
        ("publish gate", (heartbeat.get("publish_gate") or {}).get("decision")),
        ("p1 social ok", (heartbeat.get("p1_social") or {}).get("verify_ok")),
    ])}
    {card("Metrics", [
        ("publish blockers", (metrics.get("publish_gate") or {}).get("blocking_count")),
        ("missing publish time", (metrics.get("publish_gate") or {}).get("missing_publish_time_articles")),
        ("ocr missing", (metrics.get("ocr_recovery") or {}).get("missing_count")),
    ])}
    {card("Alerts", [
        ("decision", alerts.get("decision")),
        ("alert count", len(alerts.get("alerts") or [])),
    ])}
    {card("Cost", [
        ("deepseek observed", (costs.get("totals") or {}).get("deepseek")),
        ("dajiala observed", (costs.get("totals") or {}).get("dajiala")),
        ("balance blockers", len(costs.get("dajiala_balance_blockers") or [])),
    ])}
  </main>
</body>
</html>
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "hermes_dashboard.html"
    write_text(out_path, html_text)
    write_text(out_dir / "dashboard_manifest.json", json.dumps({"schema_version": SCHEMA_VERSION, "generated_at": now_iso(), "dashboard": str(out_path), "writes": "reports_only"}, indent=2))
    return out_path


def serve(out_dir: Path, port: int) -> None:  # pragma: no cover - manual mode
    handler = SimpleHTTPRequestHandler
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    webbrowser.open(f"http://127.0.0.1:{port}/{out_dir.as_posix()}/hermes_dashboard.html")
    server.serve_forever()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--mode", choices=["build", "serve"], default="build")
    parser.add_argument("--port", type=int, default=9494)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_path = build_dashboard(args.root, args.out_dir)
    print(json.dumps({"ok": True, "dashboard": str(out_path)}, ensure_ascii=False, indent=2))
    if args.mode == "serve":
        serve(args.out_dir, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
