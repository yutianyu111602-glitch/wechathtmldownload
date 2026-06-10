import { open } from "node:fs/promises";
import { dirname } from "node:path";

import { ensureDir } from "../utils/fs.js";
import { sha256Hex } from "../utils/hash.js";

export type StageResultStatus = "succeeded" | "failed" | "skipped" | "deferred";

export type StageRunnerId = "windows-4090" | "mac-m3pro" | "cloud-5090";

export interface StageRunManifest {
  run_id: string;
  stage: string;
  runner_id: StageRunnerId;
  article_id: string;
  account_key: string;
  source_url: string;
  input_ref: string;
  input_sha256: string;
  prompt_id: string;
  prompt_sha256: string;
  model_id: string;
  params_hash: string;
  schema_version: string;
  idempotency_key: string;
  expected_output_ref: string;
}

export interface StageResultLogRow {
  run_id: string;
  stage: string;
  article_id: string;
  status: StageResultStatus;
  started_at: string;
  finished_at: string;
  runner_id: StageRunnerId;
  model_id: string;
  input_hash: string;
  output_hash: string;
  error_type: string;
  error_message: string;
  output_paths: string[];
}

export interface BuildIdempotencyKeyInput {
  stage: string;
  articleId: string;
  inputSha256: string;
  modelId: string;
  promptSha256: string;
  paramsHash: string;
  schemaVersion: string;
}

function sortObject(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sortObject(item));
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => [key, sortObject(child)]),
  );
}

export function stableJson(value: unknown): string {
  return JSON.stringify(sortObject(value));
}

export function hashStageParams(value: unknown): string {
  return sha256Hex(stableJson(value ?? {}));
}

export function buildStageIdempotencyKey(input: BuildIdempotencyKeyInput): string {
  return sha256Hex(
    stableJson({
      stage: input.stage,
      article_id: input.articleId,
      input_sha256: input.inputSha256,
      model_id: input.modelId,
      prompt_sha256: input.promptSha256,
      params_hash: input.paramsHash,
      schema_version: input.schemaVersion,
    }),
  );
}

export function validateStageRunManifest(manifest: StageRunManifest): string[] {
  const errors: string[] = [];
  for (const key of [
    "run_id",
    "stage",
    "runner_id",
    "article_id",
    "input_ref",
    "input_sha256",
    "prompt_id",
    "prompt_sha256",
    "model_id",
    "params_hash",
    "schema_version",
    "idempotency_key",
    "expected_output_ref",
  ] satisfies Array<keyof StageRunManifest>) {
    if (!String(manifest[key] || "").trim()) {
      errors.push(`missing ${key}`);
    }
  }
  const expected = buildStageIdempotencyKey({
    stage: manifest.stage,
    articleId: manifest.article_id,
    inputSha256: manifest.input_sha256,
    modelId: manifest.model_id,
    promptSha256: manifest.prompt_sha256,
    paramsHash: manifest.params_hash,
    schemaVersion: manifest.schema_version,
  });
  if (manifest.idempotency_key && manifest.idempotency_key !== expected) {
    errors.push("idempotency_key mismatch");
  }
  return errors;
}

export async function appendStageResultLog(
  resultLogPath: string,
  row: StageResultLogRow,
): Promise<void> {
  await ensureDir(dirname(resultLogPath));
  const writer = await open(resultLogPath, "a");
  try {
    await writer.write(`${JSON.stringify(row)}\n`);
  } finally {
    await writer.close();
  }
}
