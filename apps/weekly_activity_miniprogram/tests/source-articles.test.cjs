const assert = require("node:assert/strict");
const test = require("node:test");

const { buildDetailSourceArticles, buildVenueSourceArticles } = require("../utils/sourceArticles");

test("venue home surfaces aggregate parent article once for several child events", () => {
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

  assert.equal(articles.length, 1);
  assert.equal(articles[0].hash, "parent-hash");
  assert.equal(articles[0].title, "loopy Club 排期原文");
  assert.match(articles[0].subtitle, /发布 04\.29/);
  assert.match(articles[0].subtitle, /2场/);
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
