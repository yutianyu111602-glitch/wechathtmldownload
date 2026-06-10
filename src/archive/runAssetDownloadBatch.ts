import { appendFile, mkdir, readFile, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import { load } from "cheerio";

import { extractAssets } from "../extract/extractAssets.js";
import { extractMeta } from "../extract/extractMeta.js";
import { ensureDir, writeJson } from "../utils/fs.js";
import { readJsonlFile } from "../utils/jsonl.js";
import { compactItems } from "../utils/snapshotCompaction.js";
import { downloadArticleAssets } from "./downloadArticleAssets.js";
import { isValidArticleHtml } from "./articleHtmlQuality.js";
import type {
  ArchiveMetaJson,
  ArchiveQueueRecord,
  AssetsLocalJson,
  LocalAssetRecord,
} from "./types.js";

type AppendFileImpl = (path: string, data: string, encoding: BufferEncoding) => Promise<void>;

interface RunAssetDownloadBatchOptions {
  archiveRoot: string;
  manifestPath: string;
  statusPath?: string;
  resultLogPath?: string;
  resume?: boolean;
  concurrency?: number;
  fetchImpl?: typeof fetch;
  appendFileImpl?: AppendFileImpl;
  appendRetryDelaysMs?: readonly number[];
}

type AssetDownloadStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";

interface AssetDownloadItem {
  token: string;
  accountKey: string;
  outDir: string;
  status: AssetDownloadStatus;
  message: string;
  errorMessage: string;
  startedAt: string;
  endedAt: string;
}

interface AssetDownloadResultLogRecord {
  run_id: string;
  token: string;
  account_key: string;
  out_dir: string;
  status: "succeeded" | "failed" | "skipped";
  image_count: number;
  media_count: number;
  downloaded_count: number;
  failed_asset_count: number;
  message: string;
  error_message: string;
  started_at: string;
  ended_at: string;
}

function getStatusPersistIntervalMs(): number {
  const configured = Number(process.env.WECHAT_BATCH_STATUS_INTERVAL_MS);
  if (Number.isFinite(configured) && configured >= 0) {
    return Math.floor(configured);
  }
  return 2_000;
}

function nowIso(): string {
  return new Date().toISOString();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

function isRetryableAppendError(error: unknown): boolean {
  const code = (error as NodeJS.ErrnoException | undefined)?.code;
  return code === "EBUSY" || code === "EPERM";
}

function allAssets(assets: AssetsLocalJson): LocalAssetRecord[] {
  return [...(assets.images || []), ...(assets.media || [])];
}

function countAssetStatuses(assets: AssetsLocalJson): {
  imageCount: number;
  mediaCount: number;
  downloadedCount: number;
  failedAssetCount: number;
} {
  const records = allAssets(assets);
  return {
    imageCount: assets.images?.length || 0,
    mediaCount: assets.media?.length || 0,
    downloadedCount: records.filter((record) => record.status === "downloaded").length,
    failedAssetCount: records.filter((record) => record.status === "failed").length,
  };
}

async function readAssetsLocalIfComplete(
  bundleDir: string,
  assetsPath: string,
  expectedImageUrls: string[],
): Promise<AssetsLocalJson | null> {
  let assets: AssetsLocalJson;
  try {
    assets = JSON.parse(await readFile(assetsPath, "utf-8")) as AssetsLocalJson;
  } catch {
    return null;
  }

  if (!Array.isArray(assets.images) || !Array.isArray(assets.media)) {
    return null;
  }
  const actualImageUrls = assets.images.map((asset) => asset.remote_url);
  if (
    actualImageUrls.length !== expectedImageUrls.length ||
    actualImageUrls.some((url, index) => url !== expectedImageUrls[index])
  ) {
    return null;
  }

  for (const asset of allAssets(assets)) {
    if (asset.status === "failed") {
      return null;
    }
    if (asset.status !== "downloaded") {
      continue;
    }
    if (!asset.local_path) {
      return null;
    }
    try {
      const localStat = await stat(join(bundleDir, asset.local_path));
      if (localStat.size <= 0) {
        return null;
      }
      if (asset.file_size > 0 && localStat.size !== asset.file_size) {
        return null;
      }
    } catch {
      return null;
    }
  }

  return assets;
}

async function readExpectedImageUrls(bundleDir: string): Promise<string[]> {
  const rawHtml = await readFile(join(bundleDir, "raw.html"), "utf-8");
  const $ = load(rawHtml);
  const meta = extractMeta($, rawHtml, "");
  const assets = extractAssets($, meta.source_url);
  return assets.images
    .map((image) => image.data_src || image.src)
    .filter((url): url is string => Boolean(url));
}

async function readArchiveReady(bundleDir: string): Promise<{
  ready: boolean;
  message: string;
}> {
  let meta: ArchiveMetaJson;
  try {
    meta = JSON.parse(await readFile(join(bundleDir, "archive_meta.json"), "utf-8")) as ArchiveMetaJson;
  } catch {
    return {
      ready: false,
      message: "missing or invalid archive_meta.json",
    };
  }

  if (meta.status !== "archived") {
    const warning = meta.warnings?.[0] ? `: ${meta.warnings[0]}` : "";
    return {
      ready: false,
      message: `archive_meta.status=${meta.status}${warning}`,
    };
  }

  try {
    const rawHtml = await readFile(join(bundleDir, "raw.html"), "utf-8");
    if (!isValidArticleHtml(rawHtml)) {
      return {
        ready: false,
        message: "raw.html failed article quality gate",
      };
    }
  } catch {
    return {
      ready: false,
      message: "missing or unreadable raw.html",
    };
  }

  return {
    ready: true,
    message: "archive ready",
  };
}

async function appendResultLogRecord(
  resultLogPath: string,
  record: AssetDownloadResultLogRecord,
  appendFileImpl: AppendFileImpl,
  retryDelaysMs: readonly number[],
): Promise<void> {
  await ensureDir(dirname(resultLogPath));
  const line = `${JSON.stringify(record)}\n`;
  for (let attempt = 0; ; attempt += 1) {
    try {
      await appendFileImpl(resultLogPath, line, "utf-8");
      return;
    } catch (error) {
      if (!isRetryableAppendError(error) || attempt >= retryDelaysMs.length) {
        throw error;
      }
      await sleep(Math.max(0, retryDelaysMs[attempt] ?? 0));
    }
  }
}

export async function runAssetDownloadBatch(
  options: RunAssetDownloadBatchOptions,
): Promise<{ totalItems: number; succeededCount: number; skippedCount: number; failedCount: number }> {
  const archiveRoot = resolve(options.archiveRoot);
  const manifestPath = resolve(options.manifestPath);
  const statusPath = resolve(options.statusPath || join(archiveRoot, "asset-retention-status.json"));
  const resultLogPath = resolve(
    options.resultLogPath || join(archiveRoot, "asset-retention-results.jsonl"),
  );
  const appendFileImpl = options.appendFileImpl || appendFile;
  const appendRetryDelaysMs = options.appendRetryDelaysMs ?? [100, 250, 500, 1_000, 2_000];
  const records = await readJsonlFile<ArchiveQueueRecord>(manifestPath);
  const runId = nowIso();

  const concurrency = Math.max(1, Math.min(options.concurrency ?? 1, 16));
  const items: AssetDownloadItem[] =
    records.map((record) => ({
      token: record.token,
      accountKey: record.account_key,
      outDir: join(archiveRoot, record.account_key, record.token),
      status: "queued",
      message: "Queued",
      errorMessage: "",
      startedAt: "",
      endedAt: "",
    }));
  const summary = {
    totalItems: records.length,
    queuedCount: records.length,
    runningCount: 0,
    succeededCount: 0,
    skippedCount: 0,
    failedCount: 0,
    items,
  };

  function setStatus(item: AssetDownloadItem, status: AssetDownloadStatus): void {
    if (item.status === status) {
      return;
    }
    if (item.status === "queued") summary.queuedCount -= 1;
    else if (item.status === "running") summary.runningCount -= 1;
    else if (item.status === "succeeded") summary.succeededCount -= 1;
    else if (item.status === "skipped") summary.skippedCount -= 1;
    else summary.failedCount -= 1;

    item.status = status;

    if (status === "queued") summary.queuedCount += 1;
    else if (status === "running") summary.runningCount += 1;
    else if (status === "succeeded") summary.succeededCount += 1;
    else if (status === "skipped") summary.skippedCount += 1;
    else summary.failedCount += 1;
  }

  const statusPersistIntervalMs = getStatusPersistIntervalMs();
  let lastPersistedAtMs = 0;
  let persistQueue = Promise.resolve();
  let resultLogQueue = Promise.resolve();
  async function persist(force = false): Promise<void> {
    const currentTimeMs = Date.now();
    if (
      !force &&
      statusPersistIntervalMs > 0 &&
      currentTimeMs - lastPersistedAtMs < statusPersistIntervalMs
    ) {
      return;
    }
    lastPersistedAtMs = currentTimeMs;
    persistQueue = persistQueue.then(async () => {
      const compactedItems = compactItems(items);
      await writeJson(statusPath, {
        ...summary,
        items: compactedItems.items,
        itemCount: compactedItems.itemCount,
        itemLimit: compactedItems.itemLimit,
        itemsTruncated: compactedItems.itemsTruncated,
      });
    });
    await persistQueue;
  }
  async function appendResult(record: AssetDownloadResultLogRecord): Promise<void> {
    resultLogQueue = resultLogQueue.then(() =>
      appendResultLogRecord(resultLogPath, record, appendFileImpl, appendRetryDelaysMs),
    );
    await resultLogQueue;
  }

  await persist(true);

  let nextIndex = 0;
  await Promise.all(
    Array.from({ length: Math.min(concurrency, records.length) }, async () => {
      while (nextIndex < records.length) {
        const index = nextIndex;
        nextIndex += 1;
        const record = records[index];
        const item = items[index];
        if (!record || !item) {
          continue;
        }

        const bundleDir = join(archiveRoot, record.account_key, record.token);
        const assetsPath = join(bundleDir, "assets_local.json");
        try {
          await mkdir(bundleDir, { recursive: true });
          const archiveReady = await readArchiveReady(bundleDir);
          if (!archiveReady.ready) {
            setStatus(item, "failed");
            item.startedAt = item.startedAt || nowIso();
            item.message = `Archive not ready for asset download: ${archiveReady.message}`;
            item.errorMessage = item.message;
            item.endedAt = nowIso();
            await appendResult({
              run_id: runId,
              token: record.token,
              account_key: record.account_key,
              out_dir: bundleDir,
              status: "failed",
              image_count: 0,
              media_count: 0,
              downloaded_count: 0,
              failed_asset_count: 0,
              message: item.message,
              error_message: item.errorMessage,
              started_at: item.startedAt,
              ended_at: item.endedAt,
            });
            await persist();
            continue;
          }

          if (options.resume) {
            const expectedImageUrls = await readExpectedImageUrls(bundleDir);
            const existingAssets = await readAssetsLocalIfComplete(
              bundleDir,
              assetsPath,
              expectedImageUrls,
            );
            if (existingAssets) {
              const counts = countAssetStatuses(existingAssets);
              setStatus(item, "skipped");
              item.message = "Existing assets_local.json";
              item.errorMessage = "";
              item.endedAt = nowIso();
              await appendResult({
                run_id: runId,
                token: record.token,
                account_key: record.account_key,
                out_dir: bundleDir,
                status: "skipped",
                image_count: counts.imageCount,
                media_count: counts.mediaCount,
                downloaded_count: counts.downloadedCount,
                failed_asset_count: counts.failedAssetCount,
                message: item.message,
                error_message: "",
                started_at: item.startedAt,
                ended_at: item.endedAt,
              });
              await persist();
              continue;
            }
          }

          setStatus(item, "running");
          item.startedAt = nowIso();
          item.message = "Downloading local assets";
          item.errorMessage = "";
          await persist();
          const assets = await downloadArticleAssets(bundleDir, {
            fetchImpl: options.fetchImpl,
          });
          const counts = countAssetStatuses(assets);
          setStatus(item, counts.failedAssetCount > 0 ? "failed" : "succeeded");
          item.message =
            counts.failedAssetCount > 0
              ? `Downloaded assets with ${counts.failedAssetCount} failed assets`
              : "Downloaded local assets";
          item.errorMessage = counts.failedAssetCount > 0 ? item.message : "";
          item.endedAt = nowIso();
          await appendResult({
            run_id: runId,
            token: record.token,
            account_key: record.account_key,
            out_dir: bundleDir,
            status: item.status === "succeeded" ? "succeeded" : "failed",
            image_count: counts.imageCount,
            media_count: counts.mediaCount,
            downloaded_count: counts.downloadedCount,
            failed_asset_count: counts.failedAssetCount,
            message: item.message,
            error_message: item.errorMessage,
            started_at: item.startedAt,
            ended_at: item.endedAt,
          });
        } catch (error) {
          setStatus(item, "failed");
          item.message = error instanceof Error ? error.message : String(error);
          item.errorMessage = item.message;
          item.endedAt = nowIso();
          await appendResult({
            run_id: runId,
            token: record.token,
            account_key: record.account_key,
            out_dir: bundleDir,
            status: "failed",
            image_count: 0,
            media_count: 0,
            downloaded_count: 0,
            failed_asset_count: 0,
            message: item.message,
            error_message: item.errorMessage,
            started_at: item.startedAt,
            ended_at: item.endedAt,
          });
        }
        await persist();
      }
    }),
  );

  await persist(true);
  await resultLogQueue;
  return summary;
}
