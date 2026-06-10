import { createReadStream } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { createGunzip } from "node:zlib";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_STAGE7_ROOT = path.resolve(moduleDir, "../data/stage7_atlas");
const DEFAULT_POINTER = path.resolve(
  DEFAULT_STAGE7_ROOT,
  "release_pointer.staging.json",
);
const DEFAULT_RECOMMENDATIONS = path.resolve(
  DEFAULT_STAGE7_ROOT,
  "recommendations.json",
);
const DEFAULT_GRAPH_RAG_ANSWERS = path.resolve(
  DEFAULT_STAGE7_ROOT,
  "graph_rag_answer_drafts.jsonl",
);
const DEFAULT_VECTOR_ROUTER_SMOKE = path.resolve(
  DEFAULT_STAGE7_ROOT,
  "vector_collection_router_smoke.json",
);
const DEFAULT_IDENTITY_REVIEW = path.resolve(
  DEFAULT_STAGE7_ROOT,
  "identity_review_workbench.json",
);
const KIND_TO_FILE = {
  articles: "articles",
  entities: "entities",
  events: "events",
};
const DETAIL_ID_FIELDS = {
  articles: ["article_id", "article_uid"],
  entities: ["eid"],
  events: ["evid"],
};

function normalizeLimit(value, fallback = 20, max = 100) {
  const parsed = Number.parseInt(String(value ?? fallback), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(parsed, 1), max);
}

function normalizeCursor(value) {
  const parsed = Number.parseInt(String(value ?? "0"), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function text(value) {
  return String(value || "").trim();
}

function textPreview(value, maxLength = 700) {
  const normalized = text(value).replace(/\s+/g, " ");
  if (!normalized) return "";
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 3)}...` : normalized;
}

function firstText(values) {
  for (const value of values) {
    const candidate = text(value);
    if (candidate) return candidate;
  }
  return "";
}

function rowTitle(row) {
  return firstText([row.title, row.name, row.article_uid, row.source_article_uid, row.eid, row.evid, row.article_id]);
}

function primaryDetailId(row, kind) {
  const fields = DETAIL_ID_FIELDS[kind] || [];
  for (const field of fields) {
    const value = text(row[field]);
    if (value) return value;
  }
  return "";
}

function matchingDetailIdField(row, kind, id) {
  const target = text(id);
  if (!target) return "";
  const fields = DETAIL_ID_FIELDS[kind] || [];
  for (const field of fields) {
    if (text(row[field]) === target) return field;
  }
  return "";
}

function searchableText(row) {
  return [
    row.title,
    row.name,
    row.article_uid,
    row.source_article_uid,
    row.source_account,
    row.vector_text,
    row.place,
    row.type,
    ...(Array.isArray(row.participants) ? row.participants : []),
    ...(Array.isArray(row.organizers) ? row.organizers : []),
    ...(Array.isArray(row.aliases) ? row.aliases : []),
  ]
    .map(text)
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function compactRow(row, kind) {
  if (kind === "articles") {
    return {
      article_id: row.article_id || "",
      article_uid: row.article_uid || "",
      title: row.title || "",
      source_account: row.source_account || "",
      publish_time_status: row.publish_time_status || "",
      entity_count: row.entity_count || 0,
      event_count: row.event_count || 0,
      quality_grade: row.quality_grade || "",
    };
  }
  if (kind === "entities") {
    return {
      eid: row.eid || "",
      name: row.name || "",
      type: row.type || "",
      city: row.city || "",
      source_article_uid: row.source_article_uid || "",
      confidence: row.confidence ?? null,
    };
  }
  return {
    evid: row.evid || "",
    name: row.name || "",
    place: row.place || "",
    time_iso: row.time_iso || "",
    time_text: row.time_text || "",
    participants: Array.isArray(row.participants) ? row.participants.slice(0, 20) : [],
    source_article_uid: row.source_article_uid || "",
    confidence: row.confidence ?? null,
  };
}

function normalizeFacetValue(value) {
  const raw = text(value);
  if (!raw || raw.toLowerCase() === "unknown") return "";
  return raw;
}

function addFacet(map, value) {
  const label = normalizeFacetValue(value);
  if (!label) return;
  map.set(label, (map.get(label) || 0) + 1);
}

function topFacets(rows, selector, limit = 12) {
  const map = new Map();
  for (const row of rows) {
    const values = selector(row);
    for (const value of Array.isArray(values) ? values : [values]) {
      addFacet(map, value);
    }
  }
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hans-CN"))
    .slice(0, limit)
    .map(([label, count]) => ({ label, count }));
}

function entityMatchesType(row, patterns) {
  const haystack = [row.type, row.name, row.vector_text].map(text).join(" ").toLowerCase();
  return patterns.some((pattern) => haystack.includes(pattern));
}

function compactRecommendation(row) {
  return {
    id: row.id || "",
    type: row.type || "",
    title: row.title || row.name || "",
    score: row.score ?? row.final_score ?? null,
  };
}

function compactGraphRagAnswer(row) {
  return {
    id: row.id || "",
    query: row.query || "",
    answer: row.answer || "",
    citations: Array.isArray(row.citations) ? row.citations.slice(0, 5) : [],
    citation_count: row.citation_count ?? (Array.isArray(row.citations) ? row.citations.length : 0),
  };
}

function compactIdentityReviewItem(row) {
  return {
    id: row.id || "",
    queue: row.queue || "",
    bucket: row.bucket || "",
    status: row.status || "",
    subjectName: row.subjectName || "",
    subjectType: row.subjectType || "",
    url: row.url || "",
    domain: row.domain || "",
    sourceAccount: row.sourceAccount || "",
    sourceArticleUid: row.sourceArticleUid || "",
    sourceTitle: row.sourceTitle || "",
    supportCount: row.supportCount || 0,
    identitySignalScore: row.identitySignalScore ?? null,
    reviewReason: row.reviewReason || "",
    nextActions: Array.isArray(row.nextActions) ? row.nextActions.slice(0, 6) : [],
    signals: row.signals && typeof row.signals === "object" ? row.signals : {},
    acceptedForGraph: Boolean(row.acceptedForGraph),
    identityProof: Boolean(row.identityProof),
    graphWriteAllowed: Boolean(row.graphWriteAllowed),
  };
}

function publicEvidence(row, kind) {
  return {
    kind,
    title: row.title || row.name || "",
    sourceArticleUid: row.source_article_uid || row.article_uid || "",
    sourceAccount: row.source_account || "",
    publishTimeStatus: row.publish_time_status || "",
    qualityGrade: row.quality_grade || "",
    type: row.type || "",
    city: row.city || "",
    place: row.place || "",
    timeIso: row.time_iso || "",
    timeText: row.time_text || "",
    aliases: Array.isArray(row.aliases) ? row.aliases.slice(0, 20) : [],
    participants: Array.isArray(row.participants) ? row.participants.slice(0, 30) : [],
    organizers: Array.isArray(row.organizers) ? row.organizers.slice(0, 20) : [],
    vectorTextPreview: textPreview(row.vector_text),
  };
}

function jsonlReader(filePath) {
  const stream = filePath.endsWith(".gz")
    ? createReadStream(filePath).pipe(createGunzip())
    : createReadStream(filePath, { encoding: "utf8" });
  return createInterface({
    input: stream,
    crlfDelay: Number.POSITIVE_INFINITY,
  });
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

function parseJsonlLine(line) {
  try {
    return JSON.parse(line);
  } catch {
    return null;
  }
}

async function readJsonl(filePath, limit = 50) {
  const rows = [];
  const reader = jsonlReader(filePath);
  for await (const line of reader) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const row = parseJsonlLine(trimmed);
    if (!row) continue;
    rows.push(row);
    if (rows.length >= limit) break;
  }
  return rows;
}

export class Stage7AtlasStore {
  constructor(options = {}) {
    const env = options.env || process.env;
    this.stage7Root = options.stage7Root || env.STAGE7_ATLAS_ROOT || DEFAULT_STAGE7_ROOT;
    this.pointerPath = options.stage7AtlasPointer || env.STAGE7_ATLAS_POINTER || DEFAULT_POINTER;
    this.recommendationsPath = options.stage7RecommendationsPath || env.STAGE7_RECOMMENDATIONS_PATH || DEFAULT_RECOMMENDATIONS;
    this.graphRagAnswersPath = options.stage7GraphRagAnswersPath || env.STAGE7_GRAPH_RAG_ANSWERS_PATH || DEFAULT_GRAPH_RAG_ANSWERS;
    this.vectorRouterSmokePath =
      options.stage7VectorRouterSmokePath || env.STAGE7_VECTOR_ROUTER_SMOKE_PATH || DEFAULT_VECTOR_ROUTER_SMOKE;
    this.identityReviewPath = options.stage7IdentityReviewPath || env.STAGE7_IDENTITY_REVIEW_PATH || DEFAULT_IDENTITY_REVIEW;
    this.pointer = null;
    this.vectorRouterReport = null;
    this.identityReview = null;
  }

  async loadPointer() {
    if (!this.pointer) {
      this.pointer = await readJson(this.pointerPath);
    }
    return this.pointer;
  }

  resolveReleasePath(rawPath) {
    if (!rawPath) return "";
    if (path.isAbsolute(rawPath)) return rawPath;
    return path.resolve(this.stage7Root, rawPath);
  }

  async fileForKind(kind) {
    const pointer = await this.loadPointer();
    const fileKey = KIND_TO_FILE[kind];
    const entry = pointer.files?.[fileKey];
    if (!entry?.path) return "";
    return this.resolveReleasePath(entry.path);
  }

  async getManifest() {
    const pointer = await this.loadPointer();
    return {
      schemaVersion: "stage7_atlas_api.manifest.v1",
      releaseReady: Boolean(pointer.release_ready),
      decision: pointer.decision || "",
      channel: pointer.channel || "",
      generatedAt: pointer.generated_at || null,
      counts: pointer.counts || {},
      publishTimePolicy: pointer.publish_time_policy || {},
      files: Object.fromEntries(
        Object.entries(pointer.files || {}).map(([key, value]) => [
          key,
          {
            bytes: value.bytes || 0,
            sha256: value.sha256 || "",
          },
        ]),
      ),
    };
  }

  async getOverview({ sampleLimit } = {}) {
    const rowLimit = normalizeLimit(sampleLimit, 80, 160);
    const manifest = await this.getManifest();
    const [articleFile, entityFile, eventFile] = await Promise.all([
      this.fileForKind("articles"),
      this.fileForKind("entities"),
      this.fileForKind("events"),
    ]);
    const [articleRows, entityRows, eventRows, recommendations, graphRag, vector] = await Promise.all([
      readJsonl(articleFile, rowLimit),
      readJsonl(entityFile, rowLimit),
      readJsonl(eventFile, rowLimit),
      this.getRecommendations({ limit: 8 }),
      this.getGraphRagAnswers({ limit: 4 }),
      this.getVectorRouterStatus(),
    ]);
    const compactEntities = entityRows.map((row) => compactRow(row, "entities"));
    const people = compactEntities
      .filter((row) => entityMatchesType(row, ["person", "artist", "dj", "musician", "performer", "人物", "艺术家", "艺人"]))
      .slice(0, 12);
    const labels = compactEntities
      .filter((row) => entityMatchesType(row, ["label", "collective", "crew", "promoter", "organization", "厂牌", "组织", "club"]))
      .slice(0, 12);
    const venues = compactEntities
      .filter((row) => entityMatchesType(row, ["venue", "club", "space", "场地", "俱乐部"]))
      .slice(0, 12);
    const compactEvents = eventRows.map((row) => compactRow(row, "events"));
    const mapPlaces = topFacets([...entityRows, ...eventRows], (row) => [row.city, row.place]);
    return {
      schemaVersion: "stage7_atlas_api.overview.v1",
      generatedAt: new Date().toISOString(),
      release: {
        releaseReady: manifest.releaseReady,
        decision: manifest.decision,
        channel: manifest.channel,
        generatedAt: manifest.generatedAt,
      },
      counts: manifest.counts,
      publishTimePolicy: manifest.publishTimePolicy,
      facets: {
        cities: topFacets(entityRows, (row) => [row.city, row.place]),
        mapPlaces,
        entityTypes: topFacets(entityRows, (row) => row.type),
        eventPlaces: topFacets(eventRows, (row) => row.place),
        sourceAccounts: topFacets(articleRows, (row) => row.source_account),
      },
      browsingSurfaces: [
        { id: "map", label: "地图", count: mapPlaces.length, samples: mapPlaces },
        { id: "people", label: "人物", count: people.length, samples: people },
        { id: "labels", label: "厂牌", count: labels.length, samples: labels },
        { id: "venues", label: "场地", count: venues.length, samples: venues },
        { id: "scenes", label: "场景", count: compactEvents.length, samples: compactEvents.slice(0, 12) },
      ],
      samples: {
        articles: articleRows.slice(0, 12).map((row) => compactRow(row, "articles")),
        entities: compactEntities.slice(0, 12),
        events: compactEvents.slice(0, 12),
      },
      recommendations: (recommendations.recommendations || []).slice(0, 8).map(compactRecommendation),
      graphRagAnswers: (graphRag.answers || []).slice(0, 4).map(compactGraphRagAnswer),
      vector: {
        ok: vector.ok,
        decision: vector.decision,
        sampleSizePerCollection: vector.sampleSizePerCollection,
        topK: vector.topK,
      },
      serviceIntegration: {
        liveVectorSearchEnabled: false,
        searchMode: "materialized_text_scan",
        overviewSampleLimit: rowLimit,
      },
      safety: {
        modelCallExecuted: false,
        llmCallExecuted: false,
        qdrantWriteExecuted: false,
        qdrantAliasChangeExecuted: false,
        neo4jWriteExecuted: false,
        mem0WriteExecuted: false,
      },
    };
  }

  async loadIdentityReview() {
    if (!this.identityReview) {
      this.identityReview = await readJson(this.identityReviewPath);
    }
    return this.identityReview;
  }

  async getIdentityReview({ limit, queue, bucket, domain } = {}) {
    const payload = await this.loadIdentityReview();
    const pageLimit = normalizeLimit(limit, 50, 200);
    const queueFilter = text(queue);
    const bucketFilter = text(bucket);
    const domainFilter = text(domain).toLowerCase();
    const allItems = Array.isArray(payload.items) ? payload.items : [];
    const filtered = allItems.filter((item) => {
      if (queueFilter && item.queue !== queueFilter) return false;
      if (bucketFilter && item.bucket !== bucketFilter) return false;
      if (domainFilter && text(item.domain).toLowerCase() !== domainFilter) return false;
      return true;
    });
    return {
      schemaVersion: "stage7_atlas_api.identity_review_response.v1",
      generatedAt: payload.generatedAt || null,
      decision: payload.decision || "",
      summary: payload.summary || {},
      sourceReports: payload.sourceReports || [],
      facets: payload.facets || {},
      filters: {
        queue: queueFilter || null,
        bucket: bucketFilter || null,
        domain: domainFilter || null,
      },
      page: {
        limit: pageLimit,
        total: filtered.length,
        returned: Math.min(filtered.length, pageLimit),
      },
      items: filtered.slice(0, pageLimit).map(compactIdentityReviewItem),
      safety: {
        reportOnly: Boolean(payload.safety?.reportOnly ?? true),
        networkCallExecuted: Boolean(payload.safety?.networkCallExecuted),
        modelCallExecuted: Boolean(payload.safety?.modelCallExecuted),
        graphWriteExecuted: Boolean(payload.safety?.graphWriteExecuted),
        qdrantWriteExecuted: Boolean(payload.safety?.qdrantWriteExecuted),
        sqliteWriteExecuted: Boolean(payload.safety?.sqliteWriteExecuted),
        mem0WriteExecuted: Boolean(payload.safety?.mem0WriteExecuted),
        paidApiUsed: Boolean(payload.safety?.paidApiUsed),
        cookieOrTokenExported: Boolean(payload.safety?.cookieOrTokenExported),
        dScanExecuted: Boolean(payload.safety?.dScanExecuted),
      },
    };
  }

  async loadVectorRouterReport() {
    if (!this.vectorRouterReport) {
      this.vectorRouterReport = await readJson(this.vectorRouterSmokePath);
    }
    return this.vectorRouterReport;
  }

  async getVectorRouterStatus() {
    const report = await this.loadVectorRouterReport();
    const channelProbeSummary = {};
    for (const [channel, probes] of Object.entries(report.channel_probes || {})) {
      channelProbeSummary[channel] = (Array.isArray(probes) ? probes : []).map((probe) => ({
        kind: probe.kind || "",
        collection: probe.collection || "",
        checked: probe.checked || 0,
        matched: probe.matched || 0,
        matchRate: probe.match_rate ?? null,
      }));
    }
    return {
      schemaVersion: "stage7_atlas_api.vector_router_status.v1",
      ok: Boolean(report.ok),
      decision: report.decision || "",
      generatedAt: report.generated_at || null,
      sampleSizePerCollection: report.sample_size_per_collection || 0,
      topK: report.top_k || 0,
      collectionGroups: report.collection_groups || {},
      channelProbeSummary,
      routerCases: (report.router_cases || []).map((item) => ({
        id: item.id || "",
        lang: item.lang || "",
        routedChannels: item.routed_channels || [],
        fusedCount: Array.isArray(item.fused) ? item.fused.length : 0,
      })),
      safety: {
        modelLoaded: Boolean(report.safety?.model_loaded),
        embeddingCallExecuted: Boolean(report.safety?.embedding_call_executed),
        qdrantWriteExecuted: Boolean(report.safety?.qdrant_write_executed),
        qdrantAliasChangeExecuted: Boolean(report.safety?.qdrant_alias_change_executed),
        productionPublishExecuted: Boolean(report.safety?.production_publish_executed),
      },
      serviceIntegration: {
        liveVectorSearchEnabled: false,
        searchMode: "materialized_text_scan",
        note: "Vector router status is report-backed; this CloudRun service does not connect to local Qdrant.",
      },
    };
  }

  async listKind(kind, { limit, cursor, q } = {}) {
    if (!KIND_TO_FILE[kind]) {
      throw new Error(`Unsupported Stage7 atlas kind: ${kind}`);
    }
    const filePath = await this.fileForKind(kind);
    const pageLimit = normalizeLimit(limit);
    const pageCursor = normalizeCursor(cursor);
    const query = text(q).toLowerCase();
    const items = [];
    let matched = 0;
    let scanned = 0;
    const reader = jsonlReader(filePath);
    for await (const line of reader) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      scanned += 1;
      if (query && !trimmed.toLowerCase().includes(query)) continue;
      if (matched < pageCursor) {
        matched += 1;
        continue;
      }
      const row = parseJsonlLine(trimmed);
      if (!row) continue;
      if (query && !searchableText(row).includes(query)) continue;
      items.push(compactRow(row, kind));
      matched += 1;
      if (items.length >= pageLimit) break;
    }
    return {
      schemaVersion: "stage7_atlas_api.list_response.v1",
      kind,
      query: query || null,
      page: {
        limit: pageLimit,
        cursor: String(pageCursor),
        nextCursor: items.length >= pageLimit ? String(pageCursor + items.length) : null,
        scanned,
      },
      items,
    };
  }

  async findKindRow(kind, id) {
    if (!KIND_TO_FILE[kind]) {
      throw new Error(`Unsupported Stage7 atlas kind: ${kind}`);
    }
    const target = text(id);
    if (!target) return { row: null, scanned: 0, matchedBy: "" };
    const filePath = await this.fileForKind(kind);
    const reader = jsonlReader(filePath);
    let scanned = 0;
    for await (const line of reader) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      scanned += 1;
      const row = parseJsonlLine(trimmed);
      if (!row) continue;
      const matchedBy = matchingDetailIdField(row, kind, target);
      if (matchedBy) return { row, scanned, matchedBy };
    }
    return { row: null, scanned, matchedBy: "" };
  }

  async collectBySourceArticle(kind, sourceArticleUid, { limit } = {}) {
    if (!KIND_TO_FILE[kind]) {
      throw new Error(`Unsupported Stage7 atlas kind: ${kind}`);
    }
    const sourceUid = text(sourceArticleUid);
    if (!sourceUid) return { items: [], scanned: 0 };
    const pageLimit = normalizeLimit(limit, 12, 50);
    const filePath = await this.fileForKind(kind);
    const reader = jsonlReader(filePath);
    const items = [];
    let scanned = 0;
    for await (const line of reader) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      scanned += 1;
      if (!trimmed.includes(sourceUid)) continue;
      const row = parseJsonlLine(trimmed);
      if (!row) continue;
      if (text(row.source_article_uid) !== sourceUid) continue;
      items.push(compactRow(row, kind));
      if (items.length >= pageLimit) break;
    }
    return { items, scanned };
  }

  async getDetail(kind, id, { relatedLimit } = {}) {
    if (!KIND_TO_FILE[kind]) {
      throw new Error(`Unsupported Stage7 atlas kind: ${kind}`);
    }
    const pageLimit = normalizeLimit(relatedLimit, 12, 50);
    const found = await this.findKindRow(kind, id);
    if (!found.row) return null;
    const sourceArticleUid =
      kind === "articles" ? text(found.row.article_uid || found.row.source_article_uid) : text(found.row.source_article_uid);
    let sourceArticle = null;
    let sourceArticleScanned = 0;
    if (kind !== "articles" && sourceArticleUid) {
      const sourceFound = await this.findKindRow("articles", sourceArticleUid);
      sourceArticleScanned = sourceFound.scanned;
      sourceArticle = sourceFound.row ? compactRow(sourceFound.row, "articles") : null;
    }
    const [relatedEntities, relatedEvents] = await Promise.all([
      kind === "entities"
        ? Promise.resolve({ items: [], scanned: 0 })
        : this.collectBySourceArticle("entities", sourceArticleUid, { limit: pageLimit }),
      kind === "events"
        ? Promise.resolve({ items: [], scanned: 0 })
        : this.collectBySourceArticle("events", sourceArticleUid, { limit: pageLimit }),
    ]);
    return {
      schemaVersion: "stage7_atlas_api.detail_response.v1",
      kind,
      id: text(id),
      matchedBy: found.matchedBy,
      primaryId: primaryDetailId(found.row, kind),
      title: rowTitle(found.row),
      item: compactRow(found.row, kind),
      evidence: publicEvidence(found.row, kind),
      related: {
        sourceArticle,
        entities: relatedEntities.items,
        events: relatedEvents.items,
      },
      lookup: {
        sourceArticleUid,
        detailRowsScanned: found.scanned,
        sourceArticleRowsScanned: sourceArticleScanned,
        relatedEntityRowsScanned: relatedEntities.scanned,
        relatedEventRowsScanned: relatedEvents.scanned,
        relatedLimit: pageLimit,
      },
      safety: {
        reportOnly: true,
        modelCallExecuted: false,
        llmCallExecuted: false,
        networkCallExecuted: false,
        qdrantWriteExecuted: false,
        qdrantAliasChangeExecuted: false,
        neo4jWriteExecuted: false,
        sqliteWriteExecuted: false,
        mem0WriteExecuted: false,
      },
    };
  }

  async search({ q, limit } = {}) {
    const query = text(q).toLowerCase();
    if (!query) {
      return {
        schemaVersion: "stage7_atlas_api.search_response.v1",
        query: "",
        results: [],
        error: "MISSING_QUERY",
      };
    }
    const pageLimit = normalizeLimit(limit, 20, 50);
    const perKindLimit = Math.max(1, Math.ceil(pageLimit / 3));
    const results = [];
    for (const kind of ["articles", "entities", "events"]) {
      const response = await this.listKind(kind, { q: query, limit: perKindLimit, cursor: 0 });
      for (const item of response.items) {
        results.push({
          kind,
          title: rowTitle(item),
          item,
        });
      }
    }
    return {
      schemaVersion: "stage7_atlas_api.search_response.v1",
      query,
      retrieval: {
        mode: "materialized_text_scan",
        liveVectorSearchEnabled: false,
      },
      resultCount: results.slice(0, pageLimit).length,
      results: results.slice(0, pageLimit),
    };
  }

  async getRecommendations({ limit } = {}) {
    const payload = await readJson(this.recommendationsPath);
    const pageLimit = normalizeLimit(limit, 20, 50);
    return {
      schemaVersion: "stage7_atlas_api.recommendations_response.v1",
      decision: payload.decision || "",
      generatedAt: payload.generated_at || null,
      recommendationCount: payload.recommendation_count || 0,
      diversityRatio: payload.diversity_ratio ?? null,
      safety: {
        modelCallExecuted: Boolean(payload.safety?.model_call_executed),
        mem0WriteExecuted: Boolean(payload.safety?.mem0_write_executed),
      },
      recommendations: (payload.recommendations || []).slice(0, pageLimit),
    };
  }

  async getGraphRagAnswers({ limit } = {}) {
    const pageLimit = normalizeLimit(limit, 10, 50);
    const answers = await readJsonl(this.graphRagAnswersPath, pageLimit);
    return {
      schemaVersion: "stage7_atlas_api.graph_rag_answers_response.v1",
      answerCount: answers.length,
      llmCallExecuted: answers.some((item) => Boolean(item.llm_call_executed)),
      answers,
    };
  }
}
