#!/usr/bin/env python3
"""Re-apply the tcb CLI envId transparency patch.

The patch fixes @cloudbase/cli@3.3.1 sub-commands not forwarding envId to the SDK.
npx caches the package under a content-addressed path; the cache is rebuilt when
`npm cache clean` or a new Node/npm install runs, which silently drops the patch.
Run this script after any npm cache rebuild.

Usage:
    python scripts/patch_tcb_cli.py [--check]

    --check   Verify patch is applied without modifying the file.
"""
import argparse
import glob
import sys
from pathlib import Path

# The npx cache lives here; the hash changes only when the package lock changes.
# If the hash directory disappears, this script searches the whole npm-cache tree.
_NPX_CACHE_HINT = (
    r"C:\Users\pc\AppData\Local\npm-cache\_npx"
    r"\541eff4f486037bb"
    r"\node_modules\@cloudbase\cli\dist\standalone\cli.js"
)

OLD_SNIPPET = "options: cmdOptions,"
NEW_SNIPPET = "options: Object.assign({}, cmdOptions, envId ? { envId: envId } : {}),"

# Context required to locate the exact replacement site (avoid false positives)
CONTEXT_BEFORE = "containerPort"
CONTEXT_WINDOW = 600  # chars around the match to check for context


def find_cli_js() -> Path | None:
    """Return the path to the patched cli.js, or None if not found."""
    local_cli = (
        Path(__file__).resolve().parents[1]
        / "node_modules"
        / "@cloudbase"
        / "cli"
        / "dist"
        / "standalone"
        / "cli.js"
    )
    if local_cli.exists():
        return local_cli

    hint = Path(_NPX_CACHE_HINT)
    if hint.exists():
        return hint

    # Fallback: search entire npm-cache
    npm_cache = Path(r"C:\Users\pc\AppData\Local\npm-cache\_npx")
    if not npm_cache.exists():
        return None
    for candidate in npm_cache.rglob("@cloudbase/cli/dist/standalone/cli.js"):
        return candidate
    return None


def check_patch(content: str) -> str:
    """Return 'applied', 'missing', or 'not_found'."""
    if NEW_SNIPPET in content:
        return "applied"
    if OLD_SNIPPET in content:
        return "missing"
    return "not_found"


def apply_patch(path: Path, content: str) -> bool:
    """Apply the patch in-place; return True if successful."""
    # Find the exact replacement site using surrounding context
    idx = content.find(OLD_SNIPPET)
    while idx != -1:
        window = content[max(0, idx - CONTEXT_WINDOW): idx + CONTEXT_WINDOW]
        if CONTEXT_BEFORE in window:
            patched = content[:idx] + NEW_SNIPPET + content[idx + len(OLD_SNIPPET):]
            path.write_text(patched, encoding="utf-8")
            return True
        idx = content.find(OLD_SNIPPET, idx + 1)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check only, no modification")
    args = parser.parse_args()

    path = find_cli_js()
    if path is None:
        print("ERROR: cli.js not found in npm-cache. Run: npm exec --yes --package @cloudbase/cli@3.3.1 -- tcb --version  to re-cache, then retry.")
        return 1

    print(f"cli.js: {path}")
    content = path.read_text(encoding="utf-8")
    state = check_patch(content)

    if state == "applied":
        print("Patch already applied. Nothing to do.")
        return 0

    if state == "not_found":
        print("WARNING: Neither old nor new snippet found. cli.js version may have changed.")
        print(f"  OLD: {OLD_SNIPPET!r}")
        print(f"  NEW: {NEW_SNIPPET!r}")
        return 2

    # state == "missing"
    if args.check:
        print("Patch is NOT applied.")
        return 1

    print("Applying patch...")
    if apply_patch(path, content):
        # Verify
        new_content = path.read_text(encoding="utf-8")
        if check_patch(new_content) == "applied":
            print("Patch applied successfully.")
            return 0
        else:
            print("ERROR: Patch wrote but verify failed.")
            return 1
    else:
        print("ERROR: Could not locate replacement site (context not found). Manual patch required.")
        print(f"  File: {path}")
        print(f"  Look for: {OLD_SNIPPET!r}")
        print(f"  Replace with: {NEW_SNIPPET!r}")
        print(f"  Required nearby context: {CONTEXT_BEFORE!r}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
