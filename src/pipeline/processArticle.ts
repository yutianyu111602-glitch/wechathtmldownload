import { join } from "node:path";

import { buildCleanMd } from "../extract/buildCleanMd.js";
import { extractAssets } from "../extract/extractAssets.js";
import { extractBody } from "../extract/extractBody.js";
import { extractFooterInfo } from "../extract/extractFooterInfo.js";
import { extractMeta } from "../extract/extractMeta.js";
import { parseHtml } from "../extract/parseHtml.js";
import type { ProcessArticleResult } from "../types.js";
import { ensureDir, writeJson, writeText } from "../utils/fs.js";

export async function processArticle(
  inputPath: string,
  outDir: string,
): Promise<ProcessArticleResult> {
  const { rawHtml, $ } = await parseHtml(inputPath);
  const body = extractBody($);
  const footerInfo = extractFooterInfo(body.body_blocks);
  const meta = extractMeta($, rawHtml, body.body_text);
  const assets = extractAssets($, meta.source_url);
  const cleanMd = buildCleanMd(meta, footerInfo, body.body_text, assets);

  const result: ProcessArticleResult = {
    meta,
    assets,
    ruleExtract: {
      body_text: body.body_text,
      body_blocks: body.body_blocks,
      footer_info: footerInfo,
      warnings: body.warnings,
    },
    cleanMd,
  };

  await ensureDir(outDir);
  await writeJson(join(outDir, "meta.json"), result.meta);
  await writeJson(join(outDir, "assets.json"), result.assets);
  await writeJson(join(outDir, "rule_extract.json"), result.ruleExtract);
  await writeText(join(outDir, "clean.md"), result.cleanMd);

  return result;
}
