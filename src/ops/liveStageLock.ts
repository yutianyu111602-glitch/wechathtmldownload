import { hostname } from "node:os";
import { join, resolve } from "node:path";
import { readFile, rm } from "node:fs/promises";

import { writeJson } from "../utils/fs.js";

export interface LiveStageLockRecord {
  schemaVersion: 1;
  stageName: string;
  rootPath: string;
  owner: string;
  command: string;
  startedAt: string;
  heartbeatAt: string;
  staleAfterMs: number;
}

export interface LiveStageLockOptions {
  rootPath: string;
  stageName: string;
  owner?: string;
  command?: string;
  staleAfterMs?: number;
  now?: () => Date;
  lockPath?: string;
}

export interface LiveStageLockHandle {
  lockPath: string;
  record: LiveStageLockRecord;
}

const DEFAULT_STALE_AFTER_MS = 7 * 24 * 60 * 60 * 1000;
const LOCK_FILE_NAME = ".wechat-live-stage-lock.json";

function nowIso(now?: () => Date): string {
  return (now ? now() : new Date()).toISOString();
}

function defaultOwner(): string {
  return `${hostname()}:${process.pid}`;
}

export function isProductionRootPath(rootPath: string): boolean {
  const resolved = resolve(rootPath);
  return /^[A-Za-z]:\\DDownload(?:\\|$)/i.test(resolved);
}

export function deriveLiveStageLockPath(rootPath: string): string {
  const resolved = resolve(rootPath);
  const match = /^([A-Za-z]:\\DDownload)(?:\\|$)/i.exec(resolved);
  if (match?.[1]) {
    return join(match[1], LOCK_FILE_NAME);
  }
  return join(resolved, LOCK_FILE_NAME);
}

export async function readLiveStageLock(
  lockPath: string,
): Promise<LiveStageLockRecord | null> {
  try {
    return JSON.parse(await readFile(resolve(lockPath), "utf-8")) as LiveStageLockRecord;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return null;
    }
    throw error;
  }
}

export function isLiveStageLockStale(
  record: LiveStageLockRecord,
  now: Date = new Date(),
): boolean {
  const heartbeatMs = Date.parse(record.heartbeatAt || record.startedAt);
  if (!Number.isFinite(heartbeatMs)) {
    return false;
  }
  return now.getTime() - heartbeatMs > record.staleAfterMs;
}

export async function assertCanAcquireLiveStageLock(
  options: LiveStageLockOptions,
): Promise<void> {
  const lockPath = resolve(options.lockPath || deriveLiveStageLockPath(options.rootPath));
  const existing = await readLiveStageLock(lockPath);
  if (!existing || isLiveStageLockStale(existing, options.now?.() || new Date())) {
    return;
  }
  throw new Error(
    [
      `Refusing to start ${options.stageName} while live stage lock is active.`,
      `lockPath=${lockPath}`,
      `activeStage=${existing.stageName}`,
      `owner=${existing.owner}`,
      `heartbeatAt=${existing.heartbeatAt}`,
      "Wait for the active stage to finish, or investigate the lock if it is stale.",
    ].join(" "),
  );
}

export async function acquireLiveStageLock(
  options: LiveStageLockOptions,
): Promise<LiveStageLockHandle> {
  await assertCanAcquireLiveStageLock(options);
  const lockPath = resolve(options.lockPath || deriveLiveStageLockPath(options.rootPath));
  const timestamp = nowIso(options.now);
  const record: LiveStageLockRecord = {
    schemaVersion: 1,
    stageName: options.stageName,
    rootPath: resolve(options.rootPath),
    owner: options.owner || defaultOwner(),
    command: options.command || "",
    startedAt: timestamp,
    heartbeatAt: timestamp,
    staleAfterMs: options.staleAfterMs ?? DEFAULT_STALE_AFTER_MS,
  };
  await writeJson(lockPath, record);
  return { lockPath, record };
}

export async function releaseLiveStageLock(handle: LiveStageLockHandle): Promise<void> {
  await rm(handle.lockPath, { force: true });
}

export async function withLiveStageLock<T>(
  options: LiveStageLockOptions,
  run: () => Promise<T>,
): Promise<T> {
  const handle = await acquireLiveStageLock(options);
  try {
    return await run();
  } finally {
    await releaseLiveStageLock(handle);
  }
}

export async function withLiveStageLockIfProduction<T>(
  options: LiveStageLockOptions,
  run: () => Promise<T>,
): Promise<T> {
  if (!isProductionRootPath(options.rootPath)) {
    return run();
  }
  return withLiveStageLock(options, run);
}
