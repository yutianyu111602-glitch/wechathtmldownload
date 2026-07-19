const {
  addDaysToDateKey,
  currentShanghaiBusinessDateKey,
  weekendDateRangeFromDateKey,
} = require("../../shared/businessDate");

const DEFAULT_LIMIT = 10;
const MAX_LIMIT = 20;
const PAGE_LIMIT = 100;

function safeText(value) {
  if (Array.isArray(value)) return value.map(safeText).filter(Boolean).join(" ");
  if (value === undefined || value === null) return "";
  return String(value).replace(/\s+/g, " ").trim();
}

function isoDate(value) {
  const text = safeText(value);
  const match = text.match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function addDays(dateKey, days) {
  return addDaysToDateKey(dateKey, days);
}

function currentLocalDateKey(now = new Date()) {
  return currentShanghaiBusinessDateKey(now);
}

function weekendRange(referenceDate) {
  return weekendDateRangeFromDateKey(referenceDate);
}

function resolveDateRange(input, now) {
  const directFrom = isoDate(input.dateFrom);
  const directTo = isoDate(input.dateTo);
  if (directFrom || directTo) {
    const start = directFrom || directTo;
    const end = directTo || directFrom;
    return start <= end ? { dateFrom: start, dateTo: end } : { dateFrom: end, dateTo: start };
  }
  const referenceDate = isoDate(input.referenceDate) || currentLocalDateKey(now);
  if (input.timeHint === "tonight") return { dateFrom: referenceDate, dateTo: referenceDate };
  if (input.timeHint === "weekend") return weekendRange(referenceDate);
  if (input.timeHint === "this_week") return { dateFrom: referenceDate, dateTo: addDays(referenceDate, 6) };
  if (input.timeHint === "next_15_days") return { dateFrom: referenceDate, dateTo: addDays(referenceDate, 14) };
  return { dateFrom: "", dateTo: "" };
}

function itemDates(item) {
  const start = isoDate(item.event_date_start || item.eventDateStart || item.date || item.dateLabel);
  const end = isoDate(item.event_date_end || item.eventDateEnd) || start;
  const guess = isoDate(item.event_date_iso_guess || item.eventDateIsoGuess);
  return { start: start || guess, end: end || start || guess };
}

function overlapsRange(item, from, to) {
  if (!from && !to) return true;
  const dates = itemDates(item);
  if (!dates.start) return false;
  const start = dates.start;
  const end = dates.end || dates.start;
  const min = from || to;
  const max = to || from;
  return end >= min && start <= max;
}

function cityText(item) {
  return safeText(item.city || item.city_name || item.cityName || item.city_key || item.cityKey);
}

function venueText(item) {
  return safeText(item.venue_name || item.venueName || item.venue || item.place_name || item.placeName);
}

function titleText(item) {
  return safeText(item.title || item.display_title || item.displayTitle || item.event_title || item.name);
}

function lineupList(item) {
  const raw = item.lineup || item.artists || item.artist_names || item.artistNames || [];
  if (Array.isArray(raw)) return raw.map(safeText).filter(Boolean);
  return safeText(raw).split(/[、,，/]/).map(safeText).filter(Boolean);
}

function styleList(item) {
  const raw = item.styles || item.style || item.style_tags || item.styleTags || item.styleLabel || [];
  if (Array.isArray(raw)) return raw.map(safeText).filter(Boolean);
  return safeText(raw).split(/[、,，/]/).map(safeText).filter(Boolean);
}

function haystack(item) {
  return [
    titleText(item),
    cityText(item),
    venueText(item),
    safeText(item.source_account_name || item.sourceAccountName || item.account || item.promoter),
    lineupList(item).join(" "),
    styleList(item).join(" "),
  ].join(" ").toLowerCase();
}

function matchesText(item, value) {
  const query = safeText(value).toLowerCase();
  if (!query) return true;
  return haystack(item).includes(query);
}

function matchesCity(item, value) {
  const query = safeText(value).toLowerCase();
  if (!query) return true;
  const candidates = [
    cityText(item),
    safeText(item.city_key || item.cityKey),
    safeText(item.city_keys || item.cityKeys),
  ]
    .map((text) => text.toLowerCase())
    .filter(Boolean);
  return candidates.some((text) => text.includes(query));
}

function hasPoster(item) {
  return !!(
    item.posterFileId ||
    item.poster_file_id ||
    item.coverFileId ||
    item.cover_file_id ||
    item.coverUrl ||
    item.cover_url ||
    item.cover_image_url
  );
}

function firstHttpsUrl(...values) {
  for (const value of values) {
    const text = safeText(value);
    if (/^https:\/\//i.test(text)) return text;
  }
  return "";
}

// 原子组件 image 仅支持网络 png/jpg；把活动海报解析成可加载的 https。
// 优先用现成 https 字段；只有 cloud:// fileId 时按 tcb 公网域名转换（纯字符串，无网络调用）。
function posterHttpUrl(item) {
  const direct = firstHttpsUrl(
    item.coverUrl,
    item.cover_url,
    item.cover_image_url,
    item.posterUrl,
    item.poster_url,
    item.posterTempUrl,
  );
  if (direct) return direct;
  const fileId = safeText(item.posterFileId || item.poster_file_id || item.coverFileId || item.cover_file_id);
  const match = fileId.match(/^cloud:\/\/([^.]+)\.[^/]+\/(.+)$/i);
  return match ? `https://${match[1]}.tcb.qcloud.la/${match[2]}` : "";
}

function hasSource(item) {
  if (item.source_action && item.source_action.available === false) return false;
  return !!(
    item.sourceHash ||
    item.source_ref_id ||
    item.sourceRefId ||
    item.source_action ||
    item.source_article ||
    (Array.isArray(item.sourceArticles) && item.sourceArticles.length)
  );
}

function toPublicEvent(item) {
  const dates = itemDates(item);
  const id = safeText(item.id || item.event_id || item.eventId);
  return {
    id,
    title: titleText(item),
    date: dates.start,
    city: cityText(item),
    venue: venueText(item),
    lineup: lineupList(item).slice(0, 8),
    styles: styleList(item).slice(0, 5),
    posterAvailable: hasPoster(item),
    sourceAvailable: hasSource(item),
    detailPath: id ? `/pages/detail/detail?id=${encodeURIComponent(id)}` : "",
  };
}

function normalizeCurrentPayload(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload && payload.items)) return payload.items;
  if (Array.isArray(payload && payload.data && payload.data.items)) return payload.data.items;
  return [];
}

function requestJson(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    if (typeof wx === "undefined" || typeof wx.request !== "function") {
      reject(new Error("WX_REQUEST_UNAVAILABLE"));
      return;
    }
    wx.request({
      url,
      method: "GET",
      timeout: timeoutMs || 8000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data);
        else reject(new Error(`HTTP_${res.statusCode}`));
      },
      fail(error) {
        reject(error || new Error("REQUEST_FAILED"));
      },
    });
  });
}

function buildApiUrl(baseUrl, cursor) {
  const params = [
    "scope=current",
    "lookbackDays=0",
    `limit=${PAGE_LIMIT}`,
  ];
  if (cursor !== undefined && cursor !== null && cursor !== "") params.push(`cursor=${encodeURIComponent(cursor)}`);
  return `${String(baseUrl).replace(/\/+$/, "")}/api/v1/weekly/current?${params.join("&")}`;
}

async function fetchAllCurrentPages(requestPage) {
  let cursor = 0;
  const all = [];
  const seenIds = new Set();
  const seenCursors = new Set();
  let expectedTotal = null;
  let expectedGeneration = "";
  for (let page = 0; ; page += 1) {
    if (seenCursors.has(cursor)) throw new Error(`AI_CURRENT_CURSOR_LOOP:${cursor}`);
    seenCursors.add(cursor);
    const payload = await requestPage(cursor);
    const generation = safeText(payload && (payload.generatedAt || payload.generated_at || payload.syncId));
    if (!generation) throw new Error("AI_CURRENT_GENERATION_MISSING");
    if (!expectedGeneration) expectedGeneration = generation;
    else if (generation !== expectedGeneration) throw new Error(`AI_CURRENT_GENERATION_DRIFT:${expectedGeneration}->${generation}`);
    const scope = safeText(payload && payload.filters && payload.filters.scope).toLowerCase();
    if (scope !== "current") throw new Error(`AI_CURRENT_SCOPE_INVALID:${scope || "missing"}`);
    const total = Number(payload && payload.page && payload.page.total);
    if (!Number.isFinite(total) || total < 0 || !Number.isInteger(total)) {
      throw new Error(`AI_CURRENT_TOTAL_INVALID:${payload && payload.page && payload.page.total}`);
    }
    if (expectedTotal === null) expectedTotal = total;
    else if (total !== expectedTotal) throw new Error(`AI_CURRENT_TOTAL_DRIFT:${expectedTotal}->${total}`);
    const declaredCursor = payload && payload.page && payload.page.cursor;
    if (declaredCursor !== undefined && declaredCursor !== null && declaredCursor !== "" && Number(declaredCursor) !== cursor) {
      throw new Error(`AI_CURRENT_CURSOR_MISMATCH:${declaredCursor}!=${cursor}`);
    }
    for (const item of normalizeCurrentPayload(payload)) {
      const id = safeText(item && (item.id || item.event_id || item.eventId));
      if (!id) throw new Error("AI_CURRENT_EVENT_ID_MISSING");
      if (seenIds.has(id)) throw new Error(`AI_CURRENT_DUPLICATE_ID:${id}`);
      seenIds.add(id);
      all.push(item);
    }
    if (all.length > expectedTotal) throw new Error(`AI_CURRENT_TOTAL_OVERFLOW:${all.length}>${expectedTotal}`);
    const nextCursor = payload && payload.page && payload.page.nextCursor;
    if (nextCursor === null || nextCursor === undefined || nextCursor === "") {
      if (all.length !== expectedTotal) throw new Error(`AI_CURRENT_TOTAL_MISMATCH:${all.length}!=${expectedTotal}`);
      return all;
    }
    const parsedNext = Number(nextCursor);
    if (!Number.isFinite(parsedNext) || !Number.isInteger(parsedNext) || parsedNext <= cursor) {
      throw new Error(`AI_CURRENT_CURSOR_INVALID:${nextCursor}`);
    }
    const expectedPageCount = Math.max(1, Math.ceil(expectedTotal / PAGE_LIMIT));
    if (page + 1 >= expectedPageCount) {
      throw new Error(`AI_CURRENT_PAGE_LIMIT_EXCEEDED:${expectedPageCount}`);
    }
    cursor = parsedNext;
  }
}

async function fetchCurrentFromPublicApi() {
  const app = typeof getApp === "function" ? getApp() : null;
  const cloud = (app && app.globalData && app.globalData.cloud) || {};
  const baseUrl = cloud.useMock ? cloud.mockBaseUrl : cloud.publicBaseUrl;
  if (!baseUrl) throw new Error("NO_PUBLIC_BASE_URL");
  return fetchAllCurrentPages((cursor) => (
    requestJson(buildApiUrl(baseUrl, cursor), cloud.requestTimeoutMs || 8000)
  ));
}

function filterEvents(items, input, now) {
  const range = resolveDateRange(input, now);
  const city = safeText(input.city);
  const keyword = safeText(input.keyword);
  const style = safeText(input.style);
  return (Array.isArray(items) ? items : [])
    .filter((item) => overlapsRange(item, range.dateFrom, range.dateTo))
    .filter((item) => matchesCity(item, city))
    .filter((item) => matchesText(item, keyword))
    .filter((item) => matchesText(item, style))
    .sort((left, right) => {
      const a = toPublicEvent(left);
      const b = toPublicEvent(right);
      return [a.date, a.city, a.venue, a.title].join("\t").localeCompare(
        [b.date, b.city, b.venue, b.title].join("\t"),
        "zh-Hans-CN"
      );
    });
}

function buildSummary(events, total, query) {
  if (!total) {
    return "当前没有匹配到可确认活动。可以换一个城市、扩大日期范围，或换一个 DJ / 俱乐部 / 风格关键词再试。";
  }
  const lines = events.map((event, index) => {
    const lineup = event.lineup.length ? `，阵容：${event.lineup.join(" / ")}` : "";
    const poster = event.posterAvailable ? "，有海报" : "，暂未收录海报";
    return `${index + 1}. ${event.date} ${event.city} ${event.venue}：${event.title}${lineup}${poster}`;
  });
  const filterText = [query.city, query.dateFrom && query.dateTo ? `${query.dateFrom}..${query.dateTo}` : "", query.keyword, query.style]
    .map(safeText)
    .filter(Boolean)
    .join(" / ");
  return `已找到 ${total} 个匹配活动${filterText ? `（${filterText}）` : ""}。${lines.join(" ")}。活动时间、阵容和票务请以主办方公开信息为准。`;
}

async function searchEvents(input = {}, options = {}) {
  const limit = Math.max(1, Math.min(MAX_LIMIT, Number(input.limit || DEFAULT_LIMIT)));
  let items;
  try {
    items = options.items || (options.fetchCurrent ? await options.fetchCurrent() : await fetchCurrentFromPublicApi());
  } catch (error) {
    return {
      isError: true,
      content: [{
        type: "text",
        text: "我现在不能读取当前活动数据。请进入小程序“活动”页，按城市和日期筛选最新结果。",
      }],
      structuredContent: {
        total: 0,
        events: [],
        query: input,
        error: safeText(error && (error.errMsg || error.message || error)),
      },
    };
  }
  const matched = filterEvents(items, input, options.now || new Date());
  const matchedTop = matched.slice(0, limit);
  const publicEvents = matchedTop.map(toPublicEvent);
  // 海报 https 仅放 _meta（对 LLM 不可见，专供原子组件渲染），不污染 structuredContent。
  const posters = {};
  matchedTop.forEach((raw) => {
    const id = safeText(raw.id || raw.event_id || raw.eventId);
    const url = posterHttpUrl(raw);
    if (id && url) posters[id] = url;
  });
  const range = resolveDateRange(input, options.now || new Date());
  const query = {
    city: safeText(input.city),
    dateFrom: range.dateFrom,
    dateTo: range.dateTo,
    timeHint: safeText(input.timeHint),
    keyword: safeText(input.keyword),
    style: safeText(input.style),
    limit,
  };
  const summary = buildSummary(publicEvents, matched.length, query);
  // 事实 + 动作两段式：先陈述结果，再引导出活动卡片（official best-practices 4.2）。
  const text = matched.length ? `${summary} 请用活动卡片（event-list）展示以上活动。` : summary;
  return {
    isError: false,
    content: [{ type: "text", text }],
    structuredContent: {
      total: matched.length,
      events: publicEvents,
      query,
    },
    _meta: { posters },
  };
}

searchEvents._private = {
  filterEvents,
  fetchAllCurrentPages,
  resolveDateRange,
  toPublicEvent,
  currentLocalDateKey,
  posterHttpUrl,
};

module.exports = searchEvents;
