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
let _starmapLenses = null;
let _starmapLensesLoading = null;
let _relationTrajectoryArtifact = undefined;
let _relationTrajectoryArtifactLoading = null;
let _radioExternalLinks = null;
let _radioExternalLinksLoading = null;
let _radioPrograms = null;
let _radioProgramsLoading = null;
let _radioProgramMatchReview = null;
let _radioProgramMatchReviewLoading = null;
let _neighborhood = null;
let _neighborhoodLoading = null;
let _djExternalLinksAccepted = null;
let _djExternalLinksAcceptedLoading = null;
let _bioCandidates = null;
let _bioCandidatesLoading = null;
let _bioSnippets = null;
let _bioSnippetsLoading = null;
let _sceneClusters = null;
let _sceneClustersLoading = null;

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

const ARTIST_LIST_PAGE_LIMITS = Object.freeze({
  events: Object.freeze({ defaultLimit: 50, hardLimit: 100 }),
  venues: Object.freeze({ defaultLimit: 10, hardLimit: 100 }),
  collaborators: Object.freeze({ defaultLimit: 15, hardLimit: 200 }),
});

function positivePageLimit(value, { defaultLimit, hardLimit }) {
  const parsed = Number(text(value));
  if (!Number.isFinite(parsed) || parsed <= 0) return defaultLimit;
  return Math.min(Math.floor(parsed), hardLimit);
}

function nonNegativePageOffset(value, total) {
  const parsed = Number(text(value));
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return Math.min(Math.floor(parsed), total);
}

function knownListTotal(value, availableTotal) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return availableTotal;
  return Math.max(availableTotal, Math.min(Math.floor(parsed), Number.MAX_SAFE_INTEGER));
}

function artistListPage(rows, requestedLimit, requestedOffset, policy, knownTotal) {
  const source = Array.isArray(rows) ? rows : [];
  const availableTotal = source.length;
  const total = knownListTotal(knownTotal, availableTotal);
  const limit = positivePageLimit(requestedLimit, policy);
  const offset = nonNegativePageOffset(requestedOffset, availableTotal);
  const items = source.slice(offset, offset + limit);
  const returned = items.length;
  const hasMore = offset + returned < availableTotal;
  const sourceTruncated = total > availableTotal;
  return {
    items,
    pagination: {
      offset,
      limit,
      hardLimit: policy.hardLimit,
      total,
      availableTotal,
      returned,
      truncated: offset > 0 || hasMore || sourceTruncated,
      sourceTruncated,
      hasMore,
      nextOffset: hasMore ? offset + returned : null,
    },
  };
}

function artifactDatasetId(artifact) {
  return text(artifact?.datasetId);
}

function atlasDatasetHandshake(idx, bundle) {
  const indexDatasetId = artifactDatasetId(idx);
  const neighborhoodDatasetId = artifactDatasetId(bundle);
  if (!indexDatasetId || !neighborhoodDatasetId) {
    return { ok: false, reason: "dataset_id_missing", indexDatasetId, neighborhoodDatasetId };
  }
  if (indexDatasetId !== neighborhoodDatasetId) {
    return { ok: false, reason: "dataset_mismatch", indexDatasetId, neighborhoodDatasetId };
  }
  return { ok: true, reason: "", indexDatasetId, neighborhoodDatasetId };
}

function publicAtlasGeneration(idx, bundle = null) {
  const result = {};
  const datasetId = artifactDatasetId(idx);
  if (datasetId) result.datasetId = datasetId;
  result.subjectCount = Array.isArray(idx?.subjects) ? idx.subjects.length : 0;
  result.profileCount = idx?.profiles && typeof idx.profiles === "object"
    ? Object.keys(idx.profiles).length
    : 0;

  if (bundle && atlasDatasetHandshake(idx, bundle).ok) {
    const generation = bundle.generation || {};
    const numericFields = ["nodeCount", "relationCount", "edgeCount", "perSubjectLimit"];
    for (const field of numericFields) {
      const value = Number(generation[field]);
      if (Number.isFinite(value) && value >= 0) result[field] = value;
    }
    const neighborhoodSubjectCount = Number(generation.subjectCount);
    if (Number.isFinite(neighborhoodSubjectCount) && neighborhoodSubjectCount >= 0) {
      result.neighborhoodSubjectCount = neighborhoodSubjectCount;
    }
  }
  return result;
}

async function loadAlignedNeighborhoodBundle(idx) {
  const bundle = await loadNeighborhoodBundle();
  const handshake = atlasDatasetHandshake(idx, bundle);
  if (!handshake.ok) return null;
  return bundle;
}

function usableSubjectKey(key) {
  const value = text(key);
  return /[一-鿿]/.test(value) ? value.length >= 2 : value.length >= 3;
}

function subjectNameKeys(subject) {
  return Array.from(new Set([
    text(subject?.nn),
    normKey(subject?.nn),
    normKey(subject?.n),
    ...(Array.isArray(subject?.a) ? subject.a.map(normKey) : []),
  ].filter(Boolean)));
}

function buildRuntimeIndexes(idx) {
  if (!idx || idx._subjectById) return idx;
  idx._subjectById = new Map();
  idx._subjectsByNormName = new Map();
  for (const subject of Array.isArray(idx.subjects) ? idx.subjects : []) {
    if (!subject?.i) continue;
    idx._subjectById.set(subject.i, subject);
    for (const key of subjectNameKeys(subject)) {
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

function subjectMatchesType(subject, typeFilter) {
  const type = text(typeFilter);
  if (!type) return true;
  if (type === "organizer") return subject?.t === "org" || subject?.t === "organizer";
  return subject?.t === type;
}

function subjectRank(idx, subject) {
  const profile = idx?.profiles?.[subject?.i] || {};
  const eventCount = Math.max(
    Number(subject?.ec) || 0,
    Number(profile?.ec) || 0,
    Number(profile?.eventCount) || 0,
  );
  return (profile && Object.keys(profile).length ? 1000000000 : 0) + eventCount;
}

function resolveSubjectReference(idx, value, { typeFilter } = {}) {
  const requestedId = text(value);
  if (!requestedId || !idx) return null;

  const colon = requestedId.indexOf(":");
  const prefix = colon > 0 ? requestedId.slice(0, colon) : "";
  const slug = colon > 0 ? requestedId.slice(colon + 1) : requestedId;
  const typedLegacySlug = colon > 0
    && ["dj", "venue", "org", "organizer", "series"].includes(prefix)
    && !/^[0-9a-f]{16}$/i.test(slug);
  const exact = subjectById(idx, requestedId);
  if (exact && subjectMatchesType(exact, typeFilter) && !typedLegacySlug) {
    return { subject: exact, requestedId, canonicalId: exact.i, resolvedVia: "exact" };
  }

  const effectiveType = text(typeFilter) || (["dj", "venue", "org", "organizer", "series"].includes(prefix) ? prefix : "");
  const key = normKey(slug);
  if (!usableSubjectKey(key)) {
    return exact && subjectMatchesType(exact, typeFilter)
      ? { subject: exact, requestedId, canonicalId: exact.i, resolvedVia: "exact" }
      : null;
  }

  buildRuntimeIndexes(idx);
  const candidates = (idx._subjectsByNormName?.get(key) || [])
    .filter((subject) => subjectMatchesType(subject, effectiveType))
    .filter((subject) => subjectNameKeys(subject).includes(key))
    .sort((a, b) => subjectRank(idx, b) - subjectRank(idx, a));

  const subject = candidates[0] || (exact && subjectMatchesType(exact, typeFilter) ? exact : null);
  if (!subject) return null;
  return {
    subject,
    requestedId,
    canonicalId: subject.i,
    resolvedVia: subject.i === requestedId ? "exact" : (colon > 0 ? "legacy_slug" : "name_key"),
  };
}

function uniqueTextValues(values) {
  const out = [];
  const seen = new Set();
  for (const value of Array.isArray(values) ? values : [values]) {
    const id = text(value);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

function omitUndefinedFields(value) {
  const out = {};
  for (const [key, item] of Object.entries(value || {})) {
    if (item !== undefined) out[key] = item;
  }
  return out;
}

function legacyTypeForSubject(subject) {
  const type = text(subject?.t);
  if (type === "organizer") return "org";
  return ["dj", "venue", "org", "series"].includes(type) ? type : "";
}

function subjectReferenceIds(idx, subjectOrId, { requestedId, typeFilter } = {}) {
  let subject = subjectOrId && typeof subjectOrId === "object" ? subjectOrId : null;
  const requested = text(requestedId ?? (subject ? "" : subjectOrId));
  if (!subject && requested && idx) {
    subject = resolveSubjectReference(idx, requested, { typeFilter })?.subject || null;
  }

  const ids = [];
  if (subject?.i) ids.push(subject.i);
  if (requested) ids.push(requested);

  const legacyType = legacyTypeForSubject(subject);
  if (subject && legacyType) {
    for (const key of subjectNameKeys(subject).map(normKey)) {
      if (usableSubjectKey(key)) ids.push(`${legacyType}:${key}`);
    }
  }
  return uniqueTextValues(ids);
}

function firstValueByIds(map, ids) {
  if (!map || typeof map !== "object") return null;
  for (const id of uniqueTextValues(ids)) {
    if (map[id]) return map[id];
  }
  return null;
}

function firstRowsForSubjectIds(bundle, ids) {
  if (!bundle?.byNode) return { id: "", rows: [] };
  for (const id of uniqueTextValues(ids)) {
    const rows = bundle.byNode[id];
    if (Array.isArray(rows) && rows.length) return { id, rows };
  }
  return { id: uniqueTextValues(ids)[0] || "", rows: [] };
}

function typeFromSubjectId(id) {
  const prefix = text(id).split(":")[0];
  return ["dj", "venue", "org", "organizer", "series"].includes(prefix) ? prefix : "entity";
}

function publicSubject(idx, id, extra = {}) {
  const subjectId = text(id);
  const subject = subjectById(idx, subjectId);
  return omitUndefinedFields({
    id: subjectId,
    type: subject?.t || typeFromSubjectId(subjectId),
    name: subject?.n || subjectId,
    city: subject?.c || null,
    aliases: Array.isArray(subject?.a) ? subject.a.slice(0, 4) : [],
    eventCount: Number(subject?.ec) || 0,
    ...extra,
  });
}

function publicSubjectResolved(idx, id, extra = {}) {
  const requestedId = text(id);
  const resolved = resolveSubjectReference(idx, requestedId);
  const canonicalId = resolved?.canonicalId || requestedId;
  const resolutionFields = resolved && requestedId && requestedId !== canonicalId
    ? { requestedSubjectId: requestedId, resolvedVia: resolved.resolvedVia }
    : {};
  return publicSubject(idx, canonicalId, { ...resolutionFields, ...extra });
}

function searchSubjects(idx, name, typeFilter, { includeRelatedMatches = false } = {}) {
  const query = text(name);
  if (!query || !idx) return [];
  const qk = normKey(query);
  buildRuntimeIndexes(idx);
  const exactBucket = idx._subjectsByNormName?.get(qk) || [];
  const exactMatches = typeFilter ? exactBucket.filter(s => s.t === typeFilter) : exactBucket;
  if (exactMatches.length && !includeRelatedMatches) return exactMatches.slice(0, 10);
  const results = [];
  const seen = new Set();
  for (const s of exactMatches) {
    if (seen.has(s.i)) continue;
    seen.add(s.i);
    results.push(s);
  }
  // Exact match
  for (const s of idx.subjects) {
    if (typeFilter && s.t !== typeFilter) continue;
    if (s.nn === qk && !seen.has(s.i)) {
      seen.add(s.i);
      results.push(s);
      if (!includeRelatedMatches) break;
    }
  }
  if (results.length && !includeRelatedMatches) return results;
  // Prefix match
  for (const s of idx.subjects) {
    if (typeFilter && s.t !== typeFilter) continue;
    if (s.nn.startsWith(qk) || s.n.toLowerCase().startsWith(query.toLowerCase())) {
      if (!seen.has(s.i)) {
        seen.add(s.i);
        results.push(s);
      }
      if (results.length >= 5) break;
    }
  }
  if (results.length && !includeRelatedMatches) return results;
  // Contains match
  for (const s of idx.subjects) {
    if (typeFilter && s.t !== typeFilter) continue;
    if (s.nn.includes(qk) || s.n.toLowerCase().includes(query.toLowerCase())) {
      if (!seen.has(s.i)) {
        seen.add(s.i);
        results.push(s);
      }
      if (results.length >= 10) break;
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

export function __resetMiniappAtlasApiCachesForTests() {
  _index = null;
  _indexLoading = null;
  _starmapLenses = null;
  _starmapLensesLoading = null;
  _relationTrajectoryArtifact = undefined;
  _relationTrajectoryArtifactLoading = null;
  _radioExternalLinks = null;
  _radioExternalLinksLoading = null;
  _radioPrograms = null;
  _radioProgramsLoading = null;
  _radioProgramMatchReview = null;
  _radioProgramMatchReviewLoading = null;
  _neighborhood = null;
  _neighborhoodLoading = null;
  _djExternalLinksAccepted = null;
  _djExternalLinksAcceptedLoading = null;
  _bioCandidates = null;
  _bioCandidatesLoading = null;
  _bioSnippets = null;
  _bioSnippetsLoading = null;
  _sceneClusters = null;
  _sceneClustersLoading = null;
}

async function readJsonArtifact(artifactPath) {
  const buf = await readFile(artifactPath);
  const raw = String(artifactPath).endsWith(".gz")
    ? gunzipSync(buf).toString("utf-8")
    : buf.toString("utf-8");
  return JSON.parse(raw);
}

async function readFirstJsonArtifact(paths) {
  let lastErr = null;
  for (const artifactPath of paths.map(text).filter(Boolean)) {
    try {
      return await readJsonArtifact(artifactPath);
    } catch (err) {
      lastErr = err;
      if (err.code !== "ENOENT") throw err;
    }
  }
  throw lastErr || new Error("no artifact path configured");
}

function attachRelationTrajectoryLens(bundle, relationTrajectory) {
  if (!relationTrajectory || typeof relationTrajectory !== "object") return bundle;
  const next = bundle && typeof bundle === "object"
    ? { ...bundle, lenses: { ...(bundle.lenses || {}) } }
    : {
        schemaVersion: "atlas.starmap.lenses.v1",
        generatedAt: relationTrajectory.generatedAt || "",
        source: relationTrajectory.source || {},
        counts: {},
        lenses: {},
      };
  next.lenses.relationTrajectory = {
    schemaVersion: relationTrajectory.schemaVersion || "",
    generatedAt: relationTrajectory.generatedAt || "",
    source: relationTrajectory.source || {},
    counts: relationTrajectory.counts || {},
    ...(relationTrajectory.lenses || {}),
  };
  return next;
}

async function loadRelationTrajectoryArtifact() {
  if (_relationTrajectoryArtifact !== undefined) return _relationTrajectoryArtifact;
  if (_relationTrajectoryArtifactLoading) return _relationTrajectoryArtifactLoading;

  const configuredPath = text(process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS);
  const relationTrajectoryPath = configuredPath
    || path.resolve(moduleDir, "../data/dj_relation_trajectory_lens.json.gz");

  _relationTrajectoryArtifactLoading = (async () => {
    const start = Date.now();
    try {
      _relationTrajectoryArtifact = await readJsonArtifact(relationTrajectoryPath);
      console.log(`[atlas-miniapp] DJ relation trajectory loaded in ${Date.now() - start}ms`);
      return _relationTrajectoryArtifact;
    } catch (err) {
      if (configuredPath || err.code !== "ENOENT") {
        console.warn("[atlas-miniapp] DJ relation trajectory not available:", err.message);
      }
      _relationTrajectoryArtifact = null;
      return null;
    } finally {
      _relationTrajectoryArtifactLoading = null;
    }
  })();

  return _relationTrajectoryArtifactLoading;
}

async function loadStarmapLenses() {
  if (_starmapLenses) return _starmapLenses;
  if (_starmapLensesLoading) return _starmapLensesLoading;

  const lensPath = process.env.ATLAS_STARMAP_LENSES
    || path.resolve(moduleDir, "../data/atlas_starmap_lenses.json.gz");

  _starmapLensesLoading = (async () => {
    const start = Date.now();
    let bundle = null;
    let baseError = null;
    try {
      bundle = await readJsonArtifact(lensPath);
    } catch (err) {
      baseError = err;
    }
    try {
      const relationTrajectory = await loadRelationTrajectoryArtifact();
      if (relationTrajectory) {
        bundle = attachRelationTrajectoryLens(bundle, relationTrajectory);
      }
      if (!bundle) {
        throw baseError || new Error("no starmap lens artifact configured");
      }
      _starmapLenses = bundle;
      console.log(`[atlas-miniapp] Starmap lenses loaded in ${Date.now() - start}ms`);
      return _starmapLenses;
    } catch (err) {
      console.warn("[atlas-miniapp] Starmap lenses not available:", baseError?.message || err.message);
      _starmapLenses = null;
      return null;
    } finally {
      _starmapLensesLoading = null;
    }
  })();

  return _starmapLensesLoading;
}

async function loadRadioExternalLinks() {
  if (_radioExternalLinks) return _radioExternalLinks;
  if (_radioExternalLinksLoading) return _radioExternalLinksLoading;

  const radioPath = process.env.ATLAS_RADIO_EXTERNAL_LINKS
    || path.resolve(moduleDir, "../data/radio_external_links_public_seed_candidate.json.gz");

  _radioExternalLinksLoading = (async () => {
    const start = Date.now();
    try {
      _radioExternalLinks = await readJsonArtifact(radioPath);
      console.log(`[atlas-miniapp] Radio external links loaded in ${Date.now() - start}ms`);
      return _radioExternalLinks;
    } catch (err) {
      console.warn("[atlas-miniapp] Radio external links not available:", err.message);
      _radioExternalLinks = null;
      return null;
    } finally {
      _radioExternalLinksLoading = null;
    }
  })();

  return _radioExternalLinksLoading;
}

async function loadDjExternalLinksAccepted() {
  if (_djExternalLinksAccepted) return _djExternalLinksAccepted;
  if (_djExternalLinksAcceptedLoading) return _djExternalLinksAcceptedLoading;

  const dataPath = process.env.ATLAS_DJ_EXTERNAL_LINKS
    || path.resolve(moduleDir, "../data/dj_external_links_accepted_candidate.json.gz");

  _djExternalLinksAcceptedLoading = (async () => {
    const start = Date.now();
    try {
      const bundle = await readJsonArtifact(dataPath);
      if (bundle?.candidateOnly !== true) {
        console.warn("[atlas-miniapp] DJ external links: candidateOnly guard failed, skipping");
        return null;
      }
      _djExternalLinksAccepted = bundle;
      console.log(`[atlas-miniapp] DJ external links loaded in ${Date.now() - start}ms (${bundle?.counts?.dj_with_links} DJs)`);
      return _djExternalLinksAccepted;
    } catch (err) {
      if (err.code !== "ENOENT") console.warn("[atlas-miniapp] DJ external links not available:", err.message);
      _djExternalLinksAccepted = null;
      return null;
    } finally {
      _djExternalLinksAcceptedLoading = null;
    }
  })();

  return _djExternalLinksAcceptedLoading;
}

async function loadBioCandidates() {
  if (_bioCandidates) return _bioCandidates;
  if (_bioCandidatesLoading) return _bioCandidatesLoading;
  const dataPath = process.env.ATLAS_DJ_BIO_CANDIDATES
    || path.resolve(moduleDir, "../data/bio_candidates_accepted.jsonl");
  _bioCandidatesLoading = (async () => {
    try {
      const raw = await readFile(dataPath, "utf-8");
      const map = {};
      for (const line of raw.split("\n")) {
        if (!line.trim()) continue;
        const row = JSON.parse(line);
        if (row?.candidateOnly === true && row?.reviewDecision === "accept" && row?.djId)
          map[row.djId] = row;
      }
      _bioCandidates = map;
      console.log(`[atlas-miniapp] Bio candidates loaded (${Object.keys(map).length} DJs)`);
      return map;
    } catch (err) {
      if (err.code !== "ENOENT") console.warn("[atlas-miniapp] bio candidates:", err.message);
      _bioCandidates = {};
      return {};
    } finally { _bioCandidatesLoading = null; }
  })();
  return _bioCandidatesLoading;
}

async function loadBioSnippets() {
  if (_bioSnippets) return _bioSnippets;
  if (_bioSnippetsLoading) return _bioSnippetsLoading;
  const dataPath = process.env.ATLAS_DJ_BIO_SNIPPETS
    || path.resolve(moduleDir, "../data/bio_snippets_accepted.jsonl");
  _bioSnippetsLoading = (async () => {
    try {
      const raw = await readFile(dataPath, "utf-8");
      const map = {};
      for (const line of raw.split("\n")) {
        if (!line.trim()) continue;
        const row = JSON.parse(line);
        if (row?.candidateOnly === true && row?.reviewDecision === "accept" && row?.djId)
          map[row.djId] = row;
      }
      _bioSnippets = map;
      console.log(`[atlas-miniapp] Bio snippets loaded (${Object.keys(map).length} DJs)`);
      return map;
    } catch (err) {
      if (err.code !== "ENOENT") console.warn("[atlas-miniapp] bio snippets:", err.message);
      _bioSnippets = {};
      return {};
    } finally { _bioSnippetsLoading = null; }
  })();
  return _bioSnippetsLoading;
}

async function loadSceneClusters() {
  if (_sceneClusters) return _sceneClusters;
  if (_sceneClustersLoading) return _sceneClustersLoading;
  const dataPath = process.env.ATLAS_SCENE_CLUSTERS
    || path.resolve(moduleDir, "../data/scene_clusters_candidate.json.gz");
  _sceneClustersLoading = (async () => {
    try {
      const raw = await readFile(dataPath);
      const json = JSON.parse(gunzipSync(raw).toString("utf-8"));
      // build reverse map djId → {clusterId, label, city, members[]}
      const byDj = {};
      for (const cl of (json.clusters || [])) {
        for (const djId of (cl.members || [])) {
          byDj[djId] = cl;
        }
      }
      _sceneClusters = byDj;
      console.log(`[atlas-miniapp] Scene clusters loaded (${(json.clusters || []).length} clusters)`);
      return byDj;
    } catch (err) {
      if (err.code !== "ENOENT") console.warn("[atlas-miniapp] scene clusters:", err.message);
      _sceneClusters = {};
      return {};
    } finally { _sceneClustersLoading = null; }
  })();
  return _sceneClustersLoading;
}

// Public-safe roles; 'other' stays hidden from DJ detail page.
const DJ_OUTLINK_PUBLIC_ROLES = new Set(["listen", "social", "profile", "interview", "radio", "source", "video"]);

function externalLinksForDjFromBundle(bundle, djId, limit = 20) {
  const ids = uniqueTextValues(djId);
  if (!ids.length || !bundle || bundle.candidateOnly !== true) return [];
  const out = [];
  const seen = new Set();
  for (const id of ids) {
    const links = Array.isArray(bundle.djLinks?.[id]) ? bundle.djLinks[id] : [];
    for (const lk of links) {
      if (!lk?.url || !DJ_OUTLINK_PUBLIC_ROLES.has(text(lk.role))) continue;
      const key = `${text(lk.url).toLowerCase()}\u0000${text(lk.role)}\u0000${text(lk.platform)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({
        url: text(lk.url),
        platform: text(lk.platform) || "other",
        role: text(lk.role) || "other",
        label: text(lk.label),
        candidateOnly: true,
      });
      if (out.length >= limit) return out;
    }
  }
  return out;
}

async function externalLinksForDj(djId, limit = 20) {
  const bundle = await loadDjExternalLinksAccepted();
  return externalLinksForDjFromBundle(bundle, djId, limit);
}

async function loadRadioPrograms() {
  if (_radioPrograms) return _radioPrograms;
  if (_radioProgramsLoading) return _radioProgramsLoading;

  const radioProgramsPath = process.env.ATLAS_RADIO_PROGRAMS
    || path.resolve(moduleDir, "../data/radio_programs_candidate.json.gz");

  _radioProgramsLoading = (async () => {
    const start = Date.now();
    try {
      _radioPrograms = await readJsonArtifact(radioProgramsPath);
      console.log(`[atlas-miniapp] Radio programs loaded in ${Date.now() - start}ms`);
      return _radioPrograms;
    } catch (err) {
      console.warn("[atlas-miniapp] Radio programs not available:", err.message);
      _radioPrograms = null;
      return null;
    } finally {
      _radioProgramsLoading = null;
    }
  })();

  return _radioProgramsLoading;
}

async function loadRadioProgramMatchReview() {
  if (_radioProgramMatchReview) return _radioProgramMatchReview;
  if (_radioProgramMatchReviewLoading) return _radioProgramMatchReviewLoading;

  const configuredPath = text(process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW);
  const reviewPaths = configuredPath ? [configuredPath] : [
    path.resolve(moduleDir, "../data/radio_program_match_review.json.gz"),
    path.resolve(moduleDir, "../data/radio_program_match_review.json"),
  ];

  _radioProgramMatchReviewLoading = (async () => {
    const start = Date.now();
    try {
      _radioProgramMatchReview = await readFirstJsonArtifact(reviewPaths);
      console.log(`[atlas-miniapp] Radio program match review loaded in ${Date.now() - start}ms`);
      return _radioProgramMatchReview;
    } catch (err) {
      if (configuredPath || err.code !== "ENOENT") {
        console.warn("[atlas-miniapp] Radio program match review not available:", err.message);
      }
      _radioProgramMatchReview = null;
      return null;
    } finally {
      _radioProgramMatchReviewLoading = null;
    }
  })();

  return _radioProgramMatchReviewLoading;
}

async function loadNeighborhoodBundle() {
  if (_neighborhood) return _neighborhood;
  if (_neighborhoodLoading) return _neighborhoodLoading;

  const neighborhoodPath = process.env.ATLAS_NEIGHBORHOOD_BUNDLE
    || path.resolve(moduleDir, "../data/atlas_neighborhood.json.gz");

  _neighborhoodLoading = (async () => {
    const start = Date.now();
    try {
      _neighborhood = await readJsonArtifact(neighborhoodPath);
      console.log(`[atlas-miniapp] Neighborhood bundle loaded in ${Date.now() - start}ms (${Object.keys(_neighborhood?.byNode || {}).length} subjects)`);
      return _neighborhood;
    } catch (err) {
      console.warn("[atlas-miniapp] Neighborhood bundle not available:", err.message);
      _neighborhood = null;
      return null;
    } finally {
      _neighborhoodLoading = null;
    }
  })();

  return _neighborhoodLoading;
}

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

function parseJsonish(value, fallback) {
  if (value == null || value === "") return fallback;
  if (typeof value === "string") {
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  }
  return value;
}

function normalizeSocial(value) {
  const raw = parseJsonish(value, {});
  if (!raw || Array.isArray(raw) || typeof raw !== "object") return {};
  const out = {};
  for (const [key, val] of Object.entries(raw)) {
    const v = text(val);
    if (v) out[key] = v;
  }
  return out;
}

function normalizeBioAtoms(value, limit = 8) {
  const raw = parseJsonish(value, []);
  if (!Array.isArray(raw)) return [];
  return raw.map((row) => {
    if (typeof row === "string") return { text: text(row) };
    const confidence = Number(row?.confidence ?? row?.cf);
    const atom = {
      text: text(row?.text ?? row?.t ?? row?.bioText ?? row?.bio_text_raw ?? row?.bio_text ?? row?.bio),
      sourceRefId: text(row?.sourceRefId ?? row?.sr ?? row?.source_ref_id),
      sourceTitle: text(row?.sourceTitle ?? row?.st ?? row?.source_title),
      language: text(row?.language ?? row?.lang),
    };
    if (Number.isFinite(confidence)) atom.confidence = confidence;
    return atom;
  }).filter((row) => row.text).slice(0, limit);
}

function normalizeRelatedColumns(value, limit = 8) {
  const raw = parseJsonish(value, []);
  if (!Array.isArray(raw)) return [];
  return raw.map((row) => ({
    columnId: text(row?.columnId ?? row?.id ?? row?.cid ?? row?.article_id),
    title: text(row?.title ?? row?.t),
    summary: text(row?.summary ?? row?.s ?? row?.excerpt),
    sourceRefId: text(row?.sourceRefId ?? row?.sr ?? row?.source_ref_id),
    sourceTitle: text(row?.sourceTitle ?? row?.st ?? row?.source_title),
    publishedAt: text(row?.publishedAt ?? row?.p ?? row?.published_at),
  })).filter((row) => row.columnId || row.title).slice(0, limit);
}

const EXTERNAL_LINK_ROLE_ORDER = { listen: 0, profile: 1, social: 2, interview: 3, radio: 4, video: 5, source: 6, other: 7 };

function normalizeExternalLinks(value, limit = 20, idx = null) {
  const raw = parseJsonish(value, []);
  if (!Array.isArray(raw)) return [];
  return raw.map((row) => {
    const sourceRefId = text(row?.sourceRefId ?? row?.sr ?? row?.source_ref_id);
    const source = sourceRefId && idx ? sourceRef(idx, sourceRefId) : null;
    return {
      url: text(row?.url ?? row?.u),
      platform: text(row?.platform ?? row?.p) || "other",
      role: text(row?.role ?? row?.r) || "other",
      label: text(row?.label ?? row?.l),
      sourceRefId,
      sourceTitle: text(row?.sourceTitle ?? row?.st ?? row?.source_title) || source?.sourceTitle || "",
      sourceAccountName: source?.sourceAccountName || "",
      sourcePublishedAt: source?.sourcePublishedAt || "",
      sourceKind: source?.sourceKind || "",
    };
  }).filter((row) => row.url)
    .sort((a, b) => (EXTERNAL_LINK_ROLE_ORDER[a.role] ?? 9) - (EXTERNAL_LINK_ROLE_ORDER[b.role] ?? 9))
    .slice(0, limit);
}

function normalizeRadioProgram(row, reviewMeta = null) {
  const url = text(row?.url);
  if (!url || row?.noHotlink === false || row?.openMode === "embedded_media") return null;
  const djMatches = Array.isArray(row?.djMatches) ? row.djMatches.map((match) => ({
    djId: text(match?.djId),
    displayName: text(match?.displayName),
    matchedText: text(match?.matchedText),
    confidence: Number(match?.confidence || 0),
    matchKind: text(match?.matchKind),
  })).filter((match) => match.djId) : [];
  const out = {
    programId: text(row?.programId ?? row?.id),
    stationKey: text(row?.stationKey),
    stationName: text(row?.stationName),
    title: text(row?.title),
    url,
    platform: text(row?.platform) || "other",
    publishedAt: text(row?.publishedAt),
    description: text(row?.description),
    sourceUrl: text(row?.sourceUrl),
    openMode: "external_original_site",
    noHotlink: true,
    candidateOnly: row?.candidateOnly !== false,
    djMatches,
  };
  if (reviewMeta) {
    out.reviewDecision = text(reviewMeta.decision) || "safe_display";
    out.reviewReasons = Array.isArray(reviewMeta.reasons) ? reviewMeta.reasons.map(text).filter(Boolean) : [];
    out.reviewMatchedTexts = Array.isArray(reviewMeta.matchedTexts) ? reviewMeta.matchedTexts.map(text).filter(Boolean) : [];
  }
  return out;
}

function radioUrlKey(url) {
  // collapse #Top / trailing-slash variants (e.g. BAIHUI #Top duplicates) to one canonical key
  return text(url).split("#")[0].replace(/\/+$/, "").toLowerCase();
}

// Month names collide with HÖR/program date strings ("HÖR – April 30 / 2026" -> DJ "APRIL").
// Hide a program from a DJ when EVERY match for that DJ is just a month token.
const RADIO_GENERIC_MATCH_TERMS = new Set([
  "january", "february", "march", "april", "may", "june", "july", "august",
  "september", "october", "november", "december",
  "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
]);
const RADIO_REVIEW_DECISION_RANK = { safe_display: 0, review_only: 1, hard_hide: 2 };

function rankRadioReviewDecision(value) {
  const key = text(value) || "safe_display";
  return RADIO_REVIEW_DECISION_RANK[key] ?? 0;
}

function strongestRadioReviewDecision(a, b) {
  return rankRadioReviewDecision(a) >= rankRadioReviewDecision(b) ? a : b;
}

function buildRadioProgramReviewIndex(review) {
  if (
    !review
    || review.candidateOnly !== true
    || review.productionWriteExecuted === true
    || !Array.isArray(review.rows)
  ) {
    return null;
  }
  if (review._programDjReview) return review._programDjReview;
  const index = new Map();
  for (const row of review.rows) {
    const programId = text(row?.programId);
    const djId = text(row?.djId);
    if (!programId || !djId) continue;
    const key = `${programId}\u0000${djId}`;
    const existing = index.get(key) || {
      decision: "safe_display",
      reasons: new Set(),
      matchedTexts: new Set(),
    };
    existing.decision = strongestRadioReviewDecision(existing.decision, text(row?.decision) || "review_only");
    for (const reason of Array.isArray(row?.reasons) ? row.reasons : []) {
      const r = text(reason);
      if (r) existing.reasons.add(r);
    }
    const matchedText = text(row?.matchedText);
    if (matchedText) existing.matchedTexts.add(matchedText);
    index.set(key, existing);
  }
  review._programDjReview = index;
  return index;
}

function radioProgramReviewForDj(review, program, djId) {
  const index = buildRadioProgramReviewIndex(review);
  if (!index) return null;
  const programId = text(program?.programId ?? program?.id);
  const id = text(djId);
  if (!programId || !id) return null;
  const row = index.get(`${programId}\u0000${id}`);
  if (!row) return { decision: "safe_display", reasons: [], matchedTexts: [], hasReviewRow: false };
  return {
    decision: row.decision,
    reasons: Array.from(row.reasons).sort(),
    matchedTexts: Array.from(row.matchedTexts).sort(),
    hasReviewRow: true,
  };
}

function radioMatchGenericForDj(program, djId) {
  const mine = (Array.isArray(program?.djMatches) ? program.djMatches : []).filter((m) => text(m?.djId) === djId);
  return mine.length > 0 && mine.every((m) => RADIO_GENERIC_MATCH_TERMS.has(text(m?.matchedText).toLowerCase().trim()));
}

function radioMatchAmbiguousForDj(program, djId) {
  // matches are normalized_substring only; if this DJ's matched text ALSO maps to a different
  // djId in the same program (新生 vs 新生新生), the attribution is unsafe -> hide, send to review.
  const matches = Array.isArray(program?.djMatches) ? program.djMatches : [];
  const myTexts = new Set(
    matches.filter((m) => text(m?.djId) === djId).map((m) => text(m?.matchedText)).filter(Boolean)
  );
  if (!myTexts.size) return false;
  return matches.some((m) => text(m?.djId) !== djId && myTexts.has(text(m?.matchedText)));
}

function radioProgramsForDjFromBundle(bundle, djId, limit = 8, matchReview = null, options = {}) {
  const ids = uniqueTextValues(djId);
  if (!ids.length || !bundle || bundle.candidateOnly !== true || bundle.productionWriteExecuted === true) return [];
  const programs = Array.isArray(bundle.programs) ? bundle.programs : [];
  const reviewAvailable = Boolean(buildRadioProgramReviewIndex(matchReview));
  const includeReviewOnly = options.includeReviewOnly === true;
  const byId = new Map(programs.map((program) => [text(program?.programId ?? program?.id), program]));
  const seenUrl = new Set();
  const out = [];
  for (const id of ids) {
    const referencedIds = Array.isArray(bundle.programsByDjId?.[id]) ? bundle.programsByDjId[id].map(text).filter(Boolean) : [];
    const rawMatches = referencedIds.length
      ? referencedIds.map((programId) => byId.get(programId)).filter(Boolean)
      : programs.filter((program) => (Array.isArray(program?.djMatches) ? program.djMatches : []).some((match) => text(match?.djId) === id));
    for (const program of rawMatches) {
      const reviewMeta = radioProgramReviewForDj(matchReview, program, id);
      if (reviewAvailable) {
        if (reviewMeta?.decision === "hard_hide") continue;
        if (reviewMeta?.decision === "review_only" && !includeReviewOnly) continue;
        if (!reviewMeta?.hasReviewRow) {
          if (radioMatchAmbiguousForDj(program, id)) continue;
          if (radioMatchGenericForDj(program, id)) continue;
        }
      } else {
        if (radioMatchAmbiguousForDj(program, id)) continue;
        if (radioMatchGenericForDj(program, id)) continue;
      }
      const normalized = normalizeRadioProgram(program, reviewMeta);
      if (!normalized) continue;
      const key = radioUrlKey(normalized.url);
      if (key && seenUrl.has(key)) continue;                 // dedup #Top / slash variants
      seenUrl.add(key);
      out.push(normalized);
      if (out.length >= limit) return out;
    }
  }
  return out;
}

async function radioProgramsForDj(djId, limit = 8) {
  const [bundle, matchReview] = await Promise.all([loadRadioPrograms(), loadRadioProgramMatchReview()]);
  return radioProgramsForDjFromBundle(bundle, djId, limit, matchReview);
}

function numericValue(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function nonEmptyRows(value) {
  return Array.isArray(value) ? value : [];
}

function uniqueRowsBy(rows, keyFn) {
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    const key = text(keyFn(row));
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(row);
  }
  return out;
}

function normalizeTrajectoryCollaborator(row) {
  const djId = text(row?.djId ?? row?.id ?? row?.dstDjId);
  const displayName = text(row?.displayName ?? row?.name ?? row?.dstName ?? row?.djName);
  if (!djId && !displayName) return null;
  return {
    djId,
    displayName: displayName || djId,
    sameEventCount: numericValue(row?.sameEventCount),
    b2bCount: numericValue(row?.b2bCount),
    relationScore: numericValue(row?.relationScore ?? row?.score),
    label: text(row?.label),
  };
}

function normalizeTrajectoryRelation(row, djId) {
  const srcDjId = text(row?.srcDjId);
  const dstDjId = text(row?.dstDjId);
  if (srcDjId !== djId && dstDjId !== djId) return null;
  const isSrc = srcDjId === djId;
  const otherDjId = isSrc ? dstDjId : srcDjId;
  const displayName = text(isSrc ? row?.dstName : row?.srcName);
  if (!otherDjId && !displayName) return null;
  return {
    djId: otherDjId,
    displayName: displayName || otherDjId,
    sameEventCount: numericValue(row?.sameEventCount),
    sameVenueCount: numericValue(row?.sameVenueCount),
    b2bCount: numericValue(row?.b2bCount),
    sourceDiversity: numericValue(row?.sourceDiversity),
    relationScore: numericValue(row?.relationScore ?? row?.score),
    label: text(row?.label),
    firstSeenAt: text(row?.firstSeenAt),
    lastSeenAt: text(row?.lastSeenAt),
    evidenceCount: Array.isArray(row?.evidence) ? row.evidence.length : 0,
  };
}

function normalizeTrajectoryVenue(row) {
  const venueId = text(row?.venueId ?? row?.id);
  const venueName = text(row?.venueName ?? row?.name);
  if (!venueId && !venueName) return null;
  return {
    venueId,
    venueName: venueName || venueId,
    city: text(row?.city),
    eventCount: numericValue(row?.eventCount),
    score: numericValue(row?.score),
    firstSeenAt: text(row?.firstSeenAt),
    lastSeenAt: text(row?.lastSeenAt),
  };
}

function normalizeTrajectoryCity(row) {
  const city = text(row?.city);
  if (!city) return null;
  return {
    city,
    eventCount: numericValue(row?.eventCount),
    firstSeenAt: text(row?.firstSeenAt),
    lastSeenAt: text(row?.lastSeenAt),
    topVenues: nonEmptyRows(row?.topVenues).map((venue) => ({
      venueId: text(venue?.venueId ?? venue?.id),
      venueName: text(venue?.venueName ?? venue?.name),
      eventCount: numericValue(venue?.eventCount),
    })).filter((venue) => venue.venueId || venue.venueName).slice(0, 3),
  };
}

function normalizeTrajectoryEvent(row) {
  const eventId = text(row?.eventId ?? row?.id);
  const title = text(row?.title ?? row?.eventTitle);
  if (!eventId && !title) return null;
  return {
    eventId,
    title: title || eventId,
    startsAt: text(row?.startsAt ?? row?.date),
    timeText: text(row?.timeText),
    city: text(row?.city),
    venueId: text(row?.venueId),
    venueName: text(row?.venueName),
    sourceRefId: text(row?.sourceRefId),
    confidence: numericValue(row?.confidence, null),
  };
}

function relationTrajectoryForDjFromArtifact(artifact, djId, limits = {}) {
  for (const id of uniqueTextValues(djId)) {
    const result = relationTrajectoryForSingleDjFromArtifact(artifact, id, limits);
    if (result) return result;
  }
  return null;
}

function relationTrajectoryForSingleDjFromArtifact(artifact, djId, limits = {}) {
  const id = text(djId);
  const lens = artifact?.lenses || {};
  const relation = lens.relation || {};
  const trajectory = lens.trajectory || {};
  if (!id || !relation || !trajectory) return null;

  const maxCollaborators = Math.max(1, parseInt(limits.collaboratorLimit) || 10);
  const maxRelations = Math.max(1, parseInt(limits.relationLimit) || 8);
  const maxVenues = Math.max(1, parseInt(limits.venueLimit) || 8);
  const maxCities = Math.max(1, parseInt(limits.cityLimit) || 6);
  const maxEvents = Math.max(1, parseInt(limits.eventLimit) || 6);

  const collaborators = uniqueRowsBy(nonEmptyRows(relation.collaborators?.[id])
    .map(normalizeTrajectoryCollaborator)
    .filter(Boolean), (row) => row.djId || row.displayName)
    .slice(0, maxCollaborators);
  const relations = uniqueRowsBy(nonEmptyRows(relation.relations)
    .map((row) => normalizeTrajectoryRelation(row, id))
    .filter(Boolean), (row) => row.djId || row.displayName)
    .slice(0, maxRelations);
  const venues = uniqueRowsBy(nonEmptyRows(trajectory.venues?.[id])
    .map(normalizeTrajectoryVenue)
    .filter(Boolean), (row) => row.venueId || row.venueName)
    .slice(0, maxVenues);
  const cities = uniqueRowsBy(nonEmptyRows(trajectory.cities?.[id])
    .map(normalizeTrajectoryCity)
    .filter(Boolean), (row) => row.city)
    .slice(0, maxCities);
  const events = uniqueRowsBy(nonEmptyRows(trajectory.events?.[id])
    .map(normalizeTrajectoryEvent)
    .filter(Boolean), (row) => row.eventId || row.title)
    .slice(0, maxEvents);

  if (!collaborators.length && !relations.length && !venues.length && !cities.length && !events.length) {
    return null;
  }

  const source = artifact.source || {};
  return {
    schemaVersion: "atlas_miniapp.artist_relation_trajectory.v1",
    generatedAt: text(artifact.generatedAt),
    source: {
      candidateOnly: source.candidateOnly === true || artifact.candidateOnly === true,
      productionWriteExecuted: source.productionWriteExecuted === true || artifact.productionWriteExecuted === true,
      mode: text(source.mode),
    },
    counts: {
      collaborators: collaborators.length,
      relations: relations.length,
      venues: venues.length,
      cities: cities.length,
      events: events.length,
    },
    collaborators,
    relations,
    venues,
    cities,
    events,
  };
}

async function relationTrajectoryForDj(djId, limits = {}) {
  const artifact = await loadRelationTrajectoryArtifact();
  return relationTrajectoryForDjFromArtifact(artifact, djId, limits);
}

function artistPayloadParts(idx, subject, djId) {
  const p = idx.profiles[djId] || {};
  const social = normalizeSocial(p.s ?? p.social ?? p.social_json ?? p.socialJson);
  const bioAtoms = normalizeBioAtoms(
    p.ba ?? p.bioAtoms ?? idx.bio_atoms?.[djId] ?? idx.bioAtoms?.[djId] ?? idx.dj_bio_atoms?.[djId]
  );
  const relatedColumns = normalizeRelatedColumns(
    p.rc ?? p.relatedColumns ?? idx.related_columns?.[djId] ?? idx.relatedColumns?.[djId] ?? idx.column_articles?.[djId]
  );
  const profile = {
    subjectId: djId, djId, displayName: subject.n, aliases: subject.a, city: subject.c || null,
    eventCount: subject.ec, venueCount: p.vc || 0, collaboratorCount: p.cc || 0,
    firstSeenAt: p.fs || null, lastSeenAt: p.ls || null,
    bio: p.b || null, bioSource: p.bs || null,
    bioCandidate: null, bioCandidateSource: null,
    sceneCluster: null,
    residentVenues: [],
    labelAffiliations: [],
    social,
    bioAtoms,
    externalLinks: normalizeExternalLinks(p.x ?? idx.dj_external_links?.[djId], 20, idx),
  };
  return { profile, social, bioAtoms, relatedColumns };
}

// Similar DJs = the DJ-typed neighbors from the precomputed neighborhood graph
// Returns {label, city, members[{djId,displayName,city,eventCount}]} for the DJ's cluster, or null.
function sceneClusterForDj(idx, clusterMap, djId, limit = 6) {
  const ids = uniqueTextValues(djId);
  const cluster = ids.map((id) => clusterMap[id]).find(Boolean);
  if (!cluster) return null;
  const members = (cluster.members || [])
    .filter(id => !ids.includes(id))
    .slice(0, limit * 3)  // oversample then filter by eventCount
    .map(id => {
      const s = publicSubjectResolved(idx, id);
      return { djId: s.id, displayName: s.name, city: s.city, eventCount: s.eventCount };
    })
    .sort((a, b) => b.eventCount - a.eventCount)
    .slice(0, limit);
  return { label: cluster.label, city: cluster.city, members };
}

// Returns [{venueId, displayName, city, weight}] for DJ's highest-weight resident_at venue edges.
function residentVenuesForDj(idx, bundle, djId, limit = 4) {
  if (!bundle?.byNode) return [];
  return firstRowsForSubjectIds(bundle, djId).rows
    .filter(r => r.rt === "resident_at" && typeFromSubjectId(text(r.u)) === "venue")
    .sort((a, b) => b.w - a.w)
    .slice(0, limit)
    .map(r => { const s = publicSubjectResolved(idx, r.u); return { venueId: s.id, displayName: s.name, city: s.city, weight: Number(r.w) || 0 }; });
}

// Returns [{orgId, displayName, city, weight}] for DJ's highest-weight signed_to org edges.
function labelAffiliationsForDj(idx, bundle, djId, limit = 3) {
  if (!bundle?.byNode) return [];
  return firstRowsForSubjectIds(bundle, djId).rows
    .filter(r => r.rt === "signed_to" && typeFromSubjectId(text(r.u)) === "org")
    .sort((a, b) => b.w - a.w)
    .slice(0, limit)
    .map(r => { const s = publicSubjectResolved(idx, r.u); return { orgId: s.id, displayName: s.name, city: s.city, weight: Number(r.w) || 0 }; });
}

// (byNode rows are already rank-sorted). No new model — just filter the graph we
// already serve for /neighborhood and /path, drop self, dedupe. See plan 101 #1.
function similarDjsFromBundle(idx, bundle, djId, limit = 8) {
  const ids = uniqueTextValues(djId);
  const id = ids[0] || "";
  if (!idx || !bundle?.byNode || !id) return [];
  const myCity = subjectById(idx, id)?.c || null;
  const rows = firstRowsForSubjectIds(bundle, ids).rows;
  const seen = new Set(ids);
  const candidates = [];
  for (const row of rows) {
    const u = text(row.u);
    if (!u || seen.has(u) || typeFromSubjectId(u) !== "dj") continue;
    seen.add(u);
    const s = publicSubjectResolved(idx, u);
    const w = Number(row.w) || 0;
    candidates.push({
      djId: s.id,
      displayName: s.name,
      city: s.city,
      eventCount: s.eventCount,
      relationType: text(row.rt) || "collab",
      sharedWeight: w,
      _score: myCity && s.city === myCity ? w * 1.5 : w,
    });
  }
  candidates.sort((a, b) => b._score - a._score);
  return candidates.slice(0, limit).map(({ _score: _, ...c }) => c);
}

async function similarDjsForDj(djId, limit = 8) {
  const idx = await loadIndex();
  const bundle = idx ? await loadAlignedNeighborhoodBundle(idx) : null;
  return similarDjsFromBundle(idx, bundle, djId, limit);
}

export async function getArtist({
  name,
  eventLimit,
  eventOffset,
  collaboratorLimit,
  collaboratorOffset,
  venueLimit,
  venueOffset,
} = {}) {
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
  const lookupIds = subjectReferenceIds(idx, s, { typeFilter: "dj" });
  const { profile, social, bioAtoms, relatedColumns } = artistPayloadParts(idx, s, djId);
  const [radioPrograms, relationTrajectory, djOutlinks, similarDjs, bioMap, snippetMap, clusterMap, nb] = await Promise.all([
    radioProgramsForDj(lookupIds),
    relationTrajectoryForDj(lookupIds),
    externalLinksForDj(lookupIds),
    similarDjsForDj(lookupIds, 8),
    loadBioCandidates(),
    loadBioSnippets(),
    loadSceneClusters(),
    loadAlignedNeighborhoodBundle(idx),
  ]);
  profile.radioPrograms = radioPrograms;
  if (relationTrajectory) profile.relationTrajectory = relationTrajectory;
  if (djOutlinks.length) profile.externalLinks = djOutlinks;
  profile.similarDjs = similarDjs;
  if (!profile.bio) {
    const snippet = firstValueByIds(snippetMap, lookupIds);
    const bio = firstValueByIds(bioMap, lookupIds);
    if (snippet) {
      profile.bioCandidate = snippet.draft || null;
      profile.bioCandidateSource = snippet.bioSource || null;
    } else if (bio) {
      profile.bioCandidate = bio.draft || null;
    }
  }
  profile.sceneCluster = sceneClusterForDj(idx, clusterMap, lookupIds, 6);
  profile.residentVenues = residentVenuesForDj(idx, nb, lookupIds, 4);
  profile.labelAffiliations = labelAffiliationsForDj(idx, nb, lookupIds, 3);

  const eventPage = artistListPage(
    idx.events[djId], eventLimit, eventOffset, ARTIST_LIST_PAGE_LIMITS.events, profile.eventCount,
  );
  const venuePage = artistListPage(
    idx.dj_venues[djId], venueLimit, venueOffset, ARTIST_LIST_PAGE_LIMITS.venues, profile.venueCount,
  );
  const collaboratorPage = artistListPage(
    idx.collabs[djId],
    collaboratorLimit,
    collaboratorOffset,
    ARTIST_LIST_PAGE_LIMITS.collaborators,
    profile.collaboratorCount,
  );

  return {
    schemaVersion: "atlas_miniapp.artist_response.v1",
    query: artistName, found: true, subjectId: djId, canonicalSubjectId: djId, resolvedVia: "name",
    profile,
    events: eventPage.items.map(e => ({ eventId: e.eid, title: e.t, date: e.d || null, venueName: e.v || null, city: e.ci || null, ...publicSourceFields(idx, e.sr) })),
    venues: venuePage.items.map(v => ({ venueName: v.vn, eventCount: v.ec })),
    collaborators: collaboratorPage.items.map(c => ({ djId: c.di, displayName: c.n, sameEventCount: c.ec })),
    pagination: {
      events: eventPage.pagination,
      venues: venuePage.pagination,
      collaborators: collaboratorPage.pagination,
    },
    social,
    bioAtoms,
    relatedColumns,
    radioPrograms,
    relationTrajectory,
    generation: publicAtlasGeneration(idx, nb),
    alternatives: subjects.slice(1, 4).map(s => ({ subjectId: s.i, displayName: s.n })),
  };
}

// Global search over all v2 subjects (dj/venue/org/series) — the entry point to the
// full 75k-entity library. Reuses searchSubjects (exact -> prefix -> contains),
// ranks hits by event_count so popular entities surface first.
export async function getSearch({ q, type, limit } = {}) {
  const empty = (reason) => ({
    schemaVersion: "atlas_miniapp.search_response.v1",
    query: text(q), type: text(type) || null, found: false, reason, results: [],
  });
  const idx = await loadIndex();
  if (!idx) return empty("index_unavailable");
  const query = text(q);
  if (!query) return empty("missing_query");
  const typeFilter = ["dj", "venue", "org", "organizer", "series"].includes(text(type)) ? text(type) : null;
  const max = Math.max(1, Math.min(30, parseInt(limit) || 20));
  const results = searchSubjects(idx, query, typeFilter, { includeRelatedMatches: true })
    .slice()
    .sort((a, b) => (b.ec || 0) - (a.ec || 0))
    .slice(0, max)
    .map((s) => ({
      id: s.i, type: s.t, name: s.n, city: s.c || null,
      aliases: Array.isArray(s.a) ? s.a.slice(0, 4) : [],
      eventCount: s.ec || 0,
    }));
  return {
    schemaVersion: "atlas_miniapp.search_response.v1",
    query, type: typeFilter, found: results.length > 0,
    reason: results.length ? undefined : "no_match",
    results,
  };
}

export async function getNeighborhood({ subjectId, q, limit, depth } = {}) {
  const empty = (reason, extra = {}) => ({
    schemaVersion: "atlas_miniapp.neighborhood_response.v1",
    query: { subjectId: text(subjectId), q: text(q), depth: 1, limit: Math.max(1, Math.min(80, parseInt(limit) || 40)) },
    found: false,
    reason,
    center: null,
    neighbors: [],
    edges: [],
    ...extra,
  });

  const [idx, bundle] = await Promise.all([loadIndex(), loadNeighborhoodBundle()]);
  if (!idx) return empty("index_unavailable");
  if (!bundle?.byNode) return empty("neighborhood_unavailable");
  const handshake = atlasDatasetHandshake(idx, bundle);
  if (!handshake.ok) return empty(handshake.reason, { generation: publicAtlasGeneration(idx) });

  const requestedSubjectId = text(subjectId);
  let centerId = requestedSubjectId;
  const query = text(q);
  let resolvedSubject = null;
  if (centerId) {
    resolvedSubject = resolveSubjectReference(idx, centerId);
    if (resolvedSubject) centerId = resolvedSubject.canonicalId;
  }
  if (!centerId && query) {
    centerId = searchSubjects(idx, query, null)[0]?.i || "";
  }
  if (!centerId) return empty("missing_subject_id");

  const max = Math.max(1, Math.min(80, parseInt(limit) || 40));
  const requestedDepth = Math.max(1, Math.min(1, parseInt(depth) || 1));
  const centerSubject = resolvedSubject?.subject || subjectById(idx, centerId);
  const centerLookupIds = subjectReferenceIds(idx, centerSubject || centerId, {
    requestedId: requestedSubjectId,
    typeFilter: centerSubject?.t,
  });
  const graphCenter = firstRowsForSubjectIds(bundle, centerLookupIds);
  const rows = graphCenter.rows.slice(0, max);
  const center = publicSubject(idx, centerId);
  const neighbors = rows.map((row) => {
    const neighborId = text(row.u);
    return publicSubjectResolved(idx, neighborId, {
      relationType: text(row.rt) || "collab",
      weight: Number(row.w) || 0,
      rankScore: Number(row.rs) || 0,
      graphSubjectId: neighborId !== resolveSubjectReference(idx, neighborId)?.canonicalId ? neighborId : undefined,
    });
  }).filter((row) => row.id);
  const edges = neighbors.map((row) => omitUndefinedFields({
    source: centerId,
    target: row.id,
    relationType: row.relationType,
    weight: row.weight,
    sourceGraphId: graphCenter.id && graphCenter.id !== centerId ? graphCenter.id : undefined,
    targetGraphId: row.graphSubjectId,
  }));

  return {
    schemaVersion: "atlas_miniapp.neighborhood_response.v1",
    query: {
      subjectId: centerId,
      requestedSubjectId: requestedSubjectId && requestedSubjectId !== centerId ? requestedSubjectId : undefined,
      q: query,
      depth: requestedDepth,
      limit: max,
    },
    found: neighbors.length > 0,
    reason: neighbors.length ? undefined : "no_neighbors",
    center: requestedSubjectId && requestedSubjectId !== centerId
      ? { ...center, requestedSubjectId, resolvedVia: resolvedSubject?.resolvedVia || "unknown" }
      : center,
    neighbors,
    edges,
    generation: publicAtlasGeneration(idx, bundle),
  };
}

// Shortest connection path between two subjects through the neighborhood graph.
// Bidirectional BFS over byNode (avg degree ~14, edges are bidirectional) — meeting
// in the middle resolves even cross-scene DJ pairs in a few hops without scanning
// the whole 1M-edge graph. Returns the node chain + the relation on each hop.
export async function getPath({ from, to, fromName, toName, maxDepth } = {}) {
  const empty = (reason, extra = {}) => ({
    schemaVersion: "atlas_miniapp.path_response.v1",
    query: { from: text(from) || text(fromName), to: text(to) || text(toName) },
    found: false, reason, hops: 0, path: [], edges: [], ...extra,
  });
  const [idx, bundle] = await Promise.all([loadIndex(), loadNeighborhoodBundle()]);
  if (!idx) return empty("index_unavailable");
  if (!bundle?.byNode) return empty("neighborhood_unavailable");
  const handshake = atlasDatasetHandshake(idx, bundle);
  if (!handshake.ok) return empty(handshake.reason, { generation: publicAtlasGeneration(idx) });

  const requestedFrom = text(from);
  const requestedTo = text(to);
  let fromId = requestedFrom, toId = requestedTo;
  let fromResolved = null, toResolved = null;
  if (fromId) {
    fromResolved = resolveSubjectReference(idx, fromId);
    if (fromResolved) fromId = fromResolved.canonicalId;
  }
  if (toId) {
    toResolved = resolveSubjectReference(idx, toId);
    if (toResolved) toId = toResolved.canonicalId;
  }
  if (!fromId && text(fromName)) {
    fromResolved = null;
    fromId = searchSubjects(idx, text(fromName), null)[0]?.i || "";
  }
  if (!toId && text(toName)) {
    toResolved = null;
    toId = searchSubjects(idx, text(toName), null)[0]?.i || "";
  }
  if (!fromId || !toId) return empty("missing_endpoint");
  if (fromId === toId) return empty("same_node");

  const byNode = bundle.byNode;
  const fromSubject = fromResolved?.subject || subjectById(idx, fromId);
  const toSubject = toResolved?.subject || subjectById(idx, toId);
  const fromLookupIds = subjectReferenceIds(idx, fromSubject || fromId, { requestedId: requestedFrom, typeFilter: fromSubject?.t });
  const toLookupIds = subjectReferenceIds(idx, toSubject || toId, { requestedId: requestedTo, typeFilter: toSubject?.t });
  const fromGraphId = fromLookupIds.find((id) => Array.isArray(byNode[id]) && byNode[id].length) || fromId;
  const toGraphId = toLookupIds.find((id) => Array.isArray(byNode[id]) && byNode[id].length) || toId;
  if (fromGraphId === toGraphId) return empty("same_node");

  const cap = Math.max(2, Math.min(7, parseInt(maxDepth) || 6));
  const MAX_NODES = 60000;

  // parent maps: node -> the node it was discovered from on that side.
  const pf = new Map([[fromGraphId, null]]);
  const pb = new Map([[toGraphId, null]]);
  let ff = [fromGraphId], fb = [toGraphId];
  let meet = "";
  let visited = 2;

  for (let depth = 0; depth < cap && !meet; depth += 1) {
    const expandForward = ff.length <= fb.length;
    const front = expandForward ? ff : fb;
    const parent = expandForward ? pf : pb;
    const other = expandForward ? pb : pf;
    const next = [];
    for (const node of front) {
      const rows = byNode[node];
      if (!Array.isArray(rows)) continue;
      for (const r of rows) {
        const u = text(r.u);
        if (!u || parent.has(u)) continue;
        parent.set(u, node);
        if (other.has(u)) { meet = u; break; }
        next.push(u);
        if ((visited += 1) > MAX_NODES) return empty("search_truncated");
      }
      if (meet) break;
    }
    if (expandForward) ff = next; else fb = next;
    if (!ff.length || !fb.length) break;
  }
  if (!meet) return empty("no_path");

  // Reconstruct: from .. meet (via pf) then meet .. to (via pb).
  const left = [];
  for (let n = meet; n != null; n = pf.get(n)) left.push(n);
  left.reverse();
  const right = [];
  for (let n = pb.get(meet); n != null; n = pb.get(n)) right.push(n);
  const ids = [...left, ...right];

  const path = ids.map((id) => publicSubjectResolved(idx, id)).filter((s) => s.id);
  const edges = [];
  for (let i = 0; i + 1 < ids.length; i += 1) {
    const a = ids[i], b = ids[i + 1];
    const row = (byNode[a] || []).find((r) => text(r.u) === b)
      || (byNode[b] || []).find((r) => text(r.u) === a) || {};
    edges.push(omitUndefinedFields({
      source: path[i]?.id || a,
      target: path[i + 1]?.id || b,
      relationType: text(row.rt) || "collab",
      weight: Number(row.w) || 0,
      sourceGraphId: a !== path[i]?.id ? a : undefined,
      targetGraphId: b !== path[i + 1]?.id ? b : undefined,
    }));
  }

  return {
    schemaVersion: "atlas_miniapp.path_response.v1",
    query: {
      from: fromId,
      to: toId,
      requestedFrom: requestedFrom && requestedFrom !== fromId ? requestedFrom : undefined,
      requestedTo: requestedTo && requestedTo !== toId ? requestedTo : undefined,
    }, found: true,
    hops: edges.length, path, edges,
    generation: publicAtlasGeneration(idx, bundle),
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
  const requestedId = text(id);
  const resolved = resolveSubjectReference(idx, requestedId);
  const s = resolved?.subject || null;
  if (!s) return { found: false, id, reason: "not_found" };
  return {
    schemaVersion: "atlas_miniapp.entity_response.v1",
    found: true,
    entity: s,
    requestedSubjectId: requestedId && requestedId !== s.i ? requestedId : undefined,
    resolvedVia: resolved?.resolvedVia,
  };
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

export async function getStarmapLens({ name, subjectId } = {}) {
  const bundle = await loadStarmapLenses();
  const lensName = text(name || "future");
  if (!bundle) {
    return {
      schemaVersion: "atlas_miniapp.starmap_lens_response.v1",
      found: false,
      lens: lensName,
      reason: "lens_unavailable",
    };
  }
  const lenses = bundle.lenses || {};
  const data = lenses[lensName];
  if (!data) {
    return {
      schemaVersion: "atlas_miniapp.starmap_lens_response.v1",
      found: false,
      lens: lensName,
      reason: "lens_not_found",
      available: Object.keys(lenses).sort(),
    };
  }
  if (lensName === "subject") {
    const requestedId = text(subjectId);
    let id = requestedId;
    const subjects = data.subjects || {};
    let idx = null;
    let resolved = null;
    let lookupIds = uniqueTextValues(id);
    if (id) {
      idx = await loadIndex();
      resolved = idx ? resolveSubjectReference(idx, id) : null;
      if (resolved) {
        id = resolved.canonicalId;
        lookupIds = subjectReferenceIds(idx, resolved.subject, { requestedId });
      }
    }
    let subject = id ? firstValueByIds(subjects, lookupIds) || subjects[id] || null : null;
    let sourceFallback = "";
    if (id && !subject) {
      idx = idx || await loadIndex();
      const s = idx ? subjectById(idx, id) : null;
      if (s) {
        subject = {
          id: s.i,
          type: s.t,
          name: s.n,
          city: s.c || "",
          eventCount: s.ec || 0,
        };
        sourceFallback = "atlas_index";
      }
    }
    if (subject && subject.id && subject.id !== id) {
      subject = { ...subject, id };
    }
    return {
      schemaVersion: "atlas_miniapp.starmap_lens_response.v1",
      found: !id || Boolean(subject),
      lens: lensName,
      subjectId: id || null,
      requestedSubjectId: requestedId && requestedId !== id ? requestedId : undefined,
      generatedAt: bundle.generatedAt || "",
      source: bundle.source || {},
      counts: bundle.counts || {},
      data: id ? (subject || null) : data,
      sourceFallback: sourceFallback || undefined,
      reason: id && !subject ? "subject_not_found" : undefined,
    };
  }
  return {
    schemaVersion: "atlas_miniapp.starmap_lens_response.v1",
    found: true,
    lens: lensName,
    generatedAt: data?.generatedAt || bundle.generatedAt || "",
    source: data?.source || bundle.source || {},
    counts: data?.counts || bundle.counts || {},
    data,
  };
}

export async function getRadioExternalLinks({ stationKey } = {}) {
  const bundle = await loadRadioExternalLinks();
  const key = text(stationKey).toLowerCase();
  if (!bundle) {
    return {
      schemaVersion: "atlas_miniapp.radio_external_links_response.v1",
      found: false,
      reason: "radio_external_links_unavailable",
      stationKey: key || null,
      stations: [],
    };
  }
  const stations = Array.isArray(bundle.stations) ? bundle.stations : [];
  const filtered = key ? stations.filter((station) => text(station.stationKey).toLowerCase() === key) : stations;
  return {
    schemaVersion: "atlas_miniapp.radio_external_links_response.v1",
    found: key ? filtered.length > 0 : true,
    reason: key && filtered.length === 0 ? "station_not_found" : undefined,
    stationKey: key || null,
    generatedAt: bundle.generatedAt || "",
    candidateOnly: bundle.candidateOnly === true,
    productionWriteExecuted: bundle.productionWriteExecuted === true,
    oldDatabaseRowsUsed: Number(bundle.oldDatabaseRowsUsed || 0),
    source: bundle.source || {},
    hotlinkPolicy: bundle.hotlinkPolicy || {},
    counts: bundle.counts || {},
    stations: filtered,
    available: key && filtered.length === 0 ? stations.map((station) => station.stationKey).filter(Boolean).sort() : undefined,
  };
}

export async function getRadioPrograms({ stationKey, djId, limit, includeReviewOnly } = {}) {
  const [bundle, matchReview, idx] = await Promise.all([loadRadioPrograms(), loadRadioProgramMatchReview(), loadIndex()]);
  const key = text(stationKey).toLowerCase();
  const requestedId = text(djId);
  const resolved = requestedId ? resolveSubjectReference(idx, requestedId, { typeFilter: "dj" }) : null;
  const id = resolved?.canonicalId || requestedId;
  const lookupIds = resolved
    ? subjectReferenceIds(idx, resolved.subject, { requestedId, typeFilter: "dj" })
    : uniqueTextValues(id);
  const maxItems = Math.max(1, parseInt(limit) || 50);
  if (!bundle) {
    return {
      schemaVersion: "atlas_miniapp.radio_programs_response.v1",
      found: false,
      reason: "radio_programs_unavailable",
      stationKey: key || null,
      djId: id || null,
      requestedDjId: requestedId && requestedId !== id ? requestedId : undefined,
      programs: [],
    };
  }
  let programs = Array.isArray(bundle.programs) ? bundle.programs : [];
  if (key) programs = programs.filter((program) => text(program.stationKey).toLowerCase() === key);
  if (id) programs = radioProgramsForDjFromBundle(
    { ...bundle, programs },
    lookupIds,
    maxItems,
    matchReview,
    { includeReviewOnly: includeReviewOnly === true || text(includeReviewOnly) === "1" || text(includeReviewOnly).toLowerCase() === "true" }
  );
  else programs = programs.map(normalizeRadioProgram).filter(Boolean).slice(0, maxItems);
  return {
    schemaVersion: "atlas_miniapp.radio_programs_response.v1",
    found: programs.length > 0,
    reason: programs.length === 0 ? "programs_not_found" : undefined,
    stationKey: key || null,
    djId: id || null,
    requestedDjId: requestedId && requestedId !== id ? requestedId : undefined,
    resolvedVia: resolved?.resolvedVia,
    generatedAt: bundle.generatedAt || "",
    candidateOnly: bundle.candidateOnly === true,
    productionWriteExecuted: bundle.productionWriteExecuted === true,
    oldDatabaseRowsUsed: Number(bundle.oldDatabaseRowsUsed || 0),
    source: bundle.source || {},
    hotlinkPolicy: bundle.hotlinkPolicy || {},
    counts: bundle.counts || {},
    matchReview: matchReview?.candidateOnly === true && matchReview?.productionWriteExecuted !== true ? {
      available: true,
      schemaVersion: text(matchReview.schemaVersion),
      generatedAt: text(matchReview.generatedAt),
      counts: matchReview.counts || {},
      defaultPolicy: "safe_display_only_for_dj_detail",
    } : { available: false },
    programs,
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
export async function getArtistById(djId, {
  eventLimit,
  eventOffset,
  collaboratorLimit,
  collaboratorOffset,
  venueLimit,
  venueOffset,
} = {}) {
  const idx = await loadIndex();
  if (!idx) return { found: false, query: djId, reason: "index_unavailable" };

  const id = text(djId);
  if (!id) return { found: false, query: "", reason: "missing_id" };

  const resolved = resolveSubjectReference(idx, id, { typeFilter: "dj" });
  const s = resolved?.subject || null;
  if (!s || s.t !== "dj") return {
    schemaVersion: "atlas_miniapp.artist_response.v1",
    query: id, found: false, reason: "not_found",
    profile: null, events: [], collaborators: [], venues: [],
  };

  const canonicalId = s.i;
  const lookupIds = subjectReferenceIds(idx, s, { requestedId: id, typeFilter: "dj" });
  const { profile, social, bioAtoms, relatedColumns } = artistPayloadParts(idx, s, canonicalId);
  const [radioPrograms, relationTrajectory, djOutlinks, similarDjs, bioMap, snippetMap, clusterMap, nb] = await Promise.all([
    radioProgramsForDj(lookupIds),
    relationTrajectoryForDj(lookupIds),
    externalLinksForDj(lookupIds),
    similarDjsForDj(lookupIds, 8),
    loadBioCandidates(),
    loadBioSnippets(),
    loadSceneClusters(),
    loadAlignedNeighborhoodBundle(idx),
  ]);
  profile.radioPrograms = radioPrograms;
  if (relationTrajectory) profile.relationTrajectory = relationTrajectory;
  if (djOutlinks.length) profile.externalLinks = djOutlinks;
  profile.similarDjs = similarDjs;
  if (!profile.bio) {
    const snippet = firstValueByIds(snippetMap, lookupIds);
    const bio = firstValueByIds(bioMap, lookupIds);
    if (snippet) {
      profile.bioCandidate = snippet.draft || null;
      profile.bioCandidateSource = snippet.bioSource || null;
    } else if (bio) {
      profile.bioCandidate = bio.draft || null;
    }
  }
  profile.sceneCluster = sceneClusterForDj(idx, clusterMap, lookupIds, 6);
  profile.residentVenues = residentVenuesForDj(idx, nb, lookupIds, 4);
  profile.labelAffiliations = labelAffiliationsForDj(idx, nb, lookupIds, 3);

  const eventPage = artistListPage(
    idx.events[canonicalId], eventLimit, eventOffset, ARTIST_LIST_PAGE_LIMITS.events, profile.eventCount,
  );
  const venuePage = artistListPage(
    idx.dj_venues[canonicalId], venueLimit, venueOffset, ARTIST_LIST_PAGE_LIMITS.venues, profile.venueCount,
  );
  const collaboratorPage = artistListPage(
    idx.collabs[canonicalId],
    collaboratorLimit,
    collaboratorOffset,
    ARTIST_LIST_PAGE_LIMITS.collaborators,
    profile.collaboratorCount,
  );

  return {
    schemaVersion: "atlas_miniapp.artist_response.v1",
    query: id, found: true,
    subjectId: canonicalId,
    canonicalSubjectId: canonicalId,
    requestedSubjectId: id !== canonicalId ? id : undefined,
    resolvedVia: resolved?.resolvedVia,
    profile,
    events: eventPage.items.map(e => ({ eventId: e.eid, title: e.t, date: e.d || null, venueName: e.v || null, city: e.ci || null, ...publicSourceFields(idx, e.sr) })),
    venues: venuePage.items.map(v => ({ venueName: v.vn, eventCount: v.ec })),
    collaborators: collaboratorPage.items.map(c => ({ djId: c.di, displayName: c.n, sameEventCount: c.ec })),
    pagination: {
      events: eventPage.pagination,
      venues: venuePage.pagination,
      collaborators: collaboratorPage.pagination,
    },
    social,
    bioAtoms,
    relatedColumns,
    radioPrograms,
    relationTrajectory,
    generation: publicAtlasGeneration(idx, nb),
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
