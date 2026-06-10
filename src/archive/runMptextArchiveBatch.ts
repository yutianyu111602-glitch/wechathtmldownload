import { appendFile, mkdir, readFile, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import {
  DEFAULT_MPTEXT_AUTH_KEY,
  DEFAULT_MPTEXT_BASE_URL,
  MptextClient,
  type MptextDownloadFormat,
} from "../mptext/client.js";
import { ensureDir, writeJson, writeText } from "../utils/fs.js";
import { readJsonlFile } from "../utils/jsonl.js";
import { compactSnapshotItems } from "../utils/snapshotCompaction.js";
import { analyzeArticleHtmlQuality, isValidArticleHtml } from "./articleHtmlQuality.js";
import type { ArchiveMetaJson, ArchiveQueueRecord } from "./types.js";

interface RunMptextArchiveBatchOptions {
  manifestPath: string;
  archiveRoot: string;
  statusPath?: string;
  endpoint?: string;
  key?: string;
  fallbackEndpoint?: string;
  fallbackKey?: string;
  disableFallback?: boolean;
  resultLogPath?: string;
  resume?: boolean;
  deferExistingPartialOnResume?: boolean;
  formats?: MptextDownloadFormat[];
  concurrency?: number;
}

interface RunMptextArchiveBatchDependencies {
  now?: () => string;
  client?: MptextClient;
  fallbackClient?: MptextClient;
}

interface MptextArchiveBatchItemSnapshot {
  token: string;
  accountKey: string;
  sourceUrl: string;
  outDir: string;
  status:
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "skipped"
    | "deferred";
  message: string;
  errorMessage: string;
  startedAt: string;
  endedAt: string;
}

export interface MptextArchiveBatchSnapshot {
  manifestPath: string;
  archiveRoot: string;
  statusPath: string;
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
  deferredCount: number;
  itemCount?: number;
  itemLimit?: number;
  itemsTruncated?: boolean;
  items: MptextArchiveBatchItemSnapshot[];
}

interface MptextArchiveResultLogRecord {
  run_id: string;
  token: string;
  account_key: string;
  source_url: string;
  out_dir: string;
  status: "succeeded" | "failed" | "skipped" | "deferred";
  archive_status: ArchiveMetaJson["status"] | "";
  capture_method: ArchiveMetaJson["capture_method"] | "";
  raw_html_bytes: number;
  message: string;
  error_message: string;
  started_at: string;
  ended_at: string;
}

function nowIso(now: (() => string) | undefined): string {
  return now ? now() : new Date().toISOString();
}

async function readQueue(queuePath: string): Promise<ArchiveQueueRecord[]> {
  return readJsonlFile<ArchiveQueueRecord>(queuePath);
}

function normalizeFormats(
  formats: MptextDownloadFormat[] | undefined,
): MptextDownloadFormat[] {
  const normalized = new Set<MptextDownloadFormat>(formats || ["html"]);
  normalized.add("html");
  return Array.from(normalized);
}

function fileNameForFormat(format: MptextDownloadFormat): string {
  if (format === "html") return "raw.html";
  if (format === "json") return "download.json";
  if (format === "markdown") return "article.md";
  return "article.txt";
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getStatusPersistIntervalMs(): number {
  const configured = Number(process.env.WECHAT_BATCH_STATUS_INTERVAL_MS);
  if (Number.isFinite(configured) && configured >= 0) {
    return Math.floor(configured);
  }
  return 2_000;
}

function isLocalEndpoint(endpoint: string): boolean {
  try {
    const hostname = new URL(endpoint).hostname.toLowerCase();
    return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
  } catch {
    return false;
  }
}

function assertAllowedFallbackEndpoint(endpoint: string): void {
  if (!endpoint || isLocalEndpoint(endpoint)) {
    return;
  }
  if (process.env.WECHAT_ALLOW_PUBLIC_FALLBACK === "1") {
    return;
  }
  throw new Error(
    "Public mptext fallback is disabled for private-service runs. Use --noFallback, a localhost fallback endpoint, or set WECHAT_ALLOW_PUBLIC_FALLBACK=1 explicitly.",
  );
}

async function pathHasBytes(filePath: string): Promise<boolean> {
  try {
    return (await stat(filePath)).size > 0;
  } catch {
    return false;
  }
}

async function readExistingArchiveSummary(outDir: string): Promise<{
  archiveStatus: ArchiveMetaJson["status"] | "";
  captureMethod: ArchiveMetaJson["capture_method"] | "";
  rawHtmlBytes: number;
  hasRawHtml: boolean;
  hasArchiveMeta: boolean;
}> {
  let rawHtmlBytes = 0;
  let hasRawHtml = false;
  try {
    rawHtmlBytes = (await stat(join(outDir, "raw.html"))).size;
    hasRawHtml = rawHtmlBytes > 0;
  } catch {
    rawHtmlBytes = 0;
  }

  try {
    const meta = JSON.parse(
      await readFile(join(outDir, "archive_meta.json"), "utf-8"),
    ) as ArchiveMetaJson;
    return {
      archiveStatus: meta.status || "",
      captureMethod: meta.capture_method || "",
      rawHtmlBytes:
        Number.isFinite(meta.raw_html_bytes) && meta.raw_html_bytes > 0
          ? meta.raw_html_bytes
          : rawHtmlBytes,
      hasRawHtml,
      hasArchiveMeta: true,
    };
  } catch {
    return {
      archiveStatus: "",
      captureMethod: "",
      rawHtmlBytes,
      hasRawHtml,
      hasArchiveMeta: false,
    };
  }
}

function hasExistingArchiveAttempt(summary: {
  rawHtmlBytes: number;
  hasRawHtml: boolean;
  hasArchiveMeta: boolean;
}): boolean {
  return summary.hasArchiveMeta || summary.hasRawHtml || summary.rawHtmlBytes > 0;
}

async function isMptextArchiveComplete(
  outDir: string,
  formats: MptextDownloadFormat[],
): Promise<boolean> {
  if (!(await pathHasBytes(join(outDir, "raw.html")))) {
    return false;
  }
  try {
    if (!isValidArticleHtml(await readFile(join(outDir, "raw.html"), "utf-8"))) {
      return false;
    }
  } catch {
    return false;
  }
  for (const format of formats) {
    if (!(await pathHasBytes(join(outDir, fileNameForFormat(format))))) {
      return false;
    }
  }

  try {
    const meta = JSON.parse(
      await readFile(join(outDir, "archive_meta.json"), "utf-8"),
    ) as ArchiveMetaJson;
    return meta.status === "archived" && meta.capture_method === "mptext-api";
  } catch {
    return false;
  }
}

function decrementStatusCount(
  snapshot: MptextArchiveBatchSnapshot,
  status: MptextArchiveBatchItemSnapshot["status"],
): void {
  if (status === "queued") snapshot.queuedCount -= 1;
  else if (status === "running") snapshot.runningCount -= 1;
  else if (status === "succeeded") snapshot.succeededCount -= 1;
  else if (status === "failed") snapshot.failedCount -= 1;
  else if (status === "skipped") snapshot.skippedCount -= 1;
  else snapshot.deferredCount -= 1;
}

function incrementStatusCount(
  snapshot: MptextArchiveBatchSnapshot,
  status: MptextArchiveBatchItemSnapshot["status"],
): void {
  if (status === "queued") snapshot.queuedCount += 1;
  else if (status === "running") snapshot.runningCount += 1;
  else if (status === "succeeded") snapshot.succeededCount += 1;
  else if (status === "failed") snapshot.failedCount += 1;
  else if (status === "skipped") snapshot.skippedCount += 1;
  else snapshot.deferredCount += 1;
}

function setItemStatus(
  snapshot: MptextArchiveBatchSnapshot,
  item: MptextArchiveBatchItemSnapshot,
  status: MptextArchiveBatchItemSnapshot["status"],
): void {
  if (item.status === status) {
    return;
  }
  decrementStatusCount(snapshot, item.status);
  item.status = status;
  incrementStatusCount(snapshot, status);
}

async function persistSnapshot(
  snapshot: MptextArchiveBatchSnapshot,
): Promise<void> {
  const compactedSnapshot = compactSnapshotItems(snapshot);
  await ensureDir(dirname(snapshot.statusPath));
  await writeJson(snapshot.statusPath, compactedSnapshot);
}

async function appendResultLogRecord(
  resultLogPath: string,
  record: MptextArchiveResultLogRecord,
): Promise<void> {
  await ensureDir(dirname(resultLogPath));
  await appendFile(resultLogPath, `${JSON.stringify(record)}\n`, "utf-8");
}

async function writeArchiveBundle(options: {
  record: ArchiveQueueRecord;
  outDir: string;
  client: MptextClient;
  formats: MptextDownloadFormat[];
  archivedAt: string;
  extraWarnings?: string[];
}): Promise<ArchiveMetaJson> {
  await mkdir(options.outDir, { recursive: true });

  let rawHtml = "";
  for (const format of options.formats) {
    let content = "";
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      content = await options.client.downloadArticle(
        options.record.source_url,
        format,
      );
      if (format !== "html" || isValidArticleHtml(content) || attempt === 3) {
        break;
      }
      await sleep(1_000 * attempt);
    }
    if (format === "html") {
      rawHtml = content;
    }
    await writeText(join(options.outDir, fileNameForFormat(format)), content);
  }

  await writeText(
    join(options.outDir, "article.url.txt"),
    `${options.record.source_url}\n`,
  );

  const rawHtmlPath = join(options.outDir, "raw.html");
  const rawHtmlStat = await stat(rawHtmlPath);
  const quality = analyzeArticleHtmlQuality(rawHtml);
  const meta: ArchiveMetaJson = {
    account_key: options.record.account_key,
    token: options.record.token,
    source_url: options.record.source_url,
    final_url: options.record.source_url,
    title: options.record.title || "",
    archived_at: options.archivedAt,
    status: rawHtmlStat.size > 0 && quality.valid ? "archived" : "partial",
    capture_method: "mptext-api",
    raw_html_bytes: rawHtmlStat.size,
    mhtml_bytes: 0,
    pdf_bytes: 0,
    warnings: [
      "mptext-api archive does not produce page.mhtml or page.pdf",
      ...(options.extraWarnings || []),
      ...quality.warnings.map((warning) => `mptext-api returned invalid html: ${warning}`),
    ],
  };
  await writeJson(join(options.outDir, "archive_meta.json"), meta);
  return meta;
}

export async function runMptextArchiveBatch(
  options: RunMptextArchiveBatchOptions,
  dependencies: RunMptextArchiveBatchDependencies = {},
): Promise<MptextArchiveBatchSnapshot> {
  const manifestPath = resolve(options.manifestPath);
  const archiveRoot = resolve(options.archiveRoot);
  const statusPath = resolve(
    options.statusPath || join(archiveRoot, "mptext-archive-status.json"),
  );
  const resultLogPath = resolve(
    options.resultLogPath || join(archiveRoot, "mptext-archive-results.jsonl"),
  );
  const endpoint =
    options.endpoint || process.env.MPTEXT_BASE_URL || DEFAULT_MPTEXT_BASE_URL;
  const key = options.key || DEFAULT_MPTEXT_AUTH_KEY;
  const client =
    dependencies.client ||
    new MptextClient({
      baseUrl: endpoint,
      authKey: key,
    });
  const fallbackEndpoint = options.disableFallback
    ? ""
    : options.fallbackEndpoint || "";
  assertAllowedFallbackEndpoint(fallbackEndpoint);
  const fallbackKey =
    options.fallbackKey || process.env.MPTEXT_FALLBACK_AUTH_KEY || key;
  const fallbackClient =
    dependencies.fallbackClient ||
    (fallbackEndpoint && fallbackEndpoint.replace(/\/+$/g, "") !== client.baseUrl
      ? new MptextClient({
          baseUrl: fallbackEndpoint,
          authKey: fallbackKey,
        })
      : null);
  const formats = normalizeFormats(options.formats);
  const records = await readQueue(manifestPath);
  const concurrency = Math.max(1, Math.min(options.concurrency ?? 3, 12));

  const runId = nowIso(dependencies.now);
  const snapshot: MptextArchiveBatchSnapshot = {
    manifestPath,
    archiveRoot,
    statusPath,
    endpoint: client.baseUrl,
    status: "running",
    startedAt: runId,
    endedAt: "",
    totalItems: records.length,
    queuedCount: records.length,
    runningCount: 0,
    succeededCount: 0,
    failedCount: 0,
    skippedCount: 0,
    deferredCount: 0,
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

  const statusPersistIntervalMs = getStatusPersistIntervalMs();
  let lastPersistedAtMs = 0;
  let persistQueue = Promise.resolve();
  const persist = async (force = false): Promise<void> => {
    const currentTimeMs = Date.now();
    if (
      !force &&
      statusPersistIntervalMs > 0 &&
      currentTimeMs - lastPersistedAtMs < statusPersistIntervalMs
    ) {
      return;
    }
    lastPersistedAtMs = currentTimeMs;
    persistQueue = persistQueue.then(() => persistSnapshot(snapshot));
    await persistQueue;
  };
  let resultLogQueue = Promise.resolve();
  const appendResult = async (
    record: MptextArchiveResultLogRecord,
  ): Promise<void> => {
    resultLogQueue = resultLogQueue.then(() =>
      appendResultLogRecord(resultLogPath, record),
    );
    await resultLogQueue;
  };

  await persist(true);

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

        if (
          options.resume &&
          (await isMptextArchiveComplete(item.outDir, formats))
        ) {
          const existingArchive = await readExistingArchiveSummary(item.outDir);
          setItemStatus(snapshot, item, "skipped");
          item.message = "Skipped existing mptext archive bundle";
          item.endedAt = nowIso(dependencies.now);
          await appendResult({
            run_id: runId,
            token: record.token,
            account_key: record.account_key,
            source_url: record.source_url,
            out_dir: item.outDir,
            status: "skipped",
            archive_status: existingArchive.archiveStatus || "archived",
            capture_method: existingArchive.captureMethod || "mptext-api",
            raw_html_bytes: existingArchive.rawHtmlBytes,
            message: item.message,
            error_message: "",
            started_at: item.startedAt,
            ended_at: item.endedAt,
          });
          await persist();
          continue;
        }

        if (options.resume && options.deferExistingPartialOnResume) {
          const existingArchive = await readExistingArchiveSummary(item.outDir);
          if (hasExistingArchiveAttempt(existingArchive)) {
            setItemStatus(snapshot, item, "deferred");
            item.message = "Deferred existing incomplete mptext archive bundle";
            item.errorMessage = "";
            item.endedAt = nowIso(dependencies.now);
            await appendResult({
              run_id: runId,
              token: record.token,
              account_key: record.account_key,
              source_url: record.source_url,
              out_dir: item.outDir,
              status: "deferred",
              archive_status: existingArchive.archiveStatus,
              capture_method: existingArchive.captureMethod || "",
              raw_html_bytes: existingArchive.rawHtmlBytes,
              message: item.message,
              error_message: "",
              started_at: item.startedAt,
              ended_at: item.endedAt,
            });
            await persist();
            continue;
          }
        }

        setItemStatus(snapshot, item, "running");
        item.startedAt = nowIso(dependencies.now);
        item.message = "Downloading via mptext API";
        await persist();

        try {
          let usedFallback = false;
          let meta = await writeArchiveBundle({
            record,
            outDir: item.outDir,
            client,
            formats,
            archivedAt: nowIso(dependencies.now),
          });
          if (meta.status !== "archived" && fallbackClient) {
            item.message = "Primary mptext download was incomplete; retrying fallback endpoint";
            await persist();
            usedFallback = true;
            meta = await writeArchiveBundle({
              record,
              outDir: item.outDir,
              client: fallbackClient,
              formats,
              archivedAt: nowIso(dependencies.now),
              extraWarnings: [
                `primary mptext endpoint returned ${meta.status}; retried with fallback endpoint`,
              ],
            });
          }
          setItemStatus(
            snapshot,
            item,
            meta.status === "archived" ? "succeeded" : "failed",
          );
          item.message =
            meta.status === "archived"
              ? usedFallback
                ? "Archived via fallback mptext API"
                : "Archived via mptext API"
              : "Downloaded invalid raw.html";
          item.errorMessage = meta.status === "archived" ? "" : item.message;
          item.endedAt = nowIso(dependencies.now);
          await appendResult({
            run_id: runId,
            token: record.token,
            account_key: record.account_key,
            source_url: record.source_url,
            out_dir: item.outDir,
            status: item.status === "succeeded" ? "succeeded" : "failed",
            archive_status: meta.status,
            capture_method: meta.capture_method || "",
            raw_html_bytes: meta.raw_html_bytes,
            message: item.message,
            error_message: item.errorMessage,
            started_at: item.startedAt,
            ended_at: item.endedAt,
          });
          await persist();
        } catch (error) {
          setItemStatus(snapshot, item, "failed");
          item.message = error instanceof Error ? error.message : String(error);
          item.errorMessage = item.message;
          item.endedAt = nowIso(dependencies.now);
          await appendResult({
            run_id: runId,
            token: record.token,
            account_key: record.account_key,
            source_url: record.source_url,
            out_dir: item.outDir,
            status: "failed",
            archive_status: "",
            capture_method: "",
            raw_html_bytes: 0,
            message: item.message,
            error_message: item.errorMessage,
            started_at: item.startedAt,
            ended_at: item.endedAt,
          });
          await persist();
        }
      }
    }),
  );

  snapshot.status = "completed";
  snapshot.endedAt = nowIso(dependencies.now);
  await persist(true);
  await resultLogQueue;
  return snapshot;
}
