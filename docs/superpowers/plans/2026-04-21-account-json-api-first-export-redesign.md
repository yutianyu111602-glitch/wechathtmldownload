<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Account JSON API First Export Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace browser-heavy mptext website operations with an API-first export system driven by `D:\DDownload\公众号.json`, using the local private node from the other thread as the preferred backend.

**Architecture:** Treat `公众号.json` as the account inventory, a private mptext API node as the control plane, local files under `D:\DDownload` as durable storage, and the browser IndexedDB/web UI only as a legacy fallback. The pipeline becomes `account manifest -> API discovery -> API content export -> normalized entities -> original image cache -> verification`, all resumable through local manifests.

**Tech Stack:** Node.js 22, TypeScript, mptext public/private API, current CLI pipeline, local filesystem manifests, optional Cloudflare Worker/private proxy for image fallback, Node test runner via `npm test`.

---

## 2026-04-21 Update: Async All-Account URL Producer

The next implementation must not keep `fetch-history-urls` as a one-account, foreground prerequisite.

New required architecture:

```text
D:\DDownload\公众号.json
  -> account scheduler
  -> async URL prefetch producer
  -> durable download-ready queue
  -> mptext/html download workers
  -> article bundles / image cache / processing
```

The URL stage is a producer. It should asynchronously enumerate every account in `公众号.json`, write discovered article URLs into a durable queue, and keep running ahead of the download workers. Download workers are consumers. They must lease queue records and download articles from the shared queue without waiting for every account to finish discovery.

### Producer/Consumer Rules

- The producer owns account discovery, article page listing, dedupe, and queue append.
- Download workers own queue leasing, article HTML/JSON download, retry, and bundle writes.
- The producer and download workers may run at the same time.
- Per-account listing remains sequential (`begin += 20`) because mptext article listing is rate-limit sensitive.
- Cross-account listing may be concurrent with a small bound. Default `accountConcurrency = 2`.
- Article download workers may run with `downloadConcurrency = 3` by default, configurable up to a conservative ceiling such as `6`.
- If the ready queue exceeds a high watermark, the producer pauses page listing until consumers drain it.
- If the ready queue is empty while the producer is still running, download workers wait instead of exiting.
- If the producer has completed and the ready queue is empty, consumers can finish.

### Durable Queue Contract

Create a queue layer instead of letting download threads mutate raw `archive_queue.jsonl` directly.

Planned files:

- Create: `src/accounts/runAccountUrlPrefetch.ts`
- Create: `src/state/downloadQueueStore.ts`
- Create: `tests/runAccountUrlPrefetch.test.ts`
- Create: `tests/downloadQueueStore.test.ts`
- Modify: `src/archive/runMptextArchiveBatch.ts`
- Modify: `src/cli.ts`
- Modify: `package.json`

Suggested disk layout:

```text
D:\DDownload\_state\
  account-url-prefetch-status.json
  download-queue-state.json

D:\DDownload\_queues\
  download_ready_queue.jsonl
  accounts\<safe-account-key>\archive_queue.jsonl
```

Each durable queue record should extend the current `ArchiveQueueRecord` shape:

```json
{
  "queue_id": "sha1(fakeid + source_url)",
  "account_key": "TAGChengdu",
  "account_fakeid": "MjM5NTExMTk3OQ==",
  "account_nickname": "TAGChengdu",
  "token": "t32iH05RdSHqvO1S8QaYCg",
  "source_url": "https://mp.weixin.qq.com/s/...",
  "title": "Article title",
  "post_time": "2026-04-10 07:16:57",
  "post_date": "2026-04-10",
  "page": 1,
  "discovered_at": "2026-04-21T00:00:00.000Z",
  "discovery_source": "mptext-account-prefetch",
  "status": "ready",
  "attempt_count": 0,
  "lease_owner": "",
  "lease_expires_at": "",
  "last_error": ""
}
```

`queue_id` is the idempotency key. Re-running prefetch must not enqueue duplicate downloads for the same account URL.

### State Transitions

URL producer account states:

```text
queued -> listing -> paused_backpressure -> completed
queued -> listing -> rate_limited -> listing
queued -> listing -> failed
```

Download queue item states:

```text
ready -> leased -> downloaded
ready -> leased -> failed_retryable -> ready
ready -> leased -> failed_terminal
leased -> ready
```

`leased -> ready` is used when a worker crashes or a lease expires.

### CLI Contract

Add a producer command:

```powershell
npm run prefetch-account-urls -- --accountsPath D:\DDownload\公众号.json --outDir D:\DDownload --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --accountConcurrency 2 --queueHighWatermark 2000 --resume
```

Add a consumer mode for the existing mptext archive downloader:

```powershell
npm run mptext-archive-batch -- --queuePath D:\DDownload\_queues\download_ready_queue.jsonl --archiveRoot D:\DDownload --endpoint "$env:MPTEXT_BASE_URL" --key "$env:MPTEXT_AUTH_KEY" --concurrency 3 --resume --waitForProducer
```

The old `--manifestPath archive_queue.jsonl` mode should remain for small one-account runs and tests.

### Verification For This Update

- A test proves two accounts can be listed concurrently while each account still pages sequentially.
- A test proves duplicate URLs are not appended twice after `--resume`.
- A test proves a consumer can lease one ready URL and mark it `downloaded`.
- A test proves an expired lease returns to `ready`.
- A smoke run with `--limitAccounts 2` shows download starts before the second account has finished all pages.
- UI plan docs must display producer and consumer states as first-class runtime lanes, not as placeholder counters.

---

## Current Inputs

- Account inventory file: `D:\DDownload\公众号.json`.
- Inventory schema observed:
  - `version = "1.0"`
  - `usefor = "wechat-article-exporter"`
  - `accounts[]` entries contain `fakeid`, `nickname`, `completed`, `count`, `articles`, `total_count`, `round_head_img`, `create_time`, `update_time`, `last_update_time`.
- Inventory totals observed:
  - 63 accounts.
  - 5 completed accounts.
  - 58 incomplete accounts.
  - `articles` sum: 13,789.
  - `total_count` sum: 62,353.
- Largest account targets by current `articles`:
  - `TAGChengdu`: 6,228 articles, completed.
  - `Dada Shanghai`: 2,938 articles, completed.
  - `THE WINDOW CLUB`: 2,347 articles, completed.
  - `THE BOX 盒子黑胶`: 446 articles, completed.
  - `糊游ROAM`: 417 articles, completed.
- Current web UI state:
  - Browser cache/IndexedDB is very large and the page is slow.
  - Do not use the website UI as the operational control surface.
- Current running export:
  - `TAGChengdu` API export is running under `D:\DDownload\TAGChengdu`.
  - It is already API-based and does not require interacting with the slow web UI.
  - Treat it as a smoke run, not as the final architecture.

## Existing Plan Inputs Reviewed

- `docs/superpowers/plans/2026-04-21-mptext-api-private-node-low-cost-plan.md`
  - Strong direction: local private mptext deployment first.
  - Preferred local base URL: `http://127.0.0.1:17300`.
  - API route should replace Playwright/browser bulk capture.
  - VPS/private proxy is optional after local smoke.
- `docs/superpowers/plans/2026-04-21-wechat-cache-export-acceleration.md`
  - Strong direction: manifest-based resume, normalized entity output, content-addressed image cache, optional Cloudflare Worker, and CPU-bounded concurrency.
  - Key correction: current exported HTML/JSON is not enough for offline archival because original image bytes are not saved.

## Revised Decision

Use this backend priority order:

1. Local private mptext node from the other thread, expected base URL similar to `http://127.0.0.1:17300`.
2. User-controlled private API proxy or Cloudflare Worker that forwards to the local/private mptext API.
3. Public `https://down.mptext.top` API only as a temporary fallback.
4. Browser IndexedDB/web UI only for legacy inspection, not bulk export.

Do not build the new system around website clicks, website export dialogs, or Chrome Application panel operations.

---

## File Structure

- Create: `src/accounts/accountInventory.ts`
  - Reads and validates `D:\DDownload\公众号.json`.
  - Converts accounts to stable export jobs.
- Create: `src/accounts/accountScheduler.ts`
  - Orders account jobs, tracks account-level progress, and selects next runnable work.
- Create: `src/mptext/client.ts`
  - Typed mptext API client with base URL priority, auth validation, retry, and rate-limit handling.
- Create: `src/export/runAccountManifestExport.ts`
  - Main API-first batch runner for all accounts in `公众号.json`.
- Create: `src/export/writeArticleBundle.ts`
  - Writes one article directory with `raw.html`, `download.json`, `metadata.json`, `article.normalized.json`, and manifest records.
- Create: `src/export/normalizeArticle.ts`
  - Produces stable key entity JSON from mptext list/detail data.
- Create: `src/assets/extractArticleImageUrls.ts`
  - Extracts image URLs from HTML, detail JSON, and list metadata.
- Create: `src/assets/globalAssetCache.ts`
  - Stores original image bytes once under `D:\DDownload\_asset_cache`.
- Create: `src/state/exportStateStore.ts`
  - Atomic state store under `D:\DDownload\_state`.
- Modify: `tools/exportMptextAccount.mjs`
  - Keep as a single-account compatibility wrapper around the new API-first runner.
- Modify: `src/cli.ts`
  - Add `export-account-manifest` command.
- Modify: `package.json`
  - Add `export:account-manifest` script.
- Create: `docs/API_FIRST_EXPORT_RUNBOOK.md`
  - Human runbook for using local private node and `公众号.json`.
- Tests:
  - `tests/accountInventory.test.ts`
  - `tests/accountScheduler.test.ts`
  - `tests/mptextClient.test.ts`
  - `tests/runAccountManifestExport.test.ts`
  - `tests/writeArticleBundle.test.ts`
  - `tests/globalAssetCache.test.ts`

---

### Task 1: Freeze Browser UI As Non-Operational

**Files:**
- Create: `docs/API_FIRST_EXPORT_RUNBOOK.md`

- [ ] **Step 1: Write the runbook introduction**

Add this exact policy:

```markdown
# API First Export Runbook

## Operating Policy

The website UI is no longer the control surface for bulk export.

Reasons:

- Browser IndexedDB is large and makes the page slow.
- The data is bound to the access domain.
- UI export depends on browser responsiveness and download settings.

Preferred control surface:

1. `D:\DDownload\公众号.json` for account inventory.
2. Local/private mptext API for account/article/content requests.
3. Local filesystem manifests under `D:\DDownload\_state`.
4. Optional private proxy for image fallback.

The browser may still be used to refresh login and inspect data, but not for bulk export execution.
```

- [ ] **Step 2: Document backend priority**

Append:

```markdown
## Backend Priority

Use backends in this order:

1. Local private node from the other deployment thread.
2. Private API proxy controlled by the user.
3. Public `https://down.mptext.top` API.
4. Browser UI only for emergency manual recovery.

Expected local node URL:

```powershell
$env:MPTEXT_BASE_URL = "http://127.0.0.1:17300"
```

If the other thread uses a different port, replace this value.
```

- [ ] **Step 3: Verify docs only**

Run:

```powershell
Test-Path docs\API_FIRST_EXPORT_RUNBOOK.md
```

Expected: `True`.

---

### Task 2: Parse `公众号.json` Into Account Jobs

**Files:**
- Create: `src/accounts/accountInventory.ts`
- Test: `tests/accountInventory.test.ts`

- [ ] **Step 1: Write failing inventory test**

```ts
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { loadAccountInventory } from "../src/accounts/accountInventory.js";

test("loadAccountInventory reads wechat exporter account json", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "wechat-accounts-"));
  const filePath = path.join(root, "公众号.json");
  await writeFile(filePath, JSON.stringify({
    version: "1.0",
    usefor: "wechat-article-exporter",
    accounts: [
      {
        fakeid: "MjM5NTExMTk3OQ==",
        completed: true,
        count: 3423,
        articles: 6228,
        nickname: "TAGChengdu",
        total_count: 3427,
        update_time: 1776758006,
      },
      {
        fakeid: "MzUyNDQwODQ3Ng==",
        completed: false,
        count: 20,
        articles: 37,
        nickname: "OIL油",
        total_count: 2981,
        update_time: 1776670516,
      },
    ],
  }));

  const inventory = await loadAccountInventory(filePath);
  assert.equal(inventory.accounts.length, 2);
  assert.equal(inventory.accounts[0].nickname, "TAGChengdu");
  assert.equal(inventory.accounts[0].expectedArticleCount, 6228);
  assert.equal(inventory.accounts[1].expectedMessageCount, 2981);
  assert.equal(inventory.summary.completedAccounts, 1);
  assert.equal(inventory.summary.incompleteAccounts, 1);
});
```

- [ ] **Step 2: Run test to verify failure**

```powershell
npm test -- tests/accountInventory.test.ts
```

Expected: FAIL with module not found.

- [ ] **Step 3: Implement inventory loader**

Create `src/accounts/accountInventory.ts`:

```ts
import { readFile } from "node:fs/promises";

export interface AccountInventoryEntry {
  fakeid: string;
  nickname: string;
  completed: boolean;
  cachedMessageCount: number;
  cachedArticleCount: number;
  expectedMessageCount: number;
  expectedArticleCount: number;
  roundHeadImg: string;
  updateTime: number;
}

export interface AccountInventory {
  version: string;
  usefor: string;
  accounts: AccountInventoryEntry[];
  summary: {
    accountCount: number;
    completedAccounts: number;
    incompleteAccounts: number;
    cachedArticleCount: number;
    expectedMessageCount: number;
  };
}

export async function loadAccountInventory(filePath: string): Promise<AccountInventory> {
  const raw = JSON.parse(await readFile(filePath, "utf8"));
  const accounts = (raw.accounts || []).map((item: any) => ({
    fakeid: String(item.fakeid || ""),
    nickname: String(item.nickname || item.fakeid || ""),
    completed: Boolean(item.completed),
    cachedMessageCount: Number(item.count || 0),
    cachedArticleCount: Number(item.articles || 0),
    expectedMessageCount: Number(item.total_count || item.count || 0),
    expectedArticleCount: Number(item.articles || 0),
    roundHeadImg: String(item.round_head_img || ""),
    updateTime: Number(item.update_time || 0),
  })).filter((item: AccountInventoryEntry) => item.fakeid && item.nickname);

  return {
    version: String(raw.version || ""),
    usefor: String(raw.usefor || ""),
    accounts,
    summary: {
      accountCount: accounts.length,
      completedAccounts: accounts.filter((item: AccountInventoryEntry) => item.completed).length,
      incompleteAccounts: accounts.filter((item: AccountInventoryEntry) => !item.completed).length,
      cachedArticleCount: accounts.reduce((sum: number, item: AccountInventoryEntry) => sum + item.cachedArticleCount, 0),
      expectedMessageCount: accounts.reduce((sum: number, item: AccountInventoryEntry) => sum + item.expectedMessageCount, 0),
    },
  };
}
```

- [ ] **Step 4: Run test**

```powershell
npm test -- tests/accountInventory.test.ts
```

Expected: PASS.

---

### Task 3: Create Account Scheduler

**Files:**
- Create: `src/accounts/accountScheduler.ts`
- Test: `tests/accountScheduler.test.ts`

- [ ] **Step 1: Write scheduler test**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { buildAccountExportQueue } from "../src/accounts/accountScheduler.js";

test("buildAccountExportQueue prioritizes completed high-article accounts first", () => {
  const queue = buildAccountExportQueue([
    { fakeid: "a", nickname: "Small incomplete", completed: false, cachedArticleCount: 20, expectedArticleCount: 20, expectedMessageCount: 100 },
    { fakeid: "b", nickname: "TAGChengdu", completed: true, cachedArticleCount: 6228, expectedArticleCount: 6228, expectedMessageCount: 3427 },
    { fakeid: "c", nickname: "Dada Shanghai", completed: true, cachedArticleCount: 2938, expectedArticleCount: 2938, expectedMessageCount: 1361 },
  ] as any);

  assert.deepEqual(queue.map((item) => item.nickname), ["TAGChengdu", "Dada Shanghai", "Small incomplete"]);
  assert.equal(queue[0].priority, "completed-large");
  assert.equal(queue[2].priority, "incomplete-needs-discovery");
});
```

- [ ] **Step 2: Implement scheduler**

Create `src/accounts/accountScheduler.ts`:

```ts
import type { AccountInventoryEntry } from "./accountInventory.js";

export interface AccountExportJob extends AccountInventoryEntry {
  priority: "completed-large" | "completed" | "incomplete-needs-discovery";
}

export function buildAccountExportQueue(accounts: AccountInventoryEntry[]): AccountExportJob[] {
  return accounts.map((account) => ({
    ...account,
    priority: account.completed
      ? account.cachedArticleCount >= 1000 ? "completed-large" : "completed"
      : "incomplete-needs-discovery",
  })).sort((left, right) => {
    const rank = (job: AccountExportJob) => job.priority === "completed-large" ? 0 : job.priority === "completed" ? 1 : 2;
    return rank(left) - rank(right) || right.cachedArticleCount - left.cachedArticleCount || left.nickname.localeCompare(right.nickname);
  });
}
```

- [ ] **Step 3: Run test**

```powershell
npm test -- tests/accountScheduler.test.ts
```

Expected: PASS.

---

### Task 4: Validate Private API Backend Before Any Export

**Files:**
- Create: `src/mptext/client.ts`
- Test: `tests/mptextClient.test.ts`

- [ ] **Step 1: Write backend validation test**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { MptextClient } from "../src/mptext/client.js";

test("MptextClient validates authkey before export", async () => {
  const client = new MptextClient({
    baseUrl: "http://127.0.0.1:17300",
    authKey: "key",
    fetchImpl: async (url, init) => {
      assert.equal(String(url), "http://127.0.0.1:17300/api/public/v1/authkey");
      assert.equal((init?.headers as any)["X-Auth-Key"], "key");
      return new Response(JSON.stringify({ code: 0, authKey: "key" }), { status: 200 });
    },
  });
  await client.validateAuthKey();
});
```

- [ ] **Step 2: Implement minimum client**

Implement `src/mptext/client.ts` with:

```ts
export class MptextClient {
  private readonly baseUrl: string;
  private readonly authKey: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { baseUrl: string; authKey: string; fetchImpl?: typeof fetch }) {
    this.baseUrl = options.baseUrl.replace(/\/+$/g, "");
    this.authKey = options.authKey;
    this.fetchImpl = options.fetchImpl || fetch;
  }

  async validateAuthKey(): Promise<void> {
    const payload = await this.getJson("/api/public/v1/authkey");
    if (payload.code !== 0 && payload?.base_resp?.ret !== 0) {
      throw new Error("mptext auth key is invalid or expired");
    }
  }

  async getJson(pathAndQuery: string): Promise<any> {
    const response = await this.fetchImpl(`${this.baseUrl}${pathAndQuery}`, {
      headers: { "X-Auth-Key": this.authKey },
    });
    const text = await response.text();
    if (!response.ok) throw new Error(`mptext HTTP ${response.status}: ${text.slice(0, 200)}`);
    return JSON.parse(text);
  }
}
```

- [ ] **Step 3: Add real validation command to runbook**

Document:

```powershell
$env:MPTEXT_BASE_URL = "http://127.0.0.1:17300"
$env:MPTEXT_AUTH_KEY = "<current-key-from-private-node-api-page>"
Invoke-RestMethod -Headers @{"X-Auth-Key"=$env:MPTEXT_AUTH_KEY} "$env:MPTEXT_BASE_URL/api/public/v1/authkey"
```

Expected: valid response from the private node.

- [ ] **Step 4: Run tests**

```powershell
npm test -- tests/mptextClient.test.ts
npm run build
```

Expected: PASS and build succeeds.

---

### Task 5: Implement Account Manifest Export Command

**Files:**
- Create: `src/export/runAccountManifestExport.ts`
- Create: `src/export/writeArticleBundle.ts`
- Create: `src/export/normalizeArticle.ts`
- Create: `src/state/exportStateStore.ts`
- Modify: `src/cli.ts`
- Modify: `package.json`
- Test: `tests/runAccountManifestExport.test.ts`
- Test: `tests/writeArticleBundle.test.ts`

- [ ] **Step 1: Write bundle output test**

```ts
import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { writeArticleBundle } from "../src/export/writeArticleBundle.js";

test("writeArticleBundle writes html json metadata and normalized entity", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "wechat-bundle-"));
  const bundle = await writeArticleBundle({
    outDir: root,
    account: { fakeid: "fake", nickname: "TAGChengdu", completed: true } as any,
    article: { aid: "1_1", title: "A/B", link: "https://mp.weixin.qq.com/s/a", update_time: 1775795817 } as any,
    html: "<!doctype html><html><body id=\"js_content\">A<img data-src=\"https://mmbiz.qpic.cn/a/0?wx_fmt=jpeg\"></body></html>",
    detailJson: { title: "A/B", content_noencode: "<p>A</p>", nick_name: "TAGChengdu", link: "https://mp.weixin.qq.com/s/a" },
  });

  assert.equal(JSON.parse(await readFile(path.join(bundle.articleDir, "download.json"), "utf8")).title, "A/B");
  assert.equal(JSON.parse(await readFile(path.join(bundle.articleDir, "article.normalized.json"), "utf8")).account.nickname, "TAGChengdu");
  assert.equal((await readFile(path.join(bundle.articleDir, "raw.html"), "utf8")).includes("js_content"), true);
});
```

- [ ] **Step 2: Implement bundle writer**

Required output per article:

```text
D:\DDownload\<nickname>\<YYYY-MM-DD>_<safe-title>_<aid>\
  raw.html
  download.json
  metadata.json
  article.normalized.json
  _export_item_manifest.json
```

`_export_item_manifest.json` must include:

```json
{
  "schemaVersion": 1,
  "status": "ok",
  "articleId": "2651506855_1",
  "files": {
    "raw.html": { "bytes": 64748, "sha256": "..." },
    "download.json": { "bytes": 85488, "sha256": "..." },
    "metadata.json": { "bytes": 1711, "sha256": "..." },
    "article.normalized.json": { "bytes": 1234, "sha256": "..." }
  }
}
```

- [ ] **Step 3: Write account manifest export test**

Test behavior:

- Reads `公众号.json`.
- Validates backend once.
- Exports only first N jobs when `--limitAccounts` is set.
- Skips verified article bundles on resume.
- Writes state under `D:\DDownload\_state` or injected test state root.

- [ ] **Step 4: Implement runner**

Command contract:

```powershell
npm run export:account-manifest -- --accountsPath D:\DDownload\公众号.json --outDir D:\DDownload --endpoint http://127.0.0.1:17300 --key "$env:MPTEXT_AUTH_KEY" --formats html,json --resume --concurrency 3 --limitAccounts 1
```

Runner behavior:

1. Load account inventory.
2. Build account queue.
3. Validate private API backend once.
4. For each account:
   - Use `fakeid` directly.
   - Fetch all article pages through API.
   - Download `html` and `json` for each article.
   - Write article bundle.
   - Update account state every article.
5. Continue after single-article failures.
6. Stop account after repeated frequency-control failures and persist retry state.

- [ ] **Step 5: Add scripts**

Add to `package.json`:

```json
"export:account-manifest": "tsx src/cli.ts export-account-manifest"
```

- [ ] **Step 6: Run tests**

```powershell
npm test -- tests/accountInventory.test.ts tests/accountScheduler.test.ts tests/mptextClient.test.ts tests/writeArticleBundle.test.ts tests/runAccountManifestExport.test.ts
npm run build
```

Expected: PASS and build succeeds.

---

### Task 6: Add Original Image Cache As A Separate Stage

**Files:**
- Create: `src/assets/extractArticleImageUrls.ts`
- Create: `src/assets/globalAssetCache.ts`
- Modify: `src/cli.ts`
- Test: `tests/globalAssetCache.test.ts`

- [ ] **Step 1: Keep image stage separate from HTML/JSON export**

Policy:

```text
Do not block article HTML/JSON export on image failures.
Run image caching after article bundles exist.
```

Reason:

- API content export is the fastest reliable base layer.
- Images are numerous and more likely to hit CDN/proxy limits.
- Keeping images separate makes retries cheaper.

- [ ] **Step 2: Add command contract**

```powershell
npm run cache-account-images -- --inputDir D:\DDownload --account TAGChengdu --cacheDir D:\DDownload\_asset_cache --concurrency 6 --resume
```

Optional private proxy:

```powershell
npm run cache-account-images -- --inputDir D:\DDownload --account TAGChengdu --cacheDir D:\DDownload\_asset_cache --proxyEndpoint https://<worker-or-local-proxy>/proxy --proxyAuth "$env:PRIVATE_PROXY_TOKEN" --concurrency 6 --resume
```

- [ ] **Step 3: Acceptance for image stage**

For each article with images:

- `assets_local.json` exists.
- Each `ok` asset has `remoteUrl`, `contentType`, `size`, `sha256`, `cachePath`.
- `cachePath` points to a real image file under `D:\DDownload\_asset_cache`.
- Duplicate image bytes are stored once.

---

### Task 7: CPU/GPU Acceleration Policy

**Files:**
- Modify: `docs/API_FIRST_EXPORT_RUNBOOK.md`

- [ ] **Step 1: Document CPU settings**

Add:

```markdown
## Concurrency Defaults

- Account discovery: 1 account at a time.
- Article page listing: sequential per account, with delay and rate-limit backoff.
- Article HTML/JSON download: 2 to 4 concurrent requests.
- Image cache: 4 to 8 concurrent requests, preferably through private proxy if direct fetch fails.
- Markdown/LLM conversion: CPU worker count can be `logicalCpuCount - 2`.
```

- [ ] **Step 2: Document GPU settings**

Add:

```markdown
## GPU Policy

GPU does not accelerate API calls, browser waiting, JSON writing, or normal HTML parsing.

Use GPU only after original images are cached, for:

- OCR on event posters.
- Visual entity extraction from posters.
- Image classification or duplicate detection beyond sha256.
- Local vision model or local LLM extraction.

Do not make GPU a dependency of the base export path.
```

---

### Task 8: Verification Matrix

**Files:**
- Create: `docs/API_FIRST_EXPORT_VERIFICATION.md`

- [ ] **Step 1: Define account-level checks**

Write:

```markdown
# API First Export Verification

## Account Checks

For each account in `公众号.json`:

- account directory exists under `D:\DDownload\<nickname>`.
- `_articles.json` or account state exists.
- discovered article count is recorded.
- exported article bundle count is recorded.
- failures are listed with article URL and error.

Completed accounts should reach the `articles` value from `公众号.json` unless the API returns fewer articles.
Incomplete accounts should record both current exported count and remaining `total_count - count` as discovery debt.
```

- [ ] **Step 2: Define article-level checks**

Write:

```markdown
## Article Checks

Each article bundle must contain:

- `raw.html`
- `download.json`
- `metadata.json`
- `article.normalized.json`
- `_export_item_manifest.json`

Each file must be non-empty and listed in `_export_item_manifest.json` with byte count and sha256.
```

- [ ] **Step 3: Define image-level checks**

Write:

```markdown
## Image Checks

Image cache is complete for an article when:

- `assets_local.json` exists.
- every extracted image URL has status `ok`, `skipped-duplicate`, or `failed`.
- every `ok` record points to an existing file in `D:\DDownload\_asset_cache`.
```

---

## Revised Execution Order

1. Do not operate the slow website UI for bulk work.
2. Wait for the other thread to finish local private node deployment and provide:
   - base URL
   - current API key
   - whether it exposes public-compatible `/api/public/v1/*`
3. Validate backend with `/api/public/v1/authkey`.
4. Implement `accountInventory` and `accountScheduler`.
5. Implement typed `MptextClient`.
6. Implement `runAccountUrlPrefetch` and `downloadQueueStore`.
7. Run a two-account smoke proving the URL producer can feed the download queue while still listing later pages.
8. Implement or adapt `mptext-archive-batch` consumer mode so download workers lease from the durable queue.
9. Implement `export-account-manifest` / article bundle writing on top of the queue-fed download results.
10. Verify counts and bundle structure.
11. Add image cache stage.
12. Scale to the five completed accounts.
13. Scale to incomplete accounts only after completed accounts pass verification.

## Acceptance Criteria

- The browser UI is not required for bulk export.
- `D:\DDownload\公众号.json` is the source of account jobs.
- The local private node is the preferred API backend.
- All account URLs can be prefetched asynchronously into one durable queue.
- Download workers can consume that queue while URL discovery is still running.
- Queue records are idempotent and support leases, retries, and stale-lease recovery.
- Every exported article has HTML, raw detail JSON, list metadata, normalized entity JSON, and a manifest.
- Original images are handled by a separate resumable cache stage.
- CPU concurrency is bounded and configurable.
- GPU is only used for optional OCR/vision after images are cached.
- Verification reports account-level, article-level, and image-level completeness.

## Self-Review

- Spec coverage: This plan uses the new account JSON, incorporates the local private node being deployed elsewhere, avoids the slow web UI, prioritizes API calls, and keeps execution gated until after planning.
- Placeholder scan: Each task names concrete files, commands, output paths, and acceptance criteria.
- Type consistency: Account inventory, scheduler, mptext client, bundle writer, and state store names are consistent across tasks.

Plan complete and saved to `docs/superpowers/plans/2026-04-21-account-json-api-first-export-redesign.md`. Execution should wait until you confirm the local private node base URL and API key from the other thread.
