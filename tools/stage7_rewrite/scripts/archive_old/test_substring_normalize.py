#!/usr/bin/env python3
"""Test substring normalization for evidence/bio type tolerance."""
import json
import sys
from pathlib import Path

# ============================================================
# Functions (must match runner logic)
# ============================================================

def normalize_evidence_value(value):
    """Normalize any evidence/bio value to list[str] with warnings."""
    warnings = []
    
    if value is None:
        return [], ["missing"]
    
    if isinstance(value, str):
        s = value.strip()
        if s:
            return [s], []
        return [], ["missing"]
    
    if isinstance(value, (int, float, bool)):
        return [str(value)], ["non_string"]
    
    if isinstance(value, list):
        texts = []
        for item in value:
            if item is None:
                warnings.append("null_item_in_list")
                continue
            if isinstance(item, str):
                if item.strip():
                    texts.append(item.strip())
            elif isinstance(item, dict):
                t = (item.get("text") or item.get("quote") or 
                     item.get("evidence") or item.get("bio") or 
                     item.get("value") or "")
                if isinstance(t, str) and t.strip():
                    texts.append(t.strip())
                else:
                    warnings.append("dict_no_text_field")
            elif isinstance(item, list):
                nested, nw = normalize_evidence_value(item)
                texts.extend(nested)
                warnings.extend(nw)
            else:
                s = str(item).strip()
                if s:
                    texts.append(s)
                warnings.append("unknown_type_in_list")
        if not texts:
            warnings.append("list_empty_after_normalize")
        return texts, warnings
    
    if isinstance(value, dict):
        t = (value.get("text") or value.get("quote") or 
             value.get("evidence") or value.get("bio") or 
             value.get("value") or "")
        if isinstance(t, str) and t.strip():
            return [t.strip()], []
        # Try all string values
        for v in value.values():
            if isinstance(v, str) and v.strip():
                return [v.strip()], ["nested_dict_fallback"]
            if isinstance(v, dict):
                for vv in v.values():
                    if isinstance(vv, str) and vv.strip():
                        return [vv.strip()], ["deeply_nested_fallback"]
        # Last resort: json.dumps
        dumped = json.dumps(value, ensure_ascii=False)[:200]
        return [dumped], ["malformed"]
    
    # Fallback for any other type
    return [str(value)], ["unknown_type"]


def check_substring_any(value, source_text):
    """Check if any normalized text is a substring of source_text."""
    result = {
        "ok": False,
        "checked": [],
        "matched": [],
        "missing": [],
        "warnings": [],
    }
    
    if not source_text or not source_text.strip():
        result["warnings"].append("empty_source")
        return result
    
    texts, warnings = normalize_evidence_value(value)
    result["warnings"].extend(warnings)
    
    if not texts:
        return result
    
    for t in texts:
        if not t:
            continue
        result["checked"].append(t)
        if t in source_text:
            result["matched"].append(t)
            result["ok"] = True
        else:
            result["missing"].append(t)
    
    return result


# ============================================================
# Test cases
# ============================================================

SOURCE = "这是一个测试原文短句，包含一些信息。成都社区电台举办了一场演出。"

TEST_CASES = [
    # (description, value, expected_ok)
    ("simple string in source", "原文短句", True),  # "原文短句" IS in SOURCE
    ("string in source", "成都社区电台", True),
    ("list with hits", ["成都社区电台", "不存在"], True),
    ("list of dicts with text", [{"text": "成都社区电台"}], True),
    ("list of dicts with quote", [{"quote": "演出"}], True),
    ("list of dicts with evidence", [{"evidence": "成都"}], True),
    ("single dict with text", {"text": "社区电台"}, True),
    ("dict with evidence list", {"evidence": ["成都", "不存在"]}, False),  # dict, not list — fallback
    ("None value", None, False),
    ("integer", 123, False),
    ("boolean True", True, False),
    ("empty list", [], False),
    ("nested weird dict finds text", {"weird": {"nested": "原文短句"}}, True),  # deeply_nested fallback finds it
    ("list with None item", ["成都", None, "电台"], True),
    ("list with dict no text field", [{"foo": "bar"}], False),
    ("float", 3.14, False),
    ("string in source long", "成都社区电台举办了一场演出", True),
    ("whitespace string strips to match", "  成都  ", True),  # stripped "成都" IS in source
]

def main():
    print("=" * 60)
    print("Substring Normalize Tests")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for desc, value, expected_ok in TEST_CASES:
        try:
            result = check_substring_any(value, SOURCE)
            actual_ok = result["ok"]
            status = "PASS" if actual_ok == expected_ok else "FAIL"
            
            if status == "PASS":
                passed += 1
            else:
                failed += 1
            
            val_repr = repr(value)[:60]
            print(f"  [{status}] {desc}")
            print(f"         value={val_repr}")
            print(f"         expected_ok={expected_ok}, actual_ok={actual_ok}")
            print(f"         matched={result['matched']}, checked={result['checked'][:2]}")
            if result["warnings"]:
                print(f"         warnings={result['warnings']}")
            print()
        except Exception as e:
            failed += 1
            print(f"  [CRASH] {desc}: {e}")
            print()
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {len(TEST_CASES)} total")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")

if __name__ == "__main__":
    main()
