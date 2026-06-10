const SIMPLE_DATE_PATTERNS = [
  /\d{4}[./-]\d{1,2}[./-]\d{1,2}/g,
  /\d{4}年\d{1,2}月\d{1,2}日/g,
];

const SIMPLE_DATE_TO_ISO_PATTERNS = [
  /(\d{4})[./-](\d{1,2})[./-](\d{1,2})/,
  /(\d{4})年(\d{1,2})月(\d{1,2})日/,
];

function pad(value: string): string {
  return value.padStart(2, "0");
}

export function collectDateTexts(value: string): string[] {
  const unique = new Set<string>();

  for (const pattern of SIMPLE_DATE_PATTERNS) {
    for (const match of value.match(pattern) ?? []) {
      unique.add(match.trim());
    }
  }

  return [...unique];
}

export function parseSimpleDateToIso(value: string): string {
  for (const pattern of SIMPLE_DATE_TO_ISO_PATTERNS) {
    const match = value.match(pattern);
    if (match) {
      const [, year, month, day] = match;
      return `${year}-${pad(month)}-${pad(day)}`;
    }
  }

  return "";
}
