# Next Phase Master Plan S117

Updated: 2026-06-01 16:25 CST

Status: `CURRENT_AUTHORITY`

Scope: 三数据库合一、外链长跑重启、小程序前后端更新、抓取管线优化。This is a design-and-execution control plan. It does not authorize production DB writes, cookie reads, deploys, uploads, WeChat review submission, or paid/model-heavy runs by itself.

## Current Ground Truth

- Latest longrun story is S116: `reports\WEEKLY_ATLAS_RELATION_IDENTITY_SOURCE_REF_DISPOSITION_WORKBENCH_S116_20260601.md`.
- S116 is report-only. It produced a source-ref / disposition / field-preservation workbench for 24 selected relation/identity rows, with `ready=0`, `approved_write_gate=0`, and `write_gate_candidates=0`.
- The main unresolved blockers remain:
  - coordinate/latest-claim blocker,
  - DB3 relation/identity write gate blocker,
  - DevTools rendered coverage blocker.
- The mini-program CloudBase lane has useful new state from the CloudBase thread: CloudBase AI can run on `hunyuan-v3 / hy3-preview`; CloudBase Database is suitable as a hot cache layer, not as the graph/source authority.
- The weapon catalog is available at `\\wsl.localhost\Ubuntu\home\pc\reports\WEAPON_CATALOG_20260601.md`. The active Codex-side router is `C:\Users\pc\.codex\skills\external-link-db2-arsenal\SKILL.md`.
- OpenHuman subagent dispatch was attempted from this thread but failed with `Transport closed`; subagent use is optional and cannot be a blocker for the next local slices.

## Product Direction

The product should move from "weekly events only" toward a public evidence graph for underground music:

- show high-confidence external links first,
- keep original-source jump-out behavior,
- prioritize Instagram, mixtape/music-platform, radio, video, and official/source article links,
- avoid downloaded audio/video hosting, proxying, or hidden re-publication,
- make source/evidence visible enough for trust without leaking raw private URLs or local paths,
- preserve the anti-commercial archive-first tone.

## Database Strategy

Use a three-layer model instead of trying to force every table into one store.

| Layer | Role | Current Anchor | Next Rule |
| --- | --- | --- | --- |
| DB1 source/raw | Immutable source history, article/event/entity raw truth | `atlas.sqlite` class source DBs | Read-only by default; only explicit source/raw write gates may mutate narrow fields. |
| DB2 serving/read model | Fast public/CloudRun read model, graph/search/profile windows | `atlas_serving.sqlite` candidates | Build from DB1 + sidecars + accepted DB3 deltas; every candidate gets count/leak/search/graph validation. |
| DB3 miniapp/projection | User-facing mobile projection and relation-friendly profile view | mini-program sqlite / CloudBase hot cache | Treat as projection/cache. Do not use DB3 convenience fields as source truth without field-preservation readback. |

DB2 incremental outlinks should enter as a sidecar first:

1. collect external-link candidates into a no-write outlink evidence sidecar;
2. normalize into `source_ref`, `external_music_links`, and profile-link candidate tables;
3. score confidence and copyright safety;
4. project only high-confidence public-safe links into DB2 serving candidate;
5. expose only approved link categories to mini-program;
6. keep all raw crawl artifacts out of public packages.

## Main Workstreams

### A. External-Link Longrun Recovery

Goal: restart external-link crawling without repeating previous file-lock and session problems.

Design:

- Build a lock-aware queue runner before any real crawl wave.
- Use atomic claim files or SQLite lease rows with stale-lock detection.
- Add per-platform cache directories keyed by normalized URL/handle and content fingerprint.
- Always start with dry-run/platform smoke over tiny fixtures.
- Keep cookie use manual and explicit:
  - accepted helper: Chrome extension `Export cookie JSON file for Puppeteer`, ID `nmckokihipjgplolmcmjakknndddifde`;
  - Codex may verify path/domain/count/expiry metadata only;
  - values must never be printed, committed, stored in docs, or written to memory.

First tools:

- Maigret for username breadth.
- Scrapling / Lightpanda / Chrome DevTools for rendered public fallback.
- Platform tools only when the target platform is clear.
- Direct DeepSeek only for text extraction/adjudication when rule-based parsing is insufficient.

### B. Mini-Program External-Link Display

Goal: show high-confidence external links in the mini-program without weakening copyright/source boundaries.

Display order:

1. official/source article,
2. Instagram,
3. mixtape/music-platform,
4. radio,
5. video,
6. other public profile.

Rules:

- Jump to original URL when public and safe.
- For internal source hashes, keep source page routing; do not fabricate WeChat URLs.
- Do not embed or download audio/video.
- Add confidence labels only where they help users avoid bad links.
- Hide low-confidence candidates behind no public UI until reviewed.

Frontend surfaces:

- artist profile,
- venue profile,
- detail page source block,
- saved page link summaries,
- source page evidence detail.

Backend surfaces:

- add public-safe external link fields to current weekly/Atlas profile APIs;
- keep raw artifact paths and private source refs server-side only;
- CloudBase Database can cache current-week high-confidence links after CloudRun produces the package.

### C. Three-Database Unification And Performance

Goal: make DB1/DB2/DB3 behave like one product system without pretending they are one physical database.

Plan:

- Define stable IDs and field contracts across source/raw, serving, and miniapp projection.
- Add an incremental build manifest that records every input DB, sidecar, queue, script version, and row count.
- Use read-only SQLite smoke with `mode=ro&immutable=1` for candidates.
- Add performance gates for search, graph seed, artist/venue/profile lookup, and mini-program current-week hot paths.
- Keep CloudBase Database as a hot cache for current-week and AI summaries, not as the Atlas graph authority.

Acceptance:

- row-count drift is zero or explained;
- leak scan passes;
- search/profile/graph smoke passes;
- mini-program API schema compatibility passes;
- performance budget is recorded before promotion.

### D. Pipeline Optimization

Goal: improve the whole path from OpenClaw download to preprocessed package to DB candidate to mini-program.

Focus:

- file-lock-safe OpenClaw/outlink queue;
- Docker/exporter login-state diagnosis without dumping secrets;
- QR/login/API progress capture as structured state;
- poster OCR and lineup extraction with chunked inputs, not one oversized prompt;
- music label / 厂牌 and DJ bio recognition as a separate report-only lane before DB2/DB3 projection, so labels, crews, promoters, venues, radio shows, and DJs are not merged into one identity type;
- model routing:
  - deterministic regex/DOM/OCR first,
  - DeepSeek Flash for cheap batch classification,
  - DeepSeek Pro for hard adjudication,
  - MiMo/multimodal only for poster or image evidence,
  - CloudBase Hunyuan for mini-program AI/user-facing summary where its free quota applies.

## Execution Stories

| Story | Name | Purpose | Mutability | Stop Gate |
| --- | --- | --- | --- | --- |
| S117 | External-link and DB inventory workbench | Build a no-write inventory of existing outlink scripts, queues, sidecars, locks, cache dirs, and weapon mappings. | report-only | Missing authority, secret-only path, or unbounded disk requirement. |
| S118 | Lock/cache runner design and fixture smoke | Add a tiny lock/cache harness for external-link dry-runs. | code + tests, no production data write | Any cookie/profile requirement. |
| S119 | DB2 incremental outlink sidecar contract | Define sidecar schema and projection gates for public-safe external links. | report-only then tests | Field contract conflict with DB1/DB3. |
| S120 | Mini-program link UI contract | Design and test high-confidence external-link display contract. | frontend/backend tests, no upload | DevTools rendered blocker still unresolved for release. |
| S121 | Three-DB merge/performance audit | Measure DB1/DB2/DB3 current tables, indexes, join keys, and performance risks. | read-only | Candidate DB not discoverable or too stale. |
| S122 | Poster/lineup extraction prompt and router | Split poster and lineup extraction into deterministic/OCR/LLM lanes. | report-only + tests | Model credentials or large paid run required. |
| S123 | Docker/exporter login-state diagnostic | Make Docker login/QR/API progress visible as state without exposing credentials. | read-only diagnostics | Requires interactive account action. |
| S124 | First bounded external-link crawl canary | Run a small public no-cookie canary for selected high-confidence targets. | candidate artifacts only | Anti-bot/cookie required. |
| S125A | Label/DJ bio recognition hardening | Separate music label / 厂牌 / crew / promoter / venue / DJ-person roles and require source-backed DJ bio evidence before projection or display. | report-only + tests | Entity-kind conflict or source evidence missing. |
| S125 | DB2 candidate projection smoke | Project reviewed high-confidence links into a DB2 candidate and smoke it. | report-local candidate only | Leak/performance/schema gate fails. |
| S126 | Mini-program rendered verification | Verify UI with DevTools rendered coverage after blocker cleanup. | no upload by default | DevTools environment dirty. |
| S127 | Release preflight | Re-run goal completion, deploy/upload preflight, pointer consistency, and public-safe checks. | report-only | Any hard blocker remains. |

## S117 Acceptance Criteria

S117 is done when the repo has a report-only inventory that lists:

- existing external-link, source acquisition, social, OCR, poster, lineup, Docker/exporter, cookie, and DB2-related scripts/tests;
- existing Atlas/DB sidecars and candidate DB categories without broad disk scanning;
- active weapon mappings from the local arsenal skill and WSL weapon catalog;
- lock/cache risks and proposed paths;
- first safe no-cookie canary targets;
- exact next story entrypoint.

S117 must not:

- read cookie values,
- read `.env` or credential stores,
- start Chrome profile scraping,
- run external crawls,
- mutate DB1/DB2/DB3,
- upload/deploy/review,
- run unbounded D-drive scans.

## First Execution Slice

Next action: implement S117 as a no-write inventory script/report under `tools/stage7_rewrite/scripts` and `tools/stage7_rewrite/reports`.

Suggested command shape:

```powershell
npm run weekly:external-link-db2:inventory
```

The inventory should be small and deterministic, with pytest coverage over classification and secret redaction.

## Assumption Ledger

- The user's "three databases" maps to DB1 source/raw, DB2 serving/read model, and DB3 miniapp/projection from the current DB field contract.
- "OpenGraph" in the earlier message is treated as CodeGraph unless a different tool is named later.
- Cookie export is a user-side manual helper, not a Codex permission to read browser profile storage.
- CloudBase AI quota is useful for user-facing mini-program summaries, but CloudBase Database remains a hot cache layer only.
- Subagents are optional; this run continues locally because OpenHuman subagent dispatch failed.
