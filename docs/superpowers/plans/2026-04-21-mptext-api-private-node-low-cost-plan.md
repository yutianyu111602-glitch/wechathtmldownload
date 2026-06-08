<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

> **2026-05-21 current boundary:** this is historical mptext planning evidence. Do not use its Singapore VPS phase-3 option for HUAIDJ weekly mini-program work. The user confirmed the Singapore server / Singapore VPS belongs to the stock-trading beta line and is unrelated to weekly mini-program, Atlas read-only bridge, Docker exporter, CloudRun `weekly-api`, or mini-program upload/review workflows. Current weekly execution must follow `docs/weekly-miniprogram-handoff-20260519/PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md` and `apps/weekly_activity_miniprogram/OPENCLAW_AUTOMATION.md`.

# Mptext API Private Node Low Cost Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the WeChat article pipeline from the expensive original discovery/download path to a low-cost mptext API + private deployment/private proxy path.

**Architecture:** Use local `http://127.0.0.1:17300` mptext private deployment as the first-class control endpoint, mapping host port `17300` to the container's internal `3000` so it avoids common dev-server collisions. Local login avoids HTTPS complexity and the network SSOT routes WeChat domains direct. Historical text in this plan mentions Cloudflare Worker/private proxy and Singapore VPS options, but the Singapore VPS option is superseded for HUAIDJ weekly mini-program work by the 2026-05-21 boundary above.

**Tech Stack:** TypeScript/Node 20+, current CLI pipeline, mptext Nuxt/Nitro API, Docker, optional Cloudflare Worker, optional Ubuntu VPS with Docker Compose + Nginx + HTTPS.

---

I'm using the writing-plans skill to create the implementation plan.

## Context Read

Read sources and local state:

- Official docs: `https://docs.mptext.top/faq`, `https://docs.mptext.top/get-started/usage`, `https://docs.mptext.top/get-started/proxy`, `https://docs.mptext.top/get-started/private-proxy`, `https://docs.mptext.top/advanced/private-deploy`, `https://docs.mptext.top/advanced/api`, `https://docs.mptext.top/llms.txt`, `https://docs.mptext.top/llms-full.txt`.
- Local doc copies: `D:\DDownload\api.md`, `private-proxy.md`, `proxy.md`, `proxy (1).md`, `faq.md`, `private-deploy.md`, `features.md`.
- Official repo cloned to `C:\code\githubstar\wechathtmldownload\vendor\wechat-article-exporter`.
- Current workspace is not a git repo. Do not claim commits here unless the executor creates or moves into a real repo.
- Official cloned repo is clean on `master`, `origin/master`, commit `e6ebbf3`.
- Current workspace verification on 2026-04-21: `npm run build` passed; `npm test` passed with `48/48`.

Key official facts:

- `X-Auth-Key` is generated after mptext login and expires with the login session, about 4 days.
- Public API base is `https://down.mptext.top`, or a private deployment base URL.
- Public API endpoints needed here:
  - `GET /api/public/v1/authkey`
  - `GET /api/public/v1/account?keyword=...`
  - `GET /api/public/v1/accountbyurl?url=...`
  - `GET /api/public/v1/article?fakeid=...&begin=0&size=20`
  - `GET /api/public/v1/download?url=...&format=html|markdown|text|json`
- Article list page size is max 20.
- Public proxy nodes have shared daily quota and `429` risk.
- Private deployment can run locally or via Docker. Docker persists server KV under `/app/.data`.
- Login QR cookie works on `localhost` / `127.0.0.1`; non-local domains need HTTPS because 微信 login cookies are `Secure`.
- Private proxy node docs show a generic fetch proxy. The official snippet is not authenticated, so this plan requires a hardened private proxy if we deploy our own node.

Current repo facts:

- `src/api/fetchHistoryUrls.ts` already supports `provider: "mptext"` and writes `history_urls.json`, `history_urls.txt`, `archive_queue.jsonl`.
- `src/historyCli.ts` exposes `--provider mptext`, `--endpoint`, and `--key`.
- `tools/exportMptextAccount.mjs` already proves direct mptext account export is viable, but it is an untyped standalone tool with duplicated mptext logic and weaker status/test coverage.
- `archive-batch` currently uses Playwright browser capture and writes `raw.html`, `page.mhtml`, `page.pdf`, `article.url.txt`, `archive_meta.json`.
- `process-batch --inputMode archive` only needs archive bundle directories containing `raw.html`; `page.mhtml` / `page.pdf` are useful evidence but not required by current processing.
- `downloadArticleAssets.ts` currently direct-fetches images with WeChat referer; it does not yet support a private proxy pool.

## VPS Decision

Recommended default: **local private deployment first**.

Why local first:

- Historical note: the network SSOT says WeChat domains (`mp.weixin.qq.com`, `mmbiz.qpic.cn`, etc.) route direct locally; this remains aligned with the current boundary that HUAIDJ weekly mini-program traffic must not be sent through the Singapore stock-beta server.
- `localhost` avoids the HTTPS/cookie problem for mptext login.
- Auth cookies and `X-Auth-Key` stay on the PC instead of a public VPS.
- It is enough for self-use and keeps the first smoke cheap.

Historical only, superseded for HUAIDJ weekly mini-program work: the old Singapore VPS option applied only when one of these was true:

- You need the mptext UI/API reachable from multiple machines while the PC is off.
- Local Docker/private deployment is unstable.
- Cloudflare Worker private nodes are blocked/throttled and a VPS-hosted hardened proxy is needed.
- You want scheduled harvest jobs to run 24/7.

Do not put the first implementation on VPS by default. VPS deployment adds HTTPS, firewall, backup, exposed cookie storage, and reverse-proxy hardening before the core low-cost path has been proven.

## Chosen Approach

### 2026-04-21 Async all-account note

The single-account `fetch-history-urls` command remains useful for smoke tests and small manual runs.

For the real all-account export from `D:\DDownload\公众号.json`, do not implement a shell loop that runs `fetch-history-urls` one account at a time and then starts downloads afterward. Use the newer plan in `docs/superpowers/plans/2026-04-21-account-json-api-first-export-redesign.md`:

```text
account manifest -> async URL prefetch producer -> durable download-ready queue -> mptext download workers
```

Download/archive workers should be able to consume queue records while URL discovery is still listing later accounts.

### Approach A: Local mptext private deployment + current CLI mptext discovery

Use Docker on the PC, login at `http://127.0.0.1:17300`, get `X-Auth-Key`, call:

```powershell
npm run fetch-history-urls -- --provider mptext --endpoint "http://127.0.0.1:17300" --key "$env:MPTEXT_AUTH_KEY" --url "目标公众号名或文章URL" --outDir "D:\rawwechat_discovery"
```

Pros: fastest, lowest risk, no new remote surface.

Cons: still needs a better low-cost archive step so we do not use Playwright capture for every article.

### Approach B: Add mptext API archive mode

Add a typed mptext client and a new batch command that reads `archive_queue.jsonl`, downloads `format=html` and optionally `format=json`, and writes archive-compatible bundles. This replaces browser capture for the bulk path.

Pros: directly reduces cost/runtime. Fits current `process-batch --inputMode archive`.

Cons: does not produce MHTML/PDF, so use Playwright capture only for selected high-value samples or quality audits.

### Approach C: VPS-hosted mptext/private proxy

Historical-only option: deploy mptext on a VPS behind HTTPS and auth, or host a hardened proxy node. Do not use the Singapore stock-beta server for current HUAIDJ weekly mini-program work.

Pros: always-on, remote accessible, useful for Mac/PC shared access.

Cons: more operational risk and not clearly better for WeChat traffic. Defer until local smoke proves value.

Recommendation: **A + B first; C only as phase 3**.

## File Structure

Create:

- `src/mptext/client.ts`  
  Typed mptext API client: auth validation, account resolve, article paging, download endpoint, retry/backoff.
- `src/archive/runMptextArchiveBatch.ts`  
  Reads `archive_queue.jsonl`, downloads article HTML/JSON via mptext API, writes archive-compatible bundle directories.
- `tests/mptextClient.test.ts`  
  Mocked fetch tests for headers, auth validation, account lookup, paging, ret/backoff handling.
- `tests/mptextArchiveBatch.test.ts`  
  Verifies queue consumption, resume skip, bundle shape, failure status.
- `docs/MPTEXT_LOW_COST_RUNBOOK.md`  
  Human runbook for local deployment, auth-key refresh, queue creation, mptext API archive, processing, and when to use VPS.
- `deploy/cloudflare/mptext-private-proxy-worker.js`  
  Hardened optional Worker proxy with token auth and allowed target host list.
- `deploy/vps/mptext/docker-compose.yml`  
  Optional phase-3 VPS deployment file.
- `deploy/vps/mptext/nginx.conf`  
  Optional phase-3 HTTPS reverse proxy config.

Modify:

- `src/api/fetchHistoryUrls.ts`  
  Reuse `MptextClient` for mptext provider instead of duplicated helper functions.
- `src/historyCli.ts`  
  Keep current flags; clarify usage text for `--provider mptext`.
- `src/cli.ts`  
  Add `mptext-archive-batch` command and parse `--key`, `--endpoint`, `--concurrency`, `--formats`, `--listDelayMs`, `--rateLimitDelayMs`.
- `src/archive/types.ts`  
  Add optional `capture_method?: "playwright" | "mptext-api"` to `ArchiveMetaJson`.
- `src/archive/downloadArticleAssets.ts`  
  Add optional proxy fetch path only after direct fetch failure, so local direct remains the default.
- `package.json`  
  Add scripts for low-cost mainline.
- `HANDOFF.md`  
  Add the new canonical low-cost route after implementation.

## Task 1: Local Deployment Runbook

**Files:**

- Create: `docs/MPTEXT_LOW_COST_RUNBOOK.md`

- [ ] **Step 1: Write the runbook**

Use this exact operational position:

````markdown
# Mptext Low Cost Runbook

## Default Mode

Use local private deployment first:

- Base URL: `http://127.0.0.1:17300`
- Fallback local URL: `http://127.0.0.1:17301`, then increment by 1 if needed
- Container internal port: `3000`
- Host port: `17300` by default; if occupied, use `17301`, then `17302`
- Auth: `X-Auth-Key` from the mptext API page after login
- Data: Docker volume mapped to `.mptext-data`
- Private proxy: optional; use only when asset downloads fail or browser export needs it
- VPS: optional phase 3, not the first smoke path

## Local Docker Start

```powershell
$port = 17300
while (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue) {
  $port++
}
Write-Host "Using host port $port"

docker pull ghcr.io/wechat-article/wechat-article-exporter:latest
docker run -d `
  --restart always `
  --name wechat-article-exporter `
  -e NODE_TLS_REJECT_UNAUTHORIZED=0 `
  -e NITRO_KV_DRIVER=fs `
  -e NITRO_KV_BASE=.data/kv `
  -p "127.0.0.1:${port}:3000" `
  -v "C:\code\githubstar\wechathtmldownload\.mptext-data:/app/.data" `
  ghcr.io/wechat-article/wechat-article-exporter:latest

$env:MPTEXT_BASE_URL = "http://127.0.0.1:$port"
Write-Host "MPTEXT_BASE_URL=$env:MPTEXT_BASE_URL"
```

Open `$env:MPTEXT_BASE_URL`, scan login QR as a 公众号/服务号, then open the API page and read the auth key.

## Key Expiry

The key expires with the login session, about 4 days. Refresh by logging in again and updating `MPTEXT_AUTH_KEY`.

## Low Cost Pipeline

```powershell
$env:MPTEXT_BASE_URL = "http://127.0.0.1:17300"
$env:MPTEXT_AUTH_KEY = "<paste-current-key>"

npm run fetch-history-urls -- --provider mptext --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --url "目标公众号名或文章URL" --outDir "D:\rawwechat_discovery"

npm run mptext-archive-batch -- --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --manifestPath "D:\rawwechat_discovery\history_xxx\archive_queue.jsonl" --outDir "D:\rawwechat_archive" --resume

npm run download-archive-assets-batch -- --inputDir "D:\rawwechat_archive" --manifestPath "D:\rawwechat_discovery\history_xxx\archive_queue.jsonl" --resume

npm run export-llm-batch -- --inputDir "D:\rawwechat_archive" --outDir "D:\rawwechat_llm_artifacts" --mirrorDir "D:\rawwechat_llm_md" --inputMode archive --manifestPath "D:\rawwechat_discovery\history_xxx\archive_queue.jsonl" --resume
```

## VPS Use Criteria

Historical only, superseded for HUAIDJ weekly mini-program work: use a VPS only when local mode cannot meet the operational need:

- PC cannot stay on during long jobs
- multiple devices need the same private mptext deployment
- Cloudflare private proxy nodes are not reachable
- a scheduled 24/7 job is required

If VPS is used, deploy behind HTTPS and an access control layer. Do not expose mptext publicly without protection.
````

- [ ] **Step 2: Verify docs only**

Run:

```powershell
Test-Path "docs\MPTEXT_LOW_COST_RUNBOOK.md"
```

Expected: `True`

## Task 2: Typed Mptext Client

**Files:**

- Create: `src/mptext/client.ts`
- Create: `tests/mptextClient.test.ts`
- Modify: `src/api/fetchHistoryUrls.ts`

- [ ] **Step 1: Write failing tests**

Test cases:

```ts
test("MptextClient sends X-Auth-Key to authenticated endpoints", async () => {});
test("MptextClient validates authkey code=0 and rejects code=-1", async () => {});
test("MptextClient resolves account by article URL", async () => {});
test("MptextClient pages articles with begin increments of 20", async () => {});
test("MptextClient backs off on ret=200013 then retries", async () => {});
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
npm test -- tests/mptextClient.test.ts
```

Expected: fails because `src/mptext/client.ts` does not exist.

- [ ] **Step 3: Implement `MptextClient`**

Required public API:

```ts
export interface MptextClientOptions {
  baseUrl?: string;
  authKey: string;
  fetchImpl?: typeof fetch;
  listDelayMs?: number;
  rateLimitDelayMs?: number;
  maxRateLimitAttempts?: number;
}

export interface MptextAccount {
  fakeid: string;
  nickname: string;
  alias?: string;
}

export interface MptextArticle {
  aid?: string;
  title: string;
  link: string;
  author_name?: string;
  cover?: string;
  cover_img?: string;
  pic_cdn_url_1_1?: string;
  update_time?: number;
  create_time?: number;
  appmsgid?: number;
  itemidx?: number;
}

export class MptextClient {
  constructor(options: MptextClientOptions);
  validateAuthKey(): Promise<void>;
  resolveAccount(query: string): Promise<MptextAccount>;
  listArticlesPage(fakeid: string, begin: number, size?: number): Promise<MptextArticle[]>;
  fetchAllArticles(fakeid: string, maxPages?: number): Promise<MptextArticle[]>;
  downloadArticle(url: string, format: "html" | "markdown" | "text" | "json"): Promise<string>;
}
```

Implementation rules:

- Normalize base URL by trimming trailing slashes.
- Send `X-Auth-Key` on all mptext requests, including download, even though source code shows download does not currently require it.
- Treat `base_resp.ret !== 0` as failure except `ret === 200013`, which should back off and retry.
- Default article page size is 20.
- Preserve current `fetchHistoryUrls` output shape exactly.

- [ ] **Step 4: Refactor mptext provider in `fetchHistoryUrls.ts`**

Replace duplicated mptext fetch/account/article helpers with `MptextClient`.

No behavior change allowed for the old `dajiala` provider.

- [ ] **Step 5: Verify**

Run:

```powershell
npm test -- tests/mptextClient.test.ts tests/fetchHistoryUrls.test.ts
npm run build
```

Expected:

- mptext tests pass.
- existing `fetchHistoryUrls can use mptext API provider with X-Auth-Key` still passes.
- build passes.

## Task 3: Mptext API Archive Batch

**Files:**

- Create: `src/archive/runMptextArchiveBatch.ts`
- Create: `tests/mptextArchiveBatch.test.ts`
- Modify: `src/archive/types.ts`
- Modify: `src/cli.ts`
- Modify: `package.json`

- [ ] **Step 1: Write failing tests**

Test cases:

```ts
test("runMptextArchiveBatch writes archive-compatible bundles", async () => {});
test("runMptextArchiveBatch skips existing raw.html on resume", async () => {});
test("runMptextArchiveBatch records failed items without stopping the whole batch", async () => {});
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
npm test -- tests/mptextArchiveBatch.test.ts
```

Expected: fails because `runMptextArchiveBatch` does not exist.

- [ ] **Step 3: Extend archive metadata type**

Modify `ArchiveMetaJson`:

```ts
capture_method?: "playwright" | "mptext-api";
```

Do not make this required, so existing tests and Playwright archive metadata remain valid.

- [ ] **Step 4: Implement batch runner**

Behavior:

- Read `archive_queue.jsonl`.
- For each record, write output under `<archiveRoot>/<account_key>/<token>/`.
- Download HTML via `MptextClient.downloadArticle(record.source_url, "html")`.
- If `formats` includes `json`, also download `download.json`.
- Always write `raw.html`, `article.url.txt`, `archive_meta.json`.
- Set `archive_meta.capture_method = "mptext-api"`.
- Set `mhtml_bytes = 0` and `pdf_bytes = 0`.
- Add warning: `mptext-api archive mode does not create page.mhtml or page.pdf`.
- Resume skip if `raw.html` exists and `archive_meta.json` has `capture_method === "mptext-api"` and status is `archived`.
- Return and persist the existing `ArchiveBatchSnapshot` shape.

- [ ] **Step 5: Add CLI command**

Add:

```powershell
npm run mptext-archive-batch -- --manifestPath path\to\archive_queue.jsonl --outDir D:\rawwechat_archive --key "<auth-key>" --endpoint "http://127.0.0.1:17300" --resume
```

Add `package.json` script:

```json
"mptext-archive-batch": "tsx src/cli.ts mptext-archive-batch"
```

- [ ] **Step 6: Verify**

Run:

```powershell
npm test -- tests/mptextArchiveBatch.test.ts tests/archiveModeBatch.test.ts tests/processArchiveBundle.test.ts
npm run build
```

Expected:

- New mptext archive tests pass.
- Existing archive-mode processing tests pass.
- build passes.

## Task 4: Optional Private Proxy Fallback For Asset Downloads

**Files:**

- Create: `deploy/cloudflare/mptext-private-proxy-worker.js`
- Modify: `src/archive/downloadArticleAssets.ts`
- Create: `tests/downloadArticleAssetsProxy.test.ts`

- [ ] **Step 1: Write hardened Worker**

The Worker must require `Authorization: Bearer <PRIVATE_PROXY_TOKEN>` and allow only these target hosts:

```js
const ALLOWED_HOSTS = new Set([
  "mp.weixin.qq.com",
  "mmbiz.qpic.cn",
  "mmbiz.qlogo.cn",
]);
```

Required request shape:

```text
GET /?url=<encoded-target-url>&headers=<encoded-json-headers>
Authorization: Bearer <token>
```

Required protections:

- Reject missing token with `401`.
- Reject disallowed target host with `403`.
- Reject non-http/https target with `400`.
- Return `Access-Control-Allow-Origin` only for configured local/private origins.

- [ ] **Step 2: Add proxy fallback to asset downloader**

Add options:

```ts
interface DownloadArticleAssetsOptions {
  fetchImpl?: typeof fetch;
  proxyUrls?: string[];
  proxyAuthorization?: string;
}
```

Behavior:

- Try current direct fetch first.
- If direct fetch fails or returns non-OK, try proxy URLs round-robin.
- Proxy request should forward target headers as encoded JSON.
- Preserve current output schema in `assets_local.json`.

- [ ] **Step 3: Verify**

Run:

```powershell
npm test -- tests/downloadArticleAssets.test.ts tests/downloadArticleAssetsProxy.test.ts
npm run build
```

Expected:

- Existing direct image tests still pass.
- New proxy fallback test proves direct failure can still download via proxy.

## Task 5: End-To-End Local Smoke

**Files:**

- Create: `MPTEXT_LOW_COST_SMOKE_RESULT_2026-04-21.md`

- [ ] **Step 1: Start local mptext**

Run:

```powershell
docker ps --filter "name=wechat-article-exporter"
```

Expected: container is running and host port `17300` or the chosen fallback port maps to container port `3000`. It should be bound to `127.0.0.1`, not exposed on all LAN interfaces.

- [ ] **Step 2: Validate auth key**

Run:

```powershell
$env:MPTEXT_BASE_URL = "http://127.0.0.1:17300"
$env:MPTEXT_AUTH_KEY = "<current-key>"
Invoke-RestMethod -Headers @{"X-Auth-Key"=$env:MPTEXT_AUTH_KEY} "$env:MPTEXT_BASE_URL/api/public/v1/authkey"
```

Expected: `code` is `0`.

- [ ] **Step 3: Small discovery**

Run:

```powershell
npm run fetch-history-urls -- --provider mptext --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --url "目标公众号名或文章URL" --outDir "D:\rawwechat_discovery\mptext_smoke" --maxPages 1
```

Expected:

- `history_urls.json`
- `history_urls.txt`
- `archive_queue.jsonl`
- 1 to 20 article URLs.

- [ ] **Step 4: Low-cost archive**

Run:

```powershell
npm run mptext-archive-batch -- --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --manifestPath "D:\rawwechat_discovery\mptext_smoke\history_xxx\archive_queue.jsonl" --outDir "D:\rawwechat_archive_mptext" --resume
```

Expected per sample:

- `raw.html`
- `article.url.txt`
- `archive_meta.json`
- `archive_meta.capture_method` is `mptext-api`.

- [ ] **Step 5: Process archive**

Run:

```powershell
npm run export-llm-batch -- --inputDir "D:\rawwechat_archive_mptext" --outDir "D:\rawwechat_llm_artifacts_mptext" --mirrorDir "D:\rawwechat_llm_md_mptext" --inputMode archive --manifestPath "D:\rawwechat_discovery\mptext_smoke\history_xxx\archive_queue.jsonl" --resume
```

Expected:

- `llm_input.md`
- `sidecar.json`
- `quality_report.json`
- mirrored markdown under `D:\rawwechat_llm_md_mptext`.

- [ ] **Step 6: Record result**

Write `MPTEXT_LOW_COST_SMOKE_RESULT_2026-04-21.md` with:

- base URL used
- auth validation result
- sample count
- total archive failures
- whether assets required proxy fallback
- whether VPS was needed
- next chosen action

## Task 6: Optional VPS Deployment Only After Local Smoke

**Files:**

- Create: `deploy/vps/mptext/docker-compose.yml`
- Create: `deploy/vps/mptext/nginx.conf`
- Modify: `docs/MPTEXT_LOW_COST_RUNBOOK.md`

- [ ] **Step 1: Confirm entry criteria**

Proceed only if `MPTEXT_LOW_COST_SMOKE_RESULT_2026-04-21.md` says one of:

- local PC cannot stay online for jobs
- multi-device access is required
- local Docker is unreliable
- private proxy fallback needs VPS

- [ ] **Step 2: Create VPS compose file**

`docker-compose.yml` contents:

```yaml
services:
  app:
    image: ghcr.io/wechat-article/wechat-article-exporter:latest
    restart: always
    environment:
      - NODE_TLS_REJECT_UNAUTHORIZED=0
      - NITRO_KV_DRIVER=fs
      - NITRO_KV_BASE=.data/kv
    volumes:
      - ./.data:/app/.data
    expose:
      - "3000"

  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - app
```

- [ ] **Step 3: Create Nginx config**

Use HTTPS and restrict access by at least one of:

- Cloudflare Access
- Nginx basic auth
- source IP allowlist

Do not expose a bare unauthenticated mptext instance on the public internet.

- [ ] **Step 4: Remote execution rule**

Follow `C:\Users\pc\.codex\references\remote-execution.md`.

Use `scp + docker compose` commands, not a quote-heavy SSH one-liner:

```powershell
scp .\deploy\vps\mptext\docker-compose.yml root@149.28.150.224:/opt/mptext/docker-compose.yml
scp .\deploy\vps\mptext\nginx.conf root@149.28.150.224:/opt/mptext/nginx.conf
ssh root@149.28.150.224 'cd /opt/mptext && docker compose up -d'
```

Expected:

- `docker compose ps` shows `app` and `nginx` healthy.
- HTTPS URL loads the mptext login page.
- API `authkey` check works after login.

## Final Execution Order For GPT-5.4 Pro

1. Implement Task 1 docs.
2. Implement Task 2 typed mptext client.
3. Implement Task 3 mptext archive batch.
4. Run build/test.
5. Run Task 5 local smoke with `http://127.0.0.1:17300` or the selected fallback port.
6. Only implement Task 4 proxy fallback if smoke proves direct assets are failing.
7. Only implement Task 6 VPS deployment if local-first mode fails the operational need.

## Hard Stops

- Stop if `npm run build` fails.
- Stop if `npm test` fails.
- Stop if `authkey` validation returns `code=-1`; refresh login instead of debugging code.
- Stop if more than 30 percent of mptext archive downloads fail in the small smoke; inspect failure class before scaling.
- Do not run Playwright `archive-batch` as the bulk path unless mptext API archive quality is proven insufficient.
