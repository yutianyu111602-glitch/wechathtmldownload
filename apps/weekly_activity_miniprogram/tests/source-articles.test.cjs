const assert = require("node:assert/strict");
const test = require("node:test");

const { buildDetailSourceArticles, buildVenueSourceArticles, sourceHashOf } = require("../utils/sourceArticles");

test("venue home does not surface aggregate parent overview articles for child events", () => {
  const articles = buildVenueSourceArticles([
    {
      id: "agg-child-a",
      account: "loopy Club",
      sourceHash: "parent-hash",
      source_published_at: "2026-04-29",
      event_date_start: "2026-05-28",
    },
    {
      id: "agg-child-b",
      account: "loopy Club",
      sourceHash: "parent-hash",
      source_published_at: "2026-04-29",
      event_date_start: "2026-05-29",
    },
  ]);

  assert.deepEqual(articles, []);
});

test("single non-aggregate event does not create a venue source article block", () => {
  const articles = buildVenueSourceArticles([
    {
      id: "single-event",
      account: "EXIT Shanghai",
      sourceHash: "single-hash",
      event_date_start: "2026-05-22",
    },
  ]);

  assert.equal(articles.length, 0);
});

test("detail surfaces every merged source once without duplicating the retained article", () => {
  const articles = buildDetailSourceArticles({
    id: "exit:new",
    account: "EXIT Shanghai",
    sourceHash: "newhash",
    source_article: {
      url_hash: "newhash",
      account_name: "EXIT Shanghai",
      published_at: "2026-05-21",
    },
    merge_provenance: {
      schema_version: "weekly_merge_provenance.v1",
      retained_source_hash: "newhash",
      source_count: 2,
      sources: [
        {
          source_hash: "oldhash",
          title: "旧推文同场预告",
          account_name: "EXIT Shanghai",
          published_at: "2026-05-20",
        },
        {
          source_hash: "newhash",
          title: "新推文同场预告",
          account_name: "EXIT Shanghai",
          published_at: "2026-05-21",
        },
        {
          source_hash: "oldhash",
          title: "旧推文同场预告",
          account_name: "EXIT Shanghai",
          published_at: "2026-05-20",
        },
      ],
    },
  });

  assert.deepEqual(articles.map((article) => article.hash), ["newhash", "oldhash"]);
  assert.equal(articles[0].isPrimary, true);
  assert.equal(articles[1].isPrimary, false);
  assert.match(articles[1].title, /旧推文同场预告/);
});

test("venue source block includes merged source provenance even for one retained event card", () => {
  const articles = buildVenueSourceArticles([
    {
      id: "exit:new",
      account: "EXIT Shanghai",
      sourceHash: "newhash",
      event_date_start: "2026-05-22",
      merge_provenance: {
        schema_version: "weekly_merge_provenance.v1",
        retained_source_hash: "newhash",
        source_count: 2,
        sources: [
          { source_hash: "newhash", account_name: "EXIT Shanghai", title: "新推文", published_at: "2026-05-21" },
          { source_hash: "oldhash", account_name: "EXIT Shanghai", title: "旧推文", published_at: "2026-05-20" },
        ],
      },
    },
  ]);

  assert.deepEqual(articles.map((article) => article.hash), ["newhash", "oldhash"]);
  assert.ok(articles.every((article) => article.eventCount === 1));
  assert.ok(articles.every((article) => article.isMergedSource));
});

test("merged source provenance skips aggregate child parent overview refs", () => {
  const articles = buildDetailSourceArticles({
    id: "loopy:retained",
    account: "loopy Club",
    sourceHash: "detail-hash",
    source_article: {
      url_hash: "detail-hash",
      account_name: "loopy Club",
      published_at: "2026-06-02",
    },
    merge_provenance: {
      schema_version: "weekly_merge_provenance.v1",
      retained_source_hash: "detail-hash",
      source_count: 2,
      sources: [
        {
          event_id: "agg-child-loopy-overview",
          source_hash: "overview-hash",
          title: "本周活动一览",
          account_name: "loopy Club",
          published_at: "2026-06-01",
        },
        {
          event_id: "loopy:retained",
          source_hash: "detail-hash",
          title: "具体活动原文",
          account_name: "loopy Club",
          published_at: "2026-06-02",
        },
      ],
    },
  });

  assert.deepEqual(articles.map((article) => article.hash), []);
});

test("disabled aggregate child source action does not surface parent article links", () => {
  const item = {
    id: "agg-child-loopy-overview",
    account: "loopy Club",
    sourceHash: "parent-hash",
    source_article: { url_hash: "parent-hash", title: "本周活动一览" },
    source_action: { available: false, url_hash: "" },
    merge_provenance: {
      schema_version: "weekly_merge_provenance.v1",
      retained_source_hash: "parent-hash",
      sources: [
        { source_hash: "parent-hash", title: "本周活动一览" },
      ],
    },
  };

  assert.equal(sourceHashOf(item), "");
  assert.deepEqual(buildDetailSourceArticles(item), []);
  assert.deepEqual(buildVenueSourceArticles([item], { includeSingles: true }), []);
});
