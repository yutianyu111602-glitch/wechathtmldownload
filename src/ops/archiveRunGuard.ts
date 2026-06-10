import { readFile, stat } from "node:fs/promises";
import { join, resolve } from "node:path";

export interface MptextArchiveRunState {
  statusPath: string;
  exists: boolean;
  running: boolean;
  status: string;
  runningCount: number;
  queuedCount: number;
  updatedAt: string;
}

interface MptextStatusJson {
  status?: string;
  runningCount?: number;
  queuedCount?: number;
}

export async function readMptextArchiveRunState(
  archiveRoot: string,
): Promise<MptextArchiveRunState> {
  const statusPath = join(resolve(archiveRoot), "mptext-archive-status.json");
  try {
    const [statusText, statusStat] = await Promise.all([
      readFile(statusPath, "utf-8"),
      stat(statusPath),
    ]);
    const statusJson = JSON.parse(statusText) as MptextStatusJson;
    const status = String(statusJson.status || "");
    const runningCount = Number(statusJson.runningCount || 0);
    const queuedCount = Number(statusJson.queuedCount || 0);
    return {
      statusPath,
      exists: true,
      running: status === "running" || runningCount > 0,
      status,
      runningCount,
      queuedCount,
      updatedAt: statusStat.mtime.toISOString(),
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
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
    throw error;
  }
}

export async function assertNoRunningMptextArchive(
  archiveRoot: string,
  operation: string,
): Promise<void> {
  const state = await readMptextArchiveRunState(archiveRoot);
  if (!state.running) {
    return;
  }
  throw new Error(
    [
      `Refusing to run ${operation} while mptext archive download is running.`,
      `statusPath=${state.statusPath}`,
      `status=${state.status}`,
      `runningCount=${state.runningCount}`,
      `queuedCount=${state.queuedCount}`,
      "Wait for completed status or run the operation on a copied checkpoint root.",
    ].join(" "),
  );
}
