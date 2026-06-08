# Longrun Stability Plan For Atlas Outlink Search

Generated: 2026-05-21 20:28 CST

## Lifecycle / Current Authority Check

Classification: `historical-or-evidence` / `reference` / `verify-before-use`.

This file is a stability-pattern note for bounded report-only Atlas outlink worker batches. It is not the current execution authority for public-search, Post-Filter, Layer D, browser fallback, graph writes, or production promotion.

Current authority must be read from `..\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` and `..\..\reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md` before using any execution wording below. As of the checked closeout, public-search is `COMPLETE`, full Post-Filter generated at `2026-05-22T10:36:47+08:00`, the reduced review queue is `27`, filtered candidates are `349`, quarantine is `245,653`, and Layer D was only a dry-run over `20 / 27` rows. `accepted_for_graph`, `identity_proof`, and `graph_write_allowed` remain blocked until human acceptance and separate staged-promotion authorization.

Use the batch, artifact, resume, and failure policies below as operational hygiene only after a separately authorized bounded report-only worker run is selected. Do not treat them as permission to start public-search, Post-Filter, Scrapling, OpenCLI, Maigret, Camofox, browser, Stage7, vector, graph/database, deployment, upload, or D-drive work.

## Stability Goal

Run Atlas external outlink evidence collection for many hours without freezing the desktop, corrupting artifacts, or producing false graph evidence.

## Execution Shape

Use a gate-led worker loop:

```text
preflight
-> status check
-> prerequisite gate
-> bounded batch
-> write status
-> inspect errors
-> sleep
-> next batch
```

Do not use one huge unbounded run when the queue size is unknown.

## Batch Policy

Default batch sizing:

- HTTP outlink expansion: 500 profile rows per batch.
- Aggregator follow pages: cap at 80 per batch unless the machine is idle.
- Scrapling content evidence: 200-500 rows per batch.
- OpenCLI/Camofox fallback: 50-100 rows per batch because browser sessions are heavier.

Retry policy:

- retry transient network failures at most 2 times
- do not retry 403/429/captcha in a tight loop
- put blocked rows into an error/fallback queue

Sleep policy:

- HTTP: 0.3-0.8 seconds between rows
- Scrapling: 0.5-1.0 seconds
- OpenCLI/Camofox: 1.0-2.0 seconds

## Resource Policy

- Keep long workers at `Idle` priority when possible.
- Do not increase parallelism while the user is actively using the desktop.
- Prefer longer runtime over freezing the machine.
- If memory pressure is high, reduce batch size before stopping services.

GPU note:

- This lane is mostly network and HTML parsing. GPU does not materially accelerate HTTP, SearXNG, Maigret, OpenCLI DOM reading, or Camofox page capture.
- GPU is useful later for embedding/rerank/local model/OCR work, not for this outlink worker.

## Artifact Policy

Every batch should produce:

- summary JSON
- fetch rows JSONL
- outlinks JSONL
- follow-up queue JSONL
- errors JSONL
- a short Markdown status if the run is long

Every artifact must remain report-only:

- `accepted_for_graph=false`
- `identity_proof=false`
- `graph_write_allowed=false`

## Restart / Resume Policy

Before starting a new batch:

- check whether the output dir already exists
- inspect existing summary
- do not overwrite a completed batch unless explicitly instructed
- create `batchNNN` dirs for repeated runs

If interrupted:

- preserve partial files
- write a resume note with last input offset if known
- continue from a new batch dir rather than modifying old evidence in place

## Failure Policy

Hard stop and report if:

- public-search status file disappears
- stderr begins growing with unexplained fatal errors
- output JSONL is malformed
- graph/vector/database write code is accidentally invoked
- a script tries to expose cookie/token/credential values

Soft continue if:

- individual URLs fail
- 403/429/captcha appears
- platform-specific pages block HTTP
- Camofox/OpenCLI cannot render a page

For soft failures, write them to error queues and continue the next safe row.
