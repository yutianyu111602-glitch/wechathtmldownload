const assert = require("node:assert/strict");
const test = require("node:test");

const { buildPosterPool, posterVisualKey } = require("../utils/posterPool");

function item(id, overrides = {}) {
  return {
    id,
    displayTitle: `Event ${id}`,
    title: `Event ${id}`,
    coverUrl: `https://example.test/${id}.jpg`,
    dateLabel: "2026-05-20",
    dateCompact: "05.20",
    weekdayLabel: "Wed",
    cardLocationLabel: "Shanghai",
    hasStyle: true,
    styleLabel: "Techno",
    hasLineup: false,
    hasDescription: true,
    hasAddress: true,
    post_date: "2026-05-18",
    ...overrides,
  };
}

test("poster pool stays inside the visible filter scope supplied by the page", () => {
  const visible = Array.from({ length: 8 }, (_, index) => item(`shanghai-${index + 1}`, { city_key: "shanghai" }));
  const pool = buildPosterPool(visible, visible, "all");

  assert.equal(pool.length, 24);
  assert.ok(pool.every((entry) => entry.id.startsWith("shanghai-")));
  assert.ok(pool.every((entry) => entry.cityKey === "shanghai"));
  assert.ok(pool.every((entry) => entry.posterKey.includes("::poster::")));
});

test("poster pool loops a tiny source to keep horizontal swipe useful", () => {
  const pool = buildPosterPool([item("only-one")], [], "all", { minItems: 6, maxItems: 12 });

  assert.equal(pool.length, 6);
  assert.deepEqual([...new Set(pool.map((entry) => entry.id))], ["only-one"]);
  assert.equal(new Set(pool.map((entry) => entry.posterKey)).size, 6);
});

test("poster pool prefers poster-backed items before fallback cards", () => {
  const pool = buildPosterPool(
    [item("fallback", { coverUrl: "" })],
    [item("poster")],
    "all",
    { minItems: 2, maxItems: 4 },
  );

  assert.equal(pool[0].id, "poster");
  assert.equal(pool[1].id, "fallback");
});

test("poster pool excludes suppressed aggregate overview posters", () => {
  const pool = buildPosterPool(
    [
      item("agg-child-overview", {
        poster_suppressed: true,
        coverUrl: "cloud://atlas-prod.6174-atlas-prod-1250000000/weekly-posters/20260605/overview.jpg",
      }),
      item("main"),
    ],
    [],
    "all",
    { minItems: 1, maxItems: 6 },
  );

  assert.deepEqual(pool.map((entry) => entry.id), ["main"]);
});

test("poster pool preserves source overview projection guard", () => {
  const pool = buildPosterPool(
    [
      item("overview", {
        displayTitle: "loopy 六月活动一览",
        isSourceOverview: true,
        isCalendarPreview: true,
        calendarPreviewLabel: "活动一览",
        weekdayLabel: "",
        dateRangeCompact: "",
        dateCompact: "",
        cardLocationLabel: "",
        hasStyle: false,
        styleLabel: "",
      }),
    ],
    [],
    "all",
    { minItems: 1, maxItems: 2 },
  );

  assert.equal(pool[0].displayTitle, "loopy 六月活动一览");
  assert.equal(pool[0].isSourceOverview, true);
  assert.equal(pool[0].isCalendarPreview, true);
  assert.equal(pool[0].dateRangeCompact, "");
  assert.equal(pool[0].dateCompact, "");
  assert.equal(pool[0].cardLocationLabel, "");
  assert.equal(pool[0].hasStyle, false);
});

test("poster pool dedupes aggregate children that share the same raw poster", () => {
  const first = item("agg-a", {
    coverUrl: "https://service.test/api/v1/weekly/poster/agg-a",
    cover_image_url: "https://mmbiz.qpic.cn/mmbiz_png/source-poster?wx_fmt=png",
  });
  const second = item("agg-b", {
    coverUrl: "https://service.test/api/v1/weekly/poster/agg-b",
    cover_image_url: "https://mmbiz.qpic.cn/mmbiz_png/source-poster?wx_fmt=png&from=appmsg",
  });
  const pool = buildPosterPool(
    [first, second],
    [],
    "all",
    { minItems: 1, maxItems: 6 },
  );

  assert.equal(posterVisualKey(first), posterVisualKey(second));
  assert.equal(pool.length, 1);
  assert.equal(pool[0].id, "agg-a");
});

test("poster pool prefers information-rich main poster over qr or ticketing artwork", () => {
  const mainPoster = item("main", {
    hasLineup: true,
    lineupItems: ["DJ A", "DJ B", "DJ C", "DJ D"],
    price: ["预售 80", "现场 100"],
    descriptionLines: ["club night", "lineup and venue details"],
    sourceHash: "source-main",
    poster_ocr_text: "05.30 Club A DJ A DJ B DJ C 22:00 预售 80",
  });
  const qrArtwork = item("qr", {
    hasLineup: false,
    lineupItems: [],
    descriptionLines: [],
    sourceHash: "",
    poster_ocr_text: "扫码购票 二维码 小程序码 付款",
  });

  const pool = buildPosterPool([qrArtwork, mainPoster], [], "all", { minItems: 2, maxItems: 2 });

  assert.equal(pool[0].id, "main");
});
