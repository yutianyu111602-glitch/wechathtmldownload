import { readFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";

import { sha256Hex } from "../utils/hash.js";
import { ensureDir, writeJson } from "../utils/fs.js";
import {
  buildStageIdempotencyKey,
  hashStageParams,
  type StageRunManifest,
} from "../stage/contracts.js";

export interface RunDownstreamLlmStageOptions {
  artifactDir: string;
  outDir: string;
  stageName: string;
  articleId?: string;
  accountKey?: string;
  sourceUrl?: string;
  modelId?: string;
  schemaVersion?: string;
  params?: Record<string, unknown>;
}

export interface DownstreamInvocationInput {
  markdown: string;
  meta: Record<string, unknown>;
  stageName: string;
  promptId: string;
  systemPrompt: string;
  modelId: string;
  params: Record<string, unknown>;
}

export interface DownstreamInvocationOutput {
  provider: string;
  model: string;
  rawText: string;
  parsed?: Record<string, unknown> | null;
}

export interface DownstreamDependencies {
  invokeModel?: (
    input: DownstreamInvocationInput,
  ) => Promise<DownstreamInvocationOutput>;
}

export interface DownstreamLlmResult {
  stage: string;
  promptId: string;
  provider: string;
  model: string;
  rawText: string;
  parsed?: Record<string, unknown> | null;
}

export interface DownstreamStageManifest extends StageRunManifest {
  input_markdown_path: string;
  meta_path: string;
  markdown_sha256: string;
  system_prompt_sha256: string;
}

export const RAW_ENTITY_INFO_GUARDRAIL = [
  "Raw entity info preservation hard rule:",
  "- Entity biographies/bios, label or collective introductions, and venue profiles/info must stay as exact source text.",
  "- Do not summarize, paraphrase, abstract, rewrite, translate, shorten, merge, normalize, or invent these descriptive fields.",
  "- If a schema needs these fields, copy the exact span from the article/poster OCR; if the exact span is unavailable or too long, leave it empty and add a warning instead of abstracting it.",
].join("\n");

function appendRawEntityInfoGuardrail(systemPrompt: string): string {
  return `${systemPrompt.trim()}\n\n${RAW_ENTITY_INFO_GUARDRAIL}`;
}

async function defaultInvokeModel(): Promise<DownstreamInvocationOutput> {
  const apiKey = process.env.OPENAI_API_KEY || process.env.GLOBAL_OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error(
      "No downstream LLM provider configured. Set OPENAI_API_KEY/GLOBAL_OPENAI_API_KEY or inject invokeModel().",
    );
  }

  throw new Error("defaultInvokeModel requires invocation context");
}

function integerFromEnv(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value || "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

async function resolveDownstreamPrompt(): Promise<{ promptId: string; systemPrompt: string }> {
  const defaultPrompt =
    "You are a downstream extraction stage. Return compact JSON only with the best structured result you can infer from the article.";
  const promptPath = process.env.WECHAT_DOWNSTREAM_SYSTEM_PROMPT_PATH?.trim();
  const inlinePrompt = process.env.WECHAT_DOWNSTREAM_SYSTEM_PROMPT?.trim();
  const systemPrompt = promptPath
    ? (await readFile(resolve(promptPath), "utf-8")).trim()
    : inlinePrompt || defaultPrompt;
  return {
    promptId:
      process.env.WECHAT_DOWNSTREAM_PROMPT_ID?.trim() ||
      (promptPath ? `file:${resolve(promptPath)}` : inlinePrompt ? "env:inline" : "default"),
    systemPrompt: appendRawEntityInfoGuardrail(systemPrompt),
  };
}

function resolveDownstreamModelId(options: RunDownstreamLlmStageOptions): string {
  return (
    options.modelId ||
    process.env.WECHAT_DOWNSTREAM_MODEL ||
    process.env.OPENAI_MODEL ||
    "gpt-4.1-mini"
  );
}

function resolveDownstreamParams(options: RunDownstreamLlmStageOptions): Record<string, unknown> {
  const timeoutMs = integerFromEnv(process.env.WECHAT_DOWNSTREAM_TIMEOUT_MS, 180000);
  const maxTokens = integerFromEnv(process.env.WECHAT_DOWNSTREAM_MAX_TOKENS, 2048);
  return {
    temperature: 0.1,
    max_tokens: maxTokens,
    timeout_ms: timeoutMs,
    ...(options.params || {}),
  };
}

function inferArticleId(artifactDir: string): string {
  const token = basename(artifactDir);
  const account = basename(dirname(artifactDir));
  return account && account !== "." ? `${account}/${token}` : token;
}

async function invokeOpenAiCompatible(
  input: DownstreamInvocationInput,
): Promise<DownstreamInvocationOutput> {
  const apiKey = process.env.OPENAI_API_KEY || process.env.GLOBAL_OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error(
      "No downstream LLM provider configured. Set OPENAI_API_KEY/GLOBAL_OPENAI_API_KEY or inject invokeModel().",
    );
  }

  const baseUrl =
    process.env.OPENAI_BASE_URL ||
    process.env.GLOBAL_OPENAI_BASE_URL ||
    "https://api.openai.com/v1";
  const model = input.modelId;
  const timeoutMs =
    typeof input.params.timeout_ms === "number"
      ? input.params.timeout_ms
      : integerFromEnv(process.env.WECHAT_DOWNSTREAM_TIMEOUT_MS, 180000);
  const maxTokens =
    typeof input.params.max_tokens === "number"
      ? input.params.max_tokens
      : integerFromEnv(process.env.WECHAT_DOWNSTREAM_MAX_TOKENS, 2048);
  const { timeout_ms: _timeoutMs, ...requestParams } = input.params;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}/chat/completions`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${apiKey}`,
      },
      signal: controller.signal,
      body: JSON.stringify({
        ...requestParams,
        model,
        max_tokens: maxTokens,
        messages: [
          {
            role: "system",
            content: input.systemPrompt,
          },
          {
            role: "user",
            content: JSON.stringify(
              {
                stage: input.stageName,
                meta: input.meta,
                markdown: input.markdown,
              },
              null,
              2,
            ),
          },
        ],
      }),
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`Downstream LLM request timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }

  const payload = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
    error?: { message?: string };
  };
  if (!response.ok) {
    throw new Error(payload.error?.message || `Downstream LLM request failed: HTTP ${response.status}`);
  }

  const rawText = payload.choices?.[0]?.message?.content?.trim() || "";
  let parsed: Record<string, unknown> | null = null;
  try {
    parsed = JSON.parse(rawText) as Record<string, unknown>;
  } catch {
    parsed = null;
  }

  return {
    provider: "openai-compatible",
    model,
    rawText,
    parsed,
  };
}

export async function buildDownstreamExpectedManifest(
  options: RunDownstreamLlmStageOptions,
): Promise<DownstreamStageManifest> {
  const artifactDir = resolve(options.artifactDir);
  const outDir = resolve(options.outDir);
  const markdownPath = join(artifactDir, "llm_input.md");
  const metaPath = join(artifactDir, "meta.json");
  const markdown = await readFile(markdownPath, "utf-8");
  const meta = JSON.parse(await readFile(metaPath, "utf-8")) as Record<string, unknown>;
  const prompt = await resolveDownstreamPrompt();
  const modelId = resolveDownstreamModelId(options);
  const params = resolveDownstreamParams(options);
  const paramsHash = hashStageParams(params);
  const markdownSha256 = sha256Hex(markdown);
  const promptSha256 = sha256Hex(prompt.systemPrompt);
  const schemaVersion = options.schemaVersion || "downstream-stage.v1";
  const articleId = options.articleId || inferArticleId(artifactDir);
  const idempotencyKey = buildStageIdempotencyKey({
    stage: options.stageName,
    articleId,
    inputSha256: markdownSha256,
    modelId,
    promptSha256,
    paramsHash,
    schemaVersion,
  });

  return {
    run_id: `${options.stageName}-${schemaVersion}`,
    stage: options.stageName,
    runner_id: "windows-4090",
    article_id: articleId,
    account_key: options.accountKey || String(meta.account_name || articleId.split("/")[0] || ""),
    source_url: options.sourceUrl || String(meta.source_url || ""),
    input_ref: markdownPath,
    input_sha256: markdownSha256,
    prompt_id: prompt.promptId,
    prompt_sha256: promptSha256,
    model_id: modelId,
    params_hash: paramsHash,
    schema_version: schemaVersion,
    idempotency_key: idempotencyKey,
    expected_output_ref: join(outDir, "downstream_result.json"),
    input_markdown_path: markdownPath,
    meta_path: metaPath,
    markdown_sha256: markdownSha256,
    system_prompt_sha256: promptSha256,
  };
}

export async function runDownstreamLlmStage(
  options: RunDownstreamLlmStageOptions,
  dependencies: DownstreamDependencies = {},
): Promise<DownstreamLlmResult> {
  const artifactDir = resolve(options.artifactDir);
  const outDir = resolve(options.outDir);
  await ensureDir(outDir);

  const markdownPath = join(artifactDir, "llm_input.md");
  const metaPath = join(artifactDir, "meta.json");
  const markdown = await readFile(markdownPath, "utf-8");
  const meta = JSON.parse(await readFile(metaPath, "utf-8")) as Record<string, unknown>;
  const prompt = await resolveDownstreamPrompt();
  const modelId = resolveDownstreamModelId(options);
  const params = resolveDownstreamParams(options);
  const manifest = await buildDownstreamExpectedManifest(options);

  const invokeModel = dependencies.invokeModel || invokeOpenAiCompatible;
  const invocation = await invokeModel({
    markdown,
    meta,
    stageName: options.stageName,
    promptId: prompt.promptId,
    systemPrompt: prompt.systemPrompt,
    modelId,
    params,
  });

  const result: DownstreamLlmResult = {
    stage: options.stageName,
    promptId: prompt.promptId,
    provider: invocation.provider,
    model: invocation.model,
    rawText: invocation.rawText,
    parsed: invocation.parsed || null,
  };

  await writeJson(join(outDir, "downstream_manifest.json"), manifest);
  await writeJson(join(outDir, "downstream_result.json"), result);
  return result;
}
