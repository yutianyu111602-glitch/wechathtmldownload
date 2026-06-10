export const DEFAULT_DAJIALA_BASE_URL = "https://www.dajiala.com";
export const DEFAULT_DAJIALA_API_KEY =
  process.env.DAJIALA_API_KEY ||
  process.env.JZL_API_KEY ||
  "";

export interface DajialaClientOptions {
  baseUrl?: string;
  key?: string;
  fetchImpl?: typeof fetch;
}

export interface DajialaArticleResponse {
  code?: number | string;
  msg?: string;
  message?: string;
  content?: string;
  content_text?: string;
  cost_money?: number | string;
  remain_money?: number | string;
  cost?: number | string;
  remain?: number | string;
  data?: unknown;
  [key: string]: unknown;
}

export interface DajialaArticleInfo {
  title: string;
  url: string;
  content: string;
  contentText: string;
  imageUrls: string[];
  nickname: string;
  author: string;
  postTime: string;
  sourceUrl: string;
  coverUrl: string;
  summary: string;
}

export interface DajialaPostHistoryOptions {
  biz?: string;
  name?: string;
  url?: string;
  page?: number;
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/g, "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

function getDataRecords(response: DajialaArticleResponse): Record<string, unknown>[] {
  if (Array.isArray(response.data)) {
    return response.data.filter(isRecord);
  }
  if (isRecord(response.data)) {
    const nestedData = response.data.data;
    if (Array.isArray(nestedData)) {
      return nestedData.filter(isRecord);
    }
    if (isRecord(nestedData)) {
      return [nestedData, response.data];
    }
    return [response.data];
  }
  return [];
}

export function normalizeDajialaArticleUrl(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return url;
  }

  if (
    parsed.hostname !== "mp.weixin.qq.com" ||
    parsed.pathname !== "/mp/appmsg/show"
  ) {
    return url;
  }

  const biz = parsed.searchParams.get("__biz") || "";
  const mid = parsed.searchParams.get("appmsgid") || "";
  const idx = parsed.searchParams.get("itemidx") || "";
  const sn = parsed.searchParams.get("sign") || "";
  if (!biz || !mid || !idx || !sn) {
    return url;
  }

  const rewritten = new URL("https://mp.weixin.qq.com/s");
  rewritten.searchParams.set("__biz", biz);
  rewritten.searchParams.set("mid", mid);
  rewritten.searchParams.set("idx", idx);
  rewritten.searchParams.set("sn", sn);
  rewritten.hash = "rd";
  return rewritten.toString();
}

function readField(response: DajialaArticleResponse, names: string[]): string {
  for (const name of names) {
    const topLevelValue = toStringValue(response[name]);
    if (topLevelValue) {
      return topLevelValue;
    }
    for (const record of getDataRecords(response)) {
      const nestedValue = toStringValue(record[name]);
      if (nestedValue) {
        return nestedValue;
      }
    }
  }
  return "";
}

function readImageUrls(response: DajialaArticleResponse): string[] {
  const urls = new Set<string>();
  const add = (value: unknown): void => {
    const text = toStringValue(value);
    if (/^https?:\/\//i.test(text)) {
      urls.add(text);
    }
  };
  const collect = (record: Record<string, unknown>): void => {
    add(record.cover);
    add(record.cover_url);
    add(record.cdn_url);
    const shareCover = record.share_cover;
    if (isRecord(shareCover)) {
      add(shareCover.cdn_url);
    }
    const pictures = record.picture_page_info_list;
    if (Array.isArray(pictures)) {
      for (const picture of pictures) {
        if (!isRecord(picture)) {
          continue;
        }
        add(picture.cdn_url);
        const nestedShareCover = picture.share_cover;
        if (isRecord(nestedShareCover)) {
          add(nestedShareCover.cdn_url);
        }
      }
    }
  };
  collect(response);
  for (const record of getDataRecords(response)) {
    collect(record);
  }
  return [...urls];
}

async function parseJsonResponse(response: Response): Promise<DajialaArticleResponse> {
  const text = await response.text();
  try {
    return JSON.parse(text) as DajialaArticleResponse;
  } catch {
    return {
      code: response.status,
      msg: text.slice(0, 300),
    };
  }
}

export function getDajialaCode(response: DajialaArticleResponse): number | string {
  const code =
    response.code ??
    getDataRecords(response)
      .map((record) => record.code)
      .find((value) => typeof value === "number" || typeof value === "string");
  if (typeof code === "number" || typeof code === "string") {
    return code;
  }
  return "";
}

export function getDajialaMessage(response: DajialaArticleResponse): string {
  return readField(response, ["msg", "message"]);
}

export function extractDajialaArticleInfo(
  response: DajialaArticleResponse,
): DajialaArticleInfo {
  return {
    title: readField(response, ["title"]),
    url: readField(response, ["article_url", "url"]),
    content: readField(response, ["content"]),
    contentText: readField(response, ["content_text"]),
    imageUrls: readImageUrls(response),
    nickname: readField(response, ["nickname", "wx_name", "account_name"]),
    author: readField(response, ["author"]),
    postTime: readField(response, ["post_time_str", "post_time", "public_time"]),
    sourceUrl: readField(response, ["source_url"]),
    coverUrl: readField(response, ["cover", "cover_url"]),
    summary: readField(response, ["summary", "description"]),
  };
}

export function extractDajialaShortToLongUrl(response: DajialaArticleResponse): string {
  return readField(response, ["url", "article_url", "long_url", "link"]);
}

export class DajialaClient {
  readonly baseUrl: string;

  private readonly key: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: DajialaClientOptions = {}) {
    this.baseUrl = trimTrailingSlash(
      options.baseUrl || process.env.DAJIALA_BASE_URL || DEFAULT_DAJIALA_BASE_URL,
    );
    this.key = options.key || DEFAULT_DAJIALA_API_KEY;
    this.fetchImpl = options.fetchImpl || fetch;
  }

  async getArticleTextDetail(url: string): Promise<DajialaArticleResponse> {
    const articleUrl = normalizeDajialaArticleUrl(url);
    const params = new URLSearchParams({
      key: this.key,
      url: articleUrl,
    });
    return parseJsonResponse(
      await this.fetchImpl(`${this.baseUrl}/fbmain/monitor/v3/article_detail?${params}`),
    );
  }

  async getArticleHtmlDetail(url: string): Promise<DajialaArticleResponse> {
    const articleUrl = normalizeDajialaArticleUrl(url);
    return parseJsonResponse(
      await this.fetchImpl(`${this.baseUrl}/fbmain/monitor/v3/article_detail`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          key: this.key,
          url: articleUrl,
        }),
      }),
    );
  }

  async getArticleInfo(url: string): Promise<DajialaArticleResponse> {
    const articleUrl = normalizeDajialaArticleUrl(url);
    return parseJsonResponse(
      await this.fetchImpl(`${this.baseUrl}/fbmain/monitor/v3/article_info`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          key: this.key,
          url: articleUrl,
        }),
      }),
    );
  }

  async shortToLong(link: string): Promise<DajialaArticleResponse> {
    const articleUrl = normalizeDajialaArticleUrl(link);
    const params = new URLSearchParams({
      key: this.key,
      link: articleUrl,
    });
    return parseJsonResponse(
      await this.fetchImpl(`${this.baseUrl}/fbmain/monitor/v3/link/short2long?${params}`),
    );
  }

  async getPostHistory(
    options: DajialaPostHistoryOptions,
  ): Promise<DajialaArticleResponse> {
    const body: Record<string, string | number> = {
      key: this.key,
      page: options.page || 1,
    };
    if (options.biz) {
      body.biz = options.biz;
    }
    if (options.name) {
      body.name = options.name;
    }
    if (options.url) {
      body.url = normalizeDajialaArticleUrl(options.url);
    }
    return parseJsonResponse(
      await this.fetchImpl(`${this.baseUrl}/fbmain/monitor/v3/post_history`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify(body),
      }),
    );
  }
}
