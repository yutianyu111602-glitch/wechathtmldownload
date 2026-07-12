const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { postApi } = require("../../utils/api");
const { enableShareMenu, buildSimpleShare, buildSimpleTimeline } = require("../../utils/share");

const STORAGE_KEY = "atlasSoundSubmissions:v1";
const MAX_IMAGES = 9;
const MAX_IMAGE_SIZE = 10 * 1024 * 1024;
const CLOUD_UPLOAD_PREFIX = "atlas/sound-submissions/";

function emptyForm() {
  return { images: [], paymentImages: [], clubName: "" };
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

async function uploadImages(filePaths, prefix) {
  const results = [];
  for (let idx = 0; idx < filePaths.length; idx += 1) {
    const ts = Date.now();
    const rnd = Math.random().toString(36).slice(2, 6);
    const cloudPath = `${CLOUD_UPLOAD_PREFIX}${prefix}/${ts}_${rnd}_${idx}.jpg`;
    const result = await uploadImage(filePaths[idx], cloudPath);
    results.push(result);
  }
  return results;
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
    const remaining = MAX_IMAGES - current.length;
    if (remaining <= 0) {
      wx.showToast({ title: this.data.t.maxImages, icon: "none" });
      return;
    }
    wx.chooseImage({
      count: remaining,
      sizeType: ["original"],
      sourceType: ["album", "camera"],
      success: (res) => {
        const incoming = (res.tempFilePaths || []).filter((p) => {
          const info = res.tempFiles?.find((f) => f.path === p);
          if (info && info.size > MAX_IMAGE_SIZE) {
            wx.showToast({ title: this.data.t.imageTooLarge, icon: "none" });
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
    const totalImages = this.data.form.images.length + this.data.form.paymentImages.length;

    // Upload equipment photos
    this.setData({ uploadProgress: `${t.uploading} (1/2 ${t.images})` });
    const soundResults = await uploadImages(this.data.form.images, "sound");
    const soundOk = soundResults.filter((r) => r.ok);
    if (!soundOk.length) {
      wx.showToast({ title: this.data.t.uploadFailed, icon: "none" });
      this.setData({ submitting: false, uploadProgress: "" });
      return;
    }
    const soundFileIds = soundOk.map((r) => r.fileID);

    // Upload payment screenshots
    this.setData({ uploadProgress: `${t.uploading} (2/2 ${t.paymentImages})` });
    const payResults = await uploadImages(this.data.form.paymentImages, "payment");
    const payOk = payResults.filter((r) => r.ok);
    const payFileIds = payOk.map((r) => r.fileID);

    const record = {
      clubName: this.data.form.clubName.trim(),
      soundFileIds,
      soundImageCount: soundFileIds.length,
      paymentFileIds,
      paymentImageCount: payFileIds.length,
      submittedAt: new Date().toISOString(),
      version: 4,
    };

    // Save locally
    const localRecord = {
      ...record,
      images: soundFileIds,
      paymentImages: payFileIds,
      imageCount: soundFileIds.length,
    };
    const submissions = [localRecord, ...this.data.submissions];
    this.saveSubmissions(submissions);

    // Post to backend
    try {
      await postApi("/api/v1/weekly/sounds", record);
      wx.showToast({ title: t.submitted, icon: "success" });
    } catch (apiError) {
      console.warn("[sound] api submit failed, saved locally", apiError);
      wx.showToast({ title: t.submittedLocal, icon: "none" });
    }

    this.setData({ form: emptyForm(), submitting: false, uploadProgress: "" });
  },

  removeSubmission(e) {
    const idx = e.currentTarget.dataset.index;
    const submissions = [...this.data.submissions];
    submissions.splice(idx, 1);
    this.saveSubmissions(submissions);
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },
});
