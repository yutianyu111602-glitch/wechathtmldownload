---
name: db2-weapons-arsenal
description: DB2 Swarm weapons library. 10 weapons for outlink crawling, avatar, expansion, dedup.
---

# DB2 Weapons Arsenal — DeepSeek TUI Operator Skill

## Quick Start

```bash
# List all weapons
python3 entrypoint.py

# Run a weapon
python3 entrypoint.py <weapon>
```

## Weapons Catalog

| Weapon | Layer | Description | Cookie | Writes |
|--------|-------|-------------|:------:|:------:|
| `sc_api` | API | SoundCloud resolve/search/user (no client_id) | SC | No |
| `sc_deep` | Deep | SoundCloud deep profile crawl | SC | DB2 |
| `ig_fission` | Fission | IG bio URL extraction | IG | DB2 |
| `domestic` | Discovery | Bilibili/NetEase DJ scan | Bili+163 | DB2 |
| `avatar` | Media | Avatar download (spool) | SC | Spool |
| `expand` | Expand | Linktree/shorturl expansion (spool) | No | Spool |
| `writer` | DB | Process spool → DB2 | No | DB2 |
| `cache` | Cache | Seed sidecar cache | No | Cache |
| `dedup` | Quality | Build query-time dedup map | No | JSON |
| `monitor` | Ops | Health + status check | No | No |

## Safe Run Order

```bash
# 1. Always start with monitor
python3 entrypoint.py monitor

# 2. Discovery + deep
python3 entrypoint.py ig_fission &
python3 entrypoint.py sc_deep &

# 3. Expansion (runs on produced URLs)
python3 entrypoint.py expand &

# 4. Avatar + writer
python3 entrypoint.py avatar &
python3 entrypoint.py writer

# 5. Cache + dedup
python3 entrypoint.py cache
python3 entrypoint.py dedup
```

## Docker Run

```bash
docker compose -f compose.yaml --profile sc run --rm db2-weapons-sc
docker compose -f compose.yaml --profile ig run --rm db2-weapons-ig
```

## Anti-Deadlock Rules

1. All source DBs opened read-only: `file:path?mode=ro, uri=True`
2. New DBs created exclusively: `unlink()` before rebuild
3. Source hash guardian: SHA256 before/after build — mismatch = pipeline failure
4. WAL single-writer handles concurrent DB writes — not deadlock, normal serialization

## Files

```
/opt/db2-weapons/
├── entrypoint.py          # Weapon dispatcher
├── weapons/
│   ├── sc_api.py          # SoundCloud API (new, cookie-based)
│   ├── sc_deep.py         # → _legacy_wrappers
│   ├── ig_fission.py      # → _legacy_wrappers
│   ├── domestic.py        # → _legacy_wrappers
│   ├── avatar.py          # → _legacy_wrappers
│   ├── expand.py          # → _legacy_wrappers
│   ├── writer.py          # → _legacy_wrappers
│   ├── cache.py           # → _legacy_wrappers
│   ├── dedup.py           # → _legacy_wrappers
│   ├── monitor.py         # → _legacy_wrappers
│   └── _legacy_wrappers.py  # Shared wrappers
```
