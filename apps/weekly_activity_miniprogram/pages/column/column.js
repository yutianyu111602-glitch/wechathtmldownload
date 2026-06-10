const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { vibrateLight } = require("../../utils/haptics");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

var HARDCODED_ITEMS = [
  {"id":"col_small_8","title":"Babyching：深圳OIL地下放techno的人","djName":"Babyching","summary":"Babyching在OIL的后排放歌，选曲奇怪但上头——从硬核techno跳到碎拍bass，偶尔插一首trance让舞池愣住。","date":"2026-06-11","tag":"dj","sourceName":"OIL"},
  {"id":"col_small_9","title":"99God：上海ILLUM后座的跨风格焊工","djName":"99God","summary":"99God这个名字本身就是个meme——自称'神'但只放99%没人听过的歌。在上海ILLUM的地下室里，他敢把Kendrick Lamar的acapella塞进techno鼓里。","date":"2026-06-12","tag":"dj","sourceName":"ILLUM Shanghai"},
  {"id":"col_small_1","title":"DJ小山：大理古城里放迪斯科的人","djName":"DJ小山","summary":"DJ小山在大理干镇404号放歌三年了。选曲逻辑只有一个——能不能让人跳起来。","date":"2026-06-12","tag":"dj","sourceName":"HUAIDJ"},
  {"id":"col_small_6","title":"Hello Shitty：上海EXIT的垃圾美学","djName":"Hello Shitty","summary":"本名王磊，白天是广告公司的平面设计师，晚上戴上墨镜就成了EXIT俱乐部最朋克的DJ。","date":"2026-06-13","tag":"dj","sourceName":"EXIT Shanghai"},
  {"id":"col_small_7","title":"Altieri3000：上海EXIT的意大利未来主义暗流","djName":"Altieri3000","summary":"Altieri3000，一个意大利名字配上3000的锐利后缀。在EXIT Club的地下室，house的律动打底，穿插electro的机械脉动。","date":"2026-06-13","tag":"dj","sourceName":"EXIT Shanghai"},
  {"id":"col_small_2","title":"丝绒公路：重庆坚果里的公路电影","djName":"丝绒公路","summary":"丝绒公路是个奇怪的组合——名字像公路电影，音乐却游走在摇滚与电子之间。他们在重庆坚果NUTS演出。","date":"2026-06-13","tag":"dj","sourceName":"坚果NUTS"},
  {"id":"col_small_3","title":"JAKELxx：长春敲敲俱乐部的hip-hop与house混音师","djName":"JAKELxx","summary":"JAKELxx是长春'敲敲电子俱乐部'的驻场DJ，选曲逻辑古怪但上头。","date":"2026-06-13","tag":"dj","sourceName":"敲敲电子俱乐部"},
  {"id":"col_small_4","title":"C.S.B.Q乐队：重庆坚果的朋克钉子户","djName":"C.S.B.Q乐队","summary":"一支在重庆地下坚持了快十年的朋克乐队，主唱嗓子像砂纸磨过钢管。","date":"2026-06-14","tag":"dj","sourceName":"坚果NUTS"},
  {"id":"col_small_10","title":"Franceschini Gianluigi：广州陀地士多现场实验者","djName":"Franceschini Gianluigi","summary":"一个意大利名字，在没人知道他是谁的情况下出现在广州的陀地士多。","date":"2026-06-14","tag":"dj","sourceName":"陀地士多"},
  {"id":"col_small_5","title":"Techn：天津气厂里放Techno的人","djName":"Techn","summary":"Techn，天津本土DJ，名字直白得像在说'我就是放Techno的'。","date":"2026-06-16","tag":"dj","sourceName":"Gas Nation气厂"},
  {"id":"col_news_1","title":"Berghain 2026夏至马拉松：48小时不停歇","summary":"Berghain公布2026年夏至48小时马拉松活动。","date":"2026-06-09","tag":"event","sourceName":"Berghain","foreignMedia":"Resident Advisor"},
  {"id":"col_news_2","title":"DVS1 创立新厂牌 HUSH：专注极简 techno","djName":"DVS1","summary":"DVS1启动新厂牌HUSH，专注原始极简techno。","date":"2026-06-09","tag":"label","sourceName":"HUSH","foreignMedia":"Mixmag"},
  {"id":"col_news_3","title":"底特律Movement 2026阵容公布","summary":"Movement 2026公布headliner：Jeff Mills, Carl Craig。","date":"2026-06-10","tag":"event","sourceName":"Movement","foreignMedia":"DJ Mag"},
  {"id":"col_news_4","title":"AI DJ 引发地下俱乐部争议","summary":"柏林一场AI DJ演出引发地下电子乐圈关于真实性的大辩论。","date":"2026-06-10","tag":"trend","sourceName":"全球","foreignMedia":"The Guardian"},
  {"id":"col_news_5","title":"黑胶复兴：全球销量大涨20%","summary":"2026年全球黑胶销量同比上涨20%。","date":"2026-06-10","tag":"trend","sourceName":"全球","foreignMedia":"Billboard"},
  {"id":"col_news_6","title":"Nina Kraviz 东京 Womb 三个月驻场","djName":"Nina Kraviz","summary":"Nina Kraviz宣布在东京Womb进行三个月驻场。","date":"2026-06-11","tag":"dj","sourceName":"Womb","foreignMedia":"RA News"},
  {"id":"col_news_7","title":"Erica Synths 发布 Pulsar-1 模块合成器","summary":"Erica Synths推出Pulsar-1，专为现场techno演出设计。","date":"2026-06-11","tag":"gear","sourceName":"Erica Synths","foreignMedia":"Synthtopia"},
  {"id":"col_news_8","title":"柏林俱乐部文化危机：新噪音法威胁营业时间","summary":"柏林拟议噪音新规可能限制俱乐部营业时长。","date":"2026-06-10","tag":"city","sourceName":"柏林","foreignMedia":"The Berliner"}
];

var TAG_LIST = [
  { key: "all", zh: "全部", en: "All" },
  { key: "dj", zh: "DJ", en: "DJ" },
  { key: "event", zh: "活动", en: "Events" },
  { key: "label", zh: "厂牌", en: "Labels" },
  { key: "trend", zh: "趋势", en: "Trends" },
  { key: "gear", zh: "设备", en: "Gear" },
  { key: "city", zh: "城市", en: "Cities" },
];

var TAG_DISPLAY = {
  dj: { zh: "DJ", en: "DJ" },
  event: { zh: "活动", en: "Event" },
  label: { zh: "厂牌", en: "Label" },
  trend: { zh: "趋势", en: "Trend" },
  gear: { zh: "设备", en: "Gear" },
  city: { zh: "城市", en: "City" },
  hot: { zh: "热门", en: "Hot" },
};

var FICTIONAL_URL_HOSTS = ["ra.co","mixmag.net","theguardian.com","billboard.com","djmag.com","synthtopia.com","berliner.com"];

function isFictionalUrl(url) {
  if (!url) return false;
  for (var i = 0; i < FICTIONAL_URL_HOSTS.length; i++) {
    if (url.indexOf(FICTIONAL_URL_HOSTS[i]) !== -1) return true;
  }
  return false;
}

function enrichItems(items, lang) {
  return items.map(function(item) {
    var fm = item.foreignMedia || "";
    item.hasForeignMedia = fm && !/^暂无|不代表不重要/.test(fm);
    item.isFictionalUrl = isFictionalUrl(item.eventUrl);
    var td = TAG_DISPLAY[item.tag] || TAG_DISPLAY.dj;
    item.tagDisplay = td[lang] || td.zh;
    return item;
  });
}

Page({
  data: {
    lang: "zh",
    t: text("column", "zh"),
    items: [],
    filteredItems: [],
    tags: [],
    activeTag: "all",
    loading: true,
    loadFailed: false,
  },

  onLoad: function() {
    enableShareMenu();
    var l = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("column", l);
    var tags = TAG_LIST.map(function(t) {
      return { key: t.key, label: t[l] || t.zh };
    });
    this.setData({ lang: l, t: text("column", l), tags: tags });
    this.fetchColumnItems();
  },

  onPullDownRefresh: function() {
    this.fetchColumnItems();
  },

  fetchColumnItems: function() {
    var that = this;
    var appInstance = getApp();
    var cloud = appInstance.globalData.cloud;
    var baseUrl = cloud.publicBaseUrl || "";
    var url = baseUrl + "/api/v1/weekly/column?lang=" + (that.data.lang || "zh");

    that.setData({ loading: true, loadFailed: false });

    wx.request({
      url: url,
      method: "GET",
      timeout: 5000,
      success: function(res) {
        var data = res.data || {};
        var items = Array.isArray(data.items) && data.items.length > 0
          ? data.items
          : HARDCODED_ITEMS;
        var enriched = enrichItems(items, that.data.lang);
        that.setData({
          items: enriched,
          filteredItems: enriched,
          loading: false,
          loadFailed: false,
        });
      },
      fail: function() {
        var enriched = enrichItems(HARDCODED_ITEMS, that.data.lang);
        that.setData({
          items: enriched,
          filteredItems: enriched,
          loading: false,
          loadFailed: true,
        });
      },
      complete: function() {
        wx.stopPullDownRefresh();
      },
    });
  },

  onTagTap: function(e) {
    var key = e.currentTarget.dataset.tag;
    var filtered = key === "all"
      ? this.data.items
      : this.data.items.filter(function(item) { return item.tag === key; });
    this.setData({ activeTag: key, filteredItems: filtered });
  },

  onCardTap: function(e) {
    var id = e.currentTarget.dataset.id;
    var items = this.data.filteredItems;
    for (var i = 0; i < items.length; i++) {
      if (items[i].id === id) {
        var key = "filteredItems[" + i + "].expanded";
        this.setData({ [key]: !items[i].expanded });
        break;
      }
    }
  },

  onTabItemTap: function() {
    vibrateLight();
  },

  onShareAppMessage: function(e) {
    var target = e.target || {};
    var dataset = target.dataset || {};
    var itemId = dataset.id;
    var itemTitle = dataset.title;
    if (itemId && itemTitle) {
      return buildSimpleShare(
        itemTitle,
        "/pages/column/column",
        { lang: this.data.lang, highlight: itemId }
      );
    }
    return buildSimpleShare(
      this.data.lang === "en" ? "Upcoming DJs" : "未来演出DJ介绍",
      "/pages/column/column",
      { lang: this.data.lang }
    );
  },

  onShareTimeline: function() {
    return buildSimpleTimeline(
      this.data.lang === "en" ? "Upcoming DJs" : "未来演出DJ介绍",
      { lang: this.data.lang }
    );
  },

  openSourceLink: function(e) {
    var u = e.currentTarget.dataset.url;
    if (!u) return;
    var t = this.data.t;
    wx.setClipboardData({
      data: u,
      success: function() {
        wx.showModal({
          title: t.linkCopiedTitle || "已复制",
          content: (t.linkCopiedBody || "请在浏览器粘贴打开") + "\n\n" + u,
          showCancel: false,
          confirmText: t.linkCopiedConfirm || "知道了",
        });
      },
    });
  },
});
