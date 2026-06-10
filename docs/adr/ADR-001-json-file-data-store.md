# ADR-001: JSON File Data Store vs Database

**Date**: 2026-06-10
**Status**: Accepted

## Context

The weekly activity CloudRun service needs to serve event data to the WeChat mini-program.
We needed to choose between a database (SQLite/PostgreSQL) and static JSON files for data storage.

## Decision

Use **static JSON files on disk** as the primary data store for weekly event data.

The directory structure (`by-city/`, `by-date/`, `by-id/`) acts as a file-based index,
and `current.json` provides the full dataset for the index view.

## Rationale

1. **Read-heavy workload**: The API is almost entirely reads. Events are generated weekly
   by the Python pipeline and written once, then served many times.
2. **No relational queries**: The mini-program needs simple lookups by city, date, or ID —
   no joins, no transactions, no ad-hoc queries.
3. **Deployability**: JSON files deploy with the CloudRun container. No database provisioning,
   no connection strings, no migration scripts.
4. **Cacheability**: Each JSON file can be cached with HTTP Cache-Control headers.
   CloudRun CDN can serve files directly from cache.
5. **Simplicity**: The data store code (`dataStore.mjs`) is ~1200 lines of pure Node.js
   with no native dependencies. No ORM, no schema migrations, no connection pooling.

## Consequences

- **Positive**: Zero-config deployment, fast reads, easy debugging (just read the JSON files)
- **Negative**: Full reload required to update data (not real-time), no write API,
  file count grows with event count (~155 files per weekly pack)
- **Mitigation**: The weekly pipeline regenerates the entire pack. Cache TTL is 5 minutes.
  The `better-sqlite3` Atlas store handles the graph/query use case separately.
