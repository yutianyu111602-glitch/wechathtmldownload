const clubOverviewData = require("../data/club_overviews");

const KIND_PRIORITY = {
  week: 0,
  holiday: 1,
  month: 2,
};

const KIND_LABELS = {
  zh: {
    week: "本周",
    holiday: "假期",
    month: "本月",
    other: "一览",
  },
  en: {
    week: "This week",
    holiday: "Holiday",
    month: "This month",
    other: "Roundup",
  },
};

function normalizeClubName(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/club|俱乐部|bar|酒吧|livehouse|studio|space|空间/g, "")
    .replace(/[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]/g, "");
}

function clubNameMatches(left, right) {
  const a = normalizeClubName(left);
  const b = normalizeClubName(right);
  if (!a || !b) return false;
  if (a === b) return true;
  const [shorter, longer] = [a, b].sort((x, y) => x.length - y.length);
  return shorter.length >= 5 && longer.includes(shorter);
}

function kindLabel(kind, lang = "zh") {
  const labels = KIND_LABELS[lang === "en" ? "en" : "zh"];
  return labels[kind] || labels.other;
}

function overviewSortKey(item = {}) {
  const priority = KIND_PRIORITY[item.window_kind] ?? 9;
  const start = String(item.window_start || "");
  const end = String(item.window_end || "");
  return `${priority}|${start}|${end}`;
}

function toDisplayItem(item = {}, lang = "zh") {
  const windowKind = item.window_kind || "other";
  return {
    id: `${item.club || "club"}|${item.original_url || item.title || ""}`,
    club: item.club || "",
    title: item.title || "",
    coverUrl: item.cover_url || "",
    originalUrl: item.original_url || "",
    windowKind,
    windowLabel: item.window_label || "",
    kindLabel: kindLabel(windowKind, lang),
    publishDate: item.publish_date || "",
    meta: [kindLabel(windowKind, lang), item.window_label || "", item.publish_date || ""].filter(Boolean).join(" · "),
  };
}

function getClubOverviewsForVenue(name, options = {}) {
  const data = options.data || clubOverviewData;
  const lang = options.lang || "zh";
  const byClub = data && data.by_club && typeof data.by_club === "object" ? data.by_club : {};
  const matched = [];
  Object.entries(byClub).forEach(([club, items]) => {
    if (!clubNameMatches(club, name)) return;
    (Array.isArray(items) ? items : []).forEach((item) => {
      if (!item || !item.original_url || !item.cover_url) return;
      matched.push(item);
    });
  });
  return matched
    .sort((a, b) => overviewSortKey(a).localeCompare(overviewSortKey(b)))
    .map((item) => toDisplayItem(item, lang));
}

module.exports = {
  clubNameMatches,
  getClubOverviewsForVenue,
  kindLabel,
  normalizeClubName,
};
