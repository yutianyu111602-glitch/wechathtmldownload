export type PipelineStageName =
  | "html_ingest"
  | "dual_track_extract"
  | "mirror_export"
  | "entity_extract"
  | "relationship_extract"
  | "graph_build"
  | "done";

export type JobLifecycleStatus =
  | "queued"
  | "running"
  | "waiting_batch"
  | "blocked"
  | "completed"
  | "failed"
  | "cancelled";

export type StageRunStatus =
  | "pending"
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "skipped"
  | "cancelled";

export interface ArticleRecord {
  articleId: string;
  inputPath: string;
  relativeInputPath: string;
  sourceUrl: string;
  title: string;
  accountName: string;
  publishTimeText: string;
  publishTimeIso: string;
  contentHash: string;
  discoveredAt: string;
  updatedAt: string;
}

export interface JobStageState {
  stage: PipelineStageName;
  status: StageRunStatus;
  attemptCount: number;
  maxAttempts: number;
  startedAt: string;
  endedAt: string;
  errorSummary: string;
  artifactPaths: string[];
  notes: string[];
}

export interface ProcessingJob {
  jobId: string;
  articleId: string;
  source: "cli_single" | "batch_scan" | "gui_batch" | "imported_manifest" | "sidecar_merge";
  currentStage: PipelineStageName;
  status: JobLifecycleStatus;
  attemptCount: number;
  maxAttempts: number;
  priority: number;
  leaseOwner: string;
  leaseExpiresAt: string;
  createdAt: string;
  updatedAt: string;
  startedAt: string;
  finishedAt: string;
  lastError: string;
  stageStates: Record<string, JobStageState>;
}

export interface JobStoreSnapshot {
  version: 1;
  createdAt: string;
  updatedAt: string;
  jobs: ProcessingJob[];
  articles: ArticleRecord[];
}

export interface BatchProjection {
  pipeline: "dual-track" | "llm-export" | "markitdown-mirror" | "keeper";
  status: "idle" | "running" | "completed" | "cancelled" | "failed";
  inputRoot: string;
  outRoot: string;
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
  currentPhase: string;
  startedAt: string;
  itemCount?: number;
  itemLimit?: number;
  itemsTruncated?: boolean;
  items: Array<{
    inputPath: string;
    relativeInputPath: string;
    outDir: string;
    status: string;
    phase: string;
    message: string;
    errorMessage: string;
    startedAt: string;
    endedAt: string;
  }>;
}
