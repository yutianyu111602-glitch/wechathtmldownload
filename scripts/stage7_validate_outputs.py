#!/usr/bin/env python3
"""
Stage 7 Output Validator
Checks JSON parse, schema, bio exactness, evidence exactness
"""
import json, sys, os
from stage7_postprocess_output import (
    try_parse_json, normalize_schema, 
    exact_substring_gate, ALLOWED_ENTITY_TYPES
)

def validate_output(raw_response: str, source_text: str) -> dict:
    results = {
        "raw_parse_ok": False,
        "schema_ok": False,
        "bio_exact_count": 0,
        "bio_not_exact_count": 0,
        "evidence_exact_count": 0,
        "evidence_not_exact_count": 0,
        "markdown_wrapped": False,
        "extra_text_outside_json": False,
        "empty_entities": False,
        "empty_events": False,
        "errors": []
    }
    
    # Check markdown fence
    stripped = raw_response.strip()
    if stripped.startswith("```"):
        results["markdown_wrapped"] = True
    
    # Try parse
    parsed, error = try_parse_json(raw_response)
    if parsed is None:
        results["errors"].append(f"parse_failed: {error}")
        return results
    
    results["raw_parse_ok"] = True
    
    # Check for extra text outside JSON
    first = raw_response.find("{")
    last = raw_response.rfind("}")
    before = raw_response[:first].strip()
    after = raw_response[last+1:].strip()
    if before or after:
        if not (before.startswith("```") and after.endswith("```")):
            # Only flag if it's non-trivial text
            if len(before) > 3 or len(after) > 3:
                results["extra_text_outside_json"] = True
    
    # Normalize
    normalized = normalize_schema(parsed)
    
    # Check schema completeness
    required = ["article_id", "source", "entities", "events", "relations", "warnings", "errors"]
    missing = [k for k in required if k not in normalized]
    if missing:
        results["errors"].append(f"missing_fields: {missing}")
    else:
        results["schema_ok"] = True
    
    # Check entities
    entities = normalized.get("entities", [])
    results["empty_entities"] = len(entities) == 0
    
    for ent in entities:
        bio = ent.get("bio", "")
        if bio and bio not in source_text:
            results["bio_not_exact_count"] += 1
        elif bio:
            results["bio_exact_count"] += 1
        
        for ev in ent.get("evidence", []):
            quote = ev.get("quote", "")
            if quote and quote not in source_text:
                results["evidence_not_exact_count"] += 1
            elif quote:
                results["evidence_exact_count"] += 1
    
    # Check events
    events = normalized.get("events", [])
    results["empty_events"] = len(events) == 0
    
    for evt in events:
        for ev in evt.get("evidence", []):
            quote = ev.get("quote", "")
            if quote and quote not in source_text:
                results["evidence_not_exact_count"] += 1
            elif quote:
                results["evidence_exact_count"] += 1
    
    return results

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            source = f.read()
        with open(sys.argv[2], 'r', encoding='utf-8') as f:
            raw = f.read()
        result = validate_output(raw, source)
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    else:
        print("Usage: validate.py <source_text_file> <raw_response_file>")
