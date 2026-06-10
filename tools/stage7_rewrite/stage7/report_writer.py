"""Report writer for Stage 7 runs."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from typing import Any

from .atomic_io import atomic_write_json


def write_canary_report(output_root: Path, results: list[dict]) -> Path:
    """Write CANARY_REPORT.md with full metrics."""
    total = len(results)
    done = sum(1 for r in results if r.get("status") == "done")
    done_warnings = sum(1 for r in results if r.get("status") == "done_with_warnings")
    failed_retryable = sum(1 for r in results if r.get("status") == "failed_retryable")
    failed_final = sum(1 for r in results if r.get("status") == "failed_final")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    json_ok = sum(1 for r in results if r.get("json_valid"))
    schema_ok = sum(1 for r in results if r.get("schema_valid"))
    entities_nonzero = sum(1 for r in results if r.get("entity_count", 0) > 0)
    events_nonzero = sum(1 for r in results if r.get("event_count", 0) > 0)
    relations_nonzero = sum(1 for r in results if r.get("relation_count", 0) > 0)
    claims_nonzero = sum(1 for r in results if r.get("claim_count", 0) > 0)

    empty_recovery = sum(1 for r in results if r.get("quality_verdict") == "FAIL_RETRYABLE" or (r.get("status") == "done_with_warnings" and r.get("entity_count", 0) == 0 and r.get("event_count", 0) == 0))
    empty_recovery_blocked = sum(1 for r in results if r.get("status") == "failed_final" and r.get("error_type") == "all_chunks_failed")
    empty_recovery_used = sum(1 for r in results if r.get("quality", {}).get("empty_recovery_used"))
    all_chunks_failed_count = sum(1 for r in results if r.get("quality", {}).get("all_chunks_failed"))
    context_exceeded_count = sum(r.get("quality", {}).get("context_exceeded_count", 0) for r in results)
    repair_used_count = sum(r.get("quality", {}).get("repair_used", 0) for r in results)
    retry_used_count = sum(r.get("quality", {}).get("retry_used", 0) for r in results)
    parse_repaired_count = sum(r.get("quality", {}).get("parse_repaired_count", 0) for r in results)
    schema_normalized_count = sum(r.get("quality", {}).get("schema_normalized_count", 0) for r in results)
    schema_invalid_count = sum(r.get("quality", {}).get("schema_invalid_count", 0) for r in results)

    total_entities = sum(r.get("entity_count", 0) for r in results)
    total_events = sum(r.get("event_count", 0) for r in results)
    total_relations = sum(r.get("relation_count", 0) for r in results)
    total_claims = sum(r.get("claim_count", 0) for r in results)

    parse_rate = json_ok / total if total else 0
    schema_rate = schema_ok / total if total else 0
    entity_rate = entities_nonzero / total if total else 0
    event_rate = events_nonzero / total if total else 0
    empty_recovery_rate = empty_recovery / total if total else 0
    failed_final_rate = failed_final / total if total else 0

    avg_entities = total_entities / total if total else 0
    avg_events = total_events / total if total else 0
    avg_relations = total_relations / total if total else 0
    avg_claims = total_claims / total if total else 0

    evidence_totals = [r.get("evidence_hit_rate", 0) for r in results if r.get("evidence_hit_rate") is not None]
    avg_evidence_hit = sum(evidence_totals) / len(evidence_totals) if evidence_totals else 0

    if parse_rate >= 0.8 and schema_rate >= 0.8 and entity_rate >= 0.6 and empty_recovery == 0 and empty_recovery_used == 0:
        verdict = "GREEN"
    elif parse_rate >= 0.6 and schema_rate >= 0.6 and empty_recovery_used == 0:
        verdict = "AMBER"
    else:
        verdict = "RED"

    if empty_recovery_used > 0:
        verdict = "RED"

    lines = [
        "# Canary Report",
        f"\n**Date:** {datetime.now().isoformat()}",
        f"**Mode:** canary",
        "",
        "## Summary",
        f"- **Total:** {total}",
        f"- **Done:** {done}",
        f"- **Done (warnings):** {done_warnings}",
        f"- **Failed (retryable):** {failed_retryable}",
        f"- **Failed (final):** {failed_final}",
        f"- **Skipped:** {skipped}",
        "",
        "## Quality Metrics",
        f"- **JSON Parse Rate:** {parse_rate:.1%} ({json_ok}/{total})",
        f"- **Schema Pass Rate:** {schema_rate:.1%} ({schema_ok}/{total})",
        f"- **Entity Non-Zero Rate:** {entity_rate:.1%} ({entities_nonzero}/{total})",
        f"- **Event Non-Zero Rate:** {event_rate:.1%} ({events_nonzero}/{total})",
        f"- **Relations Non-Zero:** {relations_nonzero}/{total}",
        f"- **Claims Non-Zero:** {claims_nonzero}/{total}",
        f"- **Avg Entities/Article:** {avg_entities:.1f}",
        f"- **Avg Events/Article:** {avg_events:.1f}",
        f"- **Avg Relations/Article:** {avg_relations:.1f}",
        f"- **Avg Claims/Article:** {avg_claims:.1f}",
        f"- **Avg Evidence Hit Rate:** {avg_evidence_hit:.1%}",
        "",
        "## Failure Analysis",
        f"- **Empty Recovery Used:** {empty_recovery_used} (MUST be 0)",
        f"- **Empty Recovery Blocked:** {empty_recovery_blocked}",
        f"- **All Chunks Failed:** {all_chunks_failed_count}",
        f"- **Context Exceeded:** {context_exceeded_count}",
        f"- **Repair Used:** {repair_used_count}",
        f"- **Retry Used:** {retry_used_count}",
        f"- **Parse Repaired (success):** {parse_repaired_count}",
        f"- **Schema Normalized (success):** {schema_normalized_count}",
        f"- **Schema Invalid (rejected):** {schema_invalid_count}",
        f"- **Parse Failed Recovered Empty Rate:** {empty_recovery_rate:.1%}",
        f"- **Failed Final Rate:** {failed_final_rate:.1%}",
        "",
        f"## Verdict: {verdict}",
        "",
        "## Per-Article Results",
    ]

    for r in results:
        v = r.get("quality_verdict", "")
        st = r.get("status", "?")
        lines.append(f"- `{r.get('article_uid', '?')[:20]}...` | status={st} | verdict={v} | E={r.get('entity_count', 0)} Ev={r.get('event_count', 0)} R={r.get('relation_count', 0)} C={r.get('claim_count', 0)} | ev_hr={r.get('evidence_hit_rate', 0):.0%}")

    lines += ["\n## Errors"]
    errors = [r for r in results if r.get("error_type")]
    if errors:
        for r in errors:
            lines.append(f"- `{r.get('article_uid', '?')[:20]}...` | {r.get('error_type')}: {r.get('error_message', '')[:100]}")
    else:
        lines.append("- No errors")

    lines += ["\n## Gate Check"]
    lines.append(f"- [ ] Program did not crash")
    lines.append(f"- [ ] All {total} articles have explicit status")
    lines.append(f"- [ ] JSON parse rate >= 80%: {parse_rate:.1%} {'PASS' if parse_rate >= 0.8 else 'FAIL'}")
    lines.append(f"- [ ] Schema pass rate >= 80%: {schema_rate:.1%} {'PASS' if schema_rate >= 0.8 else 'FAIL'}")
    lines.append(f"- [ ] At least 3/{total} have non-zero entities: {entities_nonzero} {'PASS' if entities_nonzero >= 3 else 'FAIL'}")
    lines.append(f"- [ ] parse_failed_recovered_empty_count = 0: {empty_recovery_used} {'PASS' if empty_recovery_used == 0 else 'FAIL'}")
    lines.append(f"- [ ] empty_recovery_blocked working: {empty_recovery_blocked}")
    lines.append(f"- [ ] Checkpoint updated")
    lines.append(f"- [ ] Rerun skips done articles")

    lines += ["\n## Next Steps"]
    if verdict == "GREEN":
        lines.append("- Proceed to Resume Crash Test, then Mini 50 batch.")
    elif verdict == "AMBER":
        lines.append("- Review failures and adjust prompt/retry before Mini 50.")
    else:
        lines.append("- STOP. Fix critical issues before proceeding.")

    report_path = output_root / "reports" / f"CANARY_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    atomic_write_json(output_root / "reports" / "QUALITY_DASHBOARD.json", {
        "mode": "canary",
        "total": total,
        "done": done,
        "done_with_warnings": done_warnings,
        "failed_retryable": failed_retryable,
        "failed_final": failed_final,
        "skipped": skipped,
        "json_parse_rate": parse_rate,
        "schema_pass_rate": schema_rate,
        "entity_nonzero_rate": entity_rate,
        "event_nonzero_rate": event_rate,
        "parse_failed_recovered_empty_count": empty_recovery,
        "parse_failed_recovered_empty_rate": empty_recovery_rate,
        "empty_recovery_blocked": empty_recovery_blocked,
        "empty_recovery_used": empty_recovery_used,
        "all_chunks_failed_count": all_chunks_failed_count,
        "context_exceeded_count": context_exceeded_count,
        "repair_used_count": repair_used_count,
        "retry_used_count": retry_used_count,
        "failed_final_rate": failed_final_rate,
        "avg_entities_per_article": avg_entities,
        "avg_events_per_article": avg_events,
        "avg_relations_per_article": avg_relations,
        "avg_claims_per_article": avg_claims,
        "evidence_hit_rate": avg_evidence_hit,
        "verdict": verdict,
        "timestamp": datetime.now().isoformat(),
        "results": results,
    })

    return report_path


def write_batch_report(output_root: Path, mode: str, results: list[dict], stats: dict) -> Path:
    """Write batch run report (Mini 50 / Pilot 500)."""
    total = len(results)
    done = sum(1 for r in results if r.get("status") == "done")
    done_warnings = sum(1 for r in results if r.get("status") == "done_with_warnings")
    failed_retryable = sum(1 for r in results if r.get("status") == "failed_retryable")
    failed_final = sum(1 for r in results if r.get("status") == "failed_final")
    json_ok = sum(1 for r in results if r.get("json_valid"))
    schema_ok = sum(1 for r in results if r.get("schema_valid"))
    entities_nonzero = sum(1 for r in results if r.get("entity_count", 0) > 0)

    empty_recovery_used = sum(1 for r in results if r.get("quality", {}).get("empty_recovery_used"))
    empty_recovery_blocked = sum(1 for r in results if r.get("status") == "failed_final" and r.get("error_type") == "all_chunks_failed")

    parse_rate = json_ok / total if total else 0
    schema_rate = schema_ok / total if total else 0
    entity_rate = entities_nonzero / total if total else 0

    evidence_rates = [r.get("evidence_hit_rate", 0) for r in results if r.get("evidence_hit_rate") is not None]
    avg_evidence = sum(evidence_rates) / len(evidence_rates) if evidence_rates else 0

    if mode == "batch50":
        green = parse_rate >= 0.95 and schema_rate >= 0.90 and entity_rate >= 0.60 and empty_recovery_used == 0 and avg_evidence >= 0.85
        amber = parse_rate >= 0.85 and schema_rate >= 0.80 and empty_recovery_used == 0
    else:
        green = parse_rate >= 0.97 and schema_rate >= 0.95 and entity_rate >= 0.60 and empty_recovery_used == 0 and avg_evidence >= 0.88
        amber = parse_rate >= 0.90 and schema_rate >= 0.88 and empty_recovery_used == 0

    verdict = "GREEN" if green else ("AMBER" if amber else "RED")
    if empty_recovery_used > 0:
        verdict = "RED"

    lines = [
        f"# {mode.upper()} Report",
        f"\n**Date:** {datetime.now().isoformat()}",
        f"**Mode:** {mode}",
        "",
        "## Summary",
        f"- Total processed: {total}",
        f"- Done: {done}",
        f"- Done (warnings): {done_warnings}",
        f"- Failed (retryable): {failed_retryable}",
        f"- Failed (final): {failed_final}",
        "",
        "## Quality",
        f"- JSON Parse Rate: {parse_rate:.1%}",
        f"- Schema Pass Rate: {schema_rate:.1%}",
        f"- Entity Non-Zero Rate: {entity_rate:.1%}",
        f"- Evidence Hit Rate: {avg_evidence:.1%}",
        f"- Empty Recovery Used: {empty_recovery_used} (MUST be 0)",
        f"- Empty Recovery Blocked: {empty_recovery_blocked}",
        "",
        f"## Verdict: {verdict}",
        "",
        "## DB Stats",
        f"- Total in DB: {stats.get('total', 0)}",
        f"- Done: {stats.get('done', 0)}",
        f"- Done (warnings): {stats.get('done_with_warnings', 0)}",
        f"- Failed (retryable): {stats.get('failed_retryable', 0)}",
        f"- Failed (final): {stats.get('failed_final', 0)}",
        f"- Pending: {stats.get('pending', 0)}",
        f"- Running: {stats.get('running', 0)}",
    ]

    report_path = output_root / "reports" / f"BATCH_{mode.upper()}_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return report_path


def write_run_status_md(output_root: Path, stats: dict) -> None:
    """Write RUN_STATUS.md."""
    total = stats.get("total", 0) or 0
    done = stats.get("done", 0) or 0
    done_warnings = stats.get("done_with_warnings", 0) or 0
    failed_retryable = stats.get("failed_retryable", 0) or 0
    failed_final = stats.get("failed_final", 0) or 0
    skipped = stats.get("skipped", 0) or 0
    successful = done + done_warnings
    processed = successful + failed_retryable + failed_final + skipped
    percent = stats.get("percent")
    if percent is None:
        percent = (processed / total) * 100 if total else 0
    json_parse_rate = stats.get("json_parse_rate")
    if json_parse_rate is None:
        json_valid_count = stats.get("json_valid_count", successful) or 0
        json_parse_rate = json_valid_count / processed if processed else 0
    schema_pass_rate = stats.get("schema_pass_rate")
    if schema_pass_rate is None:
        schema_valid_count = stats.get("schema_valid_count", successful) or 0
        schema_pass_rate = schema_valid_count / processed if processed else 0
    evidence_hit_rate = stats.get("evidence_hit_rate")
    if evidence_hit_rate is None:
        evidence_hit_rate = schema_pass_rate
    avg_entities = stats.get("avg_entities")
    if avg_entities is None:
        avg_entities = (stats.get("entity_count", 0) or 0) / successful if successful else 0
    avg_events = stats.get("avg_events")
    if avg_events is None:
        avg_events = (stats.get("event_count", 0) or 0) / successful if successful else 0
    lines = [
        "# Stage7 Rewrite Run Status",
        f"\n**Updated:** {datetime.now().isoformat()}",
        f"\n## Current Phase",
        stats.get("phase", "UNKNOWN"),
        "\n## Total Progress",
        f"- total_articles: {total}",
        f"- done: {done}",
        f"- done_with_warnings: {done_warnings}",
        f"- failed_retryable: {failed_retryable}",
        f"- failed_final: {failed_final}",
        f"- pending: {stats.get('pending', 0)}",
        f"- running: {stats.get('running', 0)}",
        f"- skipped: {skipped}",
        f"- percent: {percent:.1f}%",
        "\n## Quality",
        f"- json_parse_rate: {json_parse_rate:.1%}",
        f"- schema_pass_rate: {schema_pass_rate:.1%}",
        f"- evidence_hit_rate: {evidence_hit_rate:.1%}",
        f"- avg_entities_per_article: {avg_entities:.1f}",
        f"- avg_events_per_article: {avg_events:.1f}",
        f"- empty_recovery_blocked: {stats.get('empty_recovery_blocked', 0)}",
        f"- empty_recovery_used: {stats.get('empty_recovery_used', 0)}",
        "\n## Need Human Intervention",
        "NO" if stats.get("phase") != "ERROR" else "YES - check logs",
    ]

    path = output_root / "reports" / "RUN_STATUS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_resume_crash_test_report(output_root: Path, test_data: dict) -> Path:
    """Write RESUME_CRASH_TEST_REPORT.md."""
    lines = [
        "# Resume Crash Test Report",
        f"\n**Date:** {datetime.now().isoformat()}",
        "",
        "## Test Steps",
        f"1. First start command: `{test_data.get('first_command', '')}`",
        f"2. Articles completed before interrupt: {test_data.get('done_before_interrupt', 0)}",
        f"3. Running articles at interrupt: {test_data.get('running_at_interrupt', 0)}",
        f"4. Resume command: `{test_data.get('resume_command', '')}`",
        f"5. Articles completed after resume: {test_data.get('done_after_resume', 0)}",
        "",
        "## Verification",
        f"- Duplicate processing of done articles: {test_data.get('duplicate_processing', 'UNKNOWN')}",
        f"- Stale running recovered: {test_data.get('stale_recovered', 'UNKNOWN')}",
        f"- Checkpoint integrity: {test_data.get('checkpoint_integrity', 'UNKNOWN')}",
        f"- SQLite integrity: {test_data.get('sqlite_integrity', 'UNKNOWN')}",
        "",
        "## Checkpoint Comparison",
        f"- Before: {json.dumps(test_data.get('checkpoint_before', {}), ensure_ascii=False)}",
        f"- After: {json.dumps(test_data.get('checkpoint_after', {}), ensure_ascii=False)}",
        "",
        f"## Verdict: {test_data.get('verdict', 'UNKNOWN')}",
        "",
        "## GREEN Conditions",
        f"- [ ] Interrupt resumable: {test_data.get('resumable', False)}",
        f"- [ ] Done articles not reprocessed: {test_data.get('no_reprocess', False)}",
        f"- [ ] Stale running recovered: {test_data.get('stale_recovered_bool', False)}",
        f"- [ ] Checkpoint normal: {test_data.get('checkpoint_ok', False)}",
        f"- [ ] SQLite not corrupted: {test_data.get('sqlite_ok', False)}",
    ]

    path = output_root / "reports" / "RESUME_CRASH_TEST_REPORT.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return path
