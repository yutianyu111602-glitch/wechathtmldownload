# Atlas Outlink Search Quality Gate

Generated: 2026-05-21 20:28 CST

## Lifecycle And Current Authority

Status: `historical-or-evidence` / `reference` / `verify-before-use`.

This file is a 2026-05-21 Atlas outlink quality-gate note. It remains useful for the report-only quality shape of an outlink worker lane, especially the rule that graph acceptance is not the success criterion and that `accepted_for_graph`, `identity_proof`, and `graph_write_allowed` counts must stay `0` until later gates.

Current runtime authority is not this file. Read `..\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` and `..\..\reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md` first.

Current verified state as of the 2026-05-22 closeout:

- public-search is `COMPLETE`, with `246,024 / 246,024` processed and `0` remaining.
- full Post-Filter was generated at `2026-05-22T10:36:47+08:00`.
- reduced review queue is `27`; filtered candidates are `349`; quarantine rows are `245,653`.
- Layer D is dry-run only over the first `20 / 27` review rows.
- graph-entry flags remain blocked: `accepted_for_graph=0`, `identity_proof=true` hits `0`, and `graph_write_allowed=true` hits `0`.

The older statement below that "the full-scale run is blocked by public-search not yet complete" is historical 2026-05-21 context. It must not be copied as current status.

## Current Quality Judgment

`WARN, can continue`.

Reason:

- The external outlink route is correct and code-aligned.
- The existing HTTP outlink runner has useful tests and report-only safety.
- The full-scale run is blocked by public-search not yet complete.
- OpenCLI/Camofox generic fetch modes are not implemented for the new queue.
- Several handoff/report files are local untracked artifacts unless packaged/committed.

## What Counts As Success

For this worker lane, success is not graph acceptance.

Success means:

- reduced queue input was used
- high-value external links were extracted
- sensitive query keys were sanitized
- local/private/login/action links were rejected
- errors were captured instead of retried forever
- all graph-write flags stayed false
- summaries include exact counts

## What Is Not Success

These are not success criteria:

- "Many links found" without source rows and summary counts
- Maigret hits without direct source context
- OpenCLI title/bio alone
- Linktree link alone
- SoundCloud/Mixcloud/RA/Bandcamp page alone
- LLM text without later gate acceptance

## Required Summary Fields

Each batch summary should report:

- input rows
- selected profile rows
- fetched rows
- aggregator pages fetched
- outlink rows
- high-value follow-up rows
- error rows
- sanitized URL count if available
- accepted_for_graph count, expected `0`
- identity_proof count, expected `0`
- graph_write_allowed count, expected `0`

## Review Priority

Prioritize outlinks in this order:

1. Linktree or similar aggregator page from official-looking Instagram/profile source.
2. SoundCloud / Mixcloud / Bandcamp audio collection, mix, track, label, artist pages.
3. RA / event / venue / lineup pages.
4. Artist/label official website pages.
5. YouTube channel/video pages where name context matches.
6. Social crosslinks only as supporting evidence, not proof.
