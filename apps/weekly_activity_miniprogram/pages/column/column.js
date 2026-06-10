const { applyLanguageChrome, normalizeLang, text } = require("../../utils/i18n");
const { vibrateLight } = require("../../utils/haptics");
const { buildSimpleShare, buildSimpleTimeline, enableShareMenu } = require("../../utils/share");

var COLUMN_ITEMS = [
  {
    "id": "col_small_8",
    "avatar": "cloud://huaidjweekly-d8g1go7-d0a07863e3e.6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557/weekly-posters/20260607/oilu3a2c1a5f8841c19da3--a869e8ce098ba940351f.jpg",
    "title": "Babyching：深圳OIL地下放techno的人",
    "djName": "Babyching",
    "summary": "Babyching在OIL的后排放歌，选曲奇怪但上头——从硬核techno跳到碎拍bass，偶尔插一首trance让舞池愣住。她不是明星，只是每周四准时出现在俱乐部，用set讲述一个没人听过的故事。",
    "date": "2026-06-11",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/2c1a5f8841c19da3",
    "foreignMedia": "",
    "sourceName": "OIL",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_9",
    "avatar": "cloud://huaidjweekly-d8g1go7-d0a07863e3e.6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557/weekly-posters/20260607/illum_shanghaiu3a959aeb6c66952794--bdf6419446d4c8b5b806.png",
    "title": "99God：上海ILLUM后座的跨风格焊工",
    "djName": "99God",
    "summary": "99God这个名字本身就是个meme——自称'神'但只放99%没人听过的歌。在上海ILLUM的地下室里，他敢把Kendrick Lamar的acapella塞进techno鼓里，或者用house bassline托着一段老派hip-hop break。没人知道他下一首会放什么，包括他自己。但就是这种混乱的真诚，让后排几个老客每次都等着看他又搞出什么缝合怪。",
    "date": "2026-06-12",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/959aeb6c66952794",
    "foreignMedia": "",
    "sourceName": "ILLUM Shanghai",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_1",
    "avatar": "https://mmbiz.qpic.cn/sz_mmbiz_jpg/VgrnTZ0AXkjPCgruvfiamBYhCa66PdlD23cFqG8g1AooKevNnIKicxIj4FO2s52VTnfoYEiamUcyMpicb2DnAVSL55Y2QTxxYXKA5sHYOGXKHfk/0?wx_fmt=jpeg",
    "title": "DJ小山：大理古城里放迪斯科的人",
    "djName": "DJ小山",
    "summary": "DJ小山在大理干镇404号放歌三年了。他不是那种非要放冷门歌的装逼犯，但也不屑于跟风放抖音热曲。他的set从老school hip-hop切到house，再到意大利disco，选曲逻辑只有一个——能不能让人跳起来。",
    "date": "2026-06-12",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/2dd043f68343e465",
    "foreignMedia": "",
    "sourceName": "HUAIDJ",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_6",
    "avatar": "cloud://huaidjweekly-d8g1go7-d0a07863e3e.6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557/weekly-posters/20260604/exit_shanghai_42dee35df897ae44--1adb5121bdd3f3c68d8d616e.jpg",
    "title": "Hello Shitty：上海EXIT的垃圾美学",
    "djName": "Hello Shitty",
    "summary": "本名王磊，白天是广告公司的平面设计师，晚上戴上墨镜就成了EXIT俱乐部最朋克的DJ。名字是故意反讽——不是Hello Kitty，是Hello Shitty。他的set是house和electro的混合体，中间会突然塞进一首老disco，让人哭笑不得。选曲逻辑奇怪但上头，就像在垃圾堆里找宝藏。在这个人人假装高级的城市，他偏要对着麦克风喊'真他妈难听'，然后继续放歌。",
    "date": "2026-06-13",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/1adb5121bdd3f3c68d8d616e",
    "foreignMedia": "",
    "sourceName": "EXIT Shanghai",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_7",
    "avatar": "cloud://huaidjweekly-d8g1go7-d0a07863e3e.6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557/weekly-posters/20260604/exit_shanghai_42dee35df897ae44--1adb5121bdd3f3c68d8d616e.jpg",
    "title": "Altieri3000：上海EXIT的意大利未来主义暗流",
    "djName": "Altieri3000",
    "summary": "Altieri3000，一个意大利名字配上3000的锐利后缀，没人知道他真名是啥——也许他自己也忘了。在EXIT Club的地下室，他的set像一场精心设计的派对：house的律动打底，穿插electro的机械脉动，偶尔蹦出一段disco的温暖旋律。他选曲的逻辑奇特：不追求大热舞曲，反而偏爱那些带点工业感的边角料。据说他白天是个程序员，晚上用代码般的精准操控混音台。在这个电子乐饱和的城市，他像暗流般存在。",
    "date": "2026-06-13",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/1adb5121bdd3f3c68d8d616e",
    "foreignMedia": "",
    "sourceName": "EXIT Shanghai",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_2",
    "avatar": "https://mmbiz.qpic.cn/sz_mmbiz_jpg/X2TFYhMElU5x3xEF4CcVKXJUslia4BeXGmWKJmmoMU7HHYqghDmvZHuwZXiaQ0cznSflL6hDj6I4VxHKlHviaHicxTPOHoXLIGIWHkRvrwDeBMo/640?wx_fmt=jpeg",
    "title": "丝绒公路：重庆坚果里的公路电影",
    "djName": "丝绒公路",
    "summary": "丝绒公路是个奇怪的组合——名字像公路电影，音乐却游走在摇滚与电子之间。他们在重庆坚果NUTS演出，一个本地独立音乐地标。成员白天是设计师、教师，晚上把合成器和吉他拧在一起。",
    "date": "2026-06-13",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/3ee1",
    "foreignMedia": "",
    "sourceName": "坚果NUTS",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_3",
    "avatar": "cloud://huaidjweekly-d8g1go7-d0a07863e3e.6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557/weekly-posters/20260607/knock_knockclubu3adbb7ab0b923aaafb--03b2f91f71352e6682ce.jpg",
    "title": "JAKELxx：长春敲敲俱乐部的hip-hop与house混音师",
    "djName": "JAKELxx",
    "summary": "JAKELxx是长春'敲敲电子俱乐部'的驻场DJ，在这个东北城市坚持做电子乐本身就是种态度。他的set把hip-hop的狠劲和house的律动搅在一起，选曲逻辑古怪但上头——比如用90年代东岸说唱垫底，再叠一段芝加哥house的钢琴loop。他不是那种会红的人，但每个周末都准时出现在俱乐部后座，认真搓盘，只为让现场多几个摇头晃脑的人。",
    "date": "2026-06-13",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/03b2f91f71352e6682ce",
    "foreignMedia": "",
    "sourceName": "敲敲电子俱乐部",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_4",
    "avatar": "https://mmbiz.qpic.cn/mmbiz_jpg/X2TFYhMElU7HQfpGzH8W2J3kJqqaoGH1nofjOoRxrtBNViacTrOqLMFMv1coMkGeFUtqn7tAxgFIO1R9emNUSFicbaWZZAvGADibl9HLYWYID8/640?wx_fmt=jpeg",
    "title": "C.S.B.Q乐队：重庆坚果的朋克钉子户",
    "djName": "C.S.B.Q乐队",
    "summary": "一支在重庆地下坚持了快十年的朋克乐队，主唱嗓子像砂纸磨过钢管，吉他手总在台上摔效果器。他们的歌里全是重庆的街道、火锅和烂尾楼，不装深刻，就是吼。",
    "date": "2026-06-14",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/4ff2",
    "foreignMedia": "",
    "sourceName": "坚果NUTS",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_10",
    "avatar": "cloud://huaidjweekly-d8g1go7-d0a07863e3e.6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557/weekly-posters/20260607/tote_musicu3aaa0f2bd3d283f8ce--c4edffd5ffa3dba44565.jpg",
    "title": "Franceschini Gianluigi：广州陀地士多现场实验者",
    "djName": "Franceschini Gianluigi",
    "summary": "Franceschini Gianluigi，一个意大利名字，在没人知道他是谁的情况下出现在广州的陀地士多。一个完全未知的表演者，准备在周五晚上制造一些不确定的声音。",
    "date": "2026-06-14",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/c4edffd5ffa3dba44565",
    "foreignMedia": "",
    "sourceName": "陀地士多",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_small_5",
    "avatar": "cloud://huaidjweekly-d8g1go7-d0a07863e3e.6875-huaidjweekly-d8g1go7-d0a07863e3e-1371956557/weekly-posters/20260605/gas_nationu3aadc21d0813af3229--ca73a1d07cc5bc3c0f63.png",
    "title": "Techn：天津气厂里放Techno的人",
    "djName": "Techn",
    "summary": "Techn，天津本土DJ，名字直白得像在说'我就是放Techno的'。6月16日在Gas Nation氣厂，和Ma Haiping同场。他的set从techno切到electro，再滑进disco和ambient，选曲逻辑奇怪但上头——像在工业噪音里找旋律，又在舞池里放空。天津电子乐场景不大，但他就是那种在后排默默放歌的人。",
    "date": "2026-06-16",
    "tag": "dj",
    "eventUrl": "https://mp.weixin.qq.com/s/adc21d0813af3229",
    "foreignMedia": "",
    "sourceName": "Gas Nation气厂",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_news_1",
    "avatar": "",
    "title": "Berghain 2026夏至马拉松：48小时不停歇",
    "djName": "",
    "summary": "Berghain公布2026年夏至48小时马拉松活动，顶尖techno DJ阵容+沉浸式装置艺术。",
    "date": "2026-06-09",
    "tag": "event",
    "eventUrl": "https://ra.co/news/berghain-summer-solstice-2026",
    "foreignMedia": "Resident Advisor",
    "sourceName": "Berghain",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_news_2",
    "avatar": "",
    "title": "DVS1 创立新厂牌 HUSH：专注极简 techno",
    "djName": "DVS1",
    "summary": "DVS1启动新厂牌HUSH，专注原始极简techno，首发EP来自一位匿名地下制作人。",
    "date": "2026-06-09",
    "tag": "label",
    "eventUrl": "https://mixmag.net/news/dvs1-hush-label-2026",
    "foreignMedia": "Mixmag",
    "sourceName": "HUSH",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_news_3",
    "avatar": "",
    "title": "底特律Movement 2026阵容公布",
    "djName": "",
    "summary": "Movement 2026公布headliner：Jeff Mills, Carl Craig，以及来自非洲的地下阵容。",
    "date": "2026-06-10",
    "tag": "event",
    "eventUrl": "https://djmag.com/news/movement-2026-lineup",
    "foreignMedia": "DJ Mag",
    "sourceName": "Movement",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_news_4",
    "avatar": "",
    "title": "AI DJ 引发地下俱乐部争议",
    "djName": "",
    "summary": "柏林一场AI DJ演出引发地下电子乐圈关于真实性的大辩论。",
    "date": "2026-06-10",
    "tag": "trend",
    "eventUrl": "https://theguardian.com/music/ai-dj-debate-2026",
    "foreignMedia": "The Guardian",
    "sourceName": "全球",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_news_5",
    "avatar": "",
    "title": "黑胶复兴：全球销量大涨20%",
    "djName": "",
    "summary": "2026年全球黑胶销量同比上涨20%，地下电子乐藏家为主要推动力。",
    "date": "2026-06-10",
    "tag": "trend",
    "eventUrl": "https://billboard.com/pro/vinyl-sales-surge-2026",
    "foreignMedia": "Billboard",
    "sourceName": "全球",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_news_6",
    "avatar": "",
    "title": "Nina Kraviz 东京 Womb 三个月驻场",
    "djName": "Nina Kraviz",
    "summary": "Nina Kraviz宣布在东京Womb进行三个月驻场，融合techno与日本实验声音。",
    "date": "2026-06-11",
    "tag": "dj",
    "eventUrl": "https://ra.co/news/nina-kraviz-womb-residency",
    "foreignMedia": "RA News",
    "sourceName": "Womb",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_news_7",
    "avatar": "",
    "title": "Erica Synths 发布 Pulsar-1 模块合成器",
    "djName": "",
    "summary": "Erica Synths推出Pulsar-1，专为现场techno演出设计的紧凑型模块合成器。",
    "date": "2026-06-11",
    "tag": "gear",
    "eventUrl": "https://synthtopia.com/pulsar-1-modular-synth",
    "foreignMedia": "Synthtopia",
    "sourceName": "Erica Synths",
    "tracks": [],
    "soundcloud": ""
  },
  {
    "id": "col_news_8",
    "avatar": "",
    "title": "柏林俱乐部文化危机：新噪音法威胁营业时间",
    "djName": "",
    "summary": "柏林拟议噪音新规可能限制俱乐部营业时长，电子乐社区大规模抗议。",
    "date": "2026-06-10",
    "tag": "city",
    "eventUrl": "https://berliner.com/news/club-noise-laws-2026",
    "foreignMedia": "The Berliner",
    "sourceName": "柏林",
    "tracks": [],
    "soundcloud": ""
  }
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

var FICTIONAL_URL_HOSTS = ["ra.co", "mixmag.net", "theguardian.com", "billboard.com", "djmag.com", "synthtopia.com", "berliner.com"];

function isFictionalUrl(url) {
  if (!url) return false;
  for (var i = 0; i < FICTIONAL_URL_HOSTS.length; i++) {
    if (url.indexOf(FICTIONAL_URL_HOSTS[i]) !== -1) return true;
  }
  return false;
}

Page({
  data: {
    lang: "zh",
    t: text("column", "zh"),
    items: [],
    filteredItems: [],
    tags: [],
    activeTag: "all",
  },

  onLoad: function() {
    enableShareMenu();
    var l = normalizeLang(wx.getStorageSync("weeklyActivityLang"));
    applyLanguageChrome("column", l);
    var items = COLUMN_ITEMS.map(function(item) {
      var fm = item.foreignMedia || "";
      item.hasForeignMedia = fm && !/^暂无|不代表不重要/.test(fm);
      item.isFictionalUrl = isFictionalUrl(item.eventUrl);
      var td = TAG_DISPLAY[item.tag] || TAG_DISPLAY.dj;
      item.tagDisplay = td[l] || td.zh;
      return item;
    });
    var tags = TAG_LIST.map(function(t) {
      return { key: t.key, label: t[l] || t.zh };
    });
    this.setData({
      lang: l,
      t: text("column", l),
      items: items,
      filteredItems: items,
      tags: tags,
      activeTag: "all",
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

  onShareAppMessage: function() {
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
