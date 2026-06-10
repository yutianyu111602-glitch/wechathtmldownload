import { mkdir, rename, rm, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

type WriteFileImpl = (filePath: string, value: string | Buffer) => Promise<void>;
type RenameImpl = (oldPath: string, newPath: string) => Promise<void>;
type RemoveImpl = (filePath: string, options: { force: boolean }) => Promise<void>;

export interface AtomicWriteOptions {
  writeFileImpl?: WriteFileImpl;
  renameImpl?: RenameImpl;
  removeImpl?: RemoveImpl;
  renameRetryDelaysMs?: readonly number[];
}

function buildRenameRetryDelaysMs(): number[] {
  const delays: number[] = [];
  let delayMs = 50;
  let totalDelayMs = 0;
  while (totalDelayMs < 120_000) {
    delays.push(delayMs);
    totalDelayMs += delayMs;
    delayMs = Math.min(delayMs * 2, 2_000);
  }
  return delays;
}

const DEFAULT_RENAME_RETRY_DELAYS_MS = buildRenameRetryDelaysMs();

export async function ensureDir(dirPath: string): Promise<void> {
  await mkdir(dirPath, { recursive: true });
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryableRenameError(error: unknown): boolean {
  const code = (error as NodeJS.ErrnoException | undefined)?.code;
  return code === "EPERM" || code === "EBUSY" || code === "EACCES";
}

async function renameWithRetry(
  tmpPath: string,
  filePath: string,
  options: AtomicWriteOptions = {},
): Promise<void> {
  const renameImpl = options.renameImpl || rename;
  const retryDelaysMs = options.renameRetryDelaysMs ?? DEFAULT_RENAME_RETRY_DELAYS_MS;
  for (let attempt = 0; ; attempt += 1) {
    try {
      await renameImpl(tmpPath, filePath);
      return;
    } catch (error) {
      if (!isRetryableRenameError(error) || attempt >= retryDelaysMs.length) {
        throw error;
      }
      await sleep(Math.max(0, retryDelaysMs[attempt] ?? 0));
    }
  }
}

async function writeFileAtomic(
  filePath: string,
  value: string | Buffer,
  options: AtomicWriteOptions = {},
): Promise<void> {
  await ensureDir(dirname(filePath));
  const writeFileImpl = options.writeFileImpl || writeFile;
  const removeImpl = options.removeImpl || rm;
  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.${Math.random()
    .toString(16)
    .slice(2)}.tmp`;
  try {
    await writeFileImpl(tmpPath, value);
    await renameWithRetry(tmpPath, filePath, options);
  } catch (error) {
    await removeImpl(tmpPath, { force: true }).catch(() => undefined);
    throw error;
  }
}

export async function writeJson(
  filePath: string,
  value: unknown,
  options: AtomicWriteOptions = {},
): Promise<void> {
  await writeFileAtomic(filePath, `${JSON.stringify(value, null, 2)}\n`, options);
}

export async function writeText(
  filePath: string,
  value: string,
  options: AtomicWriteOptions = {},
): Promise<void> {
  await writeFileAtomic(filePath, value, options);
}

export async function writeBuffer(
  filePath: string,
  value: Buffer,
  options: AtomicWriteOptions = {},
): Promise<void> {
  await writeFileAtomic(filePath, value, options);
}
