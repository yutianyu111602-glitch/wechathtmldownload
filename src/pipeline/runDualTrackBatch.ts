import { access } from "node:fs/promises";
import { basename, dirname, extname, join, relative, resolve } from "node:path";

import type { ArchiveQueueRecord } from "../archive/types.js";
import type {
  BatchItemSnapshot,
  BatchSnapshot,
  ProcessArticleDualTrackResult,
  ProcessProgressListener,
  RunDualTrackBatchOptions,
} from "../types.js";
import { isAbortError, throwIfAborted } from "../utils/abort.js";
import { collectFiles } from "../utils/fileDiscovery.js";
import { ensureDir, writeJson } from "../utils/fs.js";
import { readJsonlFile } from "../utils/jsonl.js";
import { compactSnapshotItems } from "../utils/snapshotCompaction.js";
import { createQueueExecutor } from "../utils/queueExecutor.js";
import { shouldSkipOnResume } from "./artifactManifest.js";
import { processArchiveBundleDualTrack } from "./processArchiveBundleDualTrack.js";
import { processArticleDualTrack } from "./processArticleDualTrack.js";

type ProcessItemFn = (
  inputPath: string,
  outDir: string,
  onProgress?: ProcessProgressListener,
  signal?: AbortSignal,
) => Promise<ProcessArticleDualTrackResult | unknown>;

interface BatchRunnerDependencies {
  now?: () => string;
  processItem?: ProcessItemFn;
  processArchiveItem?: ProcessItemFn;
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

async function collectArchiveInputs(
  inputRoot: string,
  manifestPath: string,
): Promise<string[]> {
  if (!manifestPath) {
    throw new Error(
      "Archive input mode requires --manifestPath pointing to archive_queue.jsonl",
    );
  }
  const records = await readJsonlFile<ArchiveQueueRecord>(manifestPath);
  return records.map((record) => join(inputRoot, record.account_key, record.token));
}

export function deriveBatchOutDir(
  inputPath: string,
  inputRoot: string,
  outRoot: string,
): string {
  return join(outRoot, stripExtension(relative(inputRoot, inputPath)));
}

function incrementSnapshotCounter(
  snapshot: BatchSnapshot,
  status: BatchItemSnapshot["status"],
): void {
  if (status === "queued") snapshot.queuedCount += 1;
  else if (status === "running") snapshot.runningCount += 1;
  else if (status === "succeeded") snapshot.succeededCount += 1;
  else if (status === "failed") snapshot.failedCount += 1;
  else if (status === "cancelled") snapshot.cancelledCount += 1;
  else if (status === "skipped") snapshot.skippedCount += 1;
}

function decrementSnapshotCounter(
  snapshot: BatchSnapshot,
  status: BatchItemSnapshot["status"],
): void {
  if (status === "queued") snapshot.queuedCount -= 1;
  else if (status === "running") snapshot.runningCount -= 1;
  else if (status === "succeeded") snapshot.succeededCount -= 1;
  else if (status === "failed") snapshot.failedCount -= 1;
  else if (status === "cancelled") snapshot.cancelledCount -= 1;
  else if (status === "skipped") snapshot.skippedCount -= 1;
}

function updateSnapshotCompletedCount(snapshot: BatchSnapshot): void {
  snapshot.completedCount =
    snapshot.succeededCount +
    snapshot.failedCount +
    snapshot.skippedCount +
    snapshot.cancelledCount;
  snapshot.progressRatio =
    snapshot.totalItems === 0
      ? 1
      : snapshot.completedCount / snapshot.totalItems;
}

async function persistSnapshot(
  snapshot: BatchSnapshot,
  listener?: RunDualTrackBatchOptions["onSnapshot"],
): Promise<void> {
  updateSnapshotCompletedCount(snapshot);
  const compactedSnapshot = compactSnapshotItems(snapshot);
  await ensureDir(dirname(snapshot.statusPath));
  await writeJson(snapshot.statusPath, compactedSnapshot);
  await listener?.(compactedSnapshot);
}

export async function runDualTrackBatch(
  options: RunDualTrackBatchOptions,
  dependencies: BatchRunnerDependencies = {},
): Promise<BatchSnapshot> {
  const inputRoot = resolve(options.inputRoot);
  const outRoot = resolve(options.outRoot);
  const inputMode = options.inputMode || "html";
  const statusPath = resolve(
    options.statusPath || join(outRoot, "batch-status.json"),
  );
  const processItem =
    inputMode === "archive"
      ? dependencies.processArchiveItem || ((inputPath, outDir, onProgress, signal) =>
          processArchiveBundleDualTrack(inputPath, outDir, onProgress, signal))
      : dependencies.processItem || processArticleDualTrack;
  const inputPaths =
    inputMode === "archive"
      ? await collectArchiveInputs(inputRoot, resolve(options.manifestPath || ""))
      : await collectHtmlInputs(inputRoot);

  const items: BatchItemSnapshot[] = [];
  const scanTotal = inputPaths.length;
  let scanIdx = 0;
  let scanSkipped = 0;
  let scanLastLog = Date.now();
  console.error(`[resume-scan] start total=${scanTotal} fast=${process.env.WECHAT_RESUME_FAST === "1" ? "1" : "0"}`);
  for (const inputPath of inputPaths) {
    const outDir = deriveBatchOutDir(inputPath, inputRoot, outRoot);
    const skipCheck = Boolean(options.resume)
      ? await shouldSkipOnResume(outDir, basename(inputPath))
      : { skip: false, reason: "Resume disabled" };
    const shouldSkip = skipCheck.skip;
    const endedAt = shouldSkip ? nowIso(dependencies.now) : "";
    scanIdx += 1;
    if (shouldSkip) scanSkipped += 1;
    const nowMs = Date.now();
    if (nowMs - scanLastLog >= 5000 || scanIdx === scanTotal) {
      console.error(`[resume-scan] ${scanIdx}/${scanTotal} skipped=${scanSkipped}`);
      scanLastLog = nowMs;
    }

    items.push({
      inputPath,
      relativeInputPath: relative(inputRoot, inputPath),
      outDir,
      status: shouldSkip ? "skipped" : "queued",
      phase: shouldSkip ? "skipped" : "queued",
      step: 0,
      totalSteps: 5,
      message: shouldSkip ? `Skipped: ${skipCheck.reason}` : "Queued",
      errorMessage: "",
      startedAt: "",
      endedAt,
    });
  }

  const snapshot: BatchSnapshot = {
    inputRoot,
    outRoot,
    statusPath,
    status: "running",
    startedAt: nowIso(dependencies.now),
    endedAt: "",
    totalItems: items.length,
    queuedCount: 0,
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

  for (const item of items) {
    incrementSnapshotCounter(snapshot, item.status);
  }
  updateSnapshotCompletedCount(snapshot);

  await persistSnapshot(snapshot, options.onSnapshot);

  const cancelQueuedItems = (): void => {
    const cancelledAt = nowIso(dependencies.now);
    let batchCancelled = 0;
    for (const queuedItem of snapshot.items) {
      if (queuedItem.status !== "queued") {
        continue;
      }

      decrementSnapshotCounter(snapshot, queuedItem.status);
      incrementSnapshotCounter(snapshot, "cancelled");
      batchCancelled += 1;
      queuedItem.status = "cancelled";
      queuedItem.phase = "cancelled";
      queuedItem.message = "Cancelled before start";
      queuedItem.errorMessage = "Batch cancelled by user";
      queuedItem.endedAt = cancelledAt;
    }
    snapshot.completedCount += batchCancelled;
    snapshot.progressRatio =
      snapshot.totalItems === 0
        ? 1
        : snapshot.completedCount / snapshot.totalItems;
  };

  async function processSingleItem(item: BatchItemSnapshot): Promise<void> {
    decrementSnapshotCounter(snapshot, item.status);
    incrementSnapshotCounter(snapshot, "running");
    item.status = "running";
    item.startedAt = nowIso(dependencies.now);
    item.message = "Starting";
    snapshot.currentFile = item.inputPath;
    snapshot.currentPhase = "parse_html";
    await persistSnapshot(snapshot, options.onSnapshot);

    try {
      throwIfAborted(options.signal);
      await processItem(
        item.inputPath,
        item.outDir,
        async (event) => {
          item.phase = event.phase;
          item.step = event.step;
          item.totalSteps = event.totalSteps;
          item.message = event.message;
          snapshot.currentFile = item.inputPath;
          snapshot.currentPhase = event.phase;
          await persistSnapshot(snapshot, options.onSnapshot);
        },
        options.signal,
      );

      decrementSnapshotCounter(snapshot, item.status);
      incrementSnapshotCounter(snapshot, "succeeded");
      item.status = "succeeded";
      item.phase = "succeeded";
      item.step = item.totalSteps;
      item.message = "Completed";
      item.endedAt = nowIso(dependencies.now);
      snapshot.currentFile = item.inputPath;
      snapshot.currentPhase = "";
      await persistSnapshot(snapshot, options.onSnapshot);
    } catch (error) {
      if (isAbortError(error)) {
        const message = error instanceof Error ? error.message : String(error);
        decrementSnapshotCounter(snapshot, item.status);
        incrementSnapshotCounter(snapshot, "cancelled");
        item.status = "cancelled";
        item.phase = "cancelled";
        item.errorMessage = message;
        item.message = message;
        item.endedAt = nowIso(dependencies.now);
        throw error; // re-throw so caller can handle batch-wide cancel
      }

      const message = error instanceof Error ? error.message : String(error);
      decrementSnapshotCounter(snapshot, item.status);
      incrementSnapshotCounter(snapshot, "failed");
      item.status = "failed";
      item.phase = "failed";
      item.errorMessage = message;
      item.message = message;
      item.endedAt = nowIso(dependencies.now);
      snapshot.currentFile = item.inputPath;
      snapshot.currentPhase = "";
      await persistSnapshot(snapshot, options.onSnapshot);
    }
  }

  const concurrency = options.concurrency ?? 1;

  if (concurrency > 1) {
    // Parallel mode with bounded concurrency
    const executor = createQueueExecutor({ concurrency });
    let abortTriggered = false;

    const abortHandler = (): void => {
      abortTriggered = true;
      executor.clear();
    };
    options.signal?.addEventListener("abort", abortHandler);

    try {
      for (const item of snapshot.items) {
        if (item.status === "skipped") {
          continue;
        }

        if (options.signal?.aborted || abortTriggered) {
          cancelQueuedItems();
          snapshot.status = "cancelled";
          snapshot.endedAt = nowIso(dependencies.now);
          snapshot.currentFile = "";
          snapshot.currentPhase = "";
          await persistSnapshot(snapshot, options.onSnapshot);
          return snapshot;
        }

        executor.add(item.inputPath, async () => {
          if (options.signal?.aborted || abortTriggered) {
            throw new Error("AbortError"); // Will be caught as generic error, then handled below
          }
          await processSingleItem(item);
        });
      }

      await executor.onIdle();
    } catch {
      // If any task threw (including abort), handle cancellation
      cancelQueuedItems();
      snapshot.status = "cancelled";
      snapshot.endedAt = nowIso(dependencies.now);
      snapshot.currentFile = "";
      snapshot.currentPhase = "";
      await persistSnapshot(snapshot, options.onSnapshot);
      return snapshot;
    } finally {
      options.signal?.removeEventListener("abort", abortHandler);
    }
  } else {
    // Serial mode (legacy behavior)
    for (const item of snapshot.items) {
      if (item.status === "skipped") {
        continue;
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

      try {
        await processSingleItem(item);
      } catch (error) {
        if (isAbortError(error)) {
          cancelQueuedItems();
          snapshot.status = "cancelled";
          snapshot.endedAt = nowIso(dependencies.now);
          snapshot.currentFile = "";
          snapshot.currentPhase = "";
          await persistSnapshot(snapshot, options.onSnapshot);
          return snapshot;
        }
        // Non-abort errors are already handled inside processSingleItem
      }
    }
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
