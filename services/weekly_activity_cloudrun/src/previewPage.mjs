function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function first(value, fallback = "") {
  return Array.isArray(value) ? value[0] || fallback : value || fallback;
}

function joinList(value, fallback = "") {
  if (!Array.isArray(value) || value.length === 0) return fallback;
  return value.filter(Boolean).join(" / ");
}

const VERIFIED_ADDRESS_BOOK = [
  {
    keys: ["potent", "potentclub"],
    address: "上海市黄浦区淮海中路523号",
  },
  {
    keys: ["dadabarbeijing", "dada北京", "dadabeijing", "dada酒吧日坛国际贸易中心a座店"],
    address: "北京市朝阳区南营房胡同日坛国际贸易中心A座北门B1层",
  },
  {
    keys: ["莫须有工厂", "groundlessfactory", "groundless factory", "798cube莫须有工厂"],
    address: "北京市朝阳区酒仙桥路2号798艺术区706路B06-2",
  },
];

const STYLE_RULES = [
  { label: "hip-hop", aliases: ["hiphop", "hip hop", "hip-hop", "说唱", "嘻哈", "rap", "trap"] },
  { label: "techno", aliases: ["techno", "工业", "industrial techno"] },
  { label: "4x4", aliases: ["4x4", "four on the floor", "four-on-the-floor"] },
  { label: "house", aliases: ["house", "浩室"] },
  { label: "club trax", aliases: ["club trax", "club tracks", "club music", "club edits", "club edit"] },
  { label: "electro", aliases: ["electro", "电子放克"] },
  { label: "bass", aliases: ["bass", "低音"] },
  { label: "drum & bass", aliases: ["drum and bass", "drum&bass", "dnb", "d&b"] },
  { label: "breaks", aliases: ["breakbeat", "breaks", "碎拍"] },
  { label: "trance", aliases: ["trance"] },
  { label: "disco", aliases: ["disco", "迪斯科"] },
  { label: "ambient", aliases: ["ambient", "氛围"] },
];

const NON_ARTIST_LINEUP_NAMES = [
  "aurora",
  "aurorabj",
  "support",
  "nighttour",
  "夜游",
];

const COPY = {
  zh: {
    htmlLang: "zh-CN",
    title: "本周活动预览",
    all: "全部",
    allCities: "全部城市",
    allDates: "全部日期",
    events: "场",
    weeklyGuide: "HUAIDJ WEEKLY",
    cityFilter: "城市",
    dateFilter: "日期",
    weeklyEvents: "本周舞池",
    statusHelp: "",
    club: "俱乐部",
    venue: "场地",
    address: "地址",
    city: "城市",
    date: "日期",
    time: "时间",
    style: "风格",
    original: "原文",
    openEventOriginal: "打开活动原文",
    djBio: "简介",
    noEvents: "这组筛选下暂无活动",
    back: "返回列表",
    langToggle: "EN",
    copyAddress: "复制地址",
    copiedAddress: "已复制",
  },
  en: {
    htmlLang: "en",
    title: "Weekly Activity Preview",
    all: "All",
    allCities: "All cities",
    allDates: "All dates",
    events: "events",
    weeklyGuide: "HUAIDJ WEEKLY",
    cityFilter: "City",
    dateFilter: "Date",
    weeklyEvents: "This week",
    statusHelp: "",
    club: "Club",
    venue: "Venue",
    address: "Address",
    city: "City",
    date: "Date",
    time: "Time",
    style: "Style",
    original: "Original",
    openEventOriginal: "Open original post",
    djBio: "DJ Bio",
    noEvents: "No events for this filter",
    back: "Back to list",
    langToggle: "中文",
    copyAddress: "Copy address",
    copiedAddress: "Copied",
  },
};

function normalizeName(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]/g, "");
}

function stripEmoji(value) {
  return String(value || "").replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, "").trim();
}

function stripLeadingDateWords(value) {
  return String(value || "")
    .replace(/^\s*[「【\[]?\s*(今晚|今夜|本周|周末)\s*[」】\]]?\s*/i, "")
    .replace(/^\s*(\d{1,2})[./-](\d{1,2})(\s*\([^)]+\))?\s*(周[一二三四五六日天]|星期[一二三四五六日天]|今晚|今夜)?\s*/i, "")
    .replace(/^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*/, "")
    .replace(/^\s*[｜|·:：,，\-–—]+\s*/, "")
    .trim();
}

function removeEntityPrefix(title, item) {
  const candidates = candidateNames(item).map(normalizeName).filter(Boolean);
  const parts = String(title || "").split(/[｜|]/).map((part) => part.trim()).filter(Boolean);
  if (parts.length < 2) return title;
  const firstPart = normalizeName(parts[0]);
  if (candidates.some((candidate) => firstPart === candidate || candidate.includes(firstPart) || firstPart.includes(candidate))) {
    return parts.slice(1).join(" / ").trim();
  }
  return title;
}

function displayTitle(item) {
  if (item.title_display || item.display_title) return stripEmoji(item.title_display || item.display_title);
  const cleaned = removeEntityPrefix(stripLeadingDateWords(stripEmoji(item.title)), item)
    .replace(/\s+\d{1,2}[./-]\d{1,2}.*$/i, "")
    .replace(/^\s*[｜|·:：,，\-–—]+\s*/, "")
    .trim();
  return cleaned || stripEmoji(item.title) || "Untitled";
}

function normalizeStyleSignal(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[＿_]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function directStyleSignals(item) {
  return [
    ...(Array.isArray(item.music_styles) ? item.music_styles : []),
    ...(Array.isArray(item.musicStyles) ? item.musicStyles : []),
    ...(Array.isArray(item.style_tags) ? item.style_tags : []),
    ...(Array.isArray(item.genres) ? item.genres : []),
  ].filter(Boolean);
}

function itemStyleSignals(item) {
  return [
    ...directStyleSignals(item),
    item.title,
    item.promoter,
    item.account,
    ...(Array.isArray(item.lineup) ? item.lineup : []),
    ...(Array.isArray(item.evidence) ? item.evidence : []),
  ].filter(Boolean);
}

function inferMusicStyles(item) {
  const signals = itemStyleSignals(item).map(normalizeStyleSignal).filter(Boolean);
  const labels = [];
  for (const rule of STYLE_RULES) {
    const matched = rule.aliases.some((alias) => {
      const normalizedAlias = normalizeStyleSignal(alias);
      return signals.some((signal) => signal.includes(normalizedAlias));
    });
    if (matched && !labels.includes(rule.label)) labels.push(rule.label);
    if (labels.length >= 4) break;
  }
  return labels;
}

function candidateNames(item) {
  const signals = itemTextSignals(item).map(normalizeName).filter(Boolean);
  const addressBookAliases = VERIFIED_ADDRESS_BOOK
    .filter((entry) => entry.keys.some((key) => signals.some((signal) => signal.includes(normalizeName(key)))))
    .flatMap((entry) => entry.keys);
  return [
    item.promoter,
    item.account,
    item.address,
    item.address_full,
    item.venue_name,
    ...(Array.isArray(item.venue) ? item.venue : []),
    ...(Array.isArray(item.city) ? item.city : []),
    ...addressBookAliases,
  ].filter(Boolean);
}

function isSameEntity(value, candidate) {
  const normalizedValue = normalizeName(value);
  const normalizedCandidate = normalizeName(candidate);
  if (!normalizedValue || !normalizedCandidate) return false;
  if (normalizedValue === normalizedCandidate) return true;
  if (normalizedValue.length >= 3 && normalizedCandidate.includes(normalizedValue)) return true;
  return normalizedCandidate.length >= 3 && normalizedValue.includes(normalizedCandidate);
}

function cleanLineup(item) {
  const sourceLineup = Array.isArray(item.lineup_artists) && item.lineup_artists.length > 0
    ? item.lineup_artists
    : item.lineup;
  if (!Array.isArray(sourceLineup)) return [];
  const candidates = candidateNames(item);
  const seen = new Set();
  return sourceLineup.filter((name) => {
    const normalized = normalizeName(name);
    if (!normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    if (NON_ARTIST_LINEUP_NAMES.includes(normalized)) return false;
    return !candidates.some((candidate) => isSameEntity(name, candidate));
  });
}

function countOf(route) {
  return route.item_count ?? route.count ?? "";
}

function isoDate(value) {
  const text = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

function addDateRange(dates, start, end) {
  if (!start || !end || start > end) return;
  const startMs = Date.parse(`${start}T00:00:00Z`);
  const endMs = Date.parse(`${end}T00:00:00Z`);
  const dayMs = 24 * 60 * 60 * 1000;
  const days = Math.round((endMs - startMs) / dayMs);
  if (!Number.isFinite(days) || days < 1 || days > 31) return;
  for (let offset = 1; offset < days; offset += 1) {
    dates.add(new Date(startMs + offset * dayMs).toISOString().slice(0, 10));
  }
}

function itemDates(item) {
  const values = [
    item.event_date_start,
    item.event_date_end,
    item.event_date_iso_guess,
    ...(Array.isArray(item.event_date_iso_guesses) ? item.event_date_iso_guesses : []),
    ...(Array.isArray(item.event_date_text) ? item.event_date_text : []),
  ];
  const dates = new Set(values.map(isoDate).filter(Boolean).filter((value) => !isUnknownValue(value)));
  addDateRange(dates, isoDate(item.event_date_start), isoDate(item.event_date_end));
  return [...dates].sort();
}

function dateRoutesFromItems(items = []) {
  const counts = new Map();
  for (const item of items) {
    for (const date of itemDates(item)) counts.set(date, (counts.get(date) || 0) + 1);
  }
  return [...counts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, count]) => ({ date, count }));
}

function isUnknownValue(value) {
  return normalizeName(value) === "unknown" || normalizeName(value) === "未知城市";
}

function normalizeLang(lang) {
  return lang === "en" ? "en" : "zh";
}

function copyFor(lang) {
  return COPY[normalizeLang(lang)];
}

function langQuery(lang) {
  return normalizeLang(lang) === "en" ? "en" : "";
}

function buildPreviewUrl({ cityKey = "", date = "", lang = "" } = {}) {
  const params = new URLSearchParams();
  if (cityKey) params.set("cityKey", cityKey);
  if (date) params.set("date", date);
  if (langQuery(lang)) params.set("lang", langQuery(lang));
  const query = params.toString();
  return `/preview${query ? `?${query}` : ""}`;
}

function buildItemUrl(itemId, lang = "") {
  const encodedId = encodeURIComponent(itemId);
  const query = langQuery(lang) ? `?lang=${encodeURIComponent(langQuery(lang))}` : "";
  return `/preview/items/${encodedId}${query}`;
}

function itemTextSignals(item) {
  return [
    item.title,
    item.promoter,
    item.account,
    item.address,
    item.address_full,
    item.venue_name,
    ...(Array.isArray(item.venue) ? item.venue : []),
    ...(Array.isArray(item.evidence) ? item.evidence : []),
  ].filter(Boolean);
}

function verifiedAddress(item) {
  if (item.address_full) return item.address_full;
  if (item.address) return item.address;
  const signals = itemTextSignals(item).map(normalizeName).filter(Boolean);
  const match = VERIFIED_ADDRESS_BOOK.find((entry) =>
    entry.keys.some((key) => signals.some((signal) => signal.includes(normalizeName(key)))),
  );
  return match?.address || "";
}

function venueText(item) {
  return verifiedAddress(item) || item.venue_name || first(item.venue, "");
}

function compactMeta(parts) {
  return parts.filter(Boolean).map(escapeHtml).join(" · ");
}

function activeLabel(value, fallback) {
  return value || fallback;
}

function itemPlace(item) {
  return item.venue_name || first(item.venue, "") || first(item.city, item.city_key === "unknown" ? "" : item.city_key || "");
}

function normalizeHour(hour, meridiem = "") {
  let value = Number.parseInt(String(hour), 10);
  if (!Number.isFinite(value)) return "";
  const marker = meridiem.toLowerCase();
  if (marker === "pm" && value < 12) value += 12;
  if (marker === "am" && value === 12) value = 0;
  return String(value).padStart(2, "0");
}

function chineseTimeToClock(match, prefix, hour, minutePart = "") {
  let value = Number.parseInt(String(hour), 10);
  if (!Number.isFinite(value) || value > 24) return "";
  if (/下午|晚上|晚间|今晚|夜里/.test(prefix || "") && value >= 1 && value < 12) value += 12;
  if (/凌晨/.test(prefix || "") && value === 12) value = 0;
  const minutes = minutePart === "半" ? "30" : (minutePart || "").replace(/\D/g, "").padStart(2, "0") || "00";
  return `${String(value).padStart(2, "0")}:${minutes}`;
}

function extractEventTime(item) {
  if (item.event_time_text) return item.event_time_text;
  const text = [
    ...(Array.isArray(item.event_date_text) ? item.event_date_text : []),
    item.title,
    ...(Array.isArray(item.evidence) ? item.evidence : []),
  ]
    .filter(Boolean)
    .join(" | ");

  const rangeMatch = text.match(/\b([01]?\d|2[0-3])[:：]([0-5]\d)\s*(?:[-–—~至到]\s*([01]?\d|2[0-3])[:：]([0-5]\d))?\s*(AM|PM|am|pm)?\b/);
  if (rangeMatch) {
    const start = `${normalizeHour(rangeMatch[1], rangeMatch[5])}:${rangeMatch[2]}`;
    if (rangeMatch[3]) return `${start}-${normalizeHour(rangeMatch[3], rangeMatch[5])}:${rangeMatch[4]}`;
    return start;
  }

  const chineseMatch = text.match(/(凌晨|早上|上午|中午|下午|晚上|晚间|今晚|夜里)?\s*([01]?\d|2[0-3])\s*点(半|[0-5]\d分?)?/);
  if (chineseMatch) return chineseTimeToClock(chineseMatch[0], chineseMatch[1], chineseMatch[2], chineseMatch[3]);

  return "";
}

function rawBioLines(item) {
  if (Array.isArray(item.dj_bio_lines) && item.dj_bio_lines.length > 0) {
    return item.dj_bio_lines.map((line) => String(line).trim()).filter(Boolean).slice(0, 4);
  }
  if (!Array.isArray(item.evidence)) return [];
  const cleanLineupNames = cleanLineup(item).map(normalizeName).filter(Boolean);
  if (cleanLineupNames.length === 0) return [];
  const title = normalizeName(item.title);
  const cleanTitle = normalizeName(displayTitle(item));
  const account = normalizeName(item.account);
  const promoter = normalizeName(item.promoter);
  const city = normalizeName(first(item.city, ""));
  const venue = normalizeName(first(item.venue, ""));
  return item.evidence
    .filter(Boolean)
    .map((line) => String(line).trim())
    .filter((line) => !/^(来源公众号|公众号)[:：]/.test(line))
    .filter((line) => !/已关注|二维码|购票|点击|扫码|小程序/.test(line))
    .filter((line) => {
      const normalized = normalizeName(line);
      if (!normalized || normalized === title || normalized === cleanTitle) return false;
      if ([account, promoter, city, venue].filter(Boolean).includes(normalized)) return false;
      return cleanLineupNames.some((name) => normalized.includes(name));
    })
    .filter((line) => /dj|producer|artist|厂牌|发行|主理|来自|现居|音乐|舞曲|电子|场景|club|house|techno|bass|trax|break/i.test(line))
    .slice(0, 4);
}

function renderFilterSelect({ label, name, options, selectedValue, lang, selectedCity, selectedDate }) {
  const optionMarkup = options
    .map((option) => {
      const selected = option.value === selectedValue ? " selected" : "";
      return `<option value="${escapeHtml(option.href)}"${selected}>${escapeHtml(option.label)}</option>`;
    })
    .join("");
  return `<section class="filter-set">
  <div class="filter-label">${label}</div>
  <select class="filter-select" name="${name}" onchange="if(this.value) window.location.href=this.value">
    ${optionMarkup}
</select>
</section>`;
}

function renderDateSelector({ label, options, selectedValue }) {
  const optionMarkup = options
    .map((option) => {
      const active = option.value === selectedValue;
      const current = active ? ' aria-current="page"' : "";
      return `<a class="date-option${active ? " is-active" : ""}" href="${escapeHtml(option.href)}"${current}>
  <span>${escapeHtml(option.label)}</span>
</a>`;
    })
    .join("");
  return `<section class="filter-set date-filter">
  <div class="filter-label">${label}</div>
  <div class="date-strip">
    ${optionMarkup}
  </div>
</section>`;
}

function renderAddressFact(label, address, t) {
  if (!address) return "";
  return `<div class="fact address-fact"><span>${label}</span><div class="address-copy">
  <span class="address-text">${escapeHtml(address)}</span>
  <button class="copy-address" type="button" data-copy="${escapeHtml(address)}" data-copied="${escapeHtml(t.copiedAddress)}">${escapeHtml(t.copyAddress)}</button>
</div></div>`;
}

function hasPosterSource(item) {
  return Boolean(item.cover_image_url || item.cover_url || item.coverUrl);
}

function posterProxyUrl(item) {
  return hasPosterSource(item) && item.id ? `/api/v1/weekly/poster/${encodeURIComponent(item.id)}` : "";
}

function cleanDescriptionLines(item, fallbackLines = []) {
  const rawLines = Array.isArray(item.description_original_lines) && item.description_original_lines.length > 0
    ? item.description_original_lines
    : fallbackLines;
  const blocked = [
    item.title,
    item.title_original,
    displayTitle(item),
    item.account,
    item.promoter,
    item.venue_name,
    verifiedAddress(item),
    ...(Array.isArray(item.venue) ? item.venue : []),
    ...(Array.isArray(item.city) ? item.city : []),
  ].map(normalizeName).filter(Boolean);

  return rawLines
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .filter((line) => !/^[-—–_＝=]{3,}$/.test(line))
    .filter((line) => !/^(来源|公众号|日期|时间|地点|地址|场地|俱乐部|票价|门票|预售|现场|购票|报名|link|address|date|time|venue|tickets?)\s*[:：]/i.test(line))
    .filter((line) => !/^(📅|⏰|🎫|📍|地址|地点|时间|日期)/.test(line))
    .filter((line) => {
      const normalized = normalizeName(line);
      if (!normalized) return false;
      if (blocked.includes(normalized)) return false;
      return !blocked.some((value) => value.length >= 8 && normalized.includes(value));
    })
    .slice(0, 6);
}

export function renderLandingPage() {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HUAIDJ Atlas / Weekly API</title>
  <style>
    body{margin:0;background:#111;color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}
    main{max-width:880px;margin:0 auto;padding:48px 24px}
    h1{font-size:40px;line-height:1.1;margin:0 0 16px}
    p{color:#888;font-size:16px;line-height:1.7}
    a{color:#7eb8da;text-decoration:none;font-weight:700}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:28px}
    .link{display:block;border:1px solid #333;border-radius:6px;padding:18px;background:#1a1a1a}
    code{font-size:13px}
  </style>
</head>
<body>
  <main>
    <h1>HUAIDJ Atlas / Weekly</h1>
    <p>CloudBase Run compatible weekly-api. 图鉴成品层和本周活动侧面共用同一套只读服务入口。</p>
    <div class="grid">
      <a class="link" href="/atlas">打开中国地下电子音乐图鉴</a>
      <a class="link" href="/atlas/identity">打开身份审阅</a>
      <a class="link" href="/preview">打开活动预览</a>
      <a class="link" href="/api/v1/stage7/manifest">图鉴 manifest</a>
      <a class="link" href="/api/v1/weekly/current">current.json</a>
      <a class="link" href="/api/v1/weekly/cities">城市索引</a>
      <a class="link" href="/api/v1/weekly/dates">日期索引</a>
      <a class="link" href="/api/v1/weekly/manifest">发布 manifest</a>
      <a class="link" href="/healthz">healthz</a>
    </div>
  </main>
</body>
</html>`;
}

export function renderPreviewPage({ current, cities, dates, dateScope, selectedCity = "", selectedDate = "", lang = "" }) {
  const activeLang = normalizeLang(lang);
  const t = copyFor(activeLang);
  const nextLang = activeLang === "en" ? "zh" : "en";
  const langToggleUrl = buildPreviewUrl({ cityKey: selectedCity, date: selectedDate, lang: nextLang });
  const visibleCities = (cities.cities || []).filter((city) => {
    const key = city.city_key || "";
    const label = city.city || key;
    return !isUnknownValue(key) && !isUnknownValue(label);
  });
  const effectiveSelectedCity = isUnknownValue(selectedCity) ? "" : selectedCity;
  const effectiveSelectedDate = isUnknownValue(selectedDate) ? "" : selectedDate;
  const dateRoutes = effectiveSelectedCity && dateScope ? dateRoutesFromItems(dateScope.items) : (dates.dates || []);
  const visibleDates = dateRoutes.filter((date) => {
    const key = date.date || "";
    return key && !isUnknownValue(key);
  });

  const cityOptions = [
    {
      value: "",
      label: t.allCities,
      href: buildPreviewUrl({ date: effectiveSelectedDate, lang: activeLang }),
    },
    ...visibleCities.map((city) => {
      const key = city.city_key;
      return {
        value: key,
        label: `${city.city || key} ${countOf(city)}`.trim(),
        href: buildPreviewUrl({ cityKey: key, date: effectiveSelectedDate, lang: activeLang }),
      };
    }),
  ];

  const dateOptions = [
    {
      value: "",
      label: t.allDates,
      href: buildPreviewUrl({ cityKey: effectiveSelectedCity, lang: activeLang }),
    },
    ...visibleDates.map((date) => {
      const key = date.date;
      return {
        value: key,
        label: `${key} ${countOf(date)}`.trim(),
        href: buildPreviewUrl({ cityKey: effectiveSelectedCity, date: key, lang: activeLang }),
      };
    }),
  ];

  const resultCount = current.page?.total ?? current.items.length;
  const generatedAt = current.generatedAt || "";
  const activeSummary = compactMeta([
    activeLabel(effectiveSelectedCity, t.allCities),
    activeLabel(effectiveSelectedDate, t.allDates),
    `${resultCount} ${t.events}`,
  ]);

  const cards = current.items.length
    ? current.items.map((item, index) => {
        const city = first(item.city, item.city_key === "unknown" ? "" : item.city_key || "");
        const date = item.event_date_start || item.event_date_iso_guess || first(item.event_date_text, "");
        const time = extractEventTime(item);
        const lineup = joinList(cleanLineup(item));
        const styles = joinList(inferMusicStyles(item));
        const place = itemPlace(item);
        const promoter = item.promoter || item.account || "";
        const meta = compactMeta([date, time, city]);
        const title = displayTitle(item);
        const cover = posterProxyUrl(item);
        const poster = cover
          ? `<a class="event-poster" href="${buildItemUrl(item.id, activeLang)}"><img src="${escapeHtml(cover)}" alt=""></a>`
          : `<a class="event-poster event-poster-fallback" href="${buildItemUrl(item.id, activeLang)}">${escapeHtml(title)}</a>`;
        const venueLine = place ? `<div class="event-place">${escapeHtml(place)}</div>` : "";
        const promoterLine = promoter && promoter !== place ? `<div class="event-promoter">${escapeHtml(promoter)}</div>` : "";
        const lineupLine = lineup ? `<div class="event-lineup">${escapeHtml(lineup)}</div>` : "";
        const styleLine = styles ? `<div class="event-style">${escapeHtml(styles)}</div>` : "";
        return `<article class="event" style="--i:${index}">
  ${poster}
  <div class="event-body">
    <div class="event-kicker">
      <span>${meta}</span>
    </div>
    <div class="event-date">${escapeHtml(time || date || city || "")}</div>
    <h2><a href="${buildItemUrl(item.id, activeLang)}">${escapeHtml(title)}</a></h2>
    ${venueLine}
    ${promoterLine}
    ${lineupLine}
    ${styleLine}
  </div>
</article>`;
      }).join("")
    : `<div class="empty">${t.noEvents}</div>`;

  return `<!doctype html>
<html lang="${t.htmlLang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${t.title}</title>
  <style>
    :root{--bg:#111;--fg:#e0e0e0;--muted:rgba(255,255,255,.48);--dim:#555;--line:#1a1a1a;--line-strong:#242424;--soft:#1a1a1a;--accent:#7eb8da}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);font-family:"JetBrains Mono","SF Mono",Consolas,"Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:48px 48px;opacity:1}
    main{position:relative;display:grid;grid-template-columns:238px minmax(0,1fr);gap:34px;max-width:1080px;margin:0 auto;padding:18px 18px 64px}
    .rail{position:sticky;top:0;align-self:start;min-height:100vh;border-right:1px solid var(--line);padding:22px 22px 34px 0}
    .filter-label,.status-label,.event-kicker,.event-index,.empty{font:500 12px/1.2 "JetBrains Mono",Consolas,monospace;letter-spacing:.08em;text-transform:uppercase}
    .rail-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
    .brand-mark{display:flex;align-items:center}
    .brand-logo{display:block;width:88px;height:auto;opacity:.88}
    .lang-switch{display:inline-flex;align-items:center;min-height:30px;border:1px solid #292929;padding:7px 9px;color:#d7d7d7;background:#080808;text-decoration:none;font:500 11px/1 "JetBrains Mono",Consolas,monospace;letter-spacing:.06em;text-transform:uppercase}
    .lang-switch:hover,.lang-switch:focus{color:#fff;border-color:#555;outline:1px solid transparent}
    h1{margin:28px 0 0;color:#fff;font-family:"Noto Sans SC",sans-serif;font-size:clamp(24px,3.2vw,38px);font-weight:700;line-height:1.15;letter-spacing:0}
    .filters{display:grid;gap:22px;margin-top:28px}
    .filter-label{margin-bottom:9px;color:var(--dim)}
    .filter-select{width:100%;min-height:38px;border:1px solid #292929;border-radius:0;padding:9px 34px 9px 11px;color:#d7d7d7;background:#080808;font:500 12px/1.2 "JetBrains Mono",Consolas,monospace;letter-spacing:.04em;text-transform:uppercase}
    .filter-select:focus{border-color:var(--accent);outline:1px solid rgba(126,184,218,.25)}
    .date-strip{display:flex;flex-wrap:nowrap;gap:8px;align-items:flex-start;overflow-x:auto;padding-bottom:2px;scrollbar-width:none}
    .date-strip::-webkit-scrollbar{display:none}
    .date-option{position:relative;display:inline-flex;align-items:center;flex:0 0 auto;min-height:36px;border:1px solid #292929;padding:9px 12px;color:#d7d7d7;background:#080808;text-decoration:none;font:500 12px/1.15 "JetBrains Mono",Consolas,monospace;letter-spacing:.04em;text-transform:uppercase;transition:color .18s ease,border-color .18s ease,background-color .18s ease,transform .18s ease}
    .date-option:before{content:"";position:absolute;left:-1px;top:-1px;bottom:-1px;width:3px;background:var(--accent);transform:scaleY(0);transform-origin:bottom;transition:transform .2s ease}
    .date-option:hover,.date-option:focus{border-color:#555;color:#fff;transform:translateY(-1px);outline:0}
    .date-option:hover:before,.date-option:focus:before{transform:scaleY(1)}
    .date-option.is-active{border-color:var(--accent);background:rgba(126,184,218,.08);color:var(--accent)}
    .date-option.is-active:before{transform:scaleY(1);background:#050505}
    .content{min-width:0;padding-top:22px}
    .status{display:grid;grid-template-columns:1fr auto;gap:16px;align-items:end;border-bottom:1px solid var(--line-strong);padding:0 0 16px}
    .status-label{color:var(--accent);margin-bottom:8px}
    .status h2{margin:0;color:#fff;font-size:clamp(20px,2.7vw,34px);line-height:1.12;font-weight:520}
    .status p{margin:8px 0 0;color:var(--muted);font-size:14px;line-height:1.55}
    .generated{color:var(--dim);text-align:right;font:500 11px/1.5 "JetBrains Mono",Consolas,monospace;text-transform:uppercase}
    .event{display:grid;grid-template-columns:minmax(136px,196px) minmax(0,1fr);gap:22px;border-bottom:1px solid var(--line);padding:22px 0 24px;animation:eventIn .42s ease both;animation-delay:calc(var(--i,0) * 30ms);transition:border-color .18s ease,transform .18s ease}
    .event:hover{border-color:#393939;transform:translateX(2px)}
    .event-poster{display:block;aspect-ratio:4/5;overflow:hidden;background:#171717;color:#f4f4f4;text-decoration:none}
    .event-poster img{display:block;width:100%;height:100%;object-fit:cover;transition:transform .25s ease}
    .event:hover .event-poster img{transform:scale(1.025)}
    .event-poster-fallback{display:flex;align-items:flex-end;padding:16px;background:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px),#111;background-size:36px 36px;color:#e0e0e0;font-family:"Noto Sans SC",sans-serif;font-size:20px;line-height:1.16;font-weight:700}
    .event-date{margin-top:4px;color:var(--accent);padding-top:3px;font:600 15px/1.2 "JetBrains Mono",Consolas,monospace;letter-spacing:.05em;text-transform:uppercase}
    .event-kicker{display:flex;justify-content:space-between;gap:14px;color:#707070;line-height:1.45}
    .event h2{max-width:760px;margin:10px 0 12px;font-family:"Noto Sans SC",sans-serif;font-size:clamp(22px,3vw,34px);line-height:1.16;font-weight:720;letter-spacing:0}
    .event h2 a{color:#f4f4f4;text-decoration:none;transition:color .18s ease}
    .event h2 a:hover{color:var(--accent)}
    .event-place,.event-promoter,.event-lineup,.event-style{max-width:760px;margin-top:7px;color:#a9a9a9;font-size:15px;line-height:1.5}
    .event-promoter{color:#707070}
    .event-lineup{color:#cfcfcf}
    .event-style{color:#7d7d7d;font:500 12px/1.4 "JetBrains Mono",Consolas,monospace;text-transform:uppercase}
    .empty{padding:64px 0;color:#777;text-align:center}
    @keyframes eventIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
    @media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important;scroll-behavior:auto!important}.event:hover,.date-option:hover,.date-option:focus{transform:none}}
    @media (max-width:780px){main{display:block;padding:0 16px 56px}.rail{position:relative;min-height:0;border-right:0;border-bottom:1px solid var(--line);padding:18px 0 18px}.filters{margin-top:18px}.content{padding-top:16px}.status{grid-template-columns:1fr}.status h2{font-size:21px;line-height:1.14}.generated{text-align:left}.event{grid-template-columns:112px minmax(0,1fr);gap:14px;padding:20px 0}.event-date{font-size:13px}.event-kicker{display:none}.event h2{font-size:20px;line-height:1.16}.event-poster-fallback{font-size:17px}.event-place,.event-promoter,.event-lineup,.event-style{font-size:13px}}
  </style>
</head>
<body>
  <main>
    <aside class="rail">
      <div class="rail-head">
        <div class="brand-mark">
          <div>
            <img class="brand-logo" src="/assets/huaidj-logo-nav-512x128.png" alt="坏DJ">
          </div>
        </div>
        <a class="lang-switch" href="${langToggleUrl}">${t.langToggle}</a>
      </div>
      <h1>HUAIDJ WEEKLY</h1>
      <nav class="filters">
        ${renderFilterSelect({ label: t.cityFilter, name: "cityKey", options: cityOptions, selectedValue: effectiveSelectedCity, lang: activeLang, selectedCity: effectiveSelectedCity, selectedDate: effectiveSelectedDate })}
        ${renderDateSelector({ label: t.dateFilter, options: dateOptions, selectedValue: effectiveSelectedDate })}
      </nav>
    </aside>
    <section class="content">
      <header class="status">
        <div>
          <div class="status-label">${t.weeklyEvents}</div>
          <h2>${activeSummary}</h2>
          ${t.statusHelp ? `<p>${t.statusHelp}</p>` : ""}
        </div>
        <div class="generated">${generatedAt ? `generated<br>${escapeHtml(generatedAt)}` : ""}</div>
      </header>
      ${cards}
    </section>
  </main>
</body>
</html>`;
}

export function renderItemPage(item, { lang = "" } = {}) {
  const activeLang = normalizeLang(lang);
  const t = copyFor(activeLang);
  const nextLang = activeLang === "en" ? "zh" : "en";
  const langToggleUrl = `${buildItemUrl(item.id, nextLang)}`;
  const city = first(item.city, item.city_key === "unknown" ? "" : item.city_key || "");
  const date = item.event_date_start || item.event_date_iso_guess || first(item.event_date_text, "");
  const time = extractEventTime(item);
  const meta = compactMeta([date, time, city]);
  const venueName = item.venue_name || first(item.venue, "");
  const address = verifiedAddress(item) || item.address || "";
  const lineup = joinList(cleanLineup(item));
  const styles = joinList(inferMusicStyles(item));
  const bioLines = rawBioLines(item);
  const descriptionItems = cleanDescriptionLines(item, bioLines).map((line) => `<p>${escapeHtml(line)}</p>`).join("");
  const bioItems = bioLines.map((line) => `<p>${escapeHtml(line)}</p>`).join("");
  const posterUrl = posterProxyUrl(item);
  const posterSection = posterUrl
    ? `<section class="poster-section"><img class="detail-poster" src="${escapeHtml(posterUrl)}" alt=""></section>`
    : "";
  const descriptionSection = descriptionItems
    ? `<section>
      <h2>DESCRIPTION</h2>
      <div class="bio-lines">${descriptionItems}</div>
    </section>`
    : "";
  const bioSection = bioItems
    ? `<section>
      <h2>${t.djBio}</h2>
      <div class="bio-lines">${bioItems}</div>
    </section>`
    : "";
  const promoter = item.promoter || item.account || "";
  const cityLine = city ? `<p class="fact"><span>${t.city}</span>${escapeHtml(city)}</p>` : "";
  const dateLine = date ? `<p class="fact"><span>${t.date}</span>${escapeHtml(date)}</p>` : "";
  const timeLine = time ? `<p class="fact"><span>${t.time}</span>${escapeHtml(time)}</p>` : "";
  const clubLine = promoter ? `<p class="fact"><span>${t.club}</span>${escapeHtml(promoter)}</p>` : "";
  const venueNameLine = venueName ? `<p class="fact"><span>${t.venue}</span>${escapeHtml(venueName)}</p>` : "";
  const styleLine = styles ? `<p class="fact"><span>${t.style}</span>${escapeHtml(styles)}</p>` : "";
  const lineupLine = lineup ? `<p class="fact"><span>DJ LINEUP</span>${escapeHtml(lineup)}</p>` : "";
  const venueLine = renderAddressFact(t.address, address, t);
  const title = displayTitle(item);
  return `<!doctype html>
<html lang="${t.htmlLang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(item.title)}</title>
  <style>
    :root{--bg:#111;--fg:#e0e0e0;--muted:#707070;--line:#1a1a1a;--accent:#7eb8da}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);font-family:"JetBrains Mono","SF Mono",Consolas,"Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:48px 48px}
    main{position:relative;max-width:820px;margin:0 auto;padding:32px 20px 64px}
    a{color:var(--accent);text-decoration:none;font-weight:600}
    .topbar{display:flex;align-items:flex-start;justify-content:space-between;gap:24px}
    .topbar-actions{display:flex;align-items:center;gap:12px}
    .brand-mark{display:flex;align-items:center}
    .brand-logo{display:block;width:88px;height:auto;opacity:.88}
    .back,.lang-switch{color:#777;font:500 12px/1 "JetBrains Mono",Consolas,monospace;letter-spacing:.08em;text-transform:uppercase}
    .lang-switch{border:1px solid #292929;padding:8px 9px;color:#d7d7d7;background:#080808}
    h1{font-family:"Noto Sans SC",sans-serif;font-size:clamp(26px,4.6vw,40px);font-weight:720;line-height:1.14;margin:30px 0 16px}
    .meta,p{color:#858585;line-height:1.65}
    .meta{font:500 12px/1.45 "JetBrains Mono",Consolas,monospace;letter-spacing:.06em;text-transform:uppercase}
    section{border-top:1px solid var(--line);margin-top:32px;padding-top:24px}
    .poster-section{padding-top:28px}
    .detail-poster{display:block;width:100%;max-height:820px;object-fit:contain;border:1px solid #1d1d1d;background:#080808}
    .fact{display:grid;grid-template-columns:92px 1fr;gap:18px;margin:10px 0}
    .fact span{color:#595959;font:500 11px/1.7 "JetBrains Mono",Consolas,monospace;letter-spacing:.08em}
    .address-copy{display:flex;align-items:flex-start;gap:12px;min-width:0}
    .address-copy .address-text{min-width:0;color:#8f8f8f;font:inherit;letter-spacing:0;text-transform:none}
    .copy-address{flex:0 0 auto;border:1px solid #2d2d2d;background:#080808;color:var(--accent);padding:7px 9px;font:600 11px/1 "JetBrains Mono",Consolas,monospace;letter-spacing:.06em;cursor:pointer;transition:background-color .18s ease,border-color .18s ease,color .18s ease,transform .18s ease}
    .copy-address:hover,.copy-address:focus{border-color:var(--accent);background:#111;outline:0;transform:translateY(-1px)}
    .copy-address.is-copied{background:var(--accent);border-color:var(--accent);color:#050505}
    h2{margin:0 0 20px;font-size:24px;line-height:1.2;font-weight:650}
    .bio-lines p{margin:0 0 18px;color:#8a8a8a;font-size:18px;line-height:1.72}
    @media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important;scroll-behavior:auto!important}.copy-address:hover,.copy-address:focus{transform:none}}
    @media (max-width:560px){.fact{grid-template-columns:1fr;gap:2px}.address-copy{display:grid;gap:8px}.copy-address{justify-self:start}}
  </style>
</head>
<body>
  <main>
    <div class="topbar">
      <div class="topbar-actions">
        <a class="back" href="${buildPreviewUrl({ lang: activeLang })}">${t.back}</a>
        <a class="lang-switch" href="${langToggleUrl}">${t.langToggle}</a>
      </div>
      <div class="brand-mark">
        <div>
          <img class="brand-logo" src="/assets/huaidj-logo-nav-512x128.png" alt="坏DJ">
        </div>
      </div>
    </div>
    <h1>${escapeHtml(title)}</h1>
    <div class="meta">${meta}</div>
    <section>
      ${venueNameLine}
      ${venueLine}
      ${dateLine}
      ${timeLine}
      ${cityLine}
      ${clubLine}
      ${styleLine}
      ${lineupLine}
    </section>
    ${posterSection}
    ${descriptionSection}
    ${bioSection}
  </main>
  <script>
    document.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-copy]");
      if (!button) return;
      const text = button.getAttribute("data-copy") || "";
      const original = button.textContent;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else {
          const area = document.createElement("textarea");
          area.value = text;
          area.setAttribute("readonly", "");
          area.style.position = "fixed";
          area.style.left = "-9999px";
          document.body.appendChild(area);
          area.select();
          document.execCommand("copy");
          area.remove();
        }
        button.textContent = button.getAttribute("data-copied") || original;
        button.classList.add("is-copied");
        window.setTimeout(() => {
          button.textContent = original;
          button.classList.remove("is-copied");
        }, 1200);
      } catch {
        button.textContent = original;
      }
    });
  </script>
</body>
</html>`;
}

