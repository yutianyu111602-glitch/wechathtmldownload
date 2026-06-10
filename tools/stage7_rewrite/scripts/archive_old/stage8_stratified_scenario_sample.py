"""Build stratified Stage8 vector scenario samples.

This script only reads Stage8-style extract roots and writes bounded scenario
sample roots. It does not embed, write Qdrant, write Neo4j, or touch PC
production databases.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import stage8_vector_production_gate as gate
import stage8_vector_semantic_eval as semantic_eval
from stage7.atomic_io import safe_read_json


SCENARIOS = [
    "ocr_heavy",
    "account_heavy",
    "event_heavy",
    "article_heavy",
    "source_strict_noisy",
    "clean_broad",
    "tier_d_quarantine",
]


@dataclass(frozen=True)
class Candidate:
    path: Path
    root: Path
    article: dict[str, Any]
    article_id: str
    account: str
    title: str
    scenarios: tuple[str, ...]


def compact_text(value: Any, limit: int = 8000) -> str:
    return " ".join(str(value or "").split())[:limit]


def article_text(article: dict[str, Any]) -> str:
    values = [
        article.get("title"),
        article.get("summary"),
        article.get("main_content"),
        article.get("body_text"),
    ]
    return compact_text(" ".join(str(value or "") for value in values))


def source_lane(article: dict[str, Any]) -> str:
    return str(
        article.get("source_lane")
        or article.get("lane")
        or article.get("manifest_mode")
        or article.get("quality_lane")
        or ""
    ).lower()


def article_id_for(path: Path, article: dict[str, Any]) -> str:
    return str(article.get("article_uid") or article.get("article_id") or path.parent.name)


def account_for(path: Path, article: dict[str, Any]) -> str:
    return str(
        article.get("source_account")
        or article.get("account_clean")
        or article.get("account")
        or path.parent.parent.name
        or "unknown_account"
    )


def has_events(article: dict[str, Any]) -> bool:
    if article.get("events"):
        return True
    return any(str(entity.get("type") or entity.get("kind") or "").lower() == "event" for entity in article.get("entities") or [])


def has_account_signal(article: dict[str, Any]) -> bool:
    if article.get("source_account") or article.get("account_clean") or article.get("account"):
        return True
    return bool((article.get("metadata") or {}).get("account"))


def is_source_noisy(article: dict[str, Any]) -> bool:
    lane = source_lane(article)
    if any(marker in lane for marker in ("review", "full_empty", "salvage", "blocked", "partial")):
        return True
    quality = article.get("source_quality")
    try:
        return quality is not None and float(quality) < 0.8
    except (TypeError, ValueError):
        return False


def classify(path: Path, root: Path, article: dict[str, Any]) -> Candidate:
    scenarios: list[str] = []
    is_tier_d = gate.is_platform_privacy_article(article) or not article_text(article)
    if is_tier_d:
        scenarios.append("tier_d_quarantine")
    else:
        if list(semantic_eval.iter_ocr_evidence(article)):
            scenarios.append("ocr_heavy")
        if has_account_signal(article):
            scenarios.append("account_heavy")
        if has_events(article):
            scenarios.append("event_heavy")
        if len(article_text(article)) >= 600:
            scenarios.append("article_heavy")
        if is_source_noisy(article):
            scenarios.append("source_strict_noisy")
        if gate.has_structured_cards(article) and not is_source_noisy(article):
            scenarios.append("clean_broad")
    return Candidate(
        path=path,
        root=root,
        article=article,
        article_id=article_id_for(path, article),
        account=account_for(path, article),
        title=str(article.get("title") or ""),
        scenarios=tuple(scenarios),
    )


def extract_base(root: Path) -> Path:
    if root.name == "llm_extract":
        return root
    return root / "llm_extract"


def iter_candidates(roots: list[Path], max_scan_files: int) -> tuple[list[Candidate], int]:
    candidates: list[Candidate] = []
    scanned = 0
    for root in roots:
        base = extract_base(root)
        for path in sorted(base.rglob("extract.article.v1.json")):
            if max_scan_files > 0 and scanned >= max_scan_files:
                return candidates, scanned
            scanned += 1
            article = safe_read_json(path, {})
            if not article:
                continue
            candidates.append(classify(path, root, article))
    return candidates, scanned


def safe_part(value: str) -> str:
    return gate.write_tests.safe_collection_model(value or "unknown")


def choose_by_scenario(candidates: list[Candidate], per_scenario: int, per_account: int) -> dict[str, list[Candidate]]:
    selected: dict[str, list[Candidate]] = {name: [] for name in SCENARIOS}
    by_account: dict[str, Counter[str]] = {name: Counter() for name in SCENARIOS}
    for scenario in SCENARIOS:
        for item in candidates:
            if scenario not in item.scenarios:
                continue
            if per_scenario > 0 and len(selected[scenario]) >= per_scenario:
                break
            if per_account > 0 and by_account[scenario][item.account] >= per_account:
                continue
            selected[scenario].append(item)
            by_account[scenario][item.account] += 1
    return selected


def materialize(out_dir: Path, selected: dict[str, list[Candidate]]) -> dict[str, str]:
    roots: dict[str, str] = {}
    for scenario, items in selected.items():
        scenario_root = out_dir / "scenarios" / scenario
        roots[scenario] = str(scenario_root)
        for item in items:
            dst = (
                scenario_root
                / "llm_extract"
                / safe_part(item.account)
                / safe_part(item.article_id)
                / "extract.article.v1.json"
            )
            dst.parent.mkdir(parents=True, exist_ok=True)
            article = dict(item.article)
            article.setdefault("schema_version", "article_extract.v1")
            dst.write_text(json.dumps(article, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return roots


def write_path_lists(out_dir: Path, selected: dict[str, list[Candidate]]) -> None:
    lists_dir = out_dir / "lists"
    lists_dir.mkdir(parents=True, exist_ok=True)
    for scenario, items in selected.items():
        lines = [str(item.path) for item in items]
        (lists_dir / f"{scenario}_paths.txt").write_text("\n".join(lines), encoding="utf-8")


def write_markdown(out_dir: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage8 Stratified Scenario Sample",
        "",
        f"- scanned_files: `{report['scanned_files']}`",
        f"- candidate_count: `{report['candidate_count']}`",
        f"- per_scenario: `{report['per_scenario']}`",
        f"- per_account: `{report['per_account']}`",
        f"- writes: `sample roots only; no embeddings or database writes`",
        "",
        "| Scenario | Selected | Top accounts | Root |",
        "|---|---:|---|---|",
    ]
    for scenario in SCENARIOS:
        item = report["scenarios"][scenario]
        top_accounts = ", ".join(f"{name}:{count}" for name, count in item["top_accounts"][:5])
        lines.append(f"| `{scenario}` | {item['selected']} | {top_accounts} | `{item['root']}` |")
    lines.extend([
        "",
        "## Next",
        "",
        "- Run semantic matrices per scenario root only after choosing the relevant scenario policy.",
        "- Keep Tier D as quarantine evidence; do not embed it into broad-map collections.",
        "- For full-target gate dry-run, use a stable Stage7 output root, not an actively mutating shard.",
        "",
    ])
    (out_dir / "STRATIFIED_SCENARIO_SAMPLE.md").write_text("\n".join(lines), encoding="utf-8")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    roots = [Path(value) for value in args.output_root]
    candidates, scanned = iter_candidates(roots, args.max_scan_files)
    selected = choose_by_scenario(candidates, args.per_scenario, args.per_account)
    materialized_roots = materialize(out_dir, selected) if not args.no_materialize else {name: "" for name in SCENARIOS}
    write_path_lists(out_dir, selected)

    scenario_report: dict[str, Any] = {}
    for scenario, items in selected.items():
        account_counts = Counter(item.account for item in items)
        scenario_report[scenario] = {
            "selected": len(items),
            "top_accounts": account_counts.most_common(10),
            "root": materialized_roots.get(scenario, ""),
            "sample_paths_file": str(out_dir / "lists" / f"{scenario}_paths.txt"),
        }
    report = {
        "schema_version": "stage8_stratified_scenario_sample.v1",
        "source_roots": [str(root) for root in roots],
        "out_dir": str(out_dir),
        "scanned_files": scanned,
        "candidate_count": len(candidates),
        "per_scenario": args.per_scenario,
        "per_account": args.per_account,
        "scenarios": scenario_report,
    }
    (out_dir / "stratified_scenario_sample.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_markdown(out_dir, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", action="append", required=True, help="Stage8-style root containing llm_extract")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--per-scenario", type=int, default=120)
    parser.add_argument("--per-account", type=int, default=20)
    parser.add_argument("--max-scan-files", type=int, default=5000)
    parser.add_argument("--no-materialize", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(args)
    print(json.dumps({"ok": True, "out_dir": report["out_dir"], "scenarios": report["scenarios"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
