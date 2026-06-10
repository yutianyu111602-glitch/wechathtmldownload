import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

export const DEFAULT_MPTEXT_BASE_URL =
  process.env.MPTEXT_BASE_URL || "http://127.0.0.1:17300";

function candidateDataDirs(): string[] {
  const roots = [
    process.env.MPTEXT_DATA_DIR || "",
    join(process.cwd(), ".mptext-data"),
    resolve(process.cwd(), ".mptext-data"),
    resolve(process.cwd(), "..", ".mptext-data"),
  ].filter(Boolean);
  return Array.from(new Set(roots));
}

function candidateCookieDirs(): string[] {
  const dirs: string[] = [];
  if (process.env.MPTEXT_COOKIE_DIR) {
    dirs.push(process.env.MPTEXT_COOKIE_DIR);
  }
  for (const root of candidateDataDirs()) {
    dirs.push(root.endsWith("cookie") ? root : join(root, "kv", "cookie"));
  }
  return Array.from(new Set(dirs));
}

function candidateAuthCacheFiles(): string[] {
  const files: string[] = [];
  if (process.env.MPTEXT_AUTH_CACHE) {
    files.push(process.env.MPTEXT_AUTH_CACHE);
  }
  for (const root of candidateDataDirs()) {
    files.push(join(root, "kv", "auth-key-current.json"));
  }
  return Array.from(new Set(files));
}

export function discoverCachedMptextAuthKey(): string {
  for (const file of candidateAuthCacheFiles()) {
    if (!existsSync(file)) {
      continue;
    }
    let raw = "";
    try {
      raw = readFileSync(file, "utf-8").trim();
    } catch {
      continue;
    }
    if (!raw) {
      continue;
    }
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (!parsed || typeof parsed !== "object") {
        continue;
      }
      const record = parsed as Record<string, unknown>;
      const key =
        typeof record.api_key === "string"
          ? record.api_key.trim()
          : typeof record.auth_key === "string"
            ? record.auth_key.trim()
            : typeof record.key === "string"
              ? record.key.trim()
              : "";
      if (key) {
        return key;
      }
    } catch {
      if (/^[A-Za-z0-9_-]{16,256}$/.test(raw)) {
        return raw;
      }
    }
  }
  return "";
}

export function discoverLatestMptextAuthKey(): string {
  const candidates: Array<{ key: string; mtimeMs: number }> = [];
  for (const dir of candidateCookieDirs()) {
    if (!existsSync(dir)) {
      continue;
    }
    for (const name of readdirSync(dir)) {
      if (!/^[a-f0-9]{32}$/i.test(name)) {
        continue;
      }
      try {
        candidates.push({
          key: name,
          mtimeMs: statSync(join(dir, name)).mtimeMs,
        });
      } catch {
        // Ignore files that disappear while the exporter updates its kv store.
      }
    }
  }
  candidates.sort((left, right) => right.mtimeMs - left.mtimeMs);
  return candidates[0]?.key || "";
}

const CACHED_MPTEXT_AUTH_KEY = discoverCachedMptextAuthKey();
const DISCOVERED_MPTEXT_AUTH_KEY = discoverLatestMptextAuthKey();

export const DEFAULT_MPTEXT_AUTH_KEY =
  process.env.MPTEXT_AUTH_KEY_PREFER_ENV === "1"
    ? process.env.MPTEXT_AUTH_KEY ||
      CACHED_MPTEXT_AUTH_KEY ||
      DISCOVERED_MPTEXT_AUTH_KEY
    : CACHED_MPTEXT_AUTH_KEY ||
      DISCOVERED_MPTEXT_AUTH_KEY ||
      process.env.MPTEXT_AUTH_KEY ||
      "";

const ARTICLE_PAGE_SIZE = 20;

export type MptextDownloadFormat = "html" | "json" | "markdown" | "text";

export interface MptextClientOptions {
  baseUrl?: string;
  authKey?: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
  rateLimitDelayMs?: number;
  maxRateLimitRetries?: number;
  requestRetryDelayMs?: number;
  maxRequestRetries?: number;
}

export interface MptextBaseResp {
  ret?: number;
  err_msg?: string;
  errmsg?: string;
}

export interface MptextAccount {
  fakeid: string;
  nickname: string;
  alias?: string;
  round_head_img?: string;
  service_type?: number;
  signature?: string;
  username?: string;
  verify_status?: number;
  [key: string]: unknown;
}

export interface MptextArticle {
  aid?: string;
  title?: string;
  cover?: string;
  link?: string;
  digest?: string;
  update_time?: number;
  appmsgid?: number;
  itemidx?: number;
  author_name?: string;
  create_time?: number;
  cover_img?: string;
  pic_cdn_url_1_1?: string;
  [key: string]: unknown;
}

export interface MptextAccountListResponse {
  base_resp?: MptextBaseResp;
  list?: MptextAccount[];
  total?: number;
  [key: string]: unknown;
}

export interface MptextArticleListResponse {
  base_resp?: MptextBaseResp;
  articles?: MptextArticle[];
  [key: string]: unknown;
}

export interface MptextAuthKeyResponse {
  code?: number;
  data?: string;
  msg?: string;
}

interface RequestJsonOptions {
  context: string;
  auth?: boolean;
  rateLimitAware?: boolean;
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

function toStringValue(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isArticleUrl(value: string): boolean {
  return /^https?:\/\/mp\.weixin\.qq\.com\//i.test(value.trim());
}

function looksLikeFakeid(value: string): boolean {
  return /^[A-Za-z0-9+/=]{16,}$/.test(value.trim());
}

function getBaseResp(payload: unknown): MptextBaseResp | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const record = payload as Record<string, unknown>;
  return record.base_resp && typeof record.base_resp === "object"
    ? (record.base_resp as MptextBaseResp)
    : null;
}

export function assertMptextOk(payload: unknown, context: string): void {
  const baseResp = getBaseResp(payload);
  const ret = toNumberValue(baseResp?.ret);
  if (ret !== null && ret !== 0) {
    const message =
      toStringValue(baseResp?.err_msg) ||
      toStringValue(baseResp?.errmsg) ||
      "unknown error";
    throw new Error(`mptext ${context} failed: ret ${ret}: ${message}`);
  }
}

function normalizeAccount(value: unknown): MptextAccount | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const fakeid = toStringValue(record.fakeid);
  if (!fakeid) {
    return null;
  }
  return {
    ...record,
    fakeid,
    nickname: toStringValue(record.nickname),
    alias: toStringValue(record.alias) || undefined,
  };
}

export class MptextClient {
  readonly baseUrl: string;
  readonly authKey: string;

  private readonly fetchImpl: typeof fetch;
  private readonly requestTimeoutMs: number;
  private readonly rateLimitDelayMs: number;
  private readonly maxRateLimitRetries: number;
  private readonly requestRetryDelayMs: number;
  private readonly maxRequestRetries: number;

  constructor(options: MptextClientOptions = {}) {
    this.baseUrl = (options.baseUrl || DEFAULT_MPTEXT_BASE_URL).replace(
      /\/+$/g,
      "",
    );
    this.authKey = options.authKey || DEFAULT_MPTEXT_AUTH_KEY;
    this.fetchImpl = options.fetchImpl || fetch;
    this.requestTimeoutMs = options.requestTimeoutMs ?? 120_000;
    this.rateLimitDelayMs = options.rateLimitDelayMs ?? 90_000;
    this.maxRateLimitRetries = options.maxRateLimitRetries ?? 20;
    this.requestRetryDelayMs = options.requestRetryDelayMs ?? 2_000;
    this.maxRequestRetries = options.maxRequestRetries ?? 3;
  }

  async validateAuthKey(): Promise<boolean> {
    const payload = await this.requestJson<MptextAuthKeyResponse>(
      "/api/public/v1/authkey",
      {},
      { context: "authkey", auth: true },
    );
    return payload.code === 0;
  }

  async searchAccounts(
    keyword: string,
    begin = 0,
    size = ARTICLE_PAGE_SIZE,
  ): Promise<MptextAccountListResponse> {
    const payload = await this.requestJson<MptextAccountListResponse>(
      "/api/public/v1/account",
      {
        keyword,
        begin: String(begin),
        size: String(size),
      },
      { context: "account search", auth: true },
    );
    assertMptextOk(payload, "account search");
    payload.list = (payload.list || [])
      .map(normalizeAccount)
      .filter((item): item is MptextAccount => item !== null);
    return payload;
  }

  async accountByUrl(url: string): Promise<MptextAccountListResponse> {
    const payload = await this.requestJson<MptextAccountListResponse>(
      "/api/public/v1/accountbyurl",
      { url },
      { context: "account by url", auth: true },
    );
    assertMptextOk(payload, "account by url");
    payload.list = (payload.list || [])
      .map(normalizeAccount)
      .filter((item): item is MptextAccount => item !== null);
    return payload;
  }

  async resolveAccount(query: string): Promise<MptextAccount> {
    const trimmedQuery = query.trim();
    if (looksLikeFakeid(trimmedQuery)) {
      return {
        fakeid: trimmedQuery,
        nickname: "",
      };
    }

    const payload = isArticleUrl(trimmedQuery)
      ? await this.accountByUrl(trimmedQuery)
      : await this.searchAccounts(trimmedQuery, 0, ARTICLE_PAGE_SIZE);
    const list = payload.list || [];
    const exact =
      list.find(
        (item) => item.nickname === trimmedQuery || item.alias === trimmedQuery,
      ) || list[0];
    if (!exact) {
      throw new Error(`mptext found no account for query: ${trimmedQuery}`);
    }
    return exact;
  }

  async getArticlePage(options: {
    fakeid: string;
    begin?: number;
    size?: number;
    keyword?: string;
  }): Promise<MptextArticleListResponse> {
    const query: Record<string, string> = {
      fakeid: options.fakeid,
      begin: String(options.begin ?? 0),
      size: String(options.size ?? ARTICLE_PAGE_SIZE),
    };
    if (options.keyword) {
      query.keyword = options.keyword;
    }

    const payload = await this.requestJson<MptextArticleListResponse>(
      "/api/public/v1/article",
      query,
      {
        context: `article page begin=${query.begin}`,
        auth: true,
        rateLimitAware: true,
      },
    );
    assertMptextOk(payload, "article page");
    payload.articles = Array.isArray(payload.articles)
      ? payload.articles
      : [];
    return payload;
  }

  async downloadArticle(
    articleUrl: string,
    format: MptextDownloadFormat = "html",
  ): Promise<string> {
    return this.requestText(
      "/api/public/v1/download",
      {
        url: articleUrl,
        format,
      },
      `download ${format}`,
      true,
    );
  }

  private buildUrl(path: string, query: Record<string, string>): string {
    const url = new URL(path, this.baseUrl);
    for (const [name, value] of Object.entries(query)) {
      url.searchParams.set(name, value);
    }
    return url.toString();
  }

  private buildHeaders(auth: boolean, accept: string): Headers {
    const headers = new Headers({ accept });
    if (auth && this.authKey) {
      headers.set("X-Auth-Key", this.authKey);
    }
    return headers;
  }

  private async requestJson<T>(
    path: string,
    query: Record<string, string>,
    options: RequestJsonOptions,
  ): Promise<T> {
    let lastPayload: unknown = null;
    for (let attempt = 1; attempt <= this.maxRateLimitRetries; attempt += 1) {
      const rawText = await this.requestRaw(
        path,
        query,
        options.context,
        this.buildHeaders(
          options.auth !== false,
          "application/json, text/plain, */*",
        ),
      );

      let payload: unknown;
      try {
        payload = JSON.parse(rawText);
      } catch {
        throw new Error(
          `mptext ${options.context} returned non-JSON: ${rawText.slice(0, 200)}`,
        );
      }
      lastPayload = payload;

      const ret = toNumberValue(getBaseResp(payload)?.ret);
      if (!options.rateLimitAware || ret !== 200013) {
        return payload as T;
      }

      const delay = this.rateLimitDelayMs * attempt;
      await sleep(delay);
    }

    return lastPayload as T;
  }

  private async requestText(
    path: string,
    query: Record<string, string>,
    context: string,
    auth: boolean,
  ): Promise<string> {
    return this.requestRaw(
      path,
      query,
      context,
      this.buildHeaders(auth, "text/html, text/plain, */*"),
    );
  }

  private async requestRaw(
    path: string,
    query: Record<string, string>,
    context: string,
    headers: Headers,
  ): Promise<string> {
    const url = this.buildUrl(path, query);
    let lastError: unknown = null;
    for (let attempt = 1; attempt <= this.maxRequestRetries; attempt += 1) {
      try {
        const response = await this.fetchImpl(url, {
          method: "GET",
          headers,
          signal: AbortSignal.timeout(this.requestTimeoutMs),
        });
        const rawText = await response.text();
        if (response.ok) {
          return rawText;
        }

        const message = `mptext ${context} failed: HTTP ${response.status} ${response.statusText}: ${rawText.slice(0, 200)}`;
        if (
          attempt >= this.maxRequestRetries ||
          !isRetryableHttpStatus(response.status)
        ) {
          throw new Error(message);
        }
        lastError = new Error(message);
      } catch (error) {
        lastError = error;
        if (attempt >= this.maxRequestRetries || !isRetryableRequestError(error)) {
          throw error;
        }
      }

      await sleep(this.requestRetryDelayMs * attempt);
    }

    throw lastError instanceof Error ? lastError : new Error(String(lastError));
  }
}

function isRetryableHttpStatus(status: number): boolean {
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

function isRetryableRequestError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return true;
  }
  const name = error.name.toLowerCase();
  const message = error.message.toLowerCase();
  return (
    name.includes("abort") ||
    name.includes("timeout") ||
    message.includes("fetch failed") ||
    message.includes("socket") ||
    message.includes("timeout") ||
    message.includes("econnreset") ||
    message.includes("etimedout") ||
    message.includes("econnrefused")
  );
}
