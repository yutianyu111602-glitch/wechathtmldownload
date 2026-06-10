import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import type {
  ClaimResult,
  EnqueueInput,
  PipelineStore,
  ProjectionSnapshot,
} from "./pipelineStore.js";

interface SqliteStoreOptions {
  dbPath: string;
  runId?: string;
}

function nowIso(): string {
  return new Date().toISOString();
}

function initSchema(db: Database.Database): void {
  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");

  db.exec(`
    CREATE TABLE IF NOT EXISTS articles (
      article_id TEXT PRIMARY KEY,
      input_path TEXT NOT NULL,
      source_url TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      account_name TEXT NOT NULL DEFAULT '',
      discovered_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS jobs (
      job_id TEXT PRIMARY KEY,
      article_id TEXT NOT NULL,
      input_path TEXT NOT NULL,
      relative_input_path TEXT NOT NULL DEFAULT '',
      source_url TEXT NOT NULL DEFAULT '',
      account_name TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      stage TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued',
      attempt_count INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3,
      priority INTEGER NOT NULL DEFAULT 100,
      lease_owner TEXT NOT NULL DEFAULT '',
      lease_expires_at TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      started_at TEXT NOT NULL DEFAULT '',
      finished_at TEXT NOT NULL DEFAULT '',
      error_summary TEXT NOT NULL DEFAULT '',
      artifact_paths TEXT NOT NULL DEFAULT '[]',
      UNIQUE(article_id, stage)
    );

    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS idx_jobs_stage ON jobs(stage);
    CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(lease_owner, lease_expires_at);

    CREATE TABLE IF NOT EXISTS job_events (
      event_id TEXT PRIMARY KEY,
      event_type TEXT NOT NULL,
      job_id TEXT NOT NULL,
      article_id TEXT NOT NULL,
      stage TEXT NOT NULL,
      timestamp TEXT NOT NULL,
      lease_owner TEXT,
      lease_expires_at TEXT,
      error_summary TEXT,
      artifact_paths TEXT,
      metadata TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id);
    CREATE INDEX IF NOT EXISTS idx_events_time ON job_events(timestamp);
  `);
}

export async function createSqlitePipelineStore(
  options: SqliteStoreOptions,
): Promise<PipelineStore> {
  const dbPath = options.dbPath;
  mkdirSync(dirname(dbPath), { recursive: true });

  const db = new Database(dbPath);
  initSchema(db);

  const insertEvent = db.prepare(`
    INSERT INTO job_events (event_id, event_type, job_id, article_id, stage, timestamp, lease_owner, lease_expires_at, error_summary, artifact_paths, metadata)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  function emitEvent(
    eventType: string,
    jobId: string,
    articleId: string,
    stage: string,
    extras?: {
      leaseOwner?: string;
      leaseExpiresAt?: string;
      errorSummary?: string;
      artifactPaths?: string[];
      metadata?: Record<string, unknown>;
    },
  ): void {
    insertEvent.run(
      `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      eventType,
      jobId,
      articleId,
      stage,
      nowIso(),
      extras?.leaseOwner ?? null,
      extras?.leaseExpiresAt ?? null,
      extras?.errorSummary ?? null,
      extras?.artifactPaths ? JSON.stringify(extras.artifactPaths) : null,
      extras?.metadata ? JSON.stringify(extras.metadata) : null,
    );
  }

  return {
    async enqueue(input: EnqueueInput) {
      const jobId = `job_${input.articleId}_${input.stage}`;
      const now = nowIso();

      const insertArticle = db.prepare(`
        INSERT OR IGNORE INTO articles (article_id, input_path, source_url, title, account_name, discovered_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `);
      insertArticle.run(input.articleId, input.inputPath, input.sourceUrl, input.title, input.accountName, now, now);

      const insertJob = db.prepare(`
        INSERT OR IGNORE INTO jobs (job_id, article_id, input_path, relative_input_path, source_url, account_name, title, stage, status, max_attempts, priority, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
      `);
      const result = insertJob.run(
        jobId,
        input.articleId,
        input.inputPath,
        input.relativeInputPath,
        input.sourceUrl,
        input.accountName,
        input.title,
        input.stage,
        input.maxAttempts ?? 3,
        input.priority ?? 100,
        now,
        now,
      );

      const alreadyExists = result.changes === 0;
      if (!alreadyExists) {
        emitEvent("enqueued", jobId, input.articleId, input.stage);
      }

      return { jobId, alreadyExists };
    },

    async claimNext(options) {
      const now = Date.now();
      const leaseExpiresAt = new Date(now + options.leaseDurationMs).toISOString();

      const query = options.stage
        ? db.prepare(`
            SELECT job_id, article_id, input_path, stage, attempt_count
            FROM jobs
            WHERE status = 'queued' AND stage = ?
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
          `)
        : db.prepare(`
            SELECT job_id, article_id, input_path, stage, attempt_count
            FROM jobs
            WHERE status = 'queued'
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
          `);

      const row = (options.stage
        ? query.get(options.stage)
        : query.get()) as { job_id: string; article_id: string; input_path: string; stage: string; attempt_count: number } | undefined;

      if (!row) {
        return null;
      }

      const update = db.prepare(`
        UPDATE jobs
        SET status = 'running', lease_owner = ?, lease_expires_at = ?, attempt_count = attempt_count + 1, started_at = ?, updated_at = ?
        WHERE job_id = ? AND status = 'queued'
      `);
      const updated = update.run(options.leaseOwner, leaseExpiresAt, leaseExpiresAt, nowIso(), row.job_id);

      if (updated.changes === 0) {
        return null; // Race condition: another worker claimed it
      }

      emitEvent("claimed", row.job_id, row.article_id, row.stage, {
        leaseOwner: options.leaseOwner,
        leaseExpiresAt,
      });

      return {
        jobId: row.job_id,
        articleId: row.article_id,
        inputPath: row.input_path,
        stage: row.stage,
        attemptCount: row.attempt_count + 1,
        leaseOwner: options.leaseOwner,
        leaseExpiresAt,
      };
    },

    async complete(options) {
      const now = nowIso();
      const newStatus = options.nextStage === null ? 'succeeded' : 'queued';
      const currentRow = db.prepare(`SELECT stage FROM jobs WHERE job_id = ?`).get(options.jobId) as { stage: string } | undefined;
      const newStage = options.nextStage ?? currentRow?.stage ?? '';

      const update = db.prepare(`
        UPDATE jobs
        SET status = ?, stage = ?, finished_at = ?, artifact_paths = ?, updated_at = ?
        WHERE job_id = ? AND lease_owner = ?
      `);
      const result = update.run(
        newStatus,
        newStage,
        now,
        options.artifactPaths ? JSON.stringify(options.artifactPaths) : '[]',
        now,
        options.jobId,
        options.leaseOwner,
      );

      if (result.changes === 0) {
        throw new Error(`Complete failed: job not found or lease mismatch for ${options.jobId}`);
      }

      const job = db.prepare(`SELECT article_id, stage FROM jobs WHERE job_id = ?`).get(options.jobId) as { article_id: string; stage: string };
      emitEvent("completed", options.jobId, job.article_id, job.stage, {
        leaseOwner: options.leaseOwner,
        artifactPaths: options.artifactPaths,
      });
    },

    async fail(options) {
      const now = nowIso();

      const update = db.prepare(`
        UPDATE jobs
        SET status = 'failed', error_summary = ?, lease_owner = '', lease_expires_at = '', finished_at = ?, updated_at = ?
        WHERE job_id = ? AND lease_owner = ?
      `);
      const result = update.run(options.errorSummary, now, now, options.jobId, options.leaseOwner);

      if (result.changes === 0) {
        throw new Error(`Fail failed: job not found or lease mismatch for ${options.jobId}`);
      }

      const job = db.prepare(`SELECT article_id, stage FROM jobs WHERE job_id = ?`).get(options.jobId) as { article_id: string; stage: string };
      emitEvent("failed", options.jobId, job.article_id, job.stage, {
        leaseOwner: options.leaseOwner,
        errorSummary: options.errorSummary,
      });
    },

    async recoverStale(options) {
      const now = nowIso();
      const cutoff = new Date(Date.now() - options.cutoffDurationMs).toISOString();

      const findStale = db.prepare(`
        SELECT job_id, article_id, stage FROM jobs
        WHERE status = 'running' AND lease_expires_at < ?
      `);
      const stale = findStale.all(cutoff) as Array<{ job_id: string; article_id: string; stage: string }>;

      const update = db.prepare(`
        UPDATE jobs
        SET status = 'queued', lease_owner = '', lease_expires_at = '', updated_at = ?
        WHERE job_id = ?
      `);

      for (const row of stale) {
        update.run(now, row.job_id);
        emitEvent("stale_recovered", row.job_id, row.article_id, row.stage);
      }

      return stale.length;
    },

    async project(options) {
      const limit = options?.itemLimit ?? 1000;
      const stageFilter = options?.stage;
      const statusFilter = options?.status;

      let whereClause = "WHERE 1=1";
      const params: (string | number)[] = [];

      if (stageFilter) {
        whereClause += " AND stage = ?";
        params.push(stageFilter);
      }
      if (statusFilter) {
        whereClause += " AND status = ?";
        params.push(statusFilter);
      }

      const countQuery = db.prepare(`SELECT COUNT(*) as count FROM jobs ${whereClause}`);
      const total = (countQuery.get(...params) as { count: number }).count;

      const statusCounts = db.prepare(`
        SELECT status, COUNT(*) as count FROM jobs ${whereClause} GROUP BY status
      `).all(...params) as Array<{ status: string; count: number }>;

      const counts: Record<string, number> = {
        queued: 0, running: 0, succeeded: 0, failed: 0, skipped: 0, deferred: 0,
      };
      for (const sc of statusCounts) {
        counts[sc.status] = sc.count;
      }

      const itemQuery = db.prepare(`
        SELECT job_id, article_id, input_path, status, stage, started_at, finished_at, error_summary, attempt_count
        FROM jobs ${whereClause}
        ORDER BY priority DESC, created_at ASC
        LIMIT ?
      `);
      const items = itemQuery.all(...params, limit) as Array<{
        job_id: string;
        article_id: string;
        input_path: string;
        status: string;
        stage: string;
        started_at: string;
        finished_at: string;
        error_summary: string;
        attempt_count: number;
      }>;

      return {
        total,
        queued: counts.queued,
        running: counts.running,
        succeeded: counts.succeeded,
        failed: counts.failed,
        skipped: counts.skipped,
        deferred: counts.deferred,
        itemCount: total,
        itemLimit: limit,
        itemsTruncated: total > items.length,
        items: items.map((row) => ({
          jobId: row.job_id,
          articleId: row.article_id,
          inputPath: row.input_path,
          status: row.status,
          stage: row.stage,
          startedAt: row.started_at,
          endedAt: row.finished_at,
          errorSummary: row.error_summary,
          attemptCount: row.attempt_count,
        })),
        updatedAt: nowIso(),
      };
    },

    async rescueFailed(options) {
      const maxAttempts = options.maxAttempts ?? 3;
      const stageFilter = options.stage;

      const whereClause = stageFilter ? "WHERE status = 'failed' AND stage = ?" : "WHERE status = 'failed'";
      const params: (string | number)[] = stageFilter ? [stageFilter] : [];

      const query = db.prepare(`SELECT job_id, article_id, stage, error_summary, attempt_count FROM jobs ${whereClause}`);
      const rows = query.all(...params) as Array<{ job_id: string; article_id: string; stage: string; error_summary: string; attempt_count: number }>;

      let rescued = 0;
      let skipped = 0;
      const errors: string[] = [];

      const update = db.prepare(`
        UPDATE jobs
        SET status = 'queued', updated_at = ?
        WHERE job_id = ? AND status = 'failed'
      `);

      for (const row of rows) {
        const matchesPattern = options.errorPatterns.some((pattern) => pattern.test(row.error_summary));
        if (!matchesPattern) {
          skipped += 1;
          continue;
        }
        if (row.attempt_count >= maxAttempts) {
          skipped += 1;
          errors.push(`Job ${row.job_id} exceeded max attempts (${maxAttempts})`);
          continue;
        }

        const result = update.run(nowIso(), row.job_id);
        if (result.changes > 0) {
          rescued += 1;
          emitEvent("rescued", row.job_id, row.article_id, row.stage, {
            errorSummary: row.error_summary,
            metadata: { maxAttempts, attemptCount: row.attempt_count },
          });
        }
      }

      return { rescued, skipped, errors };
    },

    async getEvents(options = {}) {
      const limit = options.limit ?? 1000;
      const conditions: string[] = [];
      const params: (string | number)[] = [];

      if (options.jobId) {
        conditions.push("job_id = ?");
        params.push(options.jobId);
      }
      if (options.stage) {
        conditions.push("stage = ?");
        params.push(options.stage);
      }
      if (options.eventType) {
        conditions.push("event_type = ?");
        params.push(options.eventType);
      }

      const whereClause = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
      const query = db.prepare(`
        SELECT event_id, event_type, job_id, article_id, stage, timestamp, lease_owner, lease_expires_at, error_summary, artifact_paths, metadata
        FROM job_events
        ${whereClause}
        ORDER BY timestamp ASC
        LIMIT ?
      `);

      const rows = query.all(...params, limit) as Array<{
        event_id: string;
        event_type: string;
        job_id: string;
        article_id: string;
        stage: string;
        timestamp: string;
        lease_owner: string | null;
        lease_expires_at: string | null;
        error_summary: string | null;
        artifact_paths: string | null;
        metadata: string | null;
      }>;

      return rows.map((row) => ({
        eventId: row.event_id,
        eventType: row.event_type as import("./pipelineStore.js").PipelineEventType,
        jobId: row.job_id,
        articleId: row.article_id,
        stage: row.stage,
        timestamp: row.timestamp,
        leaseOwner: row.lease_owner ?? undefined,
        leaseExpiresAt: row.lease_expires_at ?? undefined,
        errorSummary: row.error_summary ?? undefined,
        artifactPaths: row.artifact_paths ? JSON.parse(row.artifact_paths) : undefined,
        metadata: row.metadata ? JSON.parse(row.metadata) : undefined,
      }));
    },

    async rebuildProjection(options = {}) {
      const limit = options.itemLimit ?? 1000;
      const stageFilter = options.stage;
      const statusFilter = options.status;

      // Rebuild state from events
      const events = db.prepare(`
        SELECT event_id, event_type, job_id, article_id, stage, timestamp, error_summary, artifact_paths
        FROM job_events
        ORDER BY timestamp ASC
      `).all() as Array<{
        event_id: string;
        event_type: string;
        job_id: string;
        article_id: string;
        stage: string;
        timestamp: string;
        error_summary: string | null;
        artifact_paths: string | null;
      }>;

      const jobState = new Map<string, {
        jobId: string;
        articleId: string;
        stage: string;
        status: string;
        startedAt: string;
        endedAt: string;
        errorSummary: string;
        attemptCount: number;
      }>();

      for (const evt of events) {
        const existing = jobState.get(evt.job_id);
        switch (evt.event_type) {
          case "enqueued":
            if (!existing) {
              jobState.set(evt.job_id, {
                jobId: evt.job_id,
                articleId: evt.article_id,
                stage: evt.stage,
                status: "queued",
                startedAt: "",
                endedAt: "",
                errorSummary: "",
                attemptCount: 0,
              });
            }
            break;
          case "claimed": {
            const job = existing ?? {
              jobId: evt.job_id,
              articleId: evt.article_id,
              stage: evt.stage,
              status: "queued",
              startedAt: "",
              endedAt: "",
              errorSummary: "",
              attemptCount: 0,
            };
            job.status = "running";
            job.startedAt = evt.timestamp;
            job.attemptCount += 1;
            jobState.set(evt.job_id, job);
            break;
          }
          case "completed": {
            const job = existing ?? {
              jobId: evt.job_id,
              articleId: evt.article_id,
              stage: evt.stage,
              status: "queued",
              startedAt: "",
              endedAt: "",
              errorSummary: "",
              attemptCount: 0,
            };
            job.status = "succeeded";
            job.endedAt = evt.timestamp;
            jobState.set(evt.job_id, job);
            break;
          }
          case "failed": {
            const job = existing ?? {
              jobId: evt.job_id,
              articleId: evt.article_id,
              stage: evt.stage,
              status: "queued",
              startedAt: "",
              endedAt: "",
              errorSummary: "",
              attemptCount: 0,
            };
            job.status = "failed";
            job.endedAt = evt.timestamp;
            job.errorSummary = evt.error_summary ?? "";
            jobState.set(evt.job_id, job);
            break;
          }
          case "stale_recovered": {
            const job = existing ?? {
              jobId: evt.job_id,
              articleId: evt.article_id,
              stage: evt.stage,
              status: "queued",
              startedAt: "",
              endedAt: "",
              errorSummary: "",
              attemptCount: 0,
            };
            job.status = "queued";
            jobState.set(evt.job_id, job);
            break;
          }
        }
      }

      let items = Array.from(jobState.values());

      if (stageFilter) {
        items = items.filter((item) => item.stage === stageFilter);
      }
      if (statusFilter) {
        items = items.filter((item) => item.status === statusFilter);
      }

      const total = items.length;
      const counts: Record<string, number> = { queued: 0, running: 0, succeeded: 0, failed: 0, skipped: 0, deferred: 0 };
      for (const item of items) {
        counts[item.status] = (counts[item.status] ?? 0) + 1;
      }

      items = items.slice(0, limit);

      return {
        total,
        queued: counts.queued,
        running: counts.running,
        succeeded: counts.succeeded,
        failed: counts.failed,
        skipped: counts.skipped,
        deferred: counts.deferred,
        itemCount: total,
        itemLimit: limit,
        itemsTruncated: total > items.length,
        items: items.map((item) => ({
          jobId: item.jobId,
          articleId: item.articleId,
          inputPath: "",
          status: item.status,
          stage: item.stage,
          startedAt: item.startedAt,
          endedAt: item.endedAt,
          errorSummary: item.errorSummary,
          attemptCount: item.attemptCount,
        })),
        updatedAt: nowIso(),
      };
    },

    async close() {
      db.close();
    },
  };
}
