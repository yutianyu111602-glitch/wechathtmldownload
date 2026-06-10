import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { basename, dirname, join } from "node:path";

import type {
  AssetsLocalJson,
  ArchiveMetaJson,
  PosterOcrResult,
} from "../archive/types.js";
import { buildLlmInputMdFromSidecar } from "../extract/buildLlmInputMd.js";
import { buildQualityReport, buildSidecar } from "../extract/buildSidecar.js";
import { cleanMarkitdownMarkdown } from "../extract/cleanMarkitdown.js";
import { extractAssets } from "../extract/extractAssets.js";
import { extractBody } from "../extract/extractBody.js";
import { extractFooterInfo } from "../extract/extractFooterInfo.js";
import { extractMeta } from "../extract/extractMeta.js";
import { parseHtml } from "../extract/parseHtml.js";
import type { ProcessProgressListener } from "../types.js";
import { ensureDir } from "../utils/fs.js";
import { convertWithMarkItDown } from "../utils/markitdown.js";
import { runPosterOcrFallback } from "../poster/runPosterOcrFallback.js";
import { writeDualTrackArtifacts } from "./writeDualTrackArtifacts.js";

interface ArchiveProcessDependencies {
  convertHtmlToMarkdown?: (inputPath: string, signal?: AbortSignal) => Promise<string>;
  runPosterOcr?: (
    options: { bundleDir: string; mainText: string; localAssets: AssetsLocalJson | null },
  ) => Promise<PosterOcrResult>;
}

const TOTAL_STEPS = 5;

async function emitProgress(
  listener: ProcessProgressListener | undefined,
  inputPath: string,
  phase: "parse_html" | "rule_extract" | "markitdown_convert" | "markdown_clean" | "write_outputs",
  step: number,
  message: string,
): Promise<void> {
  await listener?.({
    phase,
    step,
    totalSteps: TOTAL_STEPS,
    inputPath,
    message,
  });
}

async function readOptionalJson<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

export async function processArchiveBundleDualTrack(
  bundleDir: string,
  outDir: string,
  onProgress?: ProcessProgressListener,
  signal?: AbortSignal,
  dependencies: ArchiveProcessDependencies = {},
): Promise<void> {
  await ensureDir(outDir);
  
  let inputPath: string;
  let actualBundleDir: string;
  
  if (existsSync(join(bundleDir, "raw.html"))) {
    actualBundleDir = bundleDir;
    inputPath = join(bundleDir, "raw.html");
  } else if (bundleDir.endsWith("raw.html")) {
    actualBundleDir = dirname(bundleDir);
    inputPath = bundleDir;
  } else {
    throw new Error(`Cannot find raw.html in bundle directory: ${bundleDir}`);
  }
  
  await emitProgress(onProgress, actualBundleDir, "parse_html", 1, "Loading archive bundle");
  const { rawHtml, $ } = await parseHtml(inputPath);

  await emitProgress(
    onProgress,
    actualBundleDir,
    "rule_extract",
    2,
    "Extracting archive metadata and assets",
  );
  const body = extractBody($);
  const footerInfo = extractFooterInfo(body.body_blocks);
  const meta = extractMeta($, rawHtml, body.body_text);
  const assets = extractAssets($, meta.source_url);
  const archiveMeta = await readOptionalJson<ArchiveMetaJson>(join(actualBundleDir, "archive_meta.json"));
  const localAssets = await readOptionalJson<AssetsLocalJson>(join(actualBundleDir, "assets_local.json"));

  await emitProgress(
    onProgress,
    actualBundleDir,
    "markitdown_convert",
    3,
    "Converting archive HTML to markdown",
  );
  const convertHtmlToMarkdown = dependencies.convertHtmlToMarkdown || convertWithMarkItDown;
  const markitdownRawMd = await convertHtmlToMarkdown(inputPath, signal);
  await emitProgress(
    onProgress,
    actualBundleDir,
    "markdown_clean",
    4,
    "Building stronger sidecar and poster fallback",
  );
  const cleanedMarkitdown = cleanMarkitdownMarkdown(markitdownRawMd, meta);

  const runPosterOcr =
    dependencies.runPosterOcr ||
    ((options: { bundleDir: string; mainText: string; localAssets: AssetsLocalJson | null }) =>
      runPosterOcrFallback(options));
  const posterOcr = await runPosterOcr({
    bundleDir: actualBundleDir,
    mainText: cleanedMarkitdown.markdown || body.body_text,
    localAssets,
  });

  const sidecar = buildSidecar({
    inputMode: "archive",
    meta,
    archiveMeta,
    footerInfo,
    bodyText: body.body_text,
    mainMarkdown: cleanedMarkitdown.markdown || body.body_text,
    assets,
    localAssets,
    posterOcr,
    warnings: body.warnings,
  });
  const qualityReport = buildQualityReport(sidecar);
  const llmInputMd = buildLlmInputMdFromSidecar(sidecar);

  await emitProgress(
    onProgress,
    actualBundleDir,
    "write_outputs",
    5,
    "Writing archive-aware artifacts",
  );
  await writeDualTrackArtifacts({
    outDir,
    meta,
    assets,
    ruleExtract: {
      body_text: body.body_text,
      body_blocks: body.body_blocks,
      footer_info: sidecar.footer_info,
      warnings: body.warnings,
    },
    cleanMd: sidecar.main_content,
    markitdownRawMd,
    markitdownCleanedMd: cleanedMarkitdown.markdown,
    markitdownWarnings: cleanedMarkitdown.warnings,
    sidecar,
    qualityReport,
    llmInputMd,
    posterOcr,
    articleId: basename(actualBundleDir),
    inputPath: actualBundleDir,
  });
}
