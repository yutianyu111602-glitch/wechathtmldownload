import { join } from "node:path";
import type { BatchProjection, JobStoreSnapshot } from "../state/jobTypes.js";
import { compactSnapshotItems } from "../utils/snapshotCompaction.js";

export function buildBatchProjection(
  snapshot: JobStoreSnapshot,
  options: {
    pipeline: BatchProjection["pipeline"];
    inputRoot: string;
    outRoot: string;
  },
): BatchProjection {
  const { pipeline, inputRoot, outRoot } = options;
  const jobs = snapshot.jobs;
  const articlesById = new Map(
    snapshot.articles.map((article) => [article.articleId, article]),
  );

  let queuedCount = 0;
  let runningCount = 0;
  let succeededCount = 0;
  let failedCount = 0;
  let cancelledCount = 0;
  let completedCount = 0;

  let currentFile = "";
  let currentPhase = "";
  let startedAt = "";

  const items: BatchProjection["items"] = [];

  for (const job of jobs) {
    const article = articlesById.get(job.articleId);
    const relPath = article?.relativeInputPath ?? job.jobId;
    const inputPath = article?.inputPath ?? "";

    let phase = job.currentStage as string;
    const stageState = job.stageStates[job.currentStage];
    if (stageState?.status === "running") {
      phase = job.currentStage;
    }

    let guiStatus = job.status as string;
    if (job.status === "completed") {
      guiStatus = "succeeded";
      succeededCount += 1;
      completedCount += 1;
    } else if (job.status === "queued") {
      queuedCount += 1;
    } else if (job.status === "running") {
      runningCount += 1;
      currentFile = inputPath;
      currentPhase = job.currentStage;
      if (!startedAt) startedAt = job.startedAt;
    } else if (job.status === "failed") {
      failedCount += 1;
      completedCount += 1;
    } else if (job.status === "cancelled") {
      cancelledCount += 1;
      completedCount += 1;
    }

    // FIX M2: compute outDir from relativeInputPath so detail panel shows real path
    const relKey = article?.relativeInputPath?.replace(/\.html?$/i, "") ?? "";
    const outDir = relKey ? join(outRoot, relKey) : "";

    items.push({
      inputPath,
      relativeInputPath: relPath,
      outDir,
      status: guiStatus,
      phase,
      message: stageState?.notes?.[0] ?? "",
      errorMessage: job.lastError,
      startedAt: job.startedAt,
      endedAt: job.finishedAt,
    });
  }

  const totalItems = jobs.length;
  const progressRatio = totalItems > 0 ? completedCount / totalItems : 0;

  let overallStatus: BatchProjection["status"] = "idle";
  if (runningCount > 0 || queuedCount > 0) {
    overallStatus = "running";
  } else if (totalItems > 0 && cancelledCount > 0 && succeededCount + failedCount + cancelledCount === totalItems) {
    overallStatus = "cancelled";
  } else if (totalItems > 0 && completedCount === totalItems) {
    overallStatus = "completed";
  }

  return compactSnapshotItems({
    pipeline,
    status: overallStatus,
    inputRoot,
    outRoot,
    totalItems,
    queuedCount,
    runningCount,
    succeededCount,
    failedCount,
    skippedCount: 0,
    cancelledCount,
    completedCount,
    progressRatio,
    currentFile,
    currentPhase,
    startedAt,
    items,
  });
}
