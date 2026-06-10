import { createReadStream } from "node:fs";
import { readFile } from "node:fs/promises";
import { createInterface } from "node:readline/promises";
import { dirname, join } from "node:path";

import { ensureDir, writeJson } from "../utils/fs.js";

export interface ShardManifest {
  shardIndex: number;
  shardPath: string;
  rowCount: number;
  startRow: number;
  endRow: number;
}

export interface ShardManifestSummary {
  sourcePath: string;
  totalRows: number;
  shardSize: number;
  shards: ShardManifest[];
  generatedAt: string;
}

export interface SplitManifestOptions {
  sourcePath: string;
  outDir: string;
  shardSize?: number;
  prefix?: string;
}

export async function splitManifestIntoShards(
  options: SplitManifestOptions,
): Promise<ShardManifestSummary> {
  const sourcePath = options.sourcePath;
  const outDir = options.outDir;
  const shardSize = Math.max(1, Math.min(options.shardSize || 5000, 10000));
  const prefix = options.prefix || "shard";

  await ensureDir(outDir);

  const rl = createInterface({
    input: createReadStream(sourcePath, { encoding: "utf8" }),
    crlfDelay: Infinity,
  });

  const shards: ShardManifest[] = [];
  let currentShardIndex = 0;
  let currentRowCount = 0;
  let totalRows = 0;
  let currentLines: string[] = [];
  let startRow = 0;

  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    // Validate JSON before including
    JSON.parse(trimmed);

    if (currentRowCount === 0) {
      startRow = totalRows;
    }

    currentLines.push(trimmed);
    currentRowCount += 1;
    totalRows += 1;

    if (currentRowCount >= shardSize) {
      const shardPath = join(outDir, `${prefix}_${String(currentShardIndex).padStart(4, "0")}.jsonl`);
      await writeJsonlLines(shardPath, currentLines);
      shards.push({
        shardIndex: currentShardIndex,
        shardPath,
        rowCount: currentRowCount,
        startRow,
        endRow: totalRows - 1,
      });
      currentShardIndex += 1;
      currentRowCount = 0;
      currentLines = [];
    }
  }

  // Flush remaining rows
  if (currentLines.length > 0) {
    const shardPath = join(outDir, `${prefix}_${String(currentShardIndex).padStart(4, "0")}.jsonl`);
    await writeJsonlLines(shardPath, currentLines);
    shards.push({
      shardIndex: currentShardIndex,
      shardPath,
      rowCount: currentRowCount,
      startRow,
      endRow: totalRows - 1,
    });
  }

  const summary: ShardManifestSummary = {
    sourcePath,
    totalRows,
    shardSize,
    shards,
    generatedAt: new Date().toISOString(),
  };

  const summaryPath = join(outDir, "shard-manifest-summary.json");
  await writeJson(summaryPath, summary);

  return summary;
}

async function writeJsonlLines(filePath: string, lines: string[]): Promise<void> {
  const { open } = await import("node:fs/promises");
  await ensureDir(dirname(filePath));
  const handle = await open(filePath, "w");
  try {
    for (const line of lines) {
      await handle.write(`${line}\n`);
    }
  } finally {
    await handle.close();
  }
}

export async function readShardManifestSummary(summaryPath: string): Promise<ShardManifestSummary> {
  const text = await readFile(summaryPath, "utf-8");
  const parsed = JSON.parse(text) as ShardManifestSummary;
  if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.shards)) {
    throw new Error(`Invalid shard manifest summary: ${summaryPath}`);
  }
  return parsed;
}
