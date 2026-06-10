#!/usr/bin/env python3
"""
Stage 7 v1 Deterministic Postprocessor
Performs: JSON repair → schema normalize → bio exact substring gate → evidence exact substring gate
"""
import json, re, os, sys
from typing import Optional

ALLOWED_ENTITY_TYPES = {"person", "organization", "event", "work", "place", "concept", "unknown"}

def strip_markdown_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()

def extract_balanced_json(text: str) -> Optional[str]:
    text = strip_markdown_fence(text)
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': in_str = False
        else:
            if ch == '"': in_str = True
            elif ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
    return None

def try_parse_json(raw: str):
    """Try multiple strategies to extract JSON from model output."""
    # Strategy 1: direct
    try: return json.loads(raw), None
    except: pass
    # Strategy 2: strip fence
    cleaned = strip_markdown_fence(raw)
    try: return json.loads(cleaned), None
    except: pass
    # Strategy 3: balanced extraction
    balanced = extract_balanced_json(raw)
    if balanced:
        try: return json.loads(balanced), None
        except: pass
    # Strategy 4: find first { and last }
    first = raw.find("{")
    last = raw.rfind("}")
    if first >= 0 and last > first:
        candidate = raw[first:last+1]
        try: return json.loads(candidate), None
        except: pass
    return None, "unable_to_parse_json"

EMPTY_STRUCTURE = {
    "article_id": "",
    "source": {"title": "", "account": "", "published_at": ""},
    "entities": [],
    "events": [],
    "relations": [],
    "warnings": ["model_output_invalid_json"],
    "errors": []
}

def normalize_schema(obj: dict) -> dict:
    """Ensure all required fields exist with proper defaults."""
    required_fields = {
        "article_id": "",
        "source": {"title": "", "account": "", "published_at": ""},
        "entities": [],
        "events": [],
        "relations": [],
        "warnings": [],
        "errors": []
    }
    for key, default in required_fields.items():
        if key not in obj or obj[key] is None:
            obj[key] = default
    # Normalize source
    if not isinstance(obj.get("source"), dict):
        obj["source"] = {"title": "", "account": "", "published_at": ""}
    for sk in ["title", "account", "published_at"]:
        if sk not in obj["source"] or obj["source"][sk] is None:
            obj["source"][sk] = ""
    # Normalize arrays
    for arr_key in ["entities", "events", "relations", "warnings", "errors"]:
        if not isinstance(obj.get(arr_key), list):
            obj[arr_key] = []
    return obj

def exact_substring_gate(source_text: str, text: str) -> str:
    """If text is not an exact substring of source_text, return empty string."""
    if not text:
        return ""
    if text in source_text:
        return text
    return ""

def gate_bio(source_text: str, bio: str) -> str:
    """Bio must be exact substring of source text, or become empty."""
    return exact_substring_gate(source_text, bio)

def gate_evidence(source_text: str, evidence_list: list) -> list:
    """Remove evidence items whose quote is not an exact substring."""
    if not isinstance(evidence_list, list):
        return []
    result = []
    for ev in evidence_list:
        if not isinstance(ev, dict):
            continue
        quote = ev.get("quote", "")
        if not quote:
            continue
        if quote in source_text:
            result.append(ev)
        # else: drop this evidence
    return result

def postprocess_entity(source_text: str, entity: dict) -> dict:
    """Gate and normalize a single entity."""
    if not isinstance(entity, dict):
        entity = {}
    # Required fields
    entity.setdefault("id", "")
    entity.setdefault("name", "")
    entity.setdefault("type", "unknown")
    entity.setdefault("aliases", [])
    entity.setdefault("bio", "")
    entity.setdefault("evidence", [])
    entity.setdefault("confidence", 0.0)
    entity.setdefault("warnings", [])
    
    # Gate bio
    entity["bio"] = gate_bio(source_text, entity.get("bio", ""))
    # Gate evidence
    entity["evidence"] = gate_evidence(source_text, entity.get("evidence", []))
    # Validate type
    if entity.get("type") not in ALLOWED_ENTITY_TYPES:
        entity["type"] = "unknown"
    # Validate confidence
    conf = entity.get("confidence", 0.0)
    if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
        entity["confidence"] = 0.0
    # Validate arrays
    for key in ["aliases", "evidence", "warnings"]:
        if not isinstance(entity.get(key), list):
            entity[key] = []
    return entity

def postprocess_event(source_text: str, event: dict) -> dict:
    """Gate and normalize a single event."""
    if not isinstance(event, dict):
        event = {}
    event.setdefault("name", "")
    event.setdefault("date", "")
    event.setdefault("place", "")
    event.setdefault("participants", [])
    event.setdefault("evidence", [])
    event.setdefault("confidence", 0.0)
    
    event["evidence"] = gate_evidence(source_text, event.get("evidence", []))
    if not isinstance(event.get("participants"), list):
        event["participants"] = []
    return event

def postprocess_relation(source_text: str, relation: dict) -> dict:
    """Gate and normalize a single relation."""
    if not isinstance(relation, dict):
        relation = {}
    relation.setdefault("source_entity", "")
    relation.setdefault("relation_type", "")
    relation.setdefault("target_entity", "")
    relation.setdefault("evidence", [])
    relation.setdefault("confidence", 0.0)
    
    relation["evidence"] = gate_evidence(source_text, relation.get("evidence", []))
    return relation

def run_pipeline(raw_response: str, source_text: str) -> dict:
    """Full pipeline: parse → normalize → gate."""
    # Step 1: Parse
    parsed, error = try_parse_json(raw_response)
    if parsed is None:
        result = dict(EMPTY_STRUCTURE)
        result["errors"].append(error)
        return result
    
    # Step 2: Normalize schema
    result = normalize_schema(parsed)
    
    # Step 3: Gate entities
    result["entities"] = [postprocess_entity(source_text, e) for e in result.get("entities", [])]
    # Remove entities with empty name
    result["entities"] = [e for e in result["entities"] if e.get("name", "").strip()]
    
    # Step 4: Gate events
    result["events"] = [postprocess_event(source_text, e) for e in result.get("events", [])]
    
    # Step 5: Gate relations
    result["relations"] = [postprocess_relation(source_text, r) for r in result.get("relations", [])]
    
    return result

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            source = f.read()
        with open(sys.argv[2], 'r', encoding='utf-8') as f:
            raw = f.read()
        result = run_pipeline(raw, source)
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    else:
        print("Usage: postprocess.py <source_text_file> <raw_response_file>")
        print("Outputs: final JSON to stdout")
