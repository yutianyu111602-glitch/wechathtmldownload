import { basename } from "node:path";
import type { PosterOcrResult } from "../archive/types.js";
import { buildCleanMd } from "../extract/buildCleanMd.js";
import {
  buildLlmInputMd,
  buildLlmInputMdFromSidecar,
} from "../extract/buildLlmInputMd.js";
import { buildQualityReport, buildSidecar } from "../extract/buildSidecar.js";
import { cleanMarkitdownMarkdown } from "../extract/cleanMarkitdown.js";
import { extractAssets } from "../extract/extractAssets.js";
import { extractBody } from "../extract/extractBody.js";
import { extractFooterInfo } from "../extract/extractFooterInfo.js";
import { extractMeta } from "../extract/extractMeta.js";
import { parseHtml } from "../extract/parseHtml.js";
import type {
  ProcessArticleDualTrackResult,
  ProcessProgressEvent,
  ProcessProgressListener,
} from "../types.js";
import { throwIfAborted } from "../utils/abort.js";
import { ensureDir } from "../utils/fs.js";
import { convertWithMarkItDown } from "../utils/markitdown.js";
import { writeDualTrackArtifacts } from "./writeDualTrackArtifacts.js";

const TOTAL_STEPS = 5;

async function emitProgress(
  listener: ProcessProgressListener | undefined,
  inputPath: string,
  phase: ProcessProgressEvent["phase"],
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

export async function processArticleDualTrack(
  inputPath: string,
  outDir: string,
  onProgress?: ProcessProgressListener,
  signal?: AbortSignal,
): Promise<ProcessArticleDualTrackResult> {
  throwIfAborted(signal);
  await ensureDir(outDir);

  await emitProgress(
    onProgress,
    inputPath,
    "parse_html",
    1,
    "Loading raw HTML",
  );
  const { rawHtml, $ } = await parseHtml(inputPath);
  throwIfAborted(signal);

  await emitProgress(
    onProgress,
    inputPath,
    "rule_extract",
    2,
    "Extracting deterministic fields and clean markdown",
  );
  const body = extractBody($);
  const footerInfo = extractFooterInfo(body.body_blocks);
  const meta = extractMeta($, rawHtml, body.body_text);
  const assets = extractAssets($, meta.source_url);
  const cleanMd = buildCleanMd(meta, footerInfo, body.body_text, assets);
  throwIfAborted(signal);

  await emitProgress(
    onProgress,
    inputPath,
    "markitdown_convert",
    3,
    "Converting HTML with MarkItDown",
  );
  const markitdownRawMd = await convertWithMarkItDown(inputPath, signal);
  throwIfAborted(signal);

  await emitProgress(
    onProgress,
    inputPath,
    "markdown_clean",
    4,
    "Cleaning MarkItDown output for LLM use",
  );
  const cleanedMarkitdown = cleanMarkitdownMarkdown(markitdownRawMd, meta);
  const fallbackLlmInputMd = buildLlmInputMd(
    meta,
    footerInfo,
    cleanedMarkitdown.markdown || body.body_text,
    assets,
  );
  const posterOcr: PosterOcrResult = {
    imageHeavy: false,
    candidates: [],
    recovered: {},
    warnings: [],
  };
  const sidecar = buildSidecar({
    inputMode: "html",
    meta,
    footerInfo,
    bodyText: body.body_text,
    mainMarkdown: cleanedMarkitdown.markdown || body.body_text,
    assets,
    localAssets: null,
    posterOcr,
    warnings: body.warnings,
  });
  const llmInputMd = buildLlmInputMdFromSidecar(sidecar) || fallbackLlmInputMd;
  const qualityReport = buildQualityReport(sidecar);
  throwIfAborted(signal);

  const result: ProcessArticleDualTrackResult = {
    meta,
    assets,
    ruleExtract: {
      body_text: body.body_text,
      body_blocks: body.body_blocks,
      footer_info: footerInfo,
      warnings: body.warnings,
    },
    cleanMd,
    dualTrack: {
      markitdownRawMd,
      markitdownCleanedMd: cleanedMarkitdown.markdown,
      llmInputMd,
      markitdownWarnings: cleanedMarkitdown.warnings,
    },
  };

  await emitProgress(
    onProgress,
    inputPath,
    "write_outputs",
    5,
    "Writing rule outputs and markdown artifacts",
  );
  throwIfAborted(signal);
  await writeDualTrackArtifacts({
    outDir,
    meta: result.meta,
    assets: result.assets,
    ruleExtract: result.ruleExtract,
    cleanMd: result.cleanMd,
    markitdownRawMd: result.dualTrack.markitdownRawMd,
    markitdownCleanedMd: result.dualTrack.markitdownCleanedMd,
    markitdownWarnings: result.dualTrack.markitdownWarnings,
    sidecar,
    qualityReport,
    llmInputMd: result.dualTrack.llmInputMd,
    posterOcr,
    articleId: basename(inputPath),
    inputPath,
  });

  return result;
}
