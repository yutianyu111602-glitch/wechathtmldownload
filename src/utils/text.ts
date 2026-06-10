const INLINE_SPACE_RE = /[ \t\u00A0]+/g;
const BLANK_LINE_RE = /\n{3,}/g;

export function cleanInlineText(value: string): string {
  return value.replace(/\r/g, "").replace(INLINE_SPACE_RE, " ").trim();
}

export function normalizeTextBlock(value: string): string {
  const normalized = value
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => cleanInlineText(line))
    .join("\n");

  return normalized.replace(BLANK_LINE_RE, "\n\n").trim();
}

export function splitCleanLines(value: string): string[] {
  const text = normalizeTextBlock(value);
  return text
    ? text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
    : [];
}

export function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}
