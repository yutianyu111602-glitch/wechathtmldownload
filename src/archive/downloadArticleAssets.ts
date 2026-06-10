import { createHash } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import { extname, join } from "node:path";

import { load } from "cheerio";

import type { AssetsLocalJson, LocalAssetRecord } from "./types.js";
import { extractAssets } from "../extract/extractAssets.js";
import { extractMeta } from "../extract/extractMeta.js";
import { writeBuffer, writeJson } from "../utils/fs.js";
import { sha256Hex } from "../utils/hash.js";

interface DownloadArticleAssetsOptions {
  fetchImpl?: typeof fetch;
  maxRetries?: number;
  retryDelayMs?: number;
  requestTimeoutMs?: number;
}

function getDefaultMaxRetries(): number {
  const configured = Number(process.env.WECHAT_ASSET_MAX_RETRIES);
  if (Number.isFinite(configured) && configured >= 0) {
    return Math.floor(configured);
  }
  return 3;
}

function getDefaultRetryDelayMs(): number {
  const configured = Number(process.env.WECHAT_ASSET_RETRY_DELAY_MS);
  if (Number.isFinite(configured) && configured >= 0) {
    return Math.floor(configured);
  }
  return 1_000;
}

function getDefaultRequestTimeoutMs(): number {
  const configured = Number(process.env.WECHAT_ASSET_REQUEST_TIMEOUT_MS);
  if (Number.isFinite(configured) && configured > 0) {
    return Math.floor(configured);
  }
  return 30_000;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryableStatus(status: number): boolean {
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isRetryableFetchError(error: unknown): boolean {
  const message = errorMessage(error).toLowerCase();
  return (
    message.includes("abort") ||
    message.includes("timeout") ||
    message.includes("terminated") ||
    message.includes("fetch failed") ||
    message.includes("socket") ||
    message.includes("econnreset") ||
    message.includes("etimedout") ||
    message.includes("econnrefused")
  );
}

function contentTypeToExtension(contentType: string, remoteUrl: string): string {
  const normalized = contentType.toLowerCase();
  if (normalized.includes("jpeg")) {
    return ".jpg";
  }
  if (normalized.includes("png")) {
    return ".png";
  }
  if (normalized.includes("webp")) {
    return ".webp";
  }
  if (normalized.includes("gif")) {
    return ".gif";
  }
  if (normalized.includes("mpeg") || normalized.includes("mp3")) {
    return ".mp3";
  }
  if (normalized.includes("mp4")) {
    return ".mp4";
  }
  try {
    const extension = extname(new URL(remoteUrl).pathname);
    return extension || ".bin";
  } catch {
    return ".bin";
  }
}

async function downloadOneAsset(options: {
  fetchImpl: typeof fetch;
  bundleDir: string;
  sourceUrl: string;
  remoteUrl: string;
  token: string;
  index: number;
  sourceKind: "image" | "media";
  maxRetries: number;
  retryDelayMs: number;
  requestTimeoutMs: number;
}): Promise<LocalAssetRecord> {
  const maxAttempts = options.maxRetries + 1;
  let lastErrorMessage = "";

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.requestTimeoutMs);
    try {
      const response = await options.fetchImpl(options.remoteUrl, {
        headers: {
          referer: options.sourceUrl,
          "user-agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        },
        signal: controller.signal,
      });

      if (!response.ok) {
        clearTimeout(timeout);
        lastErrorMessage = `HTTP ${response.status}`;
        if (attempt < maxAttempts && isRetryableStatus(response.status)) {
          await sleep(options.retryDelayMs * attempt);
          continue;
        }
        return {
          asset_id: `${options.sourceKind}-${options.index}`,
          remote_url: options.remoteUrl,
          local_path: "",
          status: "failed",
          content_type: response.headers.get("content-type") || "",
          file_size: 0,
          sha256: "",
          source_token: options.token,
          source_kind: options.sourceKind,
          error_message: lastErrorMessage,
        };
      }

      const bytes = Buffer.from(await response.arrayBuffer());
      clearTimeout(timeout);
      if (bytes.length === 0) {
        lastErrorMessage = "empty response body";
        if (attempt < maxAttempts) {
          await sleep(options.retryDelayMs * attempt);
          continue;
        }
        return {
          asset_id: `${options.sourceKind}-${options.index}`,
          remote_url: options.remoteUrl,
          local_path: "",
          status: "failed",
          content_type: response.headers.get("content-type") || "",
          file_size: 0,
          sha256: "",
          source_token: options.token,
          source_kind: options.sourceKind,
          error_message: lastErrorMessage,
        };
      }

      const contentType = response.headers.get("content-type") || "application/octet-stream";
      const extension = contentTypeToExtension(contentType, options.remoteUrl);
      const fileName = `${String(options.index + 1).padStart(3, "0")}-${sha256Hex(options.remoteUrl).slice(0, 12)}${extension}`;
      const relativeDir = options.sourceKind === "image" ? "images" : "media";
      const relativePath = `${relativeDir}/${fileName}`;
      await mkdir(join(options.bundleDir, relativeDir), { recursive: true });
      await writeBuffer(join(options.bundleDir, relativePath), bytes);
      return {
        asset_id: `${options.sourceKind}-${options.index}`,
        remote_url: options.remoteUrl,
        local_path: relativePath,
        status: "downloaded",
        content_type: contentType,
        file_size: bytes.length,
        sha256: createHash("sha256").update(bytes).digest("hex"),
        source_token: options.token,
        source_kind: options.sourceKind,
      };
    } catch (error) {
      clearTimeout(timeout);
      lastErrorMessage = errorMessage(error);
      if (attempt < maxAttempts && isRetryableFetchError(error)) {
        await sleep(options.retryDelayMs * attempt);
        continue;
      }
      return {
        asset_id: `${options.sourceKind}-${options.index}`,
        remote_url: options.remoteUrl,
        local_path: "",
        status: "failed",
        content_type: "",
        file_size: 0,
        sha256: "",
        source_token: options.token,
        source_kind: options.sourceKind,
        error_message: lastErrorMessage,
      };
    }
  }

  return {
    asset_id: `${options.sourceKind}-${options.index}`,
    remote_url: options.remoteUrl,
    local_path: "",
    status: "failed",
    content_type: "",
    file_size: 0,
    sha256: "",
    source_token: options.token,
    source_kind: options.sourceKind,
    error_message: lastErrorMessage || "asset download failed",
  };
}

export async function downloadArticleAssets(
  bundleDir: string,
  options: DownloadArticleAssetsOptions = {},
): Promise<AssetsLocalJson> {
  const fetchImpl = options.fetchImpl || fetch;
  const maxRetries = Math.max(0, Math.floor(options.maxRetries ?? getDefaultMaxRetries()));
  const retryDelayMs = Math.max(0, Math.floor(options.retryDelayMs ?? getDefaultRetryDelayMs()));
  const requestTimeoutMs = Math.max(
    1,
    Math.floor(options.requestTimeoutMs ?? getDefaultRequestTimeoutMs()),
  );
  const rawHtml = await readFile(join(bundleDir, "raw.html"), "utf-8");
  const $ = load(rawHtml);
  const meta = extractMeta($, rawHtml, "");
  const assets = extractAssets($, meta.source_url);
  const archiveMeta = JSON.parse(
    await readFile(join(bundleDir, "archive_meta.json"), "utf-8"),
  ) as { token?: string; source_url?: string };
  const sourceUrl = archiveMeta.source_url || meta.source_url;
  const token = archiveMeta.token || sha256Hex(sourceUrl).slice(0, 12);

  const imageRecords: LocalAssetRecord[] = [];
  for (const [index, image] of assets.images.entries()) {
    const remoteUrl = image.data_src || image.src;
    if (!remoteUrl) {
      continue;
    }
    imageRecords.push(
      await downloadOneAsset({
        fetchImpl,
        bundleDir,
        sourceUrl,
        remoteUrl,
        token,
        index,
        sourceKind: "image",
        maxRetries,
        retryDelayMs,
        requestTimeoutMs,
      }),
    );
  }

  const result: AssetsLocalJson = {
    images: imageRecords,
    media: [],
    warnings: [],
  };
  await writeJson(join(bundleDir, "assets_local.json"), result);
  return result;
}
