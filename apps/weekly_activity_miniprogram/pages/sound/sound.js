const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { enableShareMenu, buildSimpleShare, buildSimpleTimeline } = require("../../utils/share");

const STORAGE_KEY = "atlasSoundSubmissions:v1";
const CLEANUP_JOURNAL_STORAGE_KEY = "atlasSoundUploadCleanupJournal:v1";
const MAX_SOUND_IMAGES = 4;
const MAX_PAYMENT_IMAGES = 9;
const MAX_SOUND_IMAGE_SIZE = 1024 * 1024;
const MAX_PAYMENT_IMAGE_SIZE = 10 * 1024 * 1024;
const CLOUD_UPLOAD_PREFIX = "atlas/sound-submissions/";
const DEFAULT_SOUND_GATEWAY_FUNCTION = "soundSubmissionGateway";

function emptyForm() {
  return { images: [], paymentImages: [], clubName: "" };
}

function uniqueCloudFileIds(fileIds) {
  return Array.from(new Set((fileIds || [])
    .map((fileId) => String(fileId || "").trim())
    .filter((fileId) => fileId.startsWith("cloud://"))));
}

function readCleanupJournal() {
  let raw;
  try {
    raw = wx.getStorageSync(CLEANUP_JOURNAL_STORAGE_KEY);
  } catch (error) {
    const wrapped = new Error("SOUND_CLEANUP_JOURNAL_READ_FAILED");
    wrapped.cause = error;
    throw wrapped;
  }
  if (raw === "" || raw === null || raw === undefined) return [];
  let parsed;
  try {
    parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch (error) {
    const wrapped = new Error("SOUND_CLEANUP_JOURNAL_CORRUPT");
    wrapped.cause = error;
    throw wrapped;
  }
  if (!Array.isArray(parsed)) throw new Error("SOUND_CLEANUP_JOURNAL_CORRUPT");
  return parsed.map((entry) => {
    if (!entry
      || typeof entry !== "object"
      || !String(entry.submissionKey || "").trim()
      || !Array.isArray(entry.fileIds)
      || !["uploading", "cleanup_pending"].includes(entry.status)) {
      throw new Error("SOUND_CLEANUP_JOURNAL_CORRUPT");
    }
    return {
      submissionKey: String(entry.submissionKey),
      fileIds: uniqueCloudFileIds(entry.fileIds),
      status: entry.status,
      removeRecordAfterCleanup: Boolean(entry.removeRecordAfterCleanup),
      updatedAt: String(entry.updatedAt || ""),
    };
  });
}

function writeCleanupJournal(entries) {
  wx.setStorageSync(CLEANUP_JOURNAL_STORAGE_KEY, JSON.stringify(entries));
}

function persistCleanupJournalEntry(entry) {
  const entries = readCleanupJournal().filter((item) => item.submissionKey !== entry.submissionKey);
  entries.push({
    submissionKey: entry.submissionKey,
    fileIds: uniqueCloudFileIds(entry.fileIds),
    status: entry.status === "cleanup_pending" ? "cleanup_pending" : "uploading",
    removeRecordAfterCleanup: Boolean(entry.removeRecordAfterCleanup),
    updatedAt: new Date().toISOString(),
  });
  writeCleanupJournal(entries);
}

function removeCleanupJournalEntry(submissionKey) {
  writeCleanupJournal(readCleanupJournal().filter((entry) => entry.submissionKey !== submissionKey));
}

function createSubmissionKey() {
  const timestamp = Date.now().toString(36);
  const random = `${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
  return `sound_${timestamp}_${random.slice(0, 24)}`;
}

function fileIdMatchesSubmission(fileId, submissionKey, kind) {
  const value = String(fileId || "");
  if (/[\u0000-\u001f\u007f]/.test(value) || /[?#%]/.test(value)) return false;
  const match = /^cloud:\/\/[^/]+\/(.+)$/.exec(value);
  if (!match) return false;
  const segments = match[1].split("/");
  return segments.length === 5
    && segments[0] === "atlas"
    && segments[1] === "sound-submissions"
    && segments[2] === submissionKey
    && segments[3] === kind
    && /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}\.(?:jpe?g|png|webp)$/i.test(segments[4]);
}

function pendingRecordIsRetryable(record) {
  const submissionKey = String(record && record.submissionKey || "");
  const soundFileIds = record && record.soundFileIds;
  const paymentFileIds = record && record.paymentFileIds;
  return /^[A-Za-z0-9_-]{12,128}$/.test(submissionKey)
    && Boolean(String(record && record.clubName || "").trim())
    && Array.isArray(soundFileIds)
    && soundFileIds.length > 0
    && soundFileIds.length <= MAX_SOUND_IMAGES
    && Array.isArray(paymentFileIds)
    && paymentFileIds.length > 0
    && paymentFileIds.length <= MAX_PAYMENT_IMAGES
    && soundFileIds.every((fileId) => fileIdMatchesSubmission(fileId, submissionKey, "sound"))
    && paymentFileIds.every((fileId) => fileIdMatchesSubmission(fileId, submissionKey, "payment"));
}

function backendRecord(record) {
  const soundFileIds = Array.isArray(record.soundFileIds) ? record.soundFileIds : [];
  const paymentFileIds = Array.isArray(record.paymentFileIds) ? record.paymentFileIds : [];
  return {
    submissionKey: record.submissionKey,
    clubName: record.clubName,
    soundFileIds,
    soundImageCount: soundFileIds.length,
    paymentFileIds,
    paymentImageCount: paymentFileIds.length,
    submittedAt: record.submittedAt,
    version: 4,
  };
}

function getCloudClient() {
  const app = getApp();
  const cloud = app && app.globalData && app.globalData.cloud;
  return cloud && (cloud.cloudClient || (cloud.cloudReady ? wx.cloud : null)) || null;
}

async function uploadImage(filePath, cloudPath) {
  const cloud = getCloudClient();
  if (!cloud || typeof cloud.uploadFile !== "function") {
    return { ok: false, error: "cloud_unavailable" };
  }
  try {
    const result = await cloud.uploadFile({ cloudPath, filePath });
    return { ok: true, fileID: result.fileID };
  } catch (err) {
    console.warn("[sound] uploadImage failed", err);
    return { ok: false, error: "upload_failed" };
  }
}

function imageExtension(filePath) {
  const match = String(filePath || "").toLowerCase().match(/\.(jpe?g|png|webp)(?:$|[?#])/);
  return match ? match[1].replace("jpeg", "jpg") : "jpg";
}

async function uploadImages(filePaths, submissionKey, kind, onUploaded) {
  const results = [];
  for (let idx = 0; idx < filePaths.length; idx += 1) {
    const ts = Date.now();
    const rnd = Math.random().toString(36).slice(2, 6);
    const extension = imageExtension(filePaths[idx]);
    const cloudPath = `${CLOUD_UPLOAD_PREFIX}${submissionKey}/${kind}/${ts}_${rnd}_${idx}.${extension}`;
    const result = await uploadImage(filePaths[idx], cloudPath);
    if (result.fileID && typeof onUploaded === "function") {
      try {
        onUploaded(result.fileID);
      } catch (error) {
        console.warn("[sound] upload cleanup journal update failed", error);
        results.push({ ok: false, error: "upload_journal_failed", fileID: result.fileID });
        break;
      }
    }
    if (result.ok && !fileIdMatchesSubmission(result.fileID, submissionKey, kind)) {
      // Keep the returned ID available for rollback. It came from this upload
      // attempt even though it is not safe to persist under the submission.
      results.push({ ok: false, error: "upload_contract_mismatch", fileID: result.fileID });
    } else {
      results.push(result);
    }
  }
  return results;
}

async function deleteUploadedFiles(fileIds) {
  const uniqueIds = uniqueCloudFileIds(fileIds);
  if (!uniqueIds.length) return { ok: true, deletedFileIds: [], failedFileIds: [] };
  const cloud = getCloudClient();
  if (!cloud || typeof cloud.deleteFile !== "function") {
    console.warn("[sound] uploaded-file cleanup unavailable", uniqueIds.length);
    return { ok: false, deletedFileIds: [], failedFileIds: uniqueIds };
  }
  try {
    const response = await cloud.deleteFile({ fileList: uniqueIds });
    const rows = Array.isArray(response && response.fileList) ? response.fileList : [];
    const byFileId = new Map(rows.map((row) => [String(row && row.fileID || ""), row]));
    const deletedFileIds = [];
    const failedFileIds = [];
    for (const fileId of uniqueIds) {
      const row = byFileId.get(fileId);
      const status = Number(row && row.status);
      const errMsg = String(row && row.errMsg || "").trim();
      const explicitlyOk = status === 0 && (!errMsg || /(?:^|:)ok$/i.test(errMsg));
      const alreadyAbsent = /(?:not\s*found|not\s*exist|nonexist)/i.test(errMsg);
      if (explicitlyOk || alreadyAbsent) deletedFileIds.push(fileId);
      else failedFileIds.push(fileId);
    }
    return { ok: failedFileIds.length === 0, deletedFileIds, failedFileIds };
  } catch (error) {
    console.warn("[sound] uploaded-file cleanup failed", error);
    return { ok: false, deletedFileIds: [], failedFileIds: uniqueIds };
  }
}

async function cleanupUncommittedUploadSession(session) {
  const pending = {
    ...session,
    status: "cleanup_pending",
    removeRecordAfterCleanup: false,
    fileIds: uniqueCloudFileIds(session && session.fileIds),
  };
  try {
    persistCleanupJournalEntry(pending);
  } catch (error) {
    console.warn("[sound] cleanup journal persistence failed", error);
  }
  const result = await deleteUploadedFiles(pending.fileIds);
  const remaining = { ...pending, fileIds: result.failedFileIds };
  try {
    persistCleanupJournalEntry(remaining);
    if (result.ok) removeCleanupJournalEntry(pending.submissionKey);
  } catch (error) {
    // The older, pre-delete journal remains the recovery authority. Retrying
    // an already absent file is safe because not-found is accepted as clean.
    console.warn("[sound] cleanup journal finalization failed", error);
  }
  return result.ok;
}

async function callSoundSubmissionGateway(record) {
  const cloud = getCloudClient();
  if (!cloud || typeof cloud.callFunction !== "function") {
    throw new Error("SOUND_GATEWAY_UNAVAILABLE");
  }
  const app = getApp();
  const config = app && app.globalData && app.globalData.cloud || {};
  const name = String(config.soundSubmissionFunctionName || DEFAULT_SOUND_GATEWAY_FUNCTION);
  const response = await cloud.callFunction({
    name,
    data: { action: "submit", body: backendRecord(record) },
  });
  const result = response && response.result;
  if (!result || result.ok === false || result.error) {
    const code = result && result.error && (result.error.code || result.error) || "SOUND_GATEWAY_REJECTED";
    throw new Error(String(code));
  }
  return result;
}

Page({
  data: {
    lang: "zh",
    t: text("sound", "zh"),
    form: emptyForm(),
    submissions: [],
    submitting: false,
    uploadProgress: "",
  },

  onLoad() {
    enableShareMenu();
    const lang = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("sound", lang);
    this.setData({ lang, t: text("sound", lang) });
    this.loadSubmissions();
    this.retryCleanupJournal()
      .then(() => this.retryPendingSubmissions())
      .catch((error) => {
        console.warn("[sound] recovery retry failed", error);
      });
  },

  onShareAppMessage() {
    return buildSimpleShare(
      this.data.lang === "en" ? "Atlas Sound Hunter — HUAIDJ" : "城市声音猎人 — 坏DJclub",
      "/pages/sound/sound",
      { lang: this.data.lang }
    );
  },

  onShareTimeline() {
    return buildSimpleTimeline(
      this.data.lang === "en" ? "Atlas Sound Hunter — HUAIDJ" : "城市声音猎人 — 坏DJclub",
      { lang: this.data.lang }
    );
  },

  loadSubmissions() {
    try {
      const raw = wx.getStorageSync(STORAGE_KEY) || "[]";
      this.setData({ submissions: JSON.parse(raw) });
    } catch {
      this.setData({ submissions: [] });
    }
  },

  saveSubmissions(list) {
    wx.setStorageSync(STORAGE_KEY, JSON.stringify(list));
    this.setData({ submissions: list });
  },

  callSubmissionGatewayOnce(record) {
    const submissionKey = String(record && record.submissionKey || "").trim();
    if (!submissionKey) return Promise.reject(new Error("SOUND_SUBMISSION_KEY_MISSING"));
    if (!this._submissionGatewayInflight) this._submissionGatewayInflight = new Map();
    const existing = this._submissionGatewayInflight.get(submissionKey);
    if (existing) return existing;
    const request = callSoundSubmissionGateway(record).finally(() => {
      if (this._submissionGatewayInflight.get(submissionKey) === request) {
        this._submissionGatewayInflight.delete(submissionKey);
      }
    });
    this._submissionGatewayInflight.set(submissionKey, request);
    return request;
  },

  async retryCleanupJournal() {
    if (this._retryCleanupPromise) return this._retryCleanupPromise;
    this._retryCleanupPromise = (async () => {
      const snapshot = readCleanupJournal();
      for (const snapshotEntry of snapshot) {
        const entry = readCleanupJournal().find((item) => (
          item.submissionKey === snapshotEntry.submissionKey
        ));
        if (!entry) continue;
        const record = this.data.submissions.find((item) => (
          item.submissionKey === entry.submissionKey
        ));

        // A committed local record protects its evidence. This covers a crash
        // between saving the pending/synced record and clearing the upload
        // journal. Synced evidence is always owned by backend retention.
        if (record && record.syncStatus === "synced") {
          removeCleanupJournalEntry(entry.submissionKey);
          continue;
        }
        if (record
          && record.syncStatus !== "cleanup_pending"
          && !entry.removeRecordAfterCleanup) {
          removeCleanupJournalEntry(entry.submissionKey);
          continue;
        }

        const pending = {
          ...entry,
          status: "cleanup_pending",
          fileIds: uniqueCloudFileIds(entry.fileIds),
        };
        persistCleanupJournalEntry(pending);
        const result = await deleteUploadedFiles(pending.fileIds);
        const afterDelete = { ...pending, fileIds: result.failedFileIds };
        persistCleanupJournalEntry(afterDelete);
        if (!result.ok) continue;

        if (pending.removeRecordAfterCleanup) {
          const remainingRecords = this.data.submissions.filter((item) => (
            item.submissionKey !== pending.submissionKey
          ));
          try {
            this.saveSubmissions(remainingRecords);
          } catch (error) {
            console.warn("[sound] cleaned record removal persistence failed", error);
            continue;
          }
        }
        removeCleanupJournalEntry(pending.submissionKey);
      }
    })();
    try {
      await this._retryCleanupPromise;
    } finally {
      this._retryCleanupPromise = null;
    }
  },

  async retryPendingSubmissions() {
    if (this._retryPendingPromise) return this._retryPendingPromise;
    this._retryPendingPromise = (async () => {
      const snapshot = [...this.data.submissions];
      const updates = new Map();
      const seenSubmissionKeys = new Set();
      for (let index = 0; index < snapshot.length; index += 1) {
        const record = snapshot[index];
        if (record.syncStatus !== "pending") continue;
        if (seenSubmissionKeys.has(record.submissionKey)) continue;
        seenSubmissionKeys.add(record.submissionKey);
        if (!pendingRecordIsRetryable(record)) {
          updates.set(record.submissionKey, { syncStatus: "needs_resubmit" });
          continue;
        }
        try {
          const result = await this.callSubmissionGatewayOnce(record);
          updates.set(record.submissionKey, {
            syncStatus: "synced",
            backendId: result && result.id || record.backendId || "",
          });
        } catch (error) {
          console.warn("[sound] pending submission retry deferred", error);
        }
      }
      if (updates.size) {
        let changed = false;
        const submissions = this.data.submissions.map((record) => {
          const update = updates.get(record.submissionKey);
          // A concurrent delete/cleanup owns the latest state and must never be
          // reverted by a retry that began from an older pending snapshot.
          if (!update || record.syncStatus !== "pending") return record;
          changed = true;
          return { ...record, ...update };
        });
        if (changed) this.saveSubmissions(submissions);
      }
    })();
    try {
      await this._retryPendingPromise;
    } finally {
      this._retryPendingPromise = null;
    }
  },

  onFieldInput(e) {
    const key = e.currentTarget.dataset.key;
    this.setData({ [`form.${key}`]: e.detail.value || "" });
  },

  /* --- equipment photos --- */

  chooseImages() {
    this._chooseImages("images");
  },

  removeImage(e) {
    this._removeImage("images", e.currentTarget.dataset.index);
  },

  previewImage(e) {
    this._previewImage("images", e.currentTarget.dataset.index);
  },

  /* --- payment screenshots --- */

  choosePaymentImages() {
    this._chooseImages("paymentImages");
  },

  removePaymentImage(e) {
    this._removeImage("paymentImages", e.currentTarget.dataset.index);
  },

  previewPaymentImage(e) {
    this._previewImage("paymentImages", e.currentTarget.dataset.index);
  },

  /* --- generic image helpers --- */

  _chooseImages(key) {
    const current = this.data.form[key] || [];
    const isSoundEvidence = key === "images";
    const maxImages = isSoundEvidence ? MAX_SOUND_IMAGES : MAX_PAYMENT_IMAGES;
    const maxImageSize = isSoundEvidence ? MAX_SOUND_IMAGE_SIZE : MAX_PAYMENT_IMAGE_SIZE;
    const maxImagesMessage = isSoundEvidence ? this.data.t.maxSoundImages : this.data.t.maxPaymentImages;
    const tooLargeMessage = isSoundEvidence ? this.data.t.soundImageTooLarge : this.data.t.paymentImageTooLarge;
    const remaining = maxImages - current.length;
    if (remaining <= 0) {
      wx.showToast({ title: maxImagesMessage, icon: "none" });
      return;
    }
    wx.chooseImage({
      count: remaining,
      sizeType: ["original"],
      sourceType: ["album", "camera"],
      success: (res) => {
        const incoming = (res.tempFilePaths || []).filter((p) => {
          const info = res.tempFiles?.find((f) => f.path === p);
          if (info && info.size > maxImageSize) {
            wx.showToast({ title: tooLargeMessage, icon: "none" });
            return false;
          }
          return true;
        });
        if (!incoming.length) return;
        this.setData({ [`form.${key}`]: [...current, ...incoming] });
      },
    });
  },

  _removeImage(key, idx) {
    const images = [...this.data.form[key]];
    images.splice(idx, 1);
    this.setData({ [`form.${key}`]: images });
  },

  _previewImage(key, idx) {
    wx.previewImage({
      urls: this.data.form[key],
      current: this.data.form[key][idx],
    });
  },

  /* --- validation --- */

  validateForm() {
    const t = this.data.t;
    if (!this.data.form.clubName.trim()) return t.noClubName;
    if (!this.data.form.images.length) return t.noImages;
    if (!this.data.form.paymentImages.length) return t.noPaymentImages;
    return "";
  },

  /* --- submit --- */

  async submitForm() {
    if (this.data.submitting) return;
    const err = this.validateForm();
    if (err) {
      wx.showToast({ title: err, icon: "none" });
      return;
    }

    this.setData({ submitting: true, uploadProgress: this.data.t.uploading });

    const t = this.data.t;
    const submissionKey = createSubmissionKey();
    const uploadSession = {
      submissionKey,
      fileIds: [],
      status: "uploading",
      removeRecordAfterCleanup: false,
    };
    let acceptedLocally = false;
    let uploadJournalReady = false;

    try {
      // No remote write is allowed until its recovery journal exists locally.
      // Each successful upload extends this journal before another begins.
      persistCleanupJournalEntry(uploadSession);
      uploadJournalReady = true;
      const rememberUploadedFile = (fileId) => {
        uploadSession.fileIds = uniqueCloudFileIds([...uploadSession.fileIds, fileId]);
        persistCleanupJournalEntry(uploadSession);
      };

      // Upload equipment photos
      this.setData({ uploadProgress: `${t.uploading} (1/2 ${t.images})` });
      const soundResults = await uploadImages(
        this.data.form.images,
        submissionKey,
        "sound",
        rememberUploadedFile,
      );
      const soundOk = soundResults.filter((result) => result.ok);
      if (soundOk.length !== this.data.form.images.length) {
        wx.showToast({ title: t.uploadFailed, icon: "none" });
        await cleanupUncommittedUploadSession(uploadSession);
        return;
      }
      const soundFileIds = soundOk.map((result) => result.fileID);

      // Upload payment screenshots
      this.setData({ uploadProgress: `${t.uploading} (2/2 ${t.paymentImages})` });
      const payResults = await uploadImages(
        this.data.form.paymentImages,
        submissionKey,
        "payment",
        rememberUploadedFile,
      );
      const payOk = payResults.filter((result) => result.ok);
      if (payOk.length !== this.data.form.paymentImages.length) {
        wx.showToast({ title: t.uploadFailed, icon: "none" });
        await cleanupUncommittedUploadSession(uploadSession);
        return;
      }
      const payFileIds = payOk.map((result) => result.fileID);

      const record = {
        submissionKey,
        clubName: this.data.form.clubName.trim(),
        soundFileIds,
        soundImageCount: soundFileIds.length,
        paymentFileIds: payFileIds,
        paymentImageCount: payFileIds.length,
        submittedAt: new Date().toISOString(),
        version: 4,
      };

      const localRecord = {
        ...record,
        images: soundFileIds,
        paymentImages: payFileIds,
        imageCount: soundFileIds.length,
        syncStatus: "pending",
      };
      const submissions = [
        localRecord,
        ...this.data.submissions.filter((item) => item.submissionKey !== localRecord.submissionKey),
      ];
      try {
        this.saveSubmissions(submissions);
        acceptedLocally = true;
      } catch (storageError) {
        console.warn("[sound] local persistence failed", storageError);
        wx.showToast({ title: t.uploadFailed, icon: "none" });
        await cleanupUncommittedUploadSession(uploadSession);
        return;
      }

      try {
        removeCleanupJournalEntry(submissionKey);
      } catch (journalError) {
        // The committed local record protects these files when recovery sees
        // the stale upload journal on the next page load.
        console.warn("[sound] committed upload journal cleanup deferred", journalError);
      }

      try {
        const result = await this.callSubmissionGatewayOnce(record);
        this.saveSubmissions(this.data.submissions.map((submission) => (
          submission.submissionKey === record.submissionKey
            ? { ...submission, syncStatus: "synced", backendId: result && result.id || "" }
            : submission
        )));
        wx.showToast({ title: t.submitted, icon: "success" });
      } catch (apiError) {
        console.warn("[sound] api submit failed, saved locally", apiError);
        wx.showToast({ title: t.submittedLocal, icon: "none" });
      }

      this.setData({ form: emptyForm() });
    } catch (unexpectedError) {
      console.warn("[sound] submit failed unexpectedly", unexpectedError);
      if (!acceptedLocally && (uploadJournalReady || uploadSession.fileIds.length)) {
        await cleanupUncommittedUploadSession(uploadSession);
      }
      wx.showToast({ title: t.uploadFailed, icon: "none" });
    } finally {
      this.setData({ submitting: false, uploadProgress: "" });
    }
  },

  async removeSubmission(e) {
    const idx = e.currentTarget.dataset.index;
    const record = this.data.submissions[idx];
    if (!record) return;
    if (record.syncStatus === "synced") {
      const submissions = [...this.data.submissions];
      submissions.splice(idx, 1);
      this.saveSubmissions(submissions);
      return;
    }

    const fileIds = uniqueCloudFileIds([
      ...(Array.isArray(record.soundFileIds) ? record.soundFileIds : []),
      ...(Array.isArray(record.paymentFileIds) ? record.paymentFileIds : []),
    ]);
    if (!fileIds.length) {
      const submissions = [...this.data.submissions];
      submissions.splice(idx, 1);
      this.saveSubmissions(submissions);
      return;
    }

    const cleanupEntry = {
      submissionKey: record.submissionKey,
      fileIds,
      status: "cleanup_pending",
      removeRecordAfterCleanup: true,
    };
    try {
      // Journal first: a crash or local-record write failure can never make
      // the remote evidence unreachable from cleanup recovery.
      persistCleanupJournalEntry(cleanupEntry);
      this.saveSubmissions(this.data.submissions.map((item, index) => (
        index === idx ? { ...item, syncStatus: "cleanup_pending" } : item
      )));
    } catch (error) {
      console.warn("[sound] cleanup request persistence failed", error);
      return;
    }
    const recoveryWasAlreadyRunning = Boolean(this._retryCleanupPromise);
    await this.retryCleanupJournal();
    // If an on-load recovery was already iterating an older snapshot, run one
    // more pass so this newly journaled deletion is not deferred indefinitely.
    if (recoveryWasAlreadyRunning
      && readCleanupJournal().some((entry) => entry.submissionKey === record.submissionKey)) {
      await this.retryCleanupJournal();
    }
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },
});
