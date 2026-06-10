import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { buildInterviewExternalLinkFields, cleanExternalUrl } from "./externalMusicLinks.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_INTERVIEW_DIR = path.resolve(moduleDir, "../data/dj-interviews");
const MAX_TEXT_LENGTH = 1200;
const MAX_URL_LENGTH = 500;

function cleanText(value, maxLength = MAX_TEXT_LENGTH) {
  return String(value || "").trim().replace(/\s+/g, " ").slice(0, maxLength);
}

function cleanUrl(value) {
  return cleanExternalUrl(cleanText(value, MAX_URL_LENGTH));
}

function cleanBoolean(value) {
  return value === true || value === "true" || value === 1 || value === "1";
}

function redactedEntry(entry) {
  return {
    id: entry.id,
    djName: entry.djName,
    city: entry.city,
    status: entry.status,
    submittedAt: entry.submittedAt,
    version: entry.version,
    hasInstagramUrl: Boolean(entry.instagramUrl),
    hasMixtapeUrl: Boolean(entry.mixtapeUrl),
    hasSourceUrl: Boolean(entry.sourceUrl),
    externalLinkCount: Array.isArray(entry.externalLinks) ? entry.externalLinks.length : 0,
    musicLinkCount: Array.isArray(entry.musicLinks) ? entry.musicLinks.length : 0,
    consentStatus: entry.consentStatus,
  };
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function redactedLink(link = {}) {
  return {
    kind: cleanText(link.kind, 40),
    platform: cleanText(link.platform, 80),
    urlHash: cleanText(link.urlHash, 80),
    sourceRefId: cleanText(link.sourceRefId, 160),
    rightsStatus: cleanText(link.rightsStatus, 80),
    consentStatus: cleanText(link.consentStatus, 80),
    submittedAt: cleanText(link.submittedAt, 80),
    mediaHandling: {
      download: false,
      cache: false,
      proxy: false,
      transcode: false,
      republish: false,
    },
  };
}

function uniqueText(values) {
  return [...new Set(values.map((value) => cleanText(value, 80)).filter(Boolean))];
}

function buildPromotionGate(entry, externalLinks, musicLinks) {
  const consent = entry.consent || {};
  const sourceLink = externalLinks.find((link) => link.kind === "source");
  const blockers = [];
  if (!entry.djName) blockers.push("dj_name_missing");
  if (!consent.internalProcessing) blockers.push("internal_consent_missing");
  if (!consent.publicFacts) blockers.push("public_facts_consent_missing");
  if (!consent.graphCandidate) blockers.push("graph_consent_missing");
  if (!entry.sourceRefId && !sourceLink) blockers.push("source_evidence_missing");

  return {
    stage: "private_review",
    result: blockers.length ? "blocked_before_promotion" : "ready_for_human_review",
    blockers,
    requiredNext: ["human_review", "artist_confirmed", "source_quote_ref", "consent_scope"],
    writes: {
      db1: false,
      db2: false,
      db3: false,
      graph: false,
      publicProfile: false,
    },
    canPromoteExternalLinksAfterReview: Boolean(!blockers.length && musicLinks.length),
    publishAllowed: false,
  };
}

function reviewQueueEntry(entry) {
  const externalLinks = asArray(entry.externalLinks).map(redactedLink);
  const musicLinks = asArray(entry.musicLinks).map(redactedLink);
  const sourceLink = externalLinks.find((link) => link.kind === "source");
  return {
    id: entry.id,
    djName: entry.djName,
    normalizedName: entry.normalizedName,
    city: entry.city,
    status: entry.status,
    submittedAt: entry.submittedAt,
    version: entry.version,
    consentStatus: entry.consentStatus,
    hasContact: Boolean(entry.contact),
    hasAnswerText: Boolean(entry.answerText),
    linkSummary: {
      externalLinkCount: externalLinks.length,
      musicLinkCount: musicLinks.length,
      platforms: uniqueText(externalLinks.map((link) => link.platform)),
      musicPlatforms: uniqueText(musicLinks.map((link) => link.platform)),
    },
    sourceEvidence: {
      hasSourceUrl: Boolean(sourceLink),
      sourcePlatform: sourceLink?.platform || "",
      sourceUrlHash: sourceLink?.urlHash || "",
      sourceRefId: entry.sourceRefId || sourceLink?.sourceRefId || "",
    },
    externalLinks,
    musicLinks,
    promotionGate: buildPromotionGate(entry, externalLinks, musicLinks),
  };
}

export function createDjInterviewStore(options = {}) {
  const env = options.env || process.env;
  const interviewDir = options.interviewDir || env.DJ_INTERVIEW_SUBMISSIONS_DIR || DEFAULT_INTERVIEW_DIR;
  const submissionsFile = path.join(interviewDir, "submissions.json");
  let writeQueue = Promise.resolve();

  async function readAll() {
    try {
      const raw = await readFile(submissionsFile, "utf8");
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  async function writeAll(submissions) {
    await mkdir(interviewDir, { recursive: true });
    const tmpFile = `${submissionsFile}.tmp.${randomUUID()}`;
    await writeFile(tmpFile, JSON.stringify(submissions, null, 2), "utf8");
    await rename(tmpFile, submissionsFile);
  }

  function enqueueWrite(fn) {
    const prev = writeQueue;
    let resolve;
    writeQueue = new Promise((r) => { resolve = r; });
    return prev.then(async () => {
      try {
        return await fn();
      } finally {
        resolve();
      }
    });
  }

  return {
    async submit(record = {}) {
      return enqueueWrite(async () => {
        const djName = cleanText(record.djName || record.name, 120);
        if (!djName) {
          const error = new Error("DJ name is required");
          error.statusCode = 400;
          error.code = "MISSING_DJ_NAME";
          throw error;
        }

        const consent = {
          internalProcessing: cleanBoolean(record.consent?.internalProcessing ?? record.consentInternal),
          publicFacts: cleanBoolean(record.consent?.publicFacts ?? record.consentPublic),
          graphCandidate: cleanBoolean(record.consent?.graphCandidate ?? record.consentGraph),
        };
        if (!consent.internalProcessing) {
          const error = new Error("Interview consent is required before storing a submission");
          error.statusCode = 400;
          error.code = "MISSING_CONSENT";
          throw error;
        }

        const entry = {
          id: `interview_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          djName,
          normalizedName: cleanText(record.normalizedName, 160),
          city: cleanText(record.city, 80),
          contact: cleanText(record.contact, 240),
          sourceRefId: cleanText(record.sourceRefId || record.source_ref_id || record.sourceUrlHash || record.urlHash, 160),
          instagramUrl: cleanUrl(record.instagramUrl || record.instagram),
          mixtapeUrl: cleanUrl(record.mixtapeUrl || record.mixUrl || record.mixcloudUrl || record.soundcloudUrl),
          sourceUrl: cleanUrl(record.sourceUrl),
          answerText: cleanText(record.answerText || record.notes),
          note: cleanText(record.note, 800),
          consent,
          consentStatus: consent.publicFacts && consent.graphCandidate
            ? "graph_candidate_allowed"
            : consent.publicFacts
              ? "public_facts_allowed"
              : "private_review_only",
          status: "submitted",
          submittedAt: cleanText(record.submittedAt, 80) || new Date().toISOString(),
          version: 1,
          safety: {
            rawAudioStored: false,
            audioDownloadExecuted: false,
            publicGraphWriteExecuted: false,
            productionWriteExecuted: false,
            requiresHumanReview: true,
          },
        };
        const linkFields = buildInterviewExternalLinkFields(entry);
        entry.externalLinksSchemaVersion = linkFields.schemaVersion;
        entry.externalLinks = linkFields.externalLinks;
        entry.musicLinks = linkFields.musicLinks;
        entry.externalLinkSafety = linkFields.safety;

        const submissions = await readAll();
        submissions.unshift(entry);
        await writeAll(submissions);
        return {
          ok: true,
          id: entry.id,
          status: entry.status,
          consentStatus: entry.consentStatus,
          total: submissions.length,
          safety: entry.safety,
        };
      });
    },

    async reviewQueue(options = {}) {
      const limit = Math.min(Math.max(Number(options.limit) || 50, 1), 200);
      const submissions = await readAll();
      return {
        schemaVersion: "atlas_dj_interview_review_queue.v1",
        total: submissions.length,
        items: submissions.slice(0, limit).map(reviewQueueEntry),
        promotionPolicy: {
          requiredNext: ["human_review", "artist_confirmed", "source_quote_ref", "consent_scope"],
          publicWritesDuringReview: false,
        },
        safety: {
          rawContactExposed: false,
          rawInterviewTextExposed: false,
          rawAudioExposed: false,
          publicGraphWriteExecuted: false,
          productionWriteExecuted: false,
        },
      };
    },

    async list(options = {}) {
      const limit = Math.min(Math.max(Number(options.limit) || 50, 1), 200);
      const submissions = await readAll();
      return {
        schemaVersion: "atlas_dj_interview_submissions.v1",
        total: submissions.length,
        items: submissions.slice(0, limit).map(redactedEntry),
        safety: {
          rawContactExposed: false,
          rawInterviewTextExposed: false,
          rawAudioExposed: false,
          publicGraphWriteExecuted: false,
        },
      };
    },

    async count() {
      const submissions = await readAll();
      return { total: submissions.length };
    },
  };
}
