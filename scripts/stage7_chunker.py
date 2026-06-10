#!/usr/bin/env python3
"""
Stage 7 Article Chunker - v2 (balanced + transient Context exceeded retry)
Default: target=1000, hard_max=1200, overlap=120
Transient Context exceeded (<=1200c) allowed 3 retries with backoff 5/15/45s.
Length true overflow: immediate chunk degradation 1200->800->500->350.
"""
import re

def split_by_paragraphs(text: str):
    """Split text by paragraph boundaries"""
    parts = re.split(r'\n\s*\n', text.strip())
    return [p.strip() for p in parts if p.strip()]

def split_long_paragraph(text: str, target_chars=800, overlap_chars=120, hard_max_chars=950):
    """Split a single long paragraph using sentence boundaries"""
    if len(text) <= hard_max_chars:
        return [text]
    sentences = re.split(r'(?<=[。！？.!?])\s*', text)
    chunks = []
    current = ""
    for s in sentences:
        if not s.strip():
            continue
        if len(current) + len(s) + 1 <= target_chars:
            current += s
        else:
            if current:
                chunks.append(current)
                overlap = current[-overlap_chars:] if len(current) > overlap_chars else current
                current = overlap + s
            else:
                # Sentence itself exceeds hard_max - hard split
                for i in range(0, len(s), target_chars):
                    chunks.append(s[i:i+target_chars])
                current = ""
    if current:
        chunks.append(current)
    return chunks

def split_article(text: str, target_chars=1000, overlap_chars=120, hard_max_chars=1200):
    """Main chunking function"""
    if len(text) <= hard_max_chars:
        # Clean up and return as single chunk
        return [text.strip()]
    
    paragraphs = split_by_paragraphs(text)
    chunks = []
    current = ""
    
    for p in paragraphs:
        if len(p) > hard_max_chars:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_long_paragraph(p, target_chars, overlap_chars, hard_max_chars))
            continue
        
        sep = "\n\n" if current else ""
        candidate = current + sep + p if current else p
        
        if len(candidate) <= target_chars:
            current = candidate
        else:
            if current.strip():
                chunks.append(current.strip())
            overlap = current[-overlap_chars:] if current and len(current) > overlap_chars else (current or "")
            current = (overlap + "\n\n" + p) if overlap else p
    
    if current.strip():
        chunks.append(current.strip())
    
    # Post-process: ensure no chunk exceeds hard_max
    final = []
    for c in chunks:
        if len(c) <= hard_max_chars:
            final.append(c)
        else:
            final.extend(split_long_paragraph(c, target_chars, overlap_chars, hard_max_chars))
    
    return final


def dedupe_list(lst):
    seen = set()
    result = []
    for item in lst:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

def dedupe_evidence(ev_list):
    seen_quotes = set()
    result = []
    for ev in ev_list:
        q = ev.get("quote", "")
        if q and q not in seen_quotes:
            seen_quotes.add(q)
            result.append(ev)
    return result

def merge_chunk_outputs(chunk_outputs, source_text):
    """Merge multiple chunk-level JSONs into article-level JSON.
    Handles outputs that may be (dict, error) tuples from try_parse_json."""
    merged = {
        "article_id": "",
        "source": {},
        "entities": [],
        "events": [],
        "relations": [],
        "warnings": [],
        "errors": []
    }
    
    if not chunk_outputs:
        return merged
    
    # Normalize: extract dict from (dict, error) tuples
    normalized = []
    for out in chunk_outputs:
        if isinstance(out, tuple):
            d, _ = out
            if isinstance(d, dict):
                normalized.append(d)
        elif isinstance(out, dict):
            normalized.append(out)
    
    if not normalized:
        return merged
    
    # Copy metadata from first output
    first = normalized[0]
    merged["article_id"] = first.get("article_id", "")
    merged["source"] = first.get("source", {})
    
    entity_map = {}
    event_map = {}
    relation_map = {}
    
    for out in normalized:
        # Merge entities
        for e in out.get("entities", []):
            name = e.get("name", "").strip()
            typ = e.get("type", "unknown")
            if not name:
                continue
            key = (name, typ)
            bio = e.get("bio", "")
            if bio and bio not in source_text:
                bio = ""
            evidence = []
            for ev in e.get("evidence", []):
                q = ev.get("quote", "")
                if q and q in source_text:
                    evidence.append(ev)
            e["bio"] = bio
            e["evidence"] = evidence
            if key not in entity_map:
                entity_map[key] = dict(e)
            else:
                old = entity_map[key]
                old["aliases"] = dedupe_list(old.get("aliases", []) + e.get("aliases", []))
                old["warnings"] = dedupe_list(old.get("warnings", []) + e.get("warnings", []))
                old["evidence"] = dedupe_evidence(old.get("evidence", []) + evidence)
                if not old.get("bio") and bio:
                    old["bio"] = bio
                old_c = float(old.get("confidence", 0))
                e_c = float(e.get("confidence", 0))
                old["confidence"] = max(old_c, e_c)
        
        # Merge events
        for ev in out.get("events", []):
            name = ev.get("name", "").strip()
            if not name:
                continue
            if name not in event_map:
                event_map[name] = dict(ev)
            else:
                old = event_map[name]
                old_c = float(old.get("confidence", 0))
                e_c = float(ev.get("confidence", 0))
                old["confidence"] = max(old_c, e_c)
        
        # Merge relations
        for r in out.get("relations", []):
            src = r.get("source_entity", "")
            typ = r.get("relation_type", "")
            tgt = r.get("target_entity", "")
            key = (src, typ, tgt)
            if key not in relation_map:
                relation_map[key] = dict(r)
        
        # Collect warnings
        for w in out.get("warnings", []):
            if w not in merged["warnings"]:
                merged["warnings"].append(w)
        
        for e in out.get("errors", []):
            if e not in merged["errors"]:
                merged["errors"].append(e)
    
    merged["entities"] = list(entity_map.values())
    merged["events"] = list(event_map.values())
    merged["relations"] = list(relation_map.values())
    
    return merged
