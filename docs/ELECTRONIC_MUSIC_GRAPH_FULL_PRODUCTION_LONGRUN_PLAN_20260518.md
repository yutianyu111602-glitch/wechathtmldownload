# Electronic Music Atlas / Graph Full Production Longrun Plan

Updated: 2026-05-20 04:00 +08:00

Project root: `C:\code\githubstar\wechathtmldownload`.

This is the stage-reference longrun plan for the China underground/electronic-music atlas thread: **中国地下电子音乐图鉴**. It sits below `docs\ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md` and the 2026-05-20 `127,511` closeout artifacts. Treat the stage order and safety rules here as useful; treat dated counts below as historical unless the current authority docs repeat them.

## Goal

Complete the atlas production pipeline end to end, with graph/vector/network evidence as the data substrate:

1. Integrate all verified artifacts by stage.
2. Detect gaps from current reports and code facts.
3. Repair local/code/report blockers automatically.
4. Re-run or re-crawl only when evidence shows it is needed and non-duplicative.
5. Finish text vector/retrieval production lanes.
6. Finish external network/social evidence normalization and review queues.
7. Build graph candidate packs and production graph evidence with runner proof.

## Current Truth

- Latest graph source: `tools\stage7_rewrite\reports\stable_merge_all_deepseek_127490_plus_oldroute_retry21_20260520\stable_articles.jsonl`.
- Latest stable articles: `127,511`.
- Current consumer release pack: `127,511` articles, `1,456,325` release entities, `589,365` release events.
- Verified graph marker: `stage7_all_deepseek_127511_prod_20260520`.
- Verified graph counts: `127,511` articles, `875,368` entities, `150,752` events.
- Current vector route: all-DeepSeek aliases from the `127,490` full layer plus retry21 in-place delta upsert; point verification matched `101/101`, `101/101`, and `127/127` active-role points.
- Historical 47k role artifact counts remain rollback/audit evidence: `multilingual_baseline=607,338`, `snowflake_canary=607,338`, `english_sidecar=504,943`, `ocr_baseline=40`.
- Current external evidence seed queue: `100,000` written seeds, including `9,654` handle candidates and `113` URL seeds.
- Current HTTP fast evidence: `44` reachable review-ready URLs, `37` browser/auth review, `26` blocked/unreachable, `6` HTTP errors.
- Current Maigret canary is incomplete by web status, but the local Maigret container may have generated report files under its internal run directory.

## Safety Rules

- Do not print secrets, cookies, tokens, or API keys.
- Do not use or probe local `9router`.
- Do not start duplicate paid Dajiala waves or blindly retry old paid work.
- Do not run unbounded scans on `D:\`, `D:\DDownload`, or `D:\aidata`.
- Native-heavy vector/embedding work must use Python `3.11` or `3.12`, not global Python `3.13` and not the current Stage7 `.venv` if it is Python `3.14`.
- Public search/social profile hits are evidence candidates, not identity proof.
- No Maigret/OpenCLI/browser/search result may directly create production `HAS_PROFILE` edges without normalized evidence and review.

## Stage Plan

| Stage | Name | Current state | Required next output | Action |
| ---: | --- | --- | --- | --- |
| 0 | Source registry / URL discovery | Historical `63` accounts and `93,761` discovery/queue records exist; not all graph-ready | source registry reconciliation packet | Report-only reconcile against known manifests; no D-root scan |
| 1 | Archive / mptext / assets / Dajiala | `83,894` archived, `9,620` partial, `247` missing; Dajiala wave01-21 verified OCR index `807`; wave09-21 delta `375` consumed | paid/no-paid gap ledger and ROI packet | Only run signed-long-link candidates if fresh ROI gate proves non-duplicate yield |
| 2 | OCR / MarkItDown / LLM input Markdown | V6 P1 repair proved OCR-to-Markdown gap; `1,397` strict OCR-quality accepted repairs consumed; low-quality/empty rows remain review debt | OCR completeness and low-quality review queue | Prioritize local OCR/static GIF frame repair before paid recapture |
| 3 | LLM text extraction | DeepSeek Flash delta `375/375`; DeepSeek is text-only | reprocess manifests only for rows with new OCR Markdown | Run Flash only after OCR provenance is in Markdown; Pro only for risk/adjudication |
| 4 | Stage7 structured extraction | Latest stable merge `127,511` ready | current stable article/entity/event manifest | Do not rerun already-consumed 93k/full-V6 rows |
| 5 | Graph marker / Neo4j / candidate packs | Production marker verified for `127,511`; graph count `875,368/150,752` | GraphCandidatePack after external evidence review | Do not mutate graph from raw external candidates |
| 6 | Text vector / retrieval | All-DeepSeek role aliases plus retry21 delta verified | vector runtime preflight for future deltas | Verify Python 3.11/3.12 runtime and collection isolation before heavy writes |
| 7 | External network/social evidence | Seed + HTTP fast done; Maigret canary incomplete by web status | Maigret recovered/normalized report, reachable URL review queue, normalized evidence | First recover local Maigret reports; then bounded breadth; then OpenCLI/Lightpanda/Scrapling only for high-yield gaps |
| 8 | QA / orchestration / LDR | LDR is read-only; Prefect is wrapper, not authority | contradiction checks and run ledger | Use for research/audit only; no production bypass |
| 9 | Downstream consumers | Weekly/miniprogram is downstream/historical for this thread | consumer compatibility smoke only | Do not treat weekly publish as graph completion |

## Execution Order

1. Recover the incomplete Maigret canary from the existing local container output, or classify it as a real blocker with exact evidence.
2. Normalize Maigret canary hits into report-only evidence summaries and a review queue.
3. Build reachable URL identity-review queue from the `44` HTTP-fast reachable rows.
4. Build a combined external evidence gap ledger for handle candidates, URL evidence, blocked/auth/browser rows, and high-yield domains.
5. Verify vector runtime: find or create a Python 3.11/3.12 environment for native-heavy vector work; reject Python 3.13/3.14 for heavy runs.
6. For future deltas, run small role-vector smoke against current all-DeepSeek alias targets before heavy writes.
7. Run full role-vector waves only after runtime and smoke evidence are clean.
8. Run vector collection router smoke and consumer retrieval smoke against current role collections.
9. Build GraphCandidatePack from stable graph + normalized/reviewed external evidence.
10. Apply graph staging/production only with separate writer reports and promotion verification.

## Re-run / Re-crawl Rules

- Re-run local processing when the input artifact has changed, a row-level blocker was repaired, or a report shows missing downstream materialization.
- Re-crawl/re-fetch only when the source URL is known, current evidence is incomplete, and the action is bounded by a queue/report.
- Paid Dajiala can run only from a fresh ROI packet that excludes already-consumed wave01-21 rows.
- OCR repair runs before paid recapture for image-heavy rows with local assets.
- External web/social search is report-only until normalized evidence and review accept it.

## Completion Definition

This plan is complete only when all of these exist and pass validation:

- Stage-integrated gap ledger covering stages 0-9.
- OCR/Markdown/DeepSeek gap ledger with no unclassified image-heavy rows.
- Current role-vector staging reports and collection-router smoke for the `127,511` graph base.
- External evidence normalized report and review queue.
- GraphCandidatePack built from reviewed evidence, not raw search hits.
- Graph staging writer report, typed edge promotion report, production promotion report, and consumer smoke.
- `LONGRUN_STATE.md` append and `tools\stage7_rewrite\scripts\stage7_safe_handoff_verify.ps1` pass after every mutation.

## Immediate Cursor

Start with Stage 7 external evidence repair:

```text
reports\graph_maigret_canary_47k_plus_paid_20260518\maigret_canary_summary.json
  -> recover local container reports for status_path /status/20260518_150641
  -> write recovered Maigret summary
  -> normalize canary evidence as candidate-only
  -> update LONGRUN_STATE
  -> run safe handoff verify
```

Progress:

- 2026-05-18 23:28 +08:00: recovered the stalled Maigret canary from local container reports. Output: `tools\stage7_rewrite\reports\graph_maigret_canary_47k_plus_paid_20260518\maigret_canary_recovered_summary.json`, `5` JSON reports, `56` candidate-only normalized evidence rows. Next immediate cursor is source-backed identity review queue construction for Maigret rows and the `44` reachable HTTP-fast URL rows.
