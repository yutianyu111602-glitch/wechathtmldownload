export type PipelineEventType =
  | "enqueued"
  | "claimed"
  | "completed"
  | "failed"
  | "stale_recovered";

export interface PipelineEvent {
  eventId: string;
  eventType: PipelineEventType;
  jobId: string;
  articleId: string;
  stage: string;
  timestamp: string;
  leaseOwner?: string;
  leaseExpiresAt?: string;
  errorSummary?: string;
  artifactPaths?: string[];
  metadata?: Record<string, unknown>;
}

export interface EnqueueInput {
  articleId: string;
  inputPath: string;
  relativeInputPath: string;
  sourceUrl: string;
  accountName: string;
  title: string;
  stage: string;
  priority?: number;
  maxAttempts?: number;
}

export interface ClaimResult {
  jobId: string;
  articleId: string;
  inputPath: string;
  stage: string;
  attemptCount: number;
  leaseOwner: string;
  leaseExpiresAt: string;
}

export interface ProjectionSnapshot {
  total: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  skipped: number;
  deferred: number;
  itemCount: number;
  itemLimit: number;
  itemsTruncated: boolean;
  items: Array<{
    jobId: string;
    articleId: string;
    inputPath: string;
    status: string;
    stage: string;
    startedAt: string;
    endedAt: string;
    errorSummary: string;
    attemptCount: number;
  }>;
  updatedAt: string;
}

export interface PipelineStore {
  /**
   * Add a new job to the queue. Idempotent by articleId + stage.
   */
  enqueue(input: EnqueueInput): Promise<{ jobId: string; alreadyExists: boolean }>;

  /**
   * Claim the next queued job for processing. Records lease atomically.
   */
  claimNext(options: {
    leaseOwner: string;
    leaseDurationMs: number;
    stage?: string;
  }): Promise<ClaimResult | null>;

  /**
   * Mark a claimed job as completed. Optionally advance to next stage.
   */
  complete(options: {
    jobId: string;
    leaseOwner: string;
    artifactPaths?: string[];
    nextStage?: string | null;
  }): Promise<void>;

  /**
   * Mark a job as failed. Releases lease.
   */
  fail(options: {
    jobId: string;
    leaseOwner: string;
    errorSummary: string;
  }): Promise<void>;

  /**
   * Recover jobs with expired leases back to queued status.
   */
  recoverStale(options: { cutoffDurationMs: number }): Promise<number>;

  /**
   * Generate a bounded projection snapshot for UI/consumers.
   */
  project(options?: {
    itemLimit?: number;
    stage?: string;
    status?: string;
  }): Promise<ProjectionSnapshot>;

  /**
   * Rescue failed jobs matching error patterns back to queued status.
   */
  rescueFailed(options: {
    errorPatterns: RegExp[];
    maxAttempts?: number;
    stage?: string;
  }): Promise<{ rescued: number; skipped: number; errors: string[] }>;

  /**
   * Query event log for audit and replay.
   */
  getEvents(options?: {
    jobId?: string;
    stage?: string;
    eventType?: PipelineEventType;
    limit?: number;
  }): Promise<PipelineEvent[]>;

  /**
   * Rebuild projection snapshot from event log (event sourcing audit).
   */
  rebuildProjection(options?: {
    itemLimit?: number;
    stage?: string;
    status?: string;
  }): Promise<ProjectionSnapshot>;

  /**
   * Close the store and release resources.
   */
  close(): Promise<void>;
}

export interface PipelineStoreFactory {
  createStore(options: { dbPath: string; runId?: string }): Promise<PipelineStore>;
}
