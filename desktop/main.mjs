import { app, BrowserWindow, dialog, ipcMain, shell } from "electron";
import { createReadStream, existsSync } from "node:fs";
import { access, readFile, readdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline/promises";
import { fileURLToPath } from "node:url";

import { runMarkitdownBatch } from "../dist/pipeline/runMarkitdownBatch.js";
import { runLlmExportBatch } from "../dist/pipeline/runLlmExportBatch.js";
import { runDualTrackBatch } from "../dist/pipeline/runDualTrackBatch.js";
import { runKeeperOnce } from "../dist/orchestrator/pipelineKeeper.js";
import { compactSnapshotItems } from "../dist/utils/snapshotCompaction.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

let mainWindow = null;
let currentBatchPromise = null;
let latestSnapshot = null;
let currentAbortController = null;

const DEFAULT_DISCOVERY_ROOT = "D:\\rawwechat";
const DEFAULT_ARCHIVE_ROOT = "D:\\rawwechat_archive";

async function pathExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readJsonFileSafe(filePath) {
  try {
    const raw = await readFile(filePath, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function countJsonlRecordsSafe(filePath) {
  try {
    const rl = createInterface({
      input: createReadStream(filePath, { encoding: "utf8" }),
      crlfDelay: Infinity,
    });

    let count = 0;
    for await (const line of rl) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      try {
        JSON.parse(trimmed);
        count += 1;
      } catch {
        // Ignore corrupt rows but keep scanning the rest of the JSONL file.
      }
    }
    return count;
  } catch {
    return 0;
  }
}

function normalizeCollectAccount(record) {
  if (!record || typeof record !== "object") {
    return null;
  }

  return {
    fakeid: String(record.fakeid || "").trim(),
    nickname: String(record.nickname || record.fakeid || "").trim(),
    status: String(record.status || (record.completed ? "completed" : "missing") || "missing"),
    pagesFetched: Number(record.pagesFetched || 0),
    discoveredCount: Number(record.discoveredCount || record.cachedArticleCount || 0),
    enqueuedCount: Number(record.enqueuedCount || 0),
    duplicateCount: Number(record.duplicateCount || 0),
    expectedArticleCount: Number(record.expectedArticleCount || 0),
    errorMessage: String(record.errorMessage || ""),
  };
}

async function scanHistoryRuns(rootDir) {
  const runs = [];
  if (!(await pathExists(rootDir))) {
    return runs;
  }

  let entries = [];
  try {
    entries = await readdir(rootDir, { withFileTypes: true });
  } catch {
    return runs;
  }

  for (const entry of entries) {
    if (!entry.isDirectory() || !entry.name.startsWith("history_")) {
      continue;
    }

    const outDir = join(rootDir, entry.name);
    const historyJsonPath = join(outDir, "history_urls.json");
    const archiveQueuePath = join(outDir, "archive_queue.jsonl");
    const historyJson = await readJsonFileSafe(historyJsonPath);
    const archiveQueueCount = await countJsonlRecordsSafe(archiveQueuePath);
    const uniqueUrlCount = Array.isArray(historyJson?.items)
      ? historyJson.items.length
      : Array.isArray(historyJson?.articles)
        ? historyJson.articles.length
        : archiveQueueCount;

    runs.push({
      name: entry.name,
      outDir,
      uniqueUrlCount,
      pagesFetched: Number(historyJson?.pages_fetched || historyJson?.pagesFetched || 0),
      stoppedReason: String(historyJson?.stopped_reason || historyJson?.stoppedReason || ""),
      archiveQueuePath,
    });
  }

  runs.sort((left, right) => right.name.localeCompare(left.name));
  return runs.slice(0, 8);
}

async function getCollectState(options = {}) {
  const rootDir = options.rootDir || DEFAULT_DISCOVERY_ROOT;
  const accountsPath = options.accountsPath || "";
  const statusPath = join(rootDir, "_state", "account-url-prefetch-status.json");
  const queuePath = join(rootDir, "_queues", "download_ready_queue.jsonl");
  const warnings = [];

  const prefetchStatus = await readJsonFileSafe(statusPath);
  const queueRecordCount = await countJsonlRecordsSafe(queuePath);
  const historyRuns = await scanHistoryRuns(rootDir);
  const accountInventory = accountsPath ? await readJsonFileSafe(accountsPath) : null;

  let accounts = [];
  if (Array.isArray(prefetchStatus?.accounts)) {
    accounts = prefetchStatus.accounts.map(normalizeCollectAccount).filter(Boolean);
  } else if (Array.isArray(accountInventory?.accounts)) {
    accounts = accountInventory.accounts.map(normalizeCollectAccount).filter(Boolean);
  }

  if (!accounts.length && !historyRuns.length && !queueRecordCount) {
    warnings.push("未发现账号状态、队列或 history 结果。采集与账号工作区当前只能显示空骨架。");
  }

  return {
    status: prefetchStatus?.status || (accounts.length || historyRuns.length || queueRecordCount ? "partial" : "missing"),
    sources: {
      rootDir: { path: rootDir, exists: await pathExists(rootDir) },
      accountsPath: { path: accountsPath, exists: accountsPath ? await pathExists(accountsPath) : false },
      prefetchStatusPath: { path: statusPath, exists: await pathExists(statusPath) },
      queuePath: { path: queuePath, exists: await pathExists(queuePath) },
    },
    summary: {
      totalAccounts: Number(prefetchStatus?.totalAccounts || accounts.length),
      completedAccounts: Number(prefetchStatus?.completedAccounts || accounts.filter((item) => item.status === "completed" || item.status === "skipped").length),
      totalDiscovered: Number(prefetchStatus?.totalDiscovered || 0),
      totalEnqueued: Number(prefetchStatus?.totalEnqueued || 0),
      duplicateCount: Number(prefetchStatus?.duplicateCount || 0),
      failedCount: Number(prefetchStatus?.failedCount || accounts.filter((item) => item.status === "failed").length),
      readyQueueCount: queueRecordCount,
      historyRunCount: historyRuns.length,
    },
    accounts,
    historyRuns,
    warnings,
  };
}

async function scanArchiveBundles(archiveRoot, itemsByToken) {
  const bundles = [];
  if (!(await pathExists(archiveRoot))) {
    return bundles;
  }

  let accountDirs = [];
  try {
    accountDirs = await readdir(archiveRoot, { withFileTypes: true });
  } catch {
    return bundles;
  }

  for (const accountDir of accountDirs) {
    if (!accountDir.isDirectory()) {
      continue;
    }

    const accountPath = join(archiveRoot, accountDir.name);
    let tokenDirs = [];
    try {
      tokenDirs = await readdir(accountPath, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const tokenDir of tokenDirs) {
      if (!tokenDir.isDirectory()) {
        continue;
      }

      const outDir = join(accountPath, tokenDir.name);
      const [
        hasRawHtml,
        hasMhtml,
        hasPdf,
        hasArticleUrl,
        hasArchiveMeta,
        hasAssetsLocal,
      ] = await Promise.all([
        pathExists(join(outDir, "raw.html")),
        pathExists(join(outDir, "page.mhtml")),
        pathExists(join(outDir, "page.pdf")),
        pathExists(join(outDir, "article.url.txt")),
        pathExists(join(outDir, "archive_meta.json")),
        pathExists(join(outDir, "assets_local.json")),
      ]);

      const token = tokenDir.name;
      const archiveMeta = hasArchiveMeta
        ? await readJsonFileSafe(join(outDir, "archive_meta.json"))
        : null;
      const assetsLocal = hasAssetsLocal
        ? await readJsonFileSafe(join(outDir, "assets_local.json"))
        : null;
      const archiveItem = itemsByToken.get(token) || null;

      bundles.push({
        token,
        accountKey: archiveItem?.accountKey || archiveMeta?.account_key || accountDir.name,
        sourceUrl: archiveItem?.sourceUrl || archiveMeta?.source_url || "",
        outDir,
        archiveStatus: archiveItem?.status || (hasArchiveMeta ? archiveMeta?.status || "partial" : "missing"),
        assetStatus: hasAssetsLocal ? "succeeded" : "missing",
        captureComplete: hasRawHtml && hasMhtml && hasPdf && hasArticleUrl && hasArchiveMeta,
        assetsComplete: hasAssetsLocal,
        files: {
          hasRawHtml,
          hasMhtml,
          hasPdf,
          hasArticleUrl,
          hasArchiveMeta,
          hasAssetsLocal,
        },
        imageCount: Array.isArray(assetsLocal?.images) ? assetsLocal.images.length : 0,
        mediaCount: Array.isArray(assetsLocal?.media) ? assetsLocal.media.length : 0,
        message: archiveItem?.message || "",
      });
    }
  }

  bundles.sort((left, right) => left.token.localeCompare(right.token));
  return bundles.slice(0, 80);
}

async function getArchiveState(options = {}) {
  const archiveRoot = options.archiveRoot || DEFAULT_ARCHIVE_ROOT;
  const statusPath = join(archiveRoot, "archive-status.json");
  const assetStatusPath = join(archiveRoot, "asset-retention-status.json");
  const warnings = [];

  const archiveStatus = await readJsonFileSafe(statusPath);
  const assetStatus = await readJsonFileSafe(assetStatusPath);
  const archiveItems = Array.isArray(archiveStatus?.items) ? archiveStatus.items : [];
  const itemsByToken = new Map(archiveItems.map((item) => [String(item.token || ""), item]));
  const bundles = await scanArchiveBundles(archiveRoot, itemsByToken);

  if (!archiveItems.length && !bundles.length) {
    warnings.push("未发现 archive-status.json 或 bundle 目录。归档与下载工作区当前只能显示空骨架。");
  }

  return {
    status: archiveStatus?.status || (bundles.length ? "partial" : "missing"),
    sources: {
      archiveRoot: { path: archiveRoot, exists: await pathExists(archiveRoot) },
      archiveStatusPath: { path: statusPath, exists: await pathExists(statusPath) },
      assetStatusPath: { path: assetStatusPath, exists: await pathExists(assetStatusPath) },
    },
    summary: {
      archive: {
        totalItems: Number(archiveStatus?.totalItems || bundles.length),
        queuedCount: Number(archiveStatus?.queuedCount || 0),
        runningCount: Number(archiveStatus?.runningCount || 0),
        succeededCount: Number(archiveStatus?.succeededCount || 0),
        failedCount: Number(archiveStatus?.failedCount || 0),
        skippedCount: Number(archiveStatus?.skippedCount || 0),
      },
      assets: {
        totalItems: Number(assetStatus?.totalItems || bundles.length),
        succeededCount: Number(assetStatus?.succeededCount || 0),
        failedCount: Number(assetStatus?.failedCount || 0),
        skippedCount: Number(assetStatus?.skippedCount || 0),
      },
      bundles: {
        seen: bundles.length,
        withRawHtml: bundles.filter((item) => item.files.hasRawHtml).length,
        withMhtml: bundles.filter((item) => item.files.hasMhtml).length,
        withPdf: bundles.filter((item) => item.files.hasPdf).length,
        withArticleUrl: bundles.filter((item) => item.files.hasArticleUrl).length,
        withArchiveMeta: bundles.filter((item) => item.files.hasArchiveMeta).length,
        withAssetsLocal: bundles.filter((item) => item.files.hasAssetsLocal).length,
      },
    },
    items: bundles,
    warnings,
  };
}

function getAppRoot() {
  return app.getAppPath();
}

function getDesktopAssetPath(...parts) {
  return join(getAppRoot(), "desktop", ...parts);
}

function getWindowIconPath() {
  return getDesktopAssetPath("assets", "app.ico");
}

function resolveRuntimePython() {
  const candidates = [
    process.env.MARKITDOWN_PYTHON,
    join(process.resourcesPath, "markitdown-runtime", ".venv", "Scripts", "python.exe"),
    join(getAppRoot(), "vendor", "markitdown-runtime", ".venv", "Scripts", "python.exe"),
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }

  return "";
}

function configureBundledRuntimeEnv() {
  const pythonPath = resolveRuntimePython();
  if (!pythonPath) {
    return;
  }

  process.env.MARKITDOWN_PYTHON = pythonPath;
  process.env.MARKITDOWN_CWD = process.env.MARKITDOWN_CWD || dirname(dirname(pythonPath));
}

function sendSnapshot(snapshot) {
  const visibleSnapshot = Array.isArray(snapshot?.items)
    ? compactSnapshotItems(snapshot)
    : snapshot;
  latestSnapshot = visibleSnapshot;
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send("batch:snapshot", visibleSnapshot);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1280,
    minHeight: 760,
    backgroundColor: "#0f141b",
    title: "WeChat History HTML Pipeline",
    icon: getWindowIconPath(),
    webPreferences: {
      preload: getDesktopAssetPath("preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(getDesktopAssetPath("index.html"));
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

ipcMain.handle("dialog:pick-directory", async (_event, defaultPath) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    defaultPath: defaultPath || undefined,
    properties: ["openDirectory", "createDirectory"],
  });

  if (result.canceled || result.filePaths.length === 0) {
    return "";
  }

  return result.filePaths[0] || "";
});

ipcMain.handle("app:open-path", async (_event, filePath) => {
  if (!filePath) {
    return;
  }
  await shell.openPath(filePath);
});

ipcMain.handle("batch:get-latest-snapshot", async () => latestSnapshot);
ipcMain.handle("collect:get-state", async (_event, options) => getCollectState(options || {}));
ipcMain.handle("archive:get-state", async (_event, options) => getArchiveState(options || {}));

ipcMain.handle("batch:start", async (_event, payload) => {
  if (currentBatchPromise) {
    return { accepted: false, message: "A batch run is already active." };
  }

  configureBundledRuntimeEnv();

  const inputRoot = payload?.inputRoot || "";
  const outRoot = payload?.outRoot || "";
  const resume = Boolean(payload?.resume);
  const pipeline = payload?.pipeline === "markitdown-mirror"
    ? "markitdown-mirror"
    : payload?.pipeline === "llm-export"
      ? "llm-export"
      : payload?.pipeline === "keeper"
        ? "keeper"
        : "dual-track";
  const mirrorRoot = payload?.mirrorRoot || "";

  if (!inputRoot || !outRoot) {
    return { accepted: false, message: "Both input and output folders are required." };
  }

  currentAbortController = new AbortController();

  if (pipeline === "keeper") {
    currentBatchPromise = runKeeperOnce({
      inputRoot,
      outRoot,
      resume,
      signal: currentAbortController.signal,
      onSnapshot: async (projection) => {
        sendSnapshot({ ...projection, mirrorRoot });
      },
      onProgress: (message) => {
        console.log("[keeper]", message);
      },
    })
      .catch((error) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send("batch:error", error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        currentBatchPromise = null;
        currentAbortController = null;
      });

    return { accepted: true, message: "Keeper started." };
  }

  const runner = pipeline === "markitdown-mirror"
    ? runMarkitdownBatch
    : pipeline === "llm-export"
      ? runLlmExportBatch
      : runDualTrackBatch;

  const runnerOptions = {
    inputRoot,
    outRoot,
    resume,
    signal: currentAbortController.signal,
    onSnapshot: async (snapshot) => {
      sendSnapshot({ ...snapshot, pipeline, mirrorRoot });
    },
  };

  currentBatchPromise = (pipeline === "llm-export"
    ? runner({ ...runnerOptions, mirrorRoot })
    : runner(runnerOptions))
    .catch((error) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("batch:error", error instanceof Error ? error.message : String(error));
      }
    })
    .finally(() => {
      currentBatchPromise = null;
      currentAbortController = null;
    });

  return { accepted: true, message: "Batch started." };
});

ipcMain.handle("batch:cancel", async () => {
  if (!currentAbortController || currentAbortController.signal.aborted) {
    return { accepted: false, message: "No active batch to cancel." };
  }

  currentAbortController.abort();
  return { accepted: true, message: "Cancellation requested." };
});

app.whenReady().then(() => {
  configureBundledRuntimeEnv();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
