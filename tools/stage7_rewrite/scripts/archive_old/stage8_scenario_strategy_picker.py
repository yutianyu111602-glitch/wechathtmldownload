"""Pick high-scoring Stage8 vector strategies by retrieval scenario.

This script reads one or more Stage8 semantic-eval result files and converts
raw matrix rows into a tiered strategy recommendation. It does not embed, write
Qdrant, write Neo4j, or touch PC production DBs.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCENARIOS = [
    "broad_map",
    "event_lookup",
    "article_lookup",
    "venue_lookup",
    "account_lookup",
    "ocr_lookup",
    "source_strict",
    "object_safe",
    "cost_sensitive",
]


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    description: str
    min_object_precision: float = 0.0
    max_bad_source_leaks: int | None = None
    prefer_lower_cap: bool = False
    intent: str | None = None


SCENARIO_SPECS = {
    "broad_map": ScenarioSpec(
        "broad_map",
        "Default map search across accounts, venues, events, articles, and OCR.",
        min_object_precision=0.98,
    ),
    "event_lookup": ScenarioSpec("event_lookup", "Event/date/lineup style searches.", intent="event_lookup"),
    "article_lookup": ScenarioSpec("article_lookup", "Article-title and article-content searches.", intent="article_lookup"),
    "venue_lookup": ScenarioSpec("venue_lookup", "Venue/city/place searches.", intent="venue_lookup"),
    "account_lookup": ScenarioSpec("account_lookup", "Organizer/account profile searches.", intent="account_lookup"),
    "ocr_lookup": ScenarioSpec("ocr_lookup", "Poster/OCR evidence searches.", intent="ocr_evidence_lookup"),
    "source_strict": ScenarioSpec(
        "source_strict",
        "Use when bad-source leakage or review-lane contamination matters more than tiny recall deltas.",
        min_object_precision=0.95,
        max_bad_source_leaks=200,
    ),
    "object_safe": ScenarioSpec(
        "object_safe",
        "Use when the returned object kind must match the query intent.",
        min_object_precision=0.995,
    ),
    "cost_sensitive": ScenarioSpec(
        "cost_sensitive",
        "Use when candidate count and vector volume must be reduced while keeping quality acceptable.",
        min_object_precision=0.98,
        prefer_lower_cap=True,
    ),
}


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def metric(row: dict[str, Any], name: str) -> float:
    if name == "rank1":
        return as_float(row.get("rank1", row.get("rank1_rate")))
    return as_float(row.get(name))


def intent_metrics(row: dict[str, Any], intent: str) -> dict[str, Any]:
    return dict((row.get("by_intent") or {}).get(intent) or {})


def intent_metric(row: dict[str, Any], intent: str, name: str) -> float:
    data = intent_metrics(row, intent)
    if name == "rank1":
        return as_float(data.get("rank1", data.get("rank1_rate")))
    return as_float(data.get(name))


def load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    if isinstance(payload.get("results"), list):
        for row in payload["results"]:
            item = dict(row)
            item["_source_file"] = str(path)
            rows.append(item)
    elif isinstance(payload.get("variants"), dict):
        for key, row in payload["variants"].items():
            item = dict(row)
            if "/" in key:
                variant, profile = key.split("/", 1)
                item.setdefault("variant", variant)
                item.setdefault("score_profile", profile)
            else:
                item.setdefault("variant", key)
            item.setdefault("candidate_cap", payload.get("candidate_cap"))
            item["_source_file"] = str(path)
            rows.append(item)
    else:
        raise ValueError(f"unsupported result schema: {path}")
    return rows


def ocr_top1_kind(row: dict[str, Any]) -> str:
    for query in row.get("ocr_query_top3") or []:
        top3 = query.get("top3") or []
        if top3:
            return str(top3[0].get("kind") or "")
    return ""


def base_quality(row: dict[str, Any]) -> float:
    return (
        0.28 * metric(row, "recall_at_5")
        + 0.22 * metric(row, "rank1")
        + 0.22 * metric(row, "mrr_at_10")
        + 0.14 * metric(row, "city_precision_at_10")
        + 0.14 * metric(row, "object_kind_precision_at_10")
    )


def source_quality_score(row: dict[str, Any]) -> float:
    leaks = as_int(row.get("bad_source_leaks_at_10"))
    low_rate = metric(row, "low_source_top3_rate")
    review_rate = metric(row, "review_lane_top3_rate")
    hard = metric(row, "hard_negative_pass_rate")
    gate = metric(row, "source_gate_pass_rate")
    source = metric(row, "source_quality_at_10")
    leak_penalty = min(0.35, leaks / max(as_int(row.get("query_count"), 1) * 10, 1))
    return (
        0.30 * source
        + 0.25 * hard
        + 0.20 * gate
        + 0.15 * (1.0 - low_rate)
        + 0.10 * (1.0 - review_rate)
        - leak_penalty
    )


def cost_score(row: dict[str, Any]) -> float:
    cap = max(as_int(row.get("candidate_cap"), 0), 1)
    jobs = max(as_int(row.get("job_count"), 0), 1)
    cap_term = 1.0 / cap
    job_term = 1.0 / (1.0 + jobs / 1000.0)
    return 0.60 * base_quality(row) + 0.25 * cap_term + 0.15 * job_term


def scenario_score(row: dict[str, Any], scenario: str) -> float:
    spec = SCENARIO_SPECS[scenario]
    if metric(row, "object_kind_precision_at_10") < spec.min_object_precision:
        return -1.0
    if spec.max_bad_source_leaks is not None and as_int(row.get("bad_source_leaks_at_10")) > spec.max_bad_source_leaks:
        return -1.0
    if scenario == "source_strict":
        if as_int(row.get("hard_negative_query_count")) <= 0 and as_int(row.get("source_gate_query_count")) <= 0:
            return -1.0
        return source_quality_score(row) + 0.20 * base_quality(row)
    if scenario == "object_safe":
        return (
            0.55 * metric(row, "object_kind_precision_at_10")
            + 0.20 * metric(row, "recall_at_5")
            + 0.15 * metric(row, "rank1")
            + 0.10 * metric(row, "city_precision_at_10")
        )
    if scenario == "cost_sensitive":
        return cost_score(row)
    if spec.intent:
        recall = intent_metric(row, spec.intent, "recall_at_5")
        rank1 = intent_metric(row, spec.intent, "rank1")
        mrr = intent_metric(row, spec.intent, "mrr_at_10")
        kind = intent_metric(row, spec.intent, "object_kind_precision_at_10")
        city = intent_metric(row, spec.intent, "city_precision_at_10")
        if not any([recall, rank1, mrr, kind, city]):
            return -1.0
        score = 0.32 * recall + 0.24 * rank1 + 0.24 * mrr + 0.12 * kind + 0.08 * city
        if scenario == "ocr_lookup" and ocr_top1_kind(row) == "ocr_evidence":
            score += 0.05
        return score
    return base_quality(row)


def row_label(row: dict[str, Any]) -> str:
    return (
        f"{row.get('variant') or row.get('card_template')}"
        f" + cap{row.get('candidate_cap')}"
        f" + {row.get('score_profile')}"
    )


def summarize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy": row_label(row),
        "variant": row.get("variant") or row.get("card_template"),
        "score_profile": row.get("score_profile"),
        "candidate_cap": row.get("candidate_cap"),
        "job_count": row.get("job_count"),
        "query_count": row.get("query_count"),
        "recall_at_5": row.get("recall_at_5"),
        "rank1": row.get("rank1", row.get("rank1_rate")),
        "mrr_at_10": row.get("mrr_at_10"),
        "city_precision_at_10": row.get("city_precision_at_10"),
        "object_kind_precision_at_10": row.get("object_kind_precision_at_10"),
        "source_quality_at_10": row.get("source_quality_at_10"),
        "bad_source_leaks_at_10": row.get("bad_source_leaks_at_10"),
        "hard_negative_pass_rate": row.get("hard_negative_pass_rate"),
        "source_gate_pass_rate": row.get("source_gate_pass_rate"),
        "avg_candidates_scored": row.get("avg_candidates_scored"),
        "ocr_top1_kind": ocr_top1_kind(row),
        "source_file": row.get("_source_file"),
    }


def pick_scenarios(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    for scenario in SCENARIOS:
        scored = [
            (scenario_score(row, scenario), row)
            for row in rows
        ]
        scored = [(score, row) for score, row in scored if score >= 0]
        scored.sort(
            key=lambda item: (
                item[0],
                metric(item[1], "recall_at_5"),
                metric(item[1], "rank1"),
                metric(item[1], "object_kind_precision_at_10"),
                -as_int(item[1].get("candidate_cap")),
                -as_int(item[1].get("job_count")),
            ),
            reverse=True,
        )
        spec = SCENARIO_SPECS[scenario]
        if not scored:
            scenarios[scenario] = {
                "description": spec.description,
                "status": "NO_QUALIFIED_STRATEGY",
                "winner": None,
                "top3": [],
            }
            continue
        winner_score, winner = scored[0]
        scenarios[scenario] = {
            "description": spec.description,
            "status": "OK",
            "score": round(winner_score, 6),
            "winner": summarize_row(winner),
            "top3": [
                {"score": round(score, 6), **summarize_row(row)}
                for score, row in scored[:3]
            ],
        }
    return scenarios


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage8 Scenario Strategy Recommendations",
        "",
        f"- result_files: `{len(report['result_files'])}`",
        f"- row_count: `{report['row_count']}`",
        f"- writes: `none; analysis only`",
        "",
        "| Scenario | Winner | Score | Key metrics |",
        "|---|---|---:|---|",
    ]
    for name in SCENARIOS:
        item = report["scenarios"][name]
        winner = item.get("winner") or {}
        metrics = (
            f"R@5={winner.get('recall_at_5')} Rank1={winner.get('rank1')} "
            f"Obj@10={winner.get('object_kind_precision_at_10')} "
            f"Hard={winner.get('hard_negative_pass_rate')} "
            f"OCR={winner.get('ocr_top1_kind')}"
        )
        lines.append(f"| `{name}` | `{winner.get('strategy', item.get('status'))}` | {item.get('score', '')} | {metrics} |")
    lines.extend(["", "## Details", ""])
    for name in SCENARIOS:
        item = report["scenarios"][name]
        lines.append(f"### {name}")
        lines.append("")
        lines.append(item["description"])
        lines.append("")
        for row in item.get("top3", []):
            lines.append(
                f"- score `{row['score']}`: `{row['strategy']}`; "
                f"R@5 `{row.get('recall_at_5')}`, Rank1 `{row.get('rank1')}`, "
                f"MRR `{row.get('mrr_at_10')}`, City `{row.get('city_precision_at_10')}`, "
                f"Object `{row.get('object_kind_precision_at_10')}`, "
                f"Hard `{row.get('hard_negative_pass_rate')}`, SourceGate `{row.get('source_gate_pass_rate')}`, "
                f"jobs `{row.get('job_count')}`"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-json", action="append", required=True, help="algorithm_results.json or stage8_vector_semantic_eval.json")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    result_paths = [Path(value) for value in args.result_json]
    rows: list[dict[str, Any]] = []
    for path in result_paths:
        rows.extend(load_rows(path))
    report = {
        "schema_version": "stage8_scenario_strategy_recommendations.v1",
        "result_files": [str(path) for path in result_paths],
        "row_count": len(rows),
        "scenarios": pick_scenarios(rows),
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scenario_strategy_recommendations.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_markdown(out_dir / "SCENARIO_STRATEGY_RECOMMENDATIONS.md", report)
    print(json.dumps({"ok": True, "out_dir": str(out_dir), "row_count": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
