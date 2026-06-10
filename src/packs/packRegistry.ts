import { open, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

import { ensureDir, writeJson } from "../utils/fs.js";
import { sha256Hex } from "../utils/hash.js";
import { writeChecksumsFile } from "./checksums.js";

export type RegisteredPackType =
  | "final_pack"
  | "graph_candidate_pack"
  | "runner_job_pack"
  | "runner_result_pack"
  | "vector_pack";

export interface RegisterPackOptions {
  packDir: string;
  registryRoot: string;
  packType: RegisteredPackType;
  packId?: string;
  sourceFamily?: string;
  schemaVersion?: string;
  now?: () => string;
}

export interface PackRegistryRecord {
  pack_id: string;
  pack_type: RegisteredPackType;
  schema_version: string;
  source_family: string;
  pack_dir: string;
  generated_at: string;
  checksums_path: string;
  file_count: number;
  aggregate_sha256: string;
}

async function appendJsonl(filePath: string, row: unknown): Promise<void> {
  await ensureDir(dirname(filePath));
  const writer = await open(filePath, "a");
  try {
    await writer.write(`${JSON.stringify(row)}\n`);
  } finally {
    await writer.close();
  }
}

export async function registerPack(options: RegisterPackOptions): Promise<PackRegistryRecord> {
  const packDir = resolve(options.packDir);
  const registryRoot = resolve(options.registryRoot);
  const generatedAt = options.now ? options.now() : new Date().toISOString();
  const checksums = await writeChecksumsFile(packDir);
  const checksumText = await readFile(checksums.checksums_path, "utf-8");
  const aggregateSha256 = sha256Hex(checksumText);
  const packId =
    options.packId ||
    `${options.packType}-${generatedAt.replace(/[^0-9A-Za-z]+/g, "")}-${aggregateSha256.slice(0, 12)}`;
  const record: PackRegistryRecord = {
    pack_id: packId,
    pack_type: options.packType,
    schema_version: options.schemaVersion || "v1",
    source_family: options.sourceFamily || "wechat",
    pack_dir: packDir,
    generated_at: generatedAt,
    checksums_path: checksums.checksums_path,
    file_count: checksums.file_count,
    aggregate_sha256: aggregateSha256,
  };

  await writeJson(join(registryRoot, "records", `${packId}.json`), record);
  await appendJsonl(join(registryRoot, "index.jsonl"), record);
  return record;
}
