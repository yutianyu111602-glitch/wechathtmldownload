const assert = require("node:assert/strict");

const {
  areLikelyDuplicateItems,
  compactItem,
  dedupeItems,
  dedupeKeyForItem,
  isDisplayUrlLine,
} = require("../utils/format");

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
