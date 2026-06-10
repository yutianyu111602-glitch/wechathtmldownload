import { readFile } from "node:fs/promises";

import { load, type CheerioAPI } from "cheerio";

export interface ParsedHtml {
  rawHtml: string;
  $: CheerioAPI;
}

export async function parseHtml(filePath: string): Promise<ParsedHtml> {
  let rawHtml: string;
  try {
    rawHtml = await readFile(filePath, "utf-8");
  } catch (error) {
    throw new Error(`Failed to read HTML file at ${filePath}: ${error}`);
  }
  return {
    rawHtml,
    $: load(rawHtml),
  };
}
