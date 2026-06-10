import { createHash } from "node:crypto";
import { existsSync } from "node:fs";         // FIX M3: static import
import { join, relative } from "node:path";   // FIX M3: static import

import {
  loadJobStoreSnapshot,
  saveJobStoreSnapshot,
} from "../state/jobStoreFile.js";
import {
  claimNextQueuedJob,
  makeArticleId,
  markJobCancelled,
  markJobStageQueued,
  markJobStageSucceeded,
  recoverStaleJobs,
  upsertArticleRecord,
  upsertProcessingJob,
} from "../state/jobStore.js";
import type { BatchProjection, JobStoreSnapshot } from "../state/jobTypes.js";
import { collectFiles } from "../utils/fileDiscovery.js";
import { buildBatchProjection } from "./buildBatchProjection.js";
import {
  runDualTrackExtractStage,
  runMirrorExportStage,
  type StageRunnerContext,
} from "./stageRunners.js";

export interface KeeperRunOptions {
  inputRoot: string;
  outRoot: string;
  statePath?: string;
  resume?: boolean;
  once?: boolean;            // FIX M4: process exactly one job then exit
  signal?: AbortSignal;
  onSnapshot?: (projection: BatchProjection) => void | Promise<void>;
  onProgress?: (message: string) => void;
}

function defaultStatePath(outRoot: string): string {
  return join(outRoot, "_state", "job-store.json");
}

async function scanHtmlFiles(inputRoot: string): Promise<string[]> {
  return collectFiles(inputRoot, (_filePath, fileName) => /\.html?$/i.test(fileName));
}

async function registerHtmlInputsAsJobs(
  snapshot: JobStoreSnapshot,
  inputRoot: string,
  htmlFiles: string[],
): Promise<void> {
  const now = new Date().toISOString();
  for (const inputPath of htmlFiles) {
    const relativeInputPath = relative(inputRoot, inputPath).replace(/\\/g, "/");
    const articleId = makeArticleId(inputPath);
    upsertArticleRecord(snapshot, {
      inputPath,
      relativeInputPath,
      sourceUrl: "",
      title: "",
      accountName: "",
      publishTimeText: "",
      publishTimeIso: "",
      contentHash: createHash("sha1").update(relativeInputPath).digest("hex").slice(0, 8),
      updatedAt: now,
    });
    const job = upsertProcessingJob(snapshot, articleId, "batch_scan", inputRoot, inputPath);
    // Advance html_ingest immediately — it is synchronous (file already on disk)
    if (job.stageStates["html_ingest"]?.status === "pending") {
      job.stageStates["html_ingest"].status = "done";
      job.stageStates["html_ingest"].startedAt = now;
      job.stageStates["html_ingest"].endedAt = now;
      job.stageStates["html_ingest"].notes = ["registered-from-scan"];
      markJobStageQueued(snapshot, job.jobId, "dual_track_extract");
    }
  }
}

// FIX B2: cancel both running and queued jobs on abort
function cancelAllActiveJobs(snapshot: JobStoreSnapshot): void {
  for (const job of snapshot.jobs) {
    if (job.status === "running" || job.status === "queued") {
      markJobCancelled(snapshot, job.jobId);
    }
  }
}

export async function runKeeperOnce(options: KeeperRunOptions): Promise<void> {
  const {
    inputRoot,
    outRoot,
    statePath,
    resume,
    once,
    signal,
    onSnapshot,
    onProgress,
  } = options;

  const resolvedStatePath = statePath ?? defaultStatePath(outRoot);
  const snapshot = await loadJobStoreSnapshot(resolvedStatePath);

  recoverStaleJobs(snapshot);

  const htmlFiles = await scanHtmlFiles(inputRoot);
  await registerHtmlInputsAsJobs(snapshot, inputRoot, htmlFiles);

  snapshot.updatedAt = new Date().toISOString();
  await saveJobStoreSnapshot(resolvedStatePath, snapshot);

  // Emit initial projection so GUI knows total count immediately
  await onSnapshot?.(buildBatchProjection(snapshot, { pipeline: "keeper", inputRoot, outRoot }));

  const context: StageRunnerContext = {
    snapshot,
    outRoot,
    now: () => new Date().toISOString(),
    signal,
    onProgress,
  };

  while (true) {
    // FIX B2: check abort at top of every iteration
    if (signal?.aborted) {
      cancelAllActiveJobs(snapshot);
      snapshot.updatedAt = new Date().toISOString();
      await saveJobStoreSnapshot(resolvedStatePath, snapshot);
      break;
    }

    const job = claimNextQueuedJob(snapshot);
    if (!job) break;

    // Send projection before starting job so GUI sees "running"
    await onSnapshot?.(buildBatchProjection(snapshot, { pipeline: "keeper", inputRoot, outRoot }));

    try {
      if (job.currentStage === "dual_track_extract") {
        // Resume check: skip if llm_input.md already exists
        // FIX M3: existsSync is now a static import — no dynamic import in loop
        if (resume) {
          const article = snapshot.articles.find((a) => a.articleId === job.articleId);
          if (article) {
            const relKey = article.relativeInputPath.replace(/\.html?$/i, "");
            const llmInputPath = join(outRoot, relKey, "llm_input.md");
            if (existsSync(llmInputPath)) {
              markJobStageSucceeded(snapshot, job.jobId, "dual_track_extract", [llmInputPath], "mirror_export");
              markJobStageSucceeded(snapshot, job.jobId, "mirror_export", [], null);
              snapshot.updatedAt = new Date().toISOString();
              await saveJobStoreSnapshot(resolvedStatePath, snapshot);
              await onSnapshot?.(buildBatchProjection(snapshot, { pipeline: "keeper", inputRoot, outRoot }));
              // FIX M4: --once: stop after processing (or skipping) one job
              if (once) break;
              continue;
            }
          }
        }
        await runDualTrackExtractStage(job, context);
      } else if (job.currentStage === "mirror_export") {
        await runMirrorExportStage(job, context);
      } else {
        // Unknown future stage — mark completed gracefully
        markJobStageSucceeded(snapshot, job.jobId, job.currentStage, [], null);
      }
    } catch {
      // Error already persisted via markJobStageFailed inside the runner
    }

    snapshot.updatedAt = new Date().toISOString();
    await saveJobStoreSnapshot(resolvedStatePath, snapshot);

    await onSnapshot?.(buildBatchProjection(snapshot, { pipeline: "keeper", inputRoot, outRoot }));

    // FIX M4: --once: exit after one job (success or failure)
    if (once) break;
  }

  // Final snapshot — always sent, even on empty queue or abort
  const finalProjection = buildBatchProjection(snapshot, { pipeline: "keeper", inputRoot, outRoot });
  await saveJobStoreSnapshot(resolvedStatePath, snapshot);
  await onSnapshot?.(finalProjection);
}
