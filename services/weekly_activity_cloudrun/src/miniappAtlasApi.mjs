/**
 * Mini-program Atlas API — in-memory JSON-backed queries.
 * Reads atlas_index.json.gz at startup, no native modules needed.
 */
import { readFile } from "node:fs/promises";
import { gunzipSync } from "node:zlib";
import path from "node:path";
import { fileURLToPath } from "node:url";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));

let _index = null;
let _indexLoading = null;  // Promise singleton to prevent concurrent loads

async function loadIndex() {
  if (_index) return _index;
  if (_indexLoading) return _indexLoading;
  
  const indexPath = process.env.ATLAS_MINIAPP_INDEX
    || path.resolve(moduleDir, "../data/atlas_index.json.gz");
  
  _indexLoading = (async () => {
    const start = Date.now();
    try {
      const buf = await readFile(indexPath);
      // Use async gunzip via zlib to avoid blocking event loop
      const { gunzip } = await import("node:zlib");
      const json = await new Promise((resolve, reject) => {
        gunzip(buf, (err, result) => {
          if (err) reject(err);
          else resolve(result.toString("utf-8"));
        });
      });
      _index = JSON.parse(json);
      console.log(`[atlas-miniapp] Index loaded in ${Date.now() - start}ms (${(_index?.subjects?.length || 0)} subjects)`);
      return _index;
    } catch (err) {
      console.warn("[atlas-miniapp] Index not available:", err.message);
      _index = null;  // Reset so next call retries
      return null;
    } finally {
      _indexLoading = null;
    }
  })();
  
  return _indexLoading;
}

function text(v) { return String(v ?? "").trim(); }
function normKey(s) { return text(s).toLowerCase().replace(/[^a-z0-9一-鿿]/g, ""); }

function buildRuntimeIndexes(idx) {
  if (!idx || idx._subjectById) return idx;
  idx._subjectById = new Map();
  idx._subjectsByNormName = new Map();
  for (const subject of Array.isArray(idx.subjects) ? idx.subjects : []) {
    if (!subject?.i) continue;
    idx._subjectById.set(subject.i, subject);
    const keys = [subject.nn, normKey(subject.n), ...(Array.isArray(subject.a) ? subject.a.map(normKey) : [])]
      .filter(Boolean);
    for (const key of keys) {
      const bucket = idx._subjectsByNormName.get(key) || [];
      bucket.push(subject);
      idx._subjectsByNormName.set(key, bucket);
    }
  }
  return idx;
}

function subjectById(idx, id) {
  buildRuntimeIndexes(idx);
  return idx?._subjectById?.get(id) || null;
}

function searchSubjects(idx, name, typeFilter) {
  const query = text(name);
  if (!query || !idx) return [];
  const qk = normKey(query);
  buildRuntimeIndexes(idx);
  const exactBucket = idx._subjectsByNormName?.get(qk) || [];
  const exactMatches = typeFilter ? exactBucket.filter(s => s.t === typeFilter) : exactBucket;
  if (exactMatches.length) return exactMatches.slice(0, 10);
  const results = [];
  // Exact match
  for (const s of idx.subjects) {
    if (typeFilter && s.t !== typeFilter) continue;
    if (s.nn === qk) { results.push(s); break; }
  }
  if (results.length) return results;
  // Prefix match
  for (const s of idx.subjects) {
    if (typeFilter && s.t !== typeFilter) continue;
    if (s.nn.startsWith(qk) || s.n.toLowerCase().startsWith(query.toLowerCase())) {
      results.push(s); if (results.length >= 5) break;
    }
  }
  if (results.length) return results;
  // Contains match
  for (const s of idx.subjects) {
    if (typeFilter && s.t !== typeFilter) continue;
    if (s.nn.includes(qk) || s.n.toLowerCase().includes(query.toLowerCase())) {
      results.push(s); if (results.length >= 10) break;
    }
  }
  return results;
}

function preloadIndex() {
  const preload = String(process.env.ATLAS_MINIAPP_PRELOAD || "1").trim() !== "0";
  if (!preload) return;
  setTimeout(() => {
    loadIndex()
      .then((idx) => {
        if (idx) buildRuntimeIndexes(idx);
      })
      .catch((err) => {
        console.warn("[atlas-miniapp] preload failed:", err.message);
      });
  }, 0);
}

preloadIndex();

function resolveDJName(idx, djId) {
  const p = idx.profiles[djId];
  if (p) return p.n;
  const s = subjectById(idx, djId);
  return s ? s.n : djId;
}

function sourceRef(idx, sourceRefId) {
  const id = text(sourceRefId);
  if (!id) return null;
  const row = idx.source_refs?.[id] || {};
  return {
    sourceRefId: id,
    sourceHash: text(row.h),
    sourceAccountName: text(row.a),
    sourceTitle: text(row.t),
    sourcePublishedAt: text(row.p),
    sourceKind: text(row.k),
  };
}

function publicSourceFields(idx, sourceRefId) {
  const source = sourceRef(idx, sourceRefId);
  if (!source) return {};
  return {
    sourceRefId: source.sourceRefId,
    sourceHash: source.sourceHash,
    sourceTitle: source.sourceTitle,
    sourceAccountName: source.sourceAccountName,
    sourcePublishedAt: source.sourcePublishedAt,
    sourceKind: source.sourceKind,
  };
}

export async function getArtist({ name, eventLimit, collaboratorLimit, venueLimit } = {}) {
  const idx = await loadIndex();
  if (!idx) return { found: false, query: name, reason: "index_unavailable" };

  const artistName = text(name);
  if (!artistName) return { found: false, query: "", reason: "missing_name" };

  const subjects = searchSubjects(idx, artistName, "dj");
  if (!subjects.length) return {
    schemaVersion: "atlas_miniapp.artist_response.v1",
    query: artistName, found: false, reason: "not_found",
    profile: null, events: [], collaborators: [], venues: [],
  };

  const s = subjects[0];
  const djId = s.i;
  const p = idx.profiles[djId] || {};
  const profile = {
    djId, displayName: s.n, aliases: s.a, city: s.c || null,
    eventCount: s.ec, venueCount: p.vc || 0, collaboratorCount: p.cc || 0,
    firstSeenAt: p.fs || null, lastSeenAt: p.ls || null,
    bio: p.b || null, bioSource: p.bs || null,
  };

  const evts = (idx.events[djId] || []).slice(0, parseInt(eventLimit) || 50);
  const vens = (idx.dj_venues[djId] || []).slice(0, parseInt(venueLimit) || 10);
  const cols = (idx.collabs[djId] || []).slice(0, parseInt(collaboratorLimit) || 15);

  return {
    schemaVersion: "atlas_miniapp.artist_response.v1",
    query: artistName, found: true, profile,
    events: evts.map(e => ({ eventId: e.eid, title: e.t, date: e.d || null, venueName: e.v || null, city: e.ci || null, ...publicSourceFields(idx, e.sr) })),
    venues: vens.map(v => ({ venueName: v.vn, eventCount: v.ec })),
    collaborators: cols.map(c => ({ djId: c.di, displayName: c.n, sameEventCount: c.ec })),
    alternatives: subjects.slice(1, 4).map(s => ({ subjectId: s.i, displayName: s.n })),
  };
}

export async function getVenue({ name, eventLimit } = {}) {
  const idx = await loadIndex();
  if (!idx) return { found: false, query: name, reason: "index_unavailable" };

  const venueName = text(name);
  if (!venueName) return { found: false, query: "", reason: "missing_name" };

  // Search for venue or organizer
  let subjects = searchSubjects(idx, venueName, "venue");
  if (!subjects.length) subjects = searchSubjects(idx, venueName, "organizer");
  if (!subjects.length) return {
    schemaVersion: "atlas_miniapp.venue_response.v1",
    query: venueName, found: false, reason: "not_found",
    profile: null, events: [], residentDJs: [],
  };

  const s = subjects[0];
  const maxEvents = parseInt(eventLimit) || 60;

  // Get venue events from matching venue IDs — only same-city to avoid cross-club mixing
  const primaryCity = (s.c || "").toLowerCase();
  let vevents = [...(idx.venue_events[s.i] || [])];
  // Also try name-based lookup: only include IDs in same city
  const nameIds = idx.venue_by_name[normKey(venueName)] || [];
  for (const vid of nameIds) {
    if (vid === s.i) continue;
    const vsubj = subjectById(idx, vid);
    const vcity = (vsubj?.c || "").toLowerCase();
    // Only merge if same city (or either has no city)
    if (vcity && primaryCity && vcity !== primaryCity) continue;
    if (idx.venue_events[vid]) {
      vevents = [...vevents, ...idx.venue_events[vid]];
    }
  }
  // Dedupe
  const seen = new Set();
  vevents = vevents.filter(e => { const k = e.eid; if (seen.has(k)) return false; seen.add(k); return true; });

  // Resident DJs are a historical rollup, so do not derive them from the
  // eventLimit-truncated list used for display.
  const djCount = {};
  for (const e of vevents) {
    if (e.di) djCount[e.di] = (djCount[e.di] || 0) + 1;
  }
  const residentDJs = Object.entries(djCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([djId, count]) => ({ djId, displayName: resolveDJName(idx, djId), eventCount: count }));
  const displayEvents = vevents.slice(0, maxEvents);

  return {
    schemaVersion: "atlas_miniapp.venue_response.v1",
    query: venueName, found: true,
    profile: { subjectId: s.i, displayName: s.n, subjectType: s.t, aliases: s.a, city: s.c, eventCount: s.ec },
    events: displayEvents.map(e => ({ eventId: e.eid, title: e.t, date: e.d || null, djId: e.di, djName: resolveDJName(idx, e.di), city: e.ci || null, ...publicSourceFields(idx, e.sr) })),
    residentDJs,
  };
}

export async function getEntity(id) {
  const idx = await loadIndex();
  if (!idx) return { found: false, id, reason: "index_unavailable" };
  const s = subjectById(idx, text(id));
  if (!s) return { found: false, id, reason: "not_found" };
  return { schemaVersion: "atlas_miniapp.entity_response.v1", found: true, entity: s };
}

export async function getSourceEvidence(id) {
  const idx = await loadIndex();
  if (!idx) return null;
  const source = sourceRef(idx, id);
  if (!source) return null;
  return {
    schemaVersion: "atlas.evidence.v1",
    sourceRefId: source.sourceRefId,
    sourceAccount: source.sourceAccountName,
    sourceTitle: source.sourceTitle,
    postDate: source.sourcePublishedAt,
    publicSnippet: "",
    sourceKind: source.sourceKind || "atlas_miniapp_source_ref",
    publicUrl: {
      status: "not_public",
      reason: "atlas_miniapp_source_ref_only",
    },
    supportFields: {},
    safety: {
      rawLocalPathExposed: false,
      rawSourceUrlExposed: false,
      sourceHashExposed: false,
      reportOnly: true,
    },
  };
}

// ── Cross-DB Merge Map (DB2 eid → DB3 entity_id) ──
let _mergeMap = null;
let _mergeMapLoading = null;

async function loadMergeMap() {
  if (_mergeMap) return _mergeMap;
  if (_mergeMapLoading) return _mergeMapLoading;

  const mergeMapPath = process.env.CROSS_DB_MERGE_MAP
    || path.resolve(moduleDir, "../data/current_release/cross_db_merge_map.json");

  _mergeMapLoading = (async () => {
    const start = Date.now();
    try {
      const buf = await readFile(mergeMapPath);
      const raw = JSON.parse(buf.toString("utf-8"));
      _mergeMap = {
        db2ToDb3: raw.db2_to_db3_map || {},
        subjectRemap: raw.existing_subject_map || {},
        stats: {
          db2Mappings: Object.keys(raw.db2_to_db3_map || {}).length,
          subjectRemaps: Object.keys(raw.existing_subject_map || {}).length,
          loadedAt: new Date().toISOString(),
        },
      };
      console.log(`[atlas-miniapp] Cross-DB merge_map loaded in ${Date.now() - start}ms (db2→db3: ${_mergeMap.stats.db2Mappings}, subject_remap: ${_mergeMap.stats.subjectRemaps})`);
      return _mergeMap;
    } catch (err) {
      console.warn("[atlas-miniapp] Cross-DB merge_map not available:", err.message);
      _mergeMap = { db2ToDb3: {}, subjectRemap: {}, stats: null };
      return _mergeMap;
    } finally {
      _mergeMapLoading = null;
    }
  })();

  return _mergeMapLoading;
}

// Preload merge_map alongside main index
setTimeout(() => { loadMergeMap().catch(() => {}); }, 100);

/**
 * Resolve a DB2 eid to its DB3 counterpart via the merge_map.
 * Returns { resolved: true, db3Id, canonicalId, entity? } or { resolved: false, eid }.
 */
export async function resolveCrossDbEntity(eid) {
  const [idx, mm] = await Promise.all([loadIndex(), loadMergeMap()]);
  const id = text(eid);
  if (!id) return { resolved: false, eid: id, reason: "missing_eid" };

  const db3Id = mm.db2ToDb3[id];
  if (!db3Id) return { resolved: false, eid: id, reason: "no_mapping" };

  const canonicalId = mm.subjectRemap[db3Id] || db3Id;
  const entity = subjectById(idx, canonicalId);

  return {
    resolved: true,
    eid: id,
    db3Id,
    canonicalId,
    entity: entity ? {
      subjectId: entity.i,
      displayName: entity.n,
      subjectType: entity.t,
      city: entity.c || null,
      aliases: entity.a || [],
    } : null,
  };
}

/**
 * Get merge_map stats for health/monitoring.
 */

// ── Direct DJ ID lookup (by subject ID, not name search) ──
export async function getArtistById(djId, { eventLimit, collaboratorLimit, venueLimit } = {}) {
  const idx = await loadIndex();
  if (!idx) return { found: false, query: djId, reason: "index_unavailable" };

  const id = text(djId);
  if (!id) return { found: false, query: "", reason: "missing_id" };

  const s = subjectById(idx, id);
  if (!s || s.t !== "dj") return {
    schemaVersion: "atlas_miniapp.artist_response.v1",
    query: id, found: false, reason: "not_found",
    profile: null, events: [], collaborators: [], venues: [],
  };

  const p = idx.profiles[id] || {};
  const profile = {
    djId: id, displayName: s.n, aliases: s.a, city: s.c || null,
    eventCount: s.ec, venueCount: p.vc || 0, collaboratorCount: p.cc || 0,
    firstSeenAt: p.fs || null, lastSeenAt: p.ls || null,
    bio: p.b || null, bioSource: p.bs || null,
  };

  const maxEvents = parseInt(eventLimit) || 50;
  const maxVenues = parseInt(venueLimit) || 10;
  const maxCollabs = parseInt(collaboratorLimit) || 15;

  const evts = (idx.events[id] || []).slice(0, maxEvents);
  const vens = (idx.dj_venues[id] || []).slice(0, maxVenues);
  const cols = (idx.collabs[id] || []).slice(0, maxCollabs);

  return {
    schemaVersion: "atlas_miniapp.artist_response.v1",
    query: id, found: true, profile,
    events: evts.map(e => ({ eventId: e.eid, title: e.t, date: e.d || null, venueName: e.v || null, city: e.ci || null, ...publicSourceFields(idx, e.sr) })),
    venues: vens.map(v => ({ venueName: v.vn, eventCount: v.ec })),
    collaborators: cols.map(c => ({ djId: c.di, displayName: c.n, sameEventCount: c.ec })),
    alternatives: [],
  };
}

export async function getMergeMapStats() {
  const mm = await loadMergeMap();
  return {
    schemaVersion: "atlas_miniapp.cross_db_merge_map_stats.v1",
    available: mm.stats !== null,
    stats: mm.stats,
  };
}
