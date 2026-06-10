import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import {
  appendFile,
  access,
  mkdir,
  rename,
  writeFile,
} from "node:fs/promises";
import { dirname } from "node:path";
import { createInterface } from "node:readline/promises";

import type { ArchiveQueueRecord } from "../archive/types.js";

export type DownloadQueueItemStatus =
  | "ready"
  | "leased"
  | "downloaded"
  | "failed_retryable"
  | "failed_terminal";

export interface DownloadQueueRecord extends ArchiveQueueRecord {
  queue_id: string;
  account_fakeid: string;
  account_nickname: string;
  status: DownloadQueueItemStatus;
  attempt_count: number;
  lease_owner: string;
  lease_expires_at: string;
  last_error: string;
}

export function makeDownloadQueueId(fakeid: string, sourceUrl: string): string {
  return createHash("sha1")
    .update(`${fakeid}\n${sourceUrl}`, "utf8")
    .digest("hex");
}

export function toArchiveQueueRecord(
  record: DownloadQueueRecord,
): ArchiveQueueRecord {
  return {
    account_key: record.account_key,
    token: record.token,
    source_url: record.source_url,
    title: record.title,
    author: record.author,
    cover_url: record.cover_url,
    post_time: record.post_time,
    post_date: record.post_date,
    page: record.page,
    discovered_at: record.discovered_at,
    discovery_source: record.discovery_source,
  };
}

export async function readExistingQueueIds(
  queuePath: string,
): Promise<Set<string>> {
  try {
    await access(queuePath);
    const ids = new Set<string>();
    const rl = createInterface({
      input: createReadStream(queuePath, { encoding: "utf8" }),
      crlfDelay: Infinity,
    });

    for await (const line of rl) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      try {
        const record = JSON.parse(trimmed) as Partial<DownloadQueueRecord>;
        if (record.queue_id) {
          ids.add(record.queue_id);
        }
      } catch {
        // Keep reading: one corrupt line should not hide the rest of the queue.
      }
    }
    return ids;
  } catch {
    return new Set<string>();
  }
}

export async function appendJsonlRecords<T>(
  filePath: string,
  records: T[],
): Promise<void> {
  if (records.length === 0) {
    return;
  }
  await mkdir(dirname(filePath), { recursive: true });
  await appendFile(
    filePath,
    records.map((record) => JSON.stringify(record)).join("\n") + "\n",
    "utf8",
  );
}

export async function writeJsonAtomic(
  filePath: string,
  value: unknown,
): Promise<void> {
  await mkdir(dirname(filePath), { recursive: true });
  const tmpPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tmpPath, JSON.stringify(value, null, 2), "utf8");
  await writeFile(tmpPath, "\n", { encoding: "utf8", flag: "a" });
  await rename(tmpPath, filePath);
}
