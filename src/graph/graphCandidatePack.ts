import { mkdir, readFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";

import { hasSensitivePathSegment, toPortablePath } from "../artifacts/pathSafety.js";
import { writeChecksumsFile } from "../packs/checksums.js";
import { collectFiles } from "../utils/fileDiscovery.js";
import { writeJson, writeText } from "../utils/fs.js";
import { sha256Hex } from "../utils/hash.js";

export type GraphEntityType =
  | "artist"
  | "collective"
  | "venue"
  | "promoter"
  | "event"
  | "program"
  | "label"
  | "account"
  | "organization"
  | "unknown";

export type GraphClaimType =
  | "appears_in_event"
  | "appears_on_schedule"
  | "shared_bill_with"
  | "links_to_account"
  | "published_by_source";

export type GraphRelationshipEdgeType =
  | "PERFORMS_AT"
  | "APPEARS_WITH"
  | "PUBLISHED_BY"
  | "LINKED_ACCOUNT";

export interface GraphCandidatePackOptions {
  inputDir: string;
  outDir: string;
  sourcePackId?: string;
  confidenceThreshold?: number;
  now?: () => string;
}

export interface GraphCandidatePackManifest {
  version: number;
  schema_version: string;
  generated_at: string;
  source_pack_id: string;
  input_root: string;
  output_root: string;
  row_counts: Record<string, number>;
  output_paths: Record<string, string>;
}

export interface GraphEntityCandidate {
  entity_id: string;
  entity_type: GraphEntityType;
  canonical_name: string;
  display_name: string;
  aliases: string[];
  confidence: number;
  source_article_ids: string[];
  evidence_ids: string[];
  review_status: "candidate" | "needs_review";
}

export interface GraphEvidenceSpan {
  evidence_id: string;
  article_id: string;
  excerpt: string;
  source_file: string;
  method: string;
}

export interface GraphClaimCandidate {
  claim_id: string;
  claim_type: GraphClaimType;
  subject_label: string;
  object_label: string;
  subject_entity_id: string;
  object_entity_id: string;
  confidence: number;
  evidence_ids: string[];
  source_article_id: string;
  method: string;
}

export interface GraphRelationshipCandidate {
  relationship_id: string;
  edge_type: GraphRelationshipEdgeType;
  subject_entity_id: string;
  object_entity_id: string;
  claim_ids: string[];
  evidence_ids: string[];
  confidence: number;
}

export interface GraphReviewQueueItem {
  review_id: string;
  reason: string;
  target_type: "entity" | "claim" | "relationship";
  target_id: string;
  source_article_id: string;
}

interface SourceArticleRecord {
  article_id: string;
  artifact_dir: string;
  title: string;
  source_url: string;
  account: string;
}

interface ParsedDownstreamResult {
  parsed?: unknown;
  rawText?: string;
  raw_text?: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asNumber(value: unknown, fallback = 0.5): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(1, parsed)) : fallback;
}

function normalizeName(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLowerCase();
}

function normalizeEntityType(value: unknown): GraphEntityType {
  const type = asString(value).toLowerCase();
  if (
    [
      "artist",
      "collective",
      "venue",
      "promoter",
      "event",
      "program",
      "label",
      "account",
      "organization",
      "unknown",
    ].includes(type)
  ) {
    return type as GraphEntityType;
  }
  return "unknown";
}

function normalizeClaimType(value: unknown): GraphClaimType {
  const type = asString(value).toLowerCase();
  if (
    [
      "appears_in_event",
      "appears_on_schedule",
      "shared_bill_with",
      "links_to_account",
      "published_by_source",
    ].includes(type)
  ) {
    return type as GraphClaimType;
  }
  return "appears_in_event";
}

function edgeTypeForClaim(type: GraphClaimType): GraphRelationshipEdgeType {
  if (type === "shared_bill_with") {
    return "APPEARS_WITH";
  }
  if (type === "links_to_account") {
    return "LINKED_ACCOUNT";
  }
  if (type === "published_by_source") {
    return "PUBLISHED_BY";
  }
  return "PERFORMS_AT";
}

function entityId(type: GraphEntityType, name: string): string {
  return `ent_${sha256Hex(`${type}:${normalizeName(name)}`).slice(0, 20)}`;
}

function stableId(prefix: string, parts: string[]): string {
  return `${prefix}_${sha256Hex(parts.join("\u001f")).slice(0, 20)}`;
}

async function readJsonIfExists<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

async function collectArticleDirs(inputRoot: string): Promise<string[]> {
  const llmInputs = await collectFiles(inputRoot, (filePath, fileName) => {
    return fileName === "llm_input.md" && !hasSensitivePathSegment(relative(inputRoot, filePath));
  });
  return llmInputs.map((filePath) => dirname(filePath));
}

function firstArray(value: unknown, keys: string[]): unknown[] {
  if (!isObject(value)) {
    return [];
  }
  for (const key of keys) {
    const child = value[key];
    if (Array.isArray(child)) {
      return child;
    }
  }
  return [];
}

function evidenceText(value: Record<string, unknown>): string {
  return (
    asString(value.evidence) ||
    asString(value.evidence_excerpt) ||
    asString(value.excerpt) ||
    asString(value.source_text)
  );
}

function addEvidence(options: {
  evidence: GraphEvidenceSpan[];
  articleId: string;
  sourceFile: string;
  excerpt: string;
  method: string;
}): string {
  const excerpt = options.excerpt.trim();
  if (!excerpt) {
    return "";
  }
  const evidenceId = stableId("ev", [options.articleId, excerpt, options.method]);
  if (!options.evidence.some((item) => item.evidence_id === evidenceId)) {
    options.evidence.push({
      evidence_id: evidenceId,
      article_id: options.articleId,
      excerpt,
      source_file: options.sourceFile,
      method: options.method,
    });
  }
  return evidenceId;
}

function upsertEntity(
  entities: Map<string, GraphEntityCandidate>,
  candidate: GraphEntityCandidate,
): void {
  const existing = entities.get(candidate.entity_id);
  if (!existing) {
    entities.set(candidate.entity_id, candidate);
    return;
  }
  existing.confidence = Math.max(existing.confidence, candidate.confidence);
  existing.source_article_ids = Array.from(
    new Set([...existing.source_article_ids, ...candidate.source_article_ids]),
  );
  existing.evidence_ids = Array.from(new Set([...existing.evidence_ids, ...candidate.evidence_ids]));
  existing.aliases = Array.from(new Set([...existing.aliases, ...candidate.aliases]));
  if (existing.evidence_ids.length === 0 || existing.confidence < 0.7) {
    existing.review_status = "needs_review";
  }
}

async function sourceArticleForDir(inputRoot: string, articleDir: string): Promise<SourceArticleRecord> {
  const articleId = toPortablePath(relative(inputRoot, articleDir));
  const meta = await readJsonIfExists<Record<string, unknown>>(join(articleDir, "meta.json"));
  const sidecar = await readJsonIfExists<Record<string, unknown>>(join(articleDir, "sidecar.json"));
  const archive = isObject(sidecar?.archive) ? sidecar.archive : {};
  return {
    article_id: articleId,
    artifact_dir: articleId,
    title: asString(meta?.title) || asString(archive.title),
    source_url: asString(meta?.source_url) || asString(archive.source_url),
    account: asString(meta?.account_name) || asString(archive.account_key),
  };
}

function parseDownstreamPayload(result: ParsedDownstreamResult | null): unknown {
  if (!result) {
    return null;
  }
  if (result.parsed) {
    return result.parsed;
  }
  const raw = asString(result.rawText) || asString(result.raw_text);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function pushReview(
  reviewQueue: GraphReviewQueueItem[],
  item: GraphReviewQueueItem,
): void {
  if (!reviewQueue.some((existing) => existing.review_id === item.review_id)) {
    reviewQueue.push(item);
  }
}

async function writeJsonl(filePath: string, rows: unknown[]): Promise<void> {
  await mkdir(dirname(filePath), { recursive: true });
  await writeText(
    filePath,
    `${rows.map((row) => JSON.stringify(row)).join("\n")}${rows.length > 0 ? "\n" : ""}`,
  );
}

export async function buildGraphCandidatePack(
  options: GraphCandidatePackOptions,
): Promise<GraphCandidatePackManifest> {
  const inputRoot = resolve(options.inputDir);
  const outputRoot = resolve(options.outDir);
  const generatedAt = options.now ? options.now() : new Date().toISOString();
  const confidenceThreshold = options.confidenceThreshold ?? 0.7;
  const articleDirs = await collectArticleDirs(inputRoot);
  const sourceArticles: SourceArticleRecord[] = [];
  const entities = new Map<string, GraphEntityCandidate>();
  const evidence: GraphEvidenceSpan[] = [];
  const claims: GraphClaimCandidate[] = [];
  const relationships: GraphRelationshipCandidate[] = [];
  const reviewQueue: GraphReviewQueueItem[] = [];
  const aliases: unknown[] = [];
  const events: unknown[] = [];

  for (const articleDir of articleDirs) {
    const sourceArticle = await sourceArticleForDir(inputRoot, articleDir);
    sourceArticles.push(sourceArticle);
    const downstream = await readJsonIfExists<ParsedDownstreamResult>(
      join(articleDir, "downstream_result.json"),
    );
    const payload = parseDownstreamPayload(downstream);
    if (!payload) {
      continue;
    }
    const sourceFile = toPortablePath(relative(inputRoot, join(articleDir, "downstream_result.json")));

    for (const rawEntity of firstArray(payload, ["entities", "entity_candidates"])) {
      if (!isObject(rawEntity)) {
        continue;
      }
      const name = asString(rawEntity.name) || asString(rawEntity.canonical_name) || asString(rawEntity.label);
      if (!name) {
        continue;
      }
      const type = normalizeEntityType(rawEntity.type || rawEntity.entity_type);
      const confidence = asNumber(rawEntity.confidence);
      const evId = addEvidence({
        evidence,
        articleId: sourceArticle.article_id,
        sourceFile,
        excerpt: evidenceText(rawEntity),
        method: "llm",
      });
      const id = entityId(type, name);
      const aliasList = Array.isArray(rawEntity.aliases)
        ? rawEntity.aliases.map((item) => asString(item)).filter(Boolean)
        : [];
      upsertEntity(entities, {
        entity_id: id,
        entity_type: type,
        canonical_name: normalizeName(name),
        display_name: name,
        aliases: aliasList,
        confidence,
        source_article_ids: [sourceArticle.article_id],
        evidence_ids: evId ? [evId] : [],
        review_status: confidence >= confidenceThreshold && evId ? "candidate" : "needs_review",
      });
      if (aliasList.length > 0) {
        aliases.push({
          entity_id: id,
          aliases: aliasList,
          source_article_id: sourceArticle.article_id,
          evidence_ids: evId ? [evId] : [],
        });
      }
      if (!evId || confidence < confidenceThreshold) {
        pushReview(reviewQueue, {
          review_id: stableId("rev", ["entity", id, sourceArticle.article_id]),
          reason: !evId ? "missing_evidence" : "low_confidence",
          target_type: "entity",
          target_id: id,
          source_article_id: sourceArticle.article_id,
        });
      }
    }

    for (const rawEvent of firstArray(payload, ["events", "event_candidates"])) {
      if (!isObject(rawEvent)) {
        continue;
      }
      const title = asString(rawEvent.title) || asString(rawEvent.name) || sourceArticle.title;
      if (!title) {
        continue;
      }
      const evId = addEvidence({
        evidence,
        articleId: sourceArticle.article_id,
        sourceFile,
        excerpt: evidenceText(rawEvent),
        method: "llm_event",
      });
      const eventId = entityId("event", title);
      upsertEntity(entities, {
        entity_id: eventId,
        entity_type: "event",
        canonical_name: normalizeName(title),
        display_name: title,
        aliases: [],
        confidence: asNumber(rawEvent.confidence),
        source_article_ids: [sourceArticle.article_id],
        evidence_ids: evId ? [evId] : [],
        review_status: evId ? "candidate" : "needs_review",
      });
      events.push({
        event_id: eventId,
        title,
        date: asString(rawEvent.date) || asString(rawEvent.event_date),
        city: asString(rawEvent.city),
        venue: asString(rawEvent.venue),
        source_article_id: sourceArticle.article_id,
        evidence_ids: evId ? [evId] : [],
      });
    }

    for (const rawClaim of firstArray(payload, ["claims", "claim_candidates", "relationships"])) {
      if (!isObject(rawClaim)) {
        continue;
      }
      const subject = asString(rawClaim.subject) || asString(rawClaim.subject_label);
      const object = asString(rawClaim.object) || asString(rawClaim.object_label);
      if (!subject || !object) {
        continue;
      }
      const claimType = normalizeClaimType(rawClaim.claim_type || rawClaim.type || rawClaim.predicate);
      const subjectType = normalizeEntityType(rawClaim.subject_type || rawClaim.subject_entity_type);
      const objectType = normalizeEntityType(rawClaim.object_type || rawClaim.object_entity_type);
      const subjectId = entityId(subjectType, subject);
      const objectId = entityId(objectType, object);
      const confidence = asNumber(rawClaim.confidence);
      const evId = addEvidence({
        evidence,
        articleId: sourceArticle.article_id,
        sourceFile,
        excerpt: evidenceText(rawClaim),
        method: "llm_claim",
      });
      const claimId = stableId("clm", [
        sourceArticle.article_id,
        claimType,
        subjectId,
        objectId,
        evId,
      ]);
      upsertEntity(entities, {
        entity_id: subjectId,
        entity_type: subjectType,
        canonical_name: normalizeName(subject),
        display_name: subject,
        aliases: [],
        confidence,
        source_article_ids: [sourceArticle.article_id],
        evidence_ids: evId ? [evId] : [],
        review_status: evId && confidence >= confidenceThreshold ? "candidate" : "needs_review",
      });
      upsertEntity(entities, {
        entity_id: objectId,
        entity_type: objectType,
        canonical_name: normalizeName(object),
        display_name: object,
        aliases: [],
        confidence,
        source_article_ids: [sourceArticle.article_id],
        evidence_ids: evId ? [evId] : [],
        review_status: evId && confidence >= confidenceThreshold ? "candidate" : "needs_review",
      });
      claims.push({
        claim_id: claimId,
        claim_type: claimType,
        subject_label: subject,
        object_label: object,
        subject_entity_id: subjectId,
        object_entity_id: objectId,
        confidence,
        evidence_ids: evId ? [evId] : [],
        source_article_id: sourceArticle.article_id,
        method: "llm",
      });
      const relationshipId = stableId("rel", [edgeTypeForClaim(claimType), subjectId, objectId, claimId]);
      relationships.push({
        relationship_id: relationshipId,
        edge_type: edgeTypeForClaim(claimType),
        subject_entity_id: subjectId,
        object_entity_id: objectId,
        claim_ids: [claimId],
        evidence_ids: evId ? [evId] : [],
        confidence,
      });
      if (!evId || confidence < confidenceThreshold) {
        pushReview(reviewQueue, {
          review_id: stableId("rev", ["claim", claimId]),
          reason: !evId ? "missing_evidence" : "low_confidence",
          target_type: "claim",
          target_id: claimId,
          source_article_id: sourceArticle.article_id,
        });
      }
    }
  }

  const outputPaths = {
    manifest_json: join(outputRoot, "manifest.json"),
    entities_jsonl: join(outputRoot, "entities.jsonl"),
    claims_jsonl: join(outputRoot, "claims.jsonl"),
    relationships_jsonl: join(outputRoot, "relationships.jsonl"),
    events_jsonl: join(outputRoot, "events.jsonl"),
    aliases_jsonl: join(outputRoot, "aliases.jsonl"),
    review_queue_jsonl: join(outputRoot, "review_queue.jsonl"),
    evidence_spans_jsonl: join(outputRoot, "evidence_spans.jsonl"),
    source_articles_jsonl: join(outputRoot, "source_articles.jsonl"),
    checksums_sha256: join(outputRoot, "checksums.sha256"),
  };

  const entityRows = Array.from(entities.values()).sort((left, right) =>
    left.entity_id.localeCompare(right.entity_id),
  );
  await writeJsonl(outputPaths.entities_jsonl, entityRows);
  await writeJsonl(outputPaths.claims_jsonl, claims);
  await writeJsonl(outputPaths.relationships_jsonl, relationships);
  await writeJsonl(outputPaths.events_jsonl, events);
  await writeJsonl(outputPaths.aliases_jsonl, aliases);
  await writeJsonl(outputPaths.review_queue_jsonl, reviewQueue);
  await writeJsonl(outputPaths.evidence_spans_jsonl, evidence);
  await writeJsonl(outputPaths.source_articles_jsonl, sourceArticles);

  const manifest: GraphCandidatePackManifest = {
    version: 1,
    schema_version: "graph-candidate-pack.v1",
    generated_at: generatedAt,
    source_pack_id: options.sourcePackId || "",
    input_root: inputRoot,
    output_root: outputRoot,
    row_counts: {
      entities: entityRows.length,
      claims: claims.length,
      relationships: relationships.length,
      events: events.length,
      aliases: aliases.length,
      review_queue: reviewQueue.length,
      evidence_spans: evidence.length,
      source_articles: sourceArticles.length,
    },
    output_paths: outputPaths,
  };
  await writeJson(outputPaths.manifest_json, manifest);
  await writeChecksumsFile(outputRoot);
  return manifest;
}
