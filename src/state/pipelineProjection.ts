import type { ProjectionSnapshot } from "./pipelineStore.js";

export interface CompactProjectionItem {
  jobId: string;
  articleId: string;
  inputPath: string;
  status: string;
  stage: string;
  startedAt: string;
  endedAt: string;
  errorSummary: string;
  attemptCount: number;
}

export interface CompactProjectionOptions {
  items: CompactProjectionItem[];
  total: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  skipped: number;
  deferred: number;
  maxRunningItems?: number;
  maxFailedItems?: number;
  maxSucceededItems?: number;
  maxBytes?: number;
}

export interface CompactProjectionResult {
  snapshot: ProjectionSnapshot;
  retainedRunning: number;
  retainedFailed: number;
  retainedSucceeded: number;
  droppedSucceeded: number;
  estimatedBytes: number;
}

function estimateJsonBytes(value: unknown): number {
  return Buffer.byteLength(JSON.stringify(value), "utf8");
}

export function buildCompactProjection(
  options: CompactProjectionOptions,
): CompactProjectionResult {
  const {
    items,
    total,
    queued,
    running,
    succeeded,
    failed,
    skipped,
    deferred,
    maxRunningItems = Infinity,
    maxFailedItems = 50,
    maxSucceededItems = 20,
    maxBytes = 5 * 1024 * 1024,
  } = options;

  // Sort by endedAt desc (newest first), with empty endedAt at the end
  const sorted = [...items].sort((a, b) => {
    if (!a.endedAt && !b.endedAt) return 0;
    if (!a.endedAt) return 1;
    if (!b.endedAt) return -1;
    return b.endedAt.localeCompare(a.endedAt);
  });

  const runningItems = sorted.filter((i) => i.status === "running").slice(0, maxRunningItems);
  const failedItems = sorted
    .filter((i) => i.status === "failed")
    .slice(0, maxFailedItems);
  const succeededItems = sorted
    .filter((i) => i.status === "succeeded")
    .slice(0, maxSucceededItems);

  let retained = [...runningItems, ...failedItems, ...succeededItems];

  // If over byte budget, drop succeeded first, then failed (keep running)
  let estimatedBytes = estimateJsonBytes({
    total,
    queued,
    running,
    succeeded,
    failed,
    skipped,
    deferred,
    itemCount: retained.length,
    items: retained,
  });

  while (estimatedBytes > maxBytes && retained.length > runningItems.length) {
    // Try dropping from the end (oldest among non-running)
    let lastNonRunningIndex = -1;
    for (let idx = retained.length - 1; idx >= 0; idx--) {
      if (retained[idx].status !== "running") {
        lastNonRunningIndex = idx;
        break;
      }
    }
    if (lastNonRunningIndex >= 0) {
      retained.splice(lastNonRunningIndex, 1);
    } else {
      break;
    }
    estimatedBytes = estimateJsonBytes({
      total,
      queued,
      running,
      succeeded,
      failed,
      skipped,
      deferred,
      itemCount: retained.length,
      items: retained,
    });
  }

  const retainedRunning = retained.filter((i) => i.status === "running").length;
  const retainedFailed = retained.filter((i) => i.status === "failed").length;
  const retainedSucceeded = retained.filter((i) => i.status === "succeeded").length;

  const snapshot: ProjectionSnapshot = {
    total,
    queued,
    running,
    succeeded,
    failed,
    skipped,
    deferred,
    itemCount: total,
    itemLimit: retained.length,
    itemsTruncated: total > retained.length,
    items: retained,
    updatedAt: new Date().toISOString(),
  };

  return {
    snapshot,
    retainedRunning,
    retainedFailed,
    retainedSucceeded,
    droppedSucceeded: succeeded - retainedSucceeded,
    estimatedBytes,
  };
}
