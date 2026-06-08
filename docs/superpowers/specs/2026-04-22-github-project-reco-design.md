<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# GitHub Project Recommendation Corpus Design

## Goal

Build an isolated experiment around three seed WeChat article URLs to collect all historical posts from their source public accounts, identify every recommended GitHub open-source project, and produce a Chinese plain-language catalog explaining what each project is useful for.

This is a quality test for the existing WeChat archive-to-LLM pipeline. It must not pollute the current production-ish `D:\DDownload` queue or change the main pipeline semantics.

Seed URLs:

- `https://mp.weixin.qq.com/s/N6sNtFuWBrE4-daGy6CZsw`
- `https://mp.weixin.qq.com/s/35fu9RMu3sX86jDFjVP0gQ`
- `https://mp.weixin.qq.com/s/ub1ww6cuscyfgJ5-SOrJYQ`

## Recommended Direction

Use the current repository as the host, but create a new isolated experiment product directory under:

```text
C:\code\githubstar\wechathtmldownload\runs\github-project-reco-2026-04-22
```

This should not become a new repository yet. The current repo already owns the mptext discovery, archive, asset retention, Markdown export, and LLM pack stages. A separate repo would add packaging overhead before we know whether the analysis quality is good enough. If the experiment produces stable outputs and the collector needs to run repeatedly across many GitHub-recommendation accounts, then extract it later as a dedicated project.

## Alternatives Considered

### Approach A: Isolated experiment inside this repo

This is the chosen approach.

Pros:

- Reuses the current `fetch-history-urls`, `mptext-archive-batch`, `download-archive-assets-batch`, `export-llm-batch`, and `finalize-llm-pack` commands.
- Keeps the test corpus separate from `D:\DDownload`.
- Lets the analysis script evolve against real outputs without changing pipeline internals.

Cons:

- The collector is still coupled to this repo until it proves value.

### Approach B: New standalone project immediately

Pros:

- Cleaner long-term identity for a GitHub open-source project collector.
- Easier to package later as a CLI.

Cons:

- Premature split. It would duplicate pipeline knowledge and slow the quality test.

### Approach C: Add it directly to the main queue

Pros:

- Lowest setup work.

Cons:

- Rejected. It mixes GitHub-project recommendation data with the existing WeChat archive corpus and makes later audits ambiguous.

## Architecture

The experiment is a thin orchestration layer over the existing pipeline:

```text
seed article URLs
  -> resolve source public accounts through mptext
  -> fetch each account's historical article URLs
  -> merge and dedupe account archive queues
  -> download article HTML bundles through mptext
  -> retain local article assets
  -> export LLM-ready Markdown artifacts
  -> finalize lightweight LLM pack
  -> analyze Markdown for GitHub projects with a strong LLM
  -> produce human catalog and machine-readable JSONL
```

## Directory Contract

All outputs for this experiment stay under one root:

```text
runs\github-project-reco-2026-04-22\
  config\
    seeds.json
    provider.env.example
  discovery\
    accounts.json
    per_seed_account_resolution.jsonl
    history_*\archive_queue.jsonl
  queues\
    github-project-reco.queue.jsonl
  archive\
    <account_key>\<article_token>\raw.html
  artifacts\
    <account_key>\<article_token>\llm_input.md
  mirror-md\
    <account_key>\<article_token>.md
  release-pack\
    manifest.json
    index.jsonl
    articles\...
  analysis\
    article_project_mentions.jsonl
    github_projects.jsonl
    github_projects.md
    analysis_quality_report.md
  logs\
    *.log
  HANDOFF_GITHUB_PROJECT_RECO_2026-04-22.md
```

## Config And Secret Handling

The script may read local provider credentials from environment variables or from the user's private file:

```text
C:\Users\pc\Downloads\222.txt
```

The script must not copy API keys into generated docs, queues, logs, or analysis outputs.

Minimum runtime variables:

- `MPTEXT_BASE_URL`
- `MPTEXT_AUTH_KEY`
- `OPENAI_BASE_URL` or another OpenAI-compatible endpoint
- `OPENAI_API_KEY`
- `WECHAT_DOWNSTREAM_MODEL`, preferred for this run as the strongest available Kimi 2.6 coding/planning-capable model

If Kimi is unavailable, use the strongest available OpenAI-compatible model configured in the local provider file or environment.

## Analysis Contract

The analysis stage should produce two layers:

1. Article-level mentions: every GitHub URL or repo-like project mention found in each article.
2. Deduped project catalog: one row per GitHub repository or project.

Each deduped project record should include:

- `project_name`
- `github_url`
- `homepage_url`
- `source_accounts`
- `source_articles`
- `first_seen_article_title`
- `short_cn_intro`
- `what_it_is_for_cn`
- `who_should_use_it_cn`
- `tags`
- `confidence`
- `evidence`

The Markdown catalog should be written in concise Chinese, explaining projects in plain language rather than copying article marketing phrasing.

## Error Handling

- Discovery must be resumable per account.
- Archive download must use `--resume`.
- If a seed URL cannot resolve to an account, record it in `per_seed_account_resolution.jsonl` and continue with the remaining seeds.
- If article download returns invalid HTML, keep the failed bundle metadata and include it in `analysis_quality_report.md`.
- If LLM analysis fails for a shard, keep the input shard and status so it can be rerun without re-downloading articles.

## Testing And Verification

Before a full run:

- Run a smoke pass with `--maxPages 1` per resolved account.
- Verify queue merge dedupes URLs.
- Verify at least one downloaded article has valid `raw.html`.
- Verify `export-llm-batch --inputMode archive` produces `llm_input.md`.
- Verify the analysis script can extract at least direct `github.com/<owner>/<repo>` links without an LLM call.

After a full run:

- Count discovered articles, archived articles, processed Markdown files, and analysis rows.
- Compare unique GitHub URLs before and after LLM dedupe.
- Manually inspect at least 10 deduped project descriptions.
- Write final handoff with command history, paths, counts, failures, and rerun instructions.

## Not Doing

- Do not change the main `D:\DDownload` queue.
- Do not rewrite the current archive pipeline for this experiment.
- Do not build a GUI for this collector in this pass.
- Do not create a new repository until the experiment proves stable value.
- Do not commit secrets or provider keys.

