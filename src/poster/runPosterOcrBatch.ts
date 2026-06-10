import { open, readFile, stat } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";

import type {
  AssetsLocalJson,
  QualityReportJson,
  SidecarJson,
} from "../archive/types.js";
import { determineFinalLlmQualityGrade } from "../artifacts/finalizeLlmPack.js";
import { hasSensitivePathSegment } from "../artifacts/pathSafety.js";
import { buildLlmInputMdFromSidecar } from "../extract/buildLlmInputMd.js";
import { buildQualityReport } from "../extract/buildSidecar.js";
import type { MetaJson } from "../types.js";
import { collectFiles } from "../utils/fileDiscovery.js";
import { ensureDir, writeJson, writeText } from "../utils/fs.js";
import { runPosterOcrFallback } from "./runPosterOcrFallback.js";
import type { FinalLlmQualityGrade } from "../artifacts/types.js";

const DEFAULT_ONLY_QUALITY: FinalLlmQualityGrade[] = ["review", "blocked"];

export interface RunPosterOcrBatchOptions {
  artifactRoot: string;
  archiveRoot: string;
  artifactListPath?: string;
  onlyQuality?: FinalLlmQualityGrade[];
  statusPath?: string;
  resultLogPath?: string;
  resume?: boolean;
  concurrency?: number;
  limit?: number;
  now?: () => string;
}

export interface PosterOcrBatchSummary {
  artifact_root: string;
  archive_root: string;
  artifact_list_path?: string;
  status_path: string;
  result_log_path: string;
  only_quality: FinalLlmQualityGrade[];
  item_limit?: number;
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

interface PosterOcrBatchItem {
  artifactDir: string;
  archiveDir: string;
  relativeDir: string;
  qualityGrade: FinalLlmQualityGrade;
  status: "queued" | "running" | "succeeded" | "failed" | "skipped";
  message: string;
  errorMessage: string;
  startedAt: string;
  endedAt: string;
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

async function posterOcrHasReusableResult(filePath: string): Promise<boolean> {
  const value = await readJsonIfExists<Record<string, unknown>>(filePath);
  if (!value) {
    return false;
  }

  const backend = typeof value.backend === "string" ? value.backend.trim().toLowerCase() : "";
  const plainText = typeof value.plain_text === "string" ? value.plain_text.trim() : "";
  const hasBlockText =
    Array.isArray(value.blocks) &&
    value.blocks.some((block) => {
      if (!block || typeof block !== "object") {
        return false;
      }
      const text = (block as Record<string, unknown>).text;
      return typeof text === "string" && text.trim().length > 0;
    });

  if (backend === "none" || backend === "skipped") {
    return Boolean(plainText || hasBlockText);
  }

  const imageHeavy = value.imageHeavy === true;
  if (!imageHeavy) {
    return Boolean(backend || plainText || hasBlockText);
  }

  return Boolean(backend && (plainText || hasBlockText));
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function mergePosterOcrIntoSidecar(
  sidecar: SidecarJson,
  posterOcr: SidecarJson["poster_ocr"],
): SidecarJson {
  return {
    ...sidecar,
    footer_info: {
      ...sidecar.footer_info,
      venue_name_candidate:
        sidecar.footer_info.venue_name_candidate ||
        posterOcr.recovered.venue_name_candidate ||
        "",
      venue_address_lines: uniqueStrings([
        ...sidecar.footer_info.venue_address_lines,
        ...(posterOcr.recovered.venue_address_lines ?? []),
      ]),
      lineup_lines: uniqueStrings([
        ...sidecar.footer_info.lineup_lines,
        ...(posterOcr.recovered.lineup_lines ?? []),
      ]),
      date_texts: uniqueStrings([
        ...sidecar.footer_info.date_texts,
        ...(posterOcr.recovered.date_texts ?? []),
      ]),
    },
    warnings: uniqueStrings([...sidecar.warnings, ...posterOcr.warnings]),
    poster_ocr: posterOcr,
  };
}

function countStatus(
  items: PosterOcrBatchItem[],
  status: PosterOcrBatchItem["status"],
): number {
  return items.filter((item) => item.status === status).length;
}

function defaultStatusPath(artifactRoot: string): string {
  return join(artifactRoot, "poster-ocr-batch-status.json");
}

function defaultResultLogPath(artifactRoot: string): string {
  return join(artifactRoot, "poster-ocr-batch-results.jsonl");
}

async function appendResultLog(resultLogPath: string, row: unknown): Promise<void> {
  await ensureDir(dirname(resultLogPath));
  const writer = await open(resultLogPath, "a");
  try {
    await writer.write(`${JSON.stringify(row)}\n`);
  } finally {
    await writer.close();
  }
}

function buildSummary(options: {
  artifactRoot: string;
  archiveRoot: string;
  artifactListPath?: string;
  statusPath: string;
  resultLogPath: string;
  onlyQuality: FinalLlmQualityGrade[];
  itemLimit?: number;
  status: "running" | "completed";
  startedAt: string;
  endedAt: string;
  items: PosterOcrBatchItem[];
}): PosterOcrBatchSummary & { items: PosterOcrBatchItem[] } {
  return {
    artifact_root: options.artifactRoot,
    archive_root: options.archiveRoot,
    artifact_list_path: options.artifactListPath,
    status_path: options.statusPath,
    result_log_path: options.resultLogPath,
    only_quality: options.onlyQuality,
    item_limit: options.itemLimit,
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

function deriveArchiveDir(
  archiveRoot: string,
  relativeDir: string,
  sidecar: SidecarJson | null,
): string {
  const segments = relativeDir.split(/[\\/]+/g).filter(Boolean);
  const account = sidecar?.archive?.account_key || segments[0] || "";
  const token = sidecar?.archive?.token ||
    (segments.at(-1) === "raw" ? segments.at(-2) : segments.at(-1)) ||
    "";
  return join(archiveRoot, account, token);
}

function isSafeArtifactRelativePath(relativeDir: string): boolean {
  return Boolean(relativeDir) &&
    !relativeDir.startsWith("..") &&
    !relativeDir.includes(":") &&
    !hasSensitivePathSegment(relativeDir);
}

function parseArtifactList(content: string): string[] {
  return uniqueStrings(content.split(/\r?\n/));
}

function deriveLlmInputPathFromArtifactListEntry(entry: string): string {
  const resolved = resolve(entry);
  const lower = resolved.toLowerCase();
  if (lower.endsWith("llm_input.md")) {
    return resolved;
  }
  if (
    lower.endsWith("poster_ocr.json") ||
    lower.endsWith("sidecar.json") ||
    lower.endsWith("quality_report.json") ||
    lower.endsWith("meta.json")
  ) {
    return join(dirname(resolved), "llm_input.md");
  }
  return join(resolved, "llm_input.md");
}

async function collectLlmInputCandidates(options: {
  artifactRoot: string;
  artifactListPath?: string;
}): Promise<string[]> {
  if (!options.artifactListPath) {
    return collectFiles(options.artifactRoot, (filePath) => filePath.endsWith("llm_input.md"));
  }

  const content = await readFile(options.artifactListPath, "utf-8");
  const llmInputPaths: string[] = [];
  for (const entry of parseArtifactList(content)) {
    const llmInputPath = deriveLlmInputPathFromArtifactListEntry(entry);
    const relativeDir = relative(options.artifactRoot, dirname(llmInputPath));
    if (!isSafeArtifactRelativePath(relativeDir)) {
      continue;
    }
    llmInputPaths.push(llmInputPath);
  }
  return uniqueStrings(llmInputPaths);
}

export async function runPosterOcrBatch(
  options: RunPosterOcrBatchOptions,
): Promise<PosterOcrBatchSummary> {
  const artifactRoot = resolve(options.artifactRoot);
  const archiveRoot = resolve(options.archiveRoot);
  const artifactListPath = options.artifactListPath ? resolve(options.artifactListPath) : undefined;
  const statusPath = resolve(options.statusPath || defaultStatusPath(artifactRoot));
  const resultLogPath = resolve(options.resultLogPath || defaultResultLogPath(artifactRoot));
  const onlyQuality = options.onlyQuality?.length
    ? options.onlyQuality
    : DEFAULT_ONLY_QUALITY;
  const onlyQualitySet = new Set<FinalLlmQualityGrade>(onlyQuality);
  const concurrency = Math.max(1, Math.floor(options.concurrency || 1));
  const itemLimit =
    typeof options.limit === "number" && Number.isFinite(options.limit) && options.limit > 0
      ? Math.floor(options.limit)
      : undefined;
  const now = options.now || (() => new Date().toISOString());
  const startedAt = now();

  const llmInputs = await collectLlmInputCandidates({ artifactRoot, artifactListPath });
  const items: PosterOcrBatchItem[] = [];
  for (const llmInputPath of llmInputs) {
    const artifactDir = dirname(llmInputPath);
    const relativeDir = relative(artifactRoot, artifactDir);
    if (!isSafeArtifactRelativePath(relativeDir)) {
      continue;
    }
    if (artifactListPath && !(await pathExists(llmInputPath))) {
      continue;
    }
    const [llmInput, meta, sidecar, qualityReport] = await Promise.all([
      readFile(llmInputPath, "utf-8"),
      readJsonIfExists<MetaJson>(join(artifactDir, "meta.json")),
      readJsonIfExists<SidecarJson>(join(artifactDir, "sidecar.json")),
      readJsonIfExists<QualityReportJson>(join(artifactDir, "quality_report.json")),
    ]);
    const qualityGrade = determineFinalLlmQualityGrade({
      llmInput,
      meta,
      sidecar,
      qualityReport,
    });
    if (!onlyQualitySet.has(qualityGrade)) {
      continue;
    }
    items.push({
      artifactDir,
      archiveDir: deriveArchiveDir(archiveRoot, relativeDir, sidecar),
      relativeDir,
      qualityGrade,
      status: "queued",
      message: "",
      errorMessage: "",
      startedAt: "",
      endedAt: "",
    });
    if (itemLimit !== undefined && items.length >= itemLimit) {
      break;
    }
  }

  async function writeSnapshot(status: "running" | "completed", endedAt = ""): Promise<void> {
    await writeJson(
      statusPath,
      buildSummary({
        artifactRoot,
        archiveRoot,
        artifactListPath,
        statusPath,
        resultLogPath,
        onlyQuality,
        itemLimit,
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
      item.status = "running";
      item.startedAt = now();
      await writeSnapshot("running");
      try {
        const posterOcrPath = join(item.artifactDir, "poster_ocr.json");
        if (
          options.resume &&
          (await pathExists(posterOcrPath)) &&
          (await posterOcrHasReusableResult(posterOcrPath))
        ) {
          item.status = "skipped";
          item.message = "existing poster_ocr.json with v2 contract";
        } else {
          const sidecar = await readJsonIfExists<SidecarJson>(
            join(item.artifactDir, "sidecar.json"),
          );
          if (!sidecar) {
            throw new Error("missing sidecar.json");
          }
          const localAssets = await readJsonIfExists<AssetsLocalJson>(
            join(item.archiveDir, "assets_local.json"),
          );
          const posterOcr = await runPosterOcrFallback({
            bundleDir: item.archiveDir,
            mainText: sidecar.main_content,
            localAssets,
          });
          const updatedSidecar = mergePosterOcrIntoSidecar(sidecar, posterOcr);
          const updatedQualityReport = buildQualityReport(updatedSidecar);
          const llmInput = buildLlmInputMdFromSidecar(updatedSidecar);
          await writeJson(posterOcrPath, posterOcr);
          await writeJson(join(item.artifactDir, "sidecar.json"), updatedSidecar);
          await writeJson(join(item.artifactDir, "quality_report.json"), updatedQualityReport);
          await writeText(join(item.artifactDir, "llm_input.md"), llmInput);
          await writeText(join(item.artifactDir, "sidecar.md"), llmInput);
          item.status = "succeeded";
          item.message = `ocr backend=${posterOcr.backend || "unknown"}`;
        }
      } catch (error) {
        item.status = "failed";
        item.errorMessage = error instanceof Error ? error.message : String(error);
      } finally {
        item.endedAt = now();
        await appendResultLog(resultLogPath, {
          relative_dir: item.relativeDir,
          artifact_dir: item.artifactDir,
          archive_dir: item.archiveDir,
          quality_grade: item.qualityGrade,
          status: item.status,
          message: item.message,
          error_message: item.errorMessage,
          started_at: item.startedAt,
          ended_at: item.endedAt,
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
    artifactRoot,
    archiveRoot,
    artifactListPath,
    statusPath,
    resultLogPath,
    onlyQuality,
    itemLimit,
    status: "completed",
    startedAt,
    endedAt,
    items,
  });
}
