const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function loadCityPage() {
  const filename = path.join(root, "pages", "city", "city.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig = null;
  const calls = [];
  const sandbox = {
    console,
    Page(config) {
      pageConfig = config;
    },
    require(request) {
      if (request.endsWith("/api")) return { requestApi: async () => ({ cities: [] }) };
      if (request.endsWith("/share")) {
        return {
          buildSimpleShare: () => ({}),
          buildSimpleTimeline: () => ({}),
          enableShareMenu: () => {},
        };
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      setStorageSync(key, value) {
        calls.push(["setStorageSync", key, value]);
      },
      switchTab(options) {
        calls.push(["switchTab", options.url]);
        if (options.success) options.success();
      },
      navigateTo(options) {
        calls.push(["navigateTo", options.url]);
      },
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  return { pageConfig, calls };
}

test("city page opens index tab through pending city storage instead of navigateTo", () => {
  const { pageConfig, calls } = loadCityPage();

  pageConfig.openCity({ currentTarget: { dataset: { key: "hangzhou" } } });

  assert.deepEqual(calls[0], ["setStorageSync", "weeklyActivityPendingCity", "hangzhou"]);
  assert.deepEqual(calls[1], ["switchTab", "/pages/index/index"]);
  assert.equal(calls.some((call) => call[0] === "navigateTo"), false);
});

test("detail page has a dedicated merged source article section", () => {
  const detailScript = fs.readFileSync(path.join(root, "pages", "detail", "detail.js"), "utf8");
  const detailWxml = fs.readFileSync(path.join(root, "pages", "detail", "detail.wxml"), "utf8");

  assert.match(detailScript, /buildDetailSourceArticles/);
  assert.match(detailScript, /openSourceArticle/);
  assert.match(detailScript, /organizerKey/);
  assert.match(detailScript, /\/pages\/venue\/venue\?name=.*&key=/);
  assert.match(detailWxml, /SOURCE ARTICLES/);
  assert.match(detailWxml, /item\.sourceArticles\.length/);
});

test("venue and saved routes preserve key and language context", () => {
  const venueScript = fs.readFileSync(path.join(root, "pages", "venue", "venue.js"), "utf8");
  const savedScript = fs.readFileSync(path.join(root, "pages", "saved", "saved.js"), "utf8");

  assert.match(venueScript, /venueMatches\(item, name, key\)/);
  assert.match(venueScript, /item\.organizerKey === targetKey/);
  assert.match(venueScript, /&lang=\$\{this\.lang/);
  assert.match(savedScript, /weeklyActivityLang/);
  assert.match(savedScript, /\/pages\/detail\/detail\?id=.*&lang=/);
});
