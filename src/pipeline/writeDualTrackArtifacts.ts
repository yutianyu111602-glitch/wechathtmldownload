import { basename, join } from "node:path";

import { buildLlmInputMdFromSidecar } from "../extract/buildLlmInputMd.js";
import type { buildQualityReport } from "../extract/buildSidecar.js";
import type { cleanMarkitdownMarkdown } from "../extract/cleanMarkitdown.js";
import type { PosterOcrResult } from "../archive/types.js";
import type { ProcessArticleDualTrackResult } from "../types.js";
import { ensureDir, writeJson, writeText } from "../utils/fs.js";
import { writeArtifactManifest } from "./artifactManifest.js";

export interface WriteDualTrackArtifactsOptions {
  outDir: string;
  meta: ProcessArticleDualTrackResult["meta"];
  assets: ProcessArticleDualTrackResult["assets"];
  ruleExtract: ProcessArticleDualTrackResult["ruleExtract"];
  cleanMd: string;
  markitdownRawMd: string;
  markitdownCleanedMd: string;
  markitdownWarnings: string[];
  sidecar: Parameters<typeof buildQualityReport>[0];
  qualityReport: ReturnType<typeof buildQualityReport>;
  llmInputMd: string;
  posterOcr: PosterOcrResult;
  articleId?: string;
  inputPath?: string;
}

export async function writeDualTrackArtifacts(
  options: WriteDualTrackArtifactsOptions,
): Promise<void> {
  const { outDir } = options;
  await ensureDir(outDir);

  await writeJson(join(outDir, "meta.json"), options.meta);
  await writeJson(join(outDir, "assets.json"), options.assets);
  await writeJson(join(outDir, "rule_extract.json"), options.ruleExtract);
  await writeText(join(outDir, "clean.md"), options.cleanMd);
  await writeText(join(outDir, "markitdown.raw.md"), options.markitdownRawMd);
  await writeText(
    join(outDir, "markitdown.cleaned.md"),
    options.markitdownCleanedMd,
  );
  await writeText(
    join(outDir, "background_recall.md"),
    `${options.sidecar.background_recall}\n`,
  );
  await writeJson(join(outDir, "sidecar.json"), options.sidecar);
  await writeText(
    join(outDir, "sidecar.md"),
    buildLlmInputMdFromSidecar(options.sidecar),
  );
  await writeText(join(outDir, "llm_input.md"), options.llmInputMd);
  await writeJson(join(outDir, "quality_report.json"), options.qualityReport);
  await writeJson(join(outDir, "poster_ocr.json"), options.posterOcr);
  await writeJson(
    join(outDir, "markitdown_warnings.json"),
    options.markitdownWarnings,
  );

  if (options.articleId && options.inputPath) {
    await writeArtifactManifest({
      outDir,
      articleId: options.articleId,
      inputPath: options.inputPath,
    });
  }
}
