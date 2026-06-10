import { createReadStream } from "node:fs";
import { mkdir, open } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { createInterface } from "node:readline/promises";

import type { ArchiveAuditItem } from "../artifacts/types.js";
import { normalizeArticleToken } from "./normalizeArticleToken.js";
import type { ArchiveQueueRecord } from "./types.js";

export interface FilterDajialaRepairCandidatesOptions {
  auditItemsPath: string;
  outPath: string;
  requireSignedLongLink?: boolean;
  now?: () => string;
}

export interface FilterDajialaRepairCandidatesSummary {
  audit_items_path: string;
  out_path: string;
  require_signed_long_link: boolean;
  total_items: number;
  retry_candidates: number;
  signed_legacy_candidates: number;
  written_count: number;
  skipped_archived: number;
  skipped_unsigned: number;
}

export function isSignedLegacyAppmsgUrl(sourceUrl: string): boolean {
  try {
    const url = new URL(sourceUrl);
    return (
      url.hostname === "mp.weixin.qq.com" &&
      url.pathname === "/mp/appmsg/show" &&
      Boolean(url.searchParams.get("__biz")) &&
      Boolean(url.searchParams.get("appmsgid")) &&
      Boolean(url.searchParams.get("itemidx")) &&
      Boolean(url.searchParams.get("sign"))
    );
  } catch {
    return false;
  }
}

function shouldRetryWithDajiala(item: ArchiveAuditItem): boolean {
  return (
    item.retry ||
    item.status === "partial" ||
    item.status === "failed" ||
    item.status === "missing"
  );
}

function toArchiveQueueRecord(
  item: ArchiveAuditItem,
  discoveredAt: string,
): ArchiveQueueRecord {
  return {
    account_key: item.account_key,
    token: normalizeArticleToken(item.source_url),
    source_url: item.source_url,
    title: item.title || "",
    author: "",
    cover_url: "",
    post_time: "",
    post_date: "",
    page: 0,
    discovered_at: discoveredAt,
    discovery_source: "audit-dajiala-filter",
  };
}

export async function filterDajialaRepairCandidates(
  options: FilterDajialaRepairCandidatesOptions,
): Promise<FilterDajialaRepairCandidatesSummary> {
  const auditItemsPath = resolve(options.auditItemsPath);
  const outPath = resolve(options.outPath);
  const requireSignedLongLink = Boolean(options.requireSignedLongLink);
  const discoveredAt = options.now ? options.now() : new Date().toISOString();
  const summary: FilterDajialaRepairCandidatesSummary = {
    audit_items_path: auditItemsPath,
    out_path: outPath,
    require_signed_long_link: requireSignedLongLink,
    total_items: 0,
    retry_candidates: 0,
    signed_legacy_candidates: 0,
    written_count: 0,
    skipped_archived: 0,
    skipped_unsigned: 0,
  };

  await mkdir(dirname(outPath), { recursive: true });
  const writer = await open(outPath, "w");
  try {
    const lines = createInterface({
      input: createReadStream(auditItemsPath, { encoding: "utf8" }),
      crlfDelay: Infinity,
    });
    for await (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      summary.total_items += 1;
      const item = JSON.parse(trimmed) as ArchiveAuditItem;
      if (item.status === "archived") {
        summary.skipped_archived += 1;
        continue;
      }
      if (!shouldRetryWithDajiala(item)) {
        continue;
      }
      summary.retry_candidates += 1;
      const signedLegacy = isSignedLegacyAppmsgUrl(item.source_url);
      if (signedLegacy) {
        summary.signed_legacy_candidates += 1;
      }
      if (requireSignedLongLink && !signedLegacy) {
        summary.skipped_unsigned += 1;
        continue;
      }
      await writer.write(
        `${JSON.stringify(toArchiveQueueRecord(item, discoveredAt))}\n`,
      );
      summary.written_count += 1;
    }
  } finally {
    await writer.close();
  }

  return summary;
}
