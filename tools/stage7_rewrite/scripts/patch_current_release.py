#!/usr/bin/env python3
"""
patch_current_release.py — Patch current_release items with yuanbao enrichment fields.

Reads enrichment data (dj_bio_lines, artist_profiles, historical_context, extraction_metadata)
from a JSON input file and patches matching items in current.json.

Safety:
- Write-protected by confirm token: ENABLE_YUANBAO_DJ_BIO_ENRICHMENT_{YYYYMMDD}
- Creates backup before writing (current.json.bak.{timestamp})
- Validates schema after patch
- Report-only mode by default (--write required)

Usage:
  # Report-only (dry run)
  python patch_current_release.py --input enrichment.json

  # Write with confirm token
  python patch_current_release.py --input enrichment.json --write \\
    --confirm-token ENABLE_YUANBAO_DJ_BIO_ENRICHMENT_20260608

Input JSON format:
{
  "enrichments": [
    {
      "item_id": "tote_music:4f7904c8f6060616",
      "dj_bio_lines": ["bio line 1", "bio line 2"],
      "artist_profiles": [{"name": "...", "role": "headliner", ...}],
      "historical_context": "...",
      "extraction_metadata": {"dj_bio_provider": "yuanbao", "dj_bio_model": "hunyuan_gpt_175B_0404"}
    }
  ]
}
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

# Default paths
DEFAULT_CURRENT_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "services", "weekly_activity_cloudrun",
    "data", "current_release", "current.json"
)

CONFIRM_TOKEN_RE = re.compile(r"^ENABLE_YUANBAO_DJ_BIO_ENRICHMENT_\d{8}$")
ALLOWED_ENRICHMENT_KEYS = {
    "dj_bio_lines", "artist_profiles", "historical_context", "extraction_metadata"
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[patch] Saved: {path} ({os.path.getsize(path)} bytes)")


def validate_enrichment(enrichment):
    """Validate enrichment data structure."""
    errors = []
    unknown = set(enrichment.keys()) - ALLOWED_ENRICHMENT_KEYS - {"item_id"}
    if unknown:
        errors.append(f"Unknown keys: {unknown}")

    if "dj_bio_lines" in enrichment:
        if not isinstance(enrichment["dj_bio_lines"], list):
            errors.append("dj_bio_lines must be a list")
        elif not all(isinstance(line, str) for line in enrichment["dj_bio_lines"]):
            errors.append("dj_bio_lines items must be strings")

    if "artist_profiles" in enrichment:
        if not isinstance(enrichment["artist_profiles"], list):
            errors.append("artist_profiles must be a list")
        else:
            for i, p in enumerate(enrichment["artist_profiles"]):
                if not isinstance(p, dict):
                    errors.append(f"artist_profiles[{i}] must be an object")
                elif "name" not in p:
                    errors.append(f"artist_profiles[{i}] missing 'name'")

    if "extraction_metadata" in enrichment:
        if not isinstance(enrichment["extraction_metadata"], dict):
            errors.append("extraction_metadata must be an object")

    return errors


def patch_item(item, enrichment, mode="merge"):
    """Apply enrichment data to a single item."""
    changed = False

    for key in ALLOWED_ENRICHMENT_KEYS:
        if key not in enrichment:
            continue

        new_value = enrichment[key]
        old_value = item.get(key)

        if mode == "merge" and isinstance(old_value, list) and isinstance(new_value, list):
            # Merge lists (dedupe)
            existing = set(
                json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, dict)
                else str(v)
                for v in old_value
            )
            merged = list(old_value)
            for v in new_value:
                sig = json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, dict) else str(v)
                if sig not in existing:
                    merged.append(v)
                    existing.add(sig)
                    changed = True
            if changed:
                item[key] = merged
        elif mode == "merge" and isinstance(old_value, dict) and isinstance(new_value, dict):
            # Merge dicts
            merged = {**old_value, **new_value}
            if merged != old_value:
                item[key] = merged
                changed = True
        elif old_value != new_value:
            item[key] = new_value
            changed = True

    return changed


def main():
    parser = argparse.ArgumentParser(description="Patch current_release with yuanbao enrichment")
    parser.add_argument("--input", required=True, help="JSON file with enrichment data")
    parser.add_argument("--current", default=DEFAULT_CURRENT_JSON, help="Path to current.json")
    parser.add_argument("--write", action="store_true", help="Actually write changes (default: report-only)")
    parser.add_argument("--confirm-token", help="Confirmation token: ENABLE_YUANBAO_DJ_BIO_ENRICHMENT_YYYYMMDD")
    parser.add_argument("--mode", choices=["merge", "replace"], default="merge",
                        help="Merge (append to existing) or replace fields")
    args = parser.parse_args()

    # Resolve paths
    current_path = os.path.abspath(args.current)
    input_path = os.path.abspath(args.input)

    if not os.path.exists(current_path):
        print(f"[patch] ERROR: current.json not found: {current_path}")
        sys.exit(1)

    if not os.path.exists(input_path):
        print(f"[patch] ERROR: input file not found: {input_path}")
        sys.exit(1)

    # Verify confirm token if writing
    if args.write:
        if not args.confirm_token:
            print("[patch] ERROR: --write requires --confirm-token")
            print("[patch] Use: --confirm-token ENABLE_YUANBAO_DJ_BIO_ENRICHMENT_YYYYMMDD")
            sys.exit(1)
        if not CONFIRM_TOKEN_RE.match(args.confirm_token):
            print(f"[patch] ERROR: Invalid confirm token format: {args.confirm_token}")
            print("[patch] Expected: ENABLE_YUANBAO_DJ_BIO_ENRICHMENT_YYYYMMDD")
            sys.exit(1)

    # Load data
    current = load_json(current_path)
    enrichments_data = load_json(input_path)
    enrichments = enrichments_data.get("enrichments", enrichments_data.get("items", []))

    if not isinstance(enrichments, list):
        print("[patch] ERROR: Input must have 'enrichments' or 'items' array")
        sys.exit(1)

    print(f"[patch] Current: {len(current.get('items', []))} items")
    print(f"[patch] Enrichments: {len(enrichments)} entries")
    print(f"[patch] Mode: {'WRITE' if args.write else 'REPORT-ONLY (dry run)'}")
    print(f"[patch] Strategy: {args.mode}")
    print()

    # Build item index
    items = current.get("items", [])
    item_by_id = {}
    for i, item in enumerate(items):
        item_by_id[item.get("id", "")] = (i, item)

    # Process enrichments
    patched = 0
    skipped = 0
    validation_errors = []
    details = []

    for ei, enrichment in enumerate(enrichments):
        item_id = enrichment.get("item_id", enrichment.get("id", ""))
        if not item_id:
            print(f"[patch] Entry {ei}: SKIPPED (no item_id)")
            skipped += 1
            continue

        if item_id not in item_by_id:
            print(f"[patch] {item_id}: SKIPPED (not found in current.json)")
            skipped += 1
            continue

        idx, item = item_by_id[item_id]

        # Validate enrichment
        errors = validate_enrichment(enrichment)
        if errors:
            for err in errors:
                print(f"[patch] {item_id}: VALIDATION ERROR: {err}")
            validation_errors.append({"item_id": item_id, "errors": errors})
            skipped += 1
            continue

        # Report what would change
        changes = []
        for key in ALLOWED_ENRICHMENT_KEYS:
            if key in enrichment:
                old = item.get(key)
                new = enrichment[key]
                if isinstance(new, list):
                    changes.append(f"  {key}: {len(old) if isinstance(old, list) else 0} → {len(new)} items")
                elif isinstance(new, dict):
                    changes.append(f"  {key}: {len(old) if isinstance(old, dict) else 0} → {len(new)} keys")
                elif isinstance(new, str):
                    old_len = len(str(old or ""))
                    changes.append(f"  {key}: {old_len} → {len(new)} chars")

        detail = {
            "item_id": item_id,
            "title": item.get("title", item.get("title_display", "")),
            "changes": changes,
            "patched": False,
        }

        if changes:
            print(f"[patch] {item_id}: {item.get('title', '?')[:60]}")
            for c in changes:
                print(c)

        if args.write:
            changed = patch_item(item, enrichment, args.mode)
            if changed:
                detail["patched"] = True
                patched += 1
            else:
                print(f"  (no actual changes)")
        elif changes:
            patched += 1

        details.append(detail)

    # Handle validation errors
    if validation_errors:
        print(f"\n[patch] {len(validation_errors)} VALIDATION ERRORS (not patched):")
        for ve in validation_errors:
            print(f"  {ve['item_id']}: {'; '.join(ve['errors'])}")

    # Summary
    print(f"\n[patch] SUMMARY: {patched} would patch, {skipped} skipped, "
          f"{len(validation_errors)} validation errors, {len(items)} total items")

    if args.write and patched > 0:
        # Create backup
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak_path = current_path + f".bak.{timestamp}"
        shutil.copy2(current_path, bak_path)
        print(f"[patch] Backup: {bak_path}")

        # Update metadata
        current["generated_at"] = datetime.now(timezone.utc).isoformat()
        current.setdefault("incremental_merge", {})
        current["incremental_merge"]["last_yuanbao_enrichment_at"] = \
            datetime.now(timezone.utc).isoformat()
        current["incremental_merge"]["yuanbao_enrichment_token"] = args.confirm_token

        # Write
        save_json(current_path, current)
        print(f"\n[patch] ✓ Patched {patched} items successfully")

        # Verify
        verify = load_json(current_path)
        verify_items = verify.get("items", [])
        verified = sum(1 for i in verify_items
                       if i.get("dj_bio_lines") or i.get("artist_profiles"))
        print(f"[patch] ✓ Verification: {verified} items have yuanbao enrichment fields")
    elif args.write:
        print("\n[patch] No changes to write")
    else:
        print(f"\n[patch] Report-only mode. Use --write --confirm-token <token> to apply.")


if __name__ == "__main__":
    main()
