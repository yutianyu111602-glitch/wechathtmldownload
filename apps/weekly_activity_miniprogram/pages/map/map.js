const { requestApi } = require("../../utils/api");
const { compactItem, dedupeItems } = require("../../utils/format");
const { applyLanguageChrome, normalizeLang, text, localizeItems } = require("../../utils/i18n");
const { enableShareMenu, buildSimpleShare, buildSimpleTimeline } = require("../../utils/share");

function safeVibrate(type = "light") {
  if (typeof wx !== "undefined" && typeof wx.vibrateShort === "function") wx.vibrateShort({ type });
}

Page({
  data: {
    lang: "zh",
    t: text("map", "zh"),
    loading: true,
    error: "",
    markers: [],
    clubs: [],
    selectedClub: null,
    latitude: 35.86,
    longitude: 104.19,
    scale: 4,
  },

  onLoad(query) {
    enableShareMenu();
    const lang = normalizeLang(query.lang || wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("map", lang);
    this.setData({ lang, t: text("map", lang) });
    this.loadMapData();
  },

  onShareAppMessage() {
    return buildSimpleShare(
      this.data.lang === "en" ? "Club Map — HUAIDJ" : "俱乐部地图 — 坏DJclub",
      "/pages/map/map",
      { lang: this.data.lang }
    );
  },

  onShareTimeline() {
    return buildSimpleTimeline(
      this.data.lang === "en" ? "Club Map — HUAIDJ" : "俱乐部地图 — 坏DJclub",
      { lang: this.data.lang }
    );
  },

  async loadMapData() {
    this.setData({ loading: true, error: "" });
    try {
      const current = await requestApi("/api/v1/weekly/current", { limit: 100 });
      const items = localizeItems(
        dedupeItems((current.items || []).map(compactItem)),
        this.data.lang
      );

      const clubMap = new Map();
      for (const item of items) {
        if (!item.hasMapLocation || !item.mapLocation) continue;
        const key = item.organizerKey || item.venueLabel;
        if (!clubMap.has(key)) {
          clubMap.set(key, {
            id: item.id,
            name: item.venueLabel || item.promoter || item.account || "",
            cityLabel: item.cityLabel,
            addressLabel: item.addressLabel,
            latitude: item.mapLocation.latitude,
            longitude: item.mapLocation.longitude,
            styleLabel: item.styleLabel,
            count: 1,
          });
        } else {
          clubMap.get(key).count += 1;
        }
      }

      const clubs = Array.from(clubMap.values());
      const markers = clubs.map((club, index) => ({
        id: index,
        latitude: club.latitude,
        longitude: club.longitude,
        title: club.name,
        callout: { content: club.name, fontSize: 12, borderRadius: 4, padding: 6, display: "BYCLICK" },
        iconPath: "",
        width: 24,
        height: 24,
      }));

      const lats = clubs.map((c) => c.latitude);
      const lngs = clubs.map((c) => c.longitude);
      const centerLat = lats.length ? (Math.min(...lats) + Math.max(...lats)) / 2 : 35.86;
      const centerLng = lngs.length ? (Math.min(...lngs) + Math.max(...lngs)) / 2 : 104.19;

      this.setData({
        clubs,
        markers,
        latitude: centerLat,
        longitude: centerLng,
        scale: clubs.length > 0 ? 5 : 4,
        loading: false,
      });
    } catch (error) {
      console.error("[map] loadMapData failed", error);
      this.setData({ loading: false, error: this.data.t.loadFailed });
    }
  },

  onMarkerTap(event) {
    const markerId = event.detail?.markerId ?? event.markerId;
    const club = this.data.clubs[markerId];
    if (!club) return;
    this.setData({ selectedClub: club });
  },

  openClubDetail() {
    safeVibrate("light");
    const club = this.data.selectedClub;
    if (!club || !club.id) return;
    wx.navigateTo({
      url: `/pages/detail/detail?id=${encodeURIComponent(club.id)}&lang=${this.data.lang}`,
    });
  },

  navigateToClub() {
    safeVibrate("light");
    const club = this.data.selectedClub;
    if (!club || !club.latitude) return;
    wx.openLocation({
      latitude: club.latitude,
      longitude: club.longitude,
      name: club.name,
      address: club.addressLabel || "",
      scale: 16,
    });
  },

  closeClubSheet() {
    this.setData({ selectedClub: null });
  },

  goBack() {
    wx.navigateBack({ delta: 1 });
  },
});
