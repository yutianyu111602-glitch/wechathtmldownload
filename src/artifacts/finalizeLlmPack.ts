import { readdir } from "node:fs/promises";
import { copyFile, mkdir, readFile, stat } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";

import type {
  QualityReportJson,
  SidecarJson,
} from "../archive/types.js";
import type { MetaJson } from "../types.js";
import { isLlmShellLine } from "../extract/cleanLlmContent.js";
import { writeChecksumsFile } from "../packs/checksums.js";
import { ensureDir, writeJson, writeText } from "../utils/fs.js";
import {
  assertSafeRelativePath,
  hasSensitivePathSegment,
  isSafePathSegment,
  toPortablePath,
} from "./pathSafety.js";
import type {
  FinalLlmPackIndexRecord,
  FinalLlmPackManifest,
  FinalLlmQualityGrade,
} from "./types.js";

export interface FinalizeLlmPackOptions {
  artifactRoot: string;
  releaseRoot: string;
  manifestPath?: string;
  intakeManifestPath?: string;
  intakeOnly?: boolean;
  archiveRoot?: string;
  now?: () => string;
  maxPackSizeBytes?: number;
  maxArticles?: number;
}

const COPY_ARTIFACT_FILES = [
  "llm_input.md",
  "sidecar.json",
  "quality_report.json",
  "meta.json",
  "assets.json",
  "poster_ocr.json",
];

async function readJsonIfExists<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

async function collectLlmInputFiles(rootDir: string): Promise<string[]> {
  const collected: string[] = [];
  const pendingDirs = [rootDir];
  while (pendingDirs.length > 0) {
    const dir = pendingDirs.pop();
    if (!dir) {
      continue;
    }
    const relDir = relative(rootDir, dir);
    if (relDir && hasSensitivePathSegment(relDir)) {
      continue;
    }
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        pendingDirs.push(fullPath);
        continue;
      }
      if (entry.isFile() && entry.name === "llm_input.md") {
        collected.push(fullPath);
      }
    }
  }
  collected.sort((left, right) => left.localeCompare(right));
  return collected;
}

interface ArticleRef {
  llmInputPath: string;
  articleDir: string;
  relativeArticleDir: string;
}

interface IntakeManifestRow {
  artifact_dir?: unknown;
  llm_input_path?: unknown;
  relative_artifact_dir?: unknown;
  source_name?: unknown;
  source_kind?: unknown;
  verdict?: unknown;
}

function safePathPrefix(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    return "manifest";
  }
  const compact = value.trim().replace(/[^A-Za-z0-9._-]+/g, "_");
  return isSafePathSegment(compact) ? compact : "manifest";
}

function parseIntakeManifestRows(text: string): IntakeManifestRow[] {
  try {
    const parsed = JSON.parse(text) as unknown;
    if (isObject(parsed) && Array.isArray(parsed.rows)) {
      return parsed.rows.filter(isObject);
    }
    if (Array.isArray(parsed)) {
      return parsed.filter(isObject);
    }
  } catch {
    // Fall through to JSONL parsing.
  }
  const rows: IntakeManifestRow[] = [];
  for (const line of text.split(/\r?\n/g)) {
    const stripped = line.trim();
    if (!stripped) {
      continue;
    }
    try {
      const parsed = JSON.parse(stripped) as unknown;
      if (isObject(parsed)) {
        rows.push(parsed);
      }
    } catch {
      // Ignore malformed JSONL rows.
    }
  }
  return rows;
}

async function collectLlmArticleRefs(
  artifactRoot: string,
  intakeManifestPath?: string,
  intakeOnly = false,
): Promise<ArticleRef[]> {
  const baseRefs = intakeOnly
    ? []
    : (await collectLlmInputFiles(artifactRoot)).map((llmInputPath) => ({
        llmInputPath,
        articleDir: dirname(llmInputPath),
        relativeArticleDir: relative(artifactRoot, dirname(llmInputPath)),
      }));
  if (!intakeManifestPath) {
    return baseRefs;
  }

  const rows = parseIntakeManifestRows(await readFile(intakeManifestPath, "utf-8"));
  const refs: ArticleRef[] = [...baseRefs];
  const seen = new Set(baseRefs.map((ref) => resolve(ref.llmInputPath).toLowerCase()));
  for (const row of rows) {
    if (row.verdict === "blocked") {
      continue;
    }
    const articleDir =
      typeof row.artifact_dir === "string" ? resolve(row.artifact_dir) : "";
    const llmInputPath =
      typeof row.llm_input_path === "string" ? resolve(row.llm_input_path) : articleDir ? join(articleDir, "llm_input.md") : "";
    const relativeArtifactDir =
      typeof row.relative_artifact_dir === "string" ? row.relative_artifact_dir : "";
    if (!articleDir || !llmInputPath || !relativeArtifactDir) {
      continue;
    }
    const prefixedRelativeDir = join(
      safePathPrefix(row.source_name || row.source_kind),
      relativeArtifactDir,
    );
    if (hasSensitivePathSegment(prefixedRelativeDir)) {
      continue;
    }
    const key = resolve(llmInputPath).toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    refs.push({
      llmInputPath,
      articleDir,
      relativeArticleDir: prefixedRelativeDir,
    });
  }
  refs.sort((left, right) => left.relativeArticleDir.localeCompare(right.relativeArticleDir));
  return refs;
}

function countWarnings(
  sidecar: SidecarJson | null,
  qualityReport: QualityReportJson | null,
): number {
  return new Set([
    ...(sidecar?.warnings ?? []),
    ...(qualityReport?.warnings ?? []),
  ]).size;
}

export function determineFinalLlmQualityGrade(options: {
  llmInput: string;
  meta: MetaJson | null;
  sidecar: SidecarJson | null;
  qualityReport: QualityReportJson | null;
}): FinalLlmQualityGrade {
  const mainContentChars =
    options.sidecar?.main_content.trim().length || options.llmInput.trim().length;
  const sourceUrl = options.meta?.source_url || options.sidecar?.archive?.source_url || "";
  const title = options.meta?.title || options.sidecar?.archive?.title || "";
  if (!options.llmInput.trim() || mainContentChars < 20) {
    return "blocked";
  }
  if (!sourceUrl || !title || !options.sidecar) {
    return "review";
  }
  if (countWarnings(options.sidecar, options.qualityReport) > 0) {
    return "review";
  }
  return "ready";
}

function increment(counter: Record<string, number>, key: string): void {
  counter[key] = (counter[key] || 0) + 1;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isUnsafeFinalPackLink(value: unknown): boolean {
  if (!isObject(value)) {
    return false;
  }
  const href = typeof value.href === "string" ? value.href.trim().toLowerCase() : "";
  const text = typeof value.text === "string" ? value.text : "";
  return href.startsWith("javascript:") || isLlmShellLine(text);
}

function sanitizeFinalPackJson(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value
      .filter((item) => !isUnsafeFinalPackLink(item))
      .map((item) => sanitizeFinalPackJson(item));
  }
  if (!isObject(value)) {
    return value;
  }
  const sanitized: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(value)) {
    sanitized[key] = sanitizeFinalPackJson(child);
  }
  return sanitized;
}

async function copyKnownArtifacts(
  articleDir: string,
  outDir: string,
  copiedFileCounts: Record<string, number>,
): Promise<void> {
  await mkdir(outDir, { recursive: true });
  for (const fileName of COPY_ARTIFACT_FILES) {
    const sourcePath = join(articleDir, fileName);
    try {
      await stat(sourcePath);
    } catch {
      continue;
    }
    const targetPath = join(outDir, fileName);
    if (fileName === "assets.json") {
      const assets = await readJsonIfExists<unknown>(sourcePath);
      if (assets) {
        await writeJson(targetPath, sanitizeFinalPackJson(assets));
        increment(copiedFileCounts, fileName);
        continue;
      }
    }
    await copyFile(sourcePath, targetPath);
    increment(copiedFileCounts, fileName);
  }
}

function deriveSourceArchiveDir(
  sidecar: SidecarJson | null,
  archiveRoot: string,
  relativeArticleDir: string,
): string {
  if (!archiveRoot) {
    return "";
  }
  const account = sidecar?.archive?.account_key || relativeArticleDir.split(/[\\/]+/g)[0] || "";
  const token = sidecar?.archive?.token || relativeArticleDir.split(/[\\/]+/g).at(-1) || "";
  return toPortablePath(join(account, token));
}

async function computeArticleSize(articleDir: string): Promise<number> {
  let total = 0;
  for (const fileName of COPY_ARTIFACT_FILES) {
    try {
      const s = await stat(join(articleDir, fileName));
      total += s.size;
    } catch {
      // file missing
    }
  }
  return total;
}

interface PackState {
  packIndex: number;
  articlesDir: string;
  indexRows: FinalLlmPackIndexRecord[];
  qualityCounts: Record<FinalLlmQualityGrade, number>;
  copiedFileCounts: Record<string, number>;
  sizeBytes: number;
}

export async function finalizeLlmPack(
  options: FinalizeLlmPackOptions,
): Promise<FinalLlmPackManifest> {
  const artifactRoot = resolve(options.artifactRoot);
  const releaseRoot = resolve(options.releaseRoot);
  const archiveRoot = options.archiveRoot ? resolve(options.archiveRoot) : "";
  const manifestPath = options.manifestPath ? resolve(options.manifestPath) : "";
  const intakeManifestPath = options.intakeManifestPath
    ? resolve(options.intakeManifestPath)
    : "";
  const generatedAt = options.now ? options.now() : new Date().toISOString();
  const maxPackSizeBytes = options.maxPackSizeBytes;

  const collectedArticleRefs = await collectLlmArticleRefs(
    artifactRoot,
    intakeManifestPath,
    options.intakeOnly,
  );
  const maxArticles =
    typeof options.maxArticles === "number" && Number.isFinite(options.maxArticles)
      ? Math.max(0, Math.floor(options.maxArticles))
      : 0;
  const articleRefs =
    maxArticles > 0 ? collectedArticleRefs.slice(0, maxArticles) : collectedArticleRefs;

  // Global quality counts and file counts
  const globalQualityCounts: Record<FinalLlmQualityGrade, number> = {
    ready: 0,
    review: 0,
    blocked: 0,
  };
  const globalCopiedFileCounts: Record<string, number> = {};

  // If partitioning, collect article info first to compute sizes
  const articleInfos: Array<{
    llmInputPath: string;
    articleDir: string;
    relativeArticleDir: string;
    size: number;
    llmInput: string;
    meta: MetaJson | null;
    sidecar: SidecarJson | null;
    qualityReport: QualityReportJson | null;
    llmStat: { mtime: Date };
  }> = [];

  for (const ref of articleRefs) {
    const { llmInputPath, articleDir, relativeArticleDir } = ref;
    if (!relativeArticleDir || hasSensitivePathSegment(relativeArticleDir)) {
      continue;
    }

    const [llmInput, meta, sidecar, qualityReport, llmStat] = await Promise.all([
      readFile(llmInputPath, "utf-8"),
      readJsonIfExists<MetaJson>(join(articleDir, "meta.json")),
      readJsonIfExists<SidecarJson>(join(articleDir, "sidecar.json")),
      readJsonIfExists<QualityReportJson>(join(articleDir, "quality_report.json")),
      stat(llmInputPath),
    ]);

    const size = maxPackSizeBytes ? await computeArticleSize(articleDir) : 0;

    articleInfos.push({
      llmInputPath,
      articleDir,
      relativeArticleDir,
      size,
      llmInput,
      meta,
      sidecar,
      qualityReport,
      llmStat,
    });
  }

  // Build packs
  const packs: PackState[] = [];
  let currentPack: PackState | null = null;

  function getOrCreatePack(packIndex: number): PackState {
    return {
      packIndex,
      articlesDir: maxPackSizeBytes
        ? join(releaseRoot, `pack-${String(packIndex).padStart(3, "0")}`, "articles")
        : join(releaseRoot, "articles"),
      indexRows: [],
      qualityCounts: { ready: 0, review: 0, blocked: 0 },
      copiedFileCounts: {},
      sizeBytes: 0,
    };
  }

  for (const info of articleInfos) {
    // Check if we need a new pack
    if (
      maxPackSizeBytes &&
      currentPack &&
      currentPack.sizeBytes + info.size > maxPackSizeBytes &&
      currentPack.indexRows.length > 0
    ) {
      packs.push(currentPack);
      currentPack = getOrCreatePack(packs.length);
    }

    if (!currentPack) {
      currentPack = getOrCreatePack(0);
    }

    const outArticleDir = join(currentPack.articlesDir, info.relativeArticleDir);
    assertSafeRelativePath(releaseRoot, outArticleDir);
    const copiedBefore = { ...currentPack.copiedFileCounts };
    await copyKnownArtifacts(info.articleDir, outArticleDir, currentPack.copiedFileCounts);
    for (const [key, val] of Object.entries(currentPack.copiedFileCounts)) {
      globalCopiedFileCounts[key] =
        (globalCopiedFileCounts[key] || 0) + (val - (copiedBefore[key] || 0));
    }

    const grade = determineFinalLlmQualityGrade({
      llmInput: info.llmInput,
      meta: info.meta,
      sidecar: info.sidecar,
      qualityReport: info.qualityReport,
    });
    currentPack.qualityCounts[grade] += 1;
    globalQualityCounts[grade] += 1;

    const portableArticleDir = toPortablePath(info.relativeArticleDir);
    const packReleaseRoot = maxPackSizeBytes
      ? join(releaseRoot, `pack-${String(currentPack.packIndex).padStart(3, "0")}`)
      : releaseRoot;

    const record: FinalLlmPackIndexRecord = {
      account: info.sidecar?.archive?.account_key || info.meta?.account_name || "",
      token: info.sidecar?.archive?.token || portableArticleDir.split("/").at(-1) || "",
      title: info.meta?.title || info.sidecar?.archive?.title || "",
      source_url: info.meta?.source_url || info.sidecar?.archive?.source_url || "",
      post_date: info.meta?.publish_time_iso || info.meta?.publish_time_text || "",
      source_artifact_dir: portableArticleDir,
      source_archive_dir: deriveSourceArchiveDir(info.sidecar, archiveRoot, info.relativeArticleDir),
      markdown_path: toPortablePath(relative(packReleaseRoot, join(outArticleDir, "llm_input.md"))),
      sidecar_path: toPortablePath(relative(packReleaseRoot, join(outArticleDir, "sidecar.json"))),
      quality_report_path: toPortablePath(relative(packReleaseRoot, join(outArticleDir, "quality_report.json"))),
      quality_grade: grade,
      warning_count: countWarnings(info.sidecar, info.qualityReport),
      local_image_count: info.sidecar?.images.filter((image) => Boolean(image.local_path)).length || 0,
      main_content_chars: info.sidecar?.main_content.trim().length || info.llmInput.trim().length,
      background_recall_chars: info.sidecar?.background_recall.length || info.qualityReport?.background_recall_chars || 0,
      processed_at: info.llmStat.mtime.toISOString(),
    };
    currentPack.indexRows.push(record);
    currentPack.sizeBytes += info.size;
  }

  if (currentPack) {
    packs.push(currentPack);
  }

  // Write each pack's index and manifest
  const subPacks: import("./types.js").FinalLlmPackSubPack[] = [];

  for (const pack of packs) {
    const packReleaseRoot = maxPackSizeBytes
      ? join(releaseRoot, `pack-${String(pack.packIndex).padStart(3, "0")}`)
      : releaseRoot;
    const packIndexPath = join(packReleaseRoot, "index.jsonl");
    const packManifestPath = join(packReleaseRoot, "manifest.json");
    const packChecksumsPath = join(packReleaseRoot, "checksums.sha256");

    await ensureDir(pack.articlesDir);
    await writeText(
      packIndexPath,
      `${pack.indexRows.map((row) => JSON.stringify(row)).join("\n")}${pack.indexRows.length > 0 ? "\n" : ""}`,
    );

    const packManifest: FinalLlmPackManifest = {
      version: 1,
      generated_at: generatedAt,
      artifact_root: artifactRoot,
      release_root: packReleaseRoot,
      archive_root: archiveRoot,
      manifest_path: intakeManifestPath || manifestPath,
      total_articles: articleRefs.length,
      copied_articles: pack.indexRows.length,
      quality_counts: pack.qualityCounts,
      copied_file_counts: pack.copiedFileCounts,
      excluded: {
        sensitive_path_segments: [".mptext-data", "cookie", "auth", "token", "secret"],
        raw_archive_files: ["raw.html", "page.mhtml", "page.pdf", "article.url.txt"],
      },
      output_paths: {
        index_jsonl: packIndexPath,
        manifest_json: packManifestPath,
        articles_dir: pack.articlesDir,
        checksums_sha256: packChecksumsPath,
      },
    };
    await writeJson(packManifestPath, packManifest);
    await writeChecksumsFile(packReleaseRoot);

    if (maxPackSizeBytes) {
      subPacks.push({
        pack_index: pack.packIndex,
        articles_dir: pack.articlesDir,
        index_jsonl: packIndexPath,
        manifest_json: packManifestPath,
        article_count: pack.indexRows.length,
        size_bytes: pack.sizeBytes,
      });
    }
  }

  const mainArticlesDir = packs[0]?.articlesDir || join(releaseRoot, "articles");
  const mainIndexPath = packs[0]
    ? join(maxPackSizeBytes ? join(releaseRoot, `pack-${String(0).padStart(3, "0")}`) : releaseRoot, "index.jsonl")
    : join(releaseRoot, "index.jsonl");
  const mainManifestPath = join(releaseRoot, "manifest.json");
  const mainChecksumsPath = join(releaseRoot, "checksums.sha256");

  const allIndexRows = packs.flatMap((p) => p.indexRows);

  const manifest: FinalLlmPackManifest = {
    version: 1,
    generated_at: generatedAt,
    artifact_root: artifactRoot,
    release_root: releaseRoot,
    archive_root: archiveRoot,
    manifest_path: intakeManifestPath || manifestPath,
    total_articles: articleRefs.length,
    copied_articles: allIndexRows.length,
    quality_counts: globalQualityCounts,
    copied_file_counts: globalCopiedFileCounts,
    excluded: {
      sensitive_path_segments: [".mptext-data", "cookie", "auth", "token", "secret"],
      raw_archive_files: ["raw.html", "page.mhtml", "page.pdf", "article.url.txt"],
    },
    output_paths: {
      index_jsonl: mainIndexPath,
      manifest_json: mainManifestPath,
      articles_dir: mainArticlesDir,
      checksums_sha256: mainChecksumsPath,
    },
    partitioned: Boolean(maxPackSizeBytes),
    max_pack_size_bytes: maxPackSizeBytes,
    sub_packs: maxPackSizeBytes ? subPacks : undefined,
  };

  await writeJson(mainManifestPath, manifest);
  return manifest;
}
