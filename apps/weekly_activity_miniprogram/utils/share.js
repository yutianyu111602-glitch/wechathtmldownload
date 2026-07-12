const BRAND_NAME = "坏DJclub";
const INDEX_TITLE = `${BRAND_NAME} 本周电音活动查询`;
const INDEX_TITLE_EN = "HUAIDJ weekly electronic music events";

function normalizeLang(value) {
  return value === "en" ? "en" : "zh";
}

function safeText(value, fallback = "") {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text || fallback;
}

function shortTitle(value, fallback = INDEX_TITLE) {
  return safeText(value, fallback).slice(0, 48);
}

function queryString(params) {
  return Object.keys(params || {})
    .filter((key) => params[key] !== undefined && params[key] !== null && params[key] !== "")
    .map((key) => `${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`)
    .join("&");
}

function pathWithQuery(path, params) {
  const query = queryString(params);
  return query ? `${path}?${query}` : path;
}

function withImage(payload, imageUrl) {
  const url = safeText(imageUrl);
  return url ? { ...payload, imageUrl: url } : payload;
}

function enableShareMenu() {
  if (typeof wx === "undefined" || typeof wx.showShareMenu !== "function") return;
  try {
    wx.showShareMenu({
      withShareTicket: false,
      menus: ["shareAppMessage", "shareTimeline"],
      fail: () => {
        try {
          wx.showShareMenu({ withShareTicket: false });
        } catch {}
      },
    });
  } catch {}
}

function itemImage(item) {
  return item?.coverUrl || item?.cover_image_url || item?.cover_url || "";
}

function buildIndexParams(data = {}) {
  return {
    lang: normalizeLang(data.lang),
    city: data.selectedCity || "",
    date: data.selectedDate || "",
  };
}

function buildIndexTitle(data = {}) {
  const lang = normalizeLang(data.lang);
  const parts = [];
  if (data.selectedCity && data.cityTitle) parts.push(data.cityTitle);
  if (data.selectedDate && data.datePillLabel) parts.push(data.datePillLabel);
  if (lang === "en") return parts.length ? `HUAIDJ ${parts.join(" ")} events` : INDEX_TITLE_EN;
  return parts.length ? `${BRAND_NAME} ${parts.join(" ")} 电音活动` : INDEX_TITLE;
}

function buildIndexShare(data = {}) {
  const imageItem = (data.popularItems || data.viewItems || [])[0] || {};
  return withImage({
    title: shortTitle(buildIndexTitle(data)),
    path: pathWithQuery("/pages/index/index", buildIndexParams(data)),
  }, itemImage(imageItem));
}

function buildIndexTimeline(data = {}) {
  const imageItem = (data.popularItems || data.viewItems || [])[0] || {};
  return withImage({
    title: shortTitle(buildIndexTitle(data)),
    query: queryString(buildIndexParams(data)),
  }, itemImage(imageItem));
}

function buildDetailParams(item, lang, fallbackId = "") {
  return {
    id: item?.id || fallbackId || "",
    lang: normalizeLang(lang),
  };
}

function buildDetailTitle(item) {
  const title = item?.displayTitle || item?.title_display || item?.display_title || item?.title || INDEX_TITLE;
  const date = item?.dateCompact || "";
  const city = item?.cityLabel || "";
  const suffix = [date, city].filter(Boolean).join(" ");
  return suffix ? `${title} · ${suffix}` : title;
}

function buildDetailShare(item, lang, fallbackId = "") {
  return withImage({
    title: shortTitle(buildDetailTitle(item)),
    path: pathWithQuery("/pages/detail/detail", buildDetailParams(item, lang, fallbackId)),
  }, itemImage(item));
}

function buildDetailTimeline(item, lang, fallbackId = "") {
  return withImage({
    title: shortTitle(buildDetailTitle(item)),
    query: queryString(buildDetailParams(item, lang, fallbackId)),
  }, itemImage(item));
}

function buildNamedPageParams(name, lang, extraParams = {}) {
  return { name: name || "", ...(extraParams || {}), lang: normalizeLang(lang) };
}

function buildNamedPageShare(pagePath, name, lang, suffix = "活动", extraParams = {}) {
  const fallback = normalizeLang(lang) === "en" ? INDEX_TITLE_EN : INDEX_TITLE;
  const title = name ? `${name} ${suffix} - ${normalizeLang(lang) === "en" ? "HUAIDJ" : BRAND_NAME}` : fallback;
  return {
    title: shortTitle(title),
    path: pathWithQuery(pagePath, buildNamedPageParams(name, lang, extraParams)),
  };
}

function buildNamedPageTimeline(name, lang, suffix = "活动", extraParams = {}) {
  const fallback = normalizeLang(lang) === "en" ? INDEX_TITLE_EN : INDEX_TITLE;
  const title = name ? `${name} ${suffix} - ${normalizeLang(lang) === "en" ? "HUAIDJ" : BRAND_NAME}` : fallback;
  return {
    title: shortTitle(title),
    query: queryString(buildNamedPageParams(name, lang, extraParams)),
  };
}

function buildSimpleShare(title, path, params = {}) {
  return {
    title: shortTitle(title),
    path: pathWithQuery(path, params),
  };
}

function buildSimpleTimeline(title, params = {}) {
  return {
    title: shortTitle(title),
    query: queryString(params),
  };
}

module.exports = {
  BRAND_NAME,
  INDEX_TITLE,
  INDEX_TITLE_EN,
  buildDetailShare,
  buildDetailTimeline,
  buildIndexShare,
  buildIndexTimeline,
  buildNamedPageShare,
  buildNamedPageTimeline,
  buildSimpleShare,
  buildSimpleTimeline,
  enableShareMenu,
  queryString,
};
