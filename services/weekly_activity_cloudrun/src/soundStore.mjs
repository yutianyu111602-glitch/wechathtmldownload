import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash, randomUUID } from "node:crypto";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_SOUND_DIR = path.resolve(moduleDir, "../data/sounds");
const MAX_SOUND_FILES = 4;
const MAX_PAYMENT_FILES = 9;
const MAX_FILE_ID_LENGTH = 1024;
const MAX_CLUB_NAME_LENGTH = 120;
const CLOUDBASE_COLLECTION_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
const OWNER_KEY_RE = /^[a-f0-9]{64}$/;
const SUBMISSION_KEY_RE = /^[A-Za-z0-9_-]{12,128}$/;
const MIN_DAILY_LIMIT = 1;
const MAX_DAILY_LIMIT = 50;

function storeError(code, message, statusCode = 503, cause = null) {
  const error = Object.assign(new Error(message), { code, statusCode });
  if (cause) error.cause = cause;
  return error;
}

function validationError(code, message) {
  return storeError(code, `${code}: ${message}`, 400);
}

function isSoundStoreError(error) {
  return typeof error?.code === "string" && /^SOUND_SUBMISSIONS?_[A-Z0-9_]+$/.test(error.code);
}

function isExpectedCloudAuthority(authority, envId) {
  if (authority === envId) return true;
  if (!authority.startsWith(`${envId}.`)) return false;
  const bucket = authority.slice(envId.length + 1);
  return /^[A-Za-z0-9][A-Za-z0-9.-]{0,190}$/.test(bucket);
}

function validateCloudFileId(fileId, { kind, envId, submissionKey }) {
  if (!envId) {
    throw validationError("SOUND_STORAGE_ENV_NOT_CONFIGURED", "CloudBase environment id is required to validate evidence");
  }
  if (
    /[\u0000-\u001f\u007f]/.test(fileId)
    || fileId.includes("?")
    || fileId.includes("#")
    || fileId.includes("%")
  ) {
    throw validationError(`INVALID_${kind.toUpperCase()}_FILE_ID`, `Invalid ${kind} file id`);
  }
  const match = /^cloud:\/\/([^/]+)\/(.+)$/.exec(fileId);
  if (!match || !isExpectedCloudAuthority(match[1], envId)) {
    throw validationError(`INVALID_${kind.toUpperCase()}_FILE_ID`, `Invalid ${kind} file id`);
  }
  const segments = match[2].split("/");
  const valid = segments.length === 5
    && segments[0] === "atlas"
    && segments[1] === "sound-submissions"
    && segments[2] === submissionKey
    && segments[3] === kind
    && /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}\.(?:jpe?g|png|webp)$/i.test(segments[4]);
  if (!valid || segments.some((segment) => segment === "." || segment === "..")) {
    throw validationError(`INVALID_${kind.toUpperCase()}_FILE_ID`, `Invalid ${kind} file id`);
  }
}

function cleanFileIds(value, kind, contract) {
  if (!Array.isArray(value)) return [];
  const maxFiles = kind === "sound" ? MAX_SOUND_FILES : MAX_PAYMENT_FILES;
  if (value.length > maxFiles) {
    throw validationError(`TOO_MANY_${kind.toUpperCase()}_FILES`, `At most ${maxFiles} ${kind} files are allowed`);
  }
  const rawEntries = value.map((entry) => String(entry || ""));
  const cleaned = rawEntries.map((entry) => entry.trim());
  if (rawEntries.some((entry, index) => entry !== cleaned[index])) {
    throw validationError(`INVALID_${kind.toUpperCase()}_FILE_ID`, `Invalid ${kind} file id`);
  }
  if (cleaned.some((entry) => !entry || entry.length > MAX_FILE_ID_LENGTH)) {
    throw validationError(`INVALID_${kind.toUpperCase()}_FILE_ID`, `Invalid ${kind} file id`);
  }
  if (new Set(cleaned).size !== cleaned.length) {
    throw validationError(`DUPLICATE_${kind.toUpperCase()}_FILE_ID`, `Duplicate ${kind} file id`);
  }
  cleaned.forEach((fileId) => validateCloudFileId(fileId, { ...contract, kind }));
  return cleaned;
}

function validatePersistedEntry(value, expectedId = "") {
  const valid = value && typeof value === "object" && !Array.isArray(value)
    && (!value.kind || value.kind === "submission")
    && typeof value.id === "string" && value.id.startsWith("sound_")
    && (!expectedId || value.id === expectedId)
    && typeof value.clubName === "string" && value.clubName.trim()
    && Array.isArray(value.soundFileIds) && value.soundFileIds.every((item) => typeof item === "string" && item.trim())
    && Array.isArray(value.paymentFileIds) && value.paymentFileIds.every((item) => typeof item === "string" && item.trim());
  if (!valid) {
    throw storeError(
      "SOUND_SUBMISSIONS_CORRUPT",
      "Sound submission persistence contains an invalid record; writes are disabled until it is repaired.",
    );
  }
  return value;
}

function sha256(value) {
  return createHash("sha256").update(String(value)).digest("hex");
}

function shanghaiDateBucket(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function payloadHash({ clubName, soundFileIds, paymentFileIds }) {
  return sha256(JSON.stringify({
    clubName,
    soundFileIds,
    paymentFileIds,
    version: 4,
  }));
}

function submissionDocumentId(ownerKey, submissionKey) {
  return `sound_${sha256(`${ownerKey}\0${submissionKey}`).slice(0, 48)}`;
}

function quotaSlotDocumentId(ownerKey, bucket, index) {
  return `sound_quota_${sha256(`${ownerKey}\0${bucket}\0${index}`).slice(0, 40)}`;
}

function quotaReconciliationDocumentId(slotId, submissionId) {
  return `sound_reconcile_${sha256(`${slotId}\0${submissionId}`).slice(0, 40)}`;
}

function validateQuotaReconciliationEntry(value) {
  const valid = value && typeof value === "object" && !Array.isArray(value)
    && value.schemaVersion === "weekly_sound_quota_reconciliation.v1"
    && value.kind === "quota_reconciliation"
    && typeof value.id === "string" && value.id.startsWith("sound_reconcile_")
    && typeof value.slotId === "string" && value.slotId.startsWith("sound_quota_")
    && typeof value.submissionId === "string" && value.submissionId.startsWith("sound_")
    && OWNER_KEY_RE.test(value.submitterKey)
    && /^\d{4}-\d{2}-\d{2}$/.test(value.bucket)
    && Number.isSafeInteger(value.slot) && value.slot >= 0
    && typeof value.claimedAt === "string" && value.claimedAt.length > 0
    && typeof value.detectedAt === "string" && value.detectedAt.length > 0
    && value.reason === "submission_write_unverified"
    && value.manualVerificationRequired === true;
  if (!valid) {
    throw storeError(
      "SOUND_SUBMISSIONS_CORRUPT",
      "Sound quota reconciliation persistence contains an invalid record.",
    );
  }
  return value;
}

function createFileBackend(soundDir) {
  const submissionsFile = path.join(soundDir, "submissions.json");
  let writeQueue = Promise.resolve();

  async function readAll() {
    let raw;
    try {
      raw = await readFile(submissionsFile, "utf8");
    } catch (error) {
      if (error?.code === "ENOENT") return [];
      throw storeError(
        "SOUND_SUBMISSIONS_READ_FAILED",
        "Sound submission persistence could not be read; writes are disabled to protect existing data.",
        503,
        error,
      );
    }

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      throw storeError(
        "SOUND_SUBMISSIONS_CORRUPT",
        "Sound submission persistence is not valid JSON; writes are disabled until it is repaired.",
        503,
        error,
      );
    }
    if (!Array.isArray(parsed)) {
      throw storeError(
        "SOUND_SUBMISSIONS_CORRUPT",
        "Sound submission persistence has the wrong shape; writes are disabled until it is repaired.",
      );
    }
    parsed.forEach((entry) => validatePersistedEntry(entry));
    return parsed;
  }

  async function writeAll(submissions) {
    await mkdir(soundDir, { recursive: true });
    const tmpFile = `${submissionsFile}.tmp.${randomUUID()}`;
    try {
      await writeFile(tmpFile, JSON.stringify(submissions, null, 2), "utf8");
      await rename(tmpFile, submissionsFile);
    } catch (error) {
      await unlink(tmpFile).catch(() => {});
      throw storeError(
        "SOUND_SUBMISSIONS_WRITE_FAILED",
        "Sound submission persistence could not be updated.",
        503,
        error,
      );
    }
  }

  function enqueueWrite(operation) {
    const current = writeQueue.then(operation, operation);
    writeQueue = current.catch(() => {});
    return current;
  }

  return {
    name: "file",
    multiInstanceSafe: false,
    async insert(entry) {
      return enqueueWrite(async () => {
        const submissions = await readAll();
        const existing = submissions.find((candidate) => candidate.id === entry.id) || null;
        if (existing) return { created: false, existing };
        submissions.unshift(entry);
        await writeAll(submissions);
        return { created: true, existing: null };
      });
    },
    async getById(id) {
      const submissions = await readAll();
      return submissions.find((entry) => entry.id === id) || null;
    },
    async count() {
      return (await readAll()).length;
    },
    async list({ limit, status }) {
      const submissions = await readAll();
      const filtered = status ? submissions.filter((entry) => entry.status === status) : submissions;
      return {
        total: filtered.length,
        items: filtered.slice(0, limit),
      };
    },
  };
}

function firstCloudbaseDocument(result) {
  if (!result) return null;
  if (Array.isArray(result.data)) return result.data[0] || null;
  return result.data || null;
}

function createCloudbaseBackend({ env, collectionName, injectedDatabase }) {
  let databasePromise = null;

  async function getDatabase() {
    if (injectedDatabase) return injectedDatabase;
    if (!databasePromise) {
      databasePromise = import("@cloudbase/js-sdk")
        .then((module) => {
          const cloudbase = module.default || module;
          const app = cloudbase.init({ env: env.CLOUDBASE_ENV_ID });
          return app.database();
        })
        .catch((error) => {
          databasePromise = null;
          throw storeError(
            "SOUND_SUBMISSIONS_BACKEND_UNAVAILABLE",
            "CloudBase sound submission persistence is unavailable.",
            503,
            error,
          );
        });
    }
    return databasePromise;
  }

  async function collection() {
    const database = await getDatabase();
    return database.collection(collectionName);
  }

  async function readDocument(id) {
    const result = await (await collection()).doc(id).get();
    return firstCloudbaseDocument(result);
  }

  async function createDocument(id, value) {
    try {
      await (await collection()).doc(id).create(value);
      return { created: true, existing: null };
    } catch (error) {
      let existing;
      try {
        existing = await readDocument(id);
      } catch (readError) {
        throw storeError(
          "SOUND_SUBMISSIONS_WRITE_FAILED",
          "CloudBase sound submission persistence could not verify a contested write.",
          503,
          readError,
        );
      }
      if (existing) return { created: false, existing };
      throw storeError(
        "SOUND_SUBMISSIONS_WRITE_FAILED",
        "CloudBase sound submission persistence rejected the write.",
        503,
        error,
      );
    }
  }

  async function markQuotaReconciliationRequired({ slotId, slot, entry, quota }) {
    const id = quotaReconciliationDocumentId(slotId, entry.id);
    const marker = {
      id,
      schemaVersion: "weekly_sound_quota_reconciliation.v1",
      kind: "quota_reconciliation",
      slotId,
      submissionId: entry.id,
      submitterKey: quota.ownerKey,
      bucket: quota.bucket,
      slot,
      claimedAt: entry.submittedAt,
      detectedAt: new Date().toISOString(),
      reason: "submission_write_unverified",
      manualVerificationRequired: true,
    };
    try {
      const result = await createDocument(id, marker);
      if (!result.created) validateQuotaReconciliationEntry(result.existing);
    } catch (error) {
      throw storeError(
        "SOUND_SUBMISSIONS_RECONCILIATION_MARK_FAILED",
        "CloudBase preserved the quota claim but could not record its reconciliation marker.",
        503,
        error,
      );
    }
  }

  return {
    name: "cloudbase",
    multiInstanceSafe: true,
    async insert(entry, quota) {
      try {
        const existingSubmission = await readDocument(entry.id);
        if (existingSubmission) return { created: false, existing: existingSubmission };

        let claimedSlotId = "";
        let claimedSlot = -1;
        for (let index = 0; index < quota.maxPerDay; index += 1) {
          const slotId = quotaSlotDocumentId(quota.ownerKey, quota.bucket, index);
          const claim = await createDocument(slotId, {
            kind: "quota_slot",
            submitterKey: quota.ownerKey,
            bucket: quota.bucket,
            slot: index,
            submissionId: entry.id,
            claimedAt: entry.submittedAt,
          });
          if (claim.created || claim.existing?.submissionId === entry.id) {
            claimedSlotId = slotId;
            claimedSlot = index;
            break;
          }
        }
        if (!claimedSlotId) {
          throw storeError(
            "SOUND_SUBMISSION_RATE_LIMITED",
            "The daily sound submission limit has been reached.",
            429,
          );
        }

        try {
          return await createDocument(entry.id, entry);
        } catch (error) {
          // The CloudBase SDK used here cannot atomically prove that no other
          // instance created the submission between a read and a slot delete.
          // Keep the quota claim fail-closed and record a separate, immutable
          // operator queue item. The queue can verify the durable submission
          // before any later, explicitly controlled release.
          await markQuotaReconciliationRequired({
            slotId: claimedSlotId,
            slot: claimedSlot,
            entry,
            quota,
          });
          throw error;
        }
      } catch (error) {
        if (isSoundStoreError(error)) throw error;
        throw storeError(
          "SOUND_SUBMISSIONS_WRITE_FAILED",
          "CloudBase sound submission persistence rejected the write.",
          503,
          error,
        );
      }
    },
    async getById(id) {
      try {
        const value = await readDocument(id);
        return value ? validatePersistedEntry(value, id) : null;
      } catch (error) {
        if (isSoundStoreError(error)) throw error;
        throw storeError(
          "SOUND_SUBMISSIONS_READ_FAILED",
          "CloudBase sound submission persistence could not be read.",
          503,
          error,
        );
      }
    },
    async count() {
      try {
        const result = await (await collection()).where({ kind: "submission" }).count();
        const total = Number(result?.total);
        if (!Number.isSafeInteger(total) || total < 0) {
          throw storeError("SOUND_SUBMISSIONS_CORRUPT", "CloudBase sound submission count has the wrong shape.");
        }
        return total;
      } catch (error) {
        if (isSoundStoreError(error)) throw error;
        throw storeError(
          "SOUND_SUBMISSIONS_READ_FAILED",
          "CloudBase sound submission persistence could not be counted.",
          503,
          error,
        );
      }
    },
    async list({ limit, status }) {
      try {
        const query = { kind: "submission", ...(status ? { status } : {}) };
        const target = (await collection()).where(query);
        const [countResult, listResult] = await Promise.all([
          target.count(),
          target.limit(limit).get(),
        ]);
        const total = Number(countResult?.total);
        const items = Array.isArray(listResult?.data) ? listResult.data : [];
        if (!Number.isSafeInteger(total) || total < 0) {
          throw storeError("SOUND_SUBMISSIONS_CORRUPT", "CloudBase sound submission count has the wrong shape.");
        }
        items.forEach((entry) => validatePersistedEntry(entry));
        return { total, items };
      } catch (error) {
        if (isSoundStoreError(error)) throw error;
        throw storeError(
          "SOUND_SUBMISSIONS_READ_FAILED",
          "CloudBase sound submission review queue could not be read.",
          503,
          error,
        );
      }
    },
    async listQuotaReconciliation({ limit }) {
      try {
        const target = (await collection()).where({ kind: "quota_reconciliation" });
        const [countResult, listResult] = await Promise.all([
          target.count(),
          target.limit(limit).get(),
        ]);
        const total = Number(countResult?.total);
        const items = Array.isArray(listResult?.data) ? listResult.data : [];
        if (!Number.isSafeInteger(total) || total < 0) {
          throw storeError("SOUND_SUBMISSIONS_CORRUPT", "Sound quota reconciliation count has the wrong shape.");
        }
        items.forEach((entry) => validateQuotaReconciliationEntry(entry));
        return { total, items };
      } catch (error) {
        if (isSoundStoreError(error)) throw error;
        throw storeError(
          "SOUND_SUBMISSIONS_READ_FAILED",
          "CloudBase sound quota reconciliation queue could not be read.",
          503,
          error,
        );
      }
    },
  };
}

function resolveBackend(options, env) {
  if (options.soundDir) {
    return { backend: createFileBackend(options.soundDir), configured: true };
  }

  const requested = String(env.SOUND_SUBMISSIONS_BACKEND || "").trim().toLowerCase();
  const isProduction = String(env.NODE_ENV || "").trim().toLowerCase() === "production";
  if (requested === "cloudbase") {
    const envId = String(env.CLOUDBASE_ENV_ID || "").trim();
    const collectionName = String(env.SOUND_SUBMISSIONS_COLLECTION || "").trim();
    const maxPerDay = Number.parseInt(String(env.SOUND_SUBMISSIONS_MAX_PER_DAY || ""), 10);
    if (
      !envId
      || !CLOUDBASE_COLLECTION_RE.test(collectionName)
      || !Number.isInteger(maxPerDay)
      || maxPerDay < MIN_DAILY_LIMIT
      || maxPerDay > MAX_DAILY_LIMIT
    ) {
      return { backend: null, configured: false };
    }
    return {
      backend: createCloudbaseBackend({
        env,
        collectionName,
        injectedDatabase: options.cloudbaseDatabase || null,
      }),
      configured: true,
      maxPerDay,
    };
  }

  if (requested === "disabled" || isProduction || (requested && requested !== "file")) {
    return { backend: null, configured: false };
  }

  const soundDir = env.SOUND_SUBMISSIONS_DIR || DEFAULT_SOUND_DIR;
  return { backend: createFileBackend(soundDir), configured: true };
}

export function createSoundStore(options = {}) {
  const env = options.env || process.env;
  const resolved = resolveBackend(options, env);
  const backend = resolved.backend;
  const soundEvidenceVerifier = options.soundEvidenceVerifier || null;
  const requiresEvidenceVerifier = backend?.name === "cloudbase"
    && String(env.NODE_ENV || "").trim().toLowerCase() === "production";

  function requireBackend({ forWrite = false } = {}) {
    if (!backend) {
      throw storeError(
        "SOUND_SUBMISSIONS_NOT_CONFIGURED",
        "Durable sound submission persistence is not configured; submissions are temporarily disabled.",
      );
    }
    if (forWrite && requiresEvidenceVerifier && typeof soundEvidenceVerifier?.verifySubmissionFiles !== "function") {
      throw storeError(
        "SOUND_SUBMISSIONS_EVIDENCE_NOT_CONFIGURED",
        "Cloud storage evidence verification is not configured; submissions are temporarily disabled.",
      );
    }
    return backend;
  }

  return {
    async submit(record = {}, context = {}) {
      const target = requireBackend({ forWrite: true });
      const rawClubName = String(record && record.clubName || "");
      const clubName = rawClubName.trim();
      if (!clubName) throw validationError("MISSING_CLUB_NAME", "Club name is required");
      if (/[\u0000-\u001f\u007f\u2028\u2029]/.test(rawClubName)) {
        throw validationError("INVALID_CLUB_NAME", "Club name must be a single line without control characters");
      }
      if (clubName.length > MAX_CLUB_NAME_LENGTH) {
        throw validationError("CLUB_NAME_TOO_LONG", `Club name must be at most ${MAX_CLUB_NAME_LENGTH} characters`);
      }
      const isCloudbase = target.name === "cloudbase";
      const ownerKey = String(context.ownerKey || "").trim().toLowerCase();
      const submissionKey = String(record && record.submissionKey || "").trim();
      if (isCloudbase && !OWNER_KEY_RE.test(ownerKey)) {
        throw storeError(
          "SOUND_SUBMISSION_IDENTITY_REQUIRED",
          "A verified WeChat identity is required for sound submissions.",
          401,
        );
      }
      if (!submissionKey) {
        throw validationError("MISSING_SUBMISSION_KEY", "A submission idempotency key is required");
      }
      if (!SUBMISSION_KEY_RE.test(submissionKey)) {
        throw validationError("INVALID_SUBMISSION_KEY", "The submission idempotency key is invalid");
      }
      if (Number(record && record.version) !== 4) {
        throw validationError("INVALID_SUBMISSION_VERSION", "Sound submission schema version 4 is required");
      }
      const storageContract = {
        envId: String(env.CLOUDBASE_ENV_ID || "").trim(),
        submissionKey,
      };
      const soundFileIds = cleanFileIds(record && record.soundFileIds, "sound", storageContract);
      const paymentFileIds = cleanFileIds(record && record.paymentFileIds, "payment", storageContract);
      if (!soundFileIds.length) throw validationError("MISSING_SOUND_EVIDENCE", "Sound-system evidence is required");
      if (!paymentFileIds.length) throw validationError("MISSING_PAYMENT_EVIDENCE", "Payment evidence is required");
      if (typeof soundEvidenceVerifier?.verifySubmissionFiles === "function") {
        await soundEvidenceVerifier.verifySubmissionFiles({
          submissionKey,
          soundFileIds,
          paymentFileIds,
        });
      }
      const now = new Date();
      const bucket = shanghaiDateBucket(now);
      const entryPayloadHash = payloadHash({ clubName, soundFileIds, paymentFileIds });
      const entry = {
        id: submissionDocumentId(isCloudbase ? ownerKey : "local", submissionKey),
        kind: "submission",
        clubName,
        soundFileIds,
        soundImageCount: soundFileIds.length,
        paymentFileIds,
        paymentImageCount: paymentFileIds.length,
        submittedAt: now.toISOString(),
        version: 4,
        status: "new",
        idempotencyKeyHash: sha256(submissionKey),
        payloadHash: entryPayloadHash,
        ...(isCloudbase ? { submitterKey: ownerKey, rateLimitBucket: bucket } : {}),
      };
      const result = await target.insert(entry, {
        ownerKey,
        bucket,
        maxPerDay: resolved.maxPerDay || 0,
      });
      if (!result.created) {
        const existing = validatePersistedEntry(result.existing, entry.id);
        if (existing.payloadHash !== entryPayloadHash) {
          throw storeError(
            "SOUND_SUBMISSION_IDEMPOTENCY_CONFLICT",
            "The submission idempotency key was already used for different evidence.",
            409,
          );
        }
        return { ok: true, id: entry.id, duplicate: true };
      }
      return { ok: true, id: entry.id, duplicate: false };
    },

    async publicStatus() {
      const evidenceReady = !requiresEvidenceVerifier
        || typeof soundEvidenceVerifier?.verifySubmissionFiles === "function";
      return {
        schemaVersion: "weekly_sound_submission_public_status.v1",
        acceptingSubmissions: Boolean(backend) && evidenceReady,
        persistence: {
          configured: resolved.configured,
          backend: backend?.name || "disabled",
          multiInstanceSafe: Boolean(backend?.multiInstanceSafe),
          maxSubmissionsPerDay: backend?.name === "cloudbase" ? resolved.maxPerDay : null,
          evidenceVerificationConfigured: evidenceReady,
        },
        safety: {
          paymentFileIdsExposed: false,
          sensitiveReviewFieldsExposed: false,
          privateQueueExposed: false,
        },
      };
    },

    async getInternalById(id) {
      const normalizedId = String(id || "").trim();
      if (!normalizedId) return null;
      return requireBackend().getById(normalizedId);
    },

    async count() {
      return { total: await requireBackend().count() };
    },

    async listInternal({ limit = 50, status = "" } = {}) {
      const normalizedLimit = Math.min(100, Math.max(1, Number.parseInt(String(limit), 10) || 50));
      const normalizedStatus = String(status || "").trim();
      if (normalizedStatus && !/^[A-Za-z0-9_-]{1,32}$/.test(normalizedStatus)) {
        throw validationError("INVALID_REVIEW_STATUS", "Review status filter is invalid");
      }
      return requireBackend().list({ limit: normalizedLimit, status: normalizedStatus });
    },

    async listQuotaReconciliationInternal({ limit = 50 } = {}) {
      const normalizedLimit = Math.min(100, Math.max(1, Number.parseInt(String(limit), 10) || 50));
      const target = requireBackend();
      if (typeof target.listQuotaReconciliation !== "function") {
        throw storeError(
          "SOUND_SUBMISSIONS_RECONCILIATION_UNAVAILABLE",
          "Sound quota reconciliation is available only for the CloudBase backend.",
        );
      }
      return target.listQuotaReconciliation({ limit: normalizedLimit });
    },
  };
}
