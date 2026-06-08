# Atlas Outlink Search — Multi-Strategy Deep Research Plan

Generated: 2026-05-21 21:25 CST
Scope: Instagram cookie-login search + Maigret username discovery + Instagram bio outlinks
+ Camofox verification + fixed-site direct search → unified review queue

## Lifecycle And Current Authority Note

Status: `historical-or-evidence` / `reference` / `verify-before-use`.

This file is a 2026-05-21 multi-strategy research plan for the Atlas social-search
back half. It is useful for understanding the proposed Maigret, Instagram,
OpenCLI, fixed-site, Camofox, and outlink-expansion layering, plus the intended
report-only safety rules.

Do not treat this file as current runtime state or execution authorization. Its
`~890` reduced-queue estimate, `Public-search RUNNING (74.2%, ETA ~6.9h)`
prerequisite gate, Instagram logged-in search work items, OpenCLI/Camofox fetch
mode additions, generic Camofox adapter task, and batch-duration table are old
research-plan context.

Current authority is `docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` plus
`reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`.
Current verified state is public-search `COMPLETE`, processed
`246,024 / 246,024`, `missing_unique_entity_search_ids=0`, full Post-Filter
generated at `2026-05-22T10:36:47+08:00`, reduced review queue `27`, filtered
candidates `349`, quarantine `245,653`, and Layer D dry-run only `20 / 27`.
`accepted_for_graph`, `identity_proof`, and `graph_write_allowed` remain blocked
until human acceptance and separate staged-promotion authorization.

## Strategy Overview

```
Post-Filter reduced queue (~890 entities)
│
├─[L1] Maigret Username Discovery ────→ candidate usernames per entity
│   (Docker :15051, 600+ sites)
│
├─[L2] Instagram Login Search + Bio Extraction ──→ Instagram profiles + bio outlinks
│   (OpenCLI profile ejk3c3qe, logged-in session)
│
├─[L3] Fixed-Site Direct Search ──→ platform-specific profile URLs
│   (HTTP + Scrapling: RA, SoundCloud, Bandcamp, Mixcloud, YouTube)
│
├─[L4] Camofox Verification ──→ rendered profile pages, second-hop anchors
│   (Camofox :9377, anti-bot/render fallback)
│
└─[L5] Outlink Expansion ──→ Linktree → SoundCloud/Bandcamp/Mixcloud/RA/YouTube
    (HTTP + OpenCLI + Camofox, second-hop queue)
```

### Execution Environment

| Component | Runs on | Access via |
|-----------|---------|------------|
| Python pipeline scripts | WSL (/mnt/c/...) or Windows | python3 scripts/*.py |
| Maigret | Docker (Windows) | HTTP 127.0.0.1:15051 ✅ |
| OpenCLI | Windows (npm global) | cmd.exe /c opencli ... |
| Camofox | Windows (service) | HTTP 127.0.0.1:9377 (Windows side) |
| Scrapling | Windows (isolated venv) | cmd.exe /c scrapling.cmd ... |

## L1: Maigret Username Discovery

### Goal
For each entity name, find social media usernames across 600+ sites. Focus on:
Instagram, SoundCloud, Bandcamp, Mixcloud, RA, YouTube, Linktree, Twitter/X, Bilibili, Douban.

### Input
Post-Filter reduced queue: `entity_public_search_review_queue.jsonl`

### Command (from WSL or Windows)
```powershell
cd C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

# Build Maigret candidate list from reduced queue
python scripts\build_graph_maigret_candidates_from_seed_queue.py `
  --review-queue reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl `
  --out-dir reports\atlas_maigret_full_candidates_20260521

# Run Maigret against candidates (batch 50 handles at a time)
python scripts\run_maigret_http_canary.py `
  --base-url http://127.0.0.1:15051 `
  --candidates reports\atlas_maigret_full_candidates_20260521\maigret_candidates.jsonl `
  --out-dir reports\atlas_maigret_full_run_20260521 `
  --limit 50 `
  --top-sites 30
```

### Output
- `maigret_candidates.jsonl` — handle seed list
- `maigret_results.jsonl` — discovered usernames + platform URLs
- `maigret_errors.jsonl` — failed queries

### Quality Gate
- Maigret output is `candidate_only_not_identity_proof`
- Each hit must be validated by L2 (Instagram profile) or L3 (fixed-site)
- Do not treat Maigret hits as accepted evidence

## L2: Instagram Login Search + Bio Outlink Extraction

### Rationale
Instagram is the primary social profile hub for electronic music artists/DJs/clubs.
A logged-in browser session can:
1. Search Instagram for artist/club names
2. Read public profile pages (bio, display name, follower count)
3. Extract bio external links → SoundCloud, Bandcamp, Linktree, mixtape/event links

### Current Capability
`opencli_social_profile_evidence.py` already:
- Uses OpenCLI browser profile `ejk3c3qe` (Instagram logged in)
- Navigates to Instagram profile URLs
- Extracts: title, bio text, display name, external links, image hash
- Unwraps Instagram redirect URLs (l.instagram.com → real URL)
- Filters private/action paths, generic hosts, login links
- Supported platforms: Instagram, Linktree, SoundCloud, Bandcamp

### Gap: No Instagram Search Function
The current script takes profile URLs as input, not artist names to search.
We need to add an **Instagram search → profile matching** step.

### Proposed Flow
```text
entity_name + city/context
  → OpenCLI: opencli --profile ejk3c3qe browser stage7-social open "https://www.instagram.com/{search_query}/"
  → extract search results (profile handles, display names, follower counts)
  → match against entity aliases + Maigret usernames
  → for matched profiles: navigate to profile page
  → extract bio, external links, profile metadata
  → feed bio outlinks into L5 (outlink expansion)
```

### Implementation Options

**Option A: New script** `search_instagram_profiles_opencli.py`
- Takes entity names from review queue
- Uses OpenCLI to search Instagram
- Returns matched profile URLs + bio outlinks

**Option B: Extend existing** `opencli_social_profile_evidence.py`
- Add `--search-mode` flag
- Add Instagram search result extraction to PAGE_EVAL_JS
- Pipe results into existing profile reading code

**Recommendation: Option B** — extend the existing script to minimize code duplication.

### Browser-Session Safety Rules
- ✅ Allowed: use existing browser session to read public profile pages
- ✅ Allowed: use existing browser session to search Instagram
- ❌ Forbidden: export/print/persist cookie values
- ❌ Forbidden: read browser credential stores
- ❌ Forbidden: mutate accounts (follow, like, message)
- ❌ Forbidden: capture private/follower-only content

## L3: Fixed-Site Direct Search

### Goal
Search specific platforms directly for artist/club profiles, bypassing general web search noise.

### Platforms & Search Methods

| Platform | Search URL Pattern | Method | Priority |
|----------|-------------------|--------|----------|
| Resident Advisor | `https://ra.co/search?term={name}` | HTTP GET → parse results | HIGH |
| SoundCloud | `https://soundcloud.com/search?q={name}` | HTTP GET → parse | HIGH |
| Bandcamp | `https://bandcamp.com/search?q={name}` | HTTP GET → parse | HIGH |
| Mixcloud | `https://www.mixcloud.com/search/?q={name}` | HTTP GET → parse | MED |
| YouTube | `https://www.youtube.com/@YouTube/search?query={name}` | HTTP/Scrapling | MED |
| Beatport | `https://www.beatport.com/search?q={name}` | HTTP GET | LOW |
| Discogs | `https://www.discogs.com/search/?q={name}` | HTTP GET | LOW |
| Bilibili | `https://search.bilibili.com/all?keyword={name}` | HTTP GET | MED |

### Implementation

**New script**: `search_fixed_site_profiles.py`
```powershell
python scripts\search_fixed_site_profiles.py `
  --review-queue reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl `
  --out-dir reports\atlas_fixed_site_profiles_20260521 `
  --platforms ra,soundcloud,bandcamp,mixcloud,youtube `
  --timeout-sec 15 `
  --sleep-sec 0.5
```

Output:
- `fixed_site_profile_candidates.jsonl` — matched profile URLs per platform
- `fixed_site_search_errors.jsonl` — failed queries
- `fixed_site_profile_summary.json` — counts per platform

### Quality Rules
- RA artist pages: must have events/discography, not just search results
- SoundCloud profiles: must have tracks/playlists, not empty accounts
- Bandcamp: must have music/merch, not empty artist pages
- Only accept URLs with actual content indicators

## L4: Camofox Verification (Anti-Bot / Render Fallback)

### When To Use
- HTTP search returns 403/429/captcha
- Scrapling cannot extract content from JavaScript-rendered pages
- Instagram/RA/SoundCloud blocks headless HTTP
- Need to verify profile authenticity with full page render

### Current Capability
Camofox service is healthy on `127.0.0.1:9377` (Windows side):
- Browser connected and running
- Supports page navigation + screenshot + DOM extraction via HTTP API
- Existing scripts: `crawl_radio_camoufox.py`, `crawl_soundcloud_camoufox.py` (platform-specific)

### Gap: No Generic Atlas Adapter
Need a generic adapter:
- Input: URL + entity context
- Output: rendered title, visible text, anchors, canonical URL, screenshot path

### Implementation
Create generic Camofox adapter or extend existing script:

```powershell
python scripts\verify_profile_camofox.py `
  --input reports\atlas_social_profile_outlinks_errors.jsonl `
  --out-dir reports\atlas_camofox_verify_20260521 `
  --limit 50 `
  --timeout-sec 30
```

### Resource Policy
- Max 50-100 pages per batch (browser is heavy)
- Sleep 2-3 seconds between pages
- Keep browser tab count low
- Close tabs after extraction

## L5: Outlink Expansion (Second-Hop)

### Goal
From all discovered profile pages (Instagram, Linktree, SoundCloud, etc.), follow outbound links to find:
- Second-hop music platforms (Instagram bio → Linktree → SoundCloud/Bandcamp)
- Event pages, mixtapes, label sites, artist homepages

### Current Capability
`expand_atlas_social_profile_outlinks.py` already handles:
- Instagram → Linktree → SoundCloud/Mixcloud/RA/Bandcamp/YouTube
- Profile URL discovery from search results
- Link classification: audio_profile, audio_track, mix_candidate, event, social_crosslink
- Token/sensitive key sanitization

### Enhancement: Add OpenCLI + Camofox Fetch Modes
Currently only `dry-run` and `http` modes. Need:
- `--fetch-mode opencli` — uses OpenCLI browser session for rendered pages
- `--fetch-mode camofox` — uses Camofox for anti-bot pages
- Keep `--fetch-mode http` as cheap first pass

## Unified Pipeline Execution

### Phase 0: Prerequisite Gates (current)
- [x] Public-search RUNNING (74.2%, ETA ~6.9h)
- [ ] Public-search COMPLETE → run full Post-Filter
- [ ] Post-Filter output validated

### Phase 1: Parallel Discovery (after Post-Filter)
```
┌─ L1: Maigret (batch 50, ~10 min) ────────→ username candidates
├─ L3: Fixed-Site Search (batch 100, ~5 min) → platform profile URLs
└─ L2: Instagram Search (batch 20, ~15 min) ─→ Instagram profiles + bio outlinks
```

### Phase 2: Profile Verification
```
├─ L2b: OpenCLI Instagram profile reads → bio links
├─ L4: Camofox fallback for blocked pages
└─ L5: Outlink expansion (all discovered URLs)
```

### Phase 3: Unified Review Queue
```
All outputs → normalize schema → rule adjudication → human gate
```

## Required Code Work (Priority Order)

1. **L2: Instagram search + bio extraction** (extend opencli_social_profile_evidence.py)
   - Add `--search-mode` with Instagram search
   - Extract search results (handles, display names)
   - Match against entity aliases + Maigret usernames
   - Pipe matched profiles into existing PAGE_EVAL_JS extraction

2. **L3: Fixed-site direct search** (new script)
   - Search RA, SoundCloud, Bandcamp, Mixcloud, YouTube
   - Parse results for profile URLs
   - Score matches by content indicators

3. **L5: OpenCLI/Camofox fetch modes for outlink expansion**
   - Add `--fetch-mode opencli` and `--fetch-mode camofox`
   - Reuse existing DOM/anchor extraction code

4. **L4: Generic Camofox adapter** (extend or new)
   - Single-page URL → rendered content + anchors
   - Integrate with outlink expansion pipeline

5. **Maigret base URL fix**
   - Update default from stale :5050 to current :15051

6. **Unified evidence schema**
   - Normalize fields across all layers
   - Consistent graph-write flags (all false)

## Batch Policy (Multi-Strategy)

| Layer | Batch Size | Sleep | Priority | Est. Duration |
|-------|-----------|-------|----------|---------------|
| L1 Maigret | 50 handles | 0.5s | Idle | ~10 min/batch |
| L2 Instagram search | 20 profiles | 2.0s | Idle | ~15 min/batch |
| L3 Fixed-site HTTP | 100 URLs | 0.5s | Normal | ~5 min/batch |
| L4 Camofox verify | 50 pages | 3.0s | Idle | ~20 min/batch |
| L5 Outlink expand | 500 rows | 0.5s | Normal | ~10 min/batch |

## Safety Rules (Unchanged)

- All graph-write flags remain `false`
- No writing to Neo4j/Qdrant/SQLite/mem0/agentmemory
- No cookie/token export, print, or persist
- No browser credential-store reads
- No account mutation
- No private/follower-only page capture
- Report-only outputs
