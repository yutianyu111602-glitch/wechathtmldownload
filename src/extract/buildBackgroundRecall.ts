function normalizeCompareText(value: string): string {
  return value.replace(/\s+/g, "").trim().toLowerCase();
}

function splitParagraphs(value: string): string[] {
  return value
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function buildBackgroundRecall(options: {
  mainContent: string;
  bodyText: string;
  excludedValues?: string[];
  maxParagraphs?: number;
  maxChars?: number;
}): string {
  const maxParagraphs = options.maxParagraphs ?? 12;
  const maxChars = options.maxChars ?? 1600;
  const seen = new Set(
    splitParagraphs(options.mainContent)
      .map((part) => normalizeCompareText(part))
      .filter(Boolean),
  );

  for (const value of options.excludedValues ?? []) {
    const normalized = normalizeCompareText(value);
    if (normalized) {
      seen.add(normalized);
    }
  }

  const selected: string[] = [];
  let totalChars = 0;
  for (const part of splitParagraphs(options.bodyText)) {
    const normalized = normalizeCompareText(part);
    if (!normalized || seen.has(normalized) || part.length < 8) {
      continue;
    }

    const projected = totalChars + part.length + (selected.length > 0 ? 2 : 0);
    if (projected > maxChars) {
      break;
    }

    selected.push(part);
    seen.add(normalized);
    totalChars = projected;
    if (selected.length >= maxParagraphs) {
      break;
    }
  }

  return selected.join("\n\n");
}
