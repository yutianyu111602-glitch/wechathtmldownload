import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { JobStoreSnapshot } from "./jobTypes.js";

export function createEmptyJobStoreSnapshot(): JobStoreSnapshot {
  const now = new Date().toISOString();
  return {
    version: 1,
    createdAt: now,
    updatedAt: now,
    jobs: [],
    articles: [],
  };
}

export async function loadJobStoreSnapshot(storePath: string): Promise<JobStoreSnapshot> {
  try {
    const raw = await readFile(storePath, "utf8");
    const parsed = JSON.parse(raw) as JobStoreSnapshot;
    if (parsed.version !== 1) {
      return createEmptyJobStoreSnapshot();
    }
    return parsed;
  } catch {
    return createEmptyJobStoreSnapshot();
  }
}

export async function saveJobStoreSnapshot(storePath: string, snapshot: JobStoreSnapshot): Promise<void> {
  await mkdir(dirname(storePath), { recursive: true });
  await writeFile(storePath, JSON.stringify(snapshot, null, 2), "utf8");
}
