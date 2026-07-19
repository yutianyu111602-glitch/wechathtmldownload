const { fetchAllCurrentItems, requestApi } = require("../../utils/api");
const { compactItem } = require("../../utils/format");
const { normalizeLang, applyLanguageChrome } = require("../../utils/i18n");
const { vibrateLight } = require("../../utils/haptics");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");
const { buildFootprintCard } = require("../../utils/footprintCard");

// ATLAS = DJ/俱乐部关系图谱探索宇宙。数据来自后端 /api/v1/atlas/family/profile
// （serving DB 的 dj_relation_rollup / dj_venue_rollup）。点一颗星 → 展开 ta 的
// 同台 DJ 与常驻房间 → 继续点下去漫游图谱。纯 WXML/WXSS 极坐标星图，无 Canvas/web-view。
// 玩法：关系越强的星越大越亮；点过的星会被「点亮」收藏；顶部轨迹可回到任意一跳。
const VISITED_KEY = "atlasVisitedStars:v1";
const DEFAULT_ATLAS_ENTRY = "COLA REN";
const MAX_SEED_PROFILE_ATTEMPTS = 8;
// 入口优选稠密 DJ：种子的图谱邻居 < 这个数就视为偏稀疏，继续找更热闹的入口。
const MIN_SEED_NEIGHBORS = 3;
const NON_ARTIST_SEED_RE = /(活动|派对|巡演|专场|预售|门票|票价|购票|重磅|客座|厂牌|呈现|周年|音乐节|club|bar|room|stage|tickets?|pres\.|presents?)/i;

const LABELS = {
  zh: {
    title: "ATLAS 星图",
    subtitle: "DJ × 俱乐部 关系宇宙",
    intro: "点一颗星，看 ta 和谁同台、常驻哪些房间，再一直点下去。",
    seedHint: "本周活动里的人 · 任选一颗进入",
    loading: "正在连接星图…",
    empty: "这颗星暂时没有公开的关系记录，换一颗试试。",
    deadEnd: "这颗星没有更多同台记录了，换一颗继续探索。",
    error: "星图连接失败，下拉重试。",
    historyTitle: "近期演出",
    detailLink: "看本周演出 →",
    collected: "已点亮",
    starUnit: "颗星",
    newStar: "✨ 点亮新星",
    scoreLabel: "关系分",
    setsUnit: "场",
    statsEvents: "场演出",
    statsRel: "位同台",
    statsVenues: "个房间",
    relLabel: "同厂牌",
    relVenue: "同场馆",
    relSet: "同台",
    orgUnit: "厂牌 / 主办",
    randomHop: "🎲 随机跳",
    footprintTitle: "我的足迹",
    footprintBtn: "生成我的足迹卡",
    footprintEmpty: "先点亮几颗星再来生成",
    footprintDjUnit: "位 DJ",
    footprintCityUnit: "座城市",
    footprintLinks: "条同台连线",
    footprintHint: "基于你点亮过的星 · 匿名 · 仅本机",
    footprintShare: "分享给朋友",
  },
  en: {
    title: "ATLAS Starmap",
    subtitle: "DJ × Club relationship universe",
    intro: "Tap a star to see who they play with and which rooms they haunt, then keep going.",
    seedHint: "People in this week's events · pick one to enter",
    loading: "Connecting the starmap…",
    empty: "No public relationship records for this star yet — try another.",
    deadEnd: "This star has no more connections — pick another to keep exploring.",
    error: "Starmap connection failed, pull down to retry.",
    historyTitle: "Recent sets",
    detailLink: "This week's event →",
    collected: "Lit",
    starUnit: "stars",
    newStar: "✨ New star lit",
    scoreLabel: "affinity",
    setsUnit: "sets",
    statsEvents: "sets",
    statsRel: "peers",
    statsVenues: "rooms",
    relLabel: "same label",
    relVenue: "same venue",
    relSet: "co-bill",
    orgUnit: "label / promoter",
    randomHop: "🎲 Surprise",
    footprintTitle: "My footprint",
    footprintBtn: "Build my footprint",
    footprintEmpty: "Light up a few stars first",
    footprintDjUnit: "DJs",
    footprintCityUnit: "cities",
    footprintLinks: "co-bill links",
    footprintHint: "From the stars you've lit · anonymous · on-device",
    footprintShare: "Share with friends",
  },
};

function atlasKind(type) {
  const t = String(type || "").toLowerCase();
  if (t.includes("venue") || t.includes("place") || t.includes("club")) return "venue";
  if (t.includes("organ") || t.includes("label") || t.includes("radio") || t.includes("crew") || t.includes("promot")) return "org";
  return "dj";
}

// 关系类型标签（F）：从后端已带的 metrics 里读出「为什么连」，让边有语义。
// 优先级：直接同台 > 同厂牌 > 同场馆（2-hop 回填的弱连接排在直接关系之后）。
function relationMeta(metrics, t) {
  const m = metrics || {};
  const sets = Number(m.sameEventCount) || 0;
  if (sets > 0) return `${t.relSet} ${sets}`;
  if (Number(m.sameLabelCount) > 0) return t.relLabel;
  if (Number(m.sameVenueCount) > 0) return t.relVenue;
  return "";
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function tierOf(weight) {
  if (weight >= 0.66) return "strong";
  if (weight >= 0.33) return "mid";
  return "weak";
}

function sectionItems(profile, key) {
  const sections = profile && profile.sections;
  const section = sections && sections[key];
  return (section && Array.isArray(section.items) && section.items) || [];
}

function eventSubtitle(event) {
  return [event.date || event.time, event.venueName || event.venue, event.city].filter(Boolean).join(" · ");
}

function seedNameFromCandidate(raw) {
  if (!raw) return "";
  if (typeof raw === "object") {
    return String(raw.displayName || raw.canonicalName || raw.name || raw.label || raw.title || "").trim();
  }
  return String(raw || "").trim();
}

function isLikelyAtlasSeedName(name) {
  const text = String(name || "").trim();
  if (!text || text.length > 40) return false;
  if (/https?:\/\/|www\.|@/.test(text)) return false;
  if (NON_ARTIST_SEED_RE.test(text)) return false;
  if (/[：:｜|]/.test(text) && !/[A-Za-z0-9]/.test(text)) return false;
  return true;
}

function addSeed(seedList, seen, name, detailId, visited) {
  const label = seedNameFromCandidate(name);
  if (!isLikelyAtlasSeedName(label) || seen[label]) return false;
  seen[label] = true;
  seedList.push({ name: label, detailId, visited: visited.has(label) });
  return true;
}

function legacyDjProfileToFamilyProfile(payload, query) {
  if (!payload || payload.found === false || !payload.profile) return null;
  const profile = payload.profile || {};
  const name = String(profile.displayName || query || "").trim();
  if (!name) return null;
  const events = Array.isArray(payload.events) ? payload.events : [];
  const collaborators = Array.isArray(payload.collaborators) ? payload.collaborators : [];
  const venues = Array.isArray(payload.venues) ? payload.venues : [];
  return {
    found: true,
    source: "weekly_atlas_dj_profile_fallback",
    canonical: {
      id: String(profile.djId || name),
      name,
      primaryType: "dj",
      city: String(profile.city || ""),
    },
    stats: {
      events: Number(profile.eventCount || events.length || 0),
      relationships: Number(profile.collaboratorCount || collaborators.length || 0),
      venues: Number(profile.venueCount || venues.length || 0),
    },
    sections: {
      relatedDjs: {
        items: collaborators.map((row) => ({
          id: String(row.djId || row.displayName || row.label || ""),
          label: String(row.displayName || row.label || ""),
          relationshipScore: Number(row.sameEventCount || row.relationshipScore || 0),
          metrics: { sameEventCount: Number(row.sameEventCount || 0) },
        })).filter((row) => row.label),
      },
      clubs: {
        items: venues.map((row) => ({
          id: String(row.venueId || row.venueName || row.label || ""),
          label: String(row.venueName || row.label || ""),
          city: String(row.city || ""),
          activityCount: Number(row.eventCount || row.activityCount || 0),
        })).filter((row) => row.label),
      },
      events: {
        items: events.map((event) => ({
          id: String(event.eventId || event.id || ""),
          title: String(event.title || ""),
          subtitle: String(eventSubtitle(event)),
          time: String(event.date || event.time || ""),
          venue: String(event.venueName || event.venue || ""),
          city: String(event.city || ""),
        })).filter((event) => event.title),
      },
    },
  };
}

async function fetchAtlasProfile(name, id) {
  // 优先用后端给的稳定 id 下钻（dj:/venue:/org:），避免按花名模糊搜对不上 → 假死胡同。
  const byId = String(id || "").includes(":");
  let primaryError = null;
  try {
    const primary = await requestApi("/api/v1/atlas/family/profile", byId ? { id } : { q: name });
    if (primary && primary.found !== false && primary.canonical) return primary;
  } catch (error) {
    primaryError = error;
    console.warn("[atlas] family profile unavailable, falling back to weekly dj profile", error);
  }
  try {
    const legacy = await requestApi(`/api/v1/weekly/atlas/dj-profile/${encodeURIComponent(name)}`, {
      eventLimit: 12,
      collaboratorLimit: 12,
      venueLimit: 8,
    });
    const converted = legacyDjProfileToFamilyProfile(legacy, name);
    if (converted) return converted;
    return {
      found: false,
      source: "weekly_atlas_dj_profile_fallback",
      query: name,
      primaryUnavailable: Boolean(primaryError),
    };
  } catch (fallbackError) {
    throw primaryError || fallbackError;
  }
}

// 两层极坐标环：强关系在内圈，弱关系在外圈，错开相位形成纵深星系感。
function layoutNeighbors(nodes) {
  const cx = 50;
  const cy = 44;
  const inner = nodes.slice(0, Math.min(6, nodes.length));
  const outer = nodes.slice(6);
  const place = (list, radius, phase) =>
    list.map((node, i) => {
      const angle = (i / (list.length || 1)) * Math.PI * 2 - Math.PI / 2 + phase;
      const x = round2(cx + radius * Math.cos(angle) * 0.9);
      const y = round2(cy + radius * Math.sin(angle));
      const dx = x - cx;
      const dy = y - cy;
      return {
        ...node,
        x,
        y,
        lineLength: round2(Math.sqrt(dx * dx + dy * dy)),
        lineAngle: round2((Math.atan2(dy, dx) * 180) / Math.PI),
        lineOpacity: round2(0.18 + node.weight * 0.5),
      };
    });
  return [...place(inner, 23, 0), ...place(outer, 38, Math.PI / (outer.length || 1))];
}

// 各类型内部各自归一化 weight，避免「厂牌 evidenceCount 几十」把「DJ 关系分个位数」压成小点。
function normWeights(list) {
  const max = list.reduce((m, n) => Math.max(m, n.rawScore), 0);
  list.forEach((node, i) => {
    node.weight = max > 0 ? round2(node.rawScore / max) : round2(1 - i / (list.length || 1));
  });
  return list;
}

// 把同台 DJ + 常驻俱乐部 + 主办/厂牌合成邻居星；weight 决定星的大小/亮度，meta 带关系语义。
function buildNeighbors(profile, t) {
  const djs = normWeights(sectionItems(profile, "relatedDjs")
    .slice(0, 8)
    .map((it) => ({
      id: String(it.id || it.label || ""),
      label: String(it.label || ""),
      kind: "dj",
      rawScore: Number(it.relationshipScore || (it.metrics && it.metrics.sameEventCount) || 0),
      meta: relationMeta(it.metrics, t) || (it.relationshipScore ? `${t.scoreLabel} ${it.relationshipScore}` : ""),
    }))
    .filter((n) => n.label));
  const venues = normWeights(sectionItems(profile, "clubs")
    .slice(0, 5)
    .map((it) => ({
      id: String(it.id || it.label || ""),
      label: String(it.label || ""),
      kind: "venue",
      rawScore: Number(it.activityCount || it.relationshipScore || 0),
      meta: it.city || (it.activityCount ? `${it.activityCount} ${t.setsUnit}` : ""),
    }))
    .filter((n) => n.label));
  // 主办/厂牌（A）：API 早就返回 organizations，过去前端丢弃了 —— 这是 0 节点的主要补丁。
  const orgs = normWeights(sectionItems(profile, "organizations")
    .slice(0, 4)
    .map((it) => ({
      id: String(it.id || it.label || ""),
      label: String(it.label || ""),
      kind: "org",
      rawScore: Number(it.relationshipScore || it.evidenceCount || it.activityCount || 0),
      meta: t.orgUnit,
    }))
    .filter((n) => n.label));
  const all = [...djs, ...orgs, ...venues];
  all.sort((a, b) => b.weight - a.weight);
  const top = all.slice(0, 12).map((node) => ({
    ...node,
    tier: tierOf(node.weight),
    dotSize: Math.round(16 + node.weight * 24),
  }));
  return layoutNeighbors(top);
}

Page({
  data: {
    lang: "zh",
    t: LABELS.zh,
    loading: false,
    error: "",
    seedList: [],
    center: null,
    nodes: [],
    events: [],
    history: [],
    trail: [],
    visitedCount: 0,
    footprint: null,
    footprintLoading: false,
  },

  onLoad() {
    enableShareMenu();
    const lang = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("saved", lang);
    this.seedDetailMap = {};
    this.visited = new Set(this.loadVisited());
    this._graphLoadSeq = 0;
    this._seedColdStartSeq = 0;
    this._seedLoadPromise = null;
    this.setData({ lang, t: LABELS[lang] || LABELS.zh, visitedCount: this.visited.size });
    this.loadSeeds();
  },

  onShow() {
    const lang = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("saved", lang);
    if (lang !== this.data.lang) this.setData({ lang, t: LABELS[lang] || LABELS.zh });
    if (!this.data.center && !this.data.loading) this.loadSeeds();
  },

  onTabItemTap() {
    vibrateLight();
  },

  openStarmap() {
    wx.navigateTo({ url: "/pages/atlas-starmap/atlas-starmap" });
  },

  openAtlasSearch() {
    wx.navigateTo({ url: "/pages/atlas-search/atlas-search" });
  },

  onPullDownRefresh() {
    this._graphLoadSeq = (this._graphLoadSeq || 0) + 1;
    this.setData({ history: [], trail: [], center: null, error: "" });
    this.loadSeeds().then(
      () => wx.stopPullDownRefresh(),
      () => wx.stopPullDownRefresh()
    );
  },

  onShareAppMessage() {
    const fp = this.data.footprint;
    const title = fp && fp.djCount
      ? (this.data.lang === "en"
          ? `My HUAIDJ footprint: ${fp.djCount} DJs across ${fp.cityCount} cities`
          : `我的坏DJ足迹：${fp.djCount} 位 DJ · ${fp.cityCount} 座城市`)
      : (this.data.lang === "en" ? "HUAIDJ Atlas" : "坏DJclub ATLAS 星图");
    return buildSimpleShare(title, "/pages/saved/saved", { lang: this.data.lang });
  },

  onShareTimeline() {
    return buildSimpleTimeline(this.data.lang === "en" ? "HUAIDJ Atlas" : "坏DJclub ATLAS 星图", { lang: this.data.lang });
  },

  // "我的足迹" — aggregate the DJs the user has lit up into a shareable footprint
  // card (DJ count, cities, co-bill density). Anonymous, on-device: reuses the
  // existing /atlas/artist DTO (capped at the 24 most recent), no backend. Plan 101 #8.
  async buildMyFootprint() {
    const names = Array.from(this.visited || []).slice(-24);
    if (!names.length) {
      wx.showToast({ title: this.data.t.footprintEmpty, icon: "none" });
      return;
    }
    if (this.data.footprintLoading) return;
    this.setData({ footprintLoading: true });
    const results = await Promise.all(names.map((name) =>
      requestApi("/api/v1/weekly/atlas/artist", { name, eventLimit: 60, collaboratorLimit: 20 })
        .then((r) => (r && r.found && r.profile) ? {
          name: r.profile.displayName || name,
          city: r.profile.city || "",
          events: Array.isArray(r.events) ? r.events : [],
          peers: []
            .concat((r.collaborators || []).map((c) => c.displayName))
            .concat((r.profile.similarDjs || []).map((s) => s.displayName))
            .filter(Boolean),
        } : null)
        .catch(() => null)
    ));
    const footprint = buildFootprintCard(results.filter(Boolean), 6);
    this.setData({ footprint, footprintLoading: false });
    vibrateLight();
  },

  loadVisited() {
    try {
      const raw = wx.getStorageSync(VISITED_KEY);
      return Array.isArray(raw) ? raw : [];
    } catch (error) {
      return [];
    }
  },

  // 点亮一颗星：返回是否是新发现，用于轻收集玩法。
  markVisited(label) {
    const name = String(label || "").trim();
    if (!name || this.visited.has(name)) return false;
    this.visited.add(name);
    try {
      wx.setStorageSync(VISITED_KEY, Array.from(this.visited).slice(-300));
    } catch (error) {
      // storage 满了也不阻断探索
    }
    return true;
  },

  async loadFirstAvailableGraph(seedList, coldStartSeq) {
    const names = [];
    const seen = {};
    for (const seed of seedList || []) {
      const name = String(seed && seed.name || "").trim();
      if (!name || seen[name]) continue;
      seen[name] = true;
      names.push(name);
      if (names.length >= MAX_SEED_PROFILE_ATTEMPTS) break;
    }
    if (!seen[DEFAULT_ATLAS_ENTRY]) names.push(DEFAULT_ATLAS_ENTRY);
    let best = null; // 见过最稠密的入口 {name, count}，全稀疏时兜底用
    for (const name of names) {
      if (coldStartSeq !== this._seedColdStartSeq) return false;
      const ok = await this.loadGraph(name, {
        reset: true,
        silentNotFound: true,
        coldStartSeq,
      });
      if (coldStartSeq !== this._seedColdStartSeq) return false;
      if (!ok) continue;
      const count = (this.data.nodes || []).length;
      if (count >= MIN_SEED_NEIGHBORS) return true; // 够热闹，从稠密处进入
      if (!best || count > best.count) best = { name, count };
    }
    // 所有种子都偏稀疏：退回目前最稠密那颗（ponytail: 仅当全稀疏时多一次 load）。
    if (best && coldStartSeq === this._seedColdStartSeq) {
      return this.loadGraph(best.name, { reset: true, coldStartSeq });
    }
    if (coldStartSeq !== this._seedColdStartSeq) return false;
    this.setData({ loading: false, error: this.data.t.empty });
    return false;
  },

  // 用本周活动包里的 DJ 名字作为图谱探索入口。
  loadSeeds() {
    if (this._seedLoadPromise) return this._seedLoadPromise;
    const shouldColdStart = !this.data.center;
    const coldStartSeq = shouldColdStart
      ? (this._seedColdStartSeq || 0) + 1
      : this._seedColdStartSeq;
    if (shouldColdStart) this._seedColdStartSeq = coldStartSeq;
    const request = (async () => {
      try {
        const currentItems = await fetchAllCurrentItems({ scope: "current", limit: 100 });
        const seen = {};
        const seedList = [];
        for (const item of currentItems.map(compactItem)) {
          const detailId = String(item.id || "");
          const atlasArtists = item.atlasArtistItems || item.atlas_artists || [];
          const lineup = item.lineupItems || item.lineup_artists || [];
          const candidates = []
            .concat(Array.isArray(atlasArtists) ? atlasArtists : atlasArtists ? [atlasArtists] : [])
            .concat(Array.isArray(lineup) ? lineup : lineup ? [lineup] : []);
          for (const candidate of candidates) {
            addSeed(seedList, seen, candidate, detailId, this.visited);
            if (seedList.length >= 12) break;
          }
          if (seedList.length >= 12) break;
        }
        this.seedDetailMap = {};
        for (const seed of seedList) this.seedDetailMap[seed.name] = seed.detailId;
        this.setData({ seedList });
        if (shouldColdStart && !this.data.center && coldStartSeq === this._seedColdStartSeq) {
          await this.loadFirstAvailableGraph(seedList, coldStartSeq);
        }
      } catch (error) {
        console.error("[atlas] loadSeeds failed", error);
        if (shouldColdStart && !this.data.center && coldStartSeq === this._seedColdStartSeq) {
          await this.loadGraph(DEFAULT_ATLAS_ENTRY, { reset: true, coldStartSeq });
        }
      }
    })();
    this._seedLoadPromise = request;
    return request.finally(() => {
      if (this._seedLoadPromise === request) this._seedLoadPromise = null;
    });
  },

  async loadGraph(query, options = {}) {
    const name = String(query || "").trim();
    if (!name) return false;
    const {
      push = false,
      reset = false,
      setHistory = null,
      silentNotFound = false,
      id = "",
      coldStartSeq = null,
    } = options;
    if (coldStartSeq === null) {
      // An explicit navigation owns the screen and cancels any seed-probing
      // cold start that is still walking fallback candidates.
      this._seedColdStartSeq = (this._seedColdStartSeq || 0) + 1;
    } else if (coldStartSeq !== this._seedColdStartSeq) {
      return false;
    }
    this._graphLoadSeq = (this._graphLoadSeq || 0) + 1;
    const graphLoadSeq = this._graphLoadSeq;
    const isCurrentLoad = () => graphLoadSeq === this._graphLoadSeq
      && (coldStartSeq === null || coldStartSeq === this._seedColdStartSeq);
    this.setData({ loading: true, error: "" });
    try {
      const profile = await fetchAtlasProfile(name, id);
      if (!isCurrentLoad()) return false;
      if (!profile || profile.found === false || !profile.canonical) {
        // 已有星图时不要清空，只提示；冷启动（无 center）才落整屏空态。
        if (this.data.center && !silentNotFound) {
          this.setData({ loading: false });
          wx.showToast({ title: this.data.t.empty, icon: "none" });
        } else {
          this.setData({ loading: false, error: silentNotFound ? "" : this.data.t.empty });
        }
        return false;
      }
      const t = this.data.t;
      const canonical = profile.canonical;
      const stats = profile.stats || {};
      const center = {
        label: canonical.name,
        kind: atlasKind(canonical.primaryType || canonical.type),
        city: canonical.city || "",
        detailId: (this.seedDetailMap && this.seedDetailMap[canonical.name]) || "",
        statsLine: `${stats.events || 0} ${t.statsEvents} · ${stats.relationships || 0} ${t.statsRel} · ${stats.venues || 0} ${t.statsVenues}`,
      };
      const nodes = buildNeighbors(profile, t).map((node) => ({ ...node, visited: this.visited.has(node.label) }));
      const events = sectionItems(profile, "events")
        .slice(0, 5)
        .map((event) => ({
          title: String(event.title || ""),
          subtitle: String(event.subtitle || [event.time, event.venue, event.city].filter(Boolean).join(" · ")),
        }))
        .filter((event) => event.title);

      let history = this.data.history.slice();
      if (reset) history = [];
      else if (Array.isArray(setHistory)) history = setHistory;
      else if (push && this.data.center) history.push(this.data.center.label);

      const isNew = this.markVisited(center.label);
      const trail = [...history, center.label].map((label, index, arr) => ({
        label,
        index,
        current: index === arr.length - 1,
      }));
      // markVisited 可能点亮了与 center 同名的 seed，顺手刷新 seed 标记，省掉一次额外 setData。
      const seedList = this.data.seedList.map((seed) => ({ ...seed, visited: this.visited.has(seed.name) }));

      this.setData({
        loading: false,
        error: "",
        center,
        nodes,
        events,
        history,
        trail,
        seedList,
        visitedCount: this.visited.size,
      });
      if (isNew && !reset) {
        wx.showToast({ title: t.newStar, icon: "none", duration: 1200 });
      }
      vibrateLight();
      return true;
    } catch (error) {
      if (!isCurrentLoad()) return false;
      console.error("[atlas] loadGraph failed", error);
      if (this.data.center) {
        this.setData({ loading: false });
        wx.showToast({ title: this.data.t.error, icon: "none" });
      } else {
        this.setData({ loading: false, error: this.data.t.error });
      }
      return false;
    }
  },

  selectSeed(event) {
    const name = event.currentTarget.dataset.name || "";
    if (name) this.loadGraph(name, { reset: true });
  },

  exploreNode(event) {
    const { name = "", id = "" } = event.currentTarget.dataset;
    if (!name || (this.data.center && name === this.data.center.label)) return;
    this.loadGraph(name, { push: true, id });
  },

  // 随机跳一颗强邻居（E）：按 weight 加权随机，鼓励一直往热闹处探索下去。
  exploreRandom() {
    const nodes = this.data.nodes || [];
    if (!nodes.length) return;
    const total = nodes.reduce((sum, n) => sum + (n.weight || 0.1), 0);
    let r = Math.random() * total;
    let pick = nodes[0];
    for (const n of nodes) {
      r -= n.weight || 0.1;
      if (r <= 0) { pick = n; break; }
    }
    this.loadGraph(pick.label, { push: true, id: pick.id });
  },

  // 顶部轨迹：点任意一跳回到那一层（当前层忽略）。
  jumpTo(event) {
    const index = Number(event.currentTarget.dataset.index);
    if (!(index >= 0)) return;
    if (index >= this.data.history.length) return; // 当前层
    const target = this.data.history[index];
    const setHistory = this.data.history.slice(0, index);
    this.loadGraph(target, { setHistory });
  },

  // 从图谱跳回该 DJ 本周的活动详情页（仅当 seed 提供了 detailId）。
  openDetail(event) {
    const id = event.currentTarget.dataset.id || "";
    if (!id) return;
    wx.navigateTo({ url: `/pages/detail/detail?id=${encodeURIComponent(id)}&lang=${this.data.lang}` });
  },
});
