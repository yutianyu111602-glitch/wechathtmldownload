import type { MetaJson } from "../types.js";

const NOISE_LINES = new Set([
  "在小说阅读器读本章",
  "去阅读",
  "在小说阅读器中沉浸阅读",
  "阅读全文",
]);

const TAIL_SHELL_START_LINES = new Set([
  "预览时标签不可点",
  "关注该公众号",
  "继续滑动看下一个",
  "轻触阅读原文",
  "向上滑动看下一个",
  "微信扫一扫可打开此内容，",
]);

const TOP_SECTION_SCAN_LIMIT = 8;

function isMarkdownImageLine(line: string): boolean {
  return /^!\[[^\]]*\]\([^)]*\)$/.test(line.trim());
}

function hasEmptyImageTarget(line: string): boolean {
  return /^!\[[^\]]*\]\(\s*\)$/.test(line.trim());
}

function buildImagePlaceholder(count: number): string {
  return count <= 1 ? "[图片]" : `[图片 x${count}]`;
}

export interface CleanMarkitdownResult {
  markdown: string;
  warnings: string[];
  removedLineCount: number;
}

export function cleanMarkitdownMarkdown(
  markdown: string,
  meta: MetaJson,
): CleanMarkitdownResult {
  const warnings: string[] = [];
  const kept: string[] = [];
  const topMetaLines = new Set(
    [
      meta.title,
      meta.account_name,
      meta.author_display,
      `# ${meta.title}`,
      "原创",
    ].filter(Boolean),
  );
  let keptNonEmptyCount = 0;
  let removedLineCount = 0;
  let inTailShell = false;
  let pendingImageCount = 0;

  const flushPendingImages = () => {
    if (pendingImageCount <= 0) {
      return;
    }

    const placeholder = buildImagePlaceholder(pendingImageCount);
    if (kept.length > 0 && kept[kept.length - 1] !== "") {
      kept.push("");
    }
    kept.push(placeholder);
    kept.push("");
    keptNonEmptyCount += 1;
    warnings.push(`image_block_collapsed:${pendingImageCount}`);
    pendingImageCount = 0;
  };

  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();

    if (!line) {
      if (pendingImageCount > 0) {
        continue;
      }
      if (kept.length > 0 && kept[kept.length - 1] !== "") {
        kept.push("");
      }
      continue;
    }

    let removeReason = "";

    if (inTailShell) {
      removeReason = "tail_shell_noise";
    } else if (TAIL_SHELL_START_LINES.has(line)) {
      inTailShell = true;
      removeReason = "tail_shell_start";
    } else if (keptNonEmptyCount === 0 && isMarkdownImageLine(line)) {
      removeReason = "top_cover_image";
    } else if (NOISE_LINES.has(line)) {
      removeReason = "reader_shell_noise";
    } else if (hasEmptyImageTarget(line)) {
      removeReason = "empty_image_marker";
    } else if (
      keptNonEmptyCount < TOP_SECTION_SCAN_LIMIT &&
      topMetaLines.has(line)
    ) {
      removeReason = "top_metadata_duplicate";
    } else if (kept.length > 0 && kept[kept.length - 1].trim() === line) {
      removeReason = "duplicate_line";
    }

    if (removeReason) {
      removedLineCount += 1;
      warnings.push(`${removeReason}:${line}`);
      continue;
    }

    if (isMarkdownImageLine(line)) {
      pendingImageCount += 1;
      removedLineCount += 1;
      continue;
    }

    flushPendingImages();

    kept.push(rawLine.trimEnd());
    keptNonEmptyCount += 1;
  }

  flushPendingImages();

  while (kept[0] === "") {
    kept.shift();
  }
  while (kept[kept.length - 1] === "") {
    kept.pop();
  }

  const cleaned = kept
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return {
    markdown: cleaned ? `${cleaned}\n` : "",
    warnings: [...new Set(warnings)],
    removedLineCount,
  };
}
