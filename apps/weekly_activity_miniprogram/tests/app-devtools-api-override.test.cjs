const assert = require("node:assert/strict");
const test = require("node:test");
const path = require("node:path");

const appPath = path.resolve(__dirname, "../app.js");

function loadAppWithWx({ platform = "devtools", override = null } = {}) {
  let appConfig = null;
  let cloudInitCount = 0;
  const storage = new Map();
  if (override) storage.set("weeklyActivityDevtoolsApiOverride:v1", override);

  delete require.cache[appPath];
  global.App = (config) => { appConfig = config; };
  global.wx = {
    getStorageSync(key) {
      return storage.get(key) || "";
    },
    removeStorageSync(key) {
      storage.delete(key);
    },
    setTabBarItem() {},
    setNavigationBarTitle() {},
    setBackgroundColor() {},
    setBackgroundTextStyle() {},
    showTabBarRedDot() {},
    getSystemInfoSync() {
      return { platform };
    },
    cloud: {
      init() {
        cloudInitCount += 1;
        return { initialized: true };
      },
    },
  };

  require(appPath);
  assert.ok(appConfig, "app.js should register App config");
  return {
    appConfig,
    getCloudInitCount: () => cloudInitCount,
    hasOverride: () => storage.has("weeklyActivityDevtoolsApiOverride:v1"),
    cleanup() {
      delete require.cache[appPath];
      delete global.App;
      delete global.wx;
    },
  };
}

test("devtools API override applies only localhost publicBaseUrl and skips cloud init", async () => {
  const harness = loadAppWithWx({
    platform: "devtools",
    override: { publicBaseUrl: "http://127.0.0.1:5936/", createdAt: Date.now() },
  });
  try {
    harness.appConfig.onLaunch.call(harness.appConfig);
    const cloud = harness.appConfig.globalData.cloud;
    assert.equal(cloud.publicBaseUrl, "http://127.0.0.1:5936");
    assert.equal(cloud.devtoolsApiOverrideApplied, true);
    assert.equal(cloud.offlineSnapshotFallback, false);
    assert.equal(cloud.fastOfflineSnapshotFallback, false);
    assert.equal(cloud.publicFallbackDelayMs, 0);
    assert.equal(cloud.cacheMaxAgeMs, 0);
    assert.equal(cloud.cloudReady, true);
    assert.equal(cloud.cloudInitPromise, null);
    assert.equal(harness.getCloudInitCount(), 0);
    await assert.rejects(
      cloud.cloudClient.callContainer(),
      (error) => error && error.error && error.error.code === "DEVTOOLS_API_OVERRIDE_LOCAL_ONLY",
    );
  } finally {
    harness.cleanup();
  }
});
test("devtools API override expires instead of pinning the app to a dead localhost server", async () => {
  const harness = loadAppWithWx({
    platform: "devtools",
    override: {
      publicBaseUrl: "http://127.0.0.1:5936",
      createdAt: Date.now() - 60 * 60 * 1000,
    },
  });
  try {
    harness.appConfig.onLaunch.call(harness.appConfig);
    const cloud = harness.appConfig.globalData.cloud;
    assert.equal(cloud.publicBaseUrl, "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com");
    assert.equal(cloud.devtoolsApiOverrideApplied, undefined);
    assert.equal(harness.hasOverride(), false);
    assert.equal(harness.getCloudInitCount(), 1);
  } finally {
    harness.cleanup();
  }
});

test("devtools API override is ignored outside DevTools", async () => {
  const harness = loadAppWithWx({
    platform: "ios",
    override: { publicBaseUrl: "http://127.0.0.1:5936" },
  });
  try {
    harness.appConfig.onLaunch.call(harness.appConfig);
    const cloud = harness.appConfig.globalData.cloud;
    assert.equal(cloud.publicBaseUrl, "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com");
    assert.equal(cloud.devtoolsApiOverrideApplied, undefined);
    assert.equal(harness.getCloudInitCount(), 1);
    assert.ok(cloud.cloudInitPromise);
    await cloud.cloudInitPromise;
    assert.equal(cloud.cloudReady, true);
  } finally {
    harness.cleanup();
  }
});
