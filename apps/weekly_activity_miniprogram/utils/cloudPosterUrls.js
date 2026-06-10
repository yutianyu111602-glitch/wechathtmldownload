const CLOUD_FILE_ID_RE = /^(?:cloud|cloudbase):\/\//i;
const MAX_BATCH_SIZE = 50;
const DEFAULT_TIMEOUT_MS = 5000;

const tempUrlCache = new Map();
const downloadedFileCache = new Map();

function isCloudFileId(value) {
  return CLOUD_FILE_ID_RE.test(String(value || "").trim());
}

function firstMeaningful(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) return text;
  }
  return "";
}

function withTimeout(promise, timeoutMs, label) {
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(label)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) clearTimeout(timer);
  });
}

function cloudClient() {
  if (typeof wx !== "undefined" && wx.cloud && typeof wx.cloud.getTempFileURL === "function") {
    var app = null;
    try { app = getApp(); } catch (e) {}
    var cloudData = (app && app.globalData && app.globalData.cloud) || {};
    if (cloudData.cloudReady) return Promise.resolve(wx.cloud);
    if (cloudData.cloudInitPromise) {
      return cloudData.cloudInitPromise.then(function () { return wx.cloud; });
    }
    return Promise.resolve(wx.cloud);
  }
  try {
    if (typeof getApp !== "function") return Promise.reject(new Error("CLOUD_CLIENT_MISSING"));
    const cloud = getApp()?.globalData?.cloud || {};
    if (cloud.cloudClient && typeof cloud.cloudClient.getTempFileURL === "function") {
      return Promise.resolve(cloud.cloudClient);
    }
    if (cloud.cloudInitPromise) {
      return cloud.cloudInitPromise.then((client) => {
        if (client && typeof client.getTempFileURL === "function") return client;
        throw new Error("CLOUD_CLIENT_MISSING");
      });
    }
  } catch {}
  return Promise.reject(new Error("CLOUD_CLIENT_MISSING"));
}

async function cloudClientWith(methodName) {
  const client = await cloudClient();
  if (!client || typeof client[methodName] !== "function") {
    throw new Error("CLOUD_CLIENT_METHOD_MISSING");
  }
  return client;
}

function getTempFileURL(client, fileList, timeoutMs) {
  return withTimeout(new Promise((resolve, reject) => {
    client.getTempFileURL({
      fileList,
      success: resolve,
      fail: reject,
    });
  }), timeoutMs, "GET_TEMP_FILE_URL_TIMEOUT");
}

function downloadFile(client, fileID, timeoutMs) {
  return withTimeout(new Promise((resolve, reject) => {
    client.downloadFile({
      fileID,
      success: resolve,
      fail: reject,
    });
  }), timeoutMs, "CLOUD_DOWNLOAD_FILE_TIMEOUT");
}

function cloudFileIdToHttpUrl(fileId) {
  const urls = cloudFileIdToHttpUrls(fileId);
  return Array.isArray(urls) && urls.length > 0 ? urls[0] : "";
}

function cloudFileIdToHttpUrls(fileId) {
  const text = String(fileId || "").trim();
  const match = text.match(/^cloud:\/\/([^.]+)\.([^/]+)\/(.+)$/);
  if (!match) return [];
  const env = match[1];
  const appId = match[2];
  const filePath = match[3];
  return [
    `https://${env}.tcb.qcloud.la/${encodeURIComponent(filePath).replace(/%2F/g, "/")}`,
    `https://${appId}.tcb.qcloud.la/${encodeURIComponent(filePath).replace(/%2F/g, "/")}`,
    `https://${env}.tcloudbaseapp.com/${encodeURIComponent(filePath).replace(/%2F/g, "/")}`,
  ];
}

async function resolveCloudFileUrls(fileIds, options = {}) {
  const timeoutMs = Math.max(500, Number(options.timeoutMs || DEFAULT_TIMEOUT_MS));
  const unique = [];
  const seen = new Set();
  for (const fileId of fileIds || []) {
    const text = String(fileId || "").trim();
    if (!isCloudFileId(text) || seen.has(text)) continue;
    seen.add(text);
    if (!tempUrlCache.has(text)) unique.push(text);
  }
  if (!unique.length) {
    const cached = {};
    for (const fileId of seen) {
      const tempUrl = tempUrlCache.get(fileId);
      if (tempUrl) cached[fileId] = tempUrl;
    }
    return cached;
  }

  let client = null;
  var usedHttpFallback = false;
  try {
    client = await cloudClient();
  } catch {
    usedHttpFallback = true;
  }

  if (usedHttpFallback || !client) {
    const resolved = {};
    for (const fileId of unique) {
      const urls = cloudFileIdToHttpUrls(fileId);
      const httpUrl = urls[0] || "";
      if (httpUrl) {
        tempUrlCache.set(fileId, httpUrl);
        resolved[fileId] = httpUrl;
      }
    }
    return resolved;
  }

  for (let index = 0; index < unique.length; index += MAX_BATCH_SIZE) {
    const batch = unique.slice(index, index + MAX_BATCH_SIZE);
    try {
      const response = await getTempFileURL(client, batch, timeoutMs);
      const rows = Array.isArray(response && response.fileList) ? response.fileList : [];
      for (const row of rows) {
        const fileID = String(row && row.fileID || "").trim();
        const tempFileURL = String(row && row.tempFileURL || "").trim();
        if (fileID && tempFileURL && Number(row.status || 0) === 0) {
          tempUrlCache.set(fileID, tempFileURL);
        }
      }
    } catch {}
  }

  // Fallback: for any fileIds not resolved via getTempFileURL, try HTTP URLs
  for (const fileId of unique) {
    if (tempUrlCache.has(fileId)) continue;
    const urls = cloudFileIdToHttpUrls(fileId);
    const httpUrl = urls[0] || "";
    if (httpUrl) {
      tempUrlCache.set(fileId, httpUrl);
    }
  }

  const resolved = {};
  for (const fileId of seen) {
    const tempUrl = tempUrlCache.get(fileId);
    if (tempUrl) resolved[fileId] = tempUrl;
  }
  return resolved;
}

function posterFileIdForItem(item = {}) {
  return firstMeaningful(
    item.posterFileId,
    item.poster_file_id,
    item.cloudFileId,
    item.cloud_file_id,
    item.coverFileId,
    item.cover_file_id,
    isCloudFileId(item.coverUrl) ? item.coverUrl : "",
  );
}

async function resolvePosterUrlsForItems(items, options = {}) {
  const list = Array.isArray(items) ? items : [];
  const fileIds = list
    .map((item) => posterFileIdForItem(item))
    .filter(isCloudFileId);
  if (!fileIds.length) return list;
  const resolved = await resolveCloudFileUrls(fileIds, options);
  if (!Object.keys(resolved).length) return list;
  return list.map((item) => {
    const fileId = posterFileIdForItem(item);
    const tempUrl = resolved[fileId];
    if (!tempUrl) {
      return fileId && !item.posterFileId ? { ...item, posterFileId: fileId } : item;
    }
    return {
      ...item,
      posterFileId: fileId,
      posterTempUrl: tempUrl,
      coverUrl: tempUrl,
      posterLoadFailed: false,
    };
  });
}

async function resolvePosterUrlForItem(item, options = {}) {
  if (!item || typeof item !== "object") return item;
  const resolved = await resolvePosterUrlsForItems([item], options);
  return resolved[0] || item;
}

function cloudFileIdFallback(item = {}, currentSrc = "") {
  const fileId = posterFileIdForItem(item);
  if (!isCloudFileId(fileId)) return "";
  if (String(currentSrc || "").trim() === fileId) return "";
  return fileId;
}

async function downloadCloudFileToTempPath(fileId, options = {}) {
  const text = String(fileId || "").trim();
  if (!isCloudFileId(text)) return "";
  const cached = downloadedFileCache.get(text);
  if (cached) return cached;
  const timeoutMs = Math.max(500, Number(options.timeoutMs || DEFAULT_TIMEOUT_MS));
  try {
    const client = await cloudClientWith("downloadFile");
    const response = await downloadFile(client, text, timeoutMs);
    const tempFilePath = String(response && response.tempFilePath || "").trim();
    if (tempFilePath) {
      downloadedFileCache.set(text, tempFilePath);
      return tempFilePath;
    }
  } catch {}
  return "";
}

async function posterImageErrorFallback(item = {}, currentSrc = "", options = {}) {
  const fileId = cloudFileIdFallback(item, currentSrc);
  if (!fileId) return "";
  if (!item.posterDownloadFallbackTried) {
    const tempFilePath = await downloadCloudFileToTempPath(fileId, options);
    if (tempFilePath && String(currentSrc || "").trim() !== tempFilePath) {
      return tempFilePath;
    }
  }
  if (!item.posterFileIdFallbackTried) return fileId;
  return "";
}

function posterFallbackState(item = {}, fallback = "") {
  const coverUrl = String(fallback || "").trim();
  const fileId = posterFileIdForItem(item);
  const isCloudFallback = isCloudFileId(coverUrl);
  return {
    coverUrl,
    posterFileId: fileId || (isCloudFallback ? coverUrl : ""),
    posterDownloadFallbackTried: Boolean(coverUrl && !isCloudFallback),
    posterFileIdFallbackTried: Boolean(coverUrl && isCloudFallback),
    posterLoadFailed: false,
  };
}

function clearTempUrlCache() {
  tempUrlCache.clear();
  downloadedFileCache.clear();
}

module.exports = {
  cloudFileIdFallback,
  clearTempUrlCache,
  downloadCloudFileToTempPath,
  isCloudFileId,
  posterFallbackState,
  posterImageErrorFallback,
  posterFileIdForItem,
  resolveCloudFileUrls,
  resolvePosterUrlForItem,
  resolvePosterUrlsForItems,
};
