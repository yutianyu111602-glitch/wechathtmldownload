# Atlas Graph Full Entity Profile Rollup

Date: 2026-05-22

## Problem

The Atlas graph database already contains full-scale rows, but the first graph workbench behaved like a small article-neighborhood viewer. A club or DJ such as `OIL`, `DADA昆明`, or `MaFoL` can appear across hundreds or thousands of source articles, while `/atlas/graph` previously showed only the seed article and a bounded local graph window.

This looked like the database was not fully loaded.

## Decision

Do not push the full `1.5M+` entity graph into the browser. Keep the raw SQLite dark and read-only, then expose a per-entity full profile rollup:

- full exact-name counts from indexed `entities.name`;
- bounded but weighted source-article window for interactive use;
- source account / club rollups;
- historical event sample;
- venue / city rollups;
- collaborator and organization rollups from same-source entities plus event participants / organizers;
- public profile candidates from accepted asset links and identity-review rows;
- no bulk export, no raw DB path, no graph/vector/SQLite writes.

## API

`GET /api/v1/stage7/graph/profile`

Parameters:

- `q`: entity name, for one-box search follow-up.
- `id`: public entity id, preferred after clicking a graph node.
- `limit`: general result cap.
- `sourceLimit`: source-article rollup window. Default `2000`, max `20000`.
- `eventLimit`, `collaboratorLimit`, `venueLimit`, `articleLimit`: per-section display caps.

Response schema: `stage7_atlas_api.graph_entity_profile.v1`.

Important fields:

- `canonical`: display name, primary type, public id, graph node id.
- `summary.exactEntityRows`: full exact-name entity row count.
- `summary.sourceArticleCount`: full distinct source article count.
- `summary.loadedSourceArticles`: public interactive rollup window size.
- `sources.accounts`: top source accounts / clubs.
- `history.events`: historical events sample.
- `history.venues`: top places.
- `relationships.collaborators`: co-performers / same-article people.
- `relationships.organizations`: labels, collectives, venues, organizer-like entities.
- `publicProfiles`: accepted asset links and identity-review candidates.

## Network Logic

### Search DJ

`DJ name -> exact entity profile -> historical source articles -> historical events -> event places -> co-performers -> labels / organizations -> public profile candidates`

Example: `MaFoL` returns source accounts such as `All俱乐部`, `DIRTY HOUSE 得体`, `SHCR`, collaborators such as `Masher`, `GSS`, `DaRou`, `GuangYu`, `MUYANG`, and venue/event history.

### Search Club

`club name -> exact entity profile -> all source articles from that club/account -> historical events -> repeated DJs -> related organizations -> venue/place variants`

Example: `OIL` returns full-scale counts, top account `OIL油`, historical venue variants, and frequent collaborators.

### Search Venue / City-Like Club

`venue entity -> source-account rollup -> event rollup -> resident / recurring DJs -> cross-account mentions`

Example: `DADA昆明` returns `Dada Kunming`, `Dada Bar Beijing`, `VERVO国际独立电音俱乐部` as source-account context and recurring performers such as `DJ Ozone`, `No Order`, `S&M`.

## Performance Policy

The public endpoint uses level-of-detail:

- exact counts are full;
- returned relation lists are bounded;
- default rollup window is `2000` source articles for responsiveness;
- heavy full-materialized all-entity rollups should be built offline into a sidecar serving index before public scale;
- profile endpoint has a stricter app-level rate limit than normal search.

Verified local read-model self-test:

- `12/12` seeds passed;
- exact top3 `12/12`;
- profile history `12/12`;
- graph seed p95 `51ms`;
- profile p95 `1037ms` with default `sourceLimit=2000`.

## Anti-Scrape Boundary

This profile endpoint is not a bulk export surface:

- it returns top windows, not all raw rows;
- raw SQLite remains hidden and read-only;
- `ATLAS_SQLITE_READONLY=1` keeps the service from writing the raw DB;
- response safety reports no model, vector, graph, mem0, or SQLite writes;
- `/api/v1/stage7/graph/profile` is rate-limited separately.

