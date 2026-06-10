import { access } from "node:fs/promises";
import { dirname, extname, join, relative, resolve } from "node:path";

import { isAbortError, throwIfAborted } from "../utils/abort.js";

import { collectFiles } from "../utils/fileDiscovery.js";
import { ensureDir, writeJson, writeText } from "../utils/fs.js";
import { convertWithMarkItDown } from "../utils/markitdown.js";
import { compactSnapshotItems } from "../utils/snapshotCompaction.js";

export interface MarkitdownBatchItemSnapshot {
  inputPath: string;
  relativeInputPath: string;
  outPath: string;
  outDir: string;
  status:
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "skipped"
    | "cancelled";
  phase:
    | "queued"
    | "markitdown_convert"
    | "succeeded"
    | "failed"
    | "skipped"
    | "cancelled";
  step: number;
  totalSteps: number;
  message: string;
  errorMessage: string;
  startedAt: string;
  endedAt: string;
}

export interface MarkitdownBatchSnapshot {
  inputRoot: string;
  outRoot: string;
  statusPath: string;
  status: "running" | "completed" | "cancelled";
  startedAt: string;
  endedAt: string;
  totalItems: number;
  queuedCount: number;
  runningCount: number;
  succeededCount: number;
  failedCount: number;
  skippedCount: number;
  cancelledCount: number;
  completedCount: number;
  progressRatio: number;
  currentFile: string;
  currentPhase: "markitdown_convert" | "";
  itemCount?: number;
  itemLimit?: number;
  itemsTruncated?: boolean;
  items: MarkitdownBatchItemSnapshot[];
}

export interface RunMarkitdownBatchOptions {
  inputRoot: string;
  outRoot: string;
  statusPath?: string;
  resume?: boolean;
  signal?: AbortSignal;
  onSnapshot?: (snapshot: MarkitdownBatchSnapshot) => void | Promise<void>;
}

interface RunMarkitdownBatchDependencies {
  now?: () => string;
  convertMarkdown?: (
    inputPath: string,
    signal?: AbortSignal,
  ) => Promise<string>;
}

function stripExtension(filePath: string): string {
  const extension = extname(filePath);
  return extension ? filePath.slice(0, -extension.length) : filePath;
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

async function collectHtmlInputs(rootDir: string): Promise<string[]> {
  return collectFiles(rootDir, (filePath) => filePath.toLowerCase().endsWith(".html"));
}

export function deriveMarkitdownOutPath(
  inputPath: string,
  inputRoot: string,
  outRoot: string,
): string {
  return `${join(outRoot, stripExtension(relative(inputRoot, inputPath)))}.md`;
}

async function persistSnapshot(
  snapshot: MarkitdownBatchSnapshot,
  listener?: RunMarkitdownBatchOptions["onSnapshot"],
): Promise<void> {
  snapshot.completedCount =
    snapshot.succeededCount +
    snapshot.failedCount +
    snapshot.skippedCount +
    snapshot.cancelledCount;
  snapshot.progressRatio = snapshot.totalItems
    ? snapshot.completedCount / snapshot.totalItems
    : 1;
  const compactedSnapshot = compactSnapshotItems(snapshot);
  await ensureDir(dirname(snapshot.statusPath));
  await writeJson(snapshot.statusPath, compactedSnapshot);
  await listener?.(compactedSnapshot);
}

export async function runMarkitdownBatch(
  options: RunMarkitdownBatchOptions,
  dependencies: RunMarkitdownBatchDependencies = {},
): Promise<MarkitdownBatchSnapshot> {
  const inputRoot = resolve(options.inputRoot);
  const outRoot = resolve(options.outRoot);
  const statusPath = resolve(
    options.statusPath || join(outRoot, "markitdown-batch-status.json"),
  );
  const convertMarkdown =
    dependencies.convertMarkdown ||
    ((inputPath: string, signal?: AbortSignal) =>
      convertWithMarkItDown(inputPath, signal));
  const inputPaths = await collectHtmlInputs(inputRoot);

  const items = inputPaths.map((inputPath) => ({
    inputPath,
    relativeInputPath: relative(inputRoot, inputPath),
    outPath: deriveMarkitdownOutPath(inputPath, inputRoot, outRoot),
    outDir: dirname(deriveMarkitdownOutPath(inputPath, inputRoot, outRoot)),
    status: "queued" as const,
    phase: "queued" as const,
    step: 0,
    totalSteps: 1,
    message: "Queued",
    errorMessage: "",
    startedAt: "",
    endedAt: "",
  }));

  const snapshot: MarkitdownBatchSnapshot = {
    inputRoot,
    outRoot,
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
    cancelledCount: 0,
    completedCount: 0,
    progressRatio: 0,
    currentFile: "",
    currentPhase: "",
    items,
  };

  await persistSnapshot(snapshot, options.onSnapshot);

  const cancelQueuedItems = (): void => {
    const cancelledAt = nowIso(dependencies.now);
    for (const queuedItem of snapshot.items) {
      if (queuedItem.status !== "queued") {
        continue;
      }

      queuedItem.status = "cancelled";
      queuedItem.phase = "cancelled";
      queuedItem.message = "Cancelled before start";
      queuedItem.errorMessage = "Batch cancelled by user";
      queuedItem.endedAt = cancelledAt;
      snapshot.queuedCount -= 1;
      snapshot.cancelledCount += 1;
    }
  };

  for (const item of snapshot.items) {
    if (options.signal?.aborted) {
      cancelQueuedItems();
      snapshot.status = "cancelled";
      snapshot.endedAt = nowIso(dependencies.now);
      snapshot.currentFile = "";
      snapshot.currentPhase = "";
      await persistSnapshot(snapshot, options.onSnapshot);
      return snapshot;
    }

    snapshot.currentFile = item.inputPath;
    if (options.resume && (await pathExists(item.outPath))) {
      item.status = "skipped";
      item.phase = "skipped";
      item.message = "Skipped existing markdown output";
      item.endedAt = nowIso(dependencies.now);
      snapshot.queuedCount -= 1;
      snapshot.skippedCount += 1;
      await persistSnapshot(snapshot, options.onSnapshot);
      continue;
    }

    item.startedAt = nowIso(dependencies.now);
    item.status = "running";
    item.phase = "markitdown_convert";
    item.step = 1;
    item.message = "Converting HTML with MarkItDown";
    snapshot.queuedCount -= 1;
    snapshot.runningCount += 1;
    snapshot.currentPhase = "markitdown_convert";
    await persistSnapshot(snapshot, options.onSnapshot);

    try {
      throwIfAborted(options.signal);
      const markdown = await convertMarkdown(item.inputPath, options.signal);
      throwIfAborted(options.signal);
      await ensureDir(dirname(item.outPath));
      await writeText(item.outPath, markdown);
      item.status = "succeeded";
      item.phase = "succeeded";
      item.message = "Completed";
      item.endedAt = nowIso(dependencies.now);
      snapshot.runningCount -= 1;
      snapshot.succeededCount += 1;
    } catch (error) {
      if (isAbortError(error)) {
        item.status = "cancelled";
        item.phase = "cancelled";
        item.errorMessage =
          error instanceof Error ? error.message : String(error);
        item.message = item.errorMessage;
        item.endedAt = nowIso(dependencies.now);
        snapshot.runningCount -= 1;
        snapshot.cancelledCount += 1;
        cancelQueuedItems();
        snapshot.status = "cancelled";
        snapshot.endedAt = nowIso(dependencies.now);
        snapshot.currentFile = "";
        snapshot.currentPhase = "";
        await persistSnapshot(snapshot, options.onSnapshot);
        return snapshot;
      }

      item.status = "failed";
      item.phase = "failed";
      item.errorMessage =
        error instanceof Error ? error.message : String(error);
      item.message = item.errorMessage;
      item.endedAt = nowIso(dependencies.now);
      snapshot.runningCount -= 1;
      snapshot.failedCount += 1;
    }

    snapshot.currentPhase = "";
    await persistSnapshot(snapshot, options.onSnapshot);
  }

  if (options.signal?.aborted) {
    cancelQueuedItems();
    snapshot.status = "cancelled";
    snapshot.endedAt = nowIso(dependencies.now);
    snapshot.currentFile = "";
    snapshot.currentPhase = "";
    await persistSnapshot(snapshot, options.onSnapshot);
    return snapshot;
  }

  snapshot.status = "completed";
  snapshot.endedAt = nowIso(dependencies.now);
  snapshot.currentFile = "";
  snapshot.currentPhase = "";
  await persistSnapshot(snapshot, options.onSnapshot);
  return snapshot;
}
