const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const apiPath = path.resolve(__dirname, "../utils/api.js");

function response(id) {
  return {
    statusCode: 200,
    data: {
      generatedAt: "2026-07-19T08:00:00Z",
      filters: { scope: "current" },
      items: [{ id }],
      page: { cursor: 0, nextCursor: null, total: 1 },
    },
  };
}

test("inflight dedupe keeps request controls semantic without uploading or persisting them", async () => {
  const calls = [];
  const pending = [];
  const storedKeys = [];
  const cloudClient = {
    callContainer(options) {
      calls.push(options);
      return new Promise((resolve) => pending.push(resolve));
    },
  };
  global.wx = {
    cloud: cloudClient,
    getStorageSync() {
      return null;
    },
    setStorageSync(key) {
      storedKeys.push(key);
    },
  };
  global.getApp = () => ({
    globalData: {
      cloud: {
        env: "unit-test-env",
        service: "weekly-api",
        cloudClient,
        offlineSnapshotFallback: false,
        cacheFallbackDelayMs: 0,
        cloudInitTimeoutMs: 1000,
        cloudCallTimeoutMs: 1000,
      },
    },
  });
  delete require.cache[apiPath];
  const { requestApi } = require(apiPath);

  const ordinary = requestApi("/api/v1/weekly/current", { limit: 1 });
  const skipStored = requestApi("/api/v1/weekly/current", { limit: 1, __skipCache: true });
  const liveOnly = requestApi("/api/v1/weekly/current", { limit: 1, __liveOnly: true });
  const sameLiveOnly = requestApi("/api/v1/weekly/current", { limit: 1, __liveOnly: true });
  const liveRefresh = requestApi("/api/v1/weekly/current", { limit: 1, __liveRefresh: true });
  const sameLiveRefresh = requestApi("/api/v1/weekly/current", { limit: 1, __liveRefresh: true });

  await new Promise((resolve) => setImmediate(resolve));
  pending.forEach((resolve, index) => resolve(response(`event-${index}`)));
  await Promise.all([ordinary, skipStored, liveOnly, sameLiveOnly, liveRefresh, sameLiveRefresh]);

  assert.notStrictEqual(ordinary, skipStored);
  assert.notStrictEqual(skipStored, liveOnly);
  assert.notStrictEqual(ordinary, liveOnly);
  assert.notStrictEqual(ordinary, liveRefresh);
  assert.notStrictEqual(liveOnly, liveRefresh);
  assert.strictEqual(liveOnly, sameLiveOnly);
  assert.strictEqual(liveRefresh, sameLiveRefresh);
  assert.equal(calls.length, 4);
  assert.ok(calls.every((call) => !call.path.includes("__skipCache")));
  assert.ok(calls.every((call) => !call.path.includes("__liveOnly")));
  assert.ok(calls.every((call) => !call.path.includes("__liveRefresh")));
  assert.equal(new Set(storedKeys).size, 1);
});
