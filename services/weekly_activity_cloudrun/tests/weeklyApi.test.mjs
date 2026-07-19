import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "../src/server.mjs";
import { storageSlug, WeeklyActivityDataStore } from "../src/dataStore.mjs";

let server;
let baseUrl;
let testEnv;
let fixturePaths;

test("storage slug matches the package writer for whitespace and unicode IDs", () => {
  assert.equal(
    storageSlug("陀地音乐TOTE MUSIC:d78318b809090dd4:schedule:20260718:21"),
    "u9640u5730u97f3u4e50tote-musicu3ad78318b809090dd4u3ascheduleu3a20260718u3a21",
  );
});

async function writeJson(filePath, value) {
  await writeFile(filePath, JSON.stringify(value, null, 2), "utf8");
}

async function createFixture() {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-api-"));
  const sourceMapDir = path.join(dir, "..", "source_actions");
  const stage7Dir = path.join(dir, "..", "stage7");
  await mkdir(path.join(dir, "by-id"), { recursive: true });
  await mkdir(path.join(dir, "llm", "enrichments"), { recursive: true });
  await mkdir(sourceMapDir, { recursive: true });
  await mkdir(stage7Dir, { recursive: true });
  await writeJson(path.join(dir, "manifest.json"), {
    schema_version: "weekly_activity_miniprogram_api.v1",
    generated_at: "2026-05-07T09:48:35",
    item_count: 3,
    window_start: "2026-05-07",
    window_end: "2026-05-21",
    source_mode: "sanji_desktop_rss",
    source_queue_path: "C:\\Users\\pc\\local-only\\latest_queue.jsonl",
    direct_rss_feed_fetch: false,
    sanji_db_snapshot_export: true,
    sanji_desktop_refresh_invoked: true,
    sanji_snapshot_db_path: "C:\\Users\\pc\\AppData\\Roaming\\sanji\\sanji.db",
    sanji_source_contract: {
      schema_version: "weekly_sanji_source_contract.v1",
      source_mode: "sanji_desktop_rss",
      source: "sanji_desktop_local_sqlite_snapshot",
      generated_at: "2026-05-07T09:40:00+08:00",
      exported_rows: 88,
      prefetch_queue_rows: 88,
      direct_rss_feed_fetch: false,
      sanji_db_snapshot_export: true,
      sanji_desktop_refresh_invoked: true,
      snapshot_db_path: "C:\\Users\\pc\\AppData\\Roaming\\sanji\\sanji.db",
    },
    field_resource_repair: {
      schema_version: "weekly_resource_field_repair.v1",
      item_change_count: 2,
    },
    geocode_enrichment: {
      schema_version: "weekly_geocode_enrichment.v1",
      updated_item_count: 2,
    },
    id_consistency_repair: {
      schema_version: "weekly_resource_id_consistency_repair.v1",
      changed_item_count: 2,
    },
  });
  await writeJson(path.join(dir, "club_overviews.json"), {
    schema_version: "club_overviews.v1",
    generated_at: "2026-05-09T08:00:00+08:00",
    as_of_date: "2026-05-09",
    source: "sanji.db (fixture)",
    club_count: 99,
    overview_count: 99,
    kind_counts: { week: 99 },
    by_club: {
      "Club A": [
        {
          record_type: "club_overview_parent",
          parent_aggregate: true,
          include_in_activity_feed: false,
          source_table: "wechat_article",
          club_fakeid: "private-fixture-id",
          club: "Club A",
          title: "Club A 本周活动一览",
          publish_date: "2026-05-09",
          original_url: "https://mp.weixin.qq.com/s/club-a-weekly",
          cover_url: "https://mmbiz.qpic.cn/example/club-a-weekly.jpg",
          window_kind: "week",
          window_label: "5.9-5.15",
          window_start: "2026-05-09",
          window_end: "2026-05-15",
        },
      ],
      "Invalid Club": [{ title: "missing required public URLs" }],
    },
  });
  const items = [
    {
      id: "item-a",
      title: "上海 Club A",
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      event_date_iso_guess: "2026-05-09",
      event_date_iso_guesses: ["2026-05-09"],
      quality_status: "READY",
      promoter: "Club A",
      aggregation_source_kind: "wechat_article",
      dedupe_key: "fixture:item-a",
      discovery_source: "sanji_desktop_rss",
      extraction_model: "qwen-vl-fixture",
      metadata_enriched_at: "2026-05-07T10:00:00+08:00",
      cover_url: "https://mmbiz.qpic.cn/example/item-a.jpg",
      cover_image_url: "https://mmbiz.qpic.cn/example/item-a.jpg",
      source_article: {
        url_hash: "aaaaaaaaaaaaaaaa",
        account_name: "Club A",
        published_at: "2026-05-07",
        url: "https://mp.weixin.qq.com/s/item-a",
        body: "x".repeat(2000),
      },
      source_action: {
        type: "wechat_article",
        label: "公众号",
        available: true,
        url_hash: "aaaaaaaaaaaaaaaa",
        url: "https://mp.weixin.qq.com/s/item-a",
        debug_trace: "x".repeat(2000),
      },
      lineup: ["Club A", "DJ A", "DADA北京"],
      venue: ["Dada Bar Beijing"],
      evidence: ["22:00 开始", "DJ A all night", "4x4 house and club trax"],
      description_original_lines: [
        "Line 1 from public source",
        "Line 2 from public source",
        "Line 3 from public source",
        "Line 4 from public source",
        "Line 5 from public source that should be reserved for detail only",
      ],
      merge_provenance: [{ source: "aggregate-child", note: "x".repeat(2000) }],
      field_evidence_refs: {
        title: [{ ref: "ocr-span", text: "x".repeat(1000) }],
        "/home/private/evidence.json": [{ ref: "must-not-leak" }],
        "C:\\Users\\win\\private\\evidence.json": [{ ref: "must-not-leak" }],
      },
      address_verification: { provider: "fixture", trace: "x".repeat(1000) },
      geo_reverse_address: "fixture reverse address",
      poster_vl_images: [{ path: "C:\\Users\\win\\private\\poster.png" }],
      source_evidence_path: "/home/win/private/source.md",
      emergency_qwen36_lineup_patch: { path: "/srv/huaidj/private.json" },
      poster_selection_evidence: {
        schema_version: "weekly_poster_selection_evidence.vl_direct.v1",
        visible_text_lines: ["DJ A / 22:00", "/mnt/c/private/source.md"],
        source_evidence_path: "/opt/huaidj/private.md",
      },
    },
    {
      id: "item-a-duplicate",
      title: "📌 上海 Club A",
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      event_date_iso_guess: "2026-05-09",
      event_date_iso_guesses: ["2026-05-09"],
      quality_status: "READY",
      promoter: "Club A",
      cover_url: "https://mmbiz.qpic.cn/example/item-a-duplicate.jpg",
      cover_image_url: "https://mmbiz.qpic.cn/example/item-a-duplicate.jpg",
      source_action: {
        type: "wechat_article",
        label: "公众号",
        available: true,
        url_hash: "bbbbbbbbbbbbbbbb",
      },
      lineup: ["Club A", "DJ A"],
      venue: ["Dada Bar Beijing"],
      evidence: ["22:00 开始", "DJ A all night"],
    },
    {
      id: "item-b",
      title: "AURORA @ 莫须有工厂",
      city_key: "beijing",
      city_keys: ["beijing"],
      city: ["北京"],
      event_date_iso_guess: "2026-05-10",
      event_date_iso_guesses: ["2026-05-10"],
      quality_status: "READY",
      promoter: "AURORA BJ",
      lineup: ["AURORA BJ", "AURORA"],
      venue: [],
      evidence: ["来源公众号: AURORA BJ", "NIGHT TOUR / 夜游", "Night Tour 夜游 05.09 @ 莫须有工厂"],
    },
    {
      id: "club:abc123",
      title: "Colon Id Event",
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      event_date_iso_guess: "2026-05-11",
      event_date_iso_guesses: ["2026-05-11"],
      quality_status: "READY",
      promoter: "Club Colon",
      lineup: ["DJ Colon"],
      venue: ["Club Colon"],
      evidence: ["22:00 Club Colon"],
    },
    {
      id: "cocktail-festival",
      title: "重庆首届鸡尾酒节",
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      event_date_iso_guess: "2026-05-09",
      event_date_iso_guesses: ["2026-05-09"],
      quality_status: "READY",
      promoter: "Market",
      lineup: [],
      venue: ["Market"],
      evidence: ["Cocktail Festival"],
    },
    {
      id: "range-week",
      title: "Range Week Event",
      city_key: "beijing",
      city_keys: ["beijing"],
      city: ["北京"],
      event_date_iso_guess: "2026-05-18",
      event_date_iso_guesses: ["2026-05-18", "2026-05-24"],
      event_date_start: "2026-05-18",
      event_date_end: "2026-05-24",
      quality_status: "READY",
      promoter: "Range Club",
      lineup: ["DJ Range"],
      venue: ["Range Club"],
      evidence: ["2026-05-18 - 2026-05-24"],
    },
    {
      id: "item-review",
      title: "Review Only",
      city_key: "shanghai",
      city_keys: ["shanghai"],
      event_date_iso_guess: "2026-05-09",
      event_date_iso_guesses: ["2026-05-09"],
      quality_status: "REVIEW",
    },
  ];
  await writeJson(path.join(dir, "current.json"), {
    schema_version: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-05-07T09:48:35",
    item_count: items.length,
    items,
  });
  await writeJson(path.join(dir, "by-id", "item-a.json"), {
    schema_version: "weekly_activity_miniprogram_detail.v1",
    item: items[0],
  });
  await writeJson(path.join(dir, "by-id", "clubu3aabc123.json"), {
    schema_version: "weekly_activity_miniprogram_detail.v1",
    item: items.find((item) => item.id === "club:abc123"),
  });
  await writeJson(path.join(sourceMapDir, "source_url_map.json"), {
    schema_version: "weekly_activity_source_url_map.v1",
    generated_at: "2026-05-07T09:48:35",
    source_count: 2,
    sources: {
      aaaaaaaaaaaaaaaa: {
        type: "wechat_article",
        url: "https://mp.weixin.qq.com/s/item-a",
        account_name: "Club A",
        published_at: "2026-05-07",
        event_id: "item-a",
      },
      cccccccccccccccc: {
        type: "wechat_article",
        url: "file:///home/win/private/article.html",
        event_id: "item-a",
      },
    },
  });
  await writeJson(path.join(dir, "weekly_entity_snapshot.json"), {
    schema_version: "weekly_atlas_entity.v1",
    generated_at: "2026-05-20T16:47:43Z",
    publish_package: "TEST",
    artist_profiles: [
      {
        artist_id: "atlas:entity:dj-a",
        canonical_name: "DJ A",
        verified: true,
        source: "atlas_alias_export",
      },
    ],
    lineup_resolved: [
      {
        event_id: "item-a",
        raw: "DJ A",
        artist_id: "atlas:entity:dj-a",
        canonical_name: "DJ A",
        match_method: "alias_exact",
        match_score: 1,
        verified: true,
        display_tier: "show",
      },
      {
        event_id: "item-a",
        raw: "KeiKo",
        artist_id: null,
        canonical_name: null,
        match_method: "fuzzy_multiple",
        match_score: 1,
        verified: false,
        display_tier: "show_with_hint",
        candidates: [
          { artist_id: "atlas:entity:hidden-a", canonical_name: "KEIKO", score: 1 },
          { artist_id: "atlas:entity:hidden-b", canonical_name: "KeiKo 惠子", score: 1 },
        ],
      },
    ],
  });
  await writeJson(path.join(dir, "llm", "weekly_summary.json"), {
    schemaVersion: "weekly_activity_api.materialized_summary.v1",
    generatedAt: "2026-05-07T10:00:00",
    provider: "deepseek",
    model: "deepseek-v4-pro",
    thinking: "disabled",
    itemCount: 2,
    summary: {
      highlight_events: [{ title: "上海 Club A", reason_zh: "测试推荐", reason_en: "Fixture pick" }],
      city_breakdown: { shanghai: 1, beijing: 1 },
      trending_artists: ["DJ A"],
      style_distribution: { house: 1 },
      editor_note_zh: "本周测试摘要。",
      editor_note_en: "Fixture weekly summary.",
      source_evidence_path: "/home/private/weekly-summary.md",
    },
    article_dir: "C:\\Users\\win\\private\\weekly-summary",
  });
  await writeJson(path.join(dir, "llm", "enrichment_index.json"), {
    schemaVersion: "weekly_activity_api.materialized_enrichment_index.v1",
    generatedAt: "2026-05-07T10:00:00",
    provider: "deepseek",
    model: "deepseek-v4-pro",
    thinking: "disabled",
    itemCount: 3,
    enrichments: [
      { id: "item-a", sourceItemHash: "fixture", path: "llm/enrichments/item-a.json" },
      { id: "club:abc123", sourceItemHash: "fixture-colon", path: "llm/enrichments/clubu3aabc123.json" },
    ],
    incremental_merge: {
      base_enrichment_index: "/srv/huaidj/base/llm/enrichment_index.json",
      incremental_enrichment_index: "/opt/huaidj/incremental/llm/enrichment_index.json",
    },
  });
  await writeJson(path.join(dir, "llm", "enrichments", "item-a.json"), {
    schemaVersion: "weekly_activity_api.materialized_enrichment.v1",
    generatedAt: "2026-05-07T10:00:00",
    id: "item-a",
    sourceItemHash: "fixture",
    enriched: {
      provider: "deepseek",
      model: "deepseek-v4-pro",
      enrichment: {
        schema_version: "weekly_activity_llm_enrichment.v1",
        title_display: "上海 Club A",
        poster_vl_images: [{ path: "/mnt/c/private/poster.png" }],
      },
    },
  });
  await writeJson(path.join(dir, "llm", "enrichments", "clubu3aabc123.json"), {
    schemaVersion: "weekly_activity_api.materialized_enrichment.v1",
    generatedAt: "2026-05-07T10:00:00",
    id: "club:abc123",
    sourceItemHash: "fixture-colon",
    enriched: {
      provider: "deepseek",
      model: "deepseek-v4-pro",
      enrichment: { schema_version: "weekly_activity_llm_enrichment.v1", title_display: "Colon Id Event" },
    },
  });
  await writeFile(
    path.join(stage7Dir, "articles.jsonl"),
    [
      JSON.stringify({
        article_id: "article-a",
        article_uid: "DADA Beijing/article-a",
        title: "DADA Beijing archives",
        source_account: "DADA Beijing",
        publish_time_status: "unknown",
        entity_count: 2,
        event_count: 1,
        quality_grade: "ready",
        vector_text: "DADA Beijing underground club night",
      }),
      JSON.stringify({
        article_id: "article-b",
        article_uid: "Other/article-b",
        title: "Other story",
        source_account: "Other",
        publish_time_status: "unknown",
        entity_count: 1,
        event_count: 0,
        quality_grade: "ready",
        vector_text: "ambient record shop",
      }),
    ].join("\n") + "\n",
    "utf8",
  );
  await writeFile(
    path.join(stage7Dir, "entities.jsonl"),
    [
      JSON.stringify({
        eid: "entity-a",
        name: "DADA Beijing",
        type: "venue",
        city: "北京",
        source_article_uid: "DADA Beijing/article-a",
        vector_text: "实体:DADA Beijing 类型:venue 城市:北京",
      }),
    ].join("\n") + "\n",
    "utf8",
  );
  await writeFile(
    path.join(stage7Dir, "events.jsonl"),
    [
      JSON.stringify({
        evid: "event-a",
        name: "DADA all night",
        place: "DADA Beijing",
        time_text: "Friday 22:00",
        participants: ["DJ A"],
        source_article_uid: "DADA Beijing/article-a",
        vector_text: "活动:DADA all night 地点:DADA Beijing",
      }),
    ].join("\n") + "\n",
    "utf8",
  );
  await writeJson(path.join(stage7Dir, "release_pointer.staging.json"), {
    schema_version: "stage7_consumer_release_pointer.v1",
    channel: "staging",
    release_ready: true,
    decision: "staging_ready_with_unknown_publish_time",
    generated_at: "2026-05-17T18:38:05",
    counts: { articles: 2, entities: 1, events: 1, missing_publish_time_articles: 2 },
    publish_time_policy: { allow_unknown_publish_time: true, status_field: "publish_time_status" },
    files: {
      articles: { path: path.join(stage7Dir, "articles.jsonl"), bytes: 1, sha256: "fixture" },
      entities: { path: path.join(stage7Dir, "entities.jsonl"), bytes: 1, sha256: "fixture" },
      events: { path: path.join(stage7Dir, "events.jsonl"), bytes: 1, sha256: "fixture" },
      manifest: { path: path.join(stage7Dir, "manifest.json"), bytes: 1, sha256: "fixture" },
    },
  });
  await writeJson(path.join(stage7Dir, "recommendations.json"), {
    decision: "hybrid_recommendations_ready_without_mem0",
    generated_at: "2026-05-17T18:45:09",
    recommendation_count: 1,
    diversity_ratio: 0.5,
    safety: { model_call_executed: false, mem0_write_executed: false },
    recommendations: [{ id: "graph:dada", type: "graph_neighbor", title: "DADA Beijing", score: 0.9 }],
  });
  await writeFile(
    path.join(stage7Dir, "graph_rag_answers.jsonl"),
    JSON.stringify({
      id: "q1",
      query: "DADA 有什么线索",
      answer: "找到 DADA Beijing 线索。",
      citations: [{ source_article_uid: "DADA Beijing/article-a" }],
      citation_count: 1,
      llm_call_executed: false,
    }) + "\n",
    "utf8",
  );
  await writeJson(path.join(stage7Dir, "vector_router_smoke.json"), {
    schema_version: "stage7_vector_collection_router_smoke.v1",
    generated_at: "2026-05-18T02:31:45",
    ok: true,
    decision: "vector_collection_router_smoke_ready",
    sample_size_per_collection: 3,
    top_k: 5,
    collection_groups: {
      qwen3_current: { article: "wechat_stage7_article_qwen3_embedding_4b_1024_current" },
      snowflake_full_staging: { article: "wechat_stage7_article_snowflake_arctic_embed_l_v2_0_1024_20260518_full_staging" },
      english_sidecar_full_staging: { poster: "wechat_stage7_poster_bge_large_en_v1_5_1024_20260518_en_sidecar" },
    },
    channel_probes: {
      qwen3_current: [
        {
          kind: "article",
          collection: "wechat_stage7_article_qwen3_embedding_4b_1024_current",
          checked: 3,
          matched: 3,
          match_rate: 1.0,
        },
      ],
    },
    router_cases: [
      { id: "zh_full_route", lang: "zh", routed_channels: ["qwen3_current", "snowflake_full_staging"], fused: [{ parent_id: "p1" }] },
    ],
    safety: {
      model_loaded: false,
      embedding_call_executed: false,
      qdrant_write_executed: false,
      qdrant_alias_change_executed: false,
      production_publish_executed: false,
    },
  });
  await writeJson(path.join(stage7Dir, "identity_review_workbench.json"), {
    schemaVersion: "stage7_atlas_identity_review_workbench.v1",
    generatedAt: "2026-05-19T10:40:33",
    decision: "identity_review_workbench_ready_read_only",
    summary: {
      sourceReportCount: 3,
      itemCount: 2,
      acceptedForGraph: 0,
      identityProofCount: 0,
      graphWriteAllowedCount: 0,
      needsReviewCount: 2,
    },
    sourceReports: [
      { id: "initial_adjudication", decision: "external_identity_adjudication_ready_no_graph_acceptance", reviewRows: 1, acceptedForGraph: 0 },
    ],
    facets: {
      queues: [{ label: "initial_adjudication", count: 1 }, { label: "future_direct_proof_review_gate", count: 1 }],
      buckets: [{ label: "context_missing_subject", count: 1 }, { label: "needs_subject_context_before_identity_review", count: 1 }],
      domains: [{ label: "ra.co", count: 1 }, { label: "soundcloud.com", count: 1 }],
    },
    items: [
      {
        id: "initial:1",
        queue: "initial_adjudication",
        bucket: "context_missing_subject",
        status: "not_accepted_source_backed_review_required",
        subjectName: "ra.co",
        url: "https://ra.co/dj/test",
        domain: "ra.co",
        sourceAccount: "DADA",
        sourceArticleUid: "DADA/article-a",
        sourceTitle: "DADA profile mention",
        reviewReason: "reachable URL is not identity proof",
        acceptedForGraph: false,
        identityProof: false,
        graphWriteAllowed: false,
      },
      {
        id: "followup:2",
        queue: "future_direct_proof_review_gate",
        bucket: "needs_subject_context_before_identity_review",
        status: "profile_content_needs_manual_review",
        subjectName: "soundcloud.com",
        url: "https://soundcloud.com/test",
        domain: "soundcloud.com",
        sourceTitle: "SoundCloud mention",
        acceptedForGraph: false,
        identityProof: false,
        graphWriteAllowed: false,
      },
    ],
    safety: {
      reportOnly: true,
      networkCallExecuted: false,
      modelCallExecuted: false,
      graphWriteExecuted: false,
      qdrantWriteExecuted: false,
      sqliteWriteExecuted: false,
      mem0WriteExecuted: false,
      paidApiUsed: false,
      cookieOrTokenExported: false,
      dScanExecuted: false,
    },
  });
  return {
    baseDir: dir,
    sourceMapDir,
    stage7AtlasPointer: path.join(stage7Dir, "release_pointer.staging.json"),
    stage7RecommendationsPath: path.join(stage7Dir, "recommendations.json"),
    stage7GraphRagAnswersPath: path.join(stage7Dir, "graph_rag_answers.jsonl"),
    stage7VectorRouterSmokePath: path.join(stage7Dir, "vector_router_smoke.json"),
    stage7IdentityReviewPath: path.join(stage7Dir, "identity_review_workbench.json"),
  };
}

before(async () => {
  const {
    baseDir,
    sourceMapDir,
    stage7AtlasPointer,
    stage7RecommendationsPath,
    stage7GraphRagAnswersPath,
    stage7VectorRouterSmokePath,
    stage7IdentityReviewPath,
  } = await createFixture();
  fixturePaths = { baseDir, sourceMapDir };
  testEnv = { WEEKLY_ACTIVITY_TODAY: "2026-05-09" };
  for (let port = 18787; port < 18850; port += 1) {
    server = createServer({
      baseDir,
      sourceMapDir,
      stage7AtlasPointer,
      stage7RecommendationsPath,
      stage7GraphRagAnswersPath,
      stage7VectorRouterSmokePath,
      stage7IdentityReviewPath,
      env: testEnv,
      llmClient: {
        publicStatus: () => ({
          provider: "deepseek",
          configured: false,
          baseUrl: "https://api.deepseek.com",
          model: "deepseek-v4-pro",
          timeoutMs: 120000,
          thinking: "disabled",
        }),
      },
    });
    try {
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(port, "127.0.0.1", resolve);
      });
      baseUrl = `http://127.0.0.1:${port}`;
      return;
    } catch (error) {
      await new Promise((resolve) => server.close(resolve));
      if (error?.code !== "EADDRINUSE") throw error;
    }
  }
  throw new Error("No free local test port in 18787-18849.");
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
});

test("returns manifest", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/manifest`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schema_version, "weekly_activity_miniprogram_api.v1");
  assert.equal(body.window_start, "2026-05-07");
  assert.equal(body.window_end, "2026-05-21");
  assert.equal(body.source_mode, "sanji_desktop_rss");
  assert.equal(body.direct_rss_feed_fetch, false);
  assert.equal(body.sanji_db_snapshot_export, true);
  assert.equal(body.sanji_desktop_refresh_invoked, true);
  assert.equal(body.sanji_source_contract.source_mode, "sanji_desktop_rss");
  assert.equal(body.sanji_source_contract.direct_rss_feed_fetch, false);
  assert.equal(body.sanji_source_contract.sanji_db_snapshot_export, true);
  assert.equal(body.sanji_source_contract.sanji_desktop_refresh_invoked, true);
  assert.equal(Object.prototype.hasOwnProperty.call(body, "source_queue_path"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(body, "sanji_snapshot_db_path"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(body.sanji_source_contract, "snapshot_db_path"), false);
  assert.equal(body.field_resource_repair.schema_version, "weekly_resource_field_repair.v1");
  assert.equal(body.geocode_enrichment.schema_version, "weekly_geocode_enrichment.v1");
  assert.equal(body.id_consistency_repair.schema_version, "weekly_resource_id_consistency_repair.v1");
});

test("serves the baked club overview artifact through a stable public contract", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/club-overviews`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schema_version, "club_overviews.v1");
  assert.equal(body.generated_at, "2026-05-09T08:00:00+08:00");
  assert.equal(body.club_count, 1);
  assert.equal(body.overview_count, 1);
  assert.deepEqual(body.kind_counts, { week: 1 });
  assert.equal(body.by_club["Club A"][0].title, "Club A 本周活动一览");
  assert.equal(Object.prototype.hasOwnProperty.call(body.by_club["Club A"][0], "club_fakeid"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(body.by_club["Club A"][0], "source_table"), false);
});

test("club overview route remains stable when the optional artifact is absent", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-club-overviews-empty-"));
  const store = new WeeklyActivityDataStore({ baseDir: dir });
  assert.deepEqual(await store.getClubOverviews(), {
    schema_version: "club_overviews.v1",
    generated_at: null,
    as_of_date: null,
    source: null,
    club_count: 0,
    overview_count: 0,
    kind_counts: {},
    by_club: {},
  });
});

test("bake treats club overviews as an online-only optional release artifact", async () => {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const source = await readFile(path.resolve(testDir, "../scripts/bake_and_deploy.py"), "utf8");
  const optionalBlock = source.slice(
    source.indexOf("OPTIONAL_RELEASE_ITEMS = ["),
    source.indexOf("MATERIALIZED_LLM_REQUIRED_ITEMS = ["),
  );
  assert.match(optionalBlock, /"club_overviews\.json"/);
  const bakeBlock = source.slice(source.indexOf("def bake_data("), source.indexOf("def validate_stage7_atlas"));
  assert.doesNotMatch(bakeBlock, /data[\\/]club_overviews\.js|out-js|MINIPROGRAM_DIR/);
});

test("serves Stage7 atlas manifest and search from a release pointer", async () => {
  const manifestRes = await fetch(`${baseUrl}/api/v1/stage7/manifest`);
  assert.equal(manifestRes.status, 200);
  const manifest = await manifestRes.json();
  assert.equal(manifest.schemaVersion, "stage7_atlas_api.manifest.v1");
  assert.equal(manifest.releaseReady, true);
  assert.equal(manifest.counts.articles, 2);

  const searchRes = await fetch(`${baseUrl}/api/v1/stage7/search?q=dada&limit=5`);
  assert.equal(searchRes.status, 200);
  const search = await searchRes.json();
  assert.equal(search.schemaVersion, "stage7_atlas_api.search_response.v1");
  assert.equal(search.retrieval.mode, "materialized_text_scan");
  assert.equal(search.retrieval.liveVectorSearchEnabled, false);
  assert.ok(search.resultCount >= 3);
  assert.ok(search.results.some((item) => item.kind === "articles" && item.item.article_id === "article-a"));
  assert.ok(search.results.some((item) => item.kind === "entities" && item.item.eid === "entity-a"));
  assert.ok(search.results.some((item) => item.kind === "events" && item.item.evid === "event-a"));
});

test("serves Stage7 vector router status without connecting to Qdrant", async () => {
  const res = await fetch(`${baseUrl}/api/v1/stage7/vector-router/status`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schemaVersion, "stage7_atlas_api.vector_router_status.v1");
  assert.equal(body.ok, true);
  assert.equal(body.decision, "vector_collection_router_smoke_ready");
  assert.equal(body.channelProbeSummary.qwen3_current[0].matchRate, 1.0);
  assert.equal(body.serviceIntegration.liveVectorSearchEnabled, false);
  assert.equal(body.safety.qdrantWriteExecuted, false);
  assert.equal(body.safety.qdrantAliasChangeExecuted, false);
});

test("serves Stage7 materialized recommendations and Graph RAG drafts without provider calls", async () => {
  const recRes = await fetch(`${baseUrl}/api/v1/stage7/recommendations?limit=1`);
  assert.equal(recRes.status, 200);
  const rec = await recRes.json();
  assert.equal(rec.schemaVersion, "stage7_atlas_api.recommendations_response.v1");
  assert.equal(rec.safety.modelCallExecuted, false);
  assert.equal(rec.recommendations[0].title, "DADA Beijing");

  const ragRes = await fetch(`${baseUrl}/api/v1/stage7/graph-rag/answers?limit=1`);
  assert.equal(ragRes.status, 200);
  const rag = await ragRes.json();
  assert.equal(rag.schemaVersion, "stage7_atlas_api.graph_rag_answers_response.v1");
  assert.equal(rag.llmCallExecuted, false);
  assert.equal(rag.answers[0].citation_count, 1);
});

test("serves Stage7 atlas overview and browser page", async () => {
  const overviewRes = await fetch(`${baseUrl}/api/v1/stage7/overview?sampleLimit=10`);
  assert.equal(overviewRes.status, 200);
  const overview = await overviewRes.json();
  assert.equal(overview.schemaVersion, "stage7_atlas_api.overview.v1");
  assert.equal(overview.counts.articles, 2);
  assert.equal(overview.serviceIntegration.liveVectorSearchEnabled, false);
  assert.ok(overview.browsingSurfaces.some((item) => item.id === "map"));
  assert.ok(overview.browsingSurfaces.some((item) => item.id === "scenes"));
  assert.ok(overview.facets.mapPlaces.length >= 1);
  assert.equal(overview.safety.llmCallExecuted, false);
  assert.equal(overview.safety.qdrantWriteExecuted, false);

  const pageRes = await fetch(`${baseUrl}/atlas`);
  assert.equal(pageRes.status, 200);
  assert.match(pageRes.headers.get("content-type"), /text\/html/);
  const body = await pageRes.text();
  assert.match(body, /中国地下电子音乐图鉴/);
  assert.match(body, /\/api\/v1\/stage7\/overview/);
  assert.match(body, />地图</);
  assert.match(body, />人物</);
  assert.match(body, />厂牌</);
  assert.match(body, />场景</);
  assert.match(body, /\/atlas\/identity/);
  assert.match(body, /huaidj-logo-nav-512x128\.png/);
});

test("serves Stage7 identity review workbench without graph writes", async () => {
  const apiRes = await fetch(`${baseUrl}/api/v1/stage7/identity-review?domain=ra.co&limit=10`);
  assert.equal(apiRes.status, 200);
  const api = await apiRes.json();
  assert.equal(api.schemaVersion, "stage7_atlas_api.identity_review_response.v1");
  assert.equal(api.decision, "identity_review_workbench_ready_read_only");
  assert.equal(api.summary.acceptedForGraph, 0);
  assert.equal(api.page.total, 1);
  assert.equal(api.items[0].domain, "ra.co");
  assert.equal(api.items[0].acceptedForGraph, false);
  assert.equal(api.safety.graphWriteExecuted, false);
  assert.equal(api.safety.networkCallExecuted, false);

  const pageRes = await fetch(`${baseUrl}/atlas/identity`);
  assert.equal(pageRes.status, 200);
  assert.match(pageRes.headers.get("content-type"), /text\/html/);
  const body = await pageRes.text();
  assert.match(body, /图鉴身份审阅/);
  assert.match(body, /\/api\/v1\/stage7\/identity-review/);
  assert.match(body, /huaidj-logo-nav-512x128\.png/);
});

test("serves Stage7 atlas detail API and browser page with related evidence", async () => {
  const entityRes = await fetch(`${baseUrl}/api/v1/stage7/entities/entity-a?relatedLimit=5`);
  assert.equal(entityRes.status, 200);
  const entity = await entityRes.json();
  assert.equal(entity.schemaVersion, "stage7_atlas_api.detail_response.v1");
  assert.equal(entity.kind, "entities");
  assert.equal(entity.primaryId, "entity-a");
  assert.equal(entity.matchedBy, "eid");
  assert.equal(entity.item.name, "DADA Beijing");
  assert.equal(entity.related.sourceArticle.article_uid, "DADA Beijing/article-a");
  assert.equal(entity.related.events[0].evid, "event-a");
  assert.match(entity.evidence.vectorTextPreview, /实体:DADA Beijing/);
  assert.equal(entity.safety.qdrantWriteExecuted, false);
  assert.equal(entity.safety.neo4jWriteExecuted, false);
  assert.equal(entity.safety.mem0WriteExecuted, false);

  const articleRes = await fetch(`${baseUrl}/api/v1/stage7/articles/${encodeURIComponent("DADA Beijing/article-a")}`);
  assert.equal(articleRes.status, 200);
  const article = await articleRes.json();
  assert.equal(article.kind, "articles");
  assert.equal(article.matchedBy, "article_uid");
  assert.equal(article.related.entities[0].eid, "entity-a");
  assert.equal(article.related.events[0].evid, "event-a");

  const eventRes = await fetch(`${baseUrl}/api/v1/stage7/events/event-a?relatedLimit=5`);
  assert.equal(eventRes.status, 200);
  const event = await eventRes.json();
  assert.equal(event.kind, "events");
  assert.equal(event.primaryId, "event-a");
  assert.equal(event.related.sourceArticle.article_id, "article-a");
  assert.equal(event.related.entities[0].eid, "entity-a");

  const missingRes = await fetch(`${baseUrl}/api/v1/stage7/entities/missing-entity`);
  assert.equal(missingRes.status, 404);
  const missing = await missingRes.json();
  assert.equal(missing.error.code, "STAGE7_DETAIL_NOT_FOUND");

  const pageRes = await fetch(`${baseUrl}/atlas/entities/entity-a`);
  assert.equal(pageRes.status, 200);
  assert.match(pageRes.headers.get("content-type"), /text\/html/);
  const body = await pageRes.text();
  assert.match(body, /图鉴详情/);
  assert.match(body, /\/api\/v1\/stage7\//);
  assert.match(body, /huaidj-logo-nav-512x128\.png/);

  const atlasRes = await fetch(`${baseUrl}/atlas`);
  const atlasBody = await atlasRes.text();
  assert.match(atlasBody, /detailHref\("entities"/);
  assert.match(atlasBody, /detailHref\("events"/);
});

test("default packaged data source is available for CloudBase Run", async () => {
  const store = new WeeklyActivityDataStore();
  const manifest = await store.getManifest();
  assert.equal(manifest.schema_version, "weekly_activity_miniprogram_api.v1");
  assert.ok(manifest.item_count > 0);
});

test("reports DeepSeek LLM provider status without secrets", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/llm/status`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schemaVersion, "weekly_activity_api.llm_status.v1");
  assert.equal(body.llm.provider, "deepseek");
  assert.equal(body.llm.model, "deepseek-v4-pro");
  assert.equal(body.llm.baseUrl, "https://api.deepseek.com");
  assert.equal(body.llm.thinking, "disabled");
  assert.equal(Object.hasOwn(body.llm, "apiKey"), false);
});

test("serves materialized LLM summary without triggering provider calls", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/llm/materialized-summary`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schemaVersion, "weekly_activity_api.materialized_summary.v1");
  assert.equal(body.provider, "deepseek");
  assert.equal(body.thinking, "disabled");
  assert.equal(body.summary.highlight_events[0].title, "上海 Club A");
  assert.equal(Object.hasOwn(body, "article_dir"), false);
  assert.equal(Object.hasOwn(body.summary, "source_evidence_path"), false);
  assert.equal(JSON.stringify(body).includes("/home/"), false);
  assert.equal(JSON.stringify(body).includes("C:\\\\Users"), false);
});

test("serves materialized LLM enrichment index and detail", async () => {
  const indexRes = await fetch(`${baseUrl}/api/v1/weekly/llm/materialized-enrichments`);
  assert.equal(indexRes.status, 200);
  const index = await indexRes.json();
  assert.equal(index.schemaVersion, "weekly_activity_api.materialized_enrichment_index.v1");
  assert.equal(index.enrichments[0].id, "item-a");
  assert.equal(JSON.stringify(index).includes("/srv/"), false);
  assert.equal(JSON.stringify(index).includes("/opt/"), false);

  const detailRes = await fetch(`${baseUrl}/api/v1/weekly/llm/materialized-enrichments/item-a`);
  assert.equal(detailRes.status, 200);
  const detail = await detailRes.json();
  assert.equal(detail.schemaVersion, "weekly_activity_api.materialized_enrichment.v1");
  assert.equal(detail.enriched.enrichment.title_display, "上海 Club A");
  assert.equal(Object.hasOwn(detail.enriched.enrichment, "poster_vl_images"), false);
  assert.equal(JSON.stringify(detail).includes("/mnt/"), false);

  const colonDetailRes = await fetch(`${baseUrl}/api/v1/weekly/llm/materialized-enrichments/${encodeURIComponent("club:abc123")}`);
  assert.equal(colonDetailRes.status, 200);
  const colonDetail = await colonDetailRes.json();
  assert.equal(colonDetail.id, "club:abc123");
  assert.equal(colonDetail.enriched.enrichment.title_display, "Colon Id Event");
});

test("serves a browser landing page", async () => {
  const res = await fetch(`${baseUrl}/`);
  assert.equal(res.status, 200);
  assert.match(res.headers.get("content-type"), /text\/html/);
  const body = await res.text();
  assert.match(body, /HUAIDJ Atlas \/ Weekly/);
  assert.match(body, /\/atlas/);
  assert.match(body, /\/atlas\/identity/);
  assert.match(body, /\/preview/);
});

test("serves huaidj brand asset", async () => {
  const res = await fetch(`${baseUrl}/assets/huaidj-logo-nav-512x128.png`);
  assert.equal(res.status, 200);
  assert.match(res.headers.get("content-type"), /image\/png/);
  assert.ok((await res.arrayBuffer()).byteLength > 1000);
});

test("serves a browser preview page backed by current data", async () => {
  const res = await fetch(`${baseUrl}/preview?cityKey=shanghai`);
  assert.equal(res.status, 200);
  const body = await res.text();
  assert.match(body, /上海 Club A/);
  assert.doesNotMatch(body, /https:\/\/mp\.weixin\.qq\.com\/s\/item-a/);
  assert.match(body, /huaidj-logo-nav-512x128\.png/);
  assert.doesNotMatch(body, /WEEKLY CLUB GUIDE/);
  assert.match(body, /class="event-date">22:00/);
  assert.match(body, /class="event-lineup">DJ A/);
  assert.match(body, /class="event-style">4x4 \/ house \/ club trax/);
  assert.match(body, /<select class="filter-select" name="cityKey"/);
  assert.doesNotMatch(body, /<select class="filter-select" name="date"/);
  assert.match(body, /class="date-option is-active"/);
  assert.match(body, /href="\/preview\?cityKey=shanghai&amp;date=2026-05-09"/);
  assert.doesNotMatch(body, /href="\/preview\?cityKey=shanghai&amp;date=2026-05-10"/);
  assert.doesNotMatch(body, /class="event-lineup">Club A/);
  assert.doesNotMatch(body, /class="event-lineup">.*DADA北京/);
  assert.doesNotMatch(body, /class="source-link"/);
  assert.doesNotMatch(body, /打开原文/);
  assert.doesNotMatch(body, /地点待确认/);
  assert.doesNotMatch(body, /待确认/);
  assert.doesNotMatch(body, /Review Only/);
  assert.match(body, /HUAIDJ WEEKLY/);
  assert.match(body, /src="\/api\/v1\/weekly\/poster\/item-a"/);
  assert.doesNotMatch(body, /mmbiz\.qpic\.cn\/example\/item-a/);
});

test("serves browser preview with English UI labels", async () => {
  const res = await fetch(`${baseUrl}/preview?cityKey=shanghai&lang=en`);
  assert.equal(res.status, 200);
  const body = await res.text();
  assert.match(body, /<html lang="en">/);
  assert.match(body, />City</);
  assert.match(body, /All dates/);
  assert.doesNotMatch(body, /<select class="filter-select" name="date"/);
  assert.match(body, /class="date-strip"/);
  assert.match(body, /This week/);
  assert.match(body, /class="event-date">22:00/);
  assert.match(body, /class="event-style">4x4 \/ house \/ club trax/);
  assert.doesNotMatch(body, /Open original/);
  assert.doesNotMatch(body, /class="source-link"/);
  assert.match(body, /href="\/preview\?cityKey=shanghai"/);
  assert.match(body, /href="\/preview\/items\/item-a\?lang=en"/);
});

test("serves item pages without visible source links or placeholder venues", async () => {
  const res = await fetch(`${baseUrl}/preview/items/item-a`);
  assert.equal(res.status, 200);
  const body = await res.text();
  assert.doesNotMatch(body, /https:\/\/mp\.weixin\.qq\.com\/s\/item-a/);
  assert.match(body, /北京市朝阳区南营房胡同日坛国际贸易中心A座北门B1层/);
  assert.match(body, /data-copy="北京市朝阳区南营房胡同日坛国际贸易中心A座北门B1层"/);
  assert.match(body, /复制地址/);
  assert.match(body, /DJ LINEUP<\/span>DJ A/);
  assert.match(body, /时间<\/span>22:00/);
  assert.match(body, /风格<\/span>4x4 \/ house \/ club trax/);
  assert.doesNotMatch(body, /DJ LINEUP<\/span>Club A/);
  assert.doesNotMatch(body, /DJ LINEUP<\/span>.*DADA北京/);
  assert.doesNotMatch(body, /待确认/);
  assert.doesNotMatch(body, /打开活动原文/);
});

test("infers verified detailed venue addresses and exposes copy action", async () => {
  const res = await fetch(`${baseUrl}/preview/items/item-b`);
  assert.equal(res.status, 200);
  const body = await res.text();
  assert.match(body, /AURORA @ 莫须有工厂/);
  assert.match(body, /地址<\/span><div class="address-copy">/);
  assert.match(body, /北京市朝阳区酒仙桥路2号798艺术区706路B06-2/);
  assert.match(body, /data-copy="北京市朝阳区酒仙桥路2号798艺术区706路B06-2"/);
  assert.match(body, /复制地址/);
  assert.doesNotMatch(body, /DJ LINEUP<\/span>/);
  assert.doesNotMatch(body, /DJ 简介/);
  assert.doesNotMatch(body, /NIGHT TOUR \/ 夜游/);
  assert.doesNotMatch(body, /待确认/);
});

test("serves item pages with English UI labels", async () => {
  const res = await fetch(`${baseUrl}/preview/items/item-a?lang=en`);
  assert.equal(res.status, 200);
  const body = await res.text();
  assert.match(body, /<html lang="en">/);
  assert.match(body, /<span>Club<\/span>Club A/);
  assert.match(body, /<span>Time<\/span>22:00/);
  assert.match(body, /Copy address/);
  assert.doesNotMatch(body, /Open original post/);
  assert.match(body, /href="\/preview\?lang=en"/);
});

test("filters current items by city and excludes review candidates", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=shanghai`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.page.total, 2);
  assert.equal(body.items[0].id, "item-a");
  assert.equal(body.items[0].organizer_key, "dadabarbeijing");
  assert.equal(body.items[0].club_profile, undefined);
  assert.equal(body.items[0].source_action.url_hash, "aaaaaaaaaaaaaaaa");
  assert.equal(body.items[0].source_action.url, undefined);
  assert.equal(body.items[0].source_article.url_hash, "aaaaaaaaaaaaaaaa");
  assert.equal(body.items[0].source_article.url, undefined);
  assert.equal(body.items[0].description_original_lines.length, 2);
  assert.equal("merge_provenance" in body.items[0], false);
  assert.equal("field_evidence_refs" in body.items[0], false);
  assert.equal("address_verification" in body.items[0], false);
  assert.equal("geo_reverse_address" in body.items[0], false);
  assert.equal(body.items[1].id, "club:abc123");
});

test("current feed excludes clearly non-electronic activities but preserves electronic evidence", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-electronic-relevance-"));
  await writeJson(path.join(dir, "current.json"), {
    schema_version: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-06-21T00:00:00+08:00",
    item_count: 3,
    items: [
      {
        id: "pure-cocktail",
        title: "重庆首届鸡尾酒节",
        city_key: "chongqing",
        city_keys: ["chongqing"],
        event_date_iso_guess: "2026-06-21",
        quality_status: "READY",
      },
      {
        id: "standup",
        title: "周六脱口秀开放麦",
        city_key: "chongqing",
        city_keys: ["chongqing"],
        event_date_iso_guess: "2026-06-21",
        quality_status: "READY",
      },
      {
        id: "cocktail-dj-room",
        title: "Cocktail room with DJ Acid",
        city_key: "chongqing",
        city_keys: ["chongqing"],
        event_date_iso_guess: "2026-06-21",
        quality_status: "READY",
        lineup: ["DJ Acid"],
        venue: ["Club Room"],
      },
    ],
  });
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-06-21" });

  const body = await store.getCurrent({ cityKey: "chongqing", limit: 10 });

  assert.deepEqual(Array.from(body.items, (item) => item.id), ["cocktail-dj-room"]);
  assert.equal(body.page.total, 1);
});

test("filters multi-day events by inclusive date range", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?date=2026-05-20`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.page.total, 1);
  assert.equal(body.items[0].id, "range-week");
});

test("HTTP date windows keep list, city and date facets in one cache-isolated projection", async () => {
  const windowQuery = "scope=current&dateStart=2026-05-09&dateEnd=2026-05-10";
  const firstRes = await fetch(`${baseUrl}/api/v1/weekly/current?${windowQuery}&limit=100&_ts=window-a`);
  assert.equal(firstRes.status, 200);
  assert.equal(firstRes.headers.get("x-weekly-cache"), "MISS");
  const current = await firstRes.json();
  assert.equal(current.page.total, 2);
  assert.deepEqual(current.items.map((item) => item.id).sort(), ["item-a", "item-b"]);

  const repeatRes = await fetch(`${baseUrl}/api/v1/weekly/current?${windowQuery}&limit=100&_ts=window-b`);
  assert.equal(repeatRes.headers.get("x-weekly-cache"), "HIT");

  const otherWindowRes = await fetch(`${baseUrl}/api/v1/weekly/current?scope=current&dateStart=2026-05-11&dateEnd=2026-05-11&limit=100&_ts=window-c`);
  assert.equal(otherWindowRes.headers.get("x-weekly-cache"), "MISS");
  const otherWindow = await otherWindowRes.json();
  assert.deepEqual(otherWindow.items.map((item) => item.id), ["club:abc123"]);

  const citiesRes = await fetch(`${baseUrl}/api/v1/weekly/cities?${windowQuery}&_ts=window-cities`);
  const cities = await citiesRes.json();
  assert.equal(cities.scope, "current");
  assert.equal(cities.item_count, current.page.total);
  assert.deepEqual(
    Object.fromEntries(cities.cities.map((entry) => [entry.city_key, entry.count])),
    { beijing: 1, shanghai: 1 },
  );

  const datesRes = await fetch(`${baseUrl}/api/v1/weekly/dates?${windowQuery}&_ts=window-dates`);
  const dates = await datesRes.json();
  assert.equal(dates.scope, "current");
  assert.equal(dates.item_count, current.page.total);
  assert.deepEqual(dates.dates.map((entry) => entry.date), ["2026-05-09", "2026-05-10"]);
});

test("explicit single-day current filters ignore extra non-primary parser guesses", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-single-date-guesses-"));
  await writeJson(path.join(dir, "current.json"), {
    schema_version: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-06-04T00:00:00+08:00",
    item_count: 1,
    items: [
      {
        id: "single-from-calendar",
        title: "Single event from a calendar article",
        city_key: "shanghai",
        city_keys: ["shanghai"],
        city: ["上海"],
        event_date_start: "2026-06-05",
        event_date_end: "2026-06-05",
        event_date_iso_guess: "2026-06-05",
        event_date_iso_guesses: ["2026-06-05", "2026-06-12", "2026-06-13"],
        quality_status: "READY",
      },
    ],
  });
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-06-04" });

  const realDate = await store.getCurrent({ date: "2026-06-05", limit: 10 });
  const guessedDate = await store.getCurrent({ date: "2026-06-12", limit: 10 });

  assert.deepEqual(Array.from(realDate.items, (item) => item.id), ["single-from-calendar"]);
  assert.deepEqual(Array.from(guessedDate.items, (item) => item.id), []);
});

test("default current feed is strict while explicit lookback can include recent past events", async () => {
  const store = new WeeklyActivityDataStore({
    baseDir: fixturePaths.baseDir,
    sourceMapDir: fixturePaths.sourceMapDir,
    today: "2026-05-21",
  });

  const body = await store.getCurrent({ limit: 10 });
  assert.equal(body.filters.lookbackDays, null);
  assert.deepEqual(Array.from(body.items, (item) => item.id), ["range-week"]);

  const lookbackCurrent = await store.getCurrent({ limit: 10, lookbackDays: 45 });
  assert.equal(lookbackCurrent.filters.lookbackDays, 45);
  assert.deepEqual(Array.from(lookbackCurrent.items, (item) => item.id), ["item-a", "item-b", "club:abc123", "range-week"]);

  const explicitPast = await store.getCurrent({ date: "2026-05-09", limit: 10 });
  assert.equal(explicitPast.items[0].id, "item-a");
});

test("default current feed returns up to 100 rows so manifest 73 is not truncated to 50", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-current-limit-"));
  const items = Array.from({ length: 120 }, (_, index) => ({
    id: `future-${index}`,
    title: `Future ${index}`,
    city_key: "shanghai",
    city_keys: ["shanghai"],
    city: ["上海"],
    event_date_iso_guess: "2026-06-02",
    event_date_iso_guesses: ["2026-06-02"],
    quality_status: "READY",
  }));
  await writeJson(path.join(dir, "current.json"), {
    schema_version: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-06-01T00:00:00+08:00",
    item_count: items.length,
    items,
  });
  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-06-01" });

  const body = await store.getCurrent();

  assert.equal(body.page.limit, 100);
  assert.equal(body.page.total, 120);
  assert.equal(body.items.length, 100);
  assert.equal(body.page.nextCursor, "100");
});

test("date index hides past date chips when today advances", async () => {
  const store = new WeeklyActivityDataStore({
    baseDir: fixturePaths.baseDir,
    sourceMapDir: fixturePaths.sourceMapDir,
    today: "2026-05-21",
  });

  const body = await store.getDates();
  assert.deepEqual(Array.from(body.dates, (item) => item.date), [
    "2026-05-21",
    "2026-05-22",
    "2026-05-23",
    "2026-05-24",
  ]);
});

test("default current feed keeps the previous event date before late-night cutoff", async () => {
  const lateNightStore = new WeeklyActivityDataStore({
    baseDir: fixturePaths.baseDir,
    sourceMapDir: fixturePaths.sourceMapDir,
    now: "2026-05-09T17:30:00.000Z",
  });

  const body = await lateNightStore.getCurrent({ cityKey: "shanghai", limit: 10 });
  assert.deepEqual(Array.from(body.items, (item) => item.id), ["item-a", "club:abc123"]);

  const dateIndex = await lateNightStore.getDates();
  assert.equal(dateIndex.dates[0].date, "2026-05-09");
});

test("default current feed drops the previous event date after late-night cutoff", async () => {
  const morningStore = new WeeklyActivityDataStore({
    baseDir: fixturePaths.baseDir,
    sourceMapDir: fixturePaths.sourceMapDir,
    now: "2026-05-10T00:30:00.000Z",
  });

  const body = await morningStore.getCurrent({ cityKey: "shanghai", limit: 10, lookbackDays: 0 });
  assert.deepEqual(Array.from(body.items, (item) => item.id), ["club:abc123"]);
});

test("current feed can include a bounded lookback window for venue source schedules", async () => {
  const store = new WeeklyActivityDataStore({
    baseDir: fixturePaths.baseDir,
    sourceMapDir: fixturePaths.sourceMapDir,
    today: "2026-05-10",
  });

  const body = await store.getCurrent({ cityKey: "shanghai", lookbackDays: 1, limit: 10 });
  assert.deepEqual(Array.from(body.items, (item) => item.id), ["item-a", "club:abc123"]);
});

test("current feed dedupe preserves non-empty fields from lower-score duplicates", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "weekly-api-empty-merge-"));
  await writeJson(path.join(dir, "manifest.json"), {
    schema_version: "weekly_activity_miniprogram_api.v1",
    generated_at: "2026-05-09T00:00:00",
    item_count: 2,
  });
  await writeJson(path.join(dir, "current.json"), {
    schema_version: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-05-09T00:00:00",
    items: [
      {
        id: "dedupe-a",
        title: "Dedupe Night",
        city_key: "shanghai",
        city_keys: ["shanghai"],
        city: ["上海"],
        event_date_start: "2026-05-09",
        event_date_iso_guess: "2026-05-09",
        quality_status: "READY",
        venue: ["Heim Shanghai"],
        venue_name: "Heim Shanghai",
        address: "上海市黄浦区长乐路462号M101",
        poster_url: "https://example.test/main-poster.jpg",
        source_action: { available: true, url_hash: "src:heim" },
        source_article: { url_hash: "src:heim", title: "今晚|Heim Club Night", account_name: "Heim Shanghai" },
      },
      {
        id: "dedupe-b",
        title: "Dedupe Night",
        city_key: "shanghai",
        city_keys: ["shanghai"],
        city: ["上海"],
        event_date_start: "2026-05-09",
        event_date_iso_guess: "2026-05-09",
        quality_status: "READY",
        venue: ["Heim Shanghai"],
        venue_name: "Heim Shanghai",
        address: "",
        poster_url: "",
        event_time_text: "22:00 - Late",
        event_time_source: "source_text",
        source_action: { available: true, url_hash: "" },
        source_article: { url_hash: "", title: "" },
      },
    ],
  });

  const store = new WeeklyActivityDataStore({ baseDir: dir, today: "2026-05-09" });
  const body = await store.getCurrent({ cityKey: "shanghai", limit: 10 });

  assert.equal(body.page.total, 1);
  assert.equal(body.items[0].id, "dedupe-b");
  assert.equal(body.items[0].event_time_text, "22:00 - Late");
  assert.equal(body.items[0].address, "上海市黄浦区长乐路462号M101");
  assert.equal(body.items[0].poster_url, "https://example.test/main-poster.jpg");
  assert.equal(body.items[0].source_action.url_hash, "src:heim");
  assert.equal(body.items[0].source_article.title, "今晚|Heim Club Night");
});

test("supports cursor pagination", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?limit=1`);
  const body = await res.json();
  assert.equal(body.items.length, 1);
  assert.equal(body.page.nextCursor, "1");
});

test("caches repeated current list requests while ignoring cache-busting timestamps", async () => {
  const firstRes = await fetch(`${baseUrl}/api/v1/weekly/current?limit=7&lookbackDays=12&_ts=first`);
  assert.equal(firstRes.status, 200);
  assert.equal(firstRes.headers.get("x-weekly-cache"), "MISS");
  assert.match(firstRes.headers.get("cache-control") || "", /max-age=\d+/);
  const first = await firstRes.json();

  const secondRes = await fetch(`${baseUrl}/api/v1/weekly/current?limit=7&lookbackDays=12&_ts=second`);
  assert.equal(secondRes.status, 200);
  assert.equal(secondRes.headers.get("x-weekly-cache"), "HIT");
  const second = await secondRes.json();

  assert.deepEqual(
    second.items.map((item) => item.id),
    first.items.map((item) => item.id),
  );
  assert.equal(second.page.total, first.page.total);
});

test("uses normalized current-list query values for cache keys", async () => {
  const firstRes = await fetch(`${baseUrl}/api/v1/weekly/current?limit=999&lookbackDays=999&_ts=normalized-a`);
  assert.equal(firstRes.status, 200);
  assert.equal(firstRes.headers.get("x-weekly-cache"), "MISS");
  const first = await firstRes.json();
  assert.equal(first.page.limit, 100);
  assert.equal(first.filters.lookbackDays, 45);

  const secondRes = await fetch(`${baseUrl}/api/v1/weekly/current?limit=100&lookbackDays=45&_ts=normalized-b`);
  assert.equal(secondRes.status, 200);
  assert.equal(secondRes.headers.get("x-weekly-cache"), "HIT");
  const second = await secondRes.json();

  assert.deepEqual(
    second.items.map((item) => item.id),
    first.items.map((item) => item.id),
  );
  assert.equal(second.page.total, first.page.total);
});

test("keeps explicit max lookback distinct from default current cache key", async () => {
  const defaultRes = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=cache-split-probe&limit=100&_ts=cache-split-default`);
  assert.equal(defaultRes.status, 200);
  assert.equal(defaultRes.headers.get("x-weekly-cache"), "MISS");
  const defaultBody = await defaultRes.json();
  assert.equal(defaultBody.filters.lookbackDays, null);

  const lookbackRes = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=cache-split-probe&limit=100&lookbackDays=45&_ts=cache-split-lookback`);
  assert.equal(lookbackRes.status, 200);
  assert.equal(lookbackRes.headers.get("x-weekly-cache"), "MISS");
  const lookbackBody = await lookbackRes.json();
  assert.equal(lookbackBody.filters.lookbackDays, 45);
});

test("compresses public weekly JSON responses without changing the payload shape", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/current?limit=7&lookbackDays=13&_ts=gzip`, {
    headers: { "Accept-Encoding": "gzip" },
  });
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-encoding"), "gzip");
  const body = await res.json();
  assert.equal(body.schemaVersion, "weekly_activity_api.current_response.v1");
  assert.ok(Array.isArray(body.items));
});

test("returns detail by id", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/items/item-a`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.title, "上海 Club A");
  assert.equal(body.organizer_key, "dadabarbeijing");
  assert.equal(body.club_profile.schema_version, "weekly_club_profile.v1");
  assert.equal(body.club_profile.display_name, "Dada Bar Beijing");
  assert.equal(body.source_action.url, "https://mp.weixin.qq.com/s/item-a");
  assert.equal(body.merge_provenance[0].source, "aggregate-child");
  assert.equal(body.field_evidence_refs.title[0].ref, "ocr-span");
  assert.equal(body.address_verification.provider, "fixture");
  assert.equal(body.geo_reverse_address, "fixture reverse address");

  const colonRes = await fetch(`${baseUrl}/api/v1/weekly/items/${encodeURIComponent("club:abc123")}`);
  assert.equal(colonRes.status, 200);
  const colonBody = await colonRes.json();
  assert.equal(colonBody.title, "Colon Id Event");
});

test("returns club profile contract on batch detail items", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/items/batch?ids=item-a,${encodeURIComponent("club:abc123")}`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.items.length, 2);
  assert.equal(body.items[0].organizer_key, "dadabarbeijing");
  assert.equal(body.items[1].organizer_key, "clubcolon");
});

test("detail and batch apply public item projection", async () => {
  const detailRes = await fetch(`${baseUrl}/api/v1/weekly/items/item-a`);
  assert.equal(detailRes.status, 200);
  const detail = await detailRes.json();
  assert.equal(detail.address_verification.provider, "fixture");
  assert.equal(detail.source_action.url, "https://mp.weixin.qq.com/s/item-a");
  assert.deepEqual(detail.poster_selection_evidence.visible_text_lines, ["DJ A / 22:00"]);
  assert.equal(detail.aggregation_source_kind, "wechat_article");
  assert.equal(detail.dedupe_key, "fixture:item-a");
  assert.equal(detail.discovery_source, "sanji_desktop_rss");
  assert.equal(detail.extraction_model, "qwen-vl-fixture");
  assert.equal(detail.metadata_enriched_at, "2026-05-07T10:00:00+08:00");
  assert.equal(Object.hasOwn(detail.field_evidence_refs, "/home/private/evidence.json"), false);
  assert.equal(Object.hasOwn(detail.field_evidence_refs, "C:\\Users\\win\\private\\evidence.json"), false);

  const batchRes = await fetch(`${baseUrl}/api/v1/weekly/items/batch?ids=item-a`);
  assert.equal(batchRes.status, 200);
  const batch = await batchRes.json();
  assert.equal(batch.items.length, 1);

  for (const item of [detail, batch.items[0]]) {
    for (const key of ["poster_vl_images", "source_evidence_path", "emergency_qwen36_lineup_patch"]) {
      assert.equal(Object.hasOwn(item, key), false);
    }
    const serialized = JSON.stringify(item);
    for (const marker of ["C:\\\\Users", "/home/", "/mnt/", "/srv/", "/opt/"]) {
      assert.equal(serialized.includes(marker), false);
    }
  }
});

test("returns source action by hash without exposing it in current list", async () => {
  const currentRes = await fetch(`${baseUrl}/api/v1/weekly/current?cityKey=shanghai`);
  const current = await currentRes.json();
  assert.equal(Object.hasOwn(current.items[0].source_action, "url"), false);

  const res = await fetch(`${baseUrl}/api/v1/weekly/source/aaaaaaaaaaaaaaaa`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schemaVersion, "weekly_activity_api.source_action.v1");
  assert.equal(body.mode, "webview");
  assert.equal(body.url, "https://mp.weixin.qq.com/s/item-a");
});

test("source action rejects file and machine-local URLs at the API boundary", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/source/cccccccccccccccc`);
  assert.equal(res.status, 404);
});

test("returns weekly atlas event snapshot without exposing fuzzy candidate ids", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/atlas-events/item-a`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schemaVersion, "weekly_activity_api.atlas_event.v1");
  assert.equal(body.eventId, "item-a");
  assert.equal(body.lineupResolved.length, 2);
  assert.equal(body.lineupResolved[0].artistId, "atlas:entity:dj-a");
  assert.equal(body.lineupResolved[0].displayTier, "show");
  assert.equal(body.lineupResolved[1].artistId, null);
  assert.equal(body.lineupResolved[1].displayTier, "show_with_hint");
  assert.equal(Object.hasOwn(body.lineupResolved[1].candidates[0], "artist_id"), false);
  assert.equal(body.artistProfiles[0].canonicalName, "DJ A");
  assert.equal(body.safety.fuzzyCandidateIdsExposed, false);
});

test("uses unified error shape", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/items/missing`);
  assert.equal(res.status, 404);
  const body = await res.json();
  assert.equal(body.error.code, "ITEM_NOT_FOUND");
});

test("llm enrich rejects public GET even when disabled", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/llm/enrich?id=item-a`);
  assert.equal(res.status, 405);
  const body = await res.json();
  assert.equal(body.error.code, "METHOD_NOT_ALLOWED");
});

test("llm enrich fails closed when private review token is not configured", async () => {
  testEnv.DEEPSEEK_ENRICH_ENABLED = "true";
  testEnv.DEEPSEEK_API_KEY = "sk-test";
  const res = await fetch(`${baseUrl}/api/v1/weekly/llm/enrich?id=item-a`, { method: "POST" });
  assert.equal(res.status, 503);
  const body = await res.json();
  assert.equal(body.error.code, "ADMIN_TOKEN_NOT_CONFIGURED");
  delete testEnv.DEEPSEEK_ENRICH_ENABLED;
  delete testEnv.DEEPSEEK_API_KEY;
});

test("llm enrich requires private review authorization", async () => {
  testEnv.DEEPSEEK_ENRICH_ENABLED = "true";
  testEnv.DEEPSEEK_API_KEY = "sk-test";
  testEnv.WEEKLY_REVIEW_ADMIN_TOKEN = "test-review-token";
  const res = await fetch(`${baseUrl}/api/v1/weekly/llm/enrich?id=item-a`, { method: "POST" });
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error.code, "ADMIN_AUTH_REQUIRED");
  delete testEnv.DEEPSEEK_ENRICH_ENABLED;
  delete testEnv.DEEPSEEK_API_KEY;
  delete testEnv.WEEKLY_REVIEW_ADMIN_TOKEN;
});

test("llm enrich requires id after private authorization", async () => {
  testEnv.DEEPSEEK_ENRICH_ENABLED = "true";
  testEnv.DEEPSEEK_API_KEY = "sk-test";
  testEnv.WEEKLY_REVIEW_ADMIN_TOKEN = "test-review-token";
  const res = await fetch(`${baseUrl}/api/v1/weekly/llm/enrich`, {
    method: "POST",
    headers: { "x-weekly-review-token": "test-review-token" },
  });
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.equal(body.error.code, "MISSING_ID");
  delete testEnv.DEEPSEEK_ENRICH_ENABLED;
  delete testEnv.DEEPSEEK_API_KEY;
  delete testEnv.WEEKLY_REVIEW_ADMIN_TOKEN;
});

test("llm enrich returns 404 for unknown id after private authorization", async () => {
  testEnv.DEEPSEEK_ENRICH_ENABLED = "true";
  testEnv.DEEPSEEK_API_KEY = "sk-test";
  testEnv.WEEKLY_REVIEW_ADMIN_TOKEN = "test-review-token";
  const res = await fetch(`${baseUrl}/api/v1/weekly/llm/enrich?id=unknown-item`, {
    method: "POST",
    headers: { "x-weekly-review-token": "test-review-token" },
  });
  assert.equal(res.status, 404);
  const body = await res.json();
  assert.equal(body.error.code, "ITEM_NOT_FOUND");
  delete testEnv.DEEPSEEK_ENRICH_ENABLED;
  delete testEnv.DEEPSEEK_API_KEY;
  delete testEnv.WEEKLY_REVIEW_ADMIN_TOKEN;
});

test("llm weekly-summary serves materialized data without live provider execution", async () => {
  const res = await fetch(`${baseUrl}/api/v1/weekly/llm/weekly-summary`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schemaVersion, "weekly_activity_api.llm_summary.v1");
  assert.equal(body.source, "materialized-summary");
  assert.equal(body.liveGenerationExecuted, false);
  assert.equal(body.summary.highlight_events[0].title, "上海 Club A");
});
