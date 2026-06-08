# PRD: Atlas Route / External Link / DB Consolidation

Updated: 2026-05-31 10:58 CST

## Problem

Atlas / HUAIDJ Weekly accumulated multiple independently developed modules: weekly pipeline, OpenClaw, CloudRun, mini-program, Stage7 Atlas, source evidence, external identity/social evidence, and database/export scripts. Their field names, source boundaries, and deployment states are not centralized enough for safe autonomous production work.

## Goals

- Create a single inventory and control surface for routes, pipelines, outlinks, and databases.
- Normalize field contracts before further runtime changes.
- Restore and preserve mobile Atlas history/relationship behavior.
- Add rights-safe mixtape / music outlink support.
- Update SSOT and handoff after each verified story.

## Non-Goals

- Do not turn Atlas into a scoring/review product.
- Do not cache copyrighted audio or bypass platform rights.
- Do not invent coordinates or venue addresses.
- Do not submit WeChat review without a specific review packet.

## Users

- Internal operator running Codex/OpenClaw/CloudBase pipeline.
- HUAIDJ mini-program users browsing weekly events and Atlas history.
- Future agents taking over long-running Atlas maintenance.

## Acceptance

- S1 inventory script and docs pass tests and generate report.
- S2 field/database contract identifies DB/data package owners and canonical fields.
- S3 coordinate/source matrix identifies accepted, provider-confirmed, and blocked rows.
- S4 mobile outlink/mixtape UX uses original links and passes frontend tests.
- S5 deployment/upload path runs only when there is a verified runtime/data delta.
- S6 SSOT/handoff is updated with exact resume pointers.
- S25/S26 relation integrity is enforced locally before future deploy/upload claims through `npm run weekly:deploy-upload:preflight`.
- S27 DJ Interview has a local private Markdown/JSON/JSONL intake path before public DB/graph promotion.

Detailed current story status is maintained in `04-prd.json`.
