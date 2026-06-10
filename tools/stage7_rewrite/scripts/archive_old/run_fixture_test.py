"""Parse failed fixture test — standalone Python script."""
import json
import sys
import os
from pathlib import Path

STAGE7_ROOT = Path(__file__).parent.parent
FIXTURE_DIR = STAGE7_ROOT / "artifacts" / "parse_failed_fixture"

sys.path.insert(0, str(STAGE7_ROOT))

from stage7.json_repair import parse_and_repair_json
from stage7.validators import validate_extract

results = []

# Test 1: malformed JSON
malformed_path = FIXTURE_DIR / "malformed_llm_response.json"
if malformed_path.exists():
    raw = malformed_path.read_text(encoding="utf-8-sig")
else:
    raw = '{"entities": INVALID_JSON_HERE, "relations": [broken\n"summary": "malformed"}'

repair = parse_and_repair_json(raw)
parsed = repair.value if repair.ok else None
val = validate_extract(parsed) if parsed else {"ok": False, "errors": ["parse_failed"], "warnings": []}
results.append({
    "test": "malformed_json",
    "parsed": parsed is not None,
    "valid": val["ok"],
    "errors": val.get("errors", []),
    "warnings": val.get("warnings", []),
    "expect": "parse_failed should NOT become success_empty",
    "pass": not val["ok"],
})

# Test 2: empty response
empty_path = FIXTURE_DIR / "empty_llm_response.json"
if empty_path.exists():
    raw = empty_path.read_text(encoding="utf-8-sig")
else:
    raw = "{}"

repair = parse_and_repair_json(raw)
parsed = repair.value if repair.ok else None
val = validate_extract(parsed) if parsed else {"ok": False, "errors": ["parse_failed"], "warnings": []}
results.append({
    "test": "empty_response",
    "parsed": parsed is not None,
    "valid": val["ok"],
    "errors": val.get("errors", []),
    "warnings": val.get("warnings", []),
    "expect": "empty should fail validation",
    "pass": not val["ok"],
})

# Test 3: all chunks failed
all_failed_path = FIXTURE_DIR / "all_chunks_failed.json"
if all_failed_path.exists():
    data = json.loads(all_failed_path.read_text(encoding="utf-8-sig"))
else:
    data = {"chunk_results": [{"error": "context_length_exceeded"}, {"error": "json_parse_failed"}, {"error": "json_parse_failed"}]}

all_failed = all("error" in c for c in data.get("chunk_results", []))
results.append({
    "test": "all_chunks_failed",
    "all_failed": all_failed,
    "expect": "all_chunks_failed should become failed_final",
    "status": "failed_final" if all_failed else "unexpected",
    "pass": all_failed,
})

# Test 4: legal empty with empty_reason
legal_empty = {
    "schema_version": "article_extract.v1",
    "summary": "",
    "topics": [],
    "keywords": [],
    "entities": [],
    "events": [],
    "relations": [],
    "claims": [],
    "quality": {"is_empty": True, "empty_reason": "no extractable content"},
}
val = validate_extract(legal_empty)
results.append({
    "test": "legal_empty",
    "parsed": True,
    "valid": val["ok"],
    "errors": val.get("errors", []),
    "expect": "legal empty with all required fields should pass",
    "pass": val["ok"],
})

# Test 5: bio exact substring check
bio_test_text = "张三是上海电子音乐厂牌 Example 的主理人，长期组织地下派对。"
bio_entity_good = {
    "name": "张三",
    "type": "person",
    "confidence": 0.9,
    "bio": "张三是上海电子音乐厂牌 Example 的主理人",
    "evidence": [{"quote": "张三是上海电子音乐厂牌 Example 的主理人，长期组织地下派对。"}],
}
bio_entity_bad = {
    "name": "张三",
    "type": "person",
    "confidence": 0.9,
    "bio": "张三是上海的电子音乐组织者",
    "evidence": [{"quote": "张三是上海电子音乐厂牌 Example 的主理人，长期组织地下派对。"}],
}

val_good = validate_extract({
    "schema_version": "article_extract.v1",
    "summary": "",
    "topics": [],
    "keywords": [],
    "entities": [bio_entity_good],
    "events": [],
    "relations": [],
    "claims": [],
}, source_text=bio_test_text)

val_bad = validate_extract({
    "schema_version": "article_extract.v1",
    "summary": "",
    "topics": [],
    "keywords": [],
    "entities": [bio_entity_bad],
    "events": [],
    "relations": [],
    "claims": [],
}, source_text=bio_test_text)

bio_good_pass = val_good.get("bio_stats", {}).get("entity_bio_exact_match_pass", 0) > 0
bio_bad_cleared = val_bad.get("bio_stats", {}).get("entity_bio_cleared", 0) > 0

results.append({
    "test": "bio_exact_substring_good",
    "bio_matched": bio_good_pass,
    "expect": "exact substring bio should pass",
    "pass": bio_good_pass,
})
results.append({
    "test": "bio_exact_substring_bad",
    "bio_cleared": bio_bad_cleared,
    "expect": "abstracted bio should be cleared",
    "pass": bio_bad_cleared,
})

# Print results
all_pass = all(r.get("pass", False) for r in results)
for r in results:
    status = "PASS" if r.get("pass") else "FAIL"
    print(f"[{status}] {r['test']}: {r.get('expect', '')}")
    if r.get("errors"):
        print(f"  errors: {r['errors']}")
    if r.get("warnings"):
        print(f"  warnings: {r['warnings'][:3]}")

print()
print(f"Total: {len(results)}, Pass: {sum(1 for r in results if r.get('pass'))}, Fail: {sum(1 for r in results if not r.get('pass'))}")
verdict = "GREEN" if all_pass else "RED"
print(f"Verdict: {verdict}")

# Write report
report_dir = FIXTURE_DIR
report_dir.mkdir(parents=True, exist_ok=True)
report_path = report_dir / "report.md"

lines = [
    "# Parse Failed Fixture Report",
    f"\n**Date:** 2026-04-28",
    f"**Verdict:** {verdict}",
    "",
    "## Results",
    "",
    "| Test | Expectation | Result |",
    "|------|-------------|--------|",
]
for r in results:
    status = "PASS" if r.get("pass") else "FAIL"
    lines.append(f"| {r['test']} | {r.get('expect', '')} | {status} |")

lines += [f"\n## Total: {len(results)} tests, {sum(1 for r in results if r.get('pass'))} pass, {sum(1 for r in results if not r.get('pass'))} fail"]

report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\nReport: {report_path}")

sys.exit(0 if all_pass else 1)
