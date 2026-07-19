const { requestApi } = require("../../utils/api");
const { buildExternalLinkAction } = require("../../utils/externalLinkAction");
const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { openOfficialArticle } = require("../../utils/sourceAction");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

const DIRECT_WEB_HOSTS = new Set(["huaidj.club", "www.huaidj.club"]);

function isAtlasEvidenceRef(hash, kind = "") {
  return String(kind || "").toLowerCase() === "atlas" || /^(src|source|source_ref|evidence|activity_src|atlas_src):/i.test(String(hash || "").trim());
}

function safeDecodeUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function allowedDirectWebUrl(value) {
  const url = safeDecodeUrl(value);
  if (!url) return "";
  const match = url.match(/^https:\/\/([^/?#]+)([/?#].*)?$/i);
  if (!match) return "";
  if (!DIRECT_WEB_HOSTS.has(match[1].toLowerCase())) return "";
  return url;
}

function safeOriginalExternalUrl(value, lang, linkType = "external") {
  const action = buildExternalLinkAction(safeDecodeUrl(value), lang, { linkType });
  return action.ok ? action.url : "";
}

function sourceExternalTitle(dict, linkType) {
  return String(linkType || "").toLowerCase() === "radio"
    ? (dict.radioExternalTitle || dict.externalTitle)
    : dict.externalTitle;
}

function sourceExternalHint(dict, linkType) {
  return String(linkType || "").toLowerCase() === "radio"
    ? (dict.radioExternalHint || dict.externalHint)
    : dict.externalHint;
}

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

Page({
  data: {
    lang: "zh",
    t: text("source", "zh"),
    sourceUrl: "",
    externalUrl: "",
    webViewUrl: "",
    sourceHash: "",
    sourceKind: "",
    evidenceTitle: "",
    evidenceMeta: "",
    evidenceSnippet: "",
    sourceNotice: "",
    sourceLinkType: "external",
    sourceExternalTitle: "",
    sourceExternalHint: "",
    loading: true,
    loadingProgress: 0,
    error: "",
    debugHash: "",
  },

  onLoad(query) {
    enableShareMenu();
    const lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    const sourceHash = query.hash || "";
    const sourceKind = query.kind || "";
    const sourceLinkType = String(query.linkType || "external").trim() || "external";
    const directUrl = allowedDirectWebUrl(query.url || "");
    const originalExternalUrl = safeOriginalExternalUrl(query.externalUrl || "", lang, sourceLinkType);
    const evidenceTitle = safeDecodeUrl(query.title || "");
    const evidenceMeta = safeDecodeUrl(query.meta || "");
    const t = text("source", lang);
    applyLanguageChrome("source", lang);
    this.setData({
      lang,
      t,
      sourceHash,
      sourceKind,
      sourceUrl: originalExternalUrl || directUrl,
      externalUrl: originalExternalUrl || directUrl,
      webViewUrl: "",
      evidenceTitle,
      evidenceMeta,
      sourceLinkType,
      sourceExternalTitle: sourceExternalTitle(t, sourceLinkType),
      sourceExternalHint: sourceExternalHint(t, sourceLinkType),
    });
    if (directUrl || originalExternalUrl) {
      this.setData({ loading: false, loadingProgress: 100, error: "" });
      return;
    }
    if (isAtlasEvidenceRef(sourceHash, sourceKind)) {
      this.loadAtlasEvidence(sourceHash);
      return;
    }
    this.loadSource(sourceHash);
  },

  onShareAppMessage() {
    const atlasUrl = allowedDirectWebUrl(this.data.externalUrl || this.data.webViewUrl);
    const originalExternalUrl = atlasUrl ? "" : safeOriginalExternalUrl(this.data.externalUrl, this.data.lang, this.data.sourceLinkType);
    const isAtlas = Boolean(atlasUrl);
    const title = this.data.evidenceTitle || (isAtlas ? "HUAIDJ Atlas" : (this.data.lang === "en" ? "HUAIDJ source article" : "坏DJclub 公众号原文"));
    return buildSimpleShare(title, "/pages/source/source", {
      hash: this.data.sourceHash,
      url: atlasUrl,
      externalUrl: originalExternalUrl,
      linkType: originalExternalUrl ? this.data.sourceLinkType : "",
      title: originalExternalUrl ? this.data.evidenceTitle : "",
      meta: originalExternalUrl ? this.data.evidenceMeta : "",
      lang: this.data.lang,
    });
  },

  onShareTimeline() {
    const atlasUrl = allowedDirectWebUrl(this.data.externalUrl || this.data.webViewUrl);
    const originalExternalUrl = atlasUrl ? "" : safeOriginalExternalUrl(this.data.externalUrl, this.data.lang, this.data.sourceLinkType);
    const isAtlas = Boolean(atlasUrl);
    const title = this.data.evidenceTitle || (isAtlas ? "HUAIDJ Atlas" : (this.data.lang === "en" ? "HUAIDJ source article" : "坏DJclub 公众号原文"));
    return buildSimpleTimeline(title, {
      hash: this.data.sourceHash,
      url: atlasUrl,
      externalUrl: originalExternalUrl,
      linkType: originalExternalUrl ? this.data.sourceLinkType : "",
      title: originalExternalUrl ? this.data.evidenceTitle : "",
      meta: originalExternalUrl ? this.data.evidenceMeta : "",
      lang: this.data.lang,
    });
  },

  async loadSource(hash) {
    if (!hash) {
      this.setData({ loading: false, loadingProgress: 100, error: this.data.t.failed, debugHash: "" });
      return;
    }
    this.setData({ debugHash: hash });
    try {
      this.setData({ loading: true, loadingProgress: 20, error: "" });
      const source = await requestApi(`/api/v1/weekly/source/${encodeURIComponent(hash)}`);
      this.setData({
        sourceUrl: source.url || "",
        externalUrl: "",
        loading: false,
        loadingProgress: 100,
        error: source.url ? "" : this.data.t.failed,
      });
    } catch (error) {
      console.error("[source] loadSource failed", error);
      this.setData({
        loading: false,
        loadingProgress: 100,
        error: this.data.t.failed,
      });
    }
  },

  async loadAtlasEvidence(hash) {
    if (!hash) {
      this.setData({ loading: false, loadingProgress: 100, error: this.data.t.failed });
      return;
    }
    try {
      this.setData({ loading: true, loadingProgress: 20, error: "" });
      const evidence = (await requestApi(`/api/v1/atlas/evidence/${encodeURIComponent(hash)}`)) || {};
      const metaParts = [evidence.sourceAccount, evidence.postDate, evidence.sourceKind].filter(Boolean);
      // publicUrl is a real article link only when it's an http(s) string; atlas
      // evidence usually returns an object like { status: "not_public" }. Setting
      // that object as the URL produced a dead "open" button — only accept strings.
      const publicUrl = typeof evidence.publicUrl === "string" ? evidence.publicUrl : "";
      const hasInfo = Boolean(evidence.sourceTitle || metaParts.length);
      this.setData({
        evidenceTitle: evidence.sourceTitle || this.data.t.atlasEvidenceTitle || "Atlas evidence",
        evidenceMeta: metaParts.join(" · "),
        evidenceSnippet: evidence.publicSnippet || "",
        sourceUrl: publicUrl,
        externalUrl: "",
        sourceNotice: publicUrl || !hasInfo ? "" : (this.data.t.noPublicSource || ""),
        loading: false,
        loadingProgress: 100,
        error: hasInfo || publicUrl ? "" : this.data.t.failed,
      });
    } catch (error) {
      console.error("[source] loadAtlasEvidence failed", error);
      this.setData({
        loading: false,
        loadingProgress: 100,
        error: this.data.t.failed,
      });
    }
  },

  openSource() {
    safeVibrate("light");
    const externalUrl = this.data.externalUrl;
    if (externalUrl) {
      this.copyExternalUrl();
      return;
    }
    const url = this.data.sourceUrl;
    if (!url) {
      this.setData({ error: this.data.t.failed });
      return;
    }
    // 公众号原文：能直接打开就打开；微信不允许时复制链接（不再用 web-view，避免白屏）
    const opened = openOfficialArticle(url, {
      fail: () => this.copyExternalUrl(),
    });
    if (!opened) {
      this.copyExternalUrl();
    }
  },

  copyExternalUrl() {
    const url = this.data.externalUrl || this.data.sourceUrl;
    if (!url) return;
    wx.setClipboardData({
      data: url,
      success: () => {
        wx.showToast({ title: this.data.t.linkCopied || "链接已复制", icon: "none" });
      },
    });
  },

  copyDebugHash() {
    const hash = this.data.debugHash;
    if (!hash) return;
    wx.setClipboardData({
      data: hash,
      success: () => {
        wx.showToast({ title: "来源标识已复制", icon: "none" });
      },
    });
  },

  retrySource() {
    const hash = this.data.sourceHash || this.data.debugHash;
    if (!hash) return;
    this.loadSource(hash);
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },

});
