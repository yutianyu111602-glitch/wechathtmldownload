const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".json") return "application/json; charset=utf-8";
  if (ext === ".gz") return "application/gzip";
  if (ext === ".txt") return "text/plain; charset=utf-8";
  return "application/octet-stream";
}

function safeStaticPath(root, urlPath) {
  const decoded = decodeURIComponent(String(urlPath || "/").split("?")[0]);
  const relative = path.normalize(decoded).replace(/^[/\\]+/, "");
  const fullPath = path.resolve(root, relative || "current.json");
  const rootWithSep = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (fullPath !== root && !fullPath.startsWith(rootWithSep)) return null;
  return fullPath;
}

async function startStaticPackageServer(packageDir) {
  const root = path.resolve(String(packageDir || ""));
  if (!fs.existsSync(path.join(root, "current.json"))) {
    throw new Error(`MINIPROGRAM_STATIC_PACKAGE_DIR must contain current.json: ${root}`);
  }
  const server = http.createServer((req, res) => {
    const filePath = safeStaticPath(root, req.url || "/");
    if (!filePath || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      res.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ error: "not_found", path: req.url || "" }));
      return;
    }
    res.writeHead(200, {
      "Content-Type": contentTypeFor(filePath),
      "Cache-Control": "no-store",
    });
    fs.createReadStream(filePath).pipe(res);
  });
  const sockets = new Set();
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return {
    root,
    baseUrl: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(forceTimer);
        if (error) reject(error);
        else resolve();
      };
      const forceTimer = setTimeout(() => {
        for (const socket of sockets) socket.destroy();
        if (typeof server.closeAllConnections === "function") server.closeAllConnections();
        finish();
      }, 500);
      forceTimer.unref();
      server.close((error) => finish(error));
      if (typeof server.closeIdleConnections === "function") server.closeIdleConnections();
      for (const socket of sockets) socket.destroy();
    }),
  };
}

async function activateStaticPackage(miniProgram, staticBaseUrl) {
  if (!staticBaseUrl) return;
  await miniProgram.evaluate((injectedStaticBaseUrl) => {
    wx.clearStorageSync();
    const app = getApp();
    const cloud = app.globalData.cloud;
    const staticOnlyClient = {
      callContainer() {
        return Promise.reject({ error: { code: "DEVTOOLS_STATIC_PACKAGE_ONLY" } });
      },
      callFunction() {
        return Promise.reject({ error: { code: "DEVTOOLS_STATIC_PACKAGE_ONLY" } });
      },
    };
    cloud.useMock = false;
    cloud.devtoolsMockFallback = false;
    cloud.useCloudDatabaseFirst = false;
    cloud.publicBaseUrl = "";
    cloud.staticBaseUrl = injectedStaticBaseUrl;
    cloud.offlineSnapshotFallback = false;
    cloud.fastOfflineSnapshotFallback = false;
    cloud.publicFallbackDelayMs = 0;
    cloud.cloudClient = staticOnlyClient;
    cloud.cloudInitPromise = null;
    cloud.cloudReady = true;
    const pages = getCurrentPages();
    const current = pages[pages.length - 1];
    if (!current || typeof current.loadData !== "function") return null;
    current.isLoadingRequest = false;
    current.pendingLoadOptions = null;
    return current.loadData({ skipCache: true });
  }, staticBaseUrl);
}

module.exports = {
  activateStaticPackage,
  startStaticPackageServer,
};
