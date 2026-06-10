#!/usr/bin/env python3
"""DB2 Weapons Entrypoint — dispatches to the selected weapon.
Usage: python entrypoint.py <weapon> [args...]

Weapons:
  sc_api      — SoundCloud cookie API (resolve, search, user info)
  sc_deep     — SoundCloud deep profile crawl
  ig_fission  — IG bio URL extraction
  domestic    — Bilibili/NetEase scan
  avatar      — Avatar download (spool adapter)
  expand      — Linktree/shorturl expansion (spool adapter)
  writer      — Process spool → DB2
  cache       — Seed sidecar cache
  dedup       — Build query-time dedup map
  monitor     — Health + status check
"""

import sys, os

WEAPONS = {
    "sc_api":     ("weapons.sc_api", "run"),
    "sc_deep":    ("weapons.sc_deep", "run"),
    "ig_fission": ("weapons.ig_fission", "run"),
    "domestic":   ("weapons.domestic", "run"),
    "avatar":     ("weapons.avatar", "run"),
    "expand":     ("weapons.expand", "run"),
    "writer":     ("weapons.writer", "run"),
    "cache":      ("weapons.cache", "run"),
    "dedup":      ("weapons.dedup", "run"),
    "monitor":    ("weapons.monitor", "run"),
}

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in WEAPONS:
        print(f"Available weapons: {', '.join(sorted(WEAPONS))}")
        sys.exit(1)

    weapon = sys.argv[1]
    mod_name, func = WEAPONS[weapon]
    
    sys.path.insert(0, "/opt/db2-weapons")
    mod = __import__(mod_name, fromlist=[func])
    
    # Pass remaining args to weapon
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    getattr(mod, func)()

if __name__ == "__main__":
    main()
