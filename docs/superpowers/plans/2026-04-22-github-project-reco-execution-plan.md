<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# GitHub Project Recommendation Corpus Execution Plan

> Current workspace note: `C:\code\githubstar\wechathtmldownload` is not a git repository, so this plan cannot be committed here. Preserve changes by normal file backup or by moving the workspace into version control later.

## Goal

Execute the design in `docs/superpowers/specs/2026-04-22-github-project-reco-design.md`: download historical WeChat posts from the three source public accounts, process them through the archive-to-LLM pipeline, and generate a deduped Chinese catalog of recommended GitHub projects.

## Runtime Roots

Use this experiment root:

```text
C:\code\githubstar\wechathtmldownload\runs\github-project-reco-2026-04-22
```

Use these subpaths:

```text
config\seeds.json
discovery\
queues\github-project-reco.queue.jsonl
archive\
artifacts\
mirror-md\
release-pack\
analysis\
logs\
HANDOFF_GITHUB_PROJECT_RECO_2026-04-22.md
```

Use these PowerShell variables in manual runs:

```powershell
$experimentRoot = "C:\code\githubstar\wechathtmldownload\runs\github-project-reco-2026-04-22"
$discoveryRoot = Join-Path $experimentRoot "discovery"
$queuePath = Join-Path $experimentRoot "queues\github-project-reco.queue.jsonl"
$archiveRoot = Join-Path $experimentRoot "archive"
$artifactRoot = Join-Path $experimentRoot "artifacts"
$mirrorRoot = Join-Path $experimentRoot "mirror-md"
$releaseRoot = Join-Path $experimentRoot "release-pack"
```

## Phase 1: Scaffold The Experiment Runner

- [ ] Create `tools/githubProjectRecoExperiment.mjs`.
- [ ] Create `runs\github-project-reco-2026-04-22\config\seeds.json`.
- [ ] Keep seed URLs in `seeds.json`, not hard-coded inside pipeline logic.
- [ ] Add helper functions for:
  - [ ] safe path creation
  - [ ] JSON/JSONL read-write
  - [ ] child process execution with log files
  - [ ] secret loading from environment first, then `C:\Users\pc\Downloads\222.txt`
  - [ ] key redaction in logs

## Phase 2: Resolve Accounts And Discover Historical URLs

- [ ] For each seed URL, run:

```powershell
$seedUrl = "https://mp.weixin.qq.com/s/N6sNtFuWBrE4-daGy6CZsw"
npm run fetch-history-urls -- --provider mptext --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --url "$seedUrl" --outDir "$discoveryRoot" --maxPages 1
```

- [ ] Record seed-to-account evidence in `discovery\per_seed_account_resolution.jsonl`.
- [ ] For each resolved source account, run full history discovery:

```powershell
$accountQuery = "resolved-account-query-or-original-seed-url"
npm run fetch-history-urls -- --provider mptext --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --url "$accountQuery" --outDir "$discoveryRoot" --maxPages 400
```

- [ ] Collect every produced `archive_queue.jsonl`.
- [ ] Merge and dedupe queues into:

```text
queues\github-project-reco.queue.jsonl
```

- [ ] Write discovery summary with:
  - [ ] seed count
  - [ ] resolved account count
  - [ ] per-account article counts
  - [ ] merged queue count
  - [ ] duplicate count

## Phase 3: Download Article Archive Bundles

- [ ] Run a small smoke first with a limited queue copy.
- [ ] Run the full mptext archive batch:

```powershell
npm run mptext-archive-batch -- --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --manifestPath "$queuePath" --outDir "$archiveRoot" --statusPath "$(Join-Path $archiveRoot "mptext-archive-status.json")" --resultLogPath "$(Join-Path $archiveRoot "mptext-archive-results.jsonl")" --formats html,json --concurrency 3 --resume --deferExistingPartialOnResume
```

- [ ] Verify:
  - [ ] `raw.html` exists for a sample of successful articles
  - [ ] `archive_meta.json` has `capture_method = "mptext-api"`
  - [ ] failed/partial records are visible in `mptext-archive-results.jsonl`

## Phase 4: Retain Local Assets

- [ ] Run asset retention:

```powershell
npm run download-archive-assets-batch -- --inputDir "$archiveRoot" --manifestPath "$queuePath" --statusPath "$(Join-Path $archiveRoot "asset-retention-status.json")" --resultLogPath "$(Join-Path $archiveRoot "asset-retention-results.jsonl")" --concurrency 3 --resume
```

- [ ] Verify local image assets exist for articles that contain images.
- [ ] Record asset failures in the final handoff; do not block text analysis on image failures.

## Phase 5: Export LLM-Ready Markdown

- [ ] Run:

```powershell
npm run export-llm-batch -- --inputDir "$archiveRoot" --outDir "$artifactRoot" --mirrorDir "$mirrorRoot" --inputMode archive --manifestPath "$queuePath" --statusPath "$(Join-Path $artifactRoot "batch-status.json")" --resume
```

- [ ] Verify:
  - [ ] `artifacts\<account>\<token>\llm_input.md` exists
  - [ ] `mirror-md` has readable Markdown copies
  - [ ] `quality_report.json` is present for processed articles

## Phase 6: Finalize The LLM Pack

- [ ] Run:

```powershell
npm run finalize-llm-pack -- --inputDir "$artifactRoot" --outDir "$releaseRoot" --archiveRoot "$archiveRoot" --manifestPath "$queuePath"
```

- [ ] Verify:
  - [ ] `release-pack\manifest.json`
  - [ ] `release-pack\index.jsonl`
  - [ ] copied article artifacts under `release-pack\articles`

## Phase 7: Implement GitHub Project Analysis Script

- [ ] Create `tools/analyzeGithubProjectRecommendations.mjs`.
- [ ] Read from `release-pack\index.jsonl` and each `llm_input.md`.
- [ ] First pass, deterministic extraction:
  - [ ] extract direct `https://github.com/<owner>/<repo>` URLs
  - [ ] normalize trailing punctuation, query strings, and fragments
  - [ ] dedupe by lowercase owner/repo
  - [ ] preserve article title and source URL evidence
- [ ] Second pass, LLM analysis:
  - [ ] shard articles or project mentions to fit context
  - [ ] call OpenAI-compatible chat completions
  - [ ] prefer Kimi 2.6 coding/planning model from local config when available
  - [ ] require JSON-only output
  - [ ] retry malformed JSON with a repair prompt
- [ ] Write:

```text
analysis\article_project_mentions.jsonl
analysis\github_projects.jsonl
analysis\github_projects.md
analysis\analysis_quality_report.md
```

## Phase 8: Quality Review

- [ ] Count:
  - [ ] seed URLs
  - [ ] resolved accounts
  - [ ] discovered article URLs
  - [ ] archived articles
  - [ ] processed Markdown files
  - [ ] raw GitHub mentions
  - [ ] deduped GitHub projects
- [ ] Sample at least 10 deduped projects.
- [ ] Check descriptions are Chinese plain-language explanations, not copied article text.
- [ ] Check obvious false positives:
  - [ ] GitHub user profile mistaken as repo
  - [ ] docs/issues/pulls URLs treated as separate projects
  - [ ] repeated mirror URLs
  - [ ] non-GitHub domains mislabeled as GitHub projects

## Phase 9: Final Handoff

- [ ] Create:

```text
runs\github-project-reco-2026-04-22\HANDOFF_GITHUB_PROJECT_RECO_2026-04-22.md
```

- [ ] Include:
  - [ ] current branch/git status note: current workspace is not a git repo
  - [ ] exact commands run
  - [ ] output paths
  - [ ] counts and quality summary
  - [ ] known failures
  - [ ] rerun instructions
  - [ ] recommendation on whether to extract this into a new standalone repo

## Acceptance Criteria

- [ ] The main `D:\DDownload` queue is untouched.
- [ ] All experiment outputs live under `runs\github-project-reco-2026-04-22`.
- [ ] The merged queue is reproducible from the seed URLs.
- [ ] The Markdown corpus is generated from archived article bundles.
- [ ] The final project catalog has one deduped row per GitHub project.
- [ ] Every project row has a Chinese plain-language explanation of what it is used for.
- [ ] The final handoff lets another agent resume without asking for context.
