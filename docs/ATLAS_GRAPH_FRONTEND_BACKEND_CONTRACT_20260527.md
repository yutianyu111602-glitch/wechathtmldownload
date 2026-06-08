# Atlas Graph Frontend / Backend Contract - 2026-05-27

## Thread Alignment

- Backend logic thread: `codex://threads/019e5345-06e4-7fd2-84ca-00071e7e1ecb`
- Frontend UI thread: `codex://threads/019e64d4-067b-7953-94d8-8c424a3223fd`
- Frontend implementation entry: `C:\Users\pc\Documents\atlas\social-auto-upload\sau_frontend\src\views\Dashboard.vue`
- Backend implementation entry: `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs`

## Product Direction

- Default UI mode is readable 3D, with a separate immersive mode.
- Default user flow is family profile first, then evidence drawer, then bounded relationship roam. The browser must not start by loading a graph packet.
- The page is user-facing. Do not show raw LDR prompts, source packs, DB paths, field maps, or internal pipeline language.
- The page may say full database, but runtime must mean full read-only indexed serving coverage plus bounded graph packets. Do not return full database JSON to the browser.
- Main relationship metric is relationship score (`relationshipScore` / `关系分`). Same-event count is evidence detail only and must not be the primary UI label.
- Entity aliases such as `Loopy`, `Loopy俱乐部`, `loopy Club`, `杭州 Loopy`, `ALL`, `ALL Club`, `ALL俱乐部` should resolve through backend alias expansion and LLM sidecar review, not frontend regex.

## User Product Endpoints

- `GET /api/v1/atlas/family/profile?q=<query>|id=<id>`
  - Returns `atlas.family_profile.v1`.
  - Required top-level fields: `canonical`, `trust`, `stats`, `sections`, `navigation`, `safety`.
  - Candidate/social/avatar/merge/sound-system values must carry explicit state and must not be emitted as public facts.
- `GET /api/v1/atlas/family/relationships?id=<id>&limit=50`
  - Returns `atlas.family_relationships.v1`.
  - Primary metric is `relationshipScore`.
  - `sameEventCount` is allowed only under `metrics`, not as the main row label.
- `GET /api/v1/atlas/evidence/:sourceRefId`
  - Returns `atlas.evidence.v1` with public-safe source metadata, snippet, support fields, and safety flags.
  - Must not emit raw local paths, raw source URLs, source DB paths, source hashes, cookies, prompts, or internal candidate ids.

## Required Frontend Endpoints

- `GET /api/v1/stage7/overview?sampleLimit=500`
  - Returns full serving DB counts and bounded browsing surfaces.
  - Required counts: `entities`, `events`, `dj_relation_edges_directed`, `evidence_refs`, `search_documents`.
- `GET /api/v1/stage7/graph/seed?q=<query>&limit=700&lod=detail`
  - Returns a bounded focus graph for search.
  - Backend may cap packet size, but response must remain useful and non-empty for known seeds.
- `GET /api/v1/stage7/graph/expand?nodeId=<nodeId>&depth=2&limit=700&lod=detail`
  - Alias of `/api/v1/stage7/graph/subgraph`.
  - Must accept frontend node ids such as `entities:dj:<id>`.
- `GET /api/v1/atlas/session/status`
  - Local dev may allow session-free access.
  - Public deployment must gate stage7 APIs before serving dark database packets.
- `POST /api/v1/atlas/session`
  - Turnstile-backed session creation. Do not expose secret values.

## Graph DTO Compatibility Fields

Nodes must keep canonical Atlas fields and also expose frontend-friendly aliases:

- Canonical: `id`, `kind`, `label`, `subtype`, `role`, `metrics`, `publicState`, `visual`
- UI aliases: `name`, `type`, `score`, `events`, `links`, `timeline`

Edges must keep canonical Atlas fields and also expose frontend-friendly aliases:

- Canonical: `id`, `source`, `target`, `kind`, `label`, `weight`, `relationshipScore`, `evidenceCount`, `sampleEvidenceIds`, `metrics`
- UI aliases: `type`, `relation`, `width`

Label rules:

- `dj_collaboration` displays as `DJ 关系`.
- `relationshipScore` displays as `关系分`.
- `sameEventCount` remains under `metrics.sameEventCount` for audit/evidence only.
- Old labels containing `同台` should be rewritten in output DTOs before they reach the browser.

## Safety Contract

- No raw Atlas DB path in public responses: `retrieval.dbPath` must be empty unless explicitly local-debug enabled.
- No raw DB download, full graph dump, export, or bulk route exposed to public browser clients.
- No production pointer update is implied by local UI or backend tests.
- LLM entity merge output remains report-only sidecar until separately reviewed and promoted.

## Verified Local Smoke

Local server: `http://127.0.0.1:18988`

- `overview?sampleLimit=500`: `entities=53555`, `events=508049`, `dj_relation_edges_directed=701396`, `evidence_refs=130591`
- `seed?q=MaFoL&limit=700&lod=detail`: `nodes=71`, `edges=88`, first node `MaFoL`, `score=3`, `events=0`, `links=68`
- `seed?q=Loopy俱乐部&limit=700&lod=detail`: seed `Loopy`, `aliasExpanded=true`, non-empty graph
- `expand?nodeId=entities:dj:<MaFoL>&depth=2&limit=700&lod=detail`: `notFound=false`, non-empty graph
- Public-safe response smoke: `retrieval.dbPath=""`
