/**
 * Atlas frontend field contract adapter.
 *
 * The atlas serving DB is being rebuilt by a new extraction pipeline. Until the
 * clean data lands, the OLD index ships fragmented entities: the same physical
 * venue appears under several venue_ids/name variants (Dada Beijing vs Dada Bar
 * Beijing; OIL / OIL CLUB / OIL油), and the same DJ identity under several djIds
 * (moon / Moon / MOON). That inflates venue/collaborator counts and fills the
 * chip lists with duplicates.
 *
 * These pure helpers normalise + merge those lists on the client so old data
 * renders cleanly, and stay correct (no-ops) once the new pipeline emits already
 * deduped data. Tolerant of both camelCase API fields and short index keys.
 *
 * ponytail: pure functions, no deps. Runnable check: tests/atlas-contract.test.cjs
 */

function text(v) {
  return String(v == null ? "" : v).trim();
}

const PUNCT = /[\s·・|｜@＠:：,，.。、_/\\()（）\[\]【】-]/g;

// Normalise a venue name so name variants of the same physical venue collapse.
function normalizeVenueKey(value) {
  return text(value)
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/(club|俱乐部|bar|酒吧|livehouse|live house|studio|space|空间)/g, "")
    .replace(PUNCT, "");
}

// Normalise a DJ/artist display name so identity variants (moon/Moon/MOON) collapse.
function normalizeArtistKey(value) {
  return text(value)
    .toLowerCase()
    .replace(/^dj\s+/i, "")
    .replace(PUNCT, "");
}

// Of several name variants for one merged entity, pick the most authoritative:
// highest event count wins, tie-broken by the shorter (cleaner) label.
function pickCanonicalName(variants) {
  const best = variants
    .slice()
    .sort((a, b) => (b.count - a.count) || (text(a.name).length - text(b.name).length))[0];
  return best ? best.name : "";
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

// Merge venue rows by normalised name. Accepts API ({venueName,eventCount,venueId})
// or raw index ({vn,ec,vi}). Returns {venueName,eventCount,venueId} sorted desc.
function mergeVenues(venues) {
  const groups = new Map();
  for (const v of Array.isArray(venues) ? venues : []) {
    const name = text(v.venueName || v.vn || v.name);
    if (!name) continue;
    const key = normalizeVenueKey(name) || name.toLowerCase();
    const count = num(v.eventCount != null ? v.eventCount : v.ec);
    const group = groups.get(key) || { variants: [], eventCount: 0, venueId: text(v.venueId || v.vi) };
    group.variants.push({ name, count });
    group.eventCount += count;
    if (!group.venueId) group.venueId = text(v.venueId || v.vi);
    groups.set(key, group);
  }
  return [...groups.values()]
    .map((g) => ({ venueName: pickCanonicalName(g.variants), eventCount: g.eventCount, venueId: g.venueId }))
    .sort((a, b) => b.eventCount - a.eventCount);
}

// Merge collaborator/DJ rows by normalised identity. countField is preserved on
// output so the same helper serves both "常合作 DJ" (sameEventCount) and
// "经常来的 DJ" (eventCount) without touching the WXML.
function mergeByIdentity(list, countField) {
  const groups = new Map();
  for (const c of Array.isArray(list) ? list : []) {
    const name = text(c.displayName || c.n || c.name);
    if (!name) continue;
    const key = normalizeArtistKey(name) || name.toLowerCase();
    const count = num(c[countField] != null ? c[countField] : (c.sameEventCount != null ? c.sameEventCount : c.eventCount != null ? c.eventCount : c.ec));
    const group = groups.get(key) || { variants: [], count: 0, djId: text(c.djId || c.di) };
    group.variants.push({ name, count });
    group.count += count;
    if (!group.djId) group.djId = text(c.djId || c.di);
    groups.set(key, group);
  }
  return [...groups.values()]
    .map((g) => ({ displayName: pickCanonicalName(g.variants), djId: g.djId, [countField]: g.count }))
    .sort((a, b) => b[countField] - a[countField]);
}

function mergeCollaborators(list) {
  return mergeByIdentity(list, "sameEventCount");
}

function mergeResidentDjs(list) {
  return mergeByIdentity(list, "eventCount");
}

// Extract a yyyy-mm-dd start date from whatever date shape an event carries.
function eventStartISO(item) {
  const candidates = [item && item.eventDateStart, item && item.event_date_start, item && item.date, item && item.starts_at, item && item.dateLabel];
  for (const c of candidates) {
    const m = String(c == null ? "" : c).match(/\d{4}-\d{2}-\d{2}/);
    if (m) return m[0];
  }
  return "";
}

function todayISO() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

// Split events into upcoming (today..+2y) and past. Undated and absurd-future
// rows (e.g. the old DB's "2046" garbage dates) fall into past so they never
// masquerade as upcoming. Upcoming sorted soonest-first, past most-recent-first.
// ponytail: 2-year horizon caps garbage dates; widen if real far-future events appear.
function partitionEventsByDate(events, options = {}) {
  const today = options.todayISO || todayISO();
  const horizon = new Date();
  horizon.setFullYear(horizon.getFullYear() + 2);
  const maxFuture = options.maxFutureISO || horizon.toISOString().slice(0, 10);
  const upcoming = [];
  const past = [];
  for (const e of Array.isArray(events) ? events : []) {
    const start = eventStartISO(e);
    if (start && start >= today && start <= maxFuture) upcoming.push(e);
    else past.push(e);
  }
  upcoming.sort((a, b) => (eventStartISO(a) < eventStartISO(b) ? -1 : eventStartISO(a) > eventStartISO(b) ? 1 : 0));
  past.sort((a, b) => (eventStartISO(a) > eventStartISO(b) ? -1 : eventStartISO(a) < eventStartISO(b) ? 1 : 0));
  return { upcoming, past };
}

module.exports = {
  normalizeVenueKey,
  normalizeArtistKey,
  mergeVenues,
  mergeCollaborators,
  mergeResidentDjs,
  eventStartISO,
  todayISO,
  partitionEventsByDate,
};
