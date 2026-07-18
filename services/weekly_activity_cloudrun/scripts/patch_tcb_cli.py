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
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TCB_PACKAGE = "@cloudbase/cli@3.3.1"
TCB_RELATIVE_CLI = Path("node_modules/@cloudbase/cli/dist/standalone/cli.js")

OLD_SNIPPET = "options: cmdOptions,"
NEW_SNIPPET = "options: Object.assign({}, cmdOptions, envId ? { envId: envId } : {}),"

# Context required to locate the exact replacement site (avoid false positives)
CONTEXT_BEFORE = "containerPort"
CONTEXT_WINDOW = 600  # chars around the match to check for context


def npm_cache_roots() -> list[Path]:
    roots: list[Path] = []

    def add(value: str | Path | None) -> None:
        if value is None:
            return
        path = Path(value).expanduser()
        if path not in roots:
            roots.append(path)

    add(os.environ.get("NPM_CONFIG_CACHE"))
    npm = shutil.which("npm")
    if npm:
        try:
            result = subprocess.run(
                [npm, "config", "get", "cache"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode == 0 and result.stdout.strip():
                add(result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    add(Path.home() / "AppData" / "Local" / "npm-cache")
    return roots


def find_cli_js() -> Path | None:
    """Return the active pinned tcb cli.js from local install or npm's real cache."""
    local_cli = (
        Path(__file__).resolve().parents[1]
        / TCB_RELATIVE_CLI
    )
    if local_cli.exists():
        return local_cli

    for npm_cache in npm_cache_roots():
        npx_root = npm_cache / "_npx"
        if not npx_root.exists():
            continue
        for candidate in npx_root.glob(f"*/{TCB_RELATIVE_CLI.as_posix()}"):
            package_json = candidate.parents[2] / "package.json"
            try:
                package = json.loads(package_json.read_text(encoding="utf-8"))
                if package.get("version") == "3.3.1":
                    return candidate
            except (OSError, json.JSONDecodeError):
                continue
    return None


def ensure_cli_js() -> Path | None:
    path = find_cli_js()
    if path is not None:
        return path
    npm = shutil.which("npm")
    if not npm:
        return None
    print(f"Pinned {TCB_PACKAGE} is not cached; restoring it with npm exec...")
    try:
        result = subprocess.run(
            [npm, "exec", "--yes", "--package", TCB_PACKAGE, "--", "tcb", "--version"],
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print(f"WARNING: could not restore {TCB_PACKAGE}: {error}")
        return None
    return find_cli_js() if result.returncode == 0 else None


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
    if content.count(OLD_SNIPPET) == 1:
        patched = content.replace(OLD_SNIPPET, NEW_SNIPPET, 1)
        path.write_text(patched, encoding="utf-8")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check only, no modification")
    args = parser.parse_args()

    path = find_cli_js() if args.check else ensure_cli_js()
    if path is None:
        print(f"ERROR: cli.js for pinned {TCB_PACKAGE} was not found in the configured npm cache.")
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
