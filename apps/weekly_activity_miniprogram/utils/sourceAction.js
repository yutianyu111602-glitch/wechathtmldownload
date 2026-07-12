const { requestApi } = require("./api");

const I18N = {
  zh: {
    opening: "正在打开原文",
    fallbackTitle: "原文打开页",
    fallbackContent: "已进入原文打开页。微信需要二次点击确认时，可在那里点按钮打开公众号原文。",
    confirm: "知道了",
  },
  en: {
    opening: "Opening source",
    fallbackTitle: "Source page",
    fallbackContent: "The source page is open. If WeChat needs a second tap, use the button there.",
    confirm: "OK",
  },
};

function normalizeLang(value) {
  return value === "en" ? "en" : "zh";
}

function normalizeSourceUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  let normalized = raw;
  try {
    normalized = decodeURIComponent(normalized);
  } catch {
    normalized = raw;
  }
  normalized = normalized.replace(/&amp;/gi, "&").trim();
  if (normalized.startsWith("//")) {
    normalized = `https:${normalized}`;
  }
  if (/^http:\/\//i.test(normalized)) {
    normalized = `https://${normalized.slice(7)}`;
  }
  return normalized;
}

function isAtlasEvidenceRef(hash) {
  return /^(src|source|source_ref|evidence|activity_src|atlas_src):/i.test(String(hash || "").trim());
}

function buildSourcePageUrl(hash, lang, options = {}) {
  const kind = options.kind ? `&kind=${encodeURIComponent(options.kind)}` : "";
  return `/pages/source/source?hash=${encodeURIComponent(hash)}&lang=${normalizeLang(lang)}${kind}`;
}

function safeShowLoading(options) {
  if (typeof wx !== "undefined" && typeof wx.showLoading === "function") wx.showLoading(options);
}

function safeHideLoading() {
  if (typeof wx !== "undefined" && typeof wx.hideLoading === "function") wx.hideLoading();
}

function openOfficialArticle(url, callbacks = {}) {
  if (!url || typeof wx.openOfficialAccountArticle !== "function") {
    if (callbacks.fail) callbacks.fail({ errMsg: "openOfficialAccountArticle unavailable" });
    if (callbacks.complete) callbacks.complete();
    return false;
  }

  wx.openOfficialAccountArticle({
    url,
    success: callbacks.success,
    fail: callbacks.fail,
    complete: callbacks.complete,
  });
  return true;
}

function sourcePageFallback(hash, lang, options = {}) {
  const labels = I18N[normalizeLang(lang)];
  wx.navigateTo({
        url: buildSourcePageUrl(hash, lang, options),
    success: () => {
      if (options.showModal) {
        wx.showModal({
          title: labels.fallbackTitle,
          content: labels.fallbackContent,
          confirmText: labels.confirm,
          showCancel: false,
        });
      }
    },
  });
}

function fetchSourceByHash(hash) {
  if (!hash) return Promise.resolve("");
  if (isAtlasEvidenceRef(hash)) return Promise.resolve("");
  return requestApi(`/api/v1/weekly/source/${encodeURIComponent(hash)}`)
    .then((source) => normalizeSourceUrl(source?.url || ""))
    .catch(() => "");
}

function openSourceUrl(url, lang, options = {}) {
  const safeLang = normalizeLang(lang);
  const fallbackHash = options.fallbackHash || "";
  const suppressFallback = options.suppressFallback === true;
  const runFallback = () => {
    if (suppressFallback || !fallbackHash) return;
    sourcePageFallback(fallbackHash, safeLang, { showModal: options.showFallbackModal === true });
  };
  const safeUrl = normalizeSourceUrl(url);
  if (!safeUrl) {
    if (typeof options.fail === "function") options.fail({ errMsg: "openSourceUrl: empty url" });
    runFallback();
    return false;
  }
  const opened = openOfficialArticle(safeUrl, {
    success: options.success,
    fail: (error) => {
      if (typeof options.fail === "function") options.fail(error);
      runFallback();
      // 即使没有 fallbackHash，也至少复制链接到剪贴板让用户有操作入口
      if (!fallbackHash && typeof wx !== "undefined" && typeof wx.setClipboardData === "function") {
        wx.setClipboardData({
          data: safeUrl,
          success: () => {
            if (typeof wx.showToast === "function") wx.showToast({ title: "原文链接已复制，可粘贴到浏览器打开", icon: "none" });
          },
        });
      }
    },
    complete: options.complete,
  });
  if (!opened) {
    if (typeof options.fail === "function") options.fail({ errMsg: "openOfficialAccountArticle unavailable" });
    runFallback();
  }
  return opened;
}

function openSourceByHash(hash, lang, options = {}) {
  const safeLang = normalizeLang(lang);
  const labels = I18N[safeLang];

  if (!hash) {
    if (options.fallbackDetailId) {
      wx.navigateTo({
        url: `/pages/detail/detail?id=${encodeURIComponent(options.fallbackDetailId)}&lang=${safeLang}`,
      });
    }
    return Promise.resolve(false);
  }

  if (isAtlasEvidenceRef(hash)) {
    wx.navigateTo({ url: buildSourcePageUrl(hash, safeLang, { kind: "atlas" }) });
    return Promise.resolve(true);
  }

  safeShowLoading({ title: labels.opening, mask: false });
  return fetchSourceByHash(hash)
    .then((url) => {
      safeHideLoading();
      if (!url) {
        // API 没返回 URL：如果有 fallbackDetailId 则跳到详情页，否则跳 source 页
        if (options.fallbackDetailId) {
          wx.navigateTo({
            url: `/pages/detail/detail?id=${encodeURIComponent(options.fallbackDetailId)}&lang=${safeLang}`,
          });
        } else {
          wx.navigateTo({ url: buildSourcePageUrl(hash, safeLang) });
        }
        return false;
      }
      return openSourceUrl(url, safeLang, {
        fallbackHash: hash,
        showFallbackModal: options.showFallbackModal === true,
      });
    })
    .catch(() => {
      safeHideLoading();
      wx.navigateTo({ url: buildSourcePageUrl(hash, safeLang) });
      return false;
    });
}

module.exports = {
  buildSourcePageUrl,
  fetchSourceByHash,
  isAtlasEvidenceRef,
  normalizeSourceUrl,
  openOfficialArticle,
  openSourceByHash,
  openSourceUrl,
};
