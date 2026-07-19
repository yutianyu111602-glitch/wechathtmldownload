const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function loadSavedPage(requestApi) {
  const calls = {
    navigations: [],
    toasts: [],
    vibrations: 0,
  };
  const storage = {};
  let pageConfig = null;
  const code = fs.readFileSync(path.join(root, "pages/saved/saved.js"), "utf8");
  const sandbox = {
    console: {
      error() {},
      warn() {},
    },
    Page(config) {
      pageConfig = config;
    },
    wx: {
      getStorageSync(key) {
        return storage[key];
      },
      setStorageSync(key, value) {
        storage[key] = value;
      },
      stopPullDownRefresh() {},
      showToast(options) {
        calls.toasts.push(options);
      },
      navigateTo(options) {
        calls.navigations.push(options);
      },
    },
    require(request) {
      if (request === "../../utils/api") return { requestApi };
      if (request === "../../utils/format") return { compactItem: (item) => item };
      if (request === "../../utils/i18n") {
        return {
          normalizeLang: (value) => value || "zh",
          applyLanguageChrome() {},
        };
      }
      if (request === "../../utils/haptics") {
        return {
          vibrateLight() {
            calls.vibrations += 1;
          },
        };
      }
      if (request === "../../utils/share") {
        return {
          buildSimpleShare: () => ({}),
          buildSimpleTimeline: () => ({}),
          enableShareMenu() {},
        };
      }
      if (request === "../../utils/footprintCard") {
        return {
          buildFootprintCard: () => ({ cities: [], venues: [], djs: [] }),
        };
      }
      throw new Error(`Unexpected require: ${request}`);
    },
  };
  vm.runInNewContext(code, sandbox, { filename: path.join(root, "pages/saved/saved.js") });
  assert.ok(pageConfig, "saved page config captured");
  return { pageConfig, calls };
}

function bindPage(config) {
  return {
    ...config,
    data: JSON.parse(JSON.stringify(config.data || {})),
    seedDetailMap: {},
    visited: new Set(),
    setData(patch) {
      this.data = { ...this.data, ...(patch || {}) };
    },
  };
}

function djProfile(displayName) {
  return {
    schemaVersion: "atlas_miniapp.dj_profile_response.v1",
    query: displayName,
    found: true,
    profile: {
      djId: `dj:${displayName.toLowerCase().replace(/\s+/g, "-")}`,
      displayName,
      city: "深圳",
      eventCount: 2,
      venueCount: 1,
      collaboratorCount: 1,
    },
    events: [
      {
        eventId: "event:1",
        title: "Room Test",
        date: "2026-06-16",
        venueName: "OIL",
        city: "深圳",
      },
    ],
    collaborators: [
      {
        djId: "dj:peer",
        displayName: "Peer DJ",
        sameEventCount: 2,
      },
    ],
    venues: [
      {
        venueId: "venue:oil",
        venueName: "OIL",
        city: "深圳",
        eventCount: 2,
      },
    ],
  };
}

test("ATLAS starmap skips non-profile seeds and opens the first reachable profile", async () => {
  const requests = [];
  async function requestApi(apiPath) {
    requests.push(apiPath);
    if (apiPath === "/api/v1/weekly/current") {
      return {
        items: [
          {
            id: "event:first",
            lineup_artists: ["BAR SOS x BAR SAN 重磅客座", "Unknown Person", "COLA REN"],
          },
        ],
      };
    }
    if (apiPath === "/api/v1/atlas/family/profile") {
      throw { error: { code: "CONTAINER_STATUS", statusCode: 404 } };
    }
    if (apiPath.includes("Unknown%20Person")) {
      return { found: false, profile: null, events: [], collaborators: [], venues: [] };
    }
    if (apiPath.includes("COLA%20REN")) return djProfile("COLA REN");
    throw new Error(`unexpected api path: ${apiPath}`);
  }

  const { pageConfig } = loadSavedPage(requestApi);
  const page = bindPage(pageConfig);
  await page.loadSeeds();

  assert.equal(page.data.center.label, "COLA REN");
  assert.equal(page.data.error, "");
  assert.ok(page.data.nodes.length > 0);
  assert.ok(!page.data.seedList.some((seed) => seed.name.includes("重磅客座")));
  assert.ok(requests.some((apiPath) => apiPath.includes("Unknown%20Person")));
  assert.ok(requests.some((apiPath) => apiPath.includes("COLA%20REN")));
});

test("ATLAS starmap treats missing profiles as empty records, not connection failures", async () => {
  async function requestApi(apiPath) {
    if (apiPath === "/api/v1/atlas/family/profile") {
      throw { error: { code: "CONTAINER_STATUS", statusCode: 404 } };
    }
    if (apiPath.includes("Unknown%20Person")) {
      return { found: false, profile: null, events: [], collaborators: [], venues: [] };
    }
    throw new Error(`unexpected api path: ${apiPath}`);
  }

  const { pageConfig } = loadSavedPage(requestApi);
  const page = bindPage(pageConfig);
  const ok = await page.loadGraph("Unknown Person");

  assert.equal(ok, false);
  assert.equal(page.data.error, page.data.t.empty);
  assert.notEqual(page.data.error, page.data.t.error);
});
