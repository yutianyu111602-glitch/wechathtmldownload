import type { BatchSnapshot } from "../types.js";

interface CollectStatusLike {
  outDir?: string;
  accountsPath?: string;
  totalAccounts?: number;
  totalDiscovered?: number;
  totalEnqueued?: number;
  completedAccounts?: number;
}

interface SampleArchiveMetaLike {
  capture_method?: string;
  warnings?: string[];
}

export interface RuntimeImportVerificationReport {
  generatedAt: string;
  discovery: {
    root: string;
    outDir: string;
    accountsPath: string;
    totalAccounts: number;
    totalDiscovered: number;
    totalEnqueued: number;
    completedAccounts: number;
  };
  taskBus: {
    inputRoot: string;
    outRoot: string;
    status: string;
    pipeline: string;
    imported: boolean;
    totalItems: number;
    queuedCount: number;
    runningCount: number;
    succeededCount: number;
    failedCount: number;
    skippedCount: number;
    completedCount: number;
    currentFile: string;
  };
  archive: {
    root: string;
    accountDirCount: number;
    sampleBundle: {
      dir: string;
      files: string[];
      captureMethod: string;
      warnings: string[];
    };
  };
}

function toStringValue(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function toNumberValue(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return 0;
}

export function buildRuntimeImportVerificationReport(options: {
  generatedAt: string;
  discoveryRoot: string;
  archiveRoot: string;
  collectStatus: CollectStatusLike;
  importedSnapshot: BatchSnapshot & { pipeline?: string; imported?: boolean };
  archiveAccountDirCount: number;
  sampleBundleDir: string;
  sampleBundleFiles: string[];
  sampleArchiveMeta: SampleArchiveMetaLike | null;
}): RuntimeImportVerificationReport {
  return {
    generatedAt: toStringValue(options.generatedAt),
    discovery: {
      root: toStringValue(options.discoveryRoot),
      outDir: toStringValue(options.collectStatus.outDir),
      accountsPath: toStringValue(options.collectStatus.accountsPath),
      totalAccounts: toNumberValue(options.collectStatus.totalAccounts),
      totalDiscovered: toNumberValue(options.collectStatus.totalDiscovered),
      totalEnqueued: toNumberValue(options.collectStatus.totalEnqueued),
      completedAccounts: toNumberValue(options.collectStatus.completedAccounts),
    },
    taskBus: {
      inputRoot: toStringValue(options.importedSnapshot.inputRoot),
      outRoot: toStringValue(options.importedSnapshot.outRoot),
      status: toStringValue(options.importedSnapshot.status),
      pipeline: toStringValue(options.importedSnapshot.pipeline),
      imported: Boolean(options.importedSnapshot.imported),
      totalItems: toNumberValue(options.importedSnapshot.totalItems),
      queuedCount: toNumberValue(options.importedSnapshot.queuedCount),
      runningCount: toNumberValue(options.importedSnapshot.runningCount),
      succeededCount: toNumberValue(options.importedSnapshot.succeededCount),
      failedCount: toNumberValue(options.importedSnapshot.failedCount),
      skippedCount: toNumberValue(options.importedSnapshot.skippedCount),
      completedCount: toNumberValue(options.importedSnapshot.completedCount),
      currentFile: toStringValue(options.importedSnapshot.currentFile),
    },
    archive: {
      root: toStringValue(options.archiveRoot),
      accountDirCount: toNumberValue(options.archiveAccountDirCount),
      sampleBundle: {
        dir: toStringValue(options.sampleBundleDir),
        files: [...options.sampleBundleFiles].sort((left, right) => left.localeCompare(right)),
        captureMethod: toStringValue(options.sampleArchiveMeta?.capture_method),
        warnings: Array.isArray(options.sampleArchiveMeta?.warnings)
          ? [...options.sampleArchiveMeta.warnings]
          : [],
      },
    },
  };
}
