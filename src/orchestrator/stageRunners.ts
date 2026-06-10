import { existsSync } from "node:fs";
import { join } from "node:path";
import { processArticleDualTrack } from "../pipeline/processArticleDualTrack.js";
import {
  markJobStageFailed,
  markJobStageRunning,
  markJobStageSucceeded,
  upsertArticleRecord,
} from "../state/jobStore.js";
import type { JobStoreSnapshot, ProcessingJob } from "../state/jobTypes.js";

export interface StageRunnerContext {
  snapshot: JobStoreSnapshot;
  outRoot: string;
  now: () => string;
  signal?: AbortSignal;
  onProgress?: (message: string) => void;
}

export async function runDualTrackExtractStage(
  job: ProcessingJob,
  context: StageRunnerContext,
): Promise<void> {
  const { snapshot, outRoot, signal, onProgress } = context;
  const article = snapshot.articles.find((a) => a.articleId === job.articleId);
  if (!article) {
    throw new Error(`Article record not found for jobId=${job.jobId}`);
  }

  markJobStageRunning(snapshot, job.jobId, "dual_track_extract");

  const relKey = article.relativeInputPath.replace(/\.html?$/i, "");
  const outDir = join(outRoot, relKey);

  try {
    if (signal?.aborted) {
      throw new Error("Aborted before dual_track_extract start");
    }

    // FIX B1: pass signal so cancellation interrupts mid-article processing
    const result = await processArticleDualTrack(
      article.inputPath,
      outDir,
      (event) => {
        onProgress?.(`[${event.step}/${event.totalSteps}] ${event.phase} ${event.message}`);
      },
      signal,
    );

    // FIX M1: backfill meta fields into ArticleRecord so GUI can display title/account
    if (result) {
      upsertArticleRecord(snapshot, {
        inputPath: article.inputPath,
        relativeInputPath: article.relativeInputPath,
        sourceUrl: result.meta.source_url ?? article.sourceUrl,
        title: result.meta.title ?? article.title,
        accountName: result.meta.account_name ?? article.accountName,
        publishTimeText: result.meta.publish_time_text ?? article.publishTimeText,
        publishTimeIso: result.meta.publish_time_iso ?? article.publishTimeIso,
        contentHash: article.contentHash,
        updatedAt: new Date().toISOString(),
      });
    }

    const artifactPaths = [
      join(outDir, "meta.json"),
      join(outDir, "assets.json"),
      join(outDir, "rule_extract.json"),
      join(outDir, "clean.md"),
      join(outDir, "markitdown.raw.md"),
      join(outDir, "markitdown.cleaned.md"),
      join(outDir, "llm_input.md"),
      join(outDir, "markitdown_warnings.json"),
    ];

    markJobStageSucceeded(snapshot, job.jobId, "dual_track_extract", artifactPaths, "mirror_export");
  } catch (error: unknown) {
    if (signal?.aborted) {
      markJobStageFailed(snapshot, job.jobId, "dual_track_extract", "Cancelled by user");
      return;
    }
    const msg = error instanceof Error ? error.message : String(error);
    markJobStageFailed(snapshot, job.jobId, "dual_track_extract", msg);
    throw error;
  }
}

export async function runMirrorExportStage(
  job: ProcessingJob,
  context: StageRunnerContext,
): Promise<void> {
  const { snapshot } = context;
  markJobStageRunning(snapshot, job.jobId, "mirror_export");
  // mirror_export is a no-op in first version — just mark done
  markJobStageSucceeded(snapshot, job.jobId, "mirror_export", [], null);
}

// FIX M3: exported for reuse in keeper resume check (avoids dynamic import in loop)
export { existsSync };
