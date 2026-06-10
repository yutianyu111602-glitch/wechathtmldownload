import type { Cheerio, CheerioAPI } from "cheerio";

import { cleanInlineText } from "./text.js";

export function firstText($: CheerioAPI, selectors: string[]): string {
  for (const selector of selectors) {
    const value = cleanInlineText($(selector).first().text());
    if (value) {
      return value;
    }
  }

  return "";
}

export function firstAttr(
  $: CheerioAPI,
  selectors: Array<{ selector: string; attr: string }>,
): string {
  for (const { selector, attr } of selectors) {
    const value = cleanInlineText($(selector).first().attr(attr) ?? "");
    if (value) {
      return value;
    }
  }

  return "";
}

export function stripUrlFragment(value: string): string {
  return cleanInlineText(value).split("#")[0]?.trim() ?? "";
}

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

export function getAttr($node: Cheerio<any>, names: string[]): string {
  for (const name of names) {
    const value = cleanInlineText(String($node.attr(name) ?? ""));
    if (value) {
      return value;
    }
  }

  return "";
}

export function extractVideoId(value: string): string {
  const trimmed = cleanInlineText(value);
  const matched =
    trimmed.match(/[?&]vid=([^&#]+)/i) ??
    trimmed.match(/\bvid=['"]?([A-Za-z0-9_-]+)/i);
  return matched?.[1] ?? "";
}
