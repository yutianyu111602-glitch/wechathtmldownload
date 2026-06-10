import { createReadStream } from "node:fs";
import { mkdir, open, readFile, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline/promises";

import {
  analyzeArticleHtmlQuality,
  type ArticleHtmlQuality,
} from "../archive/articleHtmlQuality.js";
import type {
  ArchiveMetaJson,
  ArchiveQueueRecord,
  AssetsLocalJson,
} from "../archive/types.js";
import { ensureDir, writeJson } from "../utils/fs.js";
import { readJsonlFile } from "../utils/jsonl.js";
import { assertSafeRelativePath, isSafePathSegment } from "./pathSafety.js";
import type {
  ArchiveAuditAccountSummary,
  ArchiveAuditIssue,
  ArchiveAuditItem,
  ArchiveAuditItemStatus,
  ArchiveAuditSummary,
} from "./types.js";

export interface RunArchiveAuditOptions {
  manifestPath: string;
  archiveRoot: string;
  outDir: string;
  resultLogPath?: string;
  now?: () => string;
}

interface ResultLogRecord {
  token?: string;
  account_key?: string;
  status?: string;
  message?: string;
  error_message?: string;
}

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await stat(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readJsonIfExists<T>(filePath: string): Promise<{
  exists: boolean;
  value: T | null;
}> {
  try {
    return {
      exists: true,
      value: JSON.parse(await readFile(filePath, "utf-8")) as T,
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { exists: false, value: null };
    }
    return { exists: true, value: null };
  }
}

async function readResultLog(resultLogPath: string | undefined): Promise<Map<string, ResultLogRecord>> {
  const records = new Map<string, ResultLogRecord>();
  if (!resultLogPath) {
    return records;
  }

  try {
    const rl = createInterface({
      input: createReadStream(resultLogPath, { encoding: "utf8" }),
      crlfDelay: Infinity,
    });
    for await (const line of rl) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      const record = JSON.parse(trimmed) as ResultLogRecord;
      if (record.account_key && record.token) {
        records.set(`${record.account_key}\n${record.token}`, record);
      }
    }
  } catch {
    return records;
  }
  return records;
}

function addIssue(issues: ArchiveAuditIssue[], issue: ArchiveAuditIssue): void {
  if (!issues.includes(issue)) {
    issues.push(issue);
  }
}

function increment(counter: Record<string, number>, key: string): void {
  counter[key] = (counter[key] || 0) + 1;
}

function latestError(items: ArchiveAuditItem[]): string {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item?.error_message) {
      return item.error_message;
    }
  }
  return "";
}

function determineStatus(
  meta: ArchiveMetaJson | null,
  htmlQuality: ArticleHtmlQuality | null,
  bundleExists: boolean,
  rawHtmlExists: boolean,
  unsafePath: boolean,
): ArchiveAuditItemStatus {
  if (unsafePath) {
    return "unsafe_path";
  }
  if (!bundleExists || !rawHtmlExists) {
    return "missing";
  }
  if (!meta) {
    return htmlQuality?.valid ? "partial" : "missing";
  }
  if (meta.status === "archived" && htmlQuality?.valid) {
    return "archived";
  }
  return meta.status;
}

async function writeJsonl(
  filePath: string,
  rows: Iterable<unknown>,
): Promise<void> {
  await mkdir(dirname(filePath), { recursive: true });
  const writer = await open(filePath, "w");
  try {
    for (const row of rows) {
      await writer.write(`${JSON.stringify(row)}\n`);
    }
  } finally {
    await writer.close();
  }
}

export async function runArchiveAudit(
  options: RunArchiveAuditOptions,
): Promise<ArchiveAuditSummary> {
  const manifestPath = resolve(options.manifestPath);
  const archiveRoot = resolve(options.archiveRoot);
  const outDir = resolve(options.outDir);
  await ensureDir(outDir);

  const records = await readJsonlFile<ArchiveQueueRecord>(manifestPath);
  const generatedAt = options.now ? options.now() : new Date().toISOString();
  const resultLog = await readResultLog(
    options.resultLogPath ? resolve(options.resultLogPath) : undefined,
  );

  const tokenCounts = new Map<string, number>();
  for (const record of records) {
    tokenCounts.set(record.token, (tokenCounts.get(record.token) || 0) + 1);
  }

  const items: ArchiveAuditItem[] = [];
  const accountSummaries = new Map<string, ArchiveAuditAccountSummary>();
  const statusCounts: Record<string, number> = {};
  const issueCounts: Record<string, number> = {};
  const retryRecords: ArchiveQueueRecord[] = [];

  for (const record of records) {
    const issues: ArchiveAuditIssue[] = [];
    const warnings: string[] = [];
    const duplicateTokenCount = tokenCounts.get(record.token) || 0;
    const accountKeyIsSafe = isSafePathSegment(record.account_key);
    const tokenIsSafe = isSafePathSegment(record.token);
    if (duplicateTokenCount > 1) {
      addIssue(issues, "duplicate_token");
    }
    if (!accountKeyIsSafe) {
      addIssue(issues, "unsafe_account_key");
    }
    if (!tokenIsSafe) {
      addIssue(issues, "unsafe_token");
    }

    const unsafePath = !accountKeyIsSafe || !tokenIsSafe;
    const bundleDir = unsafePath
      ? ""
      : join(archiveRoot, record.account_key, record.token);

    let bundleExists = false;
    let rawHtmlExists = false;
    let rawHtmlBytes = 0;
    let htmlQuality: ArticleHtmlQuality | null = null;
    let archiveMetaExists = false;
    let archiveMeta: ArchiveMetaJson | null = null;
    let assetsLocalExists = false;
    let localImageCount = 0;
    let localMediaCount = 0;
    let pageMhtmlExists = false;
    let pagePdfExists = false;

    if (!unsafePath) {
      assertSafeRelativePath(archiveRoot, bundleDir);
      bundleExists = await pathExists(bundleDir);
      if (!bundleExists) {
        addIssue(issues, "missing_bundle");
      }

      const rawHtmlPath = join(bundleDir, "raw.html");
      try {
        const rawHtml = await readFile(rawHtmlPath, "utf-8");
        rawHtmlExists = true;
        rawHtmlBytes = Buffer.byteLength(rawHtml, "utf-8");
        if (rawHtml.trim().length === 0) {
          addIssue(issues, "empty_raw_html");
        }
        htmlQuality = analyzeArticleHtmlQuality(rawHtml);
        if (!htmlQuality.valid) {
          addIssue(issues, "invalid_raw_html");
          warnings.push(...htmlQuality.warnings);
        }
      } catch {
        addIssue(issues, "missing_raw_html");
      }

      const metaRead = await readJsonIfExists<ArchiveMetaJson>(
        join(bundleDir, "archive_meta.json"),
      );
      archiveMetaExists = metaRead.exists;
      archiveMeta = metaRead.value;
      if (!archiveMetaExists) {
        addIssue(issues, "missing_archive_meta");
      } else if (!archiveMeta) {
        addIssue(issues, "invalid_archive_meta_json");
      }

      const assetsRead = await readJsonIfExists<AssetsLocalJson>(
        join(bundleDir, "assets_local.json"),
      );
      assetsLocalExists = assetsRead.exists;
      if (assetsRead.exists && !assetsRead.value) {
        addIssue(issues, "invalid_assets_local_json");
      } else if (assetsRead.value) {
        localImageCount = assetsRead.value.images.length;
        localMediaCount = assetsRead.value.media.length;
        warnings.push(...(assetsRead.value.warnings ?? []));
      }

      pageMhtmlExists = await pathExists(join(bundleDir, "page.mhtml"));
      pagePdfExists = await pathExists(join(bundleDir, "page.pdf"));
    }

    if (archiveMeta?.status === "failed") {
      addIssue(issues, "archive_status_failed");
    }
    if (archiveMeta?.status === "partial") {
      addIssue(issues, "archive_status_partial");
    }
    if (archiveMeta?.status === "skipped") {
      addIssue(issues, "archive_status_skipped");
    }
    warnings.push(...(archiveMeta?.warnings ?? []));

    const logRecord = resultLog.get(`${record.account_key}\n${record.token}`);
    const errorMessage =
      logRecord?.error_message ||
      (archiveMeta?.status && archiveMeta.status !== "archived" ? archiveMeta.status : "") ||
      warnings[0] ||
      "";
    const status = determineStatus(
      archiveMeta,
      htmlQuality,
      bundleExists,
      rawHtmlExists,
      unsafePath,
    );
    const retry =
      !unsafePath &&
      status !== "archived" &&
      (issues.includes("missing_bundle") ||
        issues.includes("missing_raw_html") ||
        issues.includes("empty_raw_html") ||
        issues.includes("invalid_raw_html") ||
        issues.includes("missing_archive_meta") ||
        issues.includes("invalid_archive_meta_json") ||
        issues.includes("archive_status_failed") ||
        issues.includes("archive_status_partial"));

    const item: ArchiveAuditItem = {
      account_key: record.account_key,
      token: record.token,
      source_url: record.source_url,
      title: record.title || archiveMeta?.title || "",
      bundle_dir: bundleDir,
      status,
      retry,
      issues,
      warnings,
      error_message: errorMessage,
      archive_status: archiveMeta?.status || "",
      capture_method: archiveMeta?.capture_method || "",
      duplicate_token_count: duplicateTokenCount,
      files: {
        bundle_dir: bundleExists,
        raw_html: rawHtmlExists,
        archive_meta_json: archiveMetaExists,
        assets_local_json: assetsLocalExists,
        page_mhtml: pageMhtmlExists,
        page_pdf: pagePdfExists,
        raw_html_bytes: rawHtmlBytes,
        local_image_count: localImageCount,
        local_media_count: localMediaCount,
      },
      html_quality: htmlQuality,
    };
    items.push(item);
    increment(statusCounts, status);
    for (const issue of issues) {
      increment(issueCounts, issue);
    }
    if (retry) {
      retryRecords.push(record);
    }

    const accountSummary =
      accountSummaries.get(record.account_key) ||
      {
        account_key: record.account_key,
        total_records: 0,
        archived_count: 0,
        retry_count: 0,
        failed_count: 0,
        missing_count: 0,
        warning_count: 0,
      };
    accountSummary.total_records += 1;
    accountSummary.archived_count += status === "archived" ? 1 : 0;
    accountSummary.retry_count += retry ? 1 : 0;
    accountSummary.failed_count += status === "failed" ? 1 : 0;
    accountSummary.missing_count += status === "missing" ? 1 : 0;
    accountSummary.warning_count += warnings.length;
    accountSummaries.set(record.account_key, accountSummary);
  }

  const outputPaths = {
    summary_json: join(outDir, "archive-audit-summary.json"),
    items_jsonl: join(outDir, "archive-audit-items.jsonl"),
    account_summary_jsonl: join(outDir, "account-summary.jsonl"),
    retry_queue_jsonl: join(outDir, "retry_queue.jsonl"),
    ui_projection_json: join(outDir, "ui-projection.json"),
  };
  const accountRows = Array.from(accountSummaries.values()).sort((left, right) =>
    left.account_key.localeCompare(right.account_key),
  );
  const summary: ArchiveAuditSummary = {
    version: 1,
    generated_at: generatedAt,
    manifest_path: manifestPath,
    archive_root: archiveRoot,
    out_dir: outDir,
    total_records: records.length,
    archived_count: statusCounts.archived || 0,
    retry_queue_count: retryRecords.length,
    duplicate_token_count: Array.from(tokenCounts.values()).filter((count) => count > 1)
      .length,
    account_count: accountRows.length,
    status_counts: statusCounts,
    issue_counts: issueCounts,
    output_paths: outputPaths,
  };

  await writeJson(outputPaths.summary_json, summary);
  await writeJsonl(outputPaths.items_jsonl, items);
  await writeJsonl(outputPaths.account_summary_jsonl, accountRows);
  await writeJsonl(outputPaths.retry_queue_jsonl, retryRecords);
  await writeJson(outputPaths.ui_projection_json, {
    version: 1,
    generated_at: generatedAt,
    domain: "archive_to_llm",
    archive_root: archiveRoot,
    manifest_path: manifestPath,
    stages: [
      {
        id: "archive_download",
        label: "下载归档",
        total: records.length,
        succeeded: statusCounts.archived || 0,
        failed:
          (statusCounts.failed || 0) +
          (statusCounts.missing || 0) +
          (statusCounts.unsafe_path || 0),
        skipped: statusCounts.skipped || 0,
        running: 0,
        recoverable: retryRecords.length,
        latest_error: latestError(items),
      },
      {
        id: "asset_retention",
        label: "资源本地化",
        total: records.length,
        succeeded: items.filter((item) => item.files.assets_local_json).length,
        failed: issueCounts.invalid_assets_local_json || 0,
        skipped: records.length - items.filter((item) => item.files.assets_local_json).length,
        running: 0,
        recoverable: 0,
        latest_error: "",
      },
    ],
    summary,
    accounts: accountRows,
  });

  return summary;
}
