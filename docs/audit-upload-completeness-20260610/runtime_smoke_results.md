# Runtime Smoke Results

## Versions
- node: v24.15.0
- npm: 11.12.1
- python: Python 3.11.15

## npm scripts
60+ scripts available via 
pm run (build, process-article, archive-batch, export-llm-batch, etc.)

## Mini-program Tests (50 tests)
- 49 passed, 1 failed (data drift: date assertion)
- Failure: cacheMaxAgeMs test expects 2026-06-16, got 2026-06-25
- Root cause: test references current-week calculation, data has shifted

## CloudRun Tests
- FAILED: better-sqlite3 native module not compiled for current Node.js
- Fix: 
pm rebuild better-sqlite3`n- This is a local environment issue, not a repo problem
