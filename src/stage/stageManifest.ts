import { createHash } from "node:crypto";

import {
  buildStageIdempotencyKey,
  validateStageRunManifest,
  type BuildIdempotencyKeyInput,
  type StageRunManifest,
} from "./contracts.js";

export type StageManifestRow = StageRunManifest;

export interface BuildArticleStageIdInput {
  articleId: string;
  stage: string;
}

export function buildArticleStageId(input: BuildArticleStageIdInput): string {
  return createHash("sha256")
    .update(`${input.stage}:${input.articleId}`)
    .digest("hex")
    .slice(0, 24);
}

export function buildStageManifestIdempotencyKey(
  input: BuildIdempotencyKeyInput,
): string {
  return buildStageIdempotencyKey(input);
}

export function validateStageManifestRow(
  manifest: StageManifestRow,
): string[] {
  return validateStageRunManifest(manifest);
}

export function stageManifestRowFromInput(input: {
  runId: string;
  stage: string;
  runnerId: StageManifestRow["runner_id"];
  articleId: string;
  accountKey: string;
  sourceUrl: string;
  inputRef: string;
  inputSha256: string;
  promptId: string;
  promptSha256: string;
  modelId: string;
  paramsHash: string;
  schemaVersion: string;
  expectedOutputRef: string;
}): StageManifestRow {
  const idempotencyKey = buildStageManifestIdempotencyKey({
    stage: input.stage,
    articleId: input.articleId,
    inputSha256: input.inputSha256,
    modelId: input.modelId,
    promptSha256: input.promptSha256,
    paramsHash: input.paramsHash,
    schemaVersion: input.schemaVersion,
  });
  return {
    run_id: input.runId,
    stage: input.stage,
    runner_id: input.runnerId,
    article_id: input.articleId,
    account_key: input.accountKey,
    source_url: input.sourceUrl,
    input_ref: input.inputRef,
    input_sha256: input.inputSha256,
    prompt_id: input.promptId,
    prompt_sha256: input.promptSha256,
    model_id: input.modelId,
    params_hash: input.paramsHash,
    schema_version: input.schemaVersion,
    idempotency_key: idempotencyKey,
    expected_output_ref: input.expectedOutputRef,
  };
}
