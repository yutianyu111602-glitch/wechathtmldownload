import { join, resolve } from "node:path";

import { writeJson } from "../utils/fs.js";
import { readJsonlFile } from "../utils/jsonl.js";
import type {
  GraphClaimCandidate,
  GraphEntityCandidate,
  GraphRelationshipCandidate,
} from "../graph/graphCandidatePack.js";

const ENTITY_TYPES = new Set([
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
]);

const CLAIM_TYPES = new Set([
  "appears_in_event",
  "appears_on_schedule",
  "shared_bill_with",
  "links_to_account",
  "published_by_source",
]);

const EDGE_TYPES = new Set(["PERFORMS_AT", "APPEARS_WITH", "PUBLISHED_BY", "LINKED_ACCOUNT"]);

export interface IgnukeDryRunImportOptions {
  inputDir: string;
  outDir?: string;
  now?: () => string;
}

export interface IgnukeDryRunImportReport {
  status: "passed" | "failed";
  generated_at: string;
  input_dir: string;
  row_counts: Record<string, number>;
  errors: string[];
  warnings: string[];
  admission_enabled: false;
}

export async function runIgnukeDryRunImport(
  options: IgnukeDryRunImportOptions,
): Promise<IgnukeDryRunImportReport> {
  const inputDir = resolve(options.inputDir);
  const entities = await readJsonlFile<GraphEntityCandidate>(join(inputDir, "entities.jsonl"));
  const claims = await readJsonlFile<GraphClaimCandidate>(join(inputDir, "claims.jsonl"));
  const relationships = await readJsonlFile<GraphRelationshipCandidate>(
    join(inputDir, "relationships.jsonl"),
  );
  const evidence = await readJsonlFile<{ evidence_id: string }>(
    join(inputDir, "evidence_spans.jsonl"),
  );
  const errors: string[] = [];
  const warnings: string[] = [];
  const entityIds = new Set(entities.map((item) => item.entity_id));
  const claimIds = new Set(claims.map((item) => item.claim_id));
  const evidenceIds = new Set(evidence.map((item) => item.evidence_id));

  for (const entity of entities) {
    if (!ENTITY_TYPES.has(entity.entity_type)) {
      errors.push(`entity ${entity.entity_id} invalid type ${entity.entity_type}`);
    }
    if (!entity.evidence_ids || entity.evidence_ids.length === 0) {
      errors.push(`entity ${entity.entity_id} has no evidence`);
    }
  }

  for (const claim of claims) {
    if (!CLAIM_TYPES.has(claim.claim_type)) {
      errors.push(`claim ${claim.claim_id} invalid type ${claim.claim_type}`);
    }
    if (!entityIds.has(claim.subject_entity_id)) {
      errors.push(`claim ${claim.claim_id} missing subject entity ${claim.subject_entity_id}`);
    }
    if (!entityIds.has(claim.object_entity_id)) {
      errors.push(`claim ${claim.claim_id} missing object entity ${claim.object_entity_id}`);
    }
    if (!claim.evidence_ids || claim.evidence_ids.length === 0) {
      errors.push(`claim ${claim.claim_id} has no evidence`);
    }
    for (const evidenceId of claim.evidence_ids || []) {
      if (!evidenceIds.has(evidenceId)) {
        errors.push(`claim ${claim.claim_id} missing evidence ${evidenceId}`);
      }
    }
  }

  for (const relationship of relationships) {
    if (!EDGE_TYPES.has(relationship.edge_type)) {
      errors.push(`relationship ${relationship.relationship_id} invalid edge ${relationship.edge_type}`);
    }
    if (!entityIds.has(relationship.subject_entity_id)) {
      errors.push(`relationship ${relationship.relationship_id} missing subject entity`);
    }
    if (!entityIds.has(relationship.object_entity_id)) {
      errors.push(`relationship ${relationship.relationship_id} missing object entity`);
    }
    if (!relationship.claim_ids || relationship.claim_ids.length === 0) {
      errors.push(`relationship ${relationship.relationship_id} has no claim`);
    }
    for (const claimId of relationship.claim_ids || []) {
      if (!claimIds.has(claimId)) {
        errors.push(`relationship ${relationship.relationship_id} missing claim ${claimId}`);
      }
    }
  }

  if (relationships.length === 0) {
    warnings.push("no relationships generated");
  }

  const report: IgnukeDryRunImportReport = {
    status: errors.length > 0 ? "failed" : "passed",
    generated_at: options.now ? options.now() : new Date().toISOString(),
    input_dir: inputDir,
    row_counts: {
      entities: entities.length,
      claims: claims.length,
      relationships: relationships.length,
      evidence_spans: evidence.length,
    },
    errors,
    warnings,
    admission_enabled: false,
  };

  if (options.outDir) {
    await writeJson(join(resolve(options.outDir), "ignuke-dry-run-report.json"), report);
  }
  return report;
}
