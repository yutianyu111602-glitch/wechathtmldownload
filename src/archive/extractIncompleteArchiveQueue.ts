import { createReadStream } from "node:fs";
import { mkdir, open, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline/promises";

import { isValidArticleHtml } from "./articleHtmlQuality.js";
import { normalizeArticleToken } from "./normalizeArticleToken.js";
import type { ArchiveMetaJson, ArchiveQueueRecord } from "./types.js";

export interface ExtractIncompleteArchiveQueueOptions {
  manifestPath: string;
  archiveRoot: string;
  outPath: string;
  statuses?: string[];
}

export interface ExtractIncompleteArchiveQueueResult {
  manifestPath: string;
  archiveRoot: string;
  outPath: string;
  totalRecords: number;
  includedRecords: number;
  statusCounts: Record<string, number>;
}

const DEFAULT_STATUSES = new Set(["partial", "failed", "missing"]);

async function readArchiveMeta(
  archiveRoot: string,
  record: ArchiveQueueRecord,
): Promise<ArchiveMetaJson | null> {
  try {
    return JSON.parse(
      await readFile(
        join(archiveRoot, record.account_key, record.token, "archive_meta.json"),
        "utf-8",
      ),
    ) as ArchiveMetaJson;
  } catch {
    return null;
  }
}

async function hasValidRawHtml(
  archiveRoot: string,
  record: ArchiveQueueRecord,
): Promise<boolean> {
  try {
    const rawHtml = await readFile(
      join(archiveRoot, record.account_key, record.token, "raw.html"),
      "utf-8",
    );
    return rawHtml.trim().length > 0 && isValidArticleHtml(rawHtml);
  } catch {
    return false;
  }
}

function normalizeStatuses(statuses: string[] | undefined): Set<string> {
  const normalized = new Set(
    (statuses && statuses.length > 0 ? statuses : Array.from(DEFAULT_STATUSES))
      .map((status) => status.trim().toLowerCase())
      .filter(Boolean),
  );
  return normalized.size > 0 ? normalized : new Set(DEFAULT_STATUSES);
}

export async function extractIncompleteArchiveQueue(
  options: ExtractIncompleteArchiveQueueOptions,
): Promise<ExtractIncompleteArchiveQueueResult> {
  const manifestPath = resolve(options.manifestPath);
  const archiveRoot = resolve(options.archiveRoot);
  const outPath = resolve(options.outPath);
  const includedStatuses = normalizeStatuses(options.statuses);

  await mkdir(dirname(outPath), { recursive: true });
  const writer = await open(outPath, "w");
  const statusCounts: Record<string, number> = {};
  let totalRecords = 0;
  let includedRecords = 0;

  try {
    const rl = createInterface({
      input: createReadStream(manifestPath, { encoding: "utf8" }),
      crlfDelay: Infinity,
    });

    for await (const line of rl) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      totalRecords += 1;

      const record = JSON.parse(trimmed) as ArchiveQueueRecord;
      const meta = await readArchiveMeta(archiveRoot, record);
      const metaStatus = (meta?.status || "missing").toLowerCase();
      const validRawHtml = await hasValidRawHtml(archiveRoot, record);
      const statusKey = validRawHtml && metaStatus === "archived" ? "archived" : metaStatus;
      statusCounts[statusKey] = (statusCounts[statusKey] || 0) + 1;

      if (!validRawHtml || includedStatuses.has(statusKey)) {
        await writer.write(
          `${JSON.stringify({
            ...record,
            token: normalizeArticleToken(record.source_url),
          })}\n`,
        );
        includedRecords += 1;
      }
    }
  } finally {
    await writer.close();
  }

  return {
    manifestPath,
    archiveRoot,
    outPath,
    totalRecords,
    includedRecords,
    statusCounts,
  };
}
