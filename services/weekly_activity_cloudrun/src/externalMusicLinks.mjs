import { createHash } from "node:crypto";

const MAX_URL_LENGTH = 500;
const RIGHTS_STATUS = "external_link_only";
const DIRECT_MEDIA_EXTENSIONS = new Set([
  ".aac",
  ".aif",
  ".aiff",
  ".avi",
  ".flac",
  ".m4a",
  ".m4v",
  ".mkv",
  ".mov",
  ".mp3",
  ".mp4",
  ".ogg",
  ".opus",
  ".wav",
  ".webm",
]);
const MEDIA_HANDLING = Object.freeze({
  download: false,
  cache: false,
  proxy: false,
  transcode: false,
  republish: false,
});

function cleanText(value, maxLength = MAX_URL_LENGTH) {
  return String(value || "").trim().replace(/\s+/g, " ").slice(0, maxLength);
}

export function cleanExternalUrl(value) {
  const raw = cleanText(value);
  if (!raw) return "";
  try {
    const url = new URL(raw);
    if (!["http:", "https:"].includes(url.protocol)) return "";
    const pathname = url.pathname.toLowerCase();
    if (DIRECT_MEDIA_EXTENSIONS.has(pathname.slice(pathname.lastIndexOf(".")))) return "";
    return url.toString();
  } catch {
    return "";
  }
}

export function platformFromUrl(urlText) {
  let hostname = "";
  try {
    hostname = new URL(urlText).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "unknown";
  }
  if (hostname.endsWith("instagram.com")) return "instagram";
  if (hostname.endsWith("soundcloud.com")) return "soundcloud";
  if (hostname.endsWith("mixcloud.com")) return "mixcloud";
  if (hostname.endsWith("bandcamp.com")) return "bandcamp";
  if (hostname.endsWith("residentadvisor.net") || hostname === "ra.co") return "resident_advisor";
  if (hostname.endsWith("mp.weixin.qq.com")) return "wechat";
  return hostname.split(".").slice(-2).join(".") || "external";
}

function urlHash(url) {
  return createHash("sha256").update(url).digest("hex").slice(0, 16);
}

function linkRecord({ kind, url, sourceRefId = "", consentStatus = "", submittedAt = "" }) {
  return {
    kind,
    platform: platformFromUrl(url),
    url,
    urlHash: urlHash(url),
    sourceRefId: cleanText(sourceRefId, 160),
    rightsStatus: RIGHTS_STATUS,
    mediaHandling: MEDIA_HANDLING,
    consentStatus: cleanText(consentStatus, 80),
    submittedAt: cleanText(submittedAt, 80),
  };
}

export function buildInterviewExternalLinkFields(entry = {}) {
  const submittedAt = entry.submittedAt || "";
  const consentStatus = entry.consentStatus || "";
  const sourceRefId = entry.sourceRefId || entry.source_ref_id || "";
  const candidates = [
    { kind: "instagram", url: cleanExternalUrl(entry.instagramUrl || entry.instagram) },
    { kind: "mixtape", url: cleanExternalUrl(entry.mixtapeUrl || entry.mixUrl || entry.mixcloudUrl || entry.soundcloudUrl) },
    { kind: "source", url: cleanExternalUrl(entry.sourceUrl || entry.source) },
  ].filter((item) => item.url);

  const seen = new Set();
  const externalLinks = [];
  for (const candidate of candidates) {
    const key = `${candidate.kind}:${candidate.url}`;
    if (seen.has(key)) continue;
    seen.add(key);
    externalLinks.push(linkRecord({
      kind: candidate.kind,
      url: candidate.url,
      sourceRefId,
      consentStatus,
      submittedAt,
    }));
  }

  const musicLinks = externalLinks.filter((item) => (
    item.kind === "mixtape"
    || ["soundcloud", "mixcloud", "bandcamp"].includes(item.platform)
  ));

  return {
    schemaVersion: "atlas_external_music_links.v1",
    externalLinks,
    musicLinks,
    safety: {
      audioDownloadExecuted: false,
      audioCacheWritten: false,
      audioProxyEnabled: false,
      audioTranscodeExecuted: false,
      audioRepublishExecuted: false,
    },
  };
}
