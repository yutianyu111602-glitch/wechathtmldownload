import { open, readFile, stat } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";

import { hasSensitivePathSegment } from "../artifacts/pathSafety.js";
import { ensureDir, writeJson } from "../utils/fs.js";
import { collectFiles } from "../utils/fileDiscovery.js";
import {
  buildDownstreamExpectedManifest,
  type DownstreamDependencies,
  runDownstreamLlmStage,
} from "./runDownstreamLlmStage.js";

export interface RunDownstreamLlmBatchOptions {
  inputDir: string;
  outDir?: string;
  statusPath?: string;
  resultLogPath?: string;
  stageName: string;
  modelId?: string;
  schemaVersion?: string;
  params?: Record<string, unknown>;
  resume?: boolean;
  concurrency?: number;
  now?: () => string;
}

export interface DownstreamLlmBatchSummary {
  input_root: string;
  output_root: string;
  status_path: string;
  result_log_path: string;
  stage_name: string;
  status: "running" | "completed";
  started_at: string;
  ended_at: string;
  total_items: number;
  queued_count: number;
  running_count: number;
  succeeded_count: number;
  failed_count: number;
  skipped_count: number;
}

interface DownstreamBatchItem {
  artifactDir: string;
  outDir: string;
  relativeDir: string;
  status: "queued" | "running" | "succeeded" | "failed" | "skipped";
  message: string;
  errorMessage: string;
  startedAt: string;
  endedAt: string;
}

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await stat(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readJsonIfExists<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

function defaultStatusPath(outputRoot: string): string {
  return join(outputRoot, "downstream-llm-batch-status.json");
}

function defaultResultLogPath(outputRoot: string): string {
  return join(outputRoot, "downstream-llm-batch-results.jsonl");
}

function countStatus(
  items: DownstreamBatchItem[],
  status: DownstreamBatchItem["status"],
): number {
  return items.filter((item) => item.status === status).length;
}

async function appendResultLog(
  resultLogPath: string,
  row: unknown,
): Promise<void> {
  await ensureDir(dirname(resultLogPath));
  const writer = await open(resultLogPath, "a");
  try {
    await writer.write(`${JSON.stringify(row)}\n`);
  } finally {
    await writer.close();
  }
}

function buildSummary(options: {
  inputRoot: string;
  outputRoot: string;
  statusPath: string;
  resultLogPath: string;
  stageName: string;
  status: "running" | "completed";
  startedAt: string;
  endedAt: string;
  items: DownstreamBatchItem[];
}): DownstreamLlmBatchSummary & { items: DownstreamBatchItem[] } {
  return {
    input_root: options.inputRoot,
    output_root: options.outputRoot,
    status_path: options.statusPath,
    result_log_path: options.resultLogPath,
    stage_name: options.stageName,
    status: options.status,
    started_at: options.startedAt,
    ended_at: options.endedAt,
    total_items: options.items.length,
    queued_count: countStatus(options.items, "queued"),
    running_count: countStatus(options.items, "running"),
    succeeded_count: countStatus(options.items, "succeeded"),
    failed_count: countStatus(options.items, "failed"),
    skipped_count: countStatus(options.items, "skipped"),
    items: options.items.slice(-200),
  };
}

export async function runDownstreamLlmBatch(
  options: RunDownstreamLlmBatchOptions,
  dependencies: DownstreamDependencies = {},
): Promise<DownstreamLlmBatchSummary> {
  const inputRoot = resolve(options.inputDir);
  const outputRoot = resolve(options.outDir || options.inputDir);
  const statusPath = resolve(options.statusPath || defaultStatusPath(outputRoot));
  const resultLogPath = resolve(options.resultLogPath || defaultResultLogPath(outputRoot));
  const stageName = options.stageName || "event_extract";
  const concurrency = Math.max(1, Math.floor(options.concurrency || 1));
  const now = options.now || (() => new Date().toISOString());
  const startedAt = now();
  await ensureDir(outputRoot);

  const llmInputs = await collectFiles(inputRoot, (filePath) => filePath.endsWith("llm_input.md"));
  const items: DownstreamBatchItem[] = llmInputs
    .map((llmInputPath) => {
      const artifactDir = dirname(llmInputPath);
      const relativeDir = relative(inputRoot, artifactDir);
      const outDir = options.outDir ? join(outputRoot, relativeDir) : artifactDir;
      return {
        artifactDir,
        outDir,
        relativeDir,
        status: "queued" as const,
        message: "",
        errorMessage: "",
        startedAt: "",
        endedAt: "",
      };
    })
    .filter((item) => item.relativeDir && !hasSensitivePathSegment(item.relativeDir));

  async function writeSnapshot(status: "running" | "completed", endedAt = ""): Promise<void> {
    await writeJson(
      statusPath,
      buildSummary({
        inputRoot,
        outputRoot,
        statusPath,
        resultLogPath,
        stageName,
        status,
        startedAt,
        endedAt,
        items,
      }),
    );
  }

  await writeSnapshot("running");
  let nextIndex = 0;

  async function worker(): Promise<void> {
    for (;;) {
      const item = items[nextIndex];
      nextIndex += 1;
      if (!item) {
        return;
      }
      item.startedAt = now();
      item.status = "running";
      await writeSnapshot("running");
      try {
        const expectedManifest = await buildDownstreamExpectedManifest({
          artifactDir: item.artifactDir,
          outDir: item.outDir,
          stageName,
          articleId: item.relativeDir.replace(/\\/g, "/"),
          modelId: options.modelId,
          schemaVersion: options.schemaVersion,
          params: options.params,
        });
        const existingManifest = await readJsonIfExists<{ idempotency_key?: string }>(
          join(item.outDir, "downstream_manifest.json"),
        );
        if (
          options.resume &&
          (await pathExists(join(item.outDir, "downstream_result.json"))) &&
          existingManifest?.idempotency_key === expectedManifest.idempotency_key
        ) {
          item.status = "skipped";
          item.message = "existing downstream_result.json with matching idempotency key";
        } else {
          await runDownstreamLlmStage(
            {
              artifactDir: item.artifactDir,
              outDir: item.outDir,
              stageName,
              articleId: item.relativeDir.replace(/\\/g, "/"),
              modelId: options.modelId,
              schemaVersion: options.schemaVersion,
              params: options.params,
            },
            dependencies,
          );
          item.status = "succeeded";
          item.message = "downstream stage completed";
        }
      } catch (error) {
        item.status = "failed";
        item.errorMessage = error instanceof Error ? error.message : String(error);
      } finally {
        item.endedAt = now();
        await appendResultLog(resultLogPath, {
          relative_dir: item.relativeDir,
          artifact_dir: item.artifactDir,
          out_dir: item.outDir,
          status: item.status,
          message: item.message,
          error_message: item.errorMessage,
          started_at: item.startedAt,
          ended_at: item.endedAt,
          stage: stageName,
        });
        await writeSnapshot("running");
      }
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, () => worker()),
  );
  const endedAt = now();
  await writeSnapshot("completed", endedAt);
  return buildSummary({
    inputRoot,
    outputRoot,
    statusPath,
    resultLogPath,
    stageName,
    status: "completed",
    startedAt,
    endedAt,
    items,
  });
}
