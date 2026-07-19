const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function loadDetailPage() {
  const filename = path.join(root, "pages", "detail", "detail.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig = null;
  const calls = [];
  const sandbox = {
    console,
    Page(config) {
      pageConfig = config;
    },
    getCurrentPages() {
      return [];
    },
    require(request) {
      if (request.endsWith("/api")) return { requestApi: async () => ({}) };
      if (request.endsWith("/format")) return { compactItem: (item) => item, joinList: () => "" };
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome: () => {},
          localizeItem: (item) => item,
          localizedSourceArticles: (items) => items,
          normalizeLang: (value) => (value === "en" ? "en" : "zh"),
          text: () => ({
            addressCopied: "地址已复制",
            openMap: "打开地图",
            openMapFallback: "缺少坐标，已复制地址",
            openMapFailed: "无法打开地图，已复制地址",
          }),
        };
      }
      if (request.endsWith("/sourceAction")) {
        return {
          buildSourcePageUrl: () => "/pages/source/source",
          fetchSourceByHash: async () => "",
          openSourceUrl: () => {},
        };
      }
      if (request.endsWith("/sourceArticles")) return { buildDetailSourceArticles: () => [] };
      if (request.endsWith("/share")) {
        return {
          buildDetailShare: () => ({}),
          buildDetailTimeline: () => ({}),
          enableShareMenu: () => {},
        };
      }
      if (request.endsWith("/cloudPosterUrls")) {
        return {
          cloudFileIdFallback: () => "",
          resolvePosterUrlForItem: async (item) => item,
        };
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      getStorageSync() {
        return "";
      },
      setStorageSync() {},
      navigateTo() {},
      navigateToMiniProgram() {
        calls.push(["navigateToMiniProgram"]);
        throw new Error("detail map action must use wx.openLocation instead of navigateToMiniProgram");
      },
      switchTab() {},
      reLaunch() {},
      navigateBack() {},
      openLocation(options) {
        calls.push(["openLocation", options]);
      },
      getLocation(options) {
        calls.push(["getLocation"]);
        if (options && options.success) options.success({ latitude: 39.9, longitude: 116.4 });
      },
      setClipboardData(options) {
        calls.push(["setClipboardData", options.data]);
        if (options.success) options.success();
      },
      showToast(options) {
        calls.push(["showToast", options.title]);
      },
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  return { pageConfig, calls, code };
}

function bindPage(pageConfig, data) {
  return {
    data,
    setData(next) {
      this.data = { ...this.data, ...next };
    },
    copyAddress: pageConfig.copyAddress,
    openMapLocation: pageConfig.openMapLocation,
  };
}

test("detail address opens WeChat map with destination only when taxi-grade coordinates are present", () => {
  const { pageConfig, calls, code } = loadDetailPage();
  const detailWxml = fs.readFileSync(path.join(root, "pages", "detail", "detail.wxml"), "utf8");
  const page = bindPage(pageConfig, {
    t: { addressCopied: "地址已复制", openMapFailed: "无法打开地图" },
    item: {
      hasMapLocation: true,
      addressLabel: "上海市黄浦区测试路1号",
      mapLocation: {
        latitude: 31.2304,
        longitude: 121.4737,
        name: "测试俱乐部",
        address: "上海市黄浦区测试路1号",
      },
    },
  });

  pageConfig.handleAddressTap.call(page);

  assert.equal(code.includes("wx.getLocation"), false);
  assert.equal(code.includes("wx.navigateToMiniProgram"), false);
  assert.equal(code.includes("wx.openLocation"), true);
  assert.match(detailWxml, /class="address-action">\{\{t\.openMap\}\} ›<\/view>/);
  assert.doesNotMatch(detailWxml, /item\.hasMapLocation \? t\.openMap : t\.copyAddress/);
  assert.equal(calls.some((call) => call[0] === "getLocation"), false);
  assert.equal(calls.some((call) => call[0] === "navigateToMiniProgram"), false);
  assert.equal(calls.some((call) => call[0] === "openLocation"), true);
  const openCall = calls.find((call) => call[0] === "openLocation");
  assert.equal(openCall[1].latitude, 31.2304);
  assert.equal(openCall[1].longitude, 121.4737);
  assert.equal(openCall[1].name, "测试俱乐部");
  assert.equal(openCall[1].address, "上海市黄浦区测试路1号");
  assert.equal(openCall[1].scale, 16);
  assert.equal(typeof openCall[1].fail, "function");
  assert.equal(calls.some((call) => call[0] === "setClipboardData"), false);
});

test("detail address copies fallback if WeChat map rejects destination", () => {
  const { pageConfig, calls } = loadDetailPage();
  const page = bindPage(pageConfig, {
    t: { addressCopied: "地址已复制", openMapFallback: "缺少坐标，已复制地址", openMapFailed: "无法打开微信地图，已复制地址" },
    item: {
      hasMapLocation: true,
      addressLabel: "上海市黄浦区测试路1号",
      mapLocation: {
        latitude: 31.2304,
        longitude: 121.4737,
        name: "测试俱乐部",
        address: "上海市黄浦区测试路1号",
      },
    },
  });

  pageConfig.handleAddressTap.call(page);
  const openLocationCall = calls.find((call) => call[0] === "openLocation");
  openLocationCall[1].fail();

  assert.equal(openLocationCall[0], "openLocation");
  assert.deepEqual(calls.find((call) => call[0] === "setClipboardData"), ["setClipboardData", "上海市黄浦区测试路1号"]);
  assert.deepEqual(calls.find((call) => call[0] === "showToast"), ["showToast", "无法打开微信地图，已复制地址"]);
});

test("detail address copies fallback if stored map coordinates are invalid", () => {
  const { pageConfig, calls } = loadDetailPage();
  const page = bindPage(pageConfig, {
    t: { addressCopied: "地址已复制", openMapFallback: "缺少坐标，已复制地址", openMapFailed: "无法打开微信地图，已复制地址" },
    item: {
      hasMapLocation: true,
      addressLabel: "上海市黄浦区测试路1号",
      mapLocation: {
        latitude: 131.2304,
        longitude: 121.4737,
        name: "测试俱乐部",
        address: "上海市黄浦区测试路1号",
      },
    },
  });

  pageConfig.handleAddressTap.call(page);

  assert.deepEqual(calls[0], ["setClipboardData", "上海市黄浦区测试路1号"]);
  assert.deepEqual(calls[1], ["showToast", "缺少坐标，已复制地址"]);
  assert.equal(calls.some((call) => call[0] === "openLocation"), false);
});

test("detail address keeps copy fallback when coordinates are missing", () => {
  const { pageConfig, calls } = loadDetailPage();
  const page = bindPage(pageConfig, {
    t: { addressCopied: "地址已复制", openMapFailed: "无法打开地图" },
    item: {
      hasMapLocation: false,
      addressLabel: "上海市黄浦区测试路1号",
      mapLocation: null,
    },
  });

  pageConfig.handleAddressTap.call(page);

  assert.deepEqual(calls[0], ["setClipboardData", "上海市黄浦区测试路1号"]);
  assert.equal(calls.some((call) => call[0] === "openLocation"), false);
});
