# Audit: Django Backend Presence — 2026-06-10

## Conclusion

**DJANGO_BACKEND_NOT_FOUND_IN_THIS_REPO**

## Methodology

1. Searched for `manage.py`, `settings.py`, `urls.py`, `wsgi.py` — **0 results**
2. Searched for `django` in `requirements.txt`, `pyproject.toml`, `setup.py` — **no such files reference django**
3. Searched for `from django` or `import django` in all Python files — **0 results**
4. Searched for Django-related middleware, ORM, or template patterns — **0 results**

## What This Repo Actually Uses

| Layer | Technology |
|-------|-----------|
| API Server | **Node.js** (native `http` module, ESM) — `services/weekly_activity_cloudrun/src/server.mjs` |
| Data Store | **JSON files on disk** — `services/weekly_activity_cloudrun/data/current_release/` |
| Atlas DB | **SQLite** via `better-sqlite3` — `services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs` |
| Pipeline | **Python scripts** (874 scripts in `tools/stage7_rewrite/scripts/`) — standard library + requests, no Django |
| Mini-program | **WeChat Mini Program** — `apps/weekly_activity_miniprogram/` |
| Desktop | **Electron** — `desktop/` |

## Why This Matters

Previous handoff documents incorrectly referenced "Django + WeChat mini-program" as the
architecture. The correct description is:

> **Node/TypeScript pipeline + Python Stage7 scripts + CloudRun JSON-file service + WeChat mini-program + Electron desktop**

No Django migration, Django REST framework, Django admin, or Django ORM exists anywhere
in this repository.
