const { postApi } = require("../../utils/api");
const { copyOriginalExternalLink, validateInterviewExternalLinks } = require("../../utils/externalLinkAction");
const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

const STORAGE_KEY = "atlasDjInterviewSubmissions:v1";
const SEED_STORAGE_KEY = "atlasDjInterviewSeed:v1";

function emptyForm(seed = {}) {
  return {
    djName: seed.djName || "",
    city: seed.city || "",
    contact: "",
    instagramUrl: "",
    mixtapeUrl: "",
    sourceUrl: "",
    answerText: "",
    consentInternal: false,
    consentPublic: false,
    consentGraph: false,
  };
}

function decodeQueryValue(value) {
  try {
    return decodeURIComponent(value || "");
  } catch {
    return value || "";
  }
}

Page({
  data: {
    lang: "zh",
    t: text("interview", "zh"),
    form: emptyForm(),
    submissions: [],
    submitting: false,
  },

  onLoad(query = {}) {
    enableShareMenu();
    let storedSeed = {};
    try {
      storedSeed = wx.getStorageSync(SEED_STORAGE_KEY) || {};
      wx.removeStorageSync(SEED_STORAGE_KEY);
    } catch {
      storedSeed = {};
    }
    const lang = normalizeLang(query.lang || storedSeed.lang || wx.getStorageSync("weeklyActivityLang"));
    const seed = {
      djName: decodeQueryValue(query.djName) || storedSeed.djName || "",
      city: decodeQueryValue(query.city) || storedSeed.city || "",
    };
    applyLanguageChrome("interview", lang);
    this.setData({ lang, t: text("interview", lang), form: emptyForm(seed) });
    this.loadSubmissions();
  },

  onShareAppMessage() {
    return buildSimpleShare(
      this.data.lang === "en" ? "Atlas DJ Interview" : "Atlas DJ 采访",
      "/pages/interview/interview",
      { lang: this.data.lang }
    );
  },

  onShareTimeline() {
    return buildSimpleTimeline(
      this.data.lang === "en" ? "Atlas DJ Interview" : "Atlas DJ 采访",
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

  onConsentChange(e) {
    const values = new Set(e.detail.value || []);
    this.setData({
      "form.consentInternal": values.has("internal"),
      "form.consentPublic": values.has("public"),
      "form.consentGraph": values.has("graph"),
    });
  },

  validateForm() {
    const t = this.data.t;
    const form = this.data.form;
    if (!String(form.djName || "").trim()) return t.noDjName;
    if (!form.consentInternal) return t.noConsentInternal;
    const linkCheck = validateInterviewExternalLinks(form, this.data.lang);
    if (!linkCheck.ok) return linkCheck.message;
    return "";
  },

  openOriginalLink(e) {
    const key = e.currentTarget.dataset.key;
    const value = this.data.form[key];
    const linkType = key === "instagramUrl" ? "instagram" : "mixtape";
    const action = copyOriginalExternalLink(value, this.data.lang, { linkType });
    if (!action.ok) wx.showToast({ title: action.message, icon: "none" });
  },

  async submitForm() {
    if (this.data.submitting) return;
    const err = this.validateForm();
    if (err) {
      wx.showToast({ title: err, icon: "none" });
      return;
    }

    this.setData({ submitting: true });
    const form = this.data.form;
    const record = {
      djName: form.djName.trim(),
      city: form.city.trim(),
      contact: form.contact.trim(),
      instagramUrl: form.instagramUrl.trim(),
      mixtapeUrl: form.mixtapeUrl.trim(),
      sourceUrl: form.sourceUrl.trim(),
      answerText: form.answerText.trim(),
      consent: {
        internalProcessing: Boolean(form.consentInternal),
        publicFacts: Boolean(form.consentPublic),
        graphCandidate: Boolean(form.consentGraph),
      },
      submittedAt: new Date().toISOString(),
    };

    const localRecord = {
      djName: record.djName,
      city: record.city,
      submittedAt: record.submittedAt,
      hasMixtapeUrl: Boolean(record.mixtapeUrl),
      hasInstagramUrl: Boolean(record.instagramUrl),
      consentPublic: record.consent.publicFacts,
      consentGraph: record.consent.graphCandidate,
    };
    this.saveSubmissions([localRecord, ...this.data.submissions]);

    try {
      await postApi("/api/v1/atlas/dj-interviews", record);
      wx.showToast({ title: this.data.t.submitted, icon: "success" });
    } catch (apiError) {
      console.warn("[interview] api submit failed, saved locally", apiError);
      wx.showToast({ title: this.data.t.submittedLocal, icon: "none" });
    }

    this.setData({ form: emptyForm({ djName: record.djName, city: record.city }), submitting: false });
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
