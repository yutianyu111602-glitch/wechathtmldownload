import { copyFile, mkdir, readFile, stat } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";

import {
  assertSafeRelativePath,
  hasSensitivePathSegment,
  toPortablePath,
} from "../artifacts/pathSafety.js";
import type { FinalLlmPackIndexRecord } from "../artifacts/types.js";
import type { SidecarJson } from "../archive/types.js";
import { collectFiles } from "../utils/fileDiscovery.js";
import { ensureDir, writeJson, writeText } from "../utils/fs.js";
import { readJsonlFile } from "../utils/jsonl.js";
import { sha256File, sha256Hex } from "../utils/hash.js";
import {
  buildStageIdempotencyKey,
  hashStageParams,
  stableJson,
  validateStageRunManifest,
  type StageRunManifest,
  type StageRunnerId,
} from "../stage/contracts.js";

const INPUT_FILE_NAMES = [
  "llm_input.md",
  "sidecar.json",
  "quality_report.json",
  "meta.json",
  "poster_ocr.json",
  "assets.json",
];

export interface CreateRunnerJobPackOptions {
  inputDir: string;
  outDir: string;
  stage: string;
  runnerId: StageRunnerId;
  modelId: string;
  promptId: string;
  promptText?: string;
  schemaVersion?: string;
  params?: Record<string, unknown>;
  limit?: number;
  includeAssets?: boolean;
  now?: () => string;
}

export interface RunnerJobPackSummary {
  version: number;
  generated_at: string;
  input_root: string;
  output_root: string;
  stage: string;
  runner_id: StageRunnerId;
  total_items: number;
  copied_input_files: number;
  copied_asset_files: number;
  manifest_path: string;
}

export interface ValidateRunnerResultPackOptions {
  inputDir: string;
  manifestPath?: string;
}

export interface RunnerResultPackValidation {
  status: "passed" | "failed";
  result_count: number;
  error_count: number;
  errors: string[];
  warnings: string[];
}

async function readJsonIfExists<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await stat(filePath);
    return true;
  } catch {
    return false;
  }
}

function safePromptFileName(promptId: string): string {
  return `${promptId.replace(/[^a-zA-Z0-9._-]+/g, "_") || "prompt"}.md`;
}

function deriveArticleId(inputRoot: string, articleDir: string): string {
  return toPortablePath(relative(inputRoot, articleDir));
}

function extractAccountKey(articleId: string): string {
  return articleId.split("/")[0] || "";
}

async function collectArticleDirs(inputRoot: string, limit?: number): Promise<string[]> {
  const llmInputs = await collectFiles(inputRoot, (filePath, fileName) => {
    return fileName === "llm_input.md" && !hasSensitivePathSegment(relative(inputRoot, filePath));
  });
  const articleDirs = llmInputs.map((filePath) => dirname(filePath));
  return typeof limit === "number" && limit > 0 ? articleDirs.slice(0, limit) : articleDirs;
}

async function copyKnownInputFiles(articleDir: string, targetDir: string): Promise<number> {
  let copied = 0;
  await mkdir(targetDir, { recursive: true });
  for (const fileName of INPUT_FILE_NAMES) {
    const sourcePath = join(articleDir, fileName);
    if (!(await pathExists(sourcePath))) {
      continue;
    }
    await copyFile(sourcePath, join(targetDir, fileName));
    copied += 1;
  }
  return copied;
}

async function copyAssetSubset(options: {
  articleDir: string;
  targetAssetDir: string;
  sidecar: SidecarJson | null;
}): Promise<number> {
  if (!options.sidecar) {
    return 0;
  }
  let copied = 0;
  for (const image of options.sidecar.images) {
    if (!image.local_path) {
      continue;
    }
    const sourcePath = resolve(options.articleDir, image.local_path);
    assertSafeRelativePath(options.articleDir, sourcePath);
    if (!(await pathExists(sourcePath))) {
      continue;
    }
    const targetPath = join(options.targetAssetDir, toPortablePath(image.local_path));
    await mkdir(dirname(targetPath), { recursive: true });
    await copyFile(sourcePath, targetPath);
    copied += 1;
  }
  return copied;
}

export async function createRunnerJobPack(
  options: CreateRunnerJobPackOptions,
): Promise<RunnerJobPackSummary> {
  const inputRoot = resolve(options.inputDir);
  const outputRoot = resolve(options.outDir);
  const manifestPath = join(outputRoot, "manifest.jsonl");
  const schemaVersion = options.schemaVersion || "v1";
  const paramsHash = hashStageParams(options.params || {});
  const promptSha256 = sha256Hex(options.promptText || "");
  const generatedAt = options.now ? options.now() : new Date().toISOString();
  const runId = `${options.stage}-${generatedAt.replace(/[^0-9A-Za-z]+/g, "")}`;

  await ensureDir(outputRoot);
  if (options.promptText) {
    await writeText(join(outputRoot, "prompts", safePromptFileName(options.promptId)), options.promptText);
  }
  await writeJson(join(outputRoot, "schemas", "stage-run-manifest.v1.json"), {
    schema: "StageRunManifest",
    version: 1,
    required: [
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
    ],
  });

  const articleDirs = await collectArticleDirs(inputRoot, options.limit);
  const manifestRows: StageRunManifest[] = [];
  let copiedInputFiles = 0;
  let copiedAssetFiles = 0;

  for (const articleDir of articleDirs) {
    const articleId = deriveArticleId(inputRoot, articleDir);
    if (!articleId || hasSensitivePathSegment(articleId)) {
      continue;
    }
    const targetInputDir = join(outputRoot, "inputs", articleId);
    copiedInputFiles += await copyKnownInputFiles(articleDir, targetInputDir);
    const llmInputPath = join(articleDir, "llm_input.md");
    const inputRef = toPortablePath(relative(outputRoot, join(targetInputDir, "llm_input.md")));
    const inputSha256 = await sha256File(llmInputPath);
    const sidecar = await readJsonIfExists<SidecarJson>(join(articleDir, "sidecar.json"));
    if (options.includeAssets !== false) {
      copiedAssetFiles += await copyAssetSubset({
        articleDir,
        targetAssetDir: join(outputRoot, "assets_subset", articleId),
        sidecar,
      });
    }

    const idempotencyKey = buildStageIdempotencyKey({
      stage: options.stage,
      articleId,
      inputSha256,
      modelId: options.modelId,
      promptSha256,
      paramsHash,
      schemaVersion,
    });
    const row: StageRunManifest = {
      run_id: runId,
      stage: options.stage,
      runner_id: options.runnerId,
      article_id: articleId,
      account_key: extractAccountKey(articleId),
      source_url: sidecar?.archive?.source_url || "",
      input_ref: inputRef,
      input_sha256: inputSha256,
      prompt_id: options.promptId,
      prompt_sha256: promptSha256,
      model_id: options.modelId,
      params_hash: paramsHash,
      schema_version: schemaVersion,
      idempotency_key: idempotencyKey,
      expected_output_ref: toPortablePath(join("results", `${articleId}.json`)),
    };
    const validationErrors = validateStageRunManifest(row);
    if (validationErrors.length > 0) {
      throw new Error(`Invalid runner job manifest row for ${articleId}: ${validationErrors.join(", ")}`);
    }
    manifestRows.push(row);
  }

  await writeText(
    manifestPath,
    `${manifestRows.map((row) => JSON.stringify(row)).join("\n")}${manifestRows.length > 0 ? "\n" : ""}`,
  );
  const summary: RunnerJobPackSummary = {
    version: 1,
    generated_at: generatedAt,
    input_root: inputRoot,
    output_root: outputRoot,
    stage: options.stage,
    runner_id: options.runnerId,
    total_items: manifestRows.length,
    copied_input_files: copiedInputFiles,
    copied_asset_files: copiedAssetFiles,
    manifest_path: manifestPath,
  };
  await writeJson(join(outputRoot, "run_summary.json"), summary);
  return summary;
}

async function readJsonlIfExists<T>(filePath: string): Promise<T[]> {
  if (!(await pathExists(filePath))) {
    return [];
  }
  return readJsonlFile<T>(filePath);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export async function validateRunnerResultPack(
  options: ValidateRunnerResultPackOptions,
): Promise<RunnerResultPackValidation> {
  const inputRoot = resolve(options.inputDir);
  const errors: string[] = [];
  const warnings: string[] = [];
  const results = await readJsonlIfExists<Record<string, unknown>>(join(inputRoot, "results.jsonl"));
  const resultErrors = await readJsonlIfExists<Record<string, unknown>>(join(inputRoot, "errors.jsonl"));
  const allowedArticleIds = new Set<string>();

  if (options.manifestPath) {
    const manifests = await readJsonlFile<StageRunManifest>(resolve(options.manifestPath));
    for (const manifest of manifests) {
      const manifestErrors = validateStageRunManifest(manifest);
      if (manifestErrors.length > 0) {
        errors.push(`manifest ${manifest.article_id}: ${manifestErrors.join(", ")}`);
      }
      allowedArticleIds.add(manifest.article_id);
    }
  }

  for (const [index, row] of results.entries()) {
    if (!isObject(row)) {
      errors.push(`results[${index}] is not an object`);
      continue;
    }
    const articleId = String(row.article_id || "");
    if (!articleId) {
      errors.push(`results[${index}] missing article_id`);
    }
    if (!row.runner_id) {
      errors.push(`results[${index}] missing runner_id`);
    }
    if (!row.status) {
      errors.push(`results[${index}] missing status`);
    }
    if (allowedArticleIds.size > 0 && articleId && !allowedArticleIds.has(articleId)) {
      errors.push(`results[${index}] article_id not present in manifest: ${articleId}`);
    }
  }

  if (!(await pathExists(join(inputRoot, "run_summary.json")))) {
    warnings.push("missing run_summary.json");
  }
  if (!(await pathExists(join(inputRoot, "hashes.json")))) {
    warnings.push("missing hashes.json");
  }

  return {
    status: errors.length > 0 ? "failed" : "passed",
    result_count: results.length,
    error_count: resultErrors.length,
    errors,
    warnings,
  };
}

export function buildRunnerParamsHash(params: Record<string, unknown>): string {
  return sha256Hex(stableJson(params));
}
