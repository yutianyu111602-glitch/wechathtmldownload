"""Regression tests for the Sanji missing-HTML fail-closed contract."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

import export_sanji_appdata_manifest as exporter
import run_atlas_v2_sanji_import as orchestrator


def _write_missing_contract(
    manifest_dir: Path,
    *,
    article_count: int,
    unresolved: int,
) -> dict:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "token": f"sanji_test_{index}",
            "post_date": "2026-07-01",
            "disposition": "unresolved_retry_required",
            "reason": "html_not_found",
            "fetch_status_class": "missing",
            "fetch_retry_count": 0,
        }
        for index in range(unresolved)
    ]
    ledger_path = manifest_dir / "missing_html_dispositions.jsonl"
    ledger_text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    ledger_path.write_text(ledger_text, encoding="utf-8")
    digest = {
        "schema": "sanji.missing_html_digest.v1",
        "total_missing_html": unresolved,
        "unresolved_missing_html": unresolved,
        "disposed_nonblocking_missing_html": 0,
        "disposition_counts": ({"unresolved_retry_required": unresolved} if unresolved else {}),
        "ledger_rel_path": ledger_path.name,
        "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
    }
    digest_path = manifest_dir / "missing_html_digest.json"
    digest_path.write_text(json.dumps(digest), encoding="utf-8")
    report = {
        "article_count": article_count,
        "missing_html": unresolved,
        "actionable_missing_html": unresolved,
        "unresolved_missing_html": unresolved,
        "ignored_old_missing_html": 0,
        "missing_html_ledger_rel_path": ledger_path.name,
        "missing_html_ledger_sha256": digest["ledger_sha256"],
        "missing_html_digest_rel_path": digest_path.name,
    }
    (manifest_dir / "export_report.json").write_text(json.dumps(report), encoding="utf-8")
    return report


def _run_worker_with_export_report(
    monkeypatch,
    tmp_path: Path,
    *,
    article_count: int,
    unresolved: int,
) -> tuple[int, dict, list[str]]:
    historical_geo = tmp_path / "historical_venue_geo.json"
    historical_geo.write_text("{}", encoding="utf-8")
    sanji_root = tmp_path / "sanji"
    articles_root = tmp_path / "articles"
    sanji_root.mkdir()
    articles_root.mkdir()
    (sanji_root / "sanji.db").write_bytes(b"sqlite-placeholder")
    base_db = tmp_path / "base.sqlite"
    base_db.write_bytes(b"sqlite-placeholder")
    run_root = tmp_path / "runs"
    run_id = "contract"
    stage_names: list[str] = []

    def fake_run_step(name, cmd, env, log_dir):
        stage_names.append(name)
        if name == "export_delta":
            _write_missing_contract(
                run_root / run_id / "manifest",
                article_count=article_count,
                unresolved=unresolved,
            )
            return {"name": name, "cmd": cmd, "returncode": 0, "log": str(log_dir / "export.log")}
        return {"name": name, "cmd": [], "returncode": 97, "log": "synthetic-unexpected-stage.log"}

    monkeypatch.setattr(orchestrator, "run_step", fake_run_step)
    monkeypatch.setattr(
        orchestrator.sys,
        "argv",
        [
            str(orchestrator.__file__),
            "--sanji-root",
            str(sanji_root),
            "--articles-root",
            str(articles_root),
            "--base-serving-db",
            str(base_db),
            "--run-root",
            str(run_root),
            "--run-id",
            run_id,
            "--historical-venue-geo",
            str(historical_geo),
        ],
    )
    exit_code = orchestrator.main()
    summary = json.loads((run_root / run_id / "run_summary.json").read_text(encoding="utf-8"))
    return exit_code, summary, stage_names


def test_missing_only_is_blocked_before_paid_stages(monkeypatch, tmp_path) -> None:
    exit_code, summary, stage_names = _run_worker_with_export_report(
        monkeypatch,
        tmp_path,
        article_count=0,
        unresolved=2,
    )

    assert exit_code == 1
    assert summary["status"] == "blocked_unseen_missing_html"
    assert summary["missing_html_gate"]["unresolved_missing_html"] == 2
    assert stage_names == ["export_delta"]


def test_mixed_delta_is_blocked_before_paid_stages(monkeypatch, tmp_path) -> None:
    exit_code, summary, stage_names = _run_worker_with_export_report(
        monkeypatch,
        tmp_path,
        article_count=3,
        unresolved=1,
    )

    assert exit_code == 1
    assert summary["status"] == "blocked_unseen_missing_html"
    assert stage_names == ["export_delta"]


def test_true_noop_requires_zero_articles_and_zero_unresolved(monkeypatch, tmp_path) -> None:
    exit_code, summary, stage_names = _run_worker_with_export_report(
        monkeypatch,
        tmp_path,
        article_count=0,
        unresolved=0,
    )

    assert exit_code == 0
    assert summary["status"] == "noop_no_new_articles"
    assert summary["missing_html_gate"]["gate_pass"] is True
    assert stage_names == ["export_delta"]


def test_exporter_writes_sanitized_disposition_ledger_and_digest(tmp_path) -> None:
    sanji_root, db_path, articles_root = exporter.create_self_check_fixture(tmp_path)
    out = tmp_path / "out"

    report = exporter.export_manifest(
        sanji_root,
        db_path,
        articles_root,
        out,
        0,
        {"json"},
        "manifest-only",
        "path-ref",
    )

    assert report["unresolved_missing_html"] == 1
    ledger_path = out / report["missing_html_ledger_rel_path"]
    digest_path = out / report["missing_html_digest_rel_path"]
    ledger_rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert ledger_rows[0]["disposition"] == "unresolved_retry_required"
    assert set(ledger_rows[0]) <= {
        "token",
        "post_date",
        "disposition",
        "reason",
        "fetch_status_class",
        "fetch_retry_count",
    }
    forbidden = {"title", "digest", "link", "content_error", "content_path", "html_path", "fakeid", "aid"}
    assert forbidden.isdisjoint(ledger_rows[0])
    assert "Missing HTML" not in ledger_path.read_text(encoding="utf-8")
    assert "not fetched" not in ledger_path.read_text(encoding="utf-8")
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    assert digest["unresolved_missing_html"] == 1
    assert digest["ledger_sha256"] == hashlib.sha256(ledger_path.read_bytes()).hexdigest()


def test_export_limit_does_not_hide_later_unresolved_html(tmp_path) -> None:
    sanji_root, db_path, articles_root = exporter.create_self_check_fixture(tmp_path)
    out = tmp_path / "limited"

    report = exporter.export_manifest(
        sanji_root,
        db_path,
        articles_root,
        out,
        1,
        {"json"},
        "manifest-only",
        "path-ref",
    )

    assert report["article_count"] == 1
    assert report["unresolved_missing_html"] == 1


def test_historical_missing_html_has_explicit_nonblocking_disposition(tmp_path) -> None:
    sanji_root, db_path, articles_root = exporter.create_self_check_fixture(tmp_path)
    out = tmp_path / "historical"

    report = exporter.export_manifest(
        sanji_root,
        db_path,
        articles_root,
        out,
        0,
        {"json"},
        "manifest-only",
        "path-ref",
        ignore_missing_before_date="2025-01-01",
    )

    rows = [
        json.loads(line)
        for line in (out / report["missing_html_ledger_rel_path"]).read_text(encoding="utf-8").splitlines()
    ]
    assert report["unresolved_missing_html"] == 0
    assert report["ignored_old_missing_html"] == 1
    assert rows[0]["disposition"] == "ignored_historical_before_cutoff"


def test_formal_refresh_defaults_to_744_hours_and_rechecks_after_fetch() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    export_wrapper = (repo_root / "tools/stage7_rewrite/run_sanji_desktop_recent_export.ps1").read_text(
        encoding="utf-8"
    )
    outer_wrapper = (repo_root / "tools/stage7_rewrite/run_huaidj_sanji_daily_twice.ps1").read_text(
        encoding="utf-8"
    )
    refs_builder = (repo_root / "tools/stage7_rewrite/scripts/build_sanji_recent_fetch_refs.py").read_text(
        encoding="utf-8"
    )

    assert "[int]$SanjiRefreshCutoffHours = 744" in export_wrapper
    assert "sanji_recent_fetch_refs_postfetch_" in export_wrapper
    assert "postfetch" in export_wrapper.lower()
    assert "-SanjiRefreshCutoffHours" in outer_wrapper
    assert "[int]$SanjiRefreshCutoffHours = 744" in outer_wrapper
    assert "-SanjiRefreshCutoffHours $SanjiRefreshCutoffHours" in outer_wrapper
    assert "unresolved_missing_html" in outer_wrapper
    assert "SanjiRefreshCutoffHours" in outer_wrapper
    assert 'parser.add_argument("--cutoff-hours", type=float, default=744)' in refs_builder
    assert '"unresolved_missing_html": summary["pending_ref_count"]' in refs_builder


def test_postfetch_ledger_digest_is_hash_bound_and_sanitized(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "tools/stage7_rewrite/scripts/build_sanji_recent_fetch_refs.py"
    spec = importlib.util.spec_from_file_location("build_sanji_recent_fetch_refs_contract", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sanji_root = tmp_path / "sanji"
    sanji_root.mkdir()
    db_path = sanji_root / "sanji.db"
    con = sqlite3.connect(db_path)
    con.execute(
        """CREATE TABLE wechat_article (
        account_fakeid TEXT, aid TEXT, publish_time INTEGER, create_time INTEGER,
        is_deleted INTEGER, fetch_status TEXT, content_fetched INTEGER, content_path TEXT
        )"""
    )
    con.execute(
        "INSERT INTO wechat_article VALUES (?, ?, ?, ?, 0, ?, 0, '')",
        ("account-private", "article-private", int(time.time()), 0, "missing"),
    )
    con.commit()
    con.close()
    ledger = tmp_path / "ledger.json"
    digest = tmp_path / "digest.json"

    assert module.main(
        [
            "--sanji-root",
            str(sanji_root),
            "--cutoff-hours",
            "744",
            "--limit",
            "0",
            "--out",
            str(ledger),
            "--summary-out",
            str(digest),
        ]
    ) == 0

    rows = json.loads(ledger.read_text(encoding="utf-8"))
    report = json.loads(digest.read_text(encoding="utf-8"))
    assert len(rows) == report["unresolved_missing_html"] == report["ledger_row_count"] == 1
    assert set(rows[0]) == {"fakeid", "aid"}
    assert report["ledger_sha256"] == hashlib.sha256(ledger.read_bytes()).hexdigest()


def _run_outer_skip_gate(tmp_path: Path, *, unresolved: int) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[2]
    wrapper = repo_root / "tools/stage7_rewrite/run_huaidj_sanji_daily_twice.ps1"
    export_root = tmp_path / "export"
    sanji_root = tmp_path / "sanji"
    report_root = tmp_path / "reports"
    for path in (export_root, sanji_root, report_root, tmp_path / "hot", tmp_path / "cold"):
        path.mkdir(parents=True, exist_ok=True)
    snapshot = sanji_root / "snapshot.sqlite"
    snapshot.write_bytes(b"snapshot")
    manifest = export_root / "manifest.jsonl"
    manifest.write_text("{}\n", encoding="utf-8")
    ledger = export_root / "postfetch-ledger.json"
    ledger_rows = [
        {"fakeid": f"account-{index}", "aid": f"article-{index}"}
        for index in range(unresolved)
    ]
    ledger.write_text(json.dumps(ledger_rows), encoding="utf-8")
    now_epoch = int(time.time())
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now_epoch))
    summary = {
        "ok": True,
        "generated_at": generated_at,
        "exported_rows": 1,
        "manifest_path": str(manifest),
        "sanji_db_snapshot_export": True,
        "snapshot_db_path": str(snapshot),
        "rss_contract": {
            "direct_rss_feed_fetch": False,
            "sanji_desktop_refresh_invoked": True,
            "sanji_db_snapshot_export": True,
            "snapshot_db_path": str(snapshot),
        },
        "sanji_refresh": {
            "enabled": True,
            "fetch_refs_path": str(ledger),
            "fetch_refs_summary": {
                "generated_at": generated_at,
                "cutoff_ts": now_epoch - 744 * 3600,
                "unresolved_missing_html": unresolved,
                "pending_ref_count": unresolved,
                "ledger_row_count": unresolved,
                "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
            },
        },
    }
    (export_root / "latest_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (export_root / "LATEST.txt").write_text(str(export_root), encoding="utf-8")
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    assert pwsh
    env = os.environ.copy()
    env["HUAIDJ_PYTHON"] = sys.executable
    return subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper),
            "-DryRun",
            "-SkipSanjiExport",
            "-SkipNotify",
            "-SanjiRefreshCutoffHours",
            "744",
            "-SanjiSummaryMaxAgeHours",
            "1",
            "-SanjiExportOutRoot",
            str(export_root),
            "-SanjiRoot",
            str(sanji_root),
            "-SanjiHotArticlesRoot",
            str(tmp_path / "hot"),
            "-SanjiColdArchiveRoot",
            str(tmp_path / "cold"),
            "-ReportRoot",
            str(report_root),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_skip_sanji_export_accepts_fresh_zero_unresolved_hash_bound_ledger(tmp_path) -> None:
    result = _run_outer_skip_gate(tmp_path, unresolved=0)
    assert result.returncode == 0, result.stderr[-1000:]


def test_skip_sanji_export_rejects_existing_unresolved_ledger(tmp_path) -> None:
    result = _run_outer_skip_gate(tmp_path, unresolved=1)
    assert result.returncode == 1
    assert "unresolved_missing_html=1" in (result.stdout + result.stderr)
