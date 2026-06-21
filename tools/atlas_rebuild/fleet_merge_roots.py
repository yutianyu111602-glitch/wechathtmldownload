"""Prepare and optionally merge multiple accepted fleet work roots.

This is the final full-manifest closeout helper for staged runs such as
G1..G7.  By default it reads each accepted rung's original ``shard_*`` outputs,
including ``QUARANTINE`` shards, and turns those shard outputs into a synthetic
fleet root:

  out_root/shard_0/extractions.sqlite
  out_root/shard_0/clean.sqlite
  out_root/shard_0/shard_status.json

Then it can invoke ``fleet_merge.py`` on the synthetic root so the combined
candidate uses the same Stage3/Stage4/bio/vector path as ordinary fleets.

``--source-mode merged`` exists only for compatibility/debugging.  It should not
be the default for the 14w final union because older rung merged outputs may
predate the QUARANTINE merge fix.

Candidate-only: this never writes production DBs and never mutates source roots.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
MERGEABLE_STATUSES = {"PASS", "PASS_EMPTY", "QUARANTINE", "done", "pass", "quarantine"}


def _ro_connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"value": data}
    except Exception as exc:
        return {"read_error": f"{type(exc).__name__}: {exc}"[:300]}


def _table_count(path: Path, table: str) -> int | None:
    if not path.is_file():
        return None
    con = _ro_connect(path)
    try:
        names = {
            str(row[0])
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if table not in names:
            return None
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        con.close()


def _status_counts(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    con = _ro_connect(path)
    try:
        return {
            str(status or ""): int(count)
            for status, count in con.execute(
                "SELECT status, COUNT(*) FROM extractions GROUP BY status"
            ).fetchall()
        }
    finally:
        con.close()


def _tokens(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    con = _ro_connect(path)
    try:
        return {str(row[0]) for row in con.execute("SELECT token FROM extractions").fetchall() if row[0]}
    finally:
        con.close()


def _root_info(root: Path) -> dict[str, Any]:
    root = root.resolve()
    merged = root / "merged"
    extractions = merged / "extractions.sqlite"
    clean = merged / "clean.sqlite"
    final_report = merged / "final_report.json"
    final_data = _read_json(final_report) if final_report.exists() else {}
    return {
        "root": str(root),
        "name": root.name,
        "exists": root.is_dir(),
        "merged_dir": str(merged),
        "merged_dir_exists": merged.is_dir(),
        "extractions_db": str(extractions),
        "extractions_exists": extractions.is_file(),
        "clean_db": str(clean),
        "clean_exists": clean.is_file(),
        "final_report": str(final_report),
        "final_report_exists": final_report.is_file(),
        "final_report_integrity": final_data.get("integrity"),
        "candidate_db_exists": bool(final_data.get("candidate_db_exists")),
        "extraction_rows": _table_count(extractions, "extractions"),
        "clean_rows": _table_count(clean, "clean"),
        "status_counts": _status_counts(extractions),
    }


def _status_json(shard_dir: Path) -> dict[str, Any]:
    status_path = shard_dir / "shard_status.json"
    return _read_json(status_path) if status_path.exists() else {}


def _shard_units(root: Path) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for shard_dir in sorted(root.glob("shard_*"), key=lambda p: p.name):
        if not shard_dir.is_dir():
            continue
        status_data = _status_json(shard_dir)
        status = str(status_data.get("status") or "unknown")
        extractions = shard_dir / "extractions.sqlite"
        clean = shard_dir / "clean.sqlite"
        units.append({
            "source_mode": "shards",
            "root": str(root.resolve()),
            "root_name": root.name,
            "unit_name": shard_dir.name,
            "unit_dir": str(shard_dir.resolve()),
            "status": status,
            "mergeable": status in MERGEABLE_STATUSES and extractions.is_file() and clean.is_file(),
            "extractions_db": str(extractions),
            "extractions_exists": extractions.is_file(),
            "clean_db": str(clean),
            "clean_exists": clean.is_file(),
            "extraction_rows": _table_count(extractions, "extractions"),
            "clean_rows": _table_count(clean, "clean"),
            "status_counts": _status_counts(extractions),
        })
    return units


def _merged_units(root: Path) -> list[dict[str, Any]]:
    info = _root_info(root)
    return [{
        "source_mode": "merged",
        "root": info["root"],
        "root_name": info["name"],
        "unit_name": "merged",
        "unit_dir": info["merged_dir"],
        "status": "PASS" if info["final_report_integrity"] == "ok" else "unknown",
        "mergeable": info["extractions_exists"] and info["clean_exists"] and info["final_report_integrity"] == "ok",
        "extractions_db": info["extractions_db"],
        "extractions_exists": info["extractions_exists"],
        "clean_db": info["clean_db"],
        "clean_exists": info["clean_exists"],
        "extraction_rows": info["extraction_rows"],
        "clean_rows": info["clean_rows"],
        "status_counts": info["status_counts"],
    }]


def collect_plan(roots: list[Path], include_tokens: bool = True, source_mode: str = "shards") -> dict[str, Any]:
    infos = [_root_info(root) for root in roots]
    issues: list[str] = []
    token_seen: set[str] = set()
    duplicate_tokens = 0
    token_rows = 0
    all_units: list[dict[str, Any]] = []

    for info in infos:
        label = info["name"]
        if not info["exists"]:
            issues.append(f"{label}:missing_root")
        if source_mode == "merged":
            if not info["extractions_exists"]:
                issues.append(f"{label}:missing_merged_extractions")
            if not info["clean_exists"]:
                issues.append(f"{label}:missing_merged_clean")
            if not info["final_report_exists"]:
                issues.append(f"{label}:missing_final_report")
            elif info.get("final_report_integrity") != "ok":
                issues.append(f"{label}:final_report_integrity={info.get('final_report_integrity')}")
            units = _merged_units(Path(info["root"]))
        elif source_mode == "shards":
            units = _shard_units(Path(info["root"]))
            if not units:
                issues.append(f"{label}:no_shard_units")
            non_mergeable = [u for u in units if not u["mergeable"]]
            if non_mergeable:
                sample = ",".join(f"{u['unit_name']}:{u['status']}" for u in non_mergeable[:12])
                issues.append(f"{label}:non_mergeable_units={len(non_mergeable)}:{sample}")
        else:
            raise ValueError(f"unknown source_mode: {source_mode}")
        all_units.extend(units)

    for unit in all_units:
        if include_tokens and unit["mergeable"] and unit["extractions_exists"]:
            unit_tokens = _tokens(Path(unit["extractions_db"]))
            token_rows += len(unit_tokens)
            duplicate_tokens += len(unit_tokens & token_seen)
            token_seen.update(unit_tokens)

    return {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_mode": source_mode,
        "root_count": len(infos),
        "roots": infos,
        "unit_count": len(all_units),
        "mergeable_unit_count": sum(1 for unit in all_units if unit["mergeable"]),
        "units": all_units,
        "ready": not issues,
        "issues": issues,
        "token_unique": len(token_seen) if include_tokens else None,
        "token_rows_unique_sum": token_rows if include_tokens else None,
        "duplicate_tokens_across_roots": duplicate_tokens if include_tokens else None,
        "boundary": "candidate_only_multi_root_plan_no_production_write",
    }


def _safe_prepare_out_root(out_root: Path, force: bool) -> None:
    out_root = out_root.resolve()
    if out_root.anchor == str(out_root):
        raise SystemExit(f"refusing filesystem root out-root: {out_root}")
    if out_root.exists() and any(out_root.iterdir()):
        if not force:
            raise SystemExit(f"out-root exists and is not empty; pass --force to replace synthetic inputs: {out_root}")
        marker = out_root / "fleet_merge_roots.synthetic.json"
        if not marker.exists():
            raise SystemExit(f"refusing --force without synthetic marker: {out_root}")
        for child in out_root.iterdir():
            if child.is_dir() and child.name.startswith("shard_"):
                shutil.rmtree(child)
        merged = out_root / "merged"
        if merged.exists():
            shutil.rmtree(merged)
        for name in ("fleet_merge_roots.synthetic.json", "fleet_merge_roots.plan.json", "fleet_merge_roots.run.json"):
            path = out_root / name
            if path.exists():
                path.unlink()
    out_root.mkdir(parents=True, exist_ok=True)


def _link_or_copy(src: Path, dst: Path, mode: str) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    method = None
    error = None
    if mode in {"auto", "hardlink"}:
        try:
            os.link(src, dst)
            method = "hardlink"
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
            if mode == "hardlink":
                raise
    if method is None:
        if mode not in {"auto", "copy"}:
            raise ValueError(f"unknown link mode: {mode}")
        shutil.copy2(src, dst)
        method = "copy"
    return {
        "src": str(src),
        "dst": str(dst),
        "method": method,
        "bytes": dst.stat().st_size if dst.exists() else 0,
        "hardlink_error": error,
    }


def prepare_synthetic_root(roots: list[Path], out_root: Path, force: bool, link_mode: str, source_mode: str) -> dict[str, Any]:
    plan = collect_plan(roots, source_mode=source_mode)
    if not plan["ready"]:
        return {
            "prepared": False,
            "plan": plan,
            "error": "input_roots_not_ready",
        }
    _safe_prepare_out_root(out_root, force)
    out_root = out_root.resolve()
    links: list[dict[str, Any]] = []
    mergeable_units = [unit for unit in plan["units"] if unit["mergeable"]]
    for idx, info in enumerate(mergeable_units):
        shard_dir = out_root / f"shard_{idx}"
        shard_dir.mkdir(parents=True, exist_ok=True)
        links.append(_link_or_copy(Path(info["extractions_db"]), shard_dir / "extractions.sqlite", link_mode))
        links.append(_link_or_copy(Path(info["clean_db"]), shard_dir / "clean.sqlite", link_mode))
        status = {
            "status": info["status"],
            "shard_id": idx,
            "synthetic_source_root": info["root"],
            "synthetic_source_name": info["root_name"],
            "synthetic_source_unit": info["unit_name"],
            "synthetic_source_mode": info["source_mode"],
            "extraction_rows": info["extraction_rows"],
            "clean_rows": info["clean_rows"],
            "boundary": "candidate_only_synthetic_shard_from_accepted_root",
        }
        (shard_dir / "shard_status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    prepared = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "prepared": True,
        "out_root": str(out_root),
        "root_count": len(plan["roots"]),
        "unit_count": len(mergeable_units),
        "source_mode": source_mode,
        "link_mode": link_mode,
        "links": links,
        "plan": plan,
        "boundary": "candidate_only_synthetic_fleet_no_source_mutation",
    }
    (out_root / "fleet_merge_roots.synthetic.json").write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_root / "fleet_merge_roots.plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return prepared


def run_fleet_merge(out_root: Path, vector: bool, stage_timeout_sec: int) -> dict[str, Any]:
    cmd = [sys.executable, str(HERE / "fleet_merge.py"), "--work-root", str(out_root)]
    if vector:
        cmd.append("--vector")
    cmd.extend(["--stage-timeout-sec", str(stage_timeout_sec)])
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True, timeout=stage_timeout_sec + 120)
    run = {
        "cmd": cmd,
        "exit_code": proc.returncode,
        "elapsed_sec": round(time.time() - started, 1),
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "final_report": str(out_root / "merged" / "final_report.json"),
        "candidate_db": str(out_root / "merged" / "atlas_serving_candidate.sqlite"),
    }
    (out_root / "fleet_merge_roots.run.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run


def _make_tiny_root(root: Path, token: str) -> None:
    merged = root / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(merged / "extractions.sqlite")
    con.execute(
        "CREATE TABLE extractions (token TEXT PRIMARY KEY, account_key TEXT, model_tier TEXT, "
        "valid INTEGER, event_count INTEGER, max_conf REAL, payload TEXT, error TEXT, ms INTEGER, status TEXT)"
    )
    con.execute(
        "INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
        (token, "acct", "mock", 1, 1, 0.9, "{}", "", 1, "extracted"),
    )
    con.commit()
    con.close()
    clean = sqlite3.connect(merged / "clean.sqlite")
    clean.execute(
        "CREATE TABLE clean (token TEXT PRIMARY KEY, account_key TEXT, title TEXT, clean_text TEXT, "
        "text_len INTEGER, poster_json TEXT, poster_candidates_json TEXT, poster_selection_report_json TEXT, "
        "poster_count INTEGER, dup_group TEXT, route TEXT, status TEXT, article_type TEXT, "
        "should_process_text INTEGER, should_process_images INTEGER, image_route_reason TEXT, "
        "classification_confidence REAL, classification_reasons TEXT)"
    )
    clean.execute(
        "INSERT INTO clean VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (token, "acct", "title", "body", 4, "[]", "[]", "{}", 0, "", "needs_vision",
         "clean", "event", 1, 1, "", 1.0, "[]"),
    )
    clean.commit()
    clean.close()
    (merged / "final_report.json").write_text(
        json.dumps({"integrity": "ok", "candidate_db_exists": True}, indent=2) + "\n",
        encoding="utf-8",
    )


def self_check() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fleet_merge_roots_selfcheck_"))
    try:
        r1 = tmp / "r1"
        r2 = tmp / "r2"
        out = tmp / "combined"
        _make_tiny_root(r1, "t1")
        _make_tiny_root(r2, "t2")
        plan = collect_plan([r1, r2], source_mode="merged")
        assert plan["ready"], plan
        assert plan["token_unique"] == 2, plan
        prepared = prepare_synthetic_root([r1, r2], out, force=False, link_mode="auto", source_mode="merged")
        assert prepared["prepared"], prepared
        assert (out / "shard_0" / "extractions.sqlite").exists()
        assert (out / "shard_1" / "clean.sqlite").exists()
        print("self-check OK")
        print(json.dumps({"plan": plan, "prepared": prepared["prepared"]}, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--roots", nargs="+", help="accepted fleet work roots to combine")
    ap.add_argument("--out-root", help="synthetic combined fleet work root")
    ap.add_argument("--execute", action="store_true", help="prepare synthetic root and run fleet_merge.py")
    ap.add_argument("--prepare-only", action="store_true", help="prepare synthetic root but do not run fleet_merge.py")
    ap.add_argument("--source-mode", choices=("shards", "merged"), default="shards",
                    help="input units: original shard_* outputs (default) or prior merged outputs")
    ap.add_argument("--vector", action="store_true", help="pass --vector through to fleet_merge.py")
    ap.add_argument("--force", action="store_true", help="replace a prior synthetic out-root created by this tool")
    ap.add_argument("--link-mode", choices=("auto", "hardlink", "copy"), default="auto")
    ap.add_argument("--stage-timeout-sec", type=int, default=int(os.environ.get("ATLAS_FLEET_STAGE_TIMEOUT_SEC", "3600")))
    args = ap.parse_args()

    if args.self_check:
        return self_check()
    if not args.roots:
        raise SystemExit("--roots is required unless --self-check")
    roots = [Path(p).resolve() for p in args.roots]
    if not args.out_root:
        plan = collect_plan(roots, source_mode=args.source_mode)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if plan["ready"] else 2

    out_root = Path(args.out_root).resolve()
    if args.execute or args.prepare_only:
        prepared = prepare_synthetic_root(
            roots,
            out_root,
            force=args.force,
            link_mode=args.link_mode,
            source_mode=args.source_mode,
        )
        print(json.dumps(prepared, ensure_ascii=False, indent=2))
        if not prepared.get("prepared"):
            return 2
        if args.execute:
            run = run_fleet_merge(out_root, args.vector, args.stage_timeout_sec)
            print(json.dumps(run, ensure_ascii=False, indent=2))
            return run["exit_code"]
        return 0

    plan = collect_plan(roots, source_mode=args.source_mode)
    plan["out_root"] = str(out_root)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if plan["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
