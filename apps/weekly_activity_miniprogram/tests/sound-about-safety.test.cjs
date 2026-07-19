const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appRoot = path.resolve(__dirname, "..");

function loadSoundPage(options = {}) {
  const filename = path.join(appRoot, "pages/sound/sound.js");
  const code = fs.readFileSync(filename, "utf8");
  const postedRecords = [];
  const storedValues = new Map(Array.isArray(options.initialStorage) ? options.initialStorage : []);
  let pageConfig = null;
  let uploadIndex = 0;
  const uploadOutcomes = Array.isArray(options.uploadOutcomes) ? [...options.uploadOutcomes] : [];
  const deleteOutcomes = Array.isArray(options.deleteOutcomes) ? [...options.deleteOutcomes] : [];
  const toasts = [];
  const deletedFileLists = [];

  const sandbox = {
    console,
    Date,
    Math,
    Page(config) {
      pageConfig = config;
    },
    getApp() {
      return {
        globalData: {
          cloud: {
            cloudClient: {
              async uploadFile({ cloudPath }) {
                uploadIndex += 1;
                const outcome = uploadOutcomes.shift();
                if (outcome instanceof Error) throw outcome;
                if (outcome && outcome.fileID) return outcome;
                return { fileID: `cloud://test-env.bucket/${cloudPath}` };
              },
              async deleteFile({ fileList }) {
                deletedFileLists.push([...fileList]);
                if (options.deleteError) throw options.deleteError;
                const outcome = deleteOutcomes.shift();
                if (outcome instanceof Error) throw outcome;
                if (typeof outcome === "function") return outcome(fileList);
                if (outcome) return outcome;
                return { fileList: fileList.map((fileID) => ({ fileID, status: 0 })) };
              },
              async callFunction({ name, data }) {
                assert.equal(name, "soundSubmissionGateway");
                if (options.postError) throw options.postError;
                postedRecords.push(data.body);
                if (options.gatewayGate) await options.gatewayGate;
                return { result: { ok: true, id: `sound-backend-${postedRecords.length}` } };
              },
            },
          },
        },
      };
    },
    wx: {
      getStorageSync(key) {
        return storedValues.get(key) || "";
      },
      setStorageSync(key, value) {
        if (options.storageError && key === "atlasSoundSubmissions:v1") throw options.storageError;
        if (options.journalStorageError && key === "atlasSoundUploadCleanupJournal:v1") {
          throw options.journalStorageError;
        }
        storedValues.set(key, value);
      },
      showToast(options) { toasts.push(options); },
      chooseImage(request) {
        if (options.chooseImageResult) request.success(options.chooseImageResult);
      },
      previewImage() {},
      navigateBack() {},
    },
    require(request) {
      if (request.endsWith("utils/i18n")) {
        return {
          applyLanguageChrome() {},
          normalizeLang: (lang) => lang || "zh",
          text: () => ({
            uploading: "uploading",
            images: "images",
            paymentImages: "payment images",
            uploadFailed: "upload failed",
            submitted: "submitted",
            submittedLocal: "saved locally",
            maxSoundImages: "up to 4 equipment photos",
            maxPaymentImages: "up to 9 proof images",
            soundImageTooLarge: "equipment photo must be under 1MB",
            paymentImageTooLarge: "proof image must be under 10MB",
          }),
        };
      }
      if (request.endsWith("utils/share")) {
        return {
          enableShareMenu() {},
          buildSimpleShare() { return {}; },
          buildSimpleTimeline() { return {}; },
        };
      }
      throw new Error(`Unexpected require: ${request}`);
    },
  };

  vm.runInNewContext(code, sandbox, { filename });
  assert.ok(pageConfig, "sound page should register itself");
  const page = {
    ...pageConfig,
    data: JSON.parse(JSON.stringify(pageConfig.data)),
    setData(patch) {
      for (const [key, value] of Object.entries(patch)) {
        const parts = key.split(".");
        let cursor = this.data;
        while (parts.length > 1) {
          const part = parts.shift();
          cursor[part] = cursor[part] || {};
          cursor = cursor[part];
        }
        cursor[parts[0]] = value;
      }
    },
  };

  return { page, postedRecords, storedValues, toasts, deletedFileLists, getUploadCount: () => uploadIndex };
}

test("sound submission sends uploaded payment file IDs without a ReferenceError", async () => {
  const { page, postedRecords } = loadSoundPage();
  page.data.form = {
    clubName: "DADA Test",
    images: ["wxfile://sound.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  };

  await page.submitForm();

  assert.equal(postedRecords.length, 1);
  assert.deepEqual(
    Array.from(postedRecords[0].paymentFileIds),
    [`cloud://test-env.bucket/atlas/sound-submissions/${postedRecords[0].submissionKey}/payment/${postedRecords[0].paymentFileIds[0].split("/").pop()}`],
  );
  assert.equal(postedRecords[0].paymentImageCount, 1);
  assert.match(postedRecords[0].submissionKey, /^[A-Za-z0-9_-]{12,128}$/);
  assert.match(postedRecords[0].soundFileIds[0], new RegExp(`/atlas/sound-submissions/${postedRecords[0].submissionKey}/sound/`));
});

test("sound submission keeps the form and never posts when every payment upload fails", async () => {
  const { page, postedRecords } = loadSoundPage({
    uploadOutcomes: [
      { fileID: "cloud://sound-test/equipment" },
      new Error("payment upload failed"),
    ],
  });
  const originalForm = {
    clubName: "DADA Test",
    images: ["wxfile://sound.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  };
  page.data.form = JSON.parse(JSON.stringify(originalForm));

  await page.submitForm();

  assert.equal(postedRecords.length, 0);
  assert.equal(page.data.submissions.length, 0);
  assert.deepEqual(page.data.form, originalForm);
  assert.equal(page.data.submitting, false);
});

test("sound submission never silently drops a failed evidence upload", async () => {
  const { page, postedRecords } = loadSoundPage({
    uploadOutcomes: [
      undefined,
      new Error("second sound upload failed"),
    ],
  });
  const originalForm = {
    clubName: "DADA Test",
    images: ["wxfile://sound-one.jpg", "wxfile://sound-two.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  };
  page.data.form = JSON.parse(JSON.stringify(originalForm));

  await page.submitForm();

  assert.equal(postedRecords.length, 0);
  assert.equal(page.data.submissions.length, 0);
  assert.deepEqual(page.data.form, originalForm);
});

test("sound submission deletes every successful upload when a later evidence upload fails", async () => {
  const { page, postedRecords, deletedFileLists } = loadSoundPage({
    uploadOutcomes: [
      undefined,
      undefined,
      new Error("payment upload failed"),
    ],
  });
  const originalForm = {
    clubName: "DADA Test",
    images: ["wxfile://sound-one.jpg", "wxfile://sound-two.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  };
  page.data.form = JSON.parse(JSON.stringify(originalForm));

  await page.submitForm();

  assert.equal(postedRecords.length, 0);
  assert.equal(deletedFileLists.length, 1);
  assert.equal(deletedFileLists[0].length, 2);
  assert.ok(deletedFileLists[0].every((fileID) => fileID.includes("/sound/")));
  assert.deepEqual(page.data.form, originalForm);
  assert.equal(page.data.submitting, false);
  assert.equal(page.data.uploadProgress, "");
});

test("sound submission cleans uploads and resets state when local persistence fails", async () => {
  const originalForm = {
    clubName: "DADA Test",
    images: ["wxfile://sound.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  };
  const { page, postedRecords, deletedFileLists } = loadSoundPage({
    storageError: new Error("storage quota exceeded"),
    deleteError: new Error("cloud cleanup temporarily failed"),
  });
  page.data.form = JSON.parse(JSON.stringify(originalForm));

  await page.submitForm();

  assert.equal(postedRecords.length, 0);
  assert.equal(deletedFileLists.length, 1, "cleanup must still be attempted");
  assert.equal(deletedFileLists[0].length, 2);
  assert.deepEqual(page.data.form, originalForm);
  assert.equal(page.data.submissions.length, 0);
  assert.equal(page.data.submitting, false);
  assert.equal(page.data.uploadProgress, "");
});

test("sound submission keeps a stable pending record and can retry without re-uploading", async () => {
  const options = { postError: new Error("backend unavailable") };
  const { page, postedRecords } = loadSoundPage(options);
  page.data.form = {
    clubName: "DADA Test",
    images: ["wxfile://sound.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  };

  await page.submitForm();

  assert.equal(page.data.submissions.length, 1);
  assert.equal(page.data.submissions[0].syncStatus, "pending");
  const stableKey = page.data.submissions[0].submissionKey;
  const stableSoundIds = Array.from(page.data.submissions[0].soundFileIds);
  const stablePaymentIds = Array.from(page.data.submissions[0].paymentFileIds);

  options.postError = null;
  await page.retryPendingSubmissions();

  assert.equal(postedRecords.length, 1);
  assert.equal(postedRecords[0].submissionKey, stableKey);
  assert.deepEqual(Array.from(postedRecords[0].soundFileIds), stableSoundIds);
  assert.deepEqual(Array.from(postedRecords[0].paymentFileIds), stablePaymentIds);
  assert.equal(page.data.submissions[0].syncStatus, "synced");
});

test("pending retry coalesces the same submission and preserves concurrent additions by key", async () => {
  let releaseGateway;
  const gatewayGate = new Promise((resolve) => { releaseGateway = resolve; });
  const { page, postedRecords } = loadSoundPage({ gatewayGate });
  const first = {
    submissionKey: "sound_coalesce_123",
    clubName: "Coalesce Club",
    soundFileIds: ["cloud://test-env.bucket/atlas/sound-submissions/sound_coalesce_123/sound/equipment.jpg"],
    paymentFileIds: ["cloud://test-env.bucket/atlas/sound-submissions/sound_coalesce_123/payment/proof.jpg"],
    syncStatus: "pending",
    submittedAt: "2026-07-19T00:00:00.000Z",
  };
  page.saveSubmissions([first]);

  const retry = page.retryPendingSubmissions();
  await new Promise((resolve) => setImmediate(resolve));
  const duplicate = page.callSubmissionGatewayOnce(first);
  const concurrent = { ...first, submissionKey: "sound_concurrent_456", syncStatus: "pending" };
  page.saveSubmissions([concurrent, ...page.data.submissions]);
  releaseGateway();
  await Promise.all([retry, duplicate]);

  assert.equal(postedRecords.length, 1, "one submission key must own one in-flight gateway call");
  assert.equal(page.data.submissions.length, 2);
  assert.equal(page.data.submissions.find((item) => item.submissionKey === first.submissionKey).syncStatus, "synced");
  assert.equal(page.data.submissions.find((item) => item.submissionKey === concurrent.submissionKey).syncStatus, "pending");
});

test("legacy pending evidence is not sent under the new submission-bound storage contract", async () => {
  const { page, postedRecords } = loadSoundPage();
  page.data.submissions = [{
    submissionKey: "sound_legacy_pending_123",
    clubName: "Legacy Club",
    soundFileIds: ["cloud://test-env.bucket/atlas/sound-submissions/sound/legacy.jpg"],
    soundImageCount: 1,
    paymentFileIds: ["cloud://test-env.bucket/atlas/sound-submissions/payment/legacy.jpg"],
    paymentImageCount: 1,
    submittedAt: "2026-07-18T00:00:00.000Z",
    syncStatus: "pending",
  }];

  await page.retryPendingSubmissions();

  assert.equal(postedRecords.length, 0);
  assert.equal(page.data.submissions[0].syncStatus, "needs_resubmit");
});

test("partial remote cleanup keeps a retryable journal and local pending record until every file is deleted", async () => {
  const soundFileId = "cloud://test-env.bucket/atlas/sound-submissions/sound_pending_123/sound/equipment.jpg";
  const paymentFileId = "cloud://test-env.bucket/atlas/sound-submissions/sound_pending_123/payment/proof.jpg";
  const { page, storedValues, deletedFileLists } = loadSoundPage({
    deleteOutcomes: [
      {
        fileList: [
          { fileID: soundFileId, status: 0, errMsg: "ok" },
          { fileID: paymentFileId, status: -1, errMsg: "permission denied" },
        ],
      },
      { fileList: [{ fileID: paymentFileId, status: 0, errMsg: "ok" }] },
    ],
  });
  const pending = {
    submissionKey: "sound_pending_123",
    clubName: "Pending Club",
    soundFileIds: [soundFileId],
    paymentFileIds: [paymentFileId],
    syncStatus: "pending",
    submittedAt: "2026-07-19T00:00:00.000Z",
  };
  page.saveSubmissions([pending]);

  await page.removeSubmission({ currentTarget: { dataset: { index: 0 } } });

  assert.equal(page.data.submissions.length, 1, "local evidence must remain while one remote deletion failed");
  assert.equal(page.data.submissions[0].syncStatus, "cleanup_pending");
  const journalAfterPartial = JSON.parse(storedValues.get("atlasSoundUploadCleanupJournal:v1"));
  assert.equal(journalAfterPartial.length, 1);
  assert.deepEqual(Array.from(journalAfterPartial[0].fileIds), [paymentFileId]);
  assert.deepEqual(deletedFileLists[0], [soundFileId, paymentFileId]);

  await page.retryCleanupJournal();

  assert.equal(page.data.submissions.length, 0, "the local record may be removed only after verified cleanup");
  assert.deepEqual(JSON.parse(storedValues.get("atlasSoundUploadCleanupJournal:v1")), []);
  assert.deepEqual(deletedFileLists[1], [paymentFileId], "retry must target only the file that actually failed");
});

test("failed rollback after a later upload error persists the successful file IDs for restart cleanup", async () => {
  const { page, storedValues, deletedFileLists } = loadSoundPage({
    uploadOutcomes: [
      undefined,
      new Error("payment upload failed"),
    ],
    deleteOutcomes: [
      (fileList) => ({
        fileList: fileList.map((fileID) => ({
          fileID,
          status: -1,
          errMsg: "temporary failure",
        })),
      }),
    ],
  });
  page.data.form = {
    clubName: "Restart Safe Club",
    images: ["wxfile://sound.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  };

  await page.submitForm();

  assert.equal(page.data.submissions.length, 0);
  assert.equal(deletedFileLists.length, 1);
  const journal = JSON.parse(storedValues.get("atlasSoundUploadCleanupJournal:v1"));
  assert.equal(journal.length, 1);
  assert.equal(journal[0].status, "cleanup_pending");
  assert.deepEqual(Array.from(journal[0].fileIds), deletedFileLists[0]);
  assert.match(journal[0].fileIds[0], /\/atlas\/sound-submissions\/sound_[A-Za-z0-9_-]+\/sound\//);
});

test("a corrupt cleanup journal fails closed before any new remote upload", async () => {
  const corruptJournal = "{not-valid-json";
  const { page, storedValues, getUploadCount } = loadSoundPage({
    initialStorage: [["atlasSoundUploadCleanupJournal:v1", corruptJournal]],
  });
  page.data.form = {
    clubName: "Fail Closed Club",
    images: ["wxfile://sound.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  };

  await page.submitForm();

  assert.equal(getUploadCount(), 0, "unreadable recovery state must block new remote writes");
  assert.equal(storedValues.get("atlasSoundUploadCleanupJournal:v1"), corruptJournal);
  assert.deepEqual(page.data.form, {
    clubName: "Fail Closed Club",
    images: ["wxfile://sound.jpg"],
    paymentImages: ["wxfile://payment.jpg"],
  });
});

test("deleteFile status zero with a failing errMsg remains cleanup_pending", async () => {
  const soundFileId = "cloud://test-env.bucket/atlas/sound-submissions/sound_errmsg_123/sound/equipment.jpg";
  const { page, storedValues } = loadSoundPage({
    deleteOutcomes: [{
      fileList: [{ fileID: soundFileId, status: 0, errMsg: "deleteFile:fail permission denied" }],
    }],
  });
  page.saveSubmissions([{
    submissionKey: "sound_errmsg_123",
    clubName: "ErrMsg Club",
    soundFileIds: [soundFileId],
    paymentFileIds: [],
    syncStatus: "needs_resubmit",
  }]);

  await page.removeSubmission({ currentTarget: { dataset: { index: 0 } } });

  assert.equal(page.data.submissions[0].syncStatus, "cleanup_pending");
  const journal = JSON.parse(storedValues.get("atlasSoundUploadCleanupJournal:v1"));
  assert.deepEqual(Array.from(journal[0].fileIds), [soundFileId]);
});

test("removing a synced record never deletes backend evidence", async () => {
  const { page, deletedFileLists } = loadSoundPage();
  page.saveSubmissions([{
    submissionKey: "sound_synced_123",
    clubName: "Synced Club",
    soundFileIds: ["cloud://test-env.bucket/atlas/sound-submissions/sound_synced_123/sound/equipment.jpg"],
    paymentFileIds: ["cloud://test-env.bucket/atlas/sound-submissions/sound_synced_123/payment/proof.jpg"],
    syncStatus: "synced",
    backendId: "backend-123",
  }]);

  await page.removeSubmission({ currentTarget: { dataset: { index: 0 } } });

  assert.equal(page.data.submissions.length, 0);
  assert.deepEqual(deletedFileLists, [], "synced evidence belongs to the backend retention lifecycle");
});

test("equipment-photo chooser enforces the four-file and one-megabyte client limits", () => {
  const full = loadSoundPage();
  full.page.data.form.images = ["one", "two", "three", "four"];
  full.page.chooseImages();
  assert.equal(full.toasts.at(-1).title, "up to 4 equipment photos");

  const oversized = loadSoundPage({
    chooseImageResult: {
      tempFilePaths: ["wxfile://oversized.jpg"],
      tempFiles: [{ path: "wxfile://oversized.jpg", size: 1024 * 1024 + 1 }],
    },
  });
  oversized.page.chooseImages();
  assert.deepEqual(oversized.page.data.form.images, []);
  assert.equal(oversized.toasts.at(-1).title, "equipment photo must be under 1MB");
});

test("sound page hides the equipment-photo add control at four files", () => {
  const wxml = fs.readFileSync(path.join(appRoot, "pages/sound/sound.wxml"), "utf8");
  assert.match(wxml, /form\.images\.length\s*<\s*4/);
  assert.doesNotMatch(wxml, /form\.images\.length\s*<\s*9/);
});

test("about page ships no client-side admin password or dead admin navigation", () => {
  const aboutJs = fs.readFileSync(path.join(appRoot, "pages/about/about.js"), "utf8");
  const aboutWxml = fs.readFileSync(path.join(appRoot, "pages/about/about.wxml"), "utf8");

  assert.doesNotMatch(aboutJs, /196823/);
  assert.doesNotMatch(aboutJs, /pages\/admin\/admin/);
  assert.doesNotMatch(aboutJs, /onLogoLongpress/);
  assert.doesNotMatch(aboutWxml, /bindlongpress/);
});

test("about page marks the Sound notice seen and exposes the existing Sound route", () => {
  const aboutJs = fs.readFileSync(path.join(appRoot, "pages/about/about.js"), "utf8");
  const aboutWxml = fs.readFileSync(path.join(appRoot, "pages/about/about.wxml"), "utf8");

  assert.match(aboutJs, /SOUND_NOTICE_SEEN_KEY\s*=\s*["']weeklySoundAtlasNoticeSeen:v1["']/);
  assert.match(aboutJs, /setStorageSync\(SOUND_NOTICE_SEEN_KEY,\s*true\)/);
  assert.doesNotMatch(aboutJs, /removeStorageSync\(["']weeklySoundAtlasNoticeSeen:v1["']\)/);
  assert.match(aboutJs, /openSound\s*\(\)/);
  assert.match(aboutJs, /["']\/pages\/sound\/sound["']/);
  assert.match(aboutWxml, /bindtap=["']openSound["']/);
});

test("app tab red dot reflects both unread and seen Sound notice states", () => {
  const appJs = fs.readFileSync(path.join(appRoot, "app.js"), "utf8");
  assert.match(appJs, /showTabBarRedDot\(\{\s*index:\s*ABOUT_TAB_INDEX\s*\}\)/);
  assert.match(appJs, /else\s*\{\s*wx\.hideTabBarRedDot\(\{\s*index:\s*ABOUT_TAB_INDEX\s*\}\)/);
});
