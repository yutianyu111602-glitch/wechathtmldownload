import { readFile, stat } from "node:fs/promises";
import { join, resolve } from "node:path";

export interface StageRunState {
  statusPath: string;
  exists: boolean;
  running: boolean;
  status: string;
  runningCount: number;
  queuedCount: number;
  updatedAt: string;
}

interface StatusJson {
  status?: string;
  running?: number;
  queued?: number;
  runningCount?: number;
  queuedCount?: number;
}

function numberField(value: unknown): number {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

async function readStatusFile(statusPath: string): Promise<StageRunState> {
  const [statusText, statusStat] = await Promise.all([
    readFile(statusPath, "utf-8"),
    stat(statusPath),
  ]);
  const statusJson = JSON.parse(statusText) as StatusJson;
  const status = String(statusJson.status || "");
  const runningCount = numberField(statusJson.runningCount ?? statusJson.running);
  const queuedCount = numberField(statusJson.queuedCount ?? statusJson.queued);
  const running =
    status === "running" ||
    runningCount > 0 ||
    queuedCount > 0 ||
    (status.length > 0 && status !== "completed");

  return {
    statusPath,
    exists: true,
    running,
    status,
    runningCount,
    queuedCount,
    updatedAt: statusStat.mtime.toISOString(),
  };
}

function missingState(statusPath: string): StageRunState {
  return {
    statusPath,
    exists: false,
    running: false,
    status: "",
    runningCount: 0,
    queuedCount: 0,
    updatedAt: "",
  };
}

async function readFirstExistingStatus(
  statusPaths: string[],
): Promise<StageRunState> {
  let firstMissing: StageRunState | null = null;
  let firstExisting: StageRunState | null = null;

  for (const statusPath of statusPaths) {
    try {
      const state = await readStatusFile(statusPath);
      if (state.running) {
        return state;
      }
      firstExisting ??= state;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
      firstMissing ??= missingState(statusPath);
    }
  }

  return firstExisting || firstMissing || missingState(statusPaths[0] || "");
}

export async function readArchiveAssetRunState(
  archiveRoot: string,
  statusPath?: string,
): Promise<StageRunState> {
  const resolvedRoot = resolve(archiveRoot);
  const resolvedStatusPath = resolve(
    statusPath || join(resolvedRoot, "asset-retention-status.json"),
  );
  return readFirstExistingStatus([resolvedStatusPath]);
}

export async function assertNoRunningArchiveAssets(
  archiveRoot: string,
  operation: string,
  statusPath?: string,
): Promise<void> {
  const state = await readArchiveAssetRunState(archiveRoot, statusPath);
  if (!state.running) {
    return;
  }
  throw new Error(
    [
      `Refusing to run ${operation} while archive asset retention is not completed.`,
      `statusPath=${state.statusPath}`,
      `status=${state.status}`,
      `runningCount=${state.runningCount}`,
      `queuedCount=${state.queuedCount}`,
      "Wait for asset-retention-status.json to show completed/zero queued and running, then verify the results log is stable.",
    ].join(" "),
  );
}

export async function readLlmExportRunState(
  artifactRoot: string,
  statusPath?: string,
): Promise<StageRunState> {
  const resolvedRoot = resolve(artifactRoot);
  const candidatePaths = [
    statusPath ? resolve(statusPath) : "",
    join(resolvedRoot, "export-llm-status.json"),
    join(resolvedRoot, "batch-status.json"),
  ].filter((candidate, index, all) => candidate && all.indexOf(candidate) === index);

  return readFirstExistingStatus(candidatePaths);
}

export async function assertNoRunningLlmExport(
  artifactRoot: string,
  operation: string,
  statusPath?: string,
): Promise<void> {
  const state = await readLlmExportRunState(artifactRoot, statusPath);
  if (!state.running) {
    return;
  }
  throw new Error(
    [
      `Refusing to run ${operation} while LLM export is running.`,
      `statusPath=${state.statusPath}`,
      `status=${state.status}`,
      `runningCount=${state.runningCount}`,
      `queuedCount=${state.queuedCount}`,
      "Wait for export completion before starting downstream, OCR, final pack, graph, registry, or another export.",
    ].join(" "),
  );
}
