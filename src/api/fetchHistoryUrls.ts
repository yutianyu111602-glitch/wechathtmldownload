import { createHash } from "node:crypto";
import { join } from "node:path";

import { normalizeArticleToken } from "../archive/normalizeArticleToken.js";
import type { ArchiveQueueRecord } from "../archive/types.js";
import { DEFAULT_DAJIALA_API_KEY } from "../dajiala/client.js";
import {
  DEFAULT_MPTEXT_BASE_URL,
  MptextClient,
  type MptextArticle,
} from "../mptext/client.js";
import { ensureDir, writeJson, writeText } from "../utils/fs.js";

const KEY_ENDPOINT = "https://www.dajiala.com/fbmain/monitor/v3/post_history";
const APP_ENDPOINT = "http://api2.dajiala.com:8080/monitor/v3/post_history";
const MPTEXT_ARTICLE_PAGE_SIZE = 20;
export { DEFAULT_DAJIALA_API_KEY } from "../dajiala/client.js";

export interface HistoryUrlItem {
  title: string;
  url: string;
  position: number | null;
  author: string;
  sourceUrl: string;
  coverUrl: string;
  postTime: string;
  postDate: string;
  page: number;
}

export interface HistoryFetchResult {
  query: string;
  endpoint: string;
  authMode: "key" | "appid" | "mptext-key";
  outDir: string;
  jsonPath: string;
  txtPath: string;
  archiveQueuePath: string;
  pagesFetched: number;
  uniqueUrlCount: number;
  stoppedReason: string;
  message: string;
  items: HistoryUrlItem[];
}

export interface KeyAuthOptions {
  key: string;
}

export interface AppAuthOptions {
  appid: string;
  secret: string;
}

export type HistoryAuthOptions = KeyAuthOptions | AppAuthOptions;

export interface FetchHistoryOptions {
  query: string;
  outDir: string;
  maxPages?: number;
  endpoint?: string;
  auth: HistoryAuthOptions;
  provider?: "dajiala" | "mptext";
}

interface PaginationState {
  hasMore?: boolean;
  totalPages?: number;
}

type HistoryUrlDraft = Omit<HistoryUrlItem, "page">;

function isKeyAuth(auth: HistoryAuthOptions): auth is KeyAuthOptions {
  return "key" in auth;
}

function toStringValue(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }

  if (value === null || value === undefined) {
    return "";
  }

  return String(value).trim();
}

function toNumberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }

  return null;
}

function toBooleanValue(value: unknown): boolean | undefined {
  if (typeof value === "boolean") {
    return value;
  }

  if (typeof value === "number") {
    if (value === 1) {
      return true;
    }
    if (value === 0) {
      return false;
    }
  }

  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "true" || normalized === "1") {
      return true;
    }
    if (normalized === "false" || normalized === "0") {
      return false;
    }
  }

  return undefined;
}

function stripFragment(value: string): string {
  try {
    const url = new URL(value);
    url.hash = "";
    return url.toString();
  } catch {
    return value.split("#", 1)[0] ?? value;
  }
}

function sanitizePathPart(value: string): string {
  return value
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001F]+/g, "_")
    .replace(/\s+/g, " ")
    .replace(/[. ]+$/g, "")
    .slice(0, 80);
}

function formatEpochSeconds(value: unknown): {
  postTime: string;
  postDate: string;
} {
  const seconds = toNumberValue(value);
  if (seconds === null) {
    return {
      postTime: "",
      postDate: "",
    };
  }

  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) {
    return {
      postTime: "",
      postDate: "",
    };
  }

  const postTime = date.toISOString().replace("T", " ").slice(0, 19);
  return {
    postTime,
    postDate: postTime.slice(0, 10),
  };
}

function pickItemArray(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }

  if (!value || typeof value !== "object") {
    return [];
  }

  const record = value as Record<string, unknown>;
  if (Array.isArray(record.items)) {
    return record.items;
  }
  if (Array.isArray(record.list)) {
    return record.list;
  }
  if (Array.isArray(record.data)) {
    return record.data;
  }

  return [];
}

function normalizeHistoryItem(value: unknown): HistoryUrlDraft | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const record = value as Record<string, unknown>;
  const rawUrl =
    toStringValue(record.url) ||
    toStringValue(record.link) ||
    toStringValue(record.msg_link);
  if (!rawUrl) {
    return null;
  }

  return {
    title: toStringValue(record.title),
    url: stripFragment(rawUrl),
    position: toNumberValue(record.position),
    author: toStringValue(record.author),
    sourceUrl: toStringValue(record.source_url),
    coverUrl: toStringValue(record.cover_url),
    postTime: toStringValue(record.post_time),
    postDate: toStringValue(record.post_date),
  };
}

export function normalizeHistoryResponse(payload: unknown): {
  code?: number;
  message: string;
  items: HistoryUrlDraft[];
  pagination: PaginationState;
} {
  const root =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const message = toStringValue(root.msg) || toStringValue(root.message);
  const numericCode = toNumberValue(root.code);
  const code = numericCode === null ? undefined : numericCode;

  const data = root.data;
  const paginationSource =
    data && typeof data === "object" && !Array.isArray(data)
      ? (data as Record<string, unknown>)
      : root;
  const nestedItems = pickItemArray(data);
  const rawItems =
    nestedItems.length > 0 ? nestedItems : pickItemArray(payload);

  return {
    code,
    message,
    items: rawItems
      .map(normalizeHistoryItem)
      .filter((item): item is HistoryUrlDraft => item !== null),
    pagination: {
      hasMore:
        toBooleanValue(paginationSource.has_more) ??
        toBooleanValue(paginationSource.hasMore) ??
        toBooleanValue(paginationSource.more),
      totalPages:
        toNumberValue(paginationSource.total_page) ??
        toNumberValue(paginationSource.totalPage) ??
        toNumberValue(paginationSource.page_total) ??
        undefined,
    },
  };
}

export function createSignature(
  params: Record<string, string>,
  secret: string,
): string {
  const searchParams = new URLSearchParams();
  for (const key of Object.keys(params).sort()) {
    searchParams.set(key, params[key]);
  }

  return createHash("md5")
    .update(`${searchParams.toString()}${secret}`, "utf-8")
    .digest("hex");
}

function createNonce(length = 6): string {
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let nonce = "";
  for (let index = 0; index < length; index += 1) {
    const offset = Math.floor(Math.random() * chars.length);
    nonce += chars[offset];
  }
  return nonce;
}

function createRequestUrl(
  query: string,
  page: number,
  auth: HistoryAuthOptions,
  endpoint?: string,
): string {
  if (isKeyAuth(auth)) {
    const url = new URL(endpoint ?? KEY_ENDPOINT);
    url.searchParams.set("key", auth.key);
    url.searchParams.set("url", query);
    url.searchParams.set("page", String(page));
    return url.toString();
  }

  const timestamp = String(Math.floor(Date.now() / 1000));
  const nonce = createNonce();
  const params = {
    appid: auth.appid,
    timestamp,
    nonce,
    url: query,
    page: String(page),
  };
  const signature = createSignature(params, auth.secret);

  const url = new URL(endpoint ?? APP_ENDPOINT);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  url.searchParams.set("signature", signature);
  return url.toString();
}

export function buildOutputFolderName(query: string): string {
  let candidate = query.trim();

  if (/^https?:\/\//i.test(candidate)) {
    try {
      const url = new URL(candidate);
      candidate =
        url.searchParams.get("__biz") ||
        url.searchParams.get("biz") ||
        `${url.hostname}${url.pathname}`;
    } catch {
      candidate = query.trim();
    }
  }

  candidate = candidate
    .replace(/[^A-Za-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
  if (!candidate) {
    candidate = createHash("sha256")
      .update(query, "utf-8")
      .digest("hex")
      .slice(0, 12);
  }

  return `history_${candidate}`;
}

function deriveAccountKey(query: string): string {
  const folderName = buildOutputFolderName(query);
  return folderName.replace(/^history_/, "") || folderName;
}

export function buildArchiveQueueRecords(
  query: string,
  items: HistoryUrlItem[],
  discoveredAt = new Date().toISOString(),
  accountKeyOverride?: string,
): ArchiveQueueRecord[] {
  const accountKey = accountKeyOverride || deriveAccountKey(query);
  return items.map((item) => ({
    account_key: accountKey,
    token: normalizeArticleToken(item.url),
    source_url: item.url,
    title: item.title,
    author: item.author,
    cover_url: item.coverUrl,
    post_time: item.postTime,
    post_date: item.postDate,
    page: item.page,
    discovered_at: discoveredAt,
    discovery_source: "history-api",
  }));
}

function getMptextBaseUrl(endpoint?: string): string {
  return (endpoint || DEFAULT_MPTEXT_BASE_URL).replace(/\/+$/g, "");
}

function normalizeMptextArticle(value: unknown): HistoryUrlDraft | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const record = value as Record<string, unknown>;
  const rawUrl = toStringValue(record.link) || toStringValue(record.url);
  if (!rawUrl) {
    return null;
  }

  const { postTime, postDate } = formatEpochSeconds(
    record.update_time ?? record.create_time,
  );
  return {
    title: toStringValue(record.title),
    url: stripFragment(rawUrl),
    position: toNumberValue(record.itemidx),
    author: toStringValue(record.author_name),
    sourceUrl: "",
    coverUrl:
      toStringValue(record.cover) ||
      toStringValue(record.cover_img) ||
      toStringValue(record.pic_cdn_url_1_1),
    postTime,
    postDate,
  };
}

function normalizeMptextArticleResponse(articles: MptextArticle[]): HistoryUrlDraft[] {
  return articles
    .map(normalizeMptextArticle)
    .filter((item): item is HistoryUrlDraft => item !== null);
}

async function fetchMptextHistoryUrls(
  options: FetchHistoryOptions,
): Promise<HistoryFetchResult> {
  if (!isKeyAuth(options.auth)) {
    throw new Error("mptext provider requires --key / key auth");
  }

  const maxPages = Math.max(1, options.maxPages ?? 200);
  const client = new MptextClient({
    baseUrl: options.endpoint,
    authKey: options.auth.key,
  });
  const account = await client.resolveAccount(options.query);
  const accountKey =
    sanitizePathPart(account.nickname) ||
    sanitizePathPart(account.fakeid) ||
    deriveAccountKey(options.query);
  const outDir = join(options.outDir, `history_${accountKey}`);
  await ensureDir(outDir);

  const items: HistoryUrlItem[] = [];
  const seenUrls = new Set<string>();
  const seenPageFingerprints = new Set<string>();
  let pagesFetched = 0;
  let stoppedReason = "empty-page";

  for (let page = 1; page <= maxPages; page += 1) {
    const begin = (page - 1) * MPTEXT_ARTICLE_PAGE_SIZE;
    const payload = await client.getArticlePage({
        fakeid: account.fakeid,
        begin,
        size: MPTEXT_ARTICLE_PAGE_SIZE,
      });
    const normalizedItems = normalizeMptextArticleResponse(payload.articles || []);

    const pageFingerprint = createHash("sha256")
      .update(JSON.stringify(normalizedItems), "utf-8")
      .digest("hex");
    if (seenPageFingerprints.has(pageFingerprint)) {
      pagesFetched = page;
      stoppedReason = "repeated-page";
      break;
    }
    seenPageFingerprints.add(pageFingerprint);

    if (normalizedItems.length === 0) {
      pagesFetched = page;
      stoppedReason = page === 1 ? "empty-page" : "no-more-items";
      break;
    }

    let newUrlCount = 0;
    for (const item of normalizedItems) {
      if (seenUrls.has(item.url)) {
        continue;
      }
      seenUrls.add(item.url);
      items.push({
        ...item,
        page,
      });
      newUrlCount += 1;
    }

    pagesFetched = page;
    if (newUrlCount === 0) {
      stoppedReason = "no-new-urls";
      break;
    }
    if (normalizedItems.length < MPTEXT_ARTICLE_PAGE_SIZE) {
      stoppedReason = "no-more-items";
      break;
    }
    if (page === maxPages) {
      stoppedReason = "max-pages";
    }
  }

  const jsonPath = join(outDir, "history_urls.json");
  const txtPath = join(outDir, "history_urls.txt");
  const archiveQueuePath = join(outDir, "archive_queue.jsonl");
  const result: HistoryFetchResult = {
    query: options.query,
    endpoint: `${getMptextBaseUrl(options.endpoint)}/api/public/v1/article`,
    authMode: "mptext-key",
    outDir,
    jsonPath,
    txtPath,
    archiveQueuePath,
    pagesFetched,
    uniqueUrlCount: items.length,
    stoppedReason,
    message: account.nickname || account.fakeid,
    items,
  };

  await writeJson(jsonPath, result);
  await writeText(
    txtPath,
    items.map((item) => item.url).join("\n") + (items.length > 0 ? "\n" : ""),
  );
  const queueRecords = buildArchiveQueueRecords(
    options.query,
    items,
    new Date().toISOString(),
    accountKey,
  );
  await writeText(
    archiveQueuePath,
    queueRecords.map((record) => JSON.stringify(record)).join("\n") +
      (queueRecords.length > 0 ? "\n" : ""),
  );

  return result;
}

export async function fetchHistoryUrls(
  options: FetchHistoryOptions,
): Promise<HistoryFetchResult> {
  if (options.provider === "mptext") {
    return fetchMptextHistoryUrls(options);
  }

  const maxPages = Math.max(1, options.maxPages ?? 200);
  const outDir = join(options.outDir, buildOutputFolderName(options.query));
  await ensureDir(outDir);

  const items: HistoryUrlItem[] = [];
  const seenUrls = new Set<string>();
  const seenPageFingerprints = new Set<string>();
  let pagesFetched = 0;
  let stoppedReason = "empty-page";
  let message = "";

  for (let page = 1; page <= maxPages; page += 1) {
    const requestUrl = createRequestUrl(
      options.query,
      page,
      options.auth,
      options.endpoint,
    );
    const response = await fetch(requestUrl, {
      method: "GET",
      headers: {
        accept: "application/json, text/plain, */*",
      },
    });

    const rawText = await response.text();
    let payload: unknown;
    try {
      payload = JSON.parse(rawText);
    } catch {
      throw new Error(
        `History API returned non-JSON for page ${page}: ${rawText.slice(0, 200)}`,
      );
    }

    if (!response.ok) {
      throw new Error(
        `History API request failed on page ${page}: HTTP ${response.status} ${response.statusText}`,
      );
    }

    const normalized = normalizeHistoryResponse(payload);
    message = normalized.message;
    if (normalized.code !== undefined && normalized.code !== 0) {
      throw new Error(
        `History API returned code ${normalized.code} on page ${page}: ${message || rawText.slice(0, 200)}`,
      );
    }

    const pageFingerprint = createHash("sha256")
      .update(JSON.stringify(normalized.items), "utf-8")
      .digest("hex");
    if (seenPageFingerprints.has(pageFingerprint)) {
      pagesFetched = page;
      stoppedReason = "repeated-page";
      break;
    }
    seenPageFingerprints.add(pageFingerprint);

    if (normalized.items.length === 0) {
      pagesFetched = page;
      stoppedReason = page === 1 ? "empty-page" : "no-more-items";
      break;
    }

    let newUrlCount = 0;
    for (const item of normalized.items) {
      if (seenUrls.has(item.url)) {
        continue;
      }
      seenUrls.add(item.url);
      items.push({
        ...item,
        page,
      });
      newUrlCount += 1;
    }

    pagesFetched = page;
    if (
      normalized.pagination.totalPages !== undefined &&
      page >= normalized.pagination.totalPages
    ) {
      stoppedReason = "reached-total-pages";
      break;
    }
    if (normalized.pagination.hasMore === false) {
      stoppedReason = "has-more-false";
      break;
    }
    if (newUrlCount === 0) {
      stoppedReason = "no-new-urls";
      break;
    }
    if (page === maxPages) {
      stoppedReason = "max-pages";
    }
  }

  const jsonPath = join(outDir, "history_urls.json");
  const txtPath = join(outDir, "history_urls.txt");
  const archiveQueuePath = join(outDir, "archive_queue.jsonl");
  const endpoint =
    options.endpoint ?? (isKeyAuth(options.auth) ? KEY_ENDPOINT : APP_ENDPOINT);
  const result: HistoryFetchResult = {
    query: options.query,
    endpoint,
    authMode: isKeyAuth(options.auth) ? "key" : "appid",
    outDir,
    jsonPath,
    txtPath,
    archiveQueuePath,
    pagesFetched,
    uniqueUrlCount: items.length,
    stoppedReason,
    message,
    items,
  };

  await writeJson(jsonPath, result);
  await writeText(
    txtPath,
    items.map((item) => item.url).join("\n") + (items.length > 0 ? "\n" : ""),
  );
  const queueRecords = buildArchiveQueueRecords(options.query, items);
  await writeText(
    archiveQueuePath,
    queueRecords.map((record) => JSON.stringify(record)).join("\n") +
      (queueRecords.length > 0 ? "\n" : ""),
  );

  return result;
}
