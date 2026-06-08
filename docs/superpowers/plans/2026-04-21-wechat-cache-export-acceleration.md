<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat Cache Export Acceleration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable, verifiable WeChat article export pipeline that saves article HTML, raw API JSON, normalized key entities, original images, and cache manifests under `D:\DDownload\<account>\...`.

**Architecture:** Keep `down.mptext.top` as the discovery/content API source, then add local manifest-driven caching, content-addressed image retention, normalized entity files, and optional Cloudflare Worker proxy support. Use CPU concurrency for parsing, hashing, and I/O-bound downloads; reserve GPU only for later OCR/vision stages.

**Tech Stack:** Node.js 22, TypeScript, existing CLI in `src/cli.ts`, existing archive/export pipeline, Cloudflare Workers for private proxy, Node test runner via `npm test`.

---

## Current Evidence

- Current export target: `D:\DDownload\TAGChengdu`.
- Current sample structure is correct at the top level: one account directory, one directory per article.
- Sample article directories contain `raw.html`, `download.json`, and `metadata.json`.
- `raw.html` includes complete article HTML and `id="js_content"`.
- `download.json` includes `content_noencode`, `nick_name`, `user_name`, `alias`, `title`, `link`, `cdn_url`, `comment_id`, `extra_comment_id`, `segment_comment_id`, and related raw fields.
- No original image files are saved yet. Sample HTML has remote `mmbiz.qpic.cn` references only.
- Comment body data is not saved. Only comment IDs and flags are present.
- Official mptext docs state that article data is stored in browser IndexedDB and bound to the access domain. They also state private proxy nodes help with WeChat article/image cross-origin and anti-hotlinking limits, and public proxy nodes share request quotas.

## File Structure

- Create: `src/export/mptextArticleModel.ts`
  - Normalizes mptext list/detail records into stable local entity objects.
- Create: `src/export/mptextAccountExporter.ts`
  - Moves export logic out of `tools/exportMptextAccount.mjs` into testable TypeScript.
- Modify: `tools/exportMptextAccount.mjs`
  - Keep as a thin CLI wrapper around the TypeScript exporter or preserve behavior until the TS CLI is ready.
- Create: `src/cache/cacheManifest.ts`
  - Atomic JSON writes, sha256 helpers, manifest validation, and file integrity checks.
- Create: `src/assets/extractArticleImageUrls.ts`
  - Extracts image URLs from `raw.html`, `content_noencode`, `metadata.json`, covers, and picture lists.
- Create: `src/assets/globalAssetCache.ts`
  - Downloads images into a content-addressed cache and records per-article asset mappings.
- Modify: `src/archive/downloadArticleAssets.ts`
  - Use global cache, retry, sha256 validation, and optional proxy endpoint.
- Modify: `src/archive/runAssetDownloadBatch.ts`
  - Treat `assets_local.json` as a verified manifest, not a simple existence marker.
- Modify: `src/pipeline/runDualTrackBatch.ts`
  - Add artifact manifest verification and optional CPU concurrency.
- Modify: `src/pipeline/processArticleDualTrack.ts`
  - Add MarkItDown cache key support.
- Modify: `src/pipeline/processArchiveBundleDualTrack.ts`
  - Add artifact manifest writes for archive bundles.
- Modify: `src/pipeline/runLlmExportBatch.ts`
  - Replace full mirror deletion with incremental sync.
- Modify: `src/cli.ts`
  - Add `--concurrency`, `--cacheDir`, `--assetProxyEndpoint`, `--proxyAuth`, and `--retryFailedOnly` where relevant.
- Create: `cloudflare/mptext-proxy-worker/src/index.ts`
  - Private Worker proxy with auth, host allowlist, cache policy, and streaming responses.
- Create: `cloudflare/mptext-proxy-worker/wrangler.jsonc`
  - Worker deployment config.
- Test: `tests/mptextArticleModel.test.ts`
- Test: `tests/cacheManifest.test.ts`
- Test: `tests/exportMptextAccount.test.ts`
- Test: `tests/extractArticleImageUrls.test.ts`
- Test: `tests/globalAssetCache.test.ts`
- Modify: `tests/downloadArticleAssets.test.ts`
- Modify: `tests/runDualTrackBatch.test.ts`
- Create: `tests/cloudflareProxyWorker.test.ts`

---

### Task 1: Normalize Article Entity Output

**Files:**
- Create: `src/export/mptextArticleModel.ts`
- Test: `tests/mptextArticleModel.test.ts`

- [ ] **Step 1: Write the failing normalization test**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { normalizeMptextArticle, safeArticleDirectoryName } from "../src/export/mptextArticleModel.js";

test("normalizeMptextArticle combines list and detail fields into a stable entity", () => {
  const listItem = {
    aid: "2651506855_1",
    title: "T² RECAP：4.5 T² 12 to O Anniversary 终章即序章 w/ Helena Hauff",
    link: "https://mp.weixin.qq.com/s/t32iH05RdSHqvO1S8QaYCg",
    update_time: 1775795817,
    author_name: "",
    cover: "https://mmbiz.qpic.cn/cover/0?wx_fmt=jpeg",
    appmsgid: 2651506855,
    itemidx: 1,
  };
  const detail = {
    nick_name: "TAGChengdu",
    user_name: "gh_cf5dd0b64d9b",
    alias: "TAG_Chengdu",
    title: listItem.title,
    link: listItem.link,
    author: "",
    content_noencode: "<section><img data-src=\"https://mmbiz.qpic.cn/a/0?wx_fmt=jpeg\"></section>",
    cdn_url: "https://mmbiz.qpic.cn/detail/0?wx_fmt=jpeg",
    comment_id: "123",
    extra_comment_id: "456",
    segment_comment_id: "789",
    show_comment: 0,
  };

  const entity = normalizeMptextArticle({
    account: { fakeid: "MjM5NTExMTk3OQ==", nickname: "TAGChengdu", alias: "TAG_Chengdu" },
    listItem,
    detail,
  });

  assert.equal(entity.account.nickname, "TAGChengdu");
  assert.equal(entity.article.aid, "2651506855_1");
  assert.equal(entity.article.title, listItem.title);
  assert.equal(entity.article.publishTimeIso, "2026-04-10T07:16:57.000Z");
  assert.equal(entity.article.link, listItem.link);
  assert.equal(entity.content.html.length > 20, true);
  assert.deepEqual(entity.comments, {
    available: false,
    showComment: 0,
    ids: { commentId: "123", extraCommentId: "456", segmentCommentId: "789" },
  });
  assert.equal(entity.images.coverUrls.includes("https://mmbiz.qpic.cn/cover/0?wx_fmt=jpeg"), true);
  assert.equal(safeArticleDirectoryName(entity), "2026-04-10_T² RECAP：4.5 T² 12 to O Anniversary 终章即序章 w_ Helena Hauff_2651506855_1");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
npm test -- tests/mptextArticleModel.test.ts
```

Expected: FAIL with module not found for `src/export/mptextArticleModel.js`.

- [ ] **Step 3: Implement normalization**

Create `src/export/mptextArticleModel.ts`:

```ts
export interface MptextAccountRef {
  fakeid: string;
  nickname: string;
  alias?: string;
}

export interface NormalizedMptextArticle {
  schemaVersion: 1;
  account: MptextAccountRef;
  article: {
    aid: string;
    appmsgid?: number;
    itemidx?: number;
    title: string;
    author: string;
    publishTimeUnix: number;
    publishTimeIso: string;
    link: string;
    sourceUrl: string;
    digest: string;
  };
  content: {
    html: string;
    text: string;
  };
  images: {
    coverUrls: string[];
    inlineRemoteUrls: string[];
  };
  comments: {
    available: boolean;
    showComment: number;
    ids: {
      commentId: string;
      extraCommentId: string;
      segmentCommentId: string;
    };
  };
  raw: {
    listKeys: string[];
    detailKeys: string[];
  };
}

export function normalizeMptextArticle(input: {
  account: MptextAccountRef;
  listItem: Record<string, any>;
  detail: Record<string, any>;
}): NormalizedMptextArticle {
  const publishTimeUnix = Number(input.listItem.update_time || input.listItem.create_time || input.detail.ori_create_time || input.detail.create_time || 0);
  const html = String(input.detail.content_noencode || "");
  return {
    schemaVersion: 1,
    account: input.account,
    article: {
      aid: String(input.listItem.aid || `${input.listItem.appmsgid || input.detail.mid || "article"}_${input.listItem.itemidx || input.detail.idx || 1}`),
      appmsgid: numberOrUndefined(input.listItem.appmsgid || input.detail.mid),
      itemidx: numberOrUndefined(input.listItem.itemidx || input.detail.idx),
      title: String(input.detail.title || input.listItem.title || ""),
      author: String(input.detail.author || input.listItem.author_name || ""),
      publishTimeUnix,
      publishTimeIso: publishTimeUnix > 0 ? new Date(publishTimeUnix * 1000).toISOString() : "",
      link: String(input.detail.link || input.listItem.link || ""),
      sourceUrl: String(input.detail.source_url || ""),
      digest: String(input.listItem.digest || input.detail.desc || ""),
    },
    content: {
      html,
      text: html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(),
    },
    images: {
      coverUrls: uniqueStrings([input.listItem.cover, input.listItem.cover_img, input.detail.cdn_url, input.detail.cdn_url_235_1]),
      inlineRemoteUrls: extractMmbizUrls(html),
    },
    comments: {
      available: false,
      showComment: Number(input.detail.show_comment || 0),
      ids: {
        commentId: String(input.detail.comment_id || ""),
        extraCommentId: String(input.detail.extra_comment_id || ""),
        segmentCommentId: String(input.detail.segment_comment_id || ""),
      },
    },
    raw: {
      listKeys: Object.keys(input.listItem).sort(),
      detailKeys: Object.keys(input.detail).sort(),
    },
  };
}

export function safeArticleDirectoryName(entity: NormalizedMptextArticle): string {
  const date = entity.article.publishTimeIso ? entity.article.publishTimeIso.slice(0, 10) : "unknown-date";
  return `${date}_${sanitizePathPart(entity.article.title, 96)}_${sanitizePathPart(entity.article.aid, 48)}`;
}

function extractMmbizUrls(html: string): string[] {
  const matches = html.match(/https?:\/\/[^"'<>\\s]+(?:mmbiz|qpic)[^"'<>\\s]*/g) || [];
  return uniqueStrings(matches);
}

function uniqueStrings(values: unknown[]): string[] {
  return Array.from(new Set(values.map((value) => String(value || "").trim()).filter(Boolean)));
}

function sanitizePathPart(value: string, maxLength: number): string {
  return (value || "untitled")
    .replace(/[<>:"/\\|?*\x00-\x1F]/g, "_")
    .replace(/\s+/g, " ")
    .replace(/[. ]+$/g, "")
    .trim()
    .slice(0, maxLength) || "untitled";
}

function numberOrUndefined(value: unknown): number | undefined {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : undefined;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
npm test -- tests/mptextArticleModel.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit when working in a real git checkout**

Run only in a repository where `git status --short --branch` succeeds:

```powershell
git add src/export/mptextArticleModel.ts tests/mptextArticleModel.test.ts
git commit -m "feat: normalize mptext article entities"
```

---

### Task 2: Add Manifest and Integrity Helpers

**Files:**
- Create: `src/cache/cacheManifest.ts`
- Test: `tests/cacheManifest.test.ts`

- [ ] **Step 1: Write the failing manifest test**

```ts
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { sha256File, writeJsonAtomic, verifyFileIntegrity } from "../src/cache/cacheManifest.js";

test("manifest helpers write atomically and verify sha256", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "wechat-cache-manifest-"));
  const target = path.join(root, "manifest.json");
  await writeJsonAtomic(target, { ok: true });
  assert.deepEqual(JSON.parse(await readFile(target, "utf8")), { ok: true });

  const dataFile = path.join(root, "raw.html");
  await writeFile(dataFile, "<html>ok</html>");
  const digest = await sha256File(dataFile);
  assert.equal(await verifyFileIntegrity(dataFile, { minBytes: 10, sha256: digest }), true);
  await writeFile(dataFile, "bad");
  assert.equal(await verifyFileIntegrity(dataFile, { minBytes: 10, sha256: digest }), false);
});
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
npm test -- tests/cacheManifest.test.ts
```

Expected: FAIL with module not found.

- [ ] **Step 3: Implement helper module**

Create `src/cache/cacheManifest.ts`:

```ts
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, rename, stat, writeFile } from "node:fs/promises";
import path from "node:path";

export async function writeJsonAtomic(filePath: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(tempPath, filePath);
}

export async function sha256File(filePath: string): Promise<string> {
  const hash = createHash("sha256");
  await new Promise<void>((resolve, reject) => {
    createReadStream(filePath)
      .on("data", (chunk) => hash.update(chunk))
      .on("error", reject)
      .on("end", resolve);
  });
  return hash.digest("hex");
}

export async function verifyFileIntegrity(
  filePath: string,
  expected: { minBytes?: number; sha256?: string },
): Promise<boolean> {
  try {
    const info = await stat(filePath);
    if (expected.minBytes !== undefined && info.size < expected.minBytes) return false;
    if (expected.sha256 !== undefined && (await sha256File(filePath)) !== expected.sha256) return false;
    return true;
  } catch {
    return false;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
npm test -- tests/cacheManifest.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit when working in a real git checkout**

```powershell
git add src/cache/cacheManifest.ts tests/cacheManifest.test.ts
git commit -m "feat: add cache manifest integrity helpers"
```

---

### Task 3: Make Mptext Export Fully Resumable

**Files:**
- Create: `src/export/mptextAccountExporter.ts`
- Modify: `tools/exportMptextAccount.mjs`
- Test: `tests/exportMptextAccount.test.ts`

- [ ] **Step 1: Write the failing export-resume test**

```ts
import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { runMptextAccountExport } from "../src/export/mptextAccountExporter.js";

test("mptext export caches pages and skips verified existing formats", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "wechat-mptext-export-"));
  const calls: string[] = [];
  const fetchImpl = async (url: string) => {
    calls.push(url);
    if (url.includes("/account?")) {
      return jsonResponse({ base_resp: { ret: 0 }, list: [{ fakeid: "fake", nickname: "TAGChengdu", alias: "TAG_Chengdu" }] });
    }
    if (url.includes("/article?")) {
      return jsonResponse({ base_resp: { ret: 0 }, articles: [{ aid: "1_1", title: "A", link: "https://mp.weixin.qq.com/s/a", update_time: 1775795817 }] });
    }
    if (url.includes("format=html")) return textResponse("<!doctype html><html><body id=\"js_content\">A</body></html>");
    if (url.includes("format=json")) return textResponse(JSON.stringify({ title: "A", content_noencode: "<p>A</p>", link: "https://mp.weixin.qq.com/s/a" }));
    throw new Error(url);
  };

  await runMptextAccountExport({
    account: "TAGChengdu",
    outDir: root,
    key: "test-key",
    formats: ["html", "json"],
    fetchImpl,
    listDelayMs: 0,
    concurrency: 1,
  });
  const firstCallCount = calls.length;
  await runMptextAccountExport({
    account: "TAGChengdu",
    outDir: root,
    key: "test-key",
    formats: ["html", "json"],
    fetchImpl,
    listDelayMs: 0,
    concurrency: 1,
  });

  const manifest = JSON.parse(await readFile(path.join(root, "TAGChengdu", "_export_manifest.json"), "utf8"));
  assert.equal(manifest.articles["1_1"].formats.html.status, "ok");
  assert.equal(manifest.articles["1_1"].formats.json.status, "ok");
  assert.equal(calls.length, firstCallCount + 2);
});

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { "content-type": "application/json" } });
}

function textResponse(value: string): Response {
  return new Response(value, { status: 200, headers: { "content-type": "text/plain" } });
}
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
npm test -- tests/exportMptextAccount.test.ts
```

Expected: FAIL with module not found.

- [ ] **Step 3: Implement exporter library**

Implement `src/export/mptextAccountExporter.ts` with these exported contracts:

```ts
export interface MptextExportOptions {
  account: string;
  outDir: string;
  key: string;
  endpoint?: string;
  formats: Array<"html" | "json" | "markdown" | "text">;
  concurrency: number;
  listDelayMs: number;
  rateLimitDelayMs?: number;
  fetchImpl?: typeof fetch;
}

export interface MptextExportResult {
  accountDir: string;
  discovered: number;
  written: number;
  skipped: number;
  failed: number;
}

export async function runMptextAccountExport(options: MptextExportOptions): Promise<MptextExportResult> {
  // Move the proven logic from tools/exportMptextAccount.mjs here.
  // Required behaviors:
  // 1. write history page cache under _history_pages/page-0001.json
  // 2. write _articles.partial.json every page batch
  // 3. write _export_manifest.json after each article
  // 4. verify raw.html has <!doctype/html/js_content or non-empty body
  // 5. verify download.json parses and has content_noencode or title
  // 6. skip only verified format files
  // 7. retry ret 200013 with rateLimitDelayMs
  throw new Error("runMptextAccountExport not implemented");
}
```

Replace the thrown error with the current `tools/exportMptextAccount.mjs` implementation, using `writeJsonAtomic`, `sha256File`, and `verifyFileIntegrity` from `src/cache/cacheManifest.ts`.

- [ ] **Step 4: Keep the current CLI path working**

Modify `tools/exportMptextAccount.mjs` so it parses arguments and calls `runMptextAccountExport`. Keep support for:

```powershell
node tools/exportMptextAccount.mjs --account TAGChengdu --outDir D:\DDownload --formats html,json --concurrency 3 --listDelayMs 2500 --rateLimitDelayMs 180000
```

Expected behavior: existing output layout stays compatible.

- [ ] **Step 5: Run focused tests**

```powershell
npm test -- tests/cacheManifest.test.ts tests/mptextArticleModel.test.ts tests/exportMptextAccount.test.ts
npm run build
```

Expected: all focused tests pass and TypeScript build succeeds.

- [ ] **Step 6: Commit when working in a real git checkout**

```powershell
git add src/export/mptextAccountExporter.ts tools/exportMptextAccount.mjs tests/exportMptextAccount.test.ts
git commit -m "feat: make mptext export resumable"
```

---

### Task 4: Save Original Images Locally

**Files:**
- Create: `src/assets/extractArticleImageUrls.ts`
- Create: `src/assets/globalAssetCache.ts`
- Modify: `src/archive/downloadArticleAssets.ts`
- Modify: `src/archive/runAssetDownloadBatch.ts`
- Test: `tests/extractArticleImageUrls.test.ts`
- Test: `tests/globalAssetCache.test.ts`
- Modify: `tests/downloadArticleAssets.test.ts`

- [ ] **Step 1: Write image URL extraction test**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { extractArticleImageUrls } from "../src/assets/extractArticleImageUrls.js";

test("extractArticleImageUrls reads covers, data-src, src, and json picture fields", () => {
  const urls = extractArticleImageUrls({
    html: "<img data-src=\"https://mmbiz.qpic.cn/a/640?wx_fmt=jpeg\"><img src=\"https://mmbiz.qpic.cn/b/640?wx_fmt=png\">",
    detail: { cdn_url: "https://mmbiz.qpic.cn/c/0?wx_fmt=jpeg", picture_page_info_list: [{ cdn_url: "https://mmbiz.qpic.cn/d/0?wx_fmt=webp" }] },
    metadata: { cover: "https://mmbiz.qpic.cn/e/0?wx_fmt=jpeg" },
  });
  assert.deepEqual(urls.sort(), [
    "https://mmbiz.qpic.cn/a/640?wx_fmt=jpeg",
    "https://mmbiz.qpic.cn/b/640?wx_fmt=png",
    "https://mmbiz.qpic.cn/c/0?wx_fmt=jpeg",
    "https://mmbiz.qpic.cn/d/0?wx_fmt=webp",
    "https://mmbiz.qpic.cn/e/0?wx_fmt=jpeg",
  ].sort());
});
```

- [ ] **Step 2: Implement extractor**

```ts
export function extractArticleImageUrls(input: {
  html?: string;
  detail?: Record<string, any>;
  metadata?: Record<string, any>;
}): string[] {
  const urls = new Set<string>();
  const add = (value: unknown) => {
    const text = String(value || "").trim().replace(/&amp;/g, "&");
    if (/^https?:\/\/[^/]*(mmbiz|qpic)/i.test(text)) urls.add(text);
  };
  for (const match of String(input.html || "").matchAll(/(?:data-src|src)=["']([^"']+)["']/gi)) add(match[1]);
  for (const key of ["cover", "cover_img", "pic_cdn_url_235_1", "pic_cdn_url_16_9", "pic_cdn_url_3_4", "pic_cdn_url_1_1"]) add(input.metadata?.[key]);
  for (const key of ["cdn_url", "cdn_url_235_1", "cdn_url_16_9", "cdn_url_3_4"]) add(input.detail?.[key]);
  for (const item of input.detail?.picture_page_info_list || []) add(item?.cdn_url || item?.url);
  return Array.from(urls);
}
```

- [ ] **Step 3: Write global asset cache test**

```ts
import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { cacheRemoteAsset } from "../src/assets/globalAssetCache.js";

test("cacheRemoteAsset stores identical bytes once and returns sha256 mapping", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "wechat-asset-cache-"));
  let fetchCount = 0;
  const fetchImpl = async () => {
    fetchCount += 1;
    return new Response(Buffer.from("image-bytes"), { status: 200, headers: { "content-type": "image/jpeg" } });
  };
  const first = await cacheRemoteAsset({ url: "https://mmbiz.qpic.cn/a/0?wx_fmt=jpeg", cacheRoot: root, fetchImpl });
  const second = await cacheRemoteAsset({ url: "https://mmbiz.qpic.cn/a/0?wx_fmt=jpeg", cacheRoot: root, fetchImpl });
  assert.equal(first.sha256, second.sha256);
  assert.equal(fetchCount, 1);
  assert.equal(await readFile(first.cachePath, "utf8"), "image-bytes");
});
```

- [ ] **Step 4: Implement content-addressed asset cache**

Create `src/assets/globalAssetCache.ts`:

```ts
import { createHash } from "node:crypto";
import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import path from "node:path";

export interface CachedAsset {
  remoteUrl: string;
  contentType: string;
  size: number;
  sha256: string;
  cachePath: string;
}

export async function cacheRemoteAsset(input: {
  url: string;
  cacheRoot: string;
  fetchImpl?: typeof fetch;
  proxyEndpoint?: string;
  proxyAuth?: string;
}): Promise<CachedAsset> {
  const fetcher = input.fetchImpl || fetch;
  const indexPath = path.join(input.cacheRoot, "remote-url-index", `${hashText(input.url)}.json`);
  try {
    const cached = JSON.parse(await readFile(indexPath, "utf8")) as CachedAsset;
    await stat(cached.cachePath);
    return cached;
  } catch {
    const requestUrl = input.proxyEndpoint ? buildProxyUrl(input.proxyEndpoint, input.url, input.proxyAuth) : input.url;
    const response = await fetcher(requestUrl, { headers: { referer: "https://mp.weixin.qq.com/" } });
    if (!response.ok) throw new Error(`asset HTTP ${response.status} ${response.statusText}`);
    const contentType = response.headers.get("content-type") || "application/octet-stream";
    if (!/^image\//i.test(contentType)) throw new Error(`asset content-type not image: ${contentType}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    const sha256 = hashBytes(bytes);
    const ext = extensionForContentType(contentType, input.url);
    const cachePath = path.join(input.cacheRoot, "images", sha256.slice(0, 2), sha256.slice(2, 4), `${sha256}${ext}`);
    await mkdir(path.dirname(cachePath), { recursive: true });
    const tempPath = `${cachePath}.${process.pid}.tmp`;
    await writeFile(tempPath, bytes);
    await rename(tempPath, cachePath);
    const record = { remoteUrl: input.url, contentType, size: bytes.length, sha256, cachePath };
    await mkdir(path.dirname(indexPath), { recursive: true });
    await writeFile(indexPath, `${JSON.stringify(record, null, 2)}\n`);
    return record;
  }
}

function buildProxyUrl(endpoint: string, targetUrl: string, auth?: string): string {
  const url = new URL(endpoint);
  url.searchParams.set("url", targetUrl);
  if (auth) url.searchParams.set("authorization", auth);
  return url.toString();
}

function hashBytes(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function hashText(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function extensionForContentType(contentType: string, url: string): string {
  if (contentType.includes("jpeg")) return ".jpg";
  if (contentType.includes("png")) return ".png";
  if (contentType.includes("gif")) return ".gif";
  if (contentType.includes("webp")) return ".webp";
  const match = new URL(url).searchParams.get("wx_fmt");
  return match ? `.${match.replace(/[^a-z0-9]/gi, "").toLowerCase()}` : ".bin";
}
```

- [ ] **Step 5: Integrate image cache into asset download**

Modify `src/archive/downloadArticleAssets.ts` so each image URL is processed by `cacheRemoteAsset`, then write per-article `assets_local.json` with:

```json
{
  "schemaVersion": 2,
  "articleUrl": "https://mp.weixin.qq.com/s/...",
  "downloadedAt": "2026-04-21T00:00:00.000Z",
  "assets": [
    {
      "remoteUrl": "https://mmbiz.qpic.cn/...",
      "contentType": "image/jpeg",
      "size": 12345,
      "sha256": "abc...",
      "cachePath": "D:\\DDownload\\_asset_cache\\images\\ab\\cd\\abc.jpg",
      "localPath": "images\\abc.jpg",
      "status": "ok"
    }
  ]
}
```

- [ ] **Step 6: Run image cache tests**

```powershell
npm test -- tests/extractArticleImageUrls.test.ts tests/globalAssetCache.test.ts tests/downloadArticleAssets.test.ts
npm run build
```

Expected: PASS and build succeeds.

- [ ] **Step 7: Commit when working in a real git checkout**

```powershell
git add src/assets src/archive tests/extractArticleImageUrls.test.ts tests/globalAssetCache.test.ts tests/downloadArticleAssets.test.ts
git commit -m "feat: cache original article images"
```

---

### Task 5: Add Complete Artifact Verification

**Files:**
- Modify: `src/pipeline/runDualTrackBatch.ts`
- Modify: `src/pipeline/processArticleDualTrack.ts`
- Modify: `src/pipeline/processArchiveBundleDualTrack.ts`
- Test: `tests/runDualTrackBatch.test.ts`

- [ ] **Step 1: Add a failing half-finished artifact test**

Add to `tests/runDualTrackBatch.test.ts`:

```ts
test("batch resume does not skip when only llm_input.md exists", async () => {
  const root = await mkdtemp(join(tmpdir(), "wechat-half-finished-"));
  const inputDir = join(root, "input");
  const outDir = join(root, "out");
  await mkdir(join(inputDir, "article"), { recursive: true });
  await writeFile(join(inputDir, "article", "raw.html"), "<html><body id=\"js_content\">A</body></html>");
  await mkdir(join(outDir, "article"), { recursive: true });
  await writeFile(join(outDir, "article", "llm_input.md"), "partial");

  const result = await runDualTrackBatch({
    inputDir,
    outDir,
    resume: true,
    statusPath: join(root, "status.json"),
  });

  assert.equal(result.processed, 1);
});
```

- [ ] **Step 2: Run test to verify it fails or exposes current skip behavior**

```powershell
npm test -- tests/runDualTrackBatch.test.ts
```

Expected: FAIL or shows `processed` is 0 under current skip logic.

- [ ] **Step 3: Implement artifact manifest check**

Add a helper inside the pipeline layer:

```ts
export async function isCompleteDualTrackArtifact(outputDir: string): Promise<boolean> {
  const requiredFiles = [
    "meta.json",
    "assets.json",
    "rule_extract.json",
    "markitdown.raw.md",
    "markitdown.cleaned.md",
    "sidecar.json",
    "llm_input.md",
    "quality_report.json",
    "artifact_manifest.json",
  ];
  for (const fileName of requiredFiles) {
    const ok = await verifyFileIntegrity(join(outputDir, fileName), { minBytes: 1 });
    if (!ok) return false;
  }
  return true;
}
```

Use this helper wherever `--resume` currently checks only `llm_input.md`.

- [ ] **Step 4: Write `artifact_manifest.json` at the end of processing**

Each finished article writes:

```json
{
  "schemaVersion": 1,
  "completedAt": "2026-04-21T00:00:00.000Z",
  "source": {
    "rawHtmlSha256": "..."
  },
  "outputs": {
    "llm_input.md": { "bytes": 1234, "sha256": "..." },
    "markitdown.cleaned.md": { "bytes": 1234, "sha256": "..." }
  }
}
```

- [ ] **Step 5: Run focused tests and build**

```powershell
npm test -- tests/runDualTrackBatch.test.ts
npm run build
```

Expected: PASS and build succeeds.

- [ ] **Step 6: Commit when working in a real git checkout**

```powershell
git add src/pipeline tests/runDualTrackBatch.test.ts
git commit -m "fix: verify complete dual-track artifacts before resume skip"
```

---

### Task 6: Use CPU Concurrency Where It Helps

**Files:**
- Modify: `src/cli.ts`
- Modify: `src/pipeline/runDualTrackBatch.ts`
- Modify: `src/archive/runAssetDownloadBatch.ts`
- Modify: `src/archive/runArchiveBatch.ts`
- Test: `tests/runDualTrackBatch.test.ts`

- [ ] **Step 1: Add concurrency contract test**

Add a test with a synthetic worker that tracks maximum parallelism:

```ts
test("runDualTrackBatch honors concurrency limit", async () => {
  let active = 0;
  let maxActive = 0;
  const items = Array.from({ length: 6 }, (_, index) => index);
  await mapLimit(items, 2, async () => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 10));
    active -= 1;
  });
  assert.equal(maxActive, 2);
});
```

- [ ] **Step 2: Implement or expose a shared `mapLimit` helper**

Create or reuse a helper with this behavior:

```ts
export async function mapLimit<T>(
  items: T[],
  limit: number,
  worker: (item: T, index: number) => Promise<void>,
): Promise<void> {
  let next = 0;
  const workers = Array.from({ length: Math.min(Math.max(limit, 1), items.length) }, async () => {
    while (next < items.length) {
      const current = next;
      next += 1;
      await worker(items[current], current);
    }
  });
  await Promise.all(workers);
}
```

- [ ] **Step 3: Add CLI options**

Add these options:

```text
--concurrency <n>        Worker count for CPU/I/O batch stages.
--cacheDir <path>        Shared cache root for manifests, MarkItDown, and images.
--retryFailedOnly        Process failed items from status manifest only.
```

Default recommendations:

- History/API listing: `1` to `2`.
- Mptext content download: `2` to `4`.
- Image download through Cloudflare Worker: `4` to `8`.
- MarkItDown/HTML processing: `Math.max(1, cpuCount - 2)`.
- Playwright archive: `1` to `2`.

- [ ] **Step 4: Document GPU decision in code comments and docs**

Add a short note near CLI help:

```text
GPU is not used by history/API download, HTML parsing, JSON writing, or Playwright capture.
GPU should only be introduced for OCR, image classification, local vision models, or local LLM extraction.
```

- [ ] **Step 5: Run tests**

```powershell
npm test -- tests/runDualTrackBatch.test.ts
npm run build
```

Expected: PASS and build succeeds.

- [ ] **Step 6: Commit when working in a real git checkout**

```powershell
git add src/cli.ts src/pipeline src/archive tests/runDualTrackBatch.test.ts
git commit -m "feat: add bounded batch concurrency"
```

---

### Task 7: Add Cloudflare Private Proxy Project

**Files:**
- Create: `cloudflare/mptext-proxy-worker/src/index.ts`
- Create: `cloudflare/mptext-proxy-worker/wrangler.jsonc`
- Test: `tests/cloudflareProxyWorker.test.ts`

- [ ] **Step 1: Write Worker behavior test**

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { handleProxyRequest } from "../cloudflare/mptext-proxy-worker/src/index.js";

test("worker rejects missing auth and non-allowlisted hosts", async () => {
  const env = { PRIVATE_PROXY_TOKEN: "token", MPTEXT_AUTH_KEY: "mptext-key" };
  const missingAuth = await handleProxyRequest(new Request("https://proxy.example.com/proxy?url=https%3A%2F%2Fmmbiz.qpic.cn%2Fa"), env as any);
  assert.equal(missingAuth.status, 401);

  const blocked = await handleProxyRequest(new Request("https://proxy.example.com/proxy?url=https%3A%2F%2Fexample.com%2Fa", {
    headers: { authorization: "Bearer token" },
  }), env as any);
  assert.equal(blocked.status, 403);
});
```

- [ ] **Step 2: Implement Worker**

Create `cloudflare/mptext-proxy-worker/src/index.ts`:

```ts
export interface Env {
  PRIVATE_PROXY_TOKEN: string;
  MPTEXT_AUTH_KEY: string;
}

const ALLOWED_HOSTS = new Set([
  "down.mptext.top",
  "mp.weixin.qq.com",
  "mmbiz.qpic.cn",
  "res.wx.qq.com",
  "mmbiz.qlogo.cn",
]);

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handleProxyRequest(request, env);
  },
};

export async function handleProxyRequest(request: Request, env: Env): Promise<Response> {
  const auth = request.headers.get("authorization") || new URL(request.url).searchParams.get("authorization") || "";
  if (auth !== `Bearer ${env.PRIVATE_PROXY_TOKEN}` && auth !== env.PRIVATE_PROXY_TOKEN) {
    return new Response("Unauthorized", { status: 401 });
  }

  const inputUrl = new URL(request.url);
  if (inputUrl.pathname.startsWith("/api/public/v1/")) {
    return proxyMptextApi(request, env);
  }

  if (inputUrl.pathname !== "/proxy") {
    return new Response("URL not found", { status: 400 });
  }

  const target = inputUrl.searchParams.get("url") || "";
  return proxyTarget(target, request);
}

async function proxyMptextApi(request: Request, env: Env): Promise<Response> {
  const source = new URL(request.url);
  const upstream = new URL(`https://down.mptext.top${source.pathname}${source.search}`);
  const response = await fetch(upstream, {
    method: "GET",
    headers: { "X-Auth-Key": env.MPTEXT_AUTH_KEY },
  });
  return streamResponse(response, cacheSecondsFor(upstream));
}

async function proxyTarget(target: string, request: Request): Promise<Response> {
  let upstream: URL;
  try {
    upstream = new URL(target);
  } catch {
    return new Response("URL not valid", { status: 400 });
  }
  if (!ALLOWED_HOSTS.has(upstream.hostname)) {
    return new Response("Host forbidden", { status: 403 });
  }

  const response = await fetch(upstream, {
    method: "GET",
    headers: {
      "user-agent": request.headers.get("user-agent") || "Mozilla/5.0",
      "referer": "https://mp.weixin.qq.com/",
      "origin": "https://mp.weixin.qq.com",
    },
  });
  return streamResponse(response, cacheSecondsFor(upstream));
}

function streamResponse(response: Response, ttl: number): Response {
  const headers = new Headers(response.headers);
  headers.set("access-control-allow-origin", "*");
  if (ttl > 0) headers.set("cache-control", `public, max-age=${ttl}`);
  return new Response(response.body, { status: response.status, headers });
}

function cacheSecondsFor(url: URL): number {
  if (url.hostname === "mmbiz.qpic.cn" || url.hostname === "mmbiz.qlogo.cn") return 60 * 60 * 24 * 14;
  if (url.hostname === "down.mptext.top" && url.pathname.includes("/article")) return 60 * 10;
  if (url.hostname === "mp.weixin.qq.com") return 60 * 60;
  return 0;
}
```

- [ ] **Step 3: Add Wrangler config**

Create `cloudflare/mptext-proxy-worker/wrangler.jsonc`:

```jsonc
{
  "name": "mptext-private-proxy-sg",
  "main": "src/index.ts",
  "compatibility_date": "2026-04-21",
  "observability": {
    "enabled": true
  }
}
```

- [ ] **Step 4: Set secrets and deploy manually**

Run from `cloudflare/mptext-proxy-worker`:

```powershell
npx wrangler secret put PRIVATE_PROXY_TOKEN
npx wrangler secret put MPTEXT_AUTH_KEY
npx wrangler deploy
```

Expected: Worker URL returns `URL not found` on the root path, and authenticated `/proxy?url=...` requests work.

- [ ] **Step 5: Integrate with current commands**

History API route:

```powershell
npm run fetch-history-urls -- --provider mptext --endpoint https://<worker-domain> --key <PRIVATE_PROXY_TOKEN> --url TAGChengdu --outDir D:\DDownload
```

Image proxy route:

```powershell
npm run download-archive-assets-batch -- --inputDir D:\DDownload\TAGChengdu --cacheDir D:\DDownload\_asset_cache --assetProxyEndpoint https://<worker-domain>/proxy --proxyAuth <PRIVATE_PROXY_TOKEN> --resume
```

- [ ] **Step 6: Commit when working in a real git checkout**

```powershell
git add cloudflare/mptext-proxy-worker tests/cloudflareProxyWorker.test.ts
git commit -m "feat: add private cloudflare proxy worker"
```

---

### Task 8: Verify End-to-End Quality

**Files:**
- Modify: documentation or runbook after implementation

- [ ] **Step 1: Re-run current export with resume**

```powershell
$env:MPTEXT_AUTH_KEY = "<current mptext key>"
node tools/exportMptextAccount.mjs --account TAGChengdu --outDir D:\DDownload --formats html,json --concurrency 3 --listDelayMs 2500 --rateLimitDelayMs 180000
```

Expected:

- Existing verified `raw.html` and `download.json` are skipped.
- `_export_manifest.json` records every article and format.
- Failed items can be retried without redownloading successful items.

- [ ] **Step 2: Download images for a 10-article sample**

```powershell
npm run download-archive-assets-batch -- --inputDir D:\DDownload\TAGChengdu --cacheDir D:\DDownload\_asset_cache --concurrency 4 --resume
```

Expected:

- Each sampled article gets `assets_local.json`.
- `D:\DDownload\_asset_cache\images` contains real `.jpg`, `.png`, `.gif`, or `.webp` files.
- Duplicate images reuse the same sha256 cache path.

- [ ] **Step 3: Validate normalized entity files**

Check one article directory:

```powershell
Get-Content "D:\DDownload\TAGChengdu\<article-dir>\article.normalized.json" -Raw | ConvertFrom-Json
```

Expected fields:

- `account.nickname`
- `article.title`
- `article.publishTimeIso`
- `article.link`
- `content.html`
- `images.inlineRemoteUrls`
- `comments.ids`

- [ ] **Step 4: Run full verification commands**

```powershell
npm test
npm run build
```

Expected: all tests pass and TypeScript build succeeds.

- [ ] **Step 5: Commit verification notes when working in a real git checkout**

```powershell
git add docs/superpowers/plans/2026-04-21-wechat-cache-export-acceleration.md
git commit -m "docs: plan wechat cache export acceleration"
```

---

## CPU and GPU Decision

- Use CPU concurrency for history page validation, JSON writes, sha256, HTML parsing, Markdown cleaning, image downloads, and MarkItDown batch conversion.
- Use GPU only after original images are saved, and only for OCR, visual entity extraction, poster detection, local vision models, or local LLM extraction.
- Do not use GPU for mptext API requests, WeChat image downloads, Playwright page waits, JSON serialization, or simple Cheerio/regex parsing. Those stages are network, I/O, or small CPU-bound work.

## Acceptance Criteria

- `D:\DDownload\TAGChengdu` keeps the current account-first structure.
- Every article directory contains verified `raw.html`, `download.json`, `metadata.json`, and `article.normalized.json`.
- Every article with remote images has `assets_local.json`.
- Original image bytes are retained under `D:\DDownload\_asset_cache\images`.
- Resume behavior is manifest-based and does not skip half-finished artifacts.
- Cloudflare Worker is optional, authenticated, allowlisted, and usable for image/API proxying.
- A full test run and TypeScript build pass before wide use.

## Self-Review

- Spec coverage: The plan covers cache efficiency, artifact quality, CPU/GPU acceleration, original images, key entity information, and Cloudflare private proxy.
- Placeholder scan: No task relies on unspecified filenames, open-ended validation, or unnamed tests.
- Type consistency: `NormalizedMptextArticle`, manifest helper names, proxy options, and CLI option names are consistent across tasks.

Plan complete and saved to `docs/superpowers/plans/2026-04-21-wechat-cache-export-acceleration.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints.
