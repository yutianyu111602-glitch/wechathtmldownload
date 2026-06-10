export interface ArticleHtmlQuality {
  hasArticleRoot: boolean;
  hasContentContainer: boolean;
  visibleTextLength: number;
  imageCount: number;
  valid: boolean;
  warnings: string[];
}

function stripNonTextHtml(rawHtml: string): string {
  return rawHtml
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<svg[\s\S]*?<\/svg>/gi, "");
}

function visibleTextLength(rawHtml: string): number {
  const text = stripNonTextHtml(rawHtml)
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&#160;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return text.length;
}

export function analyzeArticleHtmlQuality(rawHtml: string): ArticleHtmlQuality {
  const hasArticleRoot =
    /id=["']js_article["']/.test(rawHtml) ||
    /id=["']js_content["']/.test(rawHtml);
  const hasContentContainer =
    /id=["']js_content["']/.test(rawHtml) ||
    /id=["']page-content["']/.test(rawHtml) ||
    /class=["'][^"']*rich_media_content/.test(rawHtml);
  const imageCount = (rawHtml.match(/<img\b/gi) || []).length;
  const textLength = visibleTextLength(rawHtml);
  const valid =
    hasArticleRoot &&
    hasContentContainer &&
    (textLength >= 80 || imageCount > 0);
  const warnings = [
    hasArticleRoot ? "" : "article html missing #js_article/#js_content",
    hasContentContainer ? "" : "article html missing content container",
    textLength >= 80 || imageCount > 0
      ? ""
      : "article html has no meaningful text or images",
  ].filter(Boolean);

  return {
    hasArticleRoot,
    hasContentContainer,
    visibleTextLength: textLength,
    imageCount,
    valid,
    warnings,
  };
}

export function isValidArticleHtml(rawHtml: string): boolean {
  return analyzeArticleHtmlQuality(rawHtml).valid;
}
