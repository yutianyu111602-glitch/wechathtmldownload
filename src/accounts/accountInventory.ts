import { readFile } from "node:fs/promises";

export interface AccountInventoryEntry {
  fakeid: string;
  nickname: string;
  completed: boolean;
  cachedMessageCount: number;
  cachedArticleCount: number;
  expectedMessageCount: number;
  expectedArticleCount: number;
  roundHeadImg: string;
  createTime: number;
  updateTime: number;
  lastUpdateTime: number;
}

export interface AccountInventory {
  version: string;
  usefor: string;
  accounts: AccountInventoryEntry[];
  summary: {
    accountCount: number;
    completedAccounts: number;
    incompleteAccounts: number;
    cachedArticleCount: number;
    expectedArticleCount: number;
    expectedMessageCount: number;
  };
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

function toNumberValue(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function normalizeAccount(value: unknown): AccountInventoryEntry | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const record = value as Record<string, unknown>;
  const fakeid = toStringValue(record.fakeid);
  const nickname = toStringValue(record.nickname) || fakeid;
  if (!fakeid || !nickname) {
    return null;
  }

  return {
    fakeid,
    nickname,
    completed: Boolean(record.completed),
    cachedMessageCount: toNumberValue(record.count),
    cachedArticleCount: toNumberValue(record.articles),
    expectedMessageCount: toNumberValue(record.total_count || record.count),
    expectedArticleCount: toNumberValue(record.articles),
    roundHeadImg: toStringValue(record.round_head_img),
    createTime: toNumberValue(record.create_time),
    updateTime: toNumberValue(record.update_time),
    lastUpdateTime: toNumberValue(record.last_update_time),
  };
}

export async function loadAccountInventory(
  filePath: string,
): Promise<AccountInventory> {
  const raw = JSON.parse(await readFile(filePath, "utf8")) as Record<
    string,
    unknown
  >;
  const accounts = Array.isArray(raw.accounts)
    ? raw.accounts
        .map(normalizeAccount)
        .filter((item): item is AccountInventoryEntry => item !== null)
    : [];

  return {
    version: toStringValue(raw.version),
    usefor: toStringValue(raw.usefor),
    accounts,
    summary: {
      accountCount: accounts.length,
      completedAccounts: accounts.filter((item) => item.completed).length,
      incompleteAccounts: accounts.filter((item) => !item.completed).length,
      cachedArticleCount: accounts.reduce(
        (sum, item) => sum + item.cachedArticleCount,
        0,
      ),
      expectedArticleCount: accounts.reduce(
        (sum, item) => sum + item.expectedArticleCount,
        0,
      ),
      expectedMessageCount: accounts.reduce(
        (sum, item) => sum + item.expectedMessageCount,
        0,
      ),
    },
  };
}
