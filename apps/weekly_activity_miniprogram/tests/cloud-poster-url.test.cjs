const assert = require("node:assert/strict");
const test = require("node:test");

const {
  clearTempUrlCache,
  cloudFileIdFallback,
  downloadCloudFileToTempPath,
  isCloudFileId,
  posterFallbackState,
  posterImageErrorFallback,
  resolvePosterUrlForItem,
  resolvePosterUrlsForItems,
} = require("../utils/cloudPosterUrls");

test.afterEach(() => {
  clearTempUrlCache();
  delete global.wx;
  delete global.getApp;
});

test("resolves CloudBase poster file IDs to temp URLs and preserves original fileId", async () => {
  global.wx = {
    cloud: {
      getTempFileURL({ fileList, success }) {
        success({
          fileList: fileList.map((fileID) => ({
            fileID,
            status: 0,
            tempFileURL: `https://temp.example.test/${encodeURIComponent(fileID)}`,
          })),
        });
      },
    },
  };

  const fileId = "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/main.jpg";
  const [item] = await resolvePosterUrlsForItems([{ id: "one", coverUrl: fileId }]);

  assert.equal(item.posterFileId, fileId);
  assert.match(item.coverUrl, /^https:\/\/temp\.example\.test\//);
  assert.equal(item.posterLoadFailed, false);
});

test("resolves backend cloudFileId weekly-posters package field to temp URL", async () => {
  global.wx = {
    cloud: {
      getTempFileURL({ fileList, success }) {
        success({
          fileList: fileList.map((fileID) => ({
            fileID,
            status: 0,
            tempFileURL: `https://temp.example.test/${encodeURIComponent(fileID)}`,
          })),
        });
      },
    },
  };

  const fileId = "cloud://atlas-prod.6174-atlas-prod-1250000000/weekly-posters/20260606/main.jpg";
  const [item] = await resolvePosterUrlsForItems([{ id: "cloud-id-only", cloudFileId: fileId }]);

  assert.equal(item.cloudFileId, fileId);
  assert.equal(item.posterFileId, fileId);
  assert.match(item.coverUrl, /^https:\/\/temp\.example\.test\//);
  assert.equal(item.posterLoadFailed, false);
});

test("falls back to HTTP URL when temp URL resolving fails", async () => {
  global.wx = {
    cloud: {
      getTempFileURL({ fail }) {
        fail({ errMsg: "mock fail" });
      },
    },
  };

  const fileId = "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/fallback.jpg";
  const item = await resolvePosterUrlForItem({ id: "one", coverUrl: fileId });

  assert.equal(item.coverUrl, "https://atlas-prod.tcb.qcloud.la/posters/fallback.jpg");
});

test("cloud fallback only retries once from temp URL back to original file ID", () => {
  const fileId = "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/fallback.jpg";
  assert.equal(isCloudFileId(fileId), true);
  assert.equal(
    cloudFileIdFallback({ posterFileId: fileId, coverUrl: "https://temp.example.test/fallback.jpg" }, "https://temp.example.test/fallback.jpg"),
    fileId,
  );
  assert.equal(cloudFileIdFallback({ posterFileId: fileId, coverUrl: fileId }, fileId), "");
});

test("poster image error fallback downloads CloudBase file before retrying file ID", async () => {
  const fileId = "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/download.jpg";
  global.wx = {
    cloud: {
      getTempFileURL({ fail }) {
        fail({ errMsg: "unused" });
      },
      downloadFile({ fileID, success }) {
        success({ tempFilePath: `wxfile://tmp/${encodeURIComponent(fileID)}.jpg` });
      },
    },
  };

  const tempPath = await downloadCloudFileToTempPath(fileId);
  assert.match(tempPath, /^wxfile:\/\/tmp\//);

  const fallback = await posterImageErrorFallback(
    { posterFileId: fileId, coverUrl: "https://temp.example.test/download.jpg" },
    "https://temp.example.test/download.jpg",
  );
  assert.match(fallback, /^wxfile:\/\/tmp\//);
});

test("poster fallback state keeps original file ID after local temp download", () => {
  const fileId = "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/download.jpg";
  const state = posterFallbackState(
    { poster_file_id: fileId, coverUrl: "https://temp.example.test/download.jpg" },
    "wxfile://tmp/download.jpg",
  );

  assert.equal(state.coverUrl, "wxfile://tmp/download.jpg");
  assert.equal(state.posterFileId, fileId);
  assert.equal(state.posterDownloadFallbackTried, true);
  assert.equal(state.posterFileIdFallbackTried, false);
  assert.equal(state.posterLoadFailed, false);
});

test("poster fallback state marks final cloud file ID retry", () => {
  const fileId = "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/fileid.jpg";
  const state = posterFallbackState({ coverUrl: "https://temp.example.test/fileid.jpg" }, fileId);

  assert.equal(state.coverUrl, fileId);
  assert.equal(state.posterFileId, fileId);
  assert.equal(state.posterDownloadFallbackTried, false);
  assert.equal(state.posterFileIdFallbackTried, true);
});

test("poster image error fallback retries file ID when cloud download fails", async () => {
  const fileId = "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/fileid.jpg";
  global.wx = {
    cloud: {
      getTempFileURL({ fail }) {
        fail({ errMsg: "unused" });
      },
      downloadFile({ fail }) {
        fail({ errMsg: "mock download fail" });
      },
    },
  };

  const fallback = await posterImageErrorFallback(
    { posterFileId: fileId, coverUrl: "https://temp.example.test/fileid.jpg" },
    "https://temp.example.test/fileid.jpg",
  );
  assert.equal(fallback, fileId);
});
