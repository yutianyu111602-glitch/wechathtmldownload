import { createHash } from "node:crypto";
import { join, resolve } from "node:path";

import { normalizeArticleToken } from "../archive/normalizeArticleToken.js";
import {
  DEFAULT_MPTEXT_AUTH_KEY,
  DEFAULT_MPTEXT_BASE_URL,
  MptextClient,
  type MptextArticle,
  type MptextArticleListResponse,
} from "../mptext/client.js";
import {
  appendJsonlRecords,
  makeDownloadQueueId,
  readExistingQueueIds,
  toArchiveQueueRecord,
  writeJsonAtomic,
  type DownloadQueueRecord,
} from "../state/downloadQueueStore.js";
import { loadAccountInventory, type AccountInventoryEntry } from "./accountInventory.js";

const ARTICLE_PAGE_SIZE = 20;

type AccountPrefetchStatus =
  | "queued"
  | "listing"
  | "completed"
  | "failed"
  | "skipped";

export interface AccountUrlPrefetchAccountSnapshot {
  fakeid: string;
  nickname: string;
  status: AccountPrefetchStatus;
  estimatedSize: number;
  pagesFetched: number;
  discoveredCount: number;
  enqueuedCount: number;
  duplicateCount: number;
  currentBegin: number;
  stoppedReason: string;
  errorMessage: string;
  lastDiscoveredAt: string;
  startedAt: string;
  endedAt: string;
}

export interface AccountUrlPrefetchSnapshot {
  version: 1;
  status: "running" | "completed";
  invalidSession?: boolean;
  abortedReason?: string;
  sessionErrorMessage?: string;
  accountsPath: string;
  outDir: string;
  queuePath: string;
  statusPath: string;
  endpoint: string;
  startedAt: string;
  endedAt: string;
  totalAccounts: number;
  accountConcurrency: number;
  totalDiscovered: number;
  totalEnqueued: number;
  duplicateCount: number;
  failedCount: number;
  completedAccounts: number;
  accounts: AccountUrlPrefetchAccountSnapshot[];
}

export interface RunAccountUrlPrefetchOptions {
  accountsPath: string;
  outDir: string;
  queuePath?: string;
  statusPath?: string;
  endpoint?: string;
  key?: string;
  accountConcurrency?: number;
  maxPages?: number;
  limitAccounts?: number;
  resume?: boolean;
}

export interface RunAccountUrlPrefetchDependencies {
  client?: AccountUrlPrefetchClient;
  now?: () => string;
  onSnapshot?: (snapshot: AccountUrlPrefetchSnapshot) => void;
}

interface AccountUrlPrefetchClient {
  baseUrl?: string;
  validateAuthKey?: () => Promise<boolean>;
  getArticlePage(options: {
    fakeid: string;
    begin?: number;
    size?: number;
  }): Promise<MptextArticleListResponse>;
}

interface NormalizedArticleUrl {
  title: string;
  url: string;
  author: string;
  coverUrl: string;
  postTime: string;
  postDate: string;
  position: number | null;
}

function nowIso(now: (() => string) | undefined): string {
  return now ? now() : new Date().toISOString();
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
    return { postTime: "", postDate: "" };
  }

  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) {
    return { postTime: "", postDate: "" };
  }

  const postTime = date.toISOString().replace("T", " ").slice(0, 19);
  return {
    postTime,
    postDate: postTime.slice(0, 10),
  };
}

function normalizeArticleUrl(article: MptextArticle): NormalizedArticleUrl | null {
  const record = article as Record<string, unknown>;
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
    author: toStringValue(record.author_name),
    coverUrl:
      toStringValue(record.cover) ||
      toStringValue(record.cover_img) ||
      toStringValue(record.pic_cdn_url_1_1),
    postTime,
    postDate,
    position: toNumberValue(record.itemidx),
  };
}

function makePageFingerprint(items: NormalizedArticleUrl[]): string {
  return createHash("sha256")
    .update(JSON.stringify(items), "utf8")
    .digest("hex");
}

function createQueueRecord(options: {
  account: AccountInventoryEntry;
  accountKey: string;
  article: NormalizedArticleUrl;
  page: number;
  discoveredAt: string;
}): DownloadQueueRecord {
  return {
    queue_id: makeDownloadQueueId(options.account.fakeid, options.article.url),
    account_key: options.accountKey,
    account_fakeid: options.account.fakeid,
    account_nickname: options.account.nickname,
    token: normalizeArticleToken(options.article.url),
    source_url: options.article.url,
    title: options.article.title,
    author: options.article.author,
    cover_url: options.article.coverUrl,
    post_time: options.article.postTime,
    post_date: options.article.postDate,
    page: options.page,
    discovered_at: options.discoveredAt,
    discovery_source: "mptext-account-prefetch",
    status: "ready",
    attempt_count: 0,
    lease_owner: "",
    lease_expires_at: "",
    last_error: "",
  };
}

function createInitialSnapshot(options: {
  accountsPath: string;
  outDir: string;
  queuePath: string;
  statusPath: string;
  endpoint: string;
  accountConcurrency: number;
  accounts: AccountInventoryEntry[];
  startedAt: string;
}): AccountUrlPrefetchSnapshot {
  return {
    version: 1,
    status: "running",
    accountsPath: options.accountsPath,
    outDir: options.outDir,
    queuePath: options.queuePath,
    statusPath: options.statusPath,
    endpoint: options.endpoint,
    startedAt: options.startedAt,
    endedAt: "",
    totalAccounts: options.accounts.length,
    accountConcurrency: options.accountConcurrency,
    totalDiscovered: 0,
    totalEnqueued: 0,
    duplicateCount: 0,
    failedCount: 0,
    completedAccounts: 0,
    accounts: options.accounts.map((account) => ({
      fakeid: account.fakeid,
      nickname: account.nickname,
      status: "queued",
      estimatedSize:
        account.expectedArticleCount ||
        account.cachedArticleCount ||
        account.expectedMessageCount ||
        account.cachedMessageCount ||
        0,
      pagesFetched: 0,
      discoveredCount: 0,
      enqueuedCount: 0,
      duplicateCount: 0,
      currentBegin: 0,
      stoppedReason: "",
      errorMessage: "",
      lastDiscoveredAt: "",
      startedAt: "",
      endedAt: "",
    })),
  };
}

function recalculateSnapshot(snapshot: AccountUrlPrefetchSnapshot): void {
  snapshot.totalDiscovered = snapshot.accounts.reduce(
    (sum, account) => sum + account.discoveredCount,
    0,
  );
  snapshot.totalEnqueued = snapshot.accounts.reduce(
    (sum, account) => sum + account.enqueuedCount,
    0,
  );
  snapshot.duplicateCount = snapshot.accounts.reduce(
    (sum, account) => sum + account.duplicateCount,
    0,
  );
  snapshot.failedCount = snapshot.accounts.filter(
    (account) => account.status === "failed",
  ).length;
  snapshot.completedAccounts = snapshot.accounts.filter(
    (account) => account.status === "completed" || account.status === "skipped",
  ).length;
}

function limitAccounts(
  accounts: AccountInventoryEntry[],
  limit: number | undefined,
): AccountInventoryEntry[] {
  if (!limit || limit <= 0) {
    return accounts;
  }
  return accounts.slice(0, limit);
}

function isMptextInvalidSessionError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  const normalized = message.toLowerCase();
  return (
    normalized.includes("ret 200003") ||
    normalized.includes("invalid session")
  );
}

export async function runAccountUrlPrefetch(
  options: RunAccountUrlPrefetchOptions,
  dependencies: RunAccountUrlPrefetchDependencies = {},
): Promise<AccountUrlPrefetchSnapshot> {
  const accountsPath = resolve(options.accountsPath);
  const outDir = resolve(options.outDir);
  const queuePath = resolve(
    options.queuePath || join(outDir, "_queues", "download_ready_queue.jsonl"),
  );
  const statusPath = resolve(
    options.statusPath ||
      join(outDir, "_state", "account-url-prefetch-status.json"),
  );
  const endpoint =
    options.endpoint || process.env.MPTEXT_BASE_URL || DEFAULT_MPTEXT_BASE_URL;
  const key = options.key || DEFAULT_MPTEXT_AUTH_KEY;
  const accountConcurrency = Math.max(
    1,
    Math.min(options.accountConcurrency ?? 2, 8),
  );
  const maxPages = Math.max(1, options.maxPages ?? 200);
  const inventory = await loadAccountInventory(accountsPath);
  const accounts = limitAccounts(inventory.accounts, options.limitAccounts);
  const client =
    dependencies.client ||
    new MptextClient({
      baseUrl: endpoint,
      authKey: key,
    });

  if (client.validateAuthKey) {
    const valid = await client.validateAuthKey();
    if (!valid) {
      throw new Error("mptext auth key is invalid or expired");
    }
  }

  const existingQueueIds = options.resume
    ? await readExistingQueueIds(queuePath)
    : new Set<string>();
  const snapshot = createInitialSnapshot({
    accountsPath,
    outDir,
    queuePath,
    statusPath,
    endpoint: client.baseUrl || endpoint,
    accountConcurrency,
    accounts,
    startedAt: nowIso(dependencies.now),
  });

  let persistLock = Promise.resolve();
  async function persist(): Promise<void> {
    recalculateSnapshot(snapshot);
    persistLock = persistLock.then(async () => {
      await writeJsonAtomic(statusPath, snapshot);
      dependencies.onSnapshot?.(snapshot);
    });
    await persistLock;
  }

  let writeLock = Promise.resolve();
  async function appendRecords(
    account: AccountInventoryEntry,
    accountKey: string,
    records: DownloadQueueRecord[],
  ): Promise<void> {
    writeLock = writeLock.then(async () => {
      await appendJsonlRecords(queuePath, records);
      await appendJsonlRecords(
        join(outDir, "_queues", "accounts", accountKey, "archive_queue.jsonl"),
        records.map(toArchiveQueueRecord),
      );
      await writeJsonAtomic(
        join(outDir, "_queues", "accounts", accountKey, "account.json"),
        account,
      );
    });
    await writeLock;
  }

  await persist();

  let nextIndex = 0;
  let abortedReason = "";
  let sessionErrorMessage = "";
  const workerCount = Math.min(accountConcurrency, accounts.length);
  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (!abortedReason && nextIndex < accounts.length) {
        const accountIndex = nextIndex;
        nextIndex += 1;
        const account = accounts[accountIndex];
        const accountSnapshot = snapshot.accounts[accountIndex];
        if (!account || !accountSnapshot) {
          continue;
        }

        const accountKey =
          sanitizePathPart(account.nickname) ||
          sanitizePathPart(account.fakeid) ||
          account.fakeid;
        accountSnapshot.status = "listing";
        accountSnapshot.startedAt = nowIso(dependencies.now);
        await persist();

        try {
          const seenPageFingerprints = new Set<string>();
          let stoppedReason = "max-pages";

          for (let page = 1; page <= maxPages; page += 1) {
            const begin = (page - 1) * ARTICLE_PAGE_SIZE;
            accountSnapshot.currentBegin = begin;
            await persist();

            const payload = await client.getArticlePage({
              fakeid: account.fakeid,
              begin,
              size: ARTICLE_PAGE_SIZE,
            });
            const articles = (payload.articles || [])
              .map(normalizeArticleUrl)
              .filter((item): item is NormalizedArticleUrl => item !== null);
            const fingerprint = makePageFingerprint(articles);

            accountSnapshot.pagesFetched = page;
            if (seenPageFingerprints.has(fingerprint)) {
              stoppedReason = "repeated-page";
              break;
            }
            seenPageFingerprints.add(fingerprint);

            if (articles.length === 0) {
              stoppedReason = page === 1 ? "empty-page" : "no-more-items";
              break;
            }

            const discoveredAt = nowIso(dependencies.now);
            accountSnapshot.lastDiscoveredAt = discoveredAt;
            const newRecords: DownloadQueueRecord[] = [];
            for (const article of articles) {
              accountSnapshot.discoveredCount += 1;
              const record = createQueueRecord({
                account,
                accountKey,
                article,
                page,
                discoveredAt,
              });
              if (existingQueueIds.has(record.queue_id)) {
                accountSnapshot.duplicateCount += 1;
                continue;
              }
              existingQueueIds.add(record.queue_id);
              newRecords.push(record);
            }

            if (newRecords.length > 0) {
              accountSnapshot.enqueuedCount += newRecords.length;
              await appendRecords(account, accountKey, newRecords);
            }

            await persist();
            if (articles.length < ARTICLE_PAGE_SIZE) {
              stoppedReason = "no-more-items";
              break;
            }
          }

          accountSnapshot.status = "completed";
          accountSnapshot.stoppedReason = stoppedReason;
          accountSnapshot.endedAt = nowIso(dependencies.now);
          await persist();
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : String(error);
          accountSnapshot.status = "failed";
          accountSnapshot.errorMessage = errorMessage;
          accountSnapshot.endedAt = nowIso(dependencies.now);
          if (isMptextInvalidSessionError(error)) {
            abortedReason = "mptext-invalid-session";
            sessionErrorMessage = errorMessage;
            snapshot.invalidSession = true;
            snapshot.abortedReason = abortedReason;
            snapshot.sessionErrorMessage = sessionErrorMessage;
            accountSnapshot.stoppedReason = abortedReason;
            nextIndex = accounts.length;
          }
          await persist();
        }
      }
    }),
  );

  if (abortedReason) {
    for (const accountSnapshot of snapshot.accounts) {
      if (accountSnapshot.status !== "queued") {
        continue;
      }
      accountSnapshot.status = "skipped";
      accountSnapshot.stoppedReason = abortedReason;
      accountSnapshot.errorMessage = sessionErrorMessage;
      accountSnapshot.endedAt = nowIso(dependencies.now);
    }
    snapshot.invalidSession = abortedReason === "mptext-invalid-session";
    snapshot.abortedReason = abortedReason;
    snapshot.sessionErrorMessage = sessionErrorMessage;
  }

  snapshot.status = "completed";
  snapshot.endedAt = nowIso(dependencies.now);
  await persist();
  return snapshot;
}
