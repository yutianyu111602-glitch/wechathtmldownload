import { access, mkdir, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import { archiveArticle } from "./archiveArticle.js";
import { isValidArticleHtml } from "./articleHtmlQuality.js";
import { ensureDir, writeJson } from "../utils/fs.js";
import { readJsonlFile } from "../utils/jsonl.js";
import { compactSnapshotItems } from "../utils/snapshotCompaction.js";
import type {
  ArchiveBatchSnapshot,
  ArchiveMetaJson,
  ArchiveQueueRecord,
} from "./types.js";

interface RunArchiveBatchOptions {
  queuePath: string;
  archiveRoot: string;
  statusPath?: string;
  resume?: boolean;
  concurrency?: number;
}

interface ArchiveBatchDependencies {
  now?: () => string;
  archiveItem?: (record: ArchiveQueueRecord, outDir: string) => Promise<ArchiveMetaJson | void>;
}

function nowIso(now: (() => string) | undefined): string {
  return now ? now() : new Date().toISOString();
}

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readQueue(queuePath: string): Promise<ArchiveQueueRecord[]> {
  return readJsonlFile<ArchiveQueueRecord>(queuePath);
}

async function isArchiveComplete(outDir: string): Promise<boolean> {
  const required = [
    "raw.html",
    "page.mhtml",
    "page.pdf",
    "article.url.txt",
    "archive_meta.json",
  ];
  for (const fileName of required) {
    if (!(await pathExists(join(outDir, fileName)))) {
      return false;
    }
  }

  try {
    const meta = JSON.parse(
      await readFile(join(outDir, "archive_meta.json"), "utf-8"),
    ) as ArchiveMetaJson;
    if (meta.status === "skipped") {
      return true;
    }
    if (meta.status !== "archived") {
      return false;
    }
    const rawHtml = await readFile(join(outDir, "raw.html"), "utf-8");
    return isValidArticleHtml(rawHtml);
  } catch {
    return false;
  }
}

async function readArchiveMeta(outDir: string): Promise<ArchiveMetaJson | null> {
  try {
    return JSON.parse(
      await readFile(join(outDir, "archive_meta.json"), "utf-8"),
    ) as ArchiveMetaJson;
  } catch {
    return null;
  }
}

function summarizeArchiveFailure(meta: ArchiveMetaJson | null): string {
  if (!meta) {
    return "Archive incomplete: missing or invalid archive_meta.json";
  }
  const warnings = meta.warnings.slice(0, 3).join("; ");
  return warnings
    ? `Archive ${meta.status}: ${warnings}`
    : `Archive ${meta.status}: quality gate failed`;
}

function recalculateSnapshot(snapshot: ArchiveBatchSnapshot): void {
  let queuedCount = 0;
  let runningCount = 0;
  let succeededCount = 0;
  let failedCount = 0;
  let skippedCount = 0;

  for (const item of snapshot.items) {
    if (item.status === "queued") {
      queuedCount += 1;
      continue;
    }
    if (item.status === "running") {
      runningCount += 1;
      continue;
    }
    if (item.status === "succeeded") {
      succeededCount += 1;
      continue;
    }
    if (item.status === "failed") {
      failedCount += 1;
      continue;
    }
    skippedCount += 1;
  }

  snapshot.totalItems = snapshot.items.length;
  snapshot.queuedCount = queuedCount;
  snapshot.runningCount = runningCount;
  snapshot.succeededCount = succeededCount;
  snapshot.failedCount = failedCount;
  snapshot.skippedCount = skippedCount;
}

async function persistSnapshot(snapshot: ArchiveBatchSnapshot): Promise<void> {
  recalculateSnapshot(snapshot);
  const compactedSnapshot = compactSnapshotItems(snapshot);
  await ensureDir(dirname(snapshot.statusPath));
  await writeJson(snapshot.statusPath, compactedSnapshot);
}

async function defaultArchiveItem(
  record: ArchiveQueueRecord,
  outDir: string,
): Promise<ArchiveMetaJson> {
  return archiveArticle(record, outDir);
}

export async function runArchiveBatch(
  options: RunArchiveBatchOptions,
  dependencies: ArchiveBatchDependencies = {},
): Promise<ArchiveBatchSnapshot> {
  const queuePath = resolve(options.queuePath);
  const archiveRoot = resolve(options.archiveRoot);
  const statusPath = resolve(options.statusPath || join(archiveRoot, "archive-status.json"));
  const archiveItem = dependencies.archiveItem || defaultArchiveItem;
  const concurrency = Math.max(1, Math.floor(options.concurrency || 1));
  const records = await readQueue(queuePath);

  const items = records.map((record) => ({
    token: record.token,
    accountKey: record.account_key,
    sourceUrl: record.source_url,
    outDir: join(archiveRoot, record.account_key, record.token),
    status: "queued" as const,
    message: "Queued",
    errorMessage: "",
    startedAt: "",
    endedAt: "",
  }));

  const snapshot: ArchiveBatchSnapshot = {
    queuePath,
    archiveRoot,
    statusPath,
    status: "running",
    startedAt: nowIso(dependencies.now),
    endedAt: "",
    totalItems: items.length,
    queuedCount: items.length,
    runningCount: 0,
    succeededCount: 0,
    failedCount: 0,
    skippedCount: 0,
    items,
  };

  await persistSnapshot(snapshot);

  async function processOne(index: number): Promise<void> {
    const record = records[index];
    const item = snapshot.items[index];
    if (!item || !record) {
      return;
    }

    if (options.resume && (await isArchiveComplete(item.outDir))) {
      item.status = "skipped";
      item.message = "Skipped existing archive bundle";
      item.endedAt = nowIso(dependencies.now);
      await persistSnapshot(snapshot);
      return;
    }

    item.status = "running";
    item.startedAt = nowIso(dependencies.now);
    item.message = "Archiving article";
    await persistSnapshot(snapshot);

    try {
      await mkdir(item.outDir, { recursive: true });
      await archiveItem(record, item.outDir);
      if (await isArchiveComplete(item.outDir)) {
        item.status = "succeeded";
        item.message = "Archived";
      } else {
        const meta = await readArchiveMeta(item.outDir);
        item.status = "failed";
        item.message = summarizeArchiveFailure(meta);
        item.errorMessage = item.message;
      }
      item.endedAt = nowIso(dependencies.now);
      await persistSnapshot(snapshot);
    } catch (error) {
      item.status = "failed";
      item.message = error instanceof Error ? error.message : String(error);
      item.errorMessage = item.message;
      item.endedAt = nowIso(dependencies.now);
      await persistSnapshot(snapshot);
    }
  }

  let nextIndex = 0;
  async function worker(): Promise<void> {
    for (;;) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= records.length) {
        return;
      }
      await processOne(index);
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(concurrency, records.length) }, () => worker()),
  );

  snapshot.status = "completed";
  snapshot.endedAt = nowIso(dependencies.now);
  await persistSnapshot(snapshot);
  return snapshot;
}
