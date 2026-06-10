import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import {
  DajialaClient,
  extractDajialaArticleInfo,
  getDajialaCode,
  getDajialaMessage,
  type DajialaArticleResponse,
} from "../dajiala/client.js";
import { ensureDir, writeJson } from "../utils/fs.js";
import { sha256File, sha256Hex } from "../utils/hash.js";
import { readJsonlFile } from "../utils/jsonl.js";
import { compactSnapshotItems } from "../utils/snapshotCompaction.js";
import { appendStageResultLog, type StageResultLogRow } from "../stage/contracts.js";
import { analyzeArticleHtmlQuality, isValidArticleHtml } from "./articleHtmlQuality.js";
import type { ArchiveMetaJson, ArchiveQueueRecord } from "./types.js";

interface RunDajialaArchiveRepairBatchOptions {
  manifestPath: string;
  archiveRoot: string;
  statusPath?: string;
  resultLogPath?: string;
  endpoint?: string;
  key?: string;
  resume?: boolean;
  concurrency?: number;
  requestDelayMs?: number;
}

interface RunDajialaArchiveRepairBatchDependencies {
  now?: () => string;
  client?: DajialaClient;
}

interface DajialaArchiveRepairBatchItemSnapshot {
  token: string;
  accountKey: string;
  sourceUrl: string;
  outDir: string;
  status: "queued" | "running" | "succeeded" | "failed" | "skipped";
  message: string;
  errorMessage: string;
  startedAt: string;
  endedAt: string;
}

export interface DajialaArchiveRepairBatchSnapshot {
  manifestPath: string;
  archiveRoot: string;
  statusPath: string;
  resultLogPath: string;
  endpoint: string;
  status: "running" | "completed";
  startedAt: string;
  endedAt: string;
  totalItems: number;
  queuedCount: number;
  runningCount: number;
  succeededCount: number;
  failedCount: number;
  skippedCount: number;
  itemCount?: number;
  itemLimit?: number;
  itemsTruncated?: boolean;
  items: DajialaArchiveRepairBatchItemSnapshot[];
}

interface DajialaRepairJson {
  account_key: string;
  token: string;
  source_url: string;
  checked_at: string;
  status: "archived" | "unavailable";
  preflight_code: number | string;
  preflight_message: string;
  html_code?: number | string;
  html_message?: string;
  cost_money?: number | string;
  remain_money?: number | string;
}

function nowIso(now: (() => string) | undefined): string {
  return now ? now() : new Date().toISOString();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isSuccessCode(code: number | string): boolean {
  return String(code) === "0";
}

function isRateLimitedCode(code: number | string): boolean {
  return code === -1 || String(code) === "-1" || String(code) === "103" || String(code) === "104";
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttribute(value: string): string {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function warningForResponse(prefix: string, response: DajialaArticleResponse): string {
  const code = getDajialaCode(response);
  const message = getDajialaMessage(response);
  return `${prefix} returned code=${code}${message ? `: ${message}` : ""}`;
}

function uniqueWarnings(warnings: string[]): string[] {
  return Array.from(new Set(warnings.filter(Boolean)));
}

function looksLikeFullArticleHtml(value: string): boolean {
  return (
    (/\bid=["']js_article["']/i.test(value) && /\bid=["']js_content["']/i.test(value)) ||
    /\bid=["']js_content["']/i.test(value) ||
    /class=["'][^"']*rich_media_content/i.test(value)
  );
}

function buildDajialaRawHtml(
  record: ArchiveQueueRecord,
  response: DajialaArticleResponse,
): string {
  const info = extractDajialaArticleInfo(response);
  const title = info.title || record.title || "";
  const sourceUrl = info.url || record.source_url;
  const content = info.content || info.contentText;
  const accountName = info.nickname || record.account_key;
  const author = info.author || record.author || "";
  const postTime = info.postTime || record.post_time || record.post_date || "";
  const description = info.summary || "";
  const coverUrl = info.coverUrl || record.cover_url || "";
  const originalUrl = info.sourceUrl || "";
  const imageHtml = info.imageUrls
    .map((url) => `<p><img data-src="${escapeAttribute(url)}" src="${escapeAttribute(url)}"></p>`)
    .join("\n");
  const baseContentHtml = info.content ? content : `<p>${escapeHtml(content)}</p>`;
  const contentHtml = [baseContentHtml, imageHtml].filter(Boolean).join("\n");

  if (info.content && looksLikeFullArticleHtml(info.content)) {
    return info.content;
  }

  return [
    "<!doctype html>",
    "<html>",
    "<head>",
    '<meta charset="utf-8">',
    `<meta property="og:url" content="${escapeAttribute(sourceUrl)}">`,
    `<meta property="og:title" content="${escapeAttribute(title)}">`,
    coverUrl ? `<meta property="og:image" content="${escapeAttribute(coverUrl)}">` : "",
    description ? `<meta name="description" content="${escapeAttribute(description)}">` : "",
    author ? `<meta name="author" content="${escapeAttribute(author)}">` : "",
    `<title>${escapeHtml(title)}</title>`,
    "</head>",
    "<body>",
    '<div id="js_article">',
    `<h1 id="activity-name">${escapeHtml(title)}</h1>`,
    '<div id="meta_content">',
    `<span id="js_name">${escapeHtml(accountName)}</span>`,
    author ? `<span id="js_author_name">${escapeHtml(author)}</span>` : "",
    postTime ? `<span id="publish_time">${escapeHtml(postTime)}</span>` : "",
    "</div>",
    `<div id="js_content">${contentHtml}</div>`,
    originalUrl
      ? `<a id="js_share_source" href="${escapeAttribute(originalUrl)}">阅读原文</a>`
      : "",
    "</div>",
    "</body>",
    "</html>",
    "",
  ]
    .filter((line) => line !== "")
    .join("\n");
}

async function pathHasBytes(filePath: string): Promise<boolean> {
  try {
    return (await stat(filePath)).size > 0;
  } catch {
    return false;
  }
}

async function hashFirstExisting(paths: string[]): Promise<string> {
  for (const filePath of paths) {
    if (await pathHasBytes(filePath)) {
      return sha256File(filePath);
    }
  }
  return "";
}

async function readOptionalJson<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

async function isArchiveComplete(outDir: string): Promise<boolean> {
  if (!(await pathHasBytes(join(outDir, "raw.html")))) {
    return false;
  }
  try {
    if (!isValidArticleHtml(await readFile(join(outDir, "raw.html"), "utf-8"))) {
      return false;
    }
    const meta = JSON.parse(
      await readFile(join(outDir, "archive_meta.json"), "utf-8"),
    ) as ArchiveMetaJson;
    return meta.status === "archived";
  } catch {
    return false;
  }
}

async function writeRepairResult(
  outDir: string,
  result: DajialaRepairJson,
): Promise<void> {
  await mkdir(outDir, { recursive: true });
  await writeJson(join(outDir, "dajiala_repair.json"), result);
}

async function writeUnavailableBundle(options: {
  record: ArchiveQueueRecord;
  outDir: string;
  response: DajialaArticleResponse;
  checkedAt: string;
}): Promise<void> {
  await mkdir(options.outDir, { recursive: true });
  const rawHtmlPath = join(options.outDir, "raw.html");
  const rawHtmlBytes = (await pathHasBytes(rawHtmlPath))
    ? (await stat(rawHtmlPath)).size
    : 0;
  const existingMeta = await readOptionalJson<ArchiveMetaJson>(
    join(options.outDir, "archive_meta.json"),
  );
  const warning = warningForResponse("dajiala article_detail preflight", options.response);
  const meta: ArchiveMetaJson = {
    account_key: options.record.account_key,
    token: options.record.token,
    source_url: options.record.source_url,
    final_url: existingMeta?.final_url || options.record.source_url,
    title: existingMeta?.title || options.record.title || "",
    archived_at: options.checkedAt,
    status: "failed",
    capture_method: existingMeta?.capture_method || "dajiala-api",
    raw_html_bytes: rawHtmlBytes,
    mhtml_bytes: existingMeta?.mhtml_bytes || 0,
    pdf_bytes: existingMeta?.pdf_bytes || 0,
    warnings: uniqueWarnings([...(existingMeta?.warnings || []), warning]),
  };
  await writeJson(join(options.outDir, "archive_meta.json"), meta);
  await writeFile(
    join(options.outDir, "article.url.txt"),
    `${options.record.source_url}\n`,
    "utf-8",
  );
}

async function writeArchivedBundle(options: {
  record: ArchiveQueueRecord;
  outDir: string;
  preflightResponse: DajialaArticleResponse;
  htmlResponse: DajialaArticleResponse;
  archivedAt: string;
}): Promise<ArchiveMetaJson> {
  await mkdir(options.outDir, { recursive: true });
  const rawHtml = buildDajialaRawHtml(options.record, options.htmlResponse);
  await writeFile(join(options.outDir, "raw.html"), rawHtml, "utf-8");
  await writeFile(
    join(options.outDir, "article.url.txt"),
    `${options.record.source_url}\n`,
    "utf-8",
  );
  await writeJson(join(options.outDir, "download.json"), options.htmlResponse);

  const rawHtmlStat = await stat(join(options.outDir, "raw.html"));
  const info = extractDajialaArticleInfo(options.htmlResponse);
  const quality = analyzeArticleHtmlQuality(rawHtml);
  const hasContent = Boolean(info.content || info.contentText || info.imageUrls.length > 0);
  const hasArticle = quality.valid && hasContent;
  const meta: ArchiveMetaJson = {
    account_key: options.record.account_key,
    token: options.record.token,
    source_url: options.record.source_url,
    final_url: info.url || options.record.source_url,
    title: info.title || options.record.title || "",
    archived_at: options.archivedAt,
    status: rawHtmlStat.size > 0 && hasArticle ? "archived" : "partial",
    capture_method: "dajiala-api",
    raw_html_bytes: rawHtmlStat.size,
    mhtml_bytes: 0,
    pdf_bytes: 0,
    warnings: uniqueWarnings([
      "dajiala-api archive does not produce page.mhtml or page.pdf",
      "dajiala-api raw.html is reconstructed from article_detail Pro content",
      ...(hasArticle ? [] : ["dajiala-api returned no usable content"]),
      ...(!quality.valid
        ? quality.warnings.map((warning) => `dajiala-api reconstructed invalid html: ${warning}`)
        : []),
      ...(isSuccessCode(getDajialaCode(options.preflightResponse))
        ? []
        : [warningForResponse("dajiala article_detail preflight", options.preflightResponse)]),
    ]),
  };
  await writeJson(join(options.outDir, "archive_meta.json"), meta);
  return meta;
}

async function getArticleTextDetailWithRetry(
  client: DajialaClient,
  sourceUrl: string,
): Promise<DajialaArticleResponse> {
  let lastResponse: DajialaArticleResponse = {};
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    lastResponse = await client.getArticleTextDetail(sourceUrl);
    if (!isRateLimitedCode(getDajialaCode(lastResponse)) || attempt === 3) {
      break;
    }
    await sleep(2_000 * attempt);
  }
  return lastResponse;
}

async function getArticleHtmlDetailWithRetry(
  client: DajialaClient,
  sourceUrl: string,
): Promise<DajialaArticleResponse> {
  let lastResponse: DajialaArticleResponse = {};
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    lastResponse = await client.getArticleHtmlDetail(sourceUrl);
    if (!isRateLimitedCode(getDajialaCode(lastResponse)) || attempt === 3) {
      break;
    }
    await sleep(2_000 * attempt);
  }
  return lastResponse;
}

function recalculateSnapshot(snapshot: DajialaArchiveRepairBatchSnapshot): void {
  let queuedCount = 0;
  let runningCount = 0;
  let succeededCount = 0;
  let failedCount = 0;
  let skippedCount = 0;

  for (const item of snapshot.items) {
    if (item.status === "queued") queuedCount += 1;
    else if (item.status === "running") runningCount += 1;
    else if (item.status === "succeeded") succeededCount += 1;
    else if (item.status === "failed") failedCount += 1;
    else skippedCount += 1;
  }

  snapshot.totalItems = snapshot.items.length;
  snapshot.queuedCount = queuedCount;
  snapshot.runningCount = runningCount;
  snapshot.succeededCount = succeededCount;
  snapshot.failedCount = failedCount;
  snapshot.skippedCount = skippedCount;
}

async function persistSnapshot(
  snapshot: DajialaArchiveRepairBatchSnapshot,
): Promise<void> {
  recalculateSnapshot(snapshot);
  const compactedSnapshot = compactSnapshotItems(snapshot);
  await ensureDir(dirname(snapshot.statusPath));
  await writeJson(snapshot.statusPath, compactedSnapshot);
}

async function appendRepairResultLog(options: {
  resultLogPath: string;
  record: ArchiveQueueRecord;
  item: DajialaArchiveRepairBatchItemSnapshot;
}): Promise<void> {
  const row: StageResultLogRow = {
    run_id: "dajiala-repair-v1",
    stage: "dajiala_repair",
    article_id: `${options.record.account_key}/${options.record.token}`,
    status:
      options.item.status === "succeeded"
        ? "succeeded"
        : options.item.status === "skipped"
          ? "skipped"
          : "failed",
    started_at: options.item.startedAt,
    finished_at: options.item.endedAt,
    runner_id: "windows-4090",
    model_id: "dajiala-api",
    input_hash: sha256Hex(options.record.source_url),
    output_hash: await hashFirstExisting([
      join(options.item.outDir, "raw.html"),
      join(options.item.outDir, "dajiala_repair.json"),
      join(options.item.outDir, "archive_meta.json"),
    ]),
    error_type: options.item.status === "failed" ? "dajiala_repair_failed" : "",
    error_message: options.item.errorMessage,
    output_paths: [
      join(options.item.outDir, "raw.html"),
      join(options.item.outDir, "archive_meta.json"),
      join(options.item.outDir, "dajiala_repair.json"),
    ],
  };
  await appendStageResultLog(options.resultLogPath, row);
}

export async function runDajialaArchiveRepairBatch(
  options: RunDajialaArchiveRepairBatchOptions,
  dependencies: RunDajialaArchiveRepairBatchDependencies = {},
): Promise<DajialaArchiveRepairBatchSnapshot> {
  const manifestPath = resolve(options.manifestPath);
  const archiveRoot = resolve(options.archiveRoot);
  const statusPath = resolve(
    options.statusPath || join(archiveRoot, "dajiala-repair-status.json"),
  );
  const resultLogPath = resolve(
    options.resultLogPath || join(archiveRoot, "dajiala-repair-results.jsonl"),
  );
  const client =
    dependencies.client ||
    new DajialaClient({
      baseUrl: options.endpoint,
      key: options.key,
    });
  const records = await readJsonlFile<ArchiveQueueRecord>(manifestPath);
  const concurrency = Math.max(1, Math.min(options.concurrency ?? 1, 5));
  const requestDelayMs = Math.max(0, options.requestDelayMs ?? 250);

  const snapshot: DajialaArchiveRepairBatchSnapshot = {
    manifestPath,
    archiveRoot,
    statusPath,
    resultLogPath,
    endpoint: client.baseUrl,
    status: "running",
    startedAt: nowIso(dependencies.now),
    endedAt: "",
    totalItems: records.length,
    queuedCount: records.length,
    runningCount: 0,
    succeededCount: 0,
    failedCount: 0,
    skippedCount: 0,
    items: records.map((record) => ({
      token: record.token,
      accountKey: record.account_key,
      sourceUrl: record.source_url,
      outDir: join(archiveRoot, record.account_key, record.token),
      status: "queued",
      message: "Queued",
      errorMessage: "",
      startedAt: "",
      endedAt: "",
    })),
  };

  let persistQueue = Promise.resolve();
  const persist = async (): Promise<void> => {
    persistQueue = persistQueue.then(() => persistSnapshot(snapshot));
    await persistQueue;
  };

  await persist();

  let nextIndex = 0;
  const workerCount = Math.min(concurrency, records.length);
  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (nextIndex < records.length) {
        const index = nextIndex;
        nextIndex += 1;
        const record = records[index];
        const item = snapshot.items[index];
        if (!record || !item) {
          continue;
        }

        if (options.resume && (await isArchiveComplete(item.outDir))) {
          item.status = "skipped";
          item.message = "Skipped existing complete archive bundle";
          item.endedAt = nowIso(dependencies.now);
          await persist();
          await appendRepairResultLog({ resultLogPath, record, item });
          continue;
        }

        const existingRepair = await readOptionalJson<DajialaRepairJson>(
          join(item.outDir, "dajiala_repair.json"),
        );
        if (options.resume && existingRepair && existingRepair.status === "unavailable") {
          item.status = "skipped";
          item.message = `Skipped existing unavailable result code=${existingRepair.preflight_code}`;
          item.endedAt = nowIso(dependencies.now);
          await persist();
          await appendRepairResultLog({ resultLogPath, record, item });
          continue;
        }

        item.status = "running";
        item.startedAt = nowIso(dependencies.now);
        item.message = "Checking article availability via Dajiala";
        await persist();

        try {
          const checkedAt = nowIso(dependencies.now);
          const preflightResponse = await getArticleTextDetailWithRetry(
            client,
            record.source_url,
          );
          const preflightCode = getDajialaCode(preflightResponse);
          const preflightMessage = getDajialaMessage(preflightResponse);

          if (!isSuccessCode(preflightCode)) {
            await writeRepairResult(item.outDir, {
              account_key: record.account_key,
              token: record.token,
              source_url: record.source_url,
              checked_at: checkedAt,
              status: "unavailable",
              preflight_code: preflightCode,
              preflight_message: preflightMessage,
              cost_money: preflightResponse.cost_money ?? preflightResponse.cost,
              remain_money: preflightResponse.remain_money ?? preflightResponse.remain,
            });
            await writeUnavailableBundle({
              record,
              outDir: item.outDir,
              response: preflightResponse,
              checkedAt,
            });
            item.status = "failed";
            item.message = `Dajiala unavailable code=${preflightCode}`;
            item.errorMessage = preflightMessage || item.message;
            item.endedAt = nowIso(dependencies.now);
            await persist();
            await appendRepairResultLog({ resultLogPath, record, item });
            if (requestDelayMs > 0) {
              await sleep(requestDelayMs);
            }
            continue;
          }

          item.message = "Article available; downloading HTML detail Pro";
          await persist();
          const htmlResponse = await getArticleHtmlDetailWithRetry(
            client,
            record.source_url,
          );
          const htmlCode = getDajialaCode(htmlResponse);
          const htmlMessage = getDajialaMessage(htmlResponse);
          if (!isSuccessCode(htmlCode)) {
            await writeRepairResult(item.outDir, {
              account_key: record.account_key,
              token: record.token,
              source_url: record.source_url,
              checked_at: checkedAt,
              status: "unavailable",
              preflight_code: preflightCode,
              preflight_message: preflightMessage,
              html_code: htmlCode,
              html_message: htmlMessage,
              cost_money: htmlResponse.cost_money ?? htmlResponse.cost,
              remain_money: htmlResponse.remain_money ?? htmlResponse.remain,
            });
            await writeUnavailableBundle({
              record,
              outDir: item.outDir,
              response: htmlResponse,
              checkedAt,
            });
            item.status = "failed";
            item.message = `Dajiala HTML detail unavailable code=${htmlCode}`;
            item.errorMessage = htmlMessage || item.message;
            item.endedAt = nowIso(dependencies.now);
            await persist();
            await appendRepairResultLog({ resultLogPath, record, item });
            if (requestDelayMs > 0) {
              await sleep(requestDelayMs);
            }
            continue;
          }

          const meta = await writeArchivedBundle({
            record,
            outDir: item.outDir,
            preflightResponse,
            htmlResponse,
            archivedAt: nowIso(dependencies.now),
          });
          await writeRepairResult(item.outDir, {
            account_key: record.account_key,
            token: record.token,
            source_url: record.source_url,
            checked_at: checkedAt,
            status: meta.status === "archived" ? "archived" : "unavailable",
            preflight_code: preflightCode,
            preflight_message: preflightMessage,
            html_code: htmlCode,
            html_message: htmlMessage,
            cost_money: htmlResponse.cost_money ?? htmlResponse.cost,
            remain_money: htmlResponse.remain_money ?? htmlResponse.remain,
          });
          item.status = meta.status === "archived" ? "succeeded" : "failed";
          item.message =
            meta.status === "archived"
              ? "Archived via Dajiala article_detail Pro"
              : "Dajiala returned invalid HTML detail";
          item.errorMessage = meta.status === "archived" ? "" : item.message;
          item.endedAt = nowIso(dependencies.now);
          await persist();
          await appendRepairResultLog({ resultLogPath, record, item });
          if (requestDelayMs > 0) {
            await sleep(requestDelayMs);
          }
        } catch (error) {
          item.status = "failed";
          item.message = error instanceof Error ? error.message : String(error);
          item.errorMessage = item.message;
          item.endedAt = nowIso(dependencies.now);
          await persist();
          await appendRepairResultLog({ resultLogPath, record, item });
          if (requestDelayMs > 0) {
            await sleep(requestDelayMs);
          }
        }
      }
    }),
  );

  snapshot.status = "completed";
  snapshot.endedAt = nowIso(dependencies.now);
  await persist();
  return snapshot;
}
