const MEDIA_EXTENSIONS = new Set([
  ".aac",
  ".aiff",
  ".flac",
  ".m4a",
  ".mkv",
  ".mov",
  ".mp3",
  ".mp4",
  ".oga",
  ".ogg",
  ".opus",
  ".wav",
  ".webm",
]);

const PLATFORM_HOSTS = [
  { platform: "instagram", hosts: ["instagram.com", "www.instagram.com"] },
  { platform: "soundcloud", hosts: ["soundcloud.com", "www.soundcloud.com"] },
  { platform: "mixcloud", hosts: ["mixcloud.com", "www.mixcloud.com"] },
  { platform: "bandcamp", hosts: ["bandcamp.com", "www.bandcamp.com"], suffixes: [".bandcamp.com"] },
  { platform: "youtube", hosts: ["youtube.com", "www.youtube.com", "youtu.be"] },
  { platform: "bilibili", hosts: ["bilibili.com", "www.bilibili.com", "space.bilibili.com"] },
  { platform: "vimeo", hosts: ["vimeo.com", "www.vimeo.com"] },
  { platform: "spotify", hosts: ["open.spotify.com", "spotify.com", "www.spotify.com"] },
  { platform: "beatport", hosts: ["beatport.com", "www.beatport.com"] },
  { platform: "residentadvisor", hosts: ["ra.co", "www.ra.co", "residentadvisor.net", "www.residentadvisor.net"] },
  { platform: "wechat", hosts: ["mp.weixin.qq.com"] },
  { platform: "byyb", hosts: ["byyb.live", "www.byyb.live", "byyb.radio", "www.byyb.radio"] },
  { platform: "cdcr", hosts: ["cdcr.live", "www.cdcr.live"] },
  { platform: "shcr", hosts: ["shcr.live", "www.shcr.live"] },
  { platform: "baihui", hosts: ["baihui.live", "www.baihui.live", "baihui.fm", "www.baihui.fm"], suffixes: [".baihui.live"] },
  { platform: "hoer", hosts: ["hoer.live", "www.hoer.live"] },
  { platform: "netease", hosts: ["music.163.com", "www.music.163.com"] },
];

const I18N = {
  zh: {
    empty: "请先填写原链接",
    invalid: "请填写 http(s) 原链接",
    blockedMedia: "请填写平台页面原链接，不要填写音频/视频直链",
    copied: "原链接已复制",
  },
  en: {
    empty: "Enter the source link first",
    invalid: "Use an http(s) source link",
    blockedMedia: "Use the platform page link, not a direct media file",
    copied: "Source link copied",
  },
};

function normalizeLang(value) {
  return value === "en" ? "en" : "zh";
}

function labelsFor(lang) {
  return I18N[normalizeLang(lang)];
}

function parseHttpUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
    return parsed;
  } catch {
    return null;
  }
}

function hostnameMatches(hostname, rule) {
  const host = String(hostname || "").toLowerCase();
  if (rule.hosts.includes(host)) return true;
  return (rule.suffixes || []).some((suffix) => host.endsWith(suffix));
}

function identifyPlatform(url) {
  if (!url) return "external";
  const rule = PLATFORM_HOSTS.find((item) => hostnameMatches(url.hostname, item));
  return rule ? rule.platform : "external";
}

function pathnameExtension(pathname) {
  const lower = String(pathname || "").toLowerCase();
  const basename = lower.split("/").pop() || "";
  const idx = basename.lastIndexOf(".");
  return idx >= 0 ? basename.slice(idx) : "";
}

function isDirectMediaUrl(url) {
  if (!url) return false;
  if (MEDIA_EXTENSIONS.has(pathnameExtension(url.pathname))) return true;
  const host = String(url.hostname || "").toLowerCase();
  const path = String(url.pathname || "").toLowerCase();
  if ((host.includes("sndcdn.com") || host.includes("audio") || host.includes("media")) && /\/(stream|download|audio|media)\b/.test(path)) {
    return true;
  }
  return false;
}

function buildExternalLinkAction(value, lang, options = {}) {
  const labels = labelsFor(lang);
  const raw = String(value || "").trim();
  if (!raw) {
    return { ok: false, reason: "empty", message: labels.empty };
  }
  const url = parseHttpUrl(raw);
  if (!url) {
    return { ok: false, reason: "invalid_url", message: labels.invalid };
  }
  if (isDirectMediaUrl(url)) {
    return { ok: false, reason: "direct_media_url", message: labels.blockedMedia };
  }
  return {
    ok: true,
    mode: "copy_original_link",
    url: url.toString(),
    platform: identifyPlatform(url),
    linkType: options.linkType || "external",
    mediaCached: false,
    mediaDownloaded: false,
    mediaProxied: false,
    message: labels.copied,
  };
}

function copyOriginalExternalLink(value, lang, options = {}) {
  const action = buildExternalLinkAction(value, lang, options);
  if (!action.ok) return action;
  if (typeof wx !== "undefined" && typeof wx.setClipboardData === "function") {
    wx.setClipboardData({
      data: action.url,
      success: () => {
        if (typeof wx.showToast === "function") {
          wx.showToast({ title: action.message, icon: "none" });
        }
      },
    });
  }
  return action;
}

function validateInterviewExternalLinks(form, lang) {
  const checks = [
    ["instagramUrl", "instagram"],
    ["mixtapeUrl", "mixtape"],
    ["sourceUrl", "source"],
  ];
  for (const [field, linkType] of checks) {
    const value = form && form[field];
    if (!String(value || "").trim()) continue;
    const action = buildExternalLinkAction(value, lang, { linkType });
    if (!action.ok) return action;
  }
  return { ok: true };
}

module.exports = {
  buildExternalLinkAction,
  copyOriginalExternalLink,
  identifyPlatform,
  isDirectMediaUrl,
  parseHttpUrl,
  validateInterviewExternalLinks,
};
