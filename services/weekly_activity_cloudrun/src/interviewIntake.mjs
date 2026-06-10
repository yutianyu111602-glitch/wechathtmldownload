import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

const SUPPORTED_EXTENSIONS = new Set([".md", ".markdown", ".json", ".jsonl"]);

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function boolValue(value) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const text = cleanString(value).toLowerCase();
  if (["true", "yes", "y", "1", "ok", "同意", "是"].includes(text)) return true;
  if (["false", "no", "n", "0", "否"].includes(text)) return false;
  return false;
}

function shortHash(value) {
  const text = cleanString(value);
  if (!text) return "";
  return createHash("sha256").update(text).digest("hex").slice(0, 16);
}

function parseScalar(value) {
  const text = cleanString(value);
  if (!text) return "";
  if ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"))) {
    return text.slice(1, -1);
  }
  if (["true", "false"].includes(text.toLowerCase())) return text.toLowerCase() === "true";
  return text;
}

export function parseInterviewMarkdown(text) {
  const lines = String(text || "").replace(/^\uFEFF/, "").split(/\r?\n/);
  const metadata = {};
  let bodyStart = 0;
  if (lines[0]?.trim() === "---") {
    const end = lines.findIndex((line, index) => index > 0 && line.trim() === "---");
    if (end > 0) {
      for (const line of lines.slice(1, end)) {
        const match = line.match(/^([A-Za-z0-9_.-]+)\s*:\s*(.*)$/);
        if (match) metadata[match[1]] = parseScalar(match[2]);
      }
      bodyStart = end + 1;
    }
  }
  const body = lines.slice(bodyStart).join("\n").trim();
  return [{ ...metadata, answerText: metadata.answerText || metadata.notes || body }];
}

export function parseInterviewJson(text) {
  const payload = JSON.parse(text);
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload.items)) return payload.items;
  if (Array.isArray(payload.submissions)) return payload.submissions;
  return [payload];
}

export function parseInterviewJsonl(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

export function normalizeInterviewRecord(record = {}, source = {}) {
  const consentInput = record.consent || {};
  const sourceUrl = cleanString(record.sourceUrl || record.source_url || record.source);
  const normalized = {
    djName: cleanString(record.djName || record.name || record.dj || record.artistName),
    normalizedName: cleanString(record.normalizedName || record.normalized_name),
    city: cleanString(record.city || record.cityName),
    contact: cleanString(record.contact || record.contactInfo || record.contact_info),
    sourceRefId: cleanString(record.sourceRefId || record.source_ref_id || record.sourceUrlHash || record.urlHash),
    sourceUrl,
    instagramUrl: cleanString(record.instagramUrl || record.instagram || record.ins),
    mixtapeUrl: cleanString(record.mixtapeUrl || record.mixtape || record.mixUrl || record.mixcloudUrl || record.soundcloudUrl),
    answerText: cleanString(record.answerText || record.interviewText || record.answers || record.transcript),
    note: cleanString(record.note || record.notes),
    submittedAt: cleanString(record.submittedAt || record.submitted_at),
    consent: {
      internalProcessing: boolValue(consentInput.internalProcessing ?? record.consentInternal ?? record.internalConsent),
      publicFacts: boolValue(consentInput.publicFacts ?? record.consentPublic ?? record.publicFactsConsent),
      graphCandidate: boolValue(consentInput.graphCandidate ?? record.consentGraph ?? record.graphConsent),
    },
  };
  return {
    record: normalized,
    summary: {
      sourceFile: source.relativePath || "",
      djName: normalized.djName,
      city: normalized.city,
      hasContact: Boolean(normalized.contact),
      hasAnswerText: Boolean(normalized.answerText),
      sourceRefId: normalized.sourceRefId,
      sourceUrlHash: shortHash(normalized.sourceUrl),
      hasInstagram: Boolean(normalized.instagramUrl),
      hasMixtape: Boolean(normalized.mixtapeUrl),
      consentStatus: normalized.consent.graphCandidate
        ? "graph_candidate_requested"
        : normalized.consent.publicFacts
          ? "public_facts_requested"
          : normalized.consent.internalProcessing
            ? "private_review_only"
            : "missing_internal_processing_consent",
    },
  };
}

function validationErrors(record) {
  const errors = [];
  if (!record.djName) errors.push("dj_name_required");
  if (!record.consent.internalProcessing) errors.push("internal_processing_consent_required");
  return errors;
}

async function inputFiles(inputPath) {
  const info = await stat(inputPath);
  if (!info.isDirectory()) return [inputPath];
  const entries = await readdir(inputPath);
  return entries
    .filter((entry) => SUPPORTED_EXTENSIONS.has(path.extname(entry).toLowerCase()))
    .sort()
    .map((entry) => path.join(inputPath, entry));
}

async function parseFile(filePath, rootPath) {
  const extension = path.extname(filePath).toLowerCase();
  const text = await readFile(filePath, "utf8");
  let records;
  if (extension === ".json") records = parseInterviewJson(text);
  else if (extension === ".jsonl") records = parseInterviewJsonl(text);
  else if (extension === ".md" || extension === ".markdown") records = parseInterviewMarkdown(text);
  else throw new Error(`Unsupported interview intake extension: ${extension}`);
  const relativePath = path.relative(rootPath, filePath) || path.basename(filePath);
  return asArray(records).map((record) => normalizeInterviewRecord(record, { relativePath }));
}

export async function readInterviewIntake(inputPath) {
  if (!inputPath) throw new Error("readInterviewIntake requires inputPath.");
  const resolved = path.resolve(inputPath);
  const files = await inputFiles(resolved);
  const parsed = [];
  for (const file of files) {
    parsed.push(...await parseFile(file, resolved));
  }
  return parsed.map((item, index) => {
    const errors = validationErrors(item.record);
    return {
      index,
      valid: errors.length === 0,
      errors,
      record: item.record,
      summary: item.summary,
    };
  });
}

export async function importDjInterviewSubmissions(options = {}) {
  const intake = await readInterviewIntake(options.inputPath);
  const accepted = intake.filter((item) => item.valid);
  const rejected = intake.filter((item) => !item.valid);
  const base = {
    schemaVersion: "atlas_dj_interview_intake.v1",
    dryRun: Boolean(options.dryRun),
    total: intake.length,
    accepted: accepted.length,
    rejected: rejected.length,
    rejectedItems: rejected.map((item) => ({ index: item.index, errors: item.errors, summary: item.summary })),
    items: accepted.map((item) => item.summary),
    safety: {
      rawContactExported: false,
      rawInterviewTextExported: false,
      publicGraphWriteExecuted: false,
      productionWriteExecuted: false,
      mediaDownloadExecuted: false,
      mediaCacheWritten: false,
    },
  };
  if (options.dryRun || rejected.length) {
    return { ...base, ok: rejected.length === 0 };
  }
  if (!options.store || typeof options.store.submit !== "function") {
    throw new Error("importDjInterviewSubmissions requires a store with submit().");
  }
  const imported = [];
  for (const item of accepted) {
    const result = await options.store.submit(item.record);
    imported.push({
      id: result.id,
      status: result.status,
      consentStatus: result.consentStatus,
      summary: item.summary,
    });
  }
  return {
    ...base,
    ok: true,
    imported: imported.length,
    importedItems: imported,
  };
}
