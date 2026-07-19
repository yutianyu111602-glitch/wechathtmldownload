const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { vibrateLight } = require("../../utils/haptics");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");
const { COLUMN_FALLBACK_ITEMS, COLUMN_STYLE_VERSION } = require("../../utils/columnFallbackItems");
const { openSourceByHash, openSourceUrl } = require("../../utils/sourceAction");
const { requestApi } = require("../../utils/api");

var HARDCODED_ITEMS = COLUMN_FALLBACK_ITEMS;
var COLUMN_HIGHLIGHT_STORAGE_KEY = "weeklyActivityColumnHighlight:v1";
var COLUMN_HIGHLIGHT_TTL_MS = 5 * 60 * 1000;

var TAG_LIST = [
  { key: "all", zh: "全部", en: "All" },
  { key: "atlas", zh: "Atlas计划", en: "Atlas" },
  { key: "dj", zh: "DJ雷达", en: "DJ Radar" },
  { key: "club", zh: "俱乐部", en: "Club" },
  { key: "live", zh: "现场", en: "Live" },
  { key: "festival", zh: "音乐节", en: "Festival" },
  { key: "news", zh: "场景", en: "Scene" },
];

var TAG_DISPLAY = {
  club: { zh: "俱乐部", en: "Club" },
  live: { zh: "现场", en: "Live" },
  festival: { zh: "音乐节", en: "Festival" },
  news: { zh: "场景", en: "Scene" },
  dj: { zh: "DJ", en: "DJ" },
  event: { zh: "活动", en: "Event" },
  label: { zh: "厂牌", en: "Label" },
  atlas: { zh: "Atlas计划", en: "Atlas" },
  trend: { zh: "趋势", en: "Trend" },
  gear: { zh: "设备", en: "Gear" },
  city: { zh: "城市", en: "City" },
  hot: { zh: "热门", en: "Hot" },
};

var FICTIONAL_URL_HOSTS = ["ra.co","mixmag.net","theguardian.com","billboard.com","djmag.com","synthtopia.com","berliner.com"];

var EXTERNAL_LINK_SPECS = [
  { key: "residentAdvisor", label: "Resident Advisor", icon: "RA", priority: 10 },
  { key: "bandcamp", label: "Bandcamp", icon: "BC", priority: 20 },
  { key: "soundcloud", label: "SoundCloud", icon: "SC", priority: 30 },
  { key: "mixcloud", label: "Mixcloud", icon: "MC", priority: 40 },
  { key: "spotify", label: "Spotify", icon: "SP", priority: 50 },
  { key: "instagram", label: "Instagram", icon: "IG", priority: 60 },
];

function isFictionalUrl(url, item) {
  if (!url) return false;
  if (item && item.sourceVerified === true) return false;
  for (var i = 0; i < FICTIONAL_URL_HOSTS.length; i++) {
    if (url.indexOf(FICTIONAL_URL_HOSTS[i]) !== -1) return true;
  }
  return false;
}

function normalizeParagraphText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function sanitizeToneSource(value) {
  var source = normalizeParagraphText(value);
  if (!source) return "";
  if (/^ZHEHU[-_\s]*UNDERGR(?:OUND|OND)[-_\s]*ANTI[-_\s]*AI$/i.test(source)) return "";
  return source;
}

function buildExternalLinks(item) {
  return EXTERNAL_LINK_SPECS
    .map(function(spec) {
      var url = normalizeParagraphText(item[spec.key]);
      if (!url) return null;
      return {
        key: spec.key,
        label: spec.label,
        icon: spec.icon,
        url: url,
        priority: spec.priority,
      };
    })
    .filter(Boolean)
    .sort(function(a, b) { return a.priority - b.priority; });
}

function firstItems(values, limit) {
  return Array.isArray(values) ? values.slice(0, limit) : [];
}

function applyFoldLabels(item, lang) {
  var isEn = lang === "en";
  var evidenceCount = Number(item.evidenceCount || 0);
  item.bodyToggleLabel = item.expanded
    ? (isEn ? "Collapse article" : "收起正文")
    : (isEn ? "Read full article" : "展开正文");
  item.evidenceToggleLabel = item.evidenceExpanded
    ? (isEn ? "Hide sources" : "收起资料入口")
    : (isEn
      ? "Sources / links / interviews / works" + (evidenceCount ? " (" + evidenceCount + ")" : "")
      : "展开来源 / 外链 / 采访 / 作品" + (evidenceCount ? "（" + evidenceCount + "）" : ""));
  return item;
}

function normalizeHighlightId(value) {
  return String(value || "").trim();
}

function clearStoredColumnHighlight() {
  if (typeof wx === "undefined" || typeof wx.removeStorageSync !== "function") return;
  try {
    wx.removeStorageSync(COLUMN_HIGHLIGHT_STORAGE_KEY);
  } catch (error) {
    // Best effort cleanup; stale storage must not block the column page.
  }
}

function consumeStoredColumnHighlight() {
  if (typeof wx === "undefined" || typeof wx.getStorageSync !== "function") return null;
  try {
    var value = wx.getStorageSync(COLUMN_HIGHLIGHT_STORAGE_KEY);
    clearStoredColumnHighlight();
    if (!value || typeof value !== "object") return null;
    var highlight = normalizeHighlightId(value.highlight);
    if (!highlight) return null;
    var createdAt = Number(value.createdAt || 0);
    if (createdAt && Date.now() - createdAt > COLUMN_HIGHLIGHT_TTL_MS) return null;
    return {
      highlight: highlight,
      lang: normalizeLang(value.lang),
    };
  } catch (error) {
    return null;
  }
}

function expandHighlightedItems(items, highlightId, lang) {
  var matched = false;
  var nextItems = (items || []).map(function(item) {
    if (item.id !== highlightId) return item;
    matched = true;
    return applyFoldLabels(Object.assign({}, item, {
      expanded: true,
      evidenceExpanded: false,
    }), lang);
  });
  return { items: nextItems, matched: matched };
}

function applyHighlightToRenderedItems(page, highlightId, lang) {
  var normalizedHighlight = normalizeHighlightId(highlightId);
  if (!normalizedHighlight) return false;
  var activeLang = normalizeLang(lang || page.data.lang);
  var result = expandHighlightedItems(page.data.items || [], normalizedHighlight, activeLang);
  page.setData({
    lang: activeLang,
    t: text("column", activeLang),
    activeTag: "all",
    items: result.items,
    filteredItems: result.items,
    pendingHighlightId: normalizedHighlight,
    lastExpandedItemId: result.matched ? normalizedHighlight : page.data.lastExpandedItemId,
  });
  return result.matched;
}

var ATLAS_PLAN_PREVIEW_ITEM = {
  id: "col_atlas_plan_preview",
  title: "Atlas 计划预览：把活动、DJ 和俱乐部连成可核对的图谱",
  djName: "Atlas Plan",
  summary: "Atlas 不是另一个活动列表，而是把未来活动、历史演出、DJ 身份、俱乐部空间和原文证据放到同一套可追溯关系里。",
  deck: "先做预览，是为了让你知道小程序为什么要记录演出历史，也为什么每条活动都尽量保留原文证据。",
  date: "2026-06-11",
  tag: "atlas",
  sourceName: "HUAIDJ Atlas",
  toneSource: "Atlas roadmap preview",
  columnStyleVersion: COLUMN_STYLE_VERSION,
  paragraphs: [
    "Atlas 计划要解决的问题很具体：电子音乐现场不是只由一张海报组成。一个 DJ 这周在上海，下周可能去成都；一个俱乐部的周五档期可能长期承载某种声音；同一篇公众号原文里，又会同时出现场地、厂牌、阵容、城市和时间。把这些线索拆散以后，用户看到的就只剩一条活动卡片；把它们连起来，才像一张真正能被核对的场景地图。",
    "小程序里的活动页负责回答“今晚去哪儿”，Atlas 则更像回答“这个人、这个房间、这个声音从哪里来”。未来你点进 DJ，不应该只看到一个名字，而应该看到他最近会出现在哪些国内俱乐部、过去在哪些场地出现过、常和哪些厂牌或音乐人同场，以及这些判断分别来自哪篇公开原文。这样做的重点不是制造权威口吻，而是让每个结论都有回看的证据。",
    "这也解释了为什么我们要保留历史演出。历史不是为了堆数量，而是为了识别重复出现的关系：某个俱乐部连续几周邀请 bass / techno / house 的不同分支，某个 DJ 在多个城市之间移动，某个系列派对在不同空间里换壳继续。等这些关系稳定下来，推荐就不再只靠“热门”和“最近发布”，而可以更贴近一个人真实的听感偏好。",
    "Atlas 预览阶段会先保持克制：不把未核实的别名合并成一个人，不把模糊阵容当作确定事实，不把外部链接当成最终证据。能展示的先展示，拿不准的宁可标成线索。这样用户看到的不是一个神秘黑箱，而是一套正在变清楚的工作台。",
    "后续栏目会把 Atlas 的能力放回具体演出里：介绍未来会在国内俱乐部出现的 DJ，说明他们适合什么房间、可能带来什么节奏语言、和本地舞池有什么连接。专栏不是一分钟摘要，而是一段能帮助你决定要不要进这个房间的长文。"
  ],
};

function normalizeParagraphs(item) {
  if (Array.isArray(item.paragraphs)) {
    return item.paragraphs
      .map(normalizeParagraphText)
      .filter(function(paragraph) { return paragraph.length > 0; });
  }

  if (item.body) {
    return String(item.body)
      .split(/\n{2,}|\r\n{2,}/)
      .map(normalizeParagraphText)
      .filter(function(paragraph) { return paragraph.length > 0; });
  }

  var summary = normalizeParagraphText(item.summary);
  return summary ? [summary] : [];
}

function hasLongformItems(items) {
  if (!Array.isArray(items) || items.length === 0) return false;
  return items.some(function(item) {
    if (!item) return false;
    if (Array.isArray(item.paragraphs) && item.paragraphs.length >= 2) return true;
    if (item.body && String(item.body).replace(/\s+/g, "").length > (item.summary || "").length + 80) return true;
    return false;
  });
}

function buildColumnQuery(lang) {
  return "?lang=" + encodeURIComponent(lang || "zh");
}

function getColumnCloudClient(cloud) {
  if (!cloud || cloud.useMock || !cloud.env || !cloud.service || typeof wx === "undefined" || !wx.cloud) {
    return Promise.reject(new Error("column cloud container unavailable"));
  }
  if (cloud.cloudInitPromise && typeof cloud.cloudInitPromise.then === "function") {
    return cloud.cloudInitPromise.then(function(client) {
      return client || cloud.cloudClient || wx.cloud;
    });
  }
  return Promise.resolve(cloud.cloudClient || wx.cloud);
}

function withColumnTimeout(promise, timeoutMs, label) {
  return new Promise(function(resolve, reject) {
    var settled = false;
    var timer = setTimeout(function() {
      if (settled) return;
      settled = true;
      reject(new Error(label + " timeout"));
    }, Math.max(1, Number(timeoutMs || 6000)));

    promise.then(function(value) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    }, function(error) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
  });
}

function assertRemoteColumnItems(payload, source) {
  var data = payload || {};
  var apiItems = Array.isArray(data.items) ? data.items : [];
  if (hasLongformItems(apiItems)) return apiItems;
  return Promise.reject(new Error(source + " returned no longform column items"));
}

function requestColumnViaCloudContainer(cloud, lang) {
  var path = "/api/v1/weekly/column";
  var query = buildColumnQuery(lang);
  var requestPromise = getColumnCloudClient(cloud).then(function(client) {
    if (!client || typeof client.callContainer !== "function") {
      return Promise.reject(new Error("column callContainer missing"));
    }
    return client.callContainer({
      config: { env: cloud.env },
      path: path + query,
      method: "GET",
      header: {
        "X-WX-SERVICE": cloud.service,
      },
    });
  }).then(function(res) {
    var statusCode = Number(res && res.statusCode);
    if (statusCode && (statusCode < 200 || statusCode >= 300)) {
      return Promise.reject(new Error("column cloud container status " + statusCode));
    }
    return assertRemoteColumnItems(res && res.data, "cloud container");
  });

  return withColumnTimeout(
    requestPromise,
    cloud && cloud.cloudCallTimeoutMs,
    "column cloud container"
  );
}

function requestColumnViaPublicApi(cloud, lang) {
  var baseUrl = String((cloud && cloud.publicBaseUrl) || "").replace(/\/+$/, "");
  if (!baseUrl) return Promise.reject(new Error("column publicBaseUrl missing"));
  var url = baseUrl + "/api/v1/weekly/column" + buildColumnQuery(lang);
  return new Promise(function(resolve, reject) {
    wx.request({
      url: url,
      method: "GET",
      timeout: (cloud && (cloud.publicRequestTimeoutMs || cloud.requestTimeoutMs)) || 5000,
      success: function(res) {
        var statusCode = Number(res && res.statusCode);
        if (statusCode && (statusCode < 200 || statusCode >= 300)) {
          reject(new Error("column public API status " + statusCode));
          return;
        }
        Promise.resolve(assertRemoteColumnItems(res && res.data, "public API"))
          .then(resolve, reject);
      },
      fail: reject,
    });
  });
}

function renderColumnItems(page, items, loadFailed) {
  var enriched = enrichItems(withAtlasPreview(items), page.data.lang);
  var highlightId = normalizeHighlightId(page.data.pendingHighlightId || page.data.lastExpandedItemId || "");
  var activeTag = highlightId ? "all" : page.data.activeTag;
  var matchedHighlight = false;
  if (highlightId) {
    var result = expandHighlightedItems(enriched, highlightId, page.data.lang);
    enriched = result.items;
    matchedHighlight = result.matched;
  }
  page.setData({
    items: enriched,
    filteredItems: activeTag === "all"
      ? enriched
      : enriched.filter(function(item) { return item.tag === activeTag; }),
    activeTag: activeTag,
    loading: false,
    loadFailed: loadFailed,
    lastExpandedItemId: matchedHighlight ? highlightId : page.data.lastExpandedItemId,
  });
}

function shouldKeepColumnItem(item) {
  if (!item) return false;
  if (item.tag === "atlas") return true;
  if (item.tag === "news") return false;
  return true;
}

function withAtlasPreview(items) {
  var list = (items || []).filter(shouldKeepColumnItem);
  var hasAtlas = list.some(function(item) { return item && item.id === ATLAS_PLAN_PREVIEW_ITEM.id; });
  return hasAtlas ? list : [ATLAS_PLAN_PREVIEW_ITEM].concat(list);
}

function expandLongformParagraphs(item, paragraphs) {
  var base = paragraphs.slice();
  var charCount = base.join("").replace(/\s+/g, "").length;
  if (
    item.tag === "atlas" ||
    (item.columnStyleVersion && item.columnStyleVersion.indexOf("shortform") !== -1) ||
    charCount >= 520
  ) {
    return base;
  }
  var djName = item.djName || item.title || "这位 DJ";
  var room = item.sourceName || "国内俱乐部";
  var date = item.date || "接下来";
  var styleLine = item.summary || item.deck || "这一晚的重点在于声音如何进入房间，而不是一张海报能概括多少信息。";
  var stylesByTag = {
    club: "Leftfield House、Dub、UK Bass、Industrial Techno、Acid",
    live: "Breaks、Dub、Ambient、Experimental、Bass",
    festival: "Trance、Progressive House、Electro、Breakbeat、Amapiano",
    event: "Deep House、Breaks、Dub、Electro、Trance",
    dj: "Leftfield House、UK Bass、Acid、Breaks、Dub"
  };
  var styles = stylesByTag[item.tag] || stylesByTag.dj;
  return base.concat([
    "把 " + djName + " 放进“未来演出 DJ 介绍”，不是因为名字醒目，而是因为这类演出能让人提前判断一个房间的声音方向。" + date + " 的 " + room + " 不只是地点，它会决定低频贴地的方式、灯光留白的尺度、以及人群在前半小时愿不愿意跟着细节慢慢进入状态。",
    styleLine + " 真正要听的是 " + styles + " 怎样在现场变成身体经验：Dub 的潮湿回响先贴住墙壁，Breaks 或 House 的拍点再把脚底推向舞池，Acid 的酸线如果从音响堆里渗出来，耳膜会先被勒紧，胸口随后才跟上。",
    "门口见。别只看标题，先把 " + room + " 当成一个正在发声的房间。如果这些线索对上你的身体，就进去，让 " + styles.split("、")[0] + " 的第一下鼓点把路线重新写一遍。"
  ]);
}

function enrichItems(items, lang) {
  return (items || []).map(function(rawItem) {
    var item = Object.assign({}, rawItem || {});
    var paragraphs = normalizeParagraphs(item);
    if (!item.summary && paragraphs.length) item.summary = paragraphs[0];
    item.paragraphs = paragraphs;
    item.body = item.body || paragraphs.join("\n\n");
    item.deck = item.deck || item.summary || "";
    item.paragraphs = expandLongformParagraphs(item, paragraphs);
    item.body = item.paragraphs.join("\n\n");
    item.hasLongBody = item.paragraphs.length > 1 || item.body.length > (item.summary || "").length + 30;
    item.readTimeLabel = "";
    item.columnStyleVersion = item.columnStyleVersion || COLUMN_STYLE_VERSION;
    var fm = item.foreignMedia || "";
    item.hasForeignMedia = !!(fm && !/^暂无|不代表不重要/.test(fm));
    item.isFictionalUrl = isFictionalUrl(item.eventUrl, item);
    item.cleanToneSource = sanitizeToneSource(item.toneSource);
    item.externalLinks = buildExternalLinks(item);
    item.primaryLinks = firstItems(item.externalLinks, 3);
    item.moreLinks = item.externalLinks.slice(item.primaryLinks.length);
    item.extraLinkCount = item.moreLinks.length;
    item.hasEventSource = !!((item.sourceHash || item.eventUrl) && !item.isFictionalUrl);
    item.hasFictionalSource = !!(item.eventUrl && item.isFictionalUrl);
    item.trackPreview = firstItems(item.tracks, 3);
    item.extraTrackCount = Array.isArray(item.tracks) ? Math.max(0, item.tracks.length - item.trackPreview.length) : 0;
    item.referencePreview = firstItems(item.references, 3);
    item.extraReferenceCount = Array.isArray(item.references) ? Math.max(0, item.references.length - item.referencePreview.length) : 0;
    item.relatedDj = normalizeParagraphText(item.djName || item.artistName || item.artist || "");
    item.evidenceCount = item.primaryLinks.length + item.moreLinks.length + item.referencePreview.length + item.trackPreview.length + (item.hasEventSource ? 1 : 0) + (item.hasForeignMedia ? 1 : 0);
    item.hasEvidencePanel = item.hasForeignMedia || item.hasEventSource || item.hasFictionalSource || item.primaryLinks.length || item.referencePreview.length || item.trackPreview.length || item.sourceName;
    var td = TAG_DISPLAY[item.tag] || TAG_DISPLAY.dj;
    item.tagDisplay = td[lang] || td.zh;
    item.expanded = item.expanded === true;
    item.evidenceExpanded = item.expanded && item.evidenceExpanded === true;
    return applyFoldLabels(item, lang);
  });
}

Page({
  data: {
    lang: "zh",
    t: text("column", "zh"),
    items: [],
    filteredItems: [],
    tags: [],
    activeTag: "all",
    loading: true,
    loadFailed: false,
    pendingHighlightId: "",
    lastExpandedItemId: "",
  },

  onLoad: function(options) {
    enableShareMenu();
    var storedHighlight = consumeStoredColumnHighlight();
    var l = normalizeLang((options && options.lang) || (storedHighlight && storedHighlight.lang) || wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("column", l);
    var tags = TAG_LIST.map(function(t) {
      return { key: t.key, label: t[l] || t.zh };
    });
    var highlight = normalizeHighlightId((options && options.highlight) || (storedHighlight && storedHighlight.highlight) || "");
    this.setData({ lang: l, t: text("column", l), tags: tags, activeTag: highlight ? "all" : this.data.activeTag, pendingHighlightId: highlight });
    this.fetchColumnItems();
  },

  onShow: function() {
    enableShareMenu();
    var storedHighlight = consumeStoredColumnHighlight();
    if (!storedHighlight || !storedHighlight.highlight) return;
    var lang = normalizeLang(storedHighlight.lang || this.data.lang);
    this.setData({ lang: lang, t: text("column", lang), activeTag: "all", pendingHighlightId: storedHighlight.highlight });
    if ((this.data.items || []).length) {
      applyHighlightToRenderedItems(this, storedHighlight.highlight, lang);
    } else {
      this.fetchColumnItems();
    }
  },

  onPullDownRefresh: function() {
    this.fetchColumnItems();
  },

  fetchColumnItems: function() {
    var that = this;
    var appInstance = getApp();
    var cloud = appInstance.globalData.cloud;
    var lang = that.data.lang || "zh";

    that.setData({ loading: true, loadFailed: false });

    requestColumnViaCloudContainer(cloud, lang)
      .catch(function(error) {
        console.warn("[column] cloud container failed, fallback to public API", error);
        return requestColumnViaPublicApi(cloud, lang);
      })
      .catch(function(error) {
        // Last real-data attempt: reuse the activity page's proven api.js chain
        // (robust cloud client + callContainer/public/cache) before local cache.
        console.warn("[column] direct paths failed, retry via shared api.js requestApi", error);
        return requestApi("/api/v1/weekly/column", { lang: lang }).then(function(payload) {
          return assertRemoteColumnItems(payload, "shared api");
        });
      })
      .then(function(items) {
        renderColumnItems(that, items, false);
      })
      .catch(function(error) {
        console.warn("[column] remote column failed, fallback to local cache", error);
        renderColumnItems(that, HARDCODED_ITEMS, true);
      })
      .then(function() {
        wx.stopPullDownRefresh();
      }, function() {
        wx.stopPullDownRefresh();
      });
  },

  onTagTap: function(e) {
    var key = e.currentTarget.dataset.tag;
    var filtered = key === "all"
      ? this.data.items
      : this.data.items.filter(function(item) { return item.tag === key; });
    this.setData({ activeTag: key, filteredItems: filtered });
  },

  onBodyToggle: function(e) {
    var id = e.currentTarget.dataset.id;
    var current = (this.data.items || []).filter(function(item) { return item.id === id; })[0] || {};
    var nextExpanded = !current.expanded;
    var lang = this.data.lang || "zh";
    var patchItem = function(item) {
      if (item.id !== id) return item;
      return applyFoldLabels(Object.assign({}, item, {
        expanded: nextExpanded,
        evidenceExpanded: nextExpanded ? item.evidenceExpanded : false,
      }), lang);
    };
    this.setData({
      items: this.data.items.map(patchItem),
      filteredItems: this.data.filteredItems.map(patchItem),
      lastExpandedItemId: nextExpanded ? id : this.data.lastExpandedItemId,
    });
  },

  onCardTap: function(e) {
    this.onBodyToggle(e);
  },

  onEvidenceToggle: function(e) {
    var id = e.currentTarget.dataset.id;
    var current = (this.data.items || []).filter(function(item) { return item.id === id; })[0] || {};
    var nextEvidenceExpanded = !current.evidenceExpanded;
    var lang = this.data.lang || "zh";
    var patchItem = function(item) {
      if (item.id !== id) return item;
      return applyFoldLabels(Object.assign({}, item, {
        expanded: true,
        evidenceExpanded: nextEvidenceExpanded,
      }), lang);
    };
    this.setData({
      items: this.data.items.map(patchItem),
      filteredItems: this.data.filteredItems.map(patchItem),
      lastExpandedItemId: id,
    });
  },

  showTimelineShareTip: function(e) {
    var id = e && e.currentTarget && e.currentTarget.dataset ? e.currentTarget.dataset.id : "";
    enableShareMenu();
    if (id) this.setData({ lastExpandedItemId: id });
    wx.showModal({
      title: "分享到朋友圈",
      content: "微信小程序不能用页面按钮直接弹出朋友圈。请点右上角 “...” 菜单，再选择“分享到朋友圈”。",
      showCancel: false,
      confirmText: "知道了",
    });
  },

  onTabItemTap: function() {
    vibrateLight();
  },

  onShareAppMessage: function(e) {
    var target = e.target || {};
    var dataset = target.dataset || {};
    var itemId = dataset.id;
    var itemTitle = dataset.title;
    if (itemId && itemTitle) {
      return buildSimpleShare(
        itemTitle,
        "/pages/column/column",
        { lang: this.data.lang, highlight: itemId }
      );
    }
    return buildSimpleShare(
      this.data.lang === "en" ? "Upcoming DJs" : "未来演出DJ介绍",
      "/pages/column/column",
      { lang: this.data.lang }
    );
  },

  onShareTimeline: function() {
    var highlight = this.data.lastExpandedItemId || this.data.pendingHighlightId || "";
    var item = (this.data.items || []).filter(function(candidate) {
      return candidate.id === highlight;
    })[0];
    return buildSimpleTimeline(
      item && item.title ? item.title : (this.data.lang === "en" ? "Upcoming DJs" : "未来演出DJ介绍"),
      { lang: this.data.lang, highlight: highlight }
    );
  },

  openSourceLink: function(e) {
    var u = e.currentTarget.dataset.url;
    if (!u) return;
    var t = this.data.t;
    wx.setClipboardData({
      data: u,
      success: function() {
        wx.showModal({
          title: t.linkCopiedTitle || "已复制",
          content: (t.linkCopiedBody || "请在浏览器粘贴打开") + "\n\n" + u,
          showCancel: false,
          confirmText: t.linkCopiedConfirm || "知道了",
        });
      },
    });
  },

  openEventSource: function(e) {
    var hash = e.currentTarget.dataset.sourceHash || "";
    var detailId = e.currentTarget.dataset.detailId || "";
    var url = e.currentTarget.dataset.url || "";
    if (hash) {
      openSourceByHash(hash, this.data.lang, { fallbackDetailId: detailId, showFallbackModal: true });
      return;
    }
    if (url) {
      openSourceUrl(url, this.data.lang, { showFallbackModal: true });
    }
  },
});
