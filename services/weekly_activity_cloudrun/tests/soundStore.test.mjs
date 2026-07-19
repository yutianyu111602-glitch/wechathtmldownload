import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createSoundStore } from "../src/soundStore.mjs";

const ENV_ID = "test-env";
const DEFAULT_KEY = "stable_submission_key_store_0001";
const soundEvidenceVerifier = { async verifySubmissionFiles() {} };

function submission(overrides = {}) {
  const submissionKey = overrides.submissionKey || DEFAULT_KEY;
  return {
    submissionKey,
    clubName: "DADA Test",
    soundFileIds: [`cloud://${ENV_ID}.bucket/atlas/sound-submissions/${submissionKey}/sound/equipment-1.jpg`],
    soundImageCount: 1,
    paymentFileIds: [`cloud://${ENV_ID}.bucket/atlas/sound-submissions/${submissionKey}/payment/private-proof-1.jpg`],
    paymentImageCount: 1,
    submittedAt: "2026-07-19T12:00:00.000Z",
    version: 4,
    ...overrides,
  };
}

function createFakeCloudbaseDatabase({
  failSubmissionCreates = 0,
  onSubmissionCreateFailure = null,
  onConditionalRemove = null,
} = {}) {
  const documents = new Map();
  let remainingSubmissionCreateFailures = failSubmissionCreates;
  const collection = {
    doc(id) {
      return {
        async set(record) {
          documents.set(id, structuredClone(record));
          return { updated: 1 };
        },
        async create(record) {
          if (documents.has(id)) {
            throw Object.assign(new Error("duplicate document"), { code: "DUPLICATE_DOCUMENT" });
          }
          if (record?.kind === "submission" && remainingSubmissionCreateFailures > 0) {
            remainingSubmissionCreateFailures -= 1;
            onSubmissionCreateFailure?.({ documents, id, record });
            throw Object.assign(new Error("injected submission create failure"), { code: "INJECTED_WRITE_FAILURE" });
          }
          documents.set(id, structuredClone(record));
          return { inserted: 1 };
        },
        async get() {
          return { data: documents.has(id) ? [structuredClone(documents.get(id))] : [] };
        },
        async remove() {
          const deleted = documents.delete(id);
          return { deleted: deleted ? 1 : 0 };
        },
      };
    },
    where(query = {}) {
      const matching = () => [...documents.values()].filter((record) => (
        Object.entries(query).every(([key, value]) => record[key] === value)
      ));
      return {
        async count() {
          return { total: matching().length };
        },
        limit(value) {
          return {
            async get() {
              return { data: matching().slice(0, value).map((record) => structuredClone(record)) };
            },
          };
        },
        async remove() {
          onConditionalRemove?.({ documents, query });
          let deleted = 0;
          for (const [id, record] of documents.entries()) {
            if (Object.entries(query).every(([key, value]) => record[key] === value)) {
              documents.delete(id);
              deleted += 1;
            }
          }
          return { deleted };
        },
      };
    },
    async count() {
      return { total: documents.size };
    },
  };
  return {
    documents,
    database: {
      collection(name) {
        assert.equal(name, "weekly_sound_submissions");
        return collection;
      },
    },
  };
}

function cloudbaseEnv(overrides = {}) {
  return {
    NODE_ENV: "production",
    SOUND_SUBMISSIONS_BACKEND: "cloudbase",
    SOUND_SUBMISSIONS_COLLECTION: "weekly_sound_submissions",
    SOUND_SUBMISSIONS_MAX_PER_DAY: "25",
    CLOUDBASE_ENV_ID: "test-env",
    ...overrides,
  };
}

test("production CloudBase SDK exposes the document operations required by the sound store", async () => {
  const module = await import("@cloudbase/js-sdk");
  const cloudbase = module.default || module;
  const database = cloudbase.init({ env: "test-env" }).database();
  const collection = database.collection("weekly_sound_submissions");
  const document = collection.doc("sound_sdk_contract");

  assert.equal(typeof document.create, "function");
  assert.equal(typeof document.get, "function");
  assert.equal(typeof document.remove, "function");
  assert.equal(typeof collection.where, "function");
  assert.equal(typeof collection.where({ kind: "quota_slot" }).remove, "function");
  assert.equal(typeof database.runTransaction, "function");
});

test("sound store creates a missing submissions directory on first write", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "sound-store-clean-"));
  const soundDir = path.join(root, "new", "sounds");
  const store = createSoundStore({ soundDir, env: { CLOUDBASE_ENV_ID: ENV_ID }, soundEvidenceVerifier });

  const result = await store.submit(submission());

  assert.equal(result.ok, true);
  const persisted = JSON.parse(await readFile(path.join(soundDir, "submissions.json"), "utf8"));
  assert.equal(persisted.length, 1);
  assert.deepEqual(persisted[0].paymentFileIds, submission().paymentFileIds);
});

test("sound store keeps review evidence private and exposes only a public status", async () => {
  const soundDir = await mkdtemp(path.join(os.tmpdir(), "sound-store-redaction-"));
  const store = createSoundStore({ soundDir, env: { CLOUDBASE_ENV_ID: ENV_ID }, soundEvidenceVerifier });
  const submitted = await store.submit(submission());
  const submissionsPath = path.join(soundDir, "submissions.json");
  const persisted = JSON.parse(await readFile(submissionsPath, "utf8"));
  persisted[0].reviewNotes = "private reviewer note";
  persisted[0].reviewerUserId = "reviewer-secret-id";
  await writeFile(submissionsPath, JSON.stringify(persisted, null, 2), "utf8");

  const status = await store.publicStatus();
  assert.equal(status.schemaVersion, "weekly_sound_submission_public_status.v1");
  assert.equal(status.acceptingSubmissions, true);
  assert.equal(status.total, undefined);
  assert.equal(status.items, undefined);
  assert.equal(status.safety.paymentFileIdsExposed, false);
  assert.equal(status.safety.sensitiveReviewFieldsExposed, false);

  const internal = await store.getInternalById(submitted.id);
  assert.deepEqual(internal.paymentFileIds, submission().paymentFileIds);
  assert.equal(internal.status, "new");
  assert.equal(internal.reviewNotes, "private reviewer note");
  assert.equal(internal.reviewerUserId, "reviewer-secret-id");
});

test("sound store rejects incomplete and oversized untrusted submissions", async () => {
  const soundDir = await mkdtemp(path.join(os.tmpdir(), "sound-store-validation-"));
  const store = createSoundStore({ soundDir, env: { CLOUDBASE_ENV_ID: ENV_ID }, soundEvidenceVerifier });

  await assert.rejects(
    store.submit(submission({ clubName: "" })),
    (error) => error?.code === "MISSING_CLUB_NAME" && error?.statusCode === 400,
  );
  await assert.rejects(
    store.submit(submission({ soundFileIds: [] })),
    (error) => error?.code === "MISSING_SOUND_EVIDENCE" && error?.statusCode === 400,
  );
  await assert.rejects(
    store.submit(submission({ paymentFileIds: [] })),
    (error) => error?.code === "MISSING_PAYMENT_EVIDENCE" && error?.statusCode === 400,
  );
  await assert.rejects(
    store.submit(submission({ soundFileIds: Array.from({ length: 10 }, (_, index) => `cloud://sound/${index}`) })),
    (error) => error?.code === "TOO_MANY_SOUND_FILES" && error?.statusCode === 400,
  );
});

test("sound store fails closed on corrupt file state and never overwrites it with an empty queue", async () => {
  const soundDir = await mkdtemp(path.join(os.tmpdir(), "sound-store-corrupt-"));
  const submissionsPath = path.join(soundDir, "submissions.json");
  const corruptPayload = "{ definitely-not-json";
  await writeFile(submissionsPath, corruptPayload, "utf8");
  const store = createSoundStore({ soundDir, env: { CLOUDBASE_ENV_ID: ENV_ID }, soundEvidenceVerifier });

  await assert.rejects(
    store.submit(submission()),
    (error) => error?.code === "SOUND_SUBMISSIONS_CORRUPT" && error?.statusCode === 503,
  );
  assert.equal(await readFile(submissionsPath, "utf8"), corruptPayload);
});

test("production sound store disables writes unless a durable backend is explicitly configured", async () => {
  const soundDir = await mkdtemp(path.join(os.tmpdir(), "sound-store-production-file-"));
  const store = createSoundStore({
    env: {
      NODE_ENV: "production",
      SOUND_SUBMISSIONS_DIR: soundDir,
    },
  });

  const status = await store.publicStatus();
  assert.equal(status.acceptingSubmissions, false);
  assert.equal(status.persistence.configured, false);
  assert.equal(status.persistence.backend, "disabled");
  await assert.rejects(
    store.submit(submission()),
    (error) => error?.code === "SOUND_SUBMISSIONS_NOT_CONFIGURED" && error?.statusCode === 503,
  );
});

test("cloudbase backend inserts independent documents so concurrent instances cannot overwrite the queue", async () => {
  const { documents, database: cloudbaseDatabase } = createFakeCloudbaseDatabase();
  const env = cloudbaseEnv();
  const firstStore = createSoundStore({ cloudbaseDatabase, env, soundEvidenceVerifier });
  const secondStore = createSoundStore({ cloudbaseDatabase, env, soundEvidenceVerifier });
  const ownerKey = "a".repeat(64);

  const results = await Promise.all(
    Array.from({ length: 20 }, (_, index) => {
      const store = index % 2 === 0 ? firstStore : secondStore;
      return store.submit(
        submission({ clubName: `Club ${index}`, submissionKey: `submission_key_${index.toString().padStart(4, "0")}` }),
        { ownerKey },
      );
    }),
  );

  assert.equal(new Set(results.map((result) => result.id)).size, 20);
  assert.equal([...documents.values()].filter((record) => record.kind === "submission").length, 20);
  assert.deepEqual(await secondStore.count(), { total: 20 });
  const first = await firstStore.getInternalById(results[0].id);
  assert.equal(first.clubName, "Club 0");
});

test("cloudbase backend fails closed when a stored document has the wrong shape", async () => {
  const cloudbaseDatabase = {
    collection() {
      return {
        doc() {
          return {
            async get() {
              return { data: [{ id: "sound_bad", clubName: "Bad", soundFileIds: "not-an-array" }] };
            },
          };
        },
      };
    },
  };
  const store = createSoundStore({
    cloudbaseDatabase,
    env: {
      NODE_ENV: "production",
      SOUND_SUBMISSIONS_BACKEND: "cloudbase",
      SOUND_SUBMISSIONS_COLLECTION: "weekly_sound_submissions",
      SOUND_SUBMISSIONS_MAX_PER_DAY: "5",
      CLOUDBASE_ENV_ID: "test-env",
    },
  });

  await assert.rejects(
    store.getInternalById("sound_bad"),
    (error) => error?.code === "SOUND_SUBMISSIONS_CORRUPT" && error?.statusCode === 503,
  );
});

test("cloudbase backend makes retries idempotent across service instances", async () => {
  const { documents, database } = createFakeCloudbaseDatabase();
  const env = cloudbaseEnv({ SOUND_SUBMISSIONS_MAX_PER_DAY: "2" });
  const firstStore = createSoundStore({ cloudbaseDatabase: database, env, soundEvidenceVerifier });
  const secondStore = createSoundStore({ cloudbaseDatabase: database, env, soundEvidenceVerifier });
  const record = submission({ submissionKey: "stable_submission_key_0001" });
  const context = { ownerKey: "b".repeat(64) };

  const [first, second] = await Promise.all([
    firstStore.submit(record, context),
    secondStore.submit(record, context),
  ]);

  assert.equal(first.id, second.id);
  assert.equal([...documents.values()].filter((entry) => entry.kind === "submission").length, 1);
  assert.equal([...documents.values()].filter((entry) => entry.kind === "quota_slot").length, 1);
  assert.equal([first.duplicate, second.duplicate].filter(Boolean).length, 1);
});

test("cloudbase backend rejects reuse of an idempotency key for a different payload", async () => {
  const { database } = createFakeCloudbaseDatabase();
  const store = createSoundStore({ cloudbaseDatabase: database, env: cloudbaseEnv(), soundEvidenceVerifier });
  const context = { ownerKey: "c".repeat(64) };
  await store.submit(submission({ submissionKey: "stable_submission_key_0002" }), context);

  await assert.rejects(
    store.submit(submission({ clubName: "Different club", submissionKey: "stable_submission_key_0002" }), context),
    (error) => error?.code === "SOUND_SUBMISSION_IDEMPOTENCY_CONFLICT" && error?.statusCode === 409,
  );
});

test("cloudbase quota slots enforce an exact shared daily limit across service instances", async () => {
  const { documents, database } = createFakeCloudbaseDatabase();
  const env = cloudbaseEnv({ SOUND_SUBMISSIONS_MAX_PER_DAY: "2" });
  const stores = [
    createSoundStore({ cloudbaseDatabase: database, env, soundEvidenceVerifier }),
    createSoundStore({ cloudbaseDatabase: database, env, soundEvidenceVerifier }),
  ];
  const context = { ownerKey: "d".repeat(64) };

  const results = await Promise.allSettled(
    Array.from({ length: 5 }, (_, index) => stores[index % 2].submit(
      submission({ clubName: `Club ${index}`, submissionKey: `quota_submission_key_${index}` }),
      context,
    )),
  );

  assert.equal(results.filter((result) => result.status === "fulfilled").length, 2);
  const rejected = results.filter((result) => result.status === "rejected");
  assert.equal(rejected.length, 3);
  assert.ok(rejected.every((result) => (
    result.reason?.code === "SOUND_SUBMISSION_RATE_LIMITED" && result.reason?.statusCode === 429
  )));
  assert.equal([...documents.values()].filter((entry) => entry.kind === "submission").length, 2);
  assert.equal([...documents.values()].filter((entry) => entry.kind === "quota_slot").length, 2);
});

test("cloudbase retains a failed quota claim until operator reconciliation", async () => {
  const { documents, database } = createFakeCloudbaseDatabase({ failSubmissionCreates: 1 });
  const env = cloudbaseEnv({ SOUND_SUBMISSIONS_MAX_PER_DAY: "1" });
  const store = createSoundStore({ cloudbaseDatabase: database, env, soundEvidenceVerifier });
  const context = { ownerKey: "f".repeat(64) };

  await assert.rejects(
    store.submit(submission({ submissionKey: "quota_compensation_failure_0001" }), context),
    (error) => error?.code === "SOUND_SUBMISSIONS_WRITE_FAILED" && error?.statusCode === 503,
  );
  assert.equal([...documents.values()].filter((entry) => entry.kind === "quota_slot").length, 1);
  assert.equal([...documents.values()].filter((entry) => entry.kind === "quota_reconciliation").length, 1);

  await assert.rejects(
    store.submit(
      submission({ submissionKey: "quota_compensation_retry_0002" }),
      context,
    ),
    (error) => error?.code === "SOUND_SUBMISSION_RATE_LIMITED" && error?.statusCode === 429,
  );
  assert.equal([...documents.values()].filter((entry) => entry.kind === "quota_slot").length, 1);
  assert.equal([...documents.values()].filter((entry) => entry.kind === "submission").length, 0);
});

test("cloudbase failure handling never removes a quota slot no longer owned by the failed submission", async () => {
  const { documents, database } = createFakeCloudbaseDatabase({
    failSubmissionCreates: 1,
    onSubmissionCreateFailure({ documents: currentDocuments }) {
      const slot = [...currentDocuments.values()].find((entry) => entry.kind === "quota_slot");
      slot.submissionId = "sound_foreign_submission";
    },
  });
  const store = createSoundStore({
    cloudbaseDatabase: database,
    env: cloudbaseEnv({ SOUND_SUBMISSIONS_MAX_PER_DAY: "1" }),
    soundEvidenceVerifier,
  });

  await assert.rejects(
    store.submit(
      submission({ submissionKey: "quota_foreign_owner_failure_0001" }),
      { ownerKey: "0".repeat(64) },
    ),
    (error) => error?.code === "SOUND_SUBMISSIONS_WRITE_FAILED",
  );
  const slots = [...documents.values()].filter((entry) => entry.kind === "quota_slot");
  assert.equal(slots.length, 1);
  assert.equal(slots[0].submissionId, "sound_foreign_submission");
});

test("cloudbase failure handling cannot delete a slot when a submission wins the read-delete race", async () => {
  let contestedSubmission = null;
  let conditionalRemoveCalls = 0;
  const { documents, database } = createFakeCloudbaseDatabase({
    failSubmissionCreates: 1,
    onSubmissionCreateFailure({ id, record }) {
      contestedSubmission = { id, record: structuredClone(record) };
    },
    onConditionalRemove({ documents: currentDocuments }) {
      conditionalRemoveCalls += 1;
      currentDocuments.set(contestedSubmission.id, contestedSubmission.record);
    },
  });
  const store = createSoundStore({
    cloudbaseDatabase: database,
    env: cloudbaseEnv({ SOUND_SUBMISSIONS_MAX_PER_DAY: "1" }),
    soundEvidenceVerifier,
  });

  await assert.rejects(
    store.submit(
      submission({ submissionKey: "quota_read_delete_race_0001" }),
      { ownerKey: "1".repeat(64) },
    ),
    (error) => error?.code === "SOUND_SUBMISSIONS_WRITE_FAILED",
  );

  assert.equal(conditionalRemoveCalls, 0);
  assert.equal([...documents.values()].filter((entry) => entry.kind === "quota_slot").length, 1);
});

test("cloudbase preserves failed claims in an operator-visible reconciliation queue", async () => {
  const { documents, database } = createFakeCloudbaseDatabase({ failSubmissionCreates: 1 });
  const store = createSoundStore({
    cloudbaseDatabase: database,
    env: cloudbaseEnv({ SOUND_SUBMISSIONS_MAX_PER_DAY: "1" }),
    soundEvidenceVerifier,
  });

  await assert.rejects(
    store.submit(
      submission({ submissionKey: "quota_reconciliation_queue_0001" }),
      { ownerKey: "2".repeat(64) },
    ),
    (error) => error?.code === "SOUND_SUBMISSIONS_WRITE_FAILED",
  );

  const queue = await store.listQuotaReconciliationInternal({ limit: 10 });
  assert.equal([...documents.values()].filter((entry) => entry.kind === "quota_slot").length, 1);
  assert.equal(queue.total, 1);
  assert.equal(queue.items.length, 1);
  assert.equal(queue.items[0].schemaVersion, "weekly_sound_quota_reconciliation.v1");
  assert.equal(queue.items[0].kind, "quota_reconciliation");
  assert.match(queue.items[0].slotId, /^sound_quota_/);
  assert.match(queue.items[0].submissionId, /^sound_/);
  assert.equal(queue.items[0].reason, "submission_write_unverified");
  assert.equal(queue.items[0].manualVerificationRequired, true);
});

test("production CloudBase persistence stays disabled when the durable quota is not configured", async () => {
  const { database } = createFakeCloudbaseDatabase();
  const env = cloudbaseEnv();
  delete env.SOUND_SUBMISSIONS_MAX_PER_DAY;
  const store = createSoundStore({ cloudbaseDatabase: database, env });

  const status = await store.publicStatus();
  assert.equal(status.acceptingSubmissions, false);
  await assert.rejects(
    store.submit(submission({ submissionKey: "stable_submission_key_0003" }), { ownerKey: "e".repeat(64) }),
    (error) => error?.code === "SOUND_SUBMISSIONS_NOT_CONFIGURED" && error?.statusCode === 503,
  );
});
