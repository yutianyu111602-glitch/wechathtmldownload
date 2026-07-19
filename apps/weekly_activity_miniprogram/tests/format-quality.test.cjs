const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  areLikelyDuplicateItems,
  atlasEventToWeeklyItem,
  compactDateRange,
  compactItem,
  dedupeItems,
  dedupeKeyForItem,
  mergeNonEmpty,
  isDisplayUrlLine,
} = require("../utils/format");
const { dateDisplay, localizeItem, priceText, translateCity } = require("../utils/i18n");
const { sourceHashOf } = require("../utils/sourceArticles");

function baseItem(overrides = {}) {
  return {
    id: "test:item",
    title: "Test Event",
    title_display: "",
    event_date_start: "2026-05-14",
    event_date_iso_guess: "2026-05-14",
    event_time_text: "",
    event_time_source: "",
    city: ["上海"],
    city_key: "shanghai",
    venue_name: "EXIT Shanghai",
    venue: ["EXIT Shanghai"],
    account: "EXIT Shanghai",
    promoter: "exit_shanghai",
    quality_status: "READY",
    source_action: { url_hash: "1234567890abcdef", available: true },
    evidence: [],
    lineup: [],
    lineup_artists: [],
    ...overrides,
  };
}

function test(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (error) {
    console.error(`not ok - ${name}`);
    throw error;
  }
}

test("dedupe key ignores emoji and punctuation in duplicate event titles", () => {
  const first = compactItem(baseItem({ id: "a", title: "JACK'N" }));
  const second = compactItem(baseItem({ id: "b", title: "📌 JACK'N" }));
  assert.equal(dedupeKeyForItem(first), dedupeKeyForItem(second));
});

test("compact item hides venue-default time and keeps source-text time", () => {
  const defaultTime = compactItem(baseItem({
    event_time_text: "22:00 - Late",
    event_time_source: "venue_default",
  }));
  const sourceTime = compactItem(baseItem({
    event_time_text: "22:00 - Late",
    event_time_source: "source_text",
  }));

  assert.equal(defaultTime.hasTime, false);
  assert.equal(defaultTime.timeLabel, "");
  assert.equal(sourceTime.hasTime, true);
  assert.equal(sourceTime.timeLabel, "22:00 - Late");
});

test("compact item repairs weak schedule title from VL poster evidence", () => {
  const item = compactItem(baseItem({
    id: "loopy-weak-title",
    title: "loopy Club｜06.21 / 周日 / 15:30",
    title_display: "/ 周日 / 15:30",
    city: ["杭州"],
    city_key: "hangzhou",
    venue_name: "loopy Club",
    venue: ["loopy Club"],
    account: "loopy Club",
    promoter: "loopy Club",
    lineup_artists: ["Endy", "Jerry", "Golgol", "小喇叭"],
    poster_selection_evidence: {
      visible_text_lines: [
        "loopy Club",
        "06.21",
        "周日",
        "15:30",
        "loopy x Open M pres. 夜游",
        "Off-duty 唱机龙舟",
        "Endy Jerry Golgol 小喇叭",
      ],
    },
  }));

  assert.equal(item.displayTitle, "loopy x Open M pres. 夜游 / Off-duty 唱机龙舟");
});

test("compact item normalizes pres and hyphen spacing in backend titles", () => {
  const item = compactItem(baseItem({
    id: "loopy-spacing",
    title: "loopy Club｜6.21 周日｜loopy x Open M pres.夜游 / Off - duty 唱机龙舟",
    title_display: "loopy x Open M pres.夜游 / Off - duty 唱机龙舟",
    city: ["杭州"],
    city_key: "hangzhou",
    venue_name: "loopy Club",
    venue: ["loopy Club"],
    account: "loopy Club",
    promoter: "loopy Club",
  }));

  assert.equal(item.displayTitle, "loopy x Open M pres. 夜游 / Off-duty 唱机龙舟");
});

test("compact item keeps ordinary English dash title separators", () => {
  const item = compactItem(baseItem({
    id: "open-decks-title",
    title: "06.21 周日｜Open Decks - Shamone",
    title_display: "Open Decks - Shamone",
    city: ["成都"],
    city_key: "chengdu",
    venue_name: "Bar.woody",
    venue: ["Bar.woody"],
    account: "一同ChengDu",
    promoter: "一同ChengDu",
  }));

  assert.equal(item.displayTitle, "Open Decks - Shamone");
});

test("compact item does not strip weekday letters inside event words", () => {
  const item = compactItem(baseItem({
    id: "friendsstand-title",
    title: "06.21 FRIENDSSTAND 粘友力站点 @ wigwam",
    title_display: "FRIENDSSTAND 粘友力站点 @ wigwam",
    venue: ["wigwam"],
    city: ["上海"],
  }));

  assert.equal(item.displayTitle, "FRIENDSSTAND 粘友力站点 @ wigwam");
});

test("compact item does not leave broken floor-like brand prefixes in titles", () => {
  const item = compactItem(baseItem({
    id: "stereo-title",
    title: "52/F Pres.｜6.26 周五｜ 联合呈现：打破边界的地下电子声浪",
    title_display: "52/F Pres. | 联合呈现：打破边界的地下电子声浪",
    venue: ["52/F"],
    city: ["上海"],
  }));

  assert.equal(item.displayTitle, "联合呈现：打破边界的地下电子声浪");
  assert.equal(item.displayTitle.startsWith("F Pres."), false);
});

test("compact item repairs English weekday-only title from VL poster evidence", () => {
  const item = compactItem(baseItem({
    id: "dada-sun-title",
    title: "Dada Bar Beijing｜6月21日 星期日 Sun.",
    title_display: "Sun.",
    city: ["北京"],
    city_key: "beijing",
    venue_name: "Dada Bar Beijing",
    venue: ["Dada Bar Beijing"],
    account: "Dada Bar Beijing",
    promoter: "Dada Bar Beijing",
    lineup_artists: ["Zean", "Sai G", "BAADAAM", "Puzzy Stack"],
    poster_selection_evidence: {
      visible_text_lines: [
        "周日 6月21日 京沪对决，Gully Boys 围捕寿星 Puzzy Stack",
        "ZEAN BAADAAM SAI G PUZZY STACK",
        "北京朝阳区南营坊胡同日坛国际贸易中心A座北门B1",
        "21:00-Late",
      ],
    },
  }));

  assert.equal(item.displayTitle, "京沪对决，Gully Boys 围捕寿星 Puzzy Stack");
});

test("compact item strips dangling bracket and time after date prefix", () => {
  const item = compactItem(baseItem({
    title: "陀地音乐TOTE MUSIC｜7/4 周六】22:00，小白爵士大乐队swing音乐跳舞派对",
    title_display: "】22:00，小白爵士大乐队swing音乐跳舞派对",
    venue_name: "陀地士多 Tote Store",
    venue: ["陀地士多 Tote Store"],
    account: "陀地音乐TOTE MUSIC",
    promoter: "陀地音乐TOTE MUSIC",
  }));

  assert.equal(item.displayTitle, "小白爵士大乐队swing音乐跳舞派对");
});

test("compact item rejects city-only title and falls back to poster event title", () => {
  const item = compactItem(baseItem({
    title: "坚果NUTS｜6/28 惠州",
    title_display: "惠州",
    venue_name: "坚果NUTS",
    venue: ["坚果NUTS"],
    account: "坚果NUTS",
    promoter: "坚果NUTS",
    lineup_artists: ["莫迪戈", "超级查理"],
    poster_selection_evidence: {
      visible_text_lines: [
        "2026 GOJAM JOINT TOUR",
        "燃烧直到终老 BURN TILL THE END 联合专场",
        "莫迪戈",
        "超级查理",
        "惠州 06.28 VOX LIVEHOUSE",
      ],
    },
  }));

  assert.equal(item.displayTitle, "燃烧直到终老 BURN TILL THE END 联合专场 / 2026 GOJAM JOINT TOUR");
});

test("compact item rejects English address line as title evidence", () => {
  const item = compactItem(baseItem({
    title: "光芒enlightening｜6月23日",
    title_display: "光芒enlightening｜6月23日",
    venue_name: "光芒喜剧脱口秀",
    venue: ["光芒喜剧脱口秀"],
    account: "光芒enlightening",
    promoter: "光芒enlightening",
    poster_selection_evidence: {
      visible_text_lines: [
        "Guangzhou Book Shopping Center No.123",
        "Tian-He Avenue",
        "Tian-he District",
        "6月23日",
        "贝多芬：第3号交响曲《英雄》",
        "贝多芬：Egmont《艾格蒙特》",
      ],
    },
  }));

  assert.equal(item.displayTitle, "贝多芬：第3号交响曲《英雄》");
});

test("compact item strips promo prefix and leading vertical separator", () => {
  const item = compactItem(baseItem({
    title: "Cedar Kitchen｜6.21丨转发打七折！周日幸运转盘赢优惠，ReCharge / ReLink 充电/重连",
    title_display: "丨转发打七折！周日幸运转盘赢优惠，ReCharge / ReLink 充电/重连",
    venue_name: "Cedar Kitchen",
    venue: ["Cedar Kitchen"],
    account: "Cedar Kitchen",
    promoter: "Cedar Kitchen",
  }));

  assert.equal(item.displayTitle, "ReCharge / ReLink 充电/重连");
});

test("compact item strips slash date ranges before event title", () => {
  const item = compactItem(baseItem({
    title: "莫须有工舍｜6.27/28｜「交流方式」夏日祭 + Promis3",
    title_display: "莫须有工舍 | 28 | 「交流方式」夏日祭 + Promis3",
    venue_name: "莫须有工厂",
    venue: ["莫须有工厂"],
    account: "莫须有工舍",
    promoter: "莫须有工舍",
  }));

  assert.equal(item.displayTitle, "「交流方式」夏日祭 + Promis3");
});

test("compact item rejects sale-status venue row and falls back to tour poster title", () => {
  const item = compactItem(baseItem({
    title: "TOMTWO通透现场｜06/21 上海｜FENRIR（即将开售）",
    title_display: "FENRIR（即将开售）",
    venue_name: "TOMTWO通透现场",
    venue: ["通透现场"],
    account: "TOMTWO通透现场",
    promoter: "TOMTWO通透现场",
    poster_selection_evidence: {
      visible_text_lines: [
        "花溪「逃离黑夜」2026巡演",
        "21 上海 FENRIR",
      ],
    },
  }));

  assert.equal(item.displayTitle, "花溪「逃离黑夜」2026巡演");
});

test("compact item strips year date ranges and drops venue-only suffix", () => {
  const item = compactItem(baseItem({
    title: "2026.6.27&28 大庆北野青年音乐浪潮|锈蚀俱乐部",
    title_display: "锈蚀俱乐部",
    venue_name: "Rust Club 锈蚀俱乐部",
    venue: ["锈蚀俱乐部"],
    account: "Rust Club 锈蚀俱乐部",
    promoter: "Rust Club 锈蚀俱乐部",
  }));

  assert.equal(item.displayTitle, "大庆北野青年音乐浪潮");
});

test("compact item prefers verified venue coordinates when package carries stale address fields", () => {
  const item = compactItem(baseItem({
    id: "loopy:stale-address",
    city: ["杭州"],
    city_key: "hangzhou",
    venue_name: "loopy Club",
    venue: ["loopy"],
    account: "loopy Club",
    promoter: "loopy_club",
    address: "浙江省杭州市西湖区天目山路398号天目里7号楼负一层",
    address_full: "浙江省杭州市上城区中山南路77号利星名品广场3楼313室",
    address_source: "manual_registry",
    venue_lat: 30.2642,
    venue_lng: 120.1273,
  }));

  assert.equal(item.addressLabel, "浙江省杭州市西湖区天目山路398号天目里7号楼负一层");
  assert.equal(item.mapLocation.latitude, 30.267023);
  assert.equal(item.mapLocation.longitude, 120.098623);
});

test("compact item does not show 3am free-entry cutoff as 3 yuan ticket", () => {
  const item = compactItem(baseItem({
    price: ["￥ 3", "免费入场"],
    ticketing_text: "3am 后免费入场",
  }));

  assert.deepEqual(item.price, ["3am 后免费入场"]);
  assert.equal(item.hasPrice, true);
});

test("compact item recovers source-backed tiered ticketing before stale price", () => {
  const item = compactItem(baseItem({
    price: ["￥ 3", "免费入场"],
    ticketing_text: "3am 后免费入场",
    evidence: ["ENTRY 预售 70￥ 双人 128￥ 现场 100￥ 3am 后免费入场"],
  }));

  assert.deepEqual(item.price, ["预售 70¥", "双人 128¥", "现场 100¥", "3am 后免费入场"]);
  assert.equal(item.priceLabel, "预售 70¥ / 双人 128¥ / 现场 100¥ / 3am 后免费入场");
});

test("compact item trims article-body noise from overlong backend display titles", () => {
  const item = compactItem(baseItem({
    id: "nuts:f8b566f41a4d222b:schedule:20260522:2",
    venue_name: "坚果NUTS",
    venue: ["坚果NUTS"],
    account: "坚果NUTS",
    promoter: "坚果NUTS",
    city: ["重庆"],
    title: "坚果NUTS｜5/22 20:00 @NUTS Puppy's Bone 小狗的骨头🦴 2026「NEW OLD BODY」巡演 顺利启程 感谢摄影师📷 上海站：大香米饭 深圳站：AKU、一直在戒酒的阿源 广州站： AD阿冻 厦门站： 一般通过登涂子 感谢大家的陪伴 短暂休整后 我们五月再见👋 海报设计：祁正 5.22 20:00 重庆 @坚果NUTS 票务信息 预售票 ¥120 全价票 ¥150 双人票 ¥200 点击购票 ☟ 现场周边售卖 *当日在售周边仅实体唱片及海报可参与签售 本次巡演签售不设置合照环节",
    title_display: "@NUTS Puppy's Bone 小狗的骨头🦴 2026「NEW OLD BODY」巡演 顺利启程 感谢摄影师📷 上海站：大香米饭 深圳站：AKU、一直在戒酒的阿源 广州站： AD阿冻 厦门站： 一般通过登涂子 感谢大家的陪伴 短暂休整后 我们五月再见👋 海报设计：祁正 5.22 20:00 重庆 @坚果NUTS 票务信息 预售票 ¥120 全价票 ¥150 双人票 ¥200 点击购票 ☟ 现场周边售卖 *当日在售周边仅实体唱片及海报可参与签售 本次巡演签售不设置合照环节",
  }));

  assert.equal(item.displayTitle, "Puppy's Bone 小狗的骨头 2026「NEW OLD BODY」巡演");
  assert.equal(item.displayTitle.includes("票务信息"), false);
  assert.equal(item.displayTitle.includes("预售票"), false);
  assert.equal(item.displayTitle.includes("感谢摄影师"), false);
});

test("compact item ignores entity-only display titles and falls back to real event title", () => {
  const item = compactItem(baseItem({
    title: "旋律朋克Hello Franky，公路巡演到重庆｜5月24日@坚果NUTS",
    title_display: "@坚果NUTS",
    venue_name: "坚果NUTS",
    venue: ["坚果NUTS"],
    account: "坚果NUTS",
    promoter: "坚果NUTS",
  }));

  assert.equal(item.displayTitle, "旋律朋克Hello Franky，公路巡演到重庆");
});

test("compact item keeps cancellation marker but drops narrative article body", () => {
  const item = compactItem(baseItem({
    title: "坚果NUTS｜5/28 20:00 @NUTS 【本场活动取消】 曾经，我们把《野孩子的星空》当作一封寄往宇宙的信，写给所有在世俗规训下保留纯真的灵魂。 5.28 20:00 重庆 @坚果NUTS / 点击购票 / ☟ 早鸟：1元 预售：30元 全价：50元",
    title_display: "@NUTS 【本场活动取消】 曾经，我们把《野孩子的星空》当作一封寄往宇宙的信，写给所有在世俗规训下保留纯真的灵魂。 5.28 20:00 重庆 @坚果NUTS / 点击购票 / ☟ 早鸟：1元 预售：30元 全价：50元",
    venue_name: "坚果NUTS",
    venue: ["坚果NUTS"],
    account: "坚果NUTS",
    promoter: "坚果NUTS",
  }));

  assert.equal(item.displayTitle, "【本场活动取消】《野孩子的星空》");
});

test("compact item does not cross evidence lines into a date-like ticket price", () => {
  const item = compactItem(baseItem({
    price: ["￥ 3", "免费入场"],
    ticketing_text: "3am 后免费入场",
    evidence: ["ENTRY ←Click for tickets 预售", "2026-05-22"],
    _source_queue_text: "ENTRY ←Click for tickets 预售 70￥ 双人 128￥ 现场 100￥ 3am 后免费入场",
  }));

  assert.deepEqual(item.price, ["预售 70¥", "双人 128¥", "现场 100¥", "3am 后免费入场"]);
  assert.equal(item.price.includes("预售 2026"), false);
});

test("compact item hides YuYuan-only ticketing when no amount is visible", () => {
  const item = compactItem(baseItem({
    price: [],
    ticketing_text: "🎫购票链接🔗 芋圆YuYuan",
    evidence: ["🎫购票链接🔗 芋圆YuYuan"],
  }));

  assert.deepEqual(item.price, []);
  assert.equal(item.hasPrice, false);
});

test("compact item does not publish drink special as ticket price", () => {
  const item = compactItem(baseItem({
    price: ["FREE ENTRY", "69￥"],
    ticketing_text: "FREE ENTRY / 特别放送：69￥ 2杯金汤力",
    evidence: ["FREE ENTRY", "特别放送：69￥ 2杯金汤力"],
  }));

  assert.deepEqual(item.price, ["FREE ENTRY"]);
});

test("sentence-like lineup values are suppressed and replaced with a source hint", () => {
  const item = compactItem(baseItem({
    account: "WITH BAR",
    promoter: "with_bar",
    venue_name: "北京WITH BAR",
    venue: ["北京WITH BAR"],
    title: "WITH · Stop Motion DJs Weekly",
    lineup_artists: [
      "PILLBOX创意成员",
      "在 Herrensauna",
      "NTS",
      "Sachsentrance",
      "PILLBOX",
    ],
  }));

  assert.deepEqual(item.lineupItems, []);
  assert.equal(item.hasLineup, false);
  assert.equal(item.hasLineupHint, true);
  assert.equal(item.lineupHint, "点击海报跳转公众号原文查看");
});

test("simple artist names survive conservative lineup filtering", () => {
  const item = compactItem(baseItem({
    title: "Let's 显化",
    venue_name: "POTENT",
    venue: ["POTENT"],
    account: "POTENT",
    promoter: "potent",
    lineup_artists: ["Hadone", "Julian Muller", "QIUQIU"],
  }));

  assert.deepEqual(item.lineupItems, ["Hadone", "Julian Muller", "QIUQIU"]);
  assert.equal(item.hasLineup, true);
  assert.equal(item.hasLineupHint, false);
});

test("compact item splits and dedupes VL lineup strings before display", () => {
  const item = compactItem(baseItem({
    title: "All Night Club Session",
    venue_name: "loopy Club",
    venue: ["loopy Club"],
    account: "loopy Club",
    lineup: ["DJ Huáng / Huang / NOIZOME，Zhou Ning｜NOIZOME"],
  }));

  assert.deepEqual(item.lineupItems, ["DJ Huáng", "NOIZOME", "Zhou Ning"]);
  assert.equal(item.lineupLabel, "DJ Huáng / NOIZOME / Zhou Ning");
  assert.equal(item.hasLineup, true);
});

test("compact item accepts Qwen VL lineup aliases and removes role suffixes", () => {
  const item = compactItem(baseItem({
    title: "Qwen VL Club Session",
    venue_name: "loopy Club",
    venue: ["loopy Club"],
    account: "loopy Club",
    qwen_vl_lineup: ["Lineup: Jasmin (DJ Set) / NOIZOME Live / Zhou Ning support / Jasmin"],
  }));

  assert.deepEqual(item.lineupItems, ["Jasmin", "NOIZOME", "Zhou Ning"]);
  assert.equal(item.lineupLabel, "Jasmin / NOIZOME / Zhou Ning");
  assert.equal(item.hasLineup, true);
});

test("compact item keeps real multi-DJ lineup when one noisy token is present", () => {
  const item = compactItem(baseItem({
    title: "Poster VL Night",
    venue_name: "Dada",
    venue: ["Dada"],
    account: "Dada",
    lineup_artists: ["阵容", "MIIIA", "Knopha", "Dokedo", "Dazzy"],
  }));

  assert.deepEqual(item.lineupItems, ["MIIIA", "Knopha", "Dokedo", "Dazzy"]);
  assert.equal(item.hasLineup, true);
  assert.equal(item.hasLineupHint, false);
});

test("Shanghai cards prefer venue names over repeated city labels", () => {
  const item = compactItem(baseItem({
    city: ["上海"],
    city_key: "shanghai",
    venue_name: "EXIT Shanghai",
  }));

  assert.equal(item.cardLocationLabel, "EXIT Shanghai");
});

test("compact item exposes stable organizer key and club profile v1 shell", () => {
  const item = compactItem(baseItem({
    city: ["杭州"],
    city_key: "hangzhou",
    venue_name: "loopy Club",
    venue: ["loopy Club"],
    address: "杭州市测试路1号",
  }));

  assert.equal(item.organizerKey, "loopyclub");
  assert.deepEqual(item.clubProfile, {
    schemaVersion: "weekly_club_profile.v1",
    organizerKey: "loopyclub",
    displayName: "loopy Club",
    cityLabel: "杭州",
    addressLabel: "杭州市测试路1号",
  });
});

test("compact item preserves backend organizer key and club profile contract", () => {
  const item = compactItem(baseItem({
    organizer_key: "atlasclub001",
    club_profile: {
      schema_version: "weekly_club_profile.v1",
      organizer_key: "atlasclub001",
      display_name: "Atlas Club",
      address: "上海市测试路2号",
    },
    venue_name: "Atlas Club CN",
  }));

  assert.equal(item.organizerKey, "atlasclub001");
  assert.deepEqual(item.clubProfile, {
    schemaVersion: "weekly_club_profile.v1",
    organizerKey: "atlasclub001",
    displayName: "Atlas Club",
    cityLabel: "上海",
    addressLabel: "上海市测试路2号",
  });
});

test("compact item canonicalizes field aliases without empty fields wiping values", () => {
  const item = compactItem(baseItem({
    venue_name: "",
    venue: [],
    venueLabel: "Heim Shanghai",
    city: [],
    city_key: "",
    cityLabel: "上海",
    address: "",
    addressLabel: "上海市黄浦区长乐路462号M101",
    poster_url: "",
    coverUrl: "https://example.test/heim-main-poster.jpg",
    source_action: { url_hash: "", available: true },
    source_article: { url_hash: "", title: "" },
    sourceRefId: "src:heim",
    sourceHash: "hash-heim",
    sourceTitle: "今晚|Heim Club Night",
    sourceAccountName: "Heim Shanghai",
    sourcePublishedAt: "2026-05-09",
  }));

  assert.equal(item.venueLabel, "Heim Shanghai");
  assert.equal(item.cityLabel, "上海");
  assert.equal(item.addressLabel, "上海市黄浦区长乐路462号M101");
  assert.equal(item.coverUrl, "https://example.test/heim-main-poster.jpg");
  assert.equal(item.sourceHash, "hash-heim");
  assert.equal(item.sourceRefId, "src:heim");
  assert.equal(sourceHashOf(item), "src:heim");
  assert.equal(item.source_article.title, "今晚|Heim Club Night");
  assert.equal(item.source_article.account_name, "Heim Shanghai");
});

test("compact item routes Tencent article posters through CloudRun when no internal file ID exists", () => {
  const originalGetApp = global.getApp;
  global.getApp = () => ({
    globalData: {
      cloud: {
        publicBaseUrl: "https://weekly-api.example.test",
        posterUseRawSourceFirst: false,
      },
    },
  });
  try {
    const item = compactItem(baseItem({
      id: "poster-direct",
      coverUrl: "https://weekly-api.example.test/api/v1/weekly/poster/poster-direct",
      cover_image_url: "http://mmbiz.qpic.cn/sz_mmbiz_jpg/direct-poster/0?wx_fmt=jpeg&amp;from=appmsg#imgIndex=0",
    }));

    assert.equal(
      item.coverUrl,
      "https://weekly-api.example.test/api/v1/weekly/poster/poster-direct",
    );
    assert.doesNotMatch(item.coverUrl, /mmbiz\.qpic\.cn/);
  } finally {
    if (originalGetApp) {
      global.getApp = originalGetApp;
    } else {
      delete global.getApp;
    }
  }
});

test("compact item prefers internal CloudBase poster file IDs over public article URLs", () => {
  const item = compactItem(baseItem({
    id: "poster-file-id",
    poster_file_id: "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/poster-file-id.jpg",
    cover_image_url: "https://mmbiz.qpic.cn/sz_mmbiz_jpg/public-poster/0?wx_fmt=jpeg",
    coverUrl: "https://weekly-api.example.test/api/v1/weekly/poster/poster-file-id",
  }));

  assert.equal(
    item.coverUrl,
    "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/poster-file-id.jpg",
  );
  assert.equal(item.posterFileId, item.coverUrl);
  assert.doesNotMatch(item.coverUrl, /mmbiz\.qpic\.cn/);
  assert.doesNotMatch(item.coverUrl, /\/api\/v1\/weekly\/poster\//);
});

test("compact item suppresses aggregate child overview posters and source actions", () => {
  const item = compactItem(baseItem({
    id: "agg-child-poster-source",
    poster_suppressed: true,
    poster_file_id: "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/agg-child-poster-source.jpg",
    cover_image_url: "https://mmbiz.qpic.cn/sz_mmbiz_jpg/public-overview/0?wx_fmt=jpeg",
    source_action: { available: false, url_hash: "" },
    source_article: { url_hash: "overviewhash", title: "本周活动一览" },
  }));

  assert.equal(item.coverUrl, "");
  assert.equal(item.posterFileId, "cloud://atlas-prod.6174-atlas-prod-1250000000/posters/agg-child-poster-source.jpg");
  assert.equal(item.sourceHash, "");
  assert.equal(item.hasSource, false);
});

test("compact item fail-closes aggregate child source and poster even if upstream forgets flags", () => {
  const item = compactItem(baseItem({
    id: "agg-child-dirty-source",
    aggregation_child: true,
    poster_suppressed: false,
    poster_file_id: "cloud://atlas-prod.6174-atlas-prod-1250000000/weekly-posters/20260605/agg-child-dirty-source.jpg",
    sourceHash: "weekly-overview-hash",
    source_action: { available: true, url_hash: "weekly-overview-hash" },
    source_article: { url_hash: "weekly-overview-hash", title: "本周活动一览" },
  }));

  assert.equal(item.coverUrl, "");
  assert.equal(item.posterFileId, "cloud://atlas-prod.6174-atlas-prod-1250000000/weekly-posters/20260605/agg-child-dirty-source.jpg");
  assert.equal(item.sourceHash, "");
  assert.equal(item.hasSource, false);
  assert.equal(sourceHashOf(item), "");
});

test("monthly or weekly overview rows render only the original article title", () => {
  const item = compactItem(baseItem({
    id: "overview-derived-dj",
    title: "DJ Love",
    title_display: "DJ Love",
    source_article: {
      url_hash: "overviewhash",
      title: "loopy 六月活动一览",
      account_name: "loopy Club",
      published_at: "2026-05-25",
    },
    source_action: { available: true, url_hash: "overviewhash" },
    event_date_start: "2026-06-06",
    event_date_end: "2026-06-08",
    event_time_text: "22:00-Late",
    event_time_source: "source_text",
    lineup_artists: ["DJ Love", "Dapi"],
    price: ["预售 80¥"],
    music_styles: ["techno"],
    city: ["杭州"],
    city_key: "hangzhou",
    venue_name: "loopy Club",
    venue: ["loopy Club"],
    description_text: "Dapi / DJ Love",
  }));

  assert.equal(item.isSourceOverview, true);
  assert.equal(item.isCalendarPreview, true);
  assert.equal(item.displayTitle, "loopy 六月活动一览");
  assert.equal(item.dateLabel, "");
  assert.equal(item.dateRangeLabel, "");
  assert.equal(item.dateRangeCompact, "");
  assert.equal(item.weekdayLabel, "");
  assert.equal(item.detailMetaLine, "");
  assert.equal(item.cardLocationLabel, "");
  assert.deepEqual(item.lineupItems, []);
  assert.equal(item.lineupLabel, "");
  assert.equal(item.hasLineup, false);
  assert.equal(item.hasLineupHint, false);
  assert.equal(item.hasTime, false);
  assert.equal(item.hasPrice, false);
  assert.equal(item.hasStyle, false);
  assert.equal(item.hasDescription, false);
  assert.equal(item.hasSource, true);
  assert.equal(item.event_date_start, "2026-06-06");
});

test("ordinary this-week event titles are not treated as overview rows", () => {
  const item = compactItem(baseItem({
    id: "normal-this-week-event",
    title: "本周五 Techno Worlds",
    title_display: "本周五 Techno Worlds",
    source_article: { title: "本周五 Techno Worlds 开票" },
    event_date_start: "2026-06-05",
    lineup_artists: ["Hadone"],
  }));

  assert.equal(item.isSourceOverview, false);
  assert.equal(item.displayTitle, "Techno Worlds");
  assert.equal(item.dateLabel, "2026-06-05");
  assert.deepEqual(item.lineupItems, ["Hadone"]);
  assert.equal(item.hasLineup, true);
});

test("compact item reads event_date_start and event_date_end when legacy date fields are blank", () => {
  const item = compactItem(baseItem({
    id: "actual-date-fields",
    date: "",
    act_date: "",
    start_date: "",
    event_date_start: "2026-06-04",
    event_date_end: "2026-06-06",
  }));

  assert.equal(item.dateLabel, "2026-06-04");
  assert.equal(item.dateRangeLabel, "2026-06-04 - 2026-06-06");
  assert.equal(item.dateRangeCompact, "06.04-06.06");
});

test("dedupe keeps non-empty fields from the lower-score duplicate", () => {
  const first = compactItem(baseItem({
    id: "dup-a",
    title: "Dedupe Night",
    address: "上海市黄浦区长乐路462号M101",
    source_action: { url_hash: "src:keep", available: true },
    source_article: { url_hash: "src:keep", title: "Source title" },
  }));
  const second = compactItem(baseItem({
    id: "dup-b",
    title: "Dedupe Night",
    address: "",
    event_time_text: "22:00 - Late",
    event_time_source: "source_text",
    source_action: { url_hash: "", available: true },
    source_article: { url_hash: "", title: "" },
  }));

  const deduped = dedupeItems([first, second]);
  assert.equal(deduped.length, 1);
  assert.equal(deduped[0].id, "dup-b");
  assert.equal(deduped[0].timeLabel, "22:00 - Late");
  assert.equal(deduped[0].addressLabel, "上海市黄浦区长乐路462号M101");
  assert.equal(deduped[0].sourceHash, "src:keep");
});

test("dedupe unions secondary city aliases from duplicate tour records", () => {
  const first = compactItem(baseItem({
    id: "tour-city-a",
    title: "Three City Techno Tour",
    city_key: "shanghai",
    city_keys: ["shanghai", "beijing"],
    city: ["上海", "北京"],
  }));
  const second = compactItem(baseItem({
    id: "tour-city-b",
    title: "Three City Techno Tour",
    city_key: "shanghai",
    city_keys: ["shanghai", "guangzhou"],
    city: ["上海", "广州"],
    event_time_text: "22:00 - Late",
    event_time_source: "source_text",
  }));

  const deduped = dedupeItems([first, second]);
  assert.equal(deduped.length, 1);
  assert.deepEqual([...deduped[0].city_keys].sort(), ["beijing", "guangzhou", "shanghai"]);
  assert.deepEqual([...deduped[0].city].sort(), ["上海", "北京", "广州"].sort());
});

test("atlas event adapter emits the same canonical source fields as weekly items", () => {
  const item = atlasEventToWeeklyItem({
    eventId: "event:heim",
    title: "Heim Club Night",
    date: "2026-05-09",
    djName: "DJ A",
    sourceRefId: "src:heim",
    sourceHash: "hash-heim",
    sourceTitle: "今晚|Heim Club Night",
    sourceAccountName: "Heim Shanghai",
    sourcePublishedAt: "2026-05-09",
  }, { venueName: "Heim Shanghai" });

  assert.equal(item.sourceHash, "hash-heim");
  assert.equal(item.sourceRefId, "src:heim");
  assert.equal(item.source_article.url_hash, "hash-heim");
  assert.equal(sourceHashOf(item), "src:heim");
  assert.equal(item.source_article.title, "今晚|Heim Club Night");
  assert.equal(item.lineupLabel, "DJ A");
});

test("atlas activity sidecar source refs take precedence over opaque source hashes", () => {
  const item = atlasEventToWeeklyItem({
    eventId: "activity_event:pools",
    title: "POOLS archive night",
    date: "2026-05-24",
    djName: "DJ Ozone",
    sourceRefId: "activity_src:pools",
    sourceHash: "opaque-source-hash",
    sourceTitle: "POOLS source title",
    sourceAccountName: "POOLS",
    sourcePublishedAt: "2026-05-21",
  }, { venueName: "POOLS" });

  assert.equal(item.sourceHash, "opaque-source-hash");
  assert.equal(item.sourceRefId, "activity_src:pools");
  assert.equal(sourceHashOf(item), "activity_src:pools");
});

test("atlas source_ref ids take precedence over opaque source hashes", () => {
  const item = atlasEventToWeeklyItem({
    eventId: "activity_event:pools",
    venueName: "POOLS",
    date: "2026-05-24",
    djName: "DJ Ozone",
    sourceRefId: "source_ref:pools",
    sourceHash: "opaque-source-hash",
    sourceTitle: "POOLS source title",
  });

  assert.equal(item.sourceHash, "opaque-source-hash");
  assert.equal(item.sourceRefId, "source_ref:pools");
  assert.equal(sourceHashOf(item), "source_ref:pools");
});

test("mergeNonEmpty ignores empty overlay fields but accepts explicit booleans", () => {
  assert.deepEqual(
    mergeNonEmpty(
      { title: "Original", source_action: { url_hash: "src:keep", available: true } },
      { title: "", source_action: { url_hash: "", available: false } },
    ),
    { title: "Original", source_action: { url_hash: "src:keep", available: false } },
  );
});

test("compact item exposes trusted GCJ-02 destination coordinates for wx.openLocation", () => {
  const item = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    geo_lat: "31.2304",
    geo_lng: "121.4737",
    geo_source: "amap_geocoder_crosscheck",
  }));

  assert.equal(item.hasMapLocation, true);
  assert.deepEqual(item.mapLocation, {
    latitude: 31.2304,
    longitude: 121.4737,
    name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
  });
});

test("localized item translates city date and ticket copy without mutating map destination", () => {
  const item = compactItem(baseItem({
    city: ["长春"],
    city_key: "changchun",
    price: ["免票", "预售 80元"],
    geo_lat: 43.8868,
    geo_lng: 125.3245,
    geo_coord_system: "GCJ-02",
    geo_source: "amap_geocoder_crosscheck",
    address: "吉林省长春市朝阳区测试路1号",
    venue_name: "敲敲电子俱乐部 KNOCK&KNOCKCLUB",
  }));
  const en = localizeItem(item, "en");
  const zh = localizeItem(en, "zh");

  assert.equal(en.cityLabel, "Changchun");
  assert.equal(en.detailMetaLine, "Changchun · 2026-05-14");
  assert.equal(en.weekdayLabel, "Thu");
  assert.deepEqual(en.price, ["Presale 80 RMB", "Free Entry"]);
  assert.equal(en.mapLocation.name, "敲敲电子俱乐部 KNOCK&KNOCKCLUB");
  assert.equal(zh.cityLabel, "长春");
  assert.deepEqual(zh.price, ["预售 80元", "免票"]);
});

test("calendar preview overview titles hide derived date range fields", () => {
  const item = compactItem(baseItem({
    id: "oil-june-preview",
    title: "OIL 6月活动一览",
    event_date_start: "2026-06-01",
    event_date_end: "2026-06-07",
    event_date_iso_guesses: ["2026-06-01", "2026-06-07"],
    quality_flags: ["calendar_preview"],
  }));
  const en = localizeItem(item, "en");

  assert.equal(compactDateRange("2026-06-01", "2026-06-07"), "06.01-06.07");
  assert.equal(item.isSourceOverview, true);
  assert.equal(item.displayTitle, "OIL 6月活动一览");
  assert.equal(item.dateRangeCompact, "");
  assert.equal(item.weekdayLabel, "");
  assert.equal(item.isCalendarPreview, true);
  assert.equal(item.calendarPreviewLabel, "活动一览");
  assert.equal(en.calendarPreviewLabel, "Preview");
  assert.equal(en.detailMetaLine, "");
});

test("global i18n helpers translate cities dates and free-entry phrases", () => {
  assert.equal(translateCity("上海", "en", "shanghai"), "Shanghai");
  assert.equal(translateCity("changchun", "zh", "changchun"), "长春");
  assert.equal(translateCity("乌鲁木齐", "en", "urumqi"), "Urumqi");
  assert.equal(dateDisplay("2026-05-26", "zh"), "周二 05.26");
  assert.equal(dateDisplay("2026-05-26", "en"), "Tue 05.26");
  assert.equal(priceText("3am 后免费入场", "en"), "Free entry after 3am");
});

test("compact item supports explicit GCJ-02 aliases and rejects ambiguous latitude fields", () => {
  const alias = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    gcj02_lat: "31.2304",
    gcj02_lng: "121.4737",
    geo_source: "amap_geocoder_crosscheck",
  }));
  const ambiguous = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    latitude: "31.2304",
    longitude: "121.4737",
  }));
  const explicit = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    latitude: "31.2304",
    longitude: "121.4737",
    geo_coord_system: "GCJ-02",
    geo_source: "amap_geocoder_crosscheck",
  }));

  assert.equal(alias.hasMapLocation, true);
  assert.deepEqual(alias.mapLocation, {
    latitude: 31.2304,
    longitude: 121.4737,
    name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
  });
  assert.equal(ambiguous.hasMapLocation, false);
  assert.equal(ambiguous.mapLocation, null);
  assert.equal(explicit.hasMapLocation, true);
});

test("compact item recovers verified map destination when offline snapshot drops coordinates", () => {
  const item = compactItem(baseItem({
    city: ["上海"],
    city_key: "shanghai",
    venue_name: "wigwam",
    venue: ["wigwam"],
    address: "上海市长宁区昭化路658号海粟文化广场LG1-02室",
    geo_lat: null,
    geo_lng: null,
  }));

  assert.equal(item.hasMapLocation, true);
  assert.deepEqual(item.mapLocation, {
    latitude: 31.210481,
    longitude: 121.419529,
    name: "wigwam",
    address: "上海市长宁区昭化路658号海粟文化广场LG1-02室",
  });
});

test("compact item recovers verified map destination for known club address aliases", () => {
  const item = compactItem(baseItem({
    city: ["西安"],
    city_key: "xian",
    venue_name: "JAR这儿",
    venue: ["JAR这儿"],
    address: "陕西省西安市碑林区粉巷18号粉巷公园负一层F-1-3",
    geo_lat: null,
    geo_lng: null,
  }));

  assert.equal(item.hasMapLocation, true);
  assert.deepEqual(item.mapLocation, {
    latitude: 34.255282,
    longitude: 108.945916,
    name: "JAR这儿",
    address: "陕西省西安市碑林区粉巷18号粉巷公园负一层F-1-3",
  });
});

test("compact item recovers Beijing Nanyingfang map aliases used by weekly cards", () => {
  const compact = (address) => compactItem(baseItem({
    city: ["北京"],
    city_key: "beijing",
    venue_name: "南营坊胡同日坛国际贸易中心",
    venue: ["南营坊胡同日坛国际贸易中心"],
    address,
    geo_lat: null,
    geo_lng: null,
  }));
  const exact = compact("北京朝阳区南营坊胡同日坛国际贸易中心A座北门B1");
  const verifiedAddressVariant = compact("北京市朝阳区南营房胡同日坛国际贸易中心A座北门B1层");

  assert.equal(exact.hasMapLocation, true);
  assert.deepEqual(exact.mapLocation, {
    latitude: 39.920181,
    longitude: 116.441876,
    name: "南营坊胡同日坛国际贸易中心",
    address: "北京朝阳区南营坊胡同日坛国际贸易中心A座北门B1",
  });
  assert.equal(verifiedAddressVariant.hasMapLocation, true);
  assert.equal(verifiedAddressVariant.mapLocation.latitude, 39.920181);
  assert.equal(verifiedAddressVariant.mapLocation.longitude, 116.441876);
});

test("active weekly venue registry entries all recover map destinations", () => {
  const seedPath = path.resolve(__dirname, "..", "..", "..", "tools", "stage7_rewrite", "registries", "weekly_venues_seed.json");
  const seed = JSON.parse(fs.readFileSync(seedPath, "utf8"));
  const missing = [];

  for (const venue of seed.venues.filter((item) => item.status === "active")) {
    const item = compactItem(baseItem({
      id: `registry:${venue.venue_id}`,
      city: [venue.city_name],
      city_key: venue.city_key,
      venue_name: venue.canonical_name,
      venue: [venue.canonical_name, ...(venue.aliases || [])],
      address: venue.address_full,
      address_full: venue.address_full,
      geo_lat: null,
      geo_lng: null,
    }));
    if (!item.hasMapLocation) missing.push(`${venue.city_name}|${venue.canonical_name}|${venue.address_full}`);
  }

  assert.deepEqual(missing, []);
});

test("compact item accepts backend geo_coordinate_system and GCJ latitude aliases", () => {
  const coordinateSystemAlias = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    geo_lat: "31.2304",
    geo_lng: "121.4737",
    geo_coordinate_system: "GCJ02",
    geo_source: "amap_geocoder_crosscheck",
  }));
  const coordinateFieldAlias = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    latitude_gcj02: "31.2304",
    longitude_gcj02: "121.4737",
    geo_source: "amap_geocoder_crosscheck",
  }));

  assert.equal(coordinateSystemAlias.hasMapLocation, true);
  assert.equal(coordinateFieldAlias.hasMapLocation, true);
});

test("compact item accepts exact map coordinate shapes from Tencent style fields", () => {
  const stringLatLng = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    tencent_location: "31.210481,121.419529",
    geo_source: "tencent_place_search_crosscheck",
  }));
  const stringLngLat = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    map_location: "121.419529,31.210481",
    geo_source: "tencent_place_search_crosscheck",
  }));
  const nestedPoint = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    geo_lat: "31.000001",
    geo_lng: "",
    geo_source: "tencent_place_search_crosscheck",
    tencentLocation: {
      point: "31.210481,121.419529",
      coordinate_type: "gcj02",
    },
  }));
  const lngLatArray = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    coordinates: [121.419529, 31.210481],
    geo_source: "tencent_place_search_crosscheck",
  }));

  assert.equal(stringLatLng.hasMapLocation, true);
  assert.deepEqual(stringLatLng.mapLocation, {
    latitude: 31.210481,
    longitude: 121.419529,
    name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
  });
  assert.deepEqual(stringLngLat.mapLocation, stringLatLng.mapLocation);
  assert.deepEqual(nestedPoint.mapLocation, stringLatLng.mapLocation);
  assert.deepEqual(lngLatArray.mapLocation, stringLatLng.mapLocation);
});

test("compact item does not expose map action for incomplete or invalid coordinates", () => {
  const unknownVenue = {
    venue_name: "未知测试俱乐部",
    venue: ["未知测试俱乐部"],
    account: "",
    promoter: "",
  };
  const missingLng = compactItem(baseItem({
    ...unknownVenue,
    address: "上海市黄浦区测试路1号",
    geo_lat: "31.2304",
    geo_lng: "",
  }));
  const outOfRange = compactItem(baseItem({
    ...unknownVenue,
    address: "上海市黄浦区测试路1号",
    geo_lat: "131.2304",
    geo_lng: "121.4737",
  }));
  const wrongSystem = compactItem(baseItem({
    ...unknownVenue,
    address: "上海市黄浦区测试路1号",
    geo_lat: "31.2304",
    geo_lng: "121.4737",
    geo_coord_system: "WGS84",
  }));

  assert.equal(missingLng.hasMapLocation, false);
  assert.equal(missingLng.mapLocation, null);
  assert.equal(outOfRange.hasMapLocation, false);
  assert.equal(outOfRange.mapLocation, null);
  assert.equal(wrongSystem.hasMapLocation, false);
  assert.equal(wrongSystem.mapLocation, null);
});

test("compact item requires taxi-grade coordinate evidence before exposing map action", () => {
  const noSource = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    geo_lat: "31.2304",
    geo_lng: "121.4737",
    geo_coord_system: "GCJ-02",
  }));
  const noAddress = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "",
    geo_lat: "31.2304",
    geo_lng: "121.4737",
    geo_coord_system: "GCJ-02",
    geo_source: "amap_place_search_crosscheck",
  }));
  const trusted = compactItem(baseItem({
    venue_name: "测试俱乐部",
    address: "上海市黄浦区测试路1号",
    geo_lat: "31.2304",
    geo_lng: "121.4737",
    geo_coord_system: "GCJ-02",
    geo_source: "amap_place_search_crosscheck",
  }));

  assert.equal(noSource.hasMapLocation, false);
  assert.equal(noSource.mapLocation, null);
  assert.equal(noAddress.hasMapLocation, false);
  assert.equal(noAddress.mapLocation, null);
  assert.equal(trusted.hasMapLocation, true);
});

test("compact item exposes source-backed sound system fields without inference", () => {
  const item = compactItem(baseItem({
    sound_system: ["Funktion-One"],
    sound_system_evidence: ["本场使用 Funktion-One 音响系统"],
  }));
  const generic = compactItem(baseItem({
    evidence: ["音响效果很棒"],
  }));

  assert.deepEqual(item.soundSystemItems, ["Funktion-One"]);
  assert.equal(item.soundSystemLabel, "Funktion-One");
  assert.equal(item.hasSoundSystem, true);
  assert.equal(item.soundSystemEvidence[0], "本场使用 Funktion-One 音响系统");
  assert.equal(generic.hasSoundSystem, false);
});

test("music styles only come from explicit style fields", () => {
  const guessed = compactItem(baseItem({
    title: "Techno tonight at warehouse",
    music_styles: [],
    style_tags: [],
    genres: [],
  }));
  const explicit = compactItem(baseItem({
    title: "No style in title",
    genres: ["techno / house / ambient"],
  }));

  assert.deepEqual(guessed.musicStyles, []);
  assert.equal(guessed.hasStyle, false);
  assert.deepEqual(explicit.musicStyles, ["techno", "house", "ambient"]);
});

test("near duplicate events collapse when date city venue and poster match", () => {
  const first = compactItem(baseItem({
    id: "illum-a",
    title: "Sat.｜1日限定！各位主人欢迎来到干瞪眼DokiDoki Bass Club Vol.2",
    venue_name: "ILLUM Shanghai",
    venue: ["ILLUM Shanghai"],
    cover_image_url: "https://example.test/poster.jpg",
  }));
  const second = compactItem(baseItem({
    id: "illum-b",
    title: "女仆咖啡厅1日限定！各位主人欢迎来到干瞪眼DokiDoki Bass Club Vol 2",
    venue_name: "ILLUM Shanghai",
    venue: ["ILLUM Shanghai"],
    cover_image_url: "https://example.test/poster.jpg?x=1",
    address: "上海市黄浦区测试路1号",
  }));

  assert.equal(areLikelyDuplicateItems(first, second), true);
  const deduped = dedupeItems([first, second]);
  assert.equal(deduped.length, 1);
  assert.equal(deduped[0].id, "illum-b");
});

test("generic same-venue titles do not collapse unrelated events", () => {
  const first = compactItem(baseItem({
    id: "nuts-a",
    title: "李飘飘2026“飘流记”全国巡演｜5月16日@坚果NUTS",
    venue_name: "坚果NUTS",
    venue: ["坚果NUTS"],
  }));
  const second = compactItem(baseItem({
    id: "nuts-b",
    title: "5月16日@坚果NUTS",
    venue_name: "坚果NUTS",
    venue: ["坚果NUTS"],
  }));

  assert.equal(areLikelyDuplicateItems(first, second), false);
  assert.equal(dedupeItems([first, second]).length, 2);
});

test("visible description and bio lines never expose source image urls", () => {
  const item = compactItem(baseItem({
    title: "Attention at INS",
    description_original_lines: [
      "https://mmbiz.qpic.cn/mmbiz_png/example/wx_fmt=png&from=appmsg",
      "一场高速、冷酷、直接的周末夜。",
    ],
    dj_bio_lines: [
      "http://mmbiz.qpic.cn/mmbiz_png/example/wx_fmt=png",
      "来自本地俱乐部场景的制作人。",
    ],
  }));

  assert.equal(isDisplayUrlLine("https://mmbiz.qpic.cn/mmbiz_png/example/wx_fmt=png"), true);
  assert.deepEqual(item.descriptionLines, ["一场高速、冷酷、直接的周末夜。"]);
  assert.deepEqual(item.bioLines, ["来自本地俱乐部场景的制作人。"]);
  assert.equal(item.descriptionLead.includes("mmbiz.qpic.cn"), false);
});

test("compact item exposes safe DJ discovery sections for detail pages", () => {
  const item = compactItem(baseItem({
    title: "Club Night with DINA",
    dj_discovery_sections: [
      {
        name: "DINA",
        name_key: "dina",
        bio_atoms: [
          { text: "DINA is a DJ and producer from Berlin.", source_ref: "source:dina", verbatim_source: true },
          { text: "来源线索: Resident Advisor profile", source_ref: "generated" },
          { text: "No source ref should be hidden." },
        ],
        links: [
          {
            item_id: "dina-soundcloud",
            entity_search_id: "dj:dina",
            entity_name: "DINA",
            entity_type: "artist",
            platform: "soundcloud",
            public_category: "mixtape_music",
            display_label: "SoundCloud",
            url: "https://soundcloud.com/dina/example-mix",
            source_ref: "seed:dina",
            confidence_score: 96,
            confidence_band: "high",
            miniapp_display_allowed_candidate: true,
            block_reasons: [],
          },
          {
            item_id: "dina-ra",
            entity_search_id: "dj:dina",
            entity_name: "DINA",
            entity_type: "artist",
            platform: "resident_advisor",
            public_category: "public_profile",
            display_label: "Resident Advisor",
            url: "https://ra.co/dj/dina",
            source_ref: "seed:dina",
            confidence_score: 94,
            confidence_band: "high",
            miniapp_display_allowed_candidate: true,
            block_reasons: [],
          },
          {
            item_id: "dina-raw-mp3",
            entity_search_id: "dj:dina",
            entity_name: "DINA",
            entity_type: "artist",
            platform: "external",
            public_category: "mixtape_music",
            display_label: "Raw MP3",
            url: "https://media.example.com/dina/raw-set.mp3",
            source_ref: "search:dina",
            confidence_score: 99,
            confidence_band: "high",
            miniapp_display_allowed_candidate: true,
            block_reasons: [],
          },
        ],
      },
    ],
  }));

  assert.equal(item.hasDjDiscovery, true);
  assert.equal(item.djDiscoverySections.length, 1);
  assert.equal(item.djDiscoverySections[0].name, "DINA");
  assert.equal(item.djDiscoverySections[0].bioAtoms.length, 1);
  assert.equal(item.djDiscoverySections[0].bioAtoms[0].text, "DINA is a DJ and producer from Berlin.");
  assert.deepEqual(
    item.djDiscoverySections[0].links.map((link) => link.displayLabel),
    ["SoundCloud", "Resident Advisor"],
  );
  assert.equal(item.djDiscoverySections[0].links.some((link) => link.url.endsWith(".mp3")), false);
  assert.equal(item.djDiscoverySections[0].links[0].action.mode, "copy_original_link");
  assert.equal(item.djDiscoverySections[0].links[0].action.mediaDownloaded, false);
});

test("source overview articles never expose DJ discovery sections", () => {
  const item = compactItem(baseItem({
    title: "loopy 六月活动一览",
    article_title: "loopy 六月活动一览",
    is_source_overview: true,
    dj_discovery_sections: [
      {
        name: "DINA",
        links: [
          {
            item_id: "dina-soundcloud",
            entity_search_id: "dj:dina",
            entity_name: "DINA",
            entity_type: "artist",
            platform: "soundcloud",
            public_category: "mixtape_music",
            display_label: "SoundCloud",
            url: "https://soundcloud.com/dina/example-mix",
            source_ref: "seed:dina",
            confidence_score: 96,
            confidence_band: "high",
            miniapp_display_allowed_candidate: true,
            block_reasons: [],
          },
        ],
      },
    ],
  }));

  assert.equal(item.isSourceOverview, true);
  assert.equal(item.hasDjDiscovery, false);
  assert.deepEqual(item.djDiscoverySections, []);
});

test("atlas artist items expose verified ids but only hint ambiguous candidates", () => {
  const item = compactItem(baseItem({
    weeklyAtlas: {
      lineupResolved: [
        {
          raw: "DJ A",
          artistId: "atlas:entity:one",
          canonicalName: "DJ A",
          matchMethod: "alias_exact",
          matchScore: 1,
          displayTier: "show",
          candidates: [],
        },
        {
          raw: "KeiKo",
          artistId: null,
          canonicalName: null,
          matchMethod: "fuzzy_multiple",
          matchScore: 1,
          displayTier: "show_with_hint",
          candidates: [
            { canonicalName: "KEIKO", score: 1 },
            { canonicalName: "KeiKo 惠子", score: 1 },
          ],
        },
      ],
    },
  }));

  assert.equal(item.hasAtlasArtistItems, true);
  assert.equal(item.atlasArtistItems[0].artistId, "atlas:entity:one");
  assert.equal(item.atlasArtistItems[0].isVerified, true);
  assert.equal(item.atlasArtistItems[1].artistId, "");
  assert.equal(item.atlasArtistItems[1].isHint, true);
  assert.equal(item.atlasArtistItems[1].hintLabel, "KEIKO / KeiKo 惠子");
});
