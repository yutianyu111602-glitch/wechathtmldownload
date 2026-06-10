import { createHash } from "node:crypto";
import { relative } from "node:path";
import type {
  ArticleRecord,
  JobLifecycleStatus,
  JobStageState,
  JobStoreSnapshot,
  PipelineStageName,
  ProcessingJob,
  StageRunStatus,
} from "./jobTypes.js";

export function makeArticleId(inputPath: string): string {
  return "a_" + createHash("sha1").update(inputPath).digest("hex").slice(0, 16);
}

export function makeJobId(articleId: string): string {
  return "job_" + articleId.slice(2);
}

export function upsertArticleRecord(
  snapshot: JobStoreSnapshot,
  fields: Omit<ArticleRecord, "articleId" | "discoveredAt"> & { discoveredAt?: string },
): ArticleRecord {
  const now = new Date().toISOString();
  const articleId = makeArticleId(fields.inputPath);
  const existing = snapshot.articles.find((a) => a.articleId === articleId);
  if (existing) {
    existing.updatedAt = now;
    Object.assign(existing, { ...fields, articleId });
    return existing;
  }
  const record: ArticleRecord = Object.assign(
    {
      articleId,
      sourceUrl: "",
      title: "",
      accountName: "",
      publishTimeText: "",
      publishTimeIso: "",
      contentHash: "",
      relativeInputPath: "",
      discoveredAt: fields.discoveredAt ?? now,
      updatedAt: now,
    },
    fields,
    { articleId, discoveredAt: fields.discoveredAt ?? now, updatedAt: now },
  );
  snapshot.articles.push(record);
  return record;
}

export function upsertProcessingJob(
  snapshot: JobStoreSnapshot,
  articleId: string,
  source: ProcessingJob["source"],
  inputRoot: string,
  inputPath: string,
): ProcessingJob {
  const now = new Date().toISOString();
  const jobId = makeJobId(articleId);
  const existing = snapshot.jobs.find((j) => j.jobId === jobId);
  if (existing) {
    return existing;
  }
  const relativeInputPath = relative(inputRoot, inputPath).replace(/\\/g, "/");
  const job: ProcessingJob = {
    jobId,
    articleId,
    source,
    currentStage: "html_ingest",
    status: "queued",
    attemptCount: 0,
    maxAttempts: 3,
    priority: 100,
    leaseOwner: "",
    leaseExpiresAt: "",
    createdAt: now,
    updatedAt: now,
    startedAt: "",
    finishedAt: "",
    lastError: "",
    stageStates: {
      html_ingest: makeInitialStageState("html_ingest"),
      dual_track_extract: makeInitialStageState("dual_track_extract"),
      mirror_export: makeInitialStageState("mirror_export"),
      done: makeInitialStageState("done"),
    },
  };
  snapshot.jobs.push(job);
  return job;
}

function makeInitialStageState(stage: PipelineStageName): JobStageState {
  return {
    stage,
    status: "pending",
    attemptCount: 0,
    maxAttempts: 3,
    startedAt: "",
    endedAt: "",
    errorSummary: "",
    artifactPaths: [],
    notes: [],
  };
}

export function markJobStageQueued(
  snapshot: JobStoreSnapshot,
  jobId: string,
  stage: PipelineStageName,
): void {
  const job = snapshot.jobs.find((j) => j.jobId === jobId);
  if (!job) return;
  const now = new Date().toISOString();
  job.currentStage = stage;
  job.status = "queued";
  job.updatedAt = now;
  if (!job.stageStates[stage]) {
    job.stageStates[stage] = makeInitialStageState(stage);
  }
  job.stageStates[stage].status = "queued";
}

export function markJobStageRunning(
  snapshot: JobStoreSnapshot,
  jobId: string,
  stage: PipelineStageName,
): void {
  const job = snapshot.jobs.find((j) => j.jobId === jobId);
  if (!job) return;
  const now = new Date().toISOString();
  job.currentStage = stage;
  job.status = "running";
  job.updatedAt = now;
  if (!job.startedAt) job.startedAt = now;
  if (!job.stageStates[stage]) {
    job.stageStates[stage] = makeInitialStageState(stage);
  }
  const stageState = job.stageStates[stage];
  stageState.status = "running";
  stageState.attemptCount += 1;
  if (!stageState.startedAt) stageState.startedAt = now;
}

export function markJobStageSucceeded(
  snapshot: JobStoreSnapshot,
  jobId: string,
  stage: PipelineStageName,
  artifactPaths: string[],
  nextStage: PipelineStageName | null,
): void {
  const job = snapshot.jobs.find((j) => j.jobId === jobId);
  if (!job) return;
  const now = new Date().toISOString();
  if (!job.stageStates[stage]) {
    job.stageStates[stage] = makeInitialStageState(stage);
  }
  const stageState = job.stageStates[stage];
  stageState.status = "done";
  stageState.endedAt = now;
  stageState.artifactPaths = artifactPaths;
  job.updatedAt = now;

  if (nextStage === null || nextStage === "done") {
    job.currentStage = "done";
    job.status = "completed";
    job.finishedAt = now;
    if (!job.stageStates["done"]) {
      job.stageStates["done"] = makeInitialStageState("done");
    }
    job.stageStates["done"].status = "done";
    job.stageStates["done"].endedAt = now;
  } else {
    job.currentStage = nextStage;
    job.status = "queued";
    if (!job.stageStates[nextStage]) {
      job.stageStates[nextStage] = makeInitialStageState(nextStage);
    }
    job.stageStates[nextStage].status = "queued";
  }
}

export function markJobStageFailed(
  snapshot: JobStoreSnapshot,
  jobId: string,
  stage: PipelineStageName,
  errorSummary: string,
): void {
  const job = snapshot.jobs.find((j) => j.jobId === jobId);
  if (!job) return;
  const now = new Date().toISOString();
  if (!job.stageStates[stage]) {
    job.stageStates[stage] = makeInitialStageState(stage);
  }
  const stageState = job.stageStates[stage];
  stageState.status = "failed";
  stageState.endedAt = now;
  stageState.errorSummary = errorSummary;
  job.status = "failed";
  job.lastError = errorSummary;
  job.updatedAt = now;
  job.finishedAt = now;
}

export function markJobCancelled(
  snapshot: JobStoreSnapshot,
  jobId: string,
): void {
  const job = snapshot.jobs.find((j) => j.jobId === jobId);
  if (!job) return;
  const now = new Date().toISOString();
  job.status = "cancelled";
  job.updatedAt = now;
  job.finishedAt = now;
  const stageState = job.stageStates[job.currentStage];
  if (stageState && stageState.status === "running") {
    stageState.status = "cancelled";
    stageState.endedAt = now;
  }
}

export function recoverStaleJobs(
  snapshot: JobStoreSnapshot,
  staleLeaseCutoffMs = 10 * 60 * 1000,
): number {
  const now = Date.now();
  let recovered = 0;
  for (const job of snapshot.jobs) {
    if (job.status !== "running") continue;
    const staleAt = job.leaseExpiresAt
      ? new Date(job.leaseExpiresAt).getTime()
      : new Date(job.updatedAt).getTime() + staleLeaseCutoffMs;
    if (now >= staleAt) {
      job.status = "queued";
      job.leaseOwner = "";
      job.leaseExpiresAt = "";
      job.updatedAt = new Date().toISOString();
      recovered += 1;
    }
  }
  return recovered;
}

export function claimNextQueuedJob(
  snapshot: JobStoreSnapshot,
): ProcessingJob | null {
  const job = snapshot.jobs.find(
    (j) => j.status === "queued" && j.currentStage !== "done",
  );
  return job ?? null;
}

export function listJobsByStatus(
  snapshot: JobStoreSnapshot,
  status: JobLifecycleStatus,
): ProcessingJob[] {
  return snapshot.jobs.filter((j) => j.status === status);
}
