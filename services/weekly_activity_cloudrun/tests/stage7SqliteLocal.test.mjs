import assert from "node:assert/strict";
import crypto from "node:crypto";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import Database from "better-sqlite3";
import { createServer } from "../src/server.mjs";
import { Stage7AtlasSqliteStore } from "../src/stage7AtlasSqliteStore.mjs";
import { runAtlasGraphSearchSelfTest } from "../scripts/atlasGraphSearchSelfTest.mjs";

let server;
let baseUrl;
let fixtureDbPath;
let fixtureAssetDir;
let fixtureAssetsPath;

function leadingZeroBits(hex) {
  let count = 0;
  for (const char of String(hex || "")) {
    const value = Number.parseInt(char, 16);
    if (!Number.isFinite(value)) return -1;
    if (value === 0) {
      count += 4;
      continue;
    }
    return count + (4 - value.toString(2).length);
  }
  return count;
}

function solveFallbackChallenge(challenge) {
  for (let attempt = 0; attempt < 1_000_000; attempt += 1) {
    const proof = String(attempt);
    const hash = crypto.createHash("sha256").update(`${challenge.payload}.${challenge.signature}.${proof}`).digest("hex");
    if (leadingZeroBits(hash) >= challenge.difficulty) return proof;
  }
  throw new Error("Unable to solve fallback Atlas challenge");
}

function assertNoPublicAtlasLeak(payload) {
  const serialized = JSON.stringify(payload);
  assert.doesNotMatch(serialized, /[A-Za-z]:\\/);
  assert.doesNotMatch(serialized, /file:\/\//i);
  assert.doesNotMatch(serialized, /\.sqlite\b/i);
  assert.doesNotMatch(serialized, /entity_merge_groups_report_only\.jsonl/i);
  assert.doesNotMatch(serialized, /venue_sound_system_evidence\.jsonl/i);
  assert.doesNotMatch(serialized, /"source_url"\s*:/i);
  assert.doesNotMatch(serialized, /"raw_json"\s*:/i);
}

function createAtlasDb(dbPath) {
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE articles (
      row_pk INTEGER PRIMARY KEY,
      article_id TEXT,
      article_uid TEXT,
      title TEXT,
      source_account TEXT,
      publish_time TEXT,
      publish_time_status TEXT,
      publish_time_index_status TEXT,
      city_label TEXT,
      entity_count INTEGER,
      event_count INTEGER,
      quality_grade TEXT,
      extract_version TEXT,
      input_chars INTEGER,
      local_image_count INTEGER,
      source_archived_at TEXT,
      vector_text_preview TEXT,
      raw_json TEXT
    );
    CREATE TABLE entities (
      row_pk INTEGER PRIMARY KEY,
      eid TEXT,
      name TEXT,
      type TEXT,
      city TEXT,
      source_kind TEXT,
      source_article_uid TEXT,
      confidence REAL,
      aliases_json TEXT,
      bio TEXT,
      evidence_quote TEXT,
      vector_text_preview TEXT,
      raw_json TEXT
    );
    CREATE TABLE events (
      row_pk INTEGER PRIMARY KEY,
      evid TEXT,
      name TEXT,
      place TEXT,
      city TEXT,
      time_iso TEXT,
      time_text TEXT,
      source_kind TEXT,
      source_article_uid TEXT,
      confidence REAL,
      participants_json TEXT,
      organizers_json TEXT,
      vector_text_preview TEXT,
      raw_json TEXT
    );
    CREATE TABLE identity_review_items (
      row_pk INTEGER PRIMARY KEY,
      item_id TEXT,
      queue TEXT,
      bucket TEXT,
      status TEXT,
      subject_name TEXT,
      subject_type TEXT,
      url TEXT,
      domain TEXT,
      source_account TEXT,
      source_article_uid TEXT,
      source_title TEXT,
      support_count INTEGER,
      identity_signal_score REAL,
      accepted_for_graph INTEGER,
      identity_proof INTEGER,
      graph_write_allowed INTEGER,
      review_reason TEXT,
      next_actions_json TEXT,
      signals_json TEXT,
      raw_json TEXT
    );
    CREATE TABLE recommendations (
      row_pk INTEGER PRIMARY KEY,
      item_id TEXT,
      type TEXT,
      title TEXT,
      score REAL,
      evidence_json TEXT,
      source_scores_json TEXT,
      raw_json TEXT
    );
    CREATE TABLE graph_rag_answers (
      row_pk INTEGER PRIMARY KEY,
      item_id TEXT,
      query TEXT,
      answer TEXT,
      citation_count INTEGER,
      fact_count INTEGER,
      citations_json TEXT,
      facts_json TEXT,
      status TEXT,
      raw_json TEXT
    );
    CREATE TABLE runtime_reports (
      row_pk INTEGER PRIMARY KEY,
      report_name TEXT NOT NULL,
      path TEXT,
      decision TEXT,
      ok INTEGER,
      summary_json TEXT,
      raw_json TEXT
    );
    CREATE TABLE map_geocode_places (
      place_id TEXT PRIMARY KEY,
      label TEXT NOT NULL,
      normalized_place TEXT NOT NULL,
      city TEXT NOT NULL DEFAULT '',
      lat REAL,
      lon REAL,
      geocode_status TEXT NOT NULL,
      geocode_source TEXT NOT NULL,
      precision TEXT NOT NULL,
      event_count INTEGER NOT NULL DEFAULT 0,
      entity_count INTEGER NOT NULL DEFAULT 0,
      article_count INTEGER NOT NULL DEFAULT 0,
      sample_article_uid TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL
    );
    CREATE TABLE map_geocode_review_items (
      review_id TEXT PRIMARY KEY,
      place_id TEXT NOT NULL,
      label TEXT NOT NULL,
      normalized_place TEXT NOT NULL,
      review_bucket TEXT NOT NULL,
      candidate_city TEXT NOT NULL DEFAULT '',
      candidate_lat REAL,
      candidate_lon REAL,
      candidate_source TEXT NOT NULL DEFAULT '',
      confidence REAL,
      reason TEXT NOT NULL DEFAULT '',
      event_count INTEGER NOT NULL DEFAULT 0,
      entity_count INTEGER NOT NULL DEFAULT 0,
      article_count INTEGER NOT NULL DEFAULT 0,
      sample_article_uid TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE VIRTUAL TABLE article_fts USING fts5(row_pk UNINDEXED, article_uid, title, source_account, vector_text_preview);
    CREATE VIRTUAL TABLE entity_fts USING fts5(row_pk UNINDEXED, eid UNINDEXED, name, type, city, source_article_uid, vector_text_preview);
    CREATE VIRTUAL TABLE event_fts USING fts5(row_pk UNINDEXED, evid UNINDEXED, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview);
  `);
  db.prepare("INSERT INTO metadata(key, value) VALUES (?, ?)").run("generated_at", "2026-05-21T00:00:00");
  db.prepare("INSERT INTO metadata(key, value) VALUES (?, ?)").run(
    "source_counts",
    JSON.stringify({ articles: 1, entities: 1, events: 1 }),
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    1,
    "article-a",
    "DADA/article-a",
    "DADA archive",
    "DADA",
    "",
    "unknown",
    "unknown",
    "Beijing",
    1,
    1,
    "ready",
    "fixture",
    100,
    0,
    "",
    "DADA Beijing underground club night",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(1, "entity-a", "DADA Beijing", "venue", "Beijing", "article", "DADA/article-a", 0.9, "[]", "", "", "DADA venue", "{}");
  db.prepare(
    `INSERT INTO events (
      row_pk, evid, name, place, city, time_iso, time_text, source_kind,
      source_article_uid, confidence, participants_json, organizers_json,
      vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(1, "event-a", "DADA all night", "Dada Beijing", "Beijing", "", "Friday 22:00", "article", "DADA/article-a", 0.9, "[]", "[]", "DADA event", "{}");
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    1,
    "DADA/article-a",
    "DADA archive",
    "DADA",
    "DADA Beijing underground club night",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    1,
    "entity-a",
    "DADA Beijing",
    "venue",
    "Beijing",
    "DADA/article-a",
    "DADA venue",
  );
  db.prepare("INSERT INTO event_fts(row_pk, evid, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    1,
    "event-a",
    "DADA all night",
    "Dada Beijing",
    "Beijing",
    "Friday 22:00",
    "DADA/article-a",
    "DJ A",
    "DADA event",
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    2,
    "article-wine",
    "Hakka/article-wine",
    "院吧夏日新酒单 · 葡萄酒系列",
    "院吧 Hakka Bar",
    "",
    "unknown",
    "unknown",
    "",
    2,
    0,
    "ready",
    "fixture",
    100,
    0,
    "",
    "Hakka Bar wine menu",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(2, "entity-wine", "马洛之家 · 弗德乔干白葡萄酒", "product", "", "article", "Hakka/article-wine", 0.9, "[]", "", "", "wine product", "{}");
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(3, "entity-hakka", "院吧 Hakka Bar", "organization", "", "article", "Hakka/article-wine", 1.0, "[]", "", "", "Hakka Bar", "{}");
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    2,
    "Hakka/article-wine",
    "院吧夏日新酒单 · 葡萄酒系列",
    "院吧 Hakka Bar",
    "Hakka Bar wine menu",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    2,
    "entity-wine",
    "马洛之家 · 弗德乔干白葡萄酒",
    "product",
    "",
    "Hakka/article-wine",
    "wine product",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    3,
    "entity-hakka",
    "院吧 Hakka Bar",
    "organization",
    "",
    "Hakka/article-wine",
    "Hakka Bar",
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    3,
    "article-art",
    "VinylCoffee/article-art",
    "第二届青年影像艺术展亮相Vinyl Café",
    "黑胶咖啡VinylCoffee",
    "",
    "unknown",
    "unknown",
    "",
    1,
    0,
    "ready",
    "fixture",
    100,
    0,
    "",
    "gallery cafe art exhibition",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(4, "entity-art", "青年影像艺术展", "work", "", "article", "VinylCoffee/article-art", 0.9, "[]", "", "", "art exhibition", "{}");
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    3,
    "VinylCoffee/article-art",
    "第二届青年影像艺术展亮相Vinyl Café",
    "黑胶咖啡VinylCoffee",
    "gallery cafe art exhibition",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    40,
    "entity-art",
    "青年影像艺术展",
    "work",
    "",
    "VinylCoffee/article-art",
    "art exhibition",
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    40,
    "article-class",
    "wigwam/article-class",
    "WIGWAM 课程表 02/20-02/26 · 周日读书会",
    "wigwam",
    "",
    "unknown",
    "unknown",
    "",
    1,
    0,
    "ready",
    "fixture",
    100,
    0,
    "",
    "course schedule and reading salon",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(5, "entity-reading", "wigwam 周日读书会", "event", "", "article", "wigwam/article-class", 0.9, "[]", "", "", "reading salon", "{}");
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    4,
    "wigwam/article-class",
    "WIGWAM 课程表 02/20-02/26 · 周日读书会",
    "wigwam",
    "course schedule and reading salon",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    5,
    "entity-reading",
    "wigwam 周日读书会",
    "event",
    "",
    "wigwam/article-class",
    "reading salon",
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    5,
    "article-mafol",
    "DONG/article-mafol",
    "南馄北饺大决斗",
    "DONG 洞",
    "",
    "unknown",
    "unknown",
    "",
    3,
    1,
    "ready",
    "fixture",
    100,
    0,
    "",
    "DaRou GuangYu MaFoL MUYANG",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(6, "local:e2", "DaRou", "person", "", "article", "DONG/article-mafol", 1.0, "[]", "", "", "DaRou GuangYu MaFoL MUYANG", "{}");
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(7, "local:e4", "MaFoL", "person", "", "article", "DONG/article-mafol", 1.0, "[]", "", "", "DaRou GuangYu MaFoL MUYANG", "{}");
  db.prepare(
    `INSERT INTO events (
      row_pk, evid, name, place, city, time_iso, time_text, source_kind,
      source_article_uid, confidence, participants_json, organizers_json,
      vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    2,
    "local:ev1",
    "南馄北饺大决斗",
    "DONG 洞",
    "",
    "",
    "2.2-2.3",
    "article",
    "DONG/article-mafol",
    0.9,
    JSON.stringify(["DaRou", "GuangYu", "MaFoL", "MUYANG"]),
    "[]",
    "DaRou GuangYu MaFoL MUYANG",
    "{}",
  );
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    5,
    "DONG/article-mafol",
    "南馄北饺大决斗",
    "DONG 洞",
    "DaRou GuangYu MaFoL MUYANG",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    6,
    "local:e2",
    "DaRou",
    "person",
    "",
    "DONG/article-mafol",
    "DaRou GuangYu MaFoL MUYANG",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    7,
    "local:e4",
    "MaFoL",
    "person",
    "",
    "DONG/article-mafol",
    "DaRou GuangYu MaFoL MUYANG",
  );
  db.prepare("INSERT INTO event_fts(row_pk, evid, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    2,
    "local:ev1",
    "南馄北饺大决斗",
    "DONG 洞",
    "",
    "2.2-2.3",
    "DONG/article-mafol",
    "DaRou GuangYu MaFoL MUYANG",
    "DaRou GuangYu MaFoL MUYANG",
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    6,
    "article-mafol-all",
    "ALL/article-mafol",
    "ALL Club MaFoL night",
    "All俱乐部",
    "",
    "unknown",
    "unknown",
    "",
    2,
    1,
    "ready",
    "fixture",
    100,
    0,
    "",
    "MaFoL Masher at All Club",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(8, "local:e1", "MaFoL", "person", "", "article", "ALL/article-mafol", 1.0, "[]", "", "", "MaFoL Masher at All Club", "{}");
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(9, "local:e2", "Masher", "person", "", "article", "ALL/article-mafol", 0.95, "[]", "", "", "MaFoL Masher at All Club", "{}");
  db.prepare(
    `INSERT INTO events (
      row_pk, evid, name, place, city, time_iso, time_text, source_kind,
      source_article_uid, confidence, participants_json, organizers_json,
      vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    3,
    "local:ev2",
    "ALL Club MaFoL night",
    "All Club",
    "",
    "",
    "Saturday 23:00",
    "article",
    "ALL/article-mafol",
    0.9,
    JSON.stringify(["MaFoL", "Masher"]),
    "[]",
    "MaFoL Masher at All Club",
    "{}",
  );
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    6,
    "ALL/article-mafol",
    "ALL Club MaFoL night",
    "All俱乐部",
    "MaFoL Masher at All Club",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    8,
    "local:e1",
    "MaFoL",
    "person",
    "",
    "ALL/article-mafol",
    "MaFoL Masher at All Club",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    9,
    "local:e2",
    "Masher",
    "person",
    "",
    "ALL/article-mafol",
    "MaFoL Masher at All Club",
  );
  db.prepare("INSERT INTO event_fts(row_pk, evid, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    3,
    "local:ev2",
    "ALL Club MaFoL night",
    "All Club",
    "",
    "Saturday 23:00",
    "ALL/article-mafol",
    "MaFoL Masher",
    "MaFoL Masher at All Club",
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    7,
    "article-oil-main",
    "OIL/article-main",
    "OIL main room night",
    "OIL油",
    "",
    "unknown",
    "unknown",
    "Shenzhen",
    2,
    1,
    "ready",
    "fixture",
    100,
    0,
    "",
    "OIL油 main room DJ A DJ B",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(20, "local:oil1", "OIL", "organization", "Shenzhen", "article", "OIL/article-main", 1.0, JSON.stringify(["OIL油"]), "", "", "OIL油 main room", "{}");
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(21, "local:oil2", "OIL油", "organization", "Shenzhen", "article", "OIL/article-main", 0.98, "[]", "", "", "OIL油 main room", "{}");
  db.prepare(
    `INSERT INTO events (
      row_pk, evid, name, place, city, time_iso, time_text, source_kind,
      source_article_uid, confidence, participants_json, organizers_json,
      vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    20,
    "local:ev20",
    "OIL main room night",
    "OIL",
    "Shenzhen",
    "",
    "Friday 23:00",
    "article",
    "OIL/article-main",
    0.9,
    JSON.stringify(["DJ A", "DJ B"]),
    JSON.stringify(["OIL Soundsystem"]),
    "OIL油 main room DJ A DJ B",
    "{}",
  );
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    7,
    "OIL/article-main",
    "OIL main room night",
    "OIL油",
    "OIL油 main room DJ A DJ B",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    20,
    "local:oil1",
    "OIL",
    "organization",
    "Shenzhen",
    "OIL/article-main",
    "OIL油 main room",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    21,
    "local:oil2",
    "OIL油",
    "organization",
    "Shenzhen",
    "OIL/article-main",
    "OIL油 main room",
  );
  db.prepare("INSERT INTO event_fts(row_pk, evid, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    20,
    "local:ev20",
    "OIL main room night",
    "OIL",
    "Shenzhen",
    "Friday 23:00",
    "OIL/article-main",
    "DJ A DJ B",
    "OIL油 main room DJ A DJ B",
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    8,
    "article-oil-club",
    "OTHER/article-oil-club",
    "OIL Club guest night",
    "Other",
    "",
    "unknown",
    "unknown",
    "Shenzhen",
    1,
    1,
    "ready",
    "fixture",
    100,
    0,
    "",
    "OIL Club DJ C",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(22, "local:oil3", "OIL Club", "organization", "Shenzhen", "article", "OTHER/article-oil-club", 0.97, "[]", "", "", "OIL Club DJ C", "{}");
  db.prepare(
    `INSERT INTO events (
      row_pk, evid, name, place, city, time_iso, time_text, source_kind,
      source_article_uid, confidence, participants_json, organizers_json,
      vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    21,
    "local:ev21",
    "OIL Club guest night",
    "OIL Club",
    "Shenzhen",
    "",
    "Saturday 23:00",
    "article",
    "OTHER/article-oil-club",
    0.9,
    JSON.stringify(["DJ C"]),
    "[]",
    "OIL Club DJ C",
    "{}",
  );
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    8,
    "OTHER/article-oil-club",
    "OIL Club guest night",
    "Other",
    "OIL Club DJ C",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    22,
    "local:oil3",
    "OIL Club",
    "organization",
    "Shenzhen",
    "OTHER/article-oil-club",
    "OIL Club DJ C",
  );
  db.prepare("INSERT INTO event_fts(row_pk, evid, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    21,
    "local:ev21",
    "OIL Club guest night",
    "OIL Club",
    "Shenzhen",
    "Saturday 23:00",
    "OTHER/article-oil-club",
    "DJ C",
    "OIL Club DJ C",
  );
  db.prepare(
    `INSERT INTO articles (
      row_pk, article_id, article_uid, title, source_account, publish_time,
      publish_time_status, publish_time_index_status, city_label, entity_count,
      event_count, quality_grade, extract_version, input_chars, local_image_count,
      source_archived_at, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    9,
    "article-boiler",
    "OTHER/article-boiler",
    "Boiler Room night",
    "Other",
    "",
    "unknown",
    "unknown",
    "",
    1,
    1,
    "ready",
    "fixture",
    100,
    0,
    "",
    "Boiler Room DJ X",
    "{}",
  );
  db.prepare(
    `INSERT INTO entities (
      row_pk, eid, name, type, city, source_kind, source_article_uid, confidence,
      aliases_json, bio, evidence_quote, vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(23, "local:boiler1", "Boiler Room", "organization", "", "article", "OTHER/article-boiler", 0.97, "[]", "", "", "Boiler Room DJ X", "{}");
  db.prepare(
    `INSERT INTO events (
      row_pk, evid, name, place, city, time_iso, time_text, source_kind,
      source_article_uid, confidence, participants_json, organizers_json,
      vector_text_preview, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).run(
    22,
    "local:ev22",
    "Boiler Room night",
    "Boiler Room",
    "",
    "",
    "Sunday 23:00",
    "article",
    "OTHER/article-boiler",
    0.9,
    JSON.stringify(["DJ X"]),
    "[]",
    "Boiler Room DJ X",
    "{}",
  );
  db.prepare("INSERT INTO article_fts(row_pk, article_uid, title, source_account, vector_text_preview) VALUES (?, ?, ?, ?, ?)").run(
    9,
    "OTHER/article-boiler",
    "Boiler Room night",
    "Other",
    "Boiler Room DJ X",
  );
  db.prepare("INSERT INTO entity_fts(row_pk, eid, name, type, city, source_article_uid, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    23,
    "local:boiler1",
    "Boiler Room",
    "organization",
    "",
    "OTHER/article-boiler",
    "Boiler Room DJ X",
  );
  db.prepare("INSERT INTO event_fts(row_pk, evid, name, place, city, time_text, source_article_uid, participants_text, vector_text_preview) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    22,
    "local:ev22",
    "Boiler Room night",
    "Boiler Room",
    "",
    "Sunday 23:00",
    "OTHER/article-boiler",
    "DJ X",
    "Boiler Room DJ X",
  );
  db.prepare(
    `INSERT INTO identity_review_items (
      row_pk, item_id, queue, bucket, status, subject_name, subject_type, url, domain,
      source_account, source_article_uid, source_title, support_count, identity_signal_score,
      accepted_for_graph, identity_proof, graph_write_allowed, review_reason,
      next_actions_json, signals_json, raw_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    1,
    "initial:1",
    "initial_adjudication",
    "needs_more_source",
    "review_required",
    "DADA Beijing",
    "venue",
    "https://example.com/dada",
    "example.com",
    "DADA",
    "DADA/article-a",
    "DADA profile mention",
    1,
    0.5,
    0,
    0,
    0,
    "fixture needs one more source",
    JSON.stringify(["review source"]),
    "{}",
    "{}",
  );
  db.prepare("INSERT INTO map_geocode_places VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "place:dada",
    "Dada Beijing",
    "dada beijing",
    "Beijing",
    39.9042,
    116.4074,
    "geocoded_city_centroid",
    "city_centroid",
    "city_centroid",
    1,
    1,
    1,
    "DADA/article-a",
    "2026-05-21T00:00:00",
  );
  db.prepare("INSERT INTO map_geocode_review_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "review:place:unknown",
    "place:unknown",
    "Unknown Basement",
    "unknown basement",
    "medium_traffic_unresolved",
    "",
    null,
    null,
    "unresolved",
    0.1,
    "fixture unresolved place",
    8,
    2,
    1,
    "X/article-a",
    "2026-05-21T00:00:00",
    "{}",
  );
  db.prepare("INSERT INTO recommendations VALUES (?, ?, ?, ?, ?, ?, ?, ?)").run(
    1,
    "graph:dada",
    "graph_neighbor",
    "DADA Beijing",
    0.9,
    "[]",
    "{}",
    "{}",
  );
  db.prepare("INSERT INTO graph_rag_answers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    1,
    "q1",
    "DADA evidence",
    "DADA appears in the fixture.",
    1,
    1,
    "[]",
    "[]",
    "ok",
    "{}",
  );
  db.prepare("INSERT INTO runtime_reports VALUES (?, ?, ?, ?, ?, ?, ?)").run(
    1,
    "vector_collection_router_smoke",
    "",
    "fixture_vector_router_ready",
    1,
    "{}",
    JSON.stringify({ ok: true, decision: "fixture_vector_router_ready", safety: {} }),
  );
  db.close();
}

before(async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "stage7-sqlite-local-"));
  const dbPath = path.join(dir, "atlas.sqlite");
  fixtureDbPath = dbPath;
  createAtlasDb(dbPath);
  fixtureAssetDir = path.join(dir, "public-assets");
  await mkdir(fixtureAssetDir, { recursive: true });
  await writeFile(
    path.join(fixtureAssetDir, "dada.png"),
    Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=", "base64"),
  );
  fixtureAssetsPath = path.join(dir, "entity-assets.json");
  await writeFile(
    fixtureAssetsPath,
    JSON.stringify({
      entities: {
        "entity-a": {
          avatarUrl: "/atlas-assets/dada.png",
          externalLinks: [
            { label: "RA", url: "https://ra.co/clubs/dada", kind: "profile" },
            { label: "bad-js", url: "javascript:alert(1)" },
            { label: "bad-file", url: "file:///tmp/secret" },
          ],
        },
      },
    }),
  );
  for (let port = 18890; port < 18930; port += 1) {
    server = createServer({
      stage7SqliteDbPath: dbPath,
      env: {
        ATLAS_GRAPH_ENTITY_ASSETS_PATH: fixtureAssetsPath,
        ATLAS_PUBLIC_ASSET_DIR: fixtureAssetDir,
      },
      llmClient: { publicStatus: () => ({ provider: "deepseek", configured: false }) },
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
  throw new Error("No free local test port in 18890-18929.");
});

after(async () => {
  if (server) await new Promise((resolve) => server.close(resolve));
});

test("serves local SQLite status, map, search, and page", async () => {
  const statusRes = await fetch(`${baseUrl}/api/v1/stage7/local/status`);
  assert.equal(statusRes.status, 200);
  const status = await statusRes.json();
  assert.equal(status.schemaVersion, "stage7_atlas_api.local_sqlite_status.v1");
  assert.equal(status.manifest.counts.articles, 9);
  assert.equal(status.map.geocodedRows, 1);
  assert.equal(status.geocodeReview.reviewRows, 1);
  assert.equal(status.geocodeReview.actions, 0);
  assert.equal(status.geocodeReview.stateRows, 0);

  const searchRes = await fetch(`${baseUrl}/api/v1/stage7/search?q=DADA&kind=entities&limit=5`);
  assert.equal(searchRes.status, 200);
  const search = await searchRes.json();
  assert.equal(search.retrieval.mode, "sqlite_fts5_trigram");
  assert.ok(search.results.every((item) => item.kind === "entities"));
  assert.ok(search.results.some((item) => item.item.eid === "entity-a"));

  const mapRes = await fetch(`${baseUrl}/api/v1/stage7/local/map?status=geocoded_city_centroid&limit=5`);
  assert.equal(mapRes.status, 200);
  const map = await mapRes.json();
  assert.equal(map.summary.geocoded, 1);
  assert.equal(map.places[0].label, "Dada Beijing");

  const reviewRes = await fetch(`${baseUrl}/api/v1/stage7/local/geocode-review?limit=5`);
  assert.equal(reviewRes.status, 200);
  const review = await reviewRes.json();
  assert.equal(review.schemaVersion, "stage7_atlas_api.geocode_review_response.v1");
  assert.equal(review.items[0].label, "Unknown Basement");

  const pageRes = await fetch(`${baseUrl}/atlas/local`);
  assert.equal(pageRes.status, 200);
  const page = await pageRes.text();
  assert.match(page, /本地图鉴数据库/);
  assert.match(page, /\/api\/v1\/stage7\/local\/status/);
  assert.match(page, /\/api\/v1\/stage7\/local\/geocode-review/);
});

test("serves bounded Atlas graph explorer and read-only graph API", async () => {
  const pageRes = await fetch(`${baseUrl}/atlas/graph`);
  assert.equal(pageRes.status, 200);
  const page = await pageRes.text();
  assert.match(page, /坏DJ Atlas/);
  assert.match(page, /搜 DJ \/ 场地 \/ 厂牌 \/ 活动 \/ mixtape/);
  assert.match(page, /常用入口/);
  assert.match(page, /Focus 3D/);
  assert.match(page, /Overview GPU/);
  assert.match(page, /信息来源/);
  assert.match(page, /关系探索/);
  assert.match(page, /DJ 关系/);
  assert.match(page, /Cosmos\.gl GPU Overview/);
  assert.match(page, /\/api\/v1\/atlas\/session\/fallback-challenge/);
  assert.match(page, /备用验证/);
  assert.match(page, /timeout-callback/);
  assert.doesNotMatch(page, /LDR Prompt/);
  assert.doesNotMatch(page, /sourcepack/);
  assert.doesNotMatch(page, /高频同台/);
  assert.doesNotMatch(page, /<option value="entities">Entities<\/option>/);
  assert.match(page, /\/api\/v1\/stage7\/graph\/seed/);

  const seedRes = await fetch(`${baseUrl}/api/v1/stage7/graph/seed?q=DADA&limit=20&lod=overview`);
  assert.equal(seedRes.status, 200);
  const seed = await seedRes.json();
  assert.equal(seed.schemaVersion, "stage7_atlas_api.graph_response.v1");
  assert.equal(seed.meta.schemaVersion, "stage7_atlas_graph_viewport.v2");
  assert.equal(seed.meta.lod, "overview");
  assert.equal(seed.meta.safety.rawDbExposed, false);
  assert.equal(seed.ldrSourcePack.mode, "source_pack_only");
  assert.equal(seed.mode, "seed");
  assert.equal(seed.safety.sqliteWriteExecuted, false);
  assert.equal(seed.safety.bulkExportEnabled, false);
  const entityNode = seed.nodes.find((node) => node.id === "entities:entity-a");
  assert.ok(entityNode);
  assert.equal(entityNode.role, "seed");
  assert.equal(entityNode.clusterId, "cluster:venue");
  assert.equal(entityNode.publicState, "public_rollup");
  assert.ok(entityNode.metrics);
  assert.equal(entityNode.visual.avatarUrl, "/atlas-assets/dada.png");
  assert.match(entityNode.visual.color, /^#/);
  assert.equal(entityNode.externalLinks.length, 1);
  assert.equal(entityNode.externalLinks[0].url, "https://ra.co/clubs/dada");
  assert.ok(seed.nodes.some((node) => node.id === "events:event-a"));
  const seedEdge = seed.edges.find((edge) => edge.source === "entities:entity-a" || edge.target === "entities:entity-a");
  assert.ok(seedEdge);
  assert.equal(typeof seedEdge.evidenceCount, "number");
  assert.deepEqual(seedEdge.sampleEvidenceIds, []);

  const detailRes = await fetch(`${baseUrl}/api/v1/stage7/entities/entity-a`);
  assert.equal(detailRes.status, 200);
  const detail = await detailRes.json();
  assert.equal(detail.visual.avatarUrl, "/atlas-assets/dada.png");
  assert.equal(detail.externalLinks.length, 1);

  const assetRes = await fetch(`${baseUrl}/atlas-assets/dada.png`);
  assert.equal(assetRes.status, 200);
  assert.match(assetRes.headers.get("content-type") || "", /image\/png/);

  const blockedAssetRes = await fetch(`${baseUrl}/atlas-assets/${encodeURIComponent("../secret.txt")}`);
  assert.equal(blockedAssetRes.status, 403);

  const subgraphRes = await fetch(`${baseUrl}/api/v1/stage7/graph/subgraph?nodeId=entities%3Aentity-a&limit=20`);
  assert.equal(subgraphRes.status, 200);
  const subgraph = await subgraphRes.json();
  assert.equal(subgraph.mode, "subgraph");
  assert.equal(subgraph.meta.schemaVersion, "stage7_atlas_graph_viewport.v2");
  assert.equal(subgraph.seed.nodeId, "entities:entity-a");
  assert.ok(subgraph.nodes.some((node) => node.id === "events:event-a"));
  assert.ok(subgraph.edges.some((edge) => edge.kind === "same_article"));

  const walkRes = await fetch(`${baseUrl}/api/v1/stage7/graph/random-walk?nodeId=entities%3Aentity-a&steps=3&fanout=5&limit=30`);
  assert.equal(walkRes.status, 200);
  const walk = await walkRes.json();
  assert.equal(walk.mode, "random_walk");
  assert.ok(walk.limits.returnedNodes > 0);
  assert.ok(walk.limits.returnedNodes <= 30);
});

test("prioritizes exact entity graph search and scopes local atlas ids by source article", async () => {
  const searchRes = await fetch(`${baseUrl}/api/v1/stage7/search?q=MaFoL&kind=entities&limit=5`);
  assert.equal(searchRes.status, 200);
  const search = await searchRes.json();
  assert.equal(search.results[0].title, "MaFoL");

  const seedRes = await fetch(`${baseUrl}/api/v1/stage7/graph/seed?q=MaFoL&limit=40`);
  assert.equal(seedRes.status, 200);
  const seed = await seedRes.json();
  const mafol = seed.nodes.find((node) => node.label === "MaFoL");
  assert.ok(mafol);
  assert.match(mafol.id, /^entities:src:/);
  assert.match(mafol.primaryId, /^src:/);
  assert.equal(seed.nodes[0].label, "MaFoL");

  const detailRes = await fetch(`${baseUrl}/api/v1/stage7/entities/${encodeURIComponent(mafol.primaryId)}?relatedLimit=10`);
  assert.equal(detailRes.status, 200);
  const detail = await detailRes.json();
  assert.equal(detail.item.name, "MaFoL");
  assert.equal(detail.matchedBy, "source_article_uid+eid");

  const subgraphRes = await fetch(`${baseUrl}/api/v1/stage7/graph/subgraph?nodeId=${encodeURIComponent(mafol.id)}&limit=40`);
  assert.equal(subgraphRes.status, 200);
  const subgraph = await subgraphRes.json();
  assert.equal(subgraph.seed.label, "MaFoL");
});

test("reads DJ-first Atlas serving read model for graph windows and profiles", async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), "atlas-serving-store-"));
  const servingDbPath = path.join(tmp, "atlas_serving.sqlite");
  const db = new Database(servingDbPath);
  db.exec(`
    CREATE TABLE search_document (
      doc_rowid INTEGER PRIMARY KEY,
      subject_id TEXT,
      subject_type TEXT,
      display_name TEXT,
      normalized_name TEXT,
      aliases_text TEXT,
      city_text TEXT,
      taxon_path TEXT,
      rank_score REAL,
      last_seen_at TEXT,
      public_state TEXT,
      search_text TEXT
    );
    CREATE VIRTUAL TABLE search_document_fts USING fts5(search_text);
    CREATE TABLE dj_profile (
      dj_id TEXT PRIMARY KEY,
      display_name TEXT,
      normalized_name TEXT,
      aliases_json TEXT,
      city_primary TEXT,
      avatar_asset_id TEXT,
      source_article_count INTEGER,
      event_count INTEGER,
      venue_count INTEGER,
      collaborator_count INTEGER,
      organization_count INTEGER,
      media_count INTEGER,
      first_seen_at TEXT,
      last_seen_at TEXT,
      confidence REAL
    );
    CREATE TABLE performance_event (
      event_id TEXT PRIMARY KEY,
      event_title TEXT,
      starts_at TEXT,
      time_text TEXT,
      venue_id TEXT,
      venue_name TEXT,
      city TEXT,
      source_ref_id TEXT,
      participant_count INTEGER,
      organizer_count INTEGER,
      confidence REAL
    );
    CREATE TABLE dj_event (
      dj_id TEXT,
      event_id TEXT,
      starts_at TEXT,
      time_text TEXT,
      event_title TEXT,
      venue_id TEXT,
      venue_name TEXT,
      city TEXT,
      source_ref_id TEXT,
      confidence REAL
    );
    CREATE TABLE dj_relation_rollup (
      src_dj_id TEXT,
      dst_dj_id TEXT,
      same_event_count INTEGER,
      same_label_count INTEGER,
      same_venue_count INTEGER,
      same_source_context_count INTEGER,
      source_diversity INTEGER,
      first_seen_at TEXT,
      last_seen_at TEXT,
      relation_score REAL,
      relation_label_zh TEXT,
      sample_evidence_json TEXT,
      public_state TEXT
    );
    CREATE TABLE dj_venue_rollup (
      dj_id TEXT,
      venue_id TEXT,
      venue_name TEXT,
      city TEXT,
      event_count INTEGER,
      first_seen_at TEXT,
      last_seen_at TEXT,
      score REAL
    );
    CREATE TABLE dj_org_rollup (
      dj_id TEXT,
      org_id TEXT,
      org_name TEXT,
      org_type TEXT,
      evidence_count INTEGER,
      score REAL,
      sample_evidence_json TEXT
    );
    CREATE TABLE evidence_ref (
      source_ref_id TEXT PRIMARY KEY,
      source_hash TEXT,
      source_account TEXT,
      source_title TEXT,
      post_date TEXT,
      public_snippet TEXT,
      source_kind TEXT,
      public_url_allowed INTEGER
    );
    CREATE TABLE activity_event_detail (
      event_id TEXT PRIMARY KEY,
      source_event_id TEXT,
      publish_package TEXT,
      title TEXT,
      event_date_start TEXT,
      event_date_end TEXT,
      event_time_text TEXT,
      time_start TEXT,
      time_end TEXT,
      venue_name TEXT,
      venue_id TEXT,
      address TEXT,
      city_name TEXT,
      lineup_artists_json TEXT,
      music_styles_json TEXT,
      genres_json TEXT,
      price_json TEXT,
      ticketing_text TEXT,
      source_ref_id TEXT,
      source_hash TEXT,
      source_account_name TEXT,
      source_published_at TEXT,
      generated_at TEXT
    );
    CREATE TABLE activity_evidence_ref (
      evidence_ref_id TEXT PRIMARY KEY,
      event_id TEXT,
      field_path TEXT,
      field_value TEXT,
      support_type TEXT,
      source_kind TEXT,
      source_ref_id TEXT,
      source_hash TEXT,
      source_account_name TEXT,
      source_published_at TEXT,
      quote TEXT,
      quote_policy TEXT,
      ocr_span_id TEXT,
      ocr_span_status TEXT,
      confidence REAL,
      created_at TEXT
    );
    CREATE TABLE graph_window_cache (
      window_key TEXT PRIMARY KEY,
      seed_subject_id TEXT,
      lens TEXT,
      depth INTEGER,
      node_count INTEGER,
      edge_count INTEGER,
      nodes_json TEXT,
      edges_json TEXT,
      generated_at TEXT
    );
  `);
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    1,
    "dj:mafol",
    "dj",
    "MaFoL",
    "mafol",
    "MaFoL Mafol",
    "上海",
    "音乐人/DJ",
    100,
    "2026-05-01",
    "public_rollup",
    "MaFoL 上海 DJ",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(1, "MaFoL 上海 DJ");
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    40,
    "venue:all",
    "venue",
    "ALL",
    "all",
    "ALL ALL俱乐部",
    "上海",
    "场地/俱乐部",
    90,
    "2026-05-01",
    "public_rollup",
    "ALL 上海 俱乐部 场地 venue",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(40, "ALL 上海 俱乐部 场地 venue");
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    43,
    "event:all-noise",
    "event",
    "AllAll乱叫",
    "allall乱叫",
    "",
    "上海",
    "活动/演出",
    5000,
    "2026-05-01",
    "public_rollup",
    "ALL AllAll乱叫 上海 活动",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(43, "ALL AllAll乱叫 上海 活动");
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    41,
    "event:b",
    "event",
    "深圳 Bass Night",
    "深圳 bass night",
    "",
    "深圳",
    "活动/演出",
    80,
    "2026-05-02",
    "public_rollup",
    "深圳 Bass Night OIL Club 深圳",
  );
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    42,
    "event:c",
    "event",
    "岜沙 Bass Night",
    "岜沙 bass night",
    "",
    "岜沙",
    "活动/演出",
    70,
    "2026-05-03",
    "public_rollup",
    "岜沙 Bass Night 岜沙",
  );
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    7,
    "venue:oil",
    "venue",
    "OIL",
    "oil",
    "OIL OIL油 OIL Club",
    "深圳",
    "场地/俱乐部",
    2000,
    "2026-05-02",
    "public_rollup",
    "OIL OIL油 OIL Club 深圳 俱乐部 venue",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(7, "OIL OIL油 OIL Club 深圳 俱乐部 venue");
  db.prepare("INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "dj:mafol",
    "MaFoL",
    "mafol",
    "[\"MaFoL\",\"Mafol\"]",
    "上海",
    "",
    3,
    2,
    1,
    1,
    1,
    0,
    "2024-01-01",
    "2026-05-01",
    0.9,
  );
  db.prepare("INSERT INTO performance_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "event:a",
    "MaFoL Night",
    "2026-05-01",
    "5月1日",
    "venue:all",
    "ALL",
    "上海",
    "src:a",
    2,
    1,
    0.95,
  );
  db.prepare("INSERT INTO performance_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "event:b",
    "深圳 Bass Night",
    "2026-05-02",
    "5月2日",
    "venue:oil-shenzhen",
    "OIL Club",
    "深圳",
    "src:b",
    1,
    1,
    0.9,
  );
  db.prepare("INSERT INTO performance_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "event:c",
    "岜沙 Bass Night",
    "2026-05-03",
    "5月3日",
    "venue:basha",
    "岜沙 Warehouse",
    "岜沙",
    "src:c",
    1,
    1,
    0.9,
  );
  db.prepare("INSERT INTO dj_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run("dj:mafol", "event:a", "2026-05-01", "5月1日", "MaFoL Night", "venue:all", "ALL", "上海", "src:a", 0.95);
  db.prepare("INSERT INTO dj_relation_rollup VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run("dj:mafol", "dj:darou", 2, 0, 1, 2, 1, "2026-05-01", "2026-05-01", 9, "高频同台", "[]", "public_rollup");
  db.prepare("INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run("dj:darou", "DaRou", "darou", "[\"DaRou\"]", "上海", "", 1, 2, 1, 1, 0, 0, "2026-05-01", "2026-05-01", 0.9);
  db.prepare("INSERT INTO dj_venue_rollup VALUES (?, ?, ?, ?, ?, ?, ?, ?)").run("dj:mafol", "venue:all", "ALL", "上海", 2, "2026-05-01", "2026-05-01", 6);
  db.prepare("INSERT INTO dj_org_rollup VALUES (?, ?, ?, ?, ?, ?, ?)").run("dj:mafol", "org:crew", "Test Crew", "organizer", 2, 4, "[]");
  db.prepare("INSERT INTO evidence_ref VALUES (?, ?, ?, ?, ?, ?, ?, ?)").run("src:a", "hash", "ALL俱乐部", "MaFoL Night", "2026-05-01", "snippet", "wechat", 0);
  db.prepare("INSERT INTO activity_event_detail VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "event:a",
    "weekly:item-a",
    "weekly-current-test",
    "MaFoL Night",
    "2026-05-01",
    "2026-05-01",
    "20:30 - Late",
    "20:30",
    "",
    "ALL",
    "all-shanghai",
    "上海市测试路1号",
    "上海",
    JSON.stringify(["MaFoL", "DaRou"]),
    JSON.stringify(["house"]),
    JSON.stringify(["house"]),
    JSON.stringify(["Door 70"]),
    "Door 70",
    "src:a",
    "sha256:source",
    "ALL俱乐部",
    "2026-05-01",
    "2026-05-22T00:00:00Z",
  );
  db.prepare("INSERT INTO activity_evidence_ref VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "eref:a",
    "event:a",
    "ticketing_text",
    "Door 70",
    "source_text",
    "wechat_article",
    "src:a",
    "sha256:source",
    "ALL俱乐部",
    "2026-05-01",
    "Door 70",
    "short_quote_sanitized_240_chars",
    "",
    "not_available_in_current_api",
    0.92,
    "2026-05-22T00:00:00Z",
  );
  db.prepare("INSERT INTO graph_window_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "window:mafol",
    "dj:mafol",
    "dj_core",
    2,
    3,
    2,
    JSON.stringify([
      { id: "dj:mafol", type: "dj", label: "MaFoL", role: "seed" },
      { id: "dj:darou", type: "dj", label: "DaRou", role: "collaborator" },
      { id: "event:a", type: "event", label: "MaFoL Night", city: "上海", starts_at: "2026-05-01" },
    ]),
    JSON.stringify([
      { id: "rel:mafol:darou", source: "dj:mafol", target: "dj:darou", type: "dj_collaboration", label: "高频同台", weight: 9 },
      { id: "played:mafol:event-a", source: "dj:mafol", target: "event:a", type: "performed_at", weight: 3 },
    ]),
    "2026-05-22T00:00:00",
  );
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    2,
    "org:loopy",
    "organizer",
    "Loopy",
    "loopy",
    "LOOPY Loopy loopy",
    "",
    "厂牌/Crew/主办",
    3000,
    "",
    "public_rollup",
    "Loopy 厂牌 crew 主办",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(2, "Loopy 厂牌 crew 主办");
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    4,
    "venue:loopy-club",
    "venue",
    "loopy Club",
    "loopy club",
    "loopy Club",
    "杭州",
    "场地/俱乐部",
    120,
    "2024-09-12",
    "public_rollup",
    "loopy Club 杭州 俱乐部 场地 club venue",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(4, "loopy Club 杭州 俱乐部 场地");
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    5,
    "org:loopy-club",
    "organizer",
    "LOOPY俱乐部",
    "loopy俱乐部",
    "LOOPY俱乐部 Loopy俱乐部",
    "",
    "厂牌/Crew/主办",
    60,
    "",
    "public_rollup",
    "LOOPY俱乐部 厂牌 crew 主办",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(5, "LOOPY俱乐部 厂牌 crew 主办");
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    6,
    "org:hangzhou-loopy",
    "organizer",
    "杭州 Loopy",
    "杭州 loopy",
    "杭州 Loopy",
    "",
    "厂牌/Crew/主办",
    90,
    "",
    "public_rollup",
    "杭州 Loopy 厂牌 crew 主办",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(6, "杭州 Loopy 厂牌 crew 主办");
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    3,
    "dj:akkoii",
    "dj",
    "akkoii [loopy]",
    "akkoii [loopy]",
    "akkoii [loopy]",
    "杭州",
    "音乐人/DJ",
    30,
    "2024-09-12",
    "public_rollup",
    "akkoii [loopy] 杭州 DJ",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(3, "akkoii [loopy] 杭州 DJ");
  db.prepare("INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run("dj:akkoii", "akkoii [loopy]", "akkoii [loopy]", "[\"akkoii [loopy]\"]", "杭州", "", 1, 1, 1, 0, 1, 0, "2024-09-12", "2024-09-12", 0.9);
  db.prepare("INSERT INTO dj_org_rollup VALUES (?, ?, ?, ?, ?, ?, ?)").run("dj:mafol", "org:loopy", "Loopy", "organizer", 4, 8, JSON.stringify(["src:a"]));
  db.prepare("INSERT INTO graph_window_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "window:akkoii",
    "dj:akkoii",
    "dj_core",
    2,
    1,
    0,
    JSON.stringify([{ id: "dj:akkoii", type: "dj", label: "akkoii [loopy]", role: "seed" }]),
    "[]",
    "2026-05-22T00:00:00",
  );
  // Phase 2 fixture: 一个 0 直接同台的「薄星」DJ，靠同场馆/同厂牌 2-hop 回填邻居。
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    99, "dj:thinny", "dj", "Thinny", "thinny", "Thinny", "上海", "音乐人/DJ", 20, "2026-05-01", "public_rollup", "Thinny 上海 DJ",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(99, "Thinny 上海 DJ");
  db.prepare("INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run("dj:thinny", "Thinny", "thinny", "[\"Thinny\"]", "上海", "", 1, 1, 1, 0, 1, 0, "2026-05-01", "2026-05-01", 0.8);
  db.prepare("INSERT INTO dj_venue_rollup VALUES (?, ?, ?, ?, ?, ?, ?, ?)").run("dj:thinny", "venue:thinroom", "Thin Room", "上海", 3, "2026-05-01", "2026-05-01", 5);
  db.prepare("INSERT INTO dj_venue_rollup VALUES (?, ?, ?, ?, ?, ?, ?, ?)").run("dj:darou", "venue:thinroom", "Thin Room", "上海", 5, "2026-05-01", "2026-05-01", 7);
  db.prepare("INSERT INTO dj_org_rollup VALUES (?, ?, ?, ?, ?, ?, ?)").run("dj:thinny", "org:thinlabel", "Thin Label", "label", 2, 4, "[]");
  db.prepare("INSERT INTO dj_org_rollup VALUES (?, ?, ?, ?, ?, ?, ?)").run("dj:akkoii", "org:thinlabel", "Thin Label", "label", 4, 8, "[]");
  db.close();

  const soundSystemEvidencePath = path.join(tmp, "venue_sound_system_evidence.jsonl");
  const entityMergeGroupsPath = path.join(tmp, "entity_merge_groups_report_only.jsonl");
  await writeFile(
    soundSystemEvidencePath,
    JSON.stringify({
      venueId: "venue:all",
      venueName: "ALL",
      city: "上海",
      evidenceCount: 2,
      sourceCount: 1,
      terms: ["Funktion-One", "sound system"],
      confidence: 0.91,
      evidence: [
        {
          sourceRefId: "src:a",
          sourceAccount: "ALL俱乐部",
          sourceTitle: "ALL 音响系统",
          postDate: "2026-05-01",
          eventId: "event:a",
          eventTitle: "MaFoL Night",
          matchedTerms: ["Funktion-One", "sound system"],
          publicSnippet: "Funktion-One sound system",
        },
      ],
      reportOnly: true,
    })
      + "\n",
    "utf8",
  );
  const oilMergeMembers = [
    { subject_id: "venue:oil", subject_type: "venue", display_name: "OIL", city_text: "深圳", rank_score: 2000 },
    { subject_id: "venue:oil-shenzhen", subject_type: "venue", display_name: "OIL油", city_text: "深圳", rank_score: 1900 },
    { subject_id: "venue:oil-club", subject_type: "venue", display_name: "OIL Club", city_text: "深圳", rank_score: 1800 },
    ...Array.from({ length: 140 }, (_, index) => ({
      subject_id: `venue:oil-alias-${index + 1}`,
      subject_type: "venue",
      display_name: `OIL Alias ${index + 1}`,
      city_text: "深圳",
      rank_score: 1000 - index,
    })),
  ];
  await writeFile(
    entityMergeGroupsPath,
    [
      {
        group_id: "entity-merge-group:org:loopy",
        canonical_subject_id: "org:loopy",
        canonical_name: "Loopy",
        member_count: 4,
        members: [
          { subject_id: "org:loopy", subject_type: "organizer", display_name: "Loopy", city_text: "", rank_score: 3042 },
          { subject_id: "venue:loopy-club", subject_type: "venue", display_name: "loopy Club", city_text: "杭州", rank_score: 120 },
          { subject_id: "org:loopy-club", subject_type: "organizer", display_name: "LOOPY俱乐部", city_text: "", rank_score: 60 },
          { subject_id: "org:hangzhou-loopy", subject_type: "organizer", display_name: "杭州 Loopy", city_text: "", rank_score: 90 },
        ],
        source_decision_count: 2,
        confidence_min: 0.9,
        confidence_avg: 0.94,
        risk_flags: ["mixed_type_merge"],
        report_only: true,
      },
      {
        group_id: "entity-merge-group:venue:all",
        canonical_subject_id: "venue:all",
        canonical_name: "ALL",
        member_count: 3,
        members: [
          { subject_id: "venue:all", subject_type: "venue", display_name: "ALL", city_text: "上海", rank_score: 1000 },
          { subject_id: "org:all-club", subject_type: "organizer", display_name: "ALL Club", city_text: "上海", rank_score: 200 },
          { subject_id: "org:all-cn", subject_type: "organizer", display_name: "All俱乐部", city_text: "上海", rank_score: 180 },
        ],
        source_decision_count: 2,
        confidence_min: 0.91,
        confidence_avg: 0.93,
        risk_flags: ["mixed_type_merge"],
        report_only: true,
      },
      {
        group_id: "entity-merge-group:venue:oil",
        canonical_subject_id: "venue:oil",
        canonical_name: "OIL",
        member_count: oilMergeMembers.length,
        members: oilMergeMembers,
        source_decision_count: 24,
        confidence_min: 0.9,
        confidence_avg: 0.95,
        risk_flags: ["large_alias_group", "ocr_confusable"],
        report_only: true,
      },
    ].map((row) => JSON.stringify(row)).join("\n") + "\n",
    "utf8",
  );

  const store = new Stage7AtlasSqliteStore({
    env: {
      ATLAS_SERVING_SQLITE_DB: servingDbPath,
      ATLAS_SQLITE_READONLY: "1",
      ATLAS_VENUE_SOUND_SYSTEM_EVIDENCE_PATH: soundSystemEvidencePath,
      ATLAS_ENTITY_MERGE_GROUPS_PATH: entityMergeGroupsPath,
    },
  });
  const seed = await store.getGraphSeed({ q: "MaFoL", limit: 20 });
  assert.equal(seed.retrieval.mode, "atlas_serving_graph_window_cache");
  assert.ok(seed.nodes.some((node) => node.id === "entities:dj:mafol" && node.subtype === "dj"));
  assert.ok(seed.edges.some((edge) => edge.kind === "dj_collaboration"));
  assert.equal(seed.meta.schemaVersion, "stage7_atlas_graph_viewport.v2");
  assert.equal(seed.meta.lens, "dj_core");
  assert.equal(seed.meta.lod, "focus");
  assert.equal(seed.meta.counts.nodes, 3);
  assert.equal(seed.meta.counts.edges, 2);
  assert.equal(seed.meta.truncation.nodesTruncated, false);
  assert.equal(seed.meta.safety.rawDbExposed, false);
  const seedNode = seed.nodes.find((node) => node.id === "entities:dj:mafol");
  assert.equal(seedNode.role, "seed");
  assert.equal(seedNode.clusterId, "cluster:dj");
  assert.equal(seedNode.publicState, "public_rollup");
  assert.equal(seedNode.name, "MaFoL");
  assert.equal(seedNode.type, "dj");
  assert.equal(typeof seedNode.score, "number");
  assert.equal(typeof seedNode.events, "number");
  assert.equal(typeof seedNode.links, "number");
  assert.ok(seedNode.score > 0);
  assert.ok(seedNode.links > 0);
  assert.equal(seedNode.metrics.relationCount, seedNode.links);
  assert.ok(Array.isArray(seedNode.timeline));
  assert.equal(seedNode.metrics.degreeHint >= 0, true);
  assert.equal(seedNode.visual.color.startsWith("#"), true);
  const collaborationEdge = seed.edges.find((edge) => edge.kind === "dj_collaboration");
  assert.equal(collaborationEdge.label, "DJ 关系");
  assert.equal(collaborationEdge.type, "dj_collaboration");
  assert.equal(collaborationEdge.relation, "dj_collaboration");
  assert.equal(collaborationEdge.relationshipScore, 9);
  assert.equal(collaborationEdge.metrics.relationshipScore, 9);
  assert.equal(typeof collaborationEdge.width, "number");
  assert.equal(collaborationEdge.evidenceCount, 0);
  assert.deepEqual(collaborationEdge.sampleEvidenceIds, []);
  assert.equal(collaborationEdge.publicState, "public_rollup");
  assert.equal(seed.ldrSourcePack.mode, "source_pack_only");
  assert.match(seed.ldrSourcePack.prompt, /MaFoL/);

  const profile = await store.getGraphEntityProfile({ id: "dj:mafol", eventLimit: 5, collaboratorLimit: 5, venueLimit: 5 });
  assert.equal(profile.found, true);
  assertNoPublicAtlasLeak(profile);
  assert.equal(profile.canonical.name, "MaFoL");
  assert.equal(profile.summary.eventCount, 2);
  assert.ok(profile.history.events.some((row) => row.name === "MaFoL Night" && row.ticketing_text === "Door 70"));
  assert.ok(profile.relationships.collaborators.some((row) => row.label === "DaRou"));
  assert.ok(profile.relationships.collaborators.some((row) => row.label === "DaRou" && row.relationshipScore === 9));
  assert.ok(profile.relationships.collaborators.every((row) => !Object.hasOwn(row, "count")));
  assert.ok(profile.sources.articles.some((row) => row.public_snippet === "snippet"));
  assert.equal(profile.attributes.soundSystemSummary.available, false);

  // Phase 2: 薄星（0 直接同台）靠同场馆/同厂牌 2-hop 回填出可继续探索的邻居，避免死胡同。
  const thinProfile = await store.getGraphEntityProfile({ id: "dj:thinny", collaboratorLimit: 10, venueLimit: 5 });
  assert.equal(thinProfile.found, true);
  const thinCollabs = thinProfile.relationships.collaborators;
  const venuePeer = thinCollabs.find((row) => row.label === "DaRou");
  assert.ok(venuePeer && venuePeer.sameVenueCount > 0, "同场馆 2-hop 回填出邻居");
  const labelPeer = thinCollabs.find((row) => row.label === "akkoii [loopy]");
  assert.ok(labelPeer && labelPeer.sameLabelCount > 0, "同厂牌 2-hop 回填出邻居");
  assert.equal(venuePeer.relationshipScore, 0, "回填项是弱连接，relationshipScore=0 排在真实同台之后");

  const venueProfile = await store.getGraphEntityProfile({ id: "venue:all", eventLimit: 5, collaboratorLimit: 5 });
  assert.equal(venueProfile.found, true);
  assertNoPublicAtlasLeak(venueProfile);
  assert.equal(venueProfile.canonical.name, "ALL");
  assert.equal(venueProfile.attributes.soundSystemSummary.available, true);
  assert.ok(venueProfile.attributes.soundSystemEvidence[0].terms.includes("Funktion-One"));
  assert.equal(venueProfile.attributes.soundSystemEvidence[0].evidence[0].sourceRefId, "src:a");

  const mobileVenueProfile = await store.getGraphMobileProfile({ id: "venue:all", eventLimit: 5, collaboratorLimit: 5 });
  assert.equal(mobileVenueProfile.schemaVersion, "stage7_atlas_api.graph_mobile_profile.v1");
  assertNoPublicAtlasLeak(mobileVenueProfile);
  assert.equal(mobileVenueProfile.header.title, "ALL");
  assert.equal(mobileVenueProfile.payloadPolicy.target, "wechat_miniprogram");
  assert.equal(mobileVenueProfile.payloadPolicy.fullGraphExport, false);
  assert.equal(mobileVenueProfile.entityMerge.available, true);
  assert.ok(mobileVenueProfile.entityMerge.aliases.some((row) => row.name === "All俱乐部" && row.tap.action === "open_entity_profile"));
  assert.ok(mobileVenueProfile.quickActions.some((row) => row.action === "open_graph_seed" && row.apiPath.includes("limit=48")));
  const soundSection = mobileVenueProfile.sections.find((row) => row.id === "sound_system");
  assert.equal(soundSection.summary.available, true);
  assert.equal(soundSection.items[0].evidence[0].tap.action, "open_source_evidence");

  const mobileAllQueryProfile = await store.getGraphMobileProfile({ q: "ALL", eventLimit: 5, collaboratorLimit: 5 });
  assert.equal(mobileAllQueryProfile.found, true);
  assert.equal(mobileAllQueryProfile.header.title, "ALL");
  assert.equal(mobileAllQueryProfile.header.primaryId, "venue:all");
  assertNoPublicAtlasLeak(mobileAllQueryProfile);

  const mobileLoopyProfile = await store.getGraphMobileProfile({ q: "Loopy", eventLimit: 5, collaboratorLimit: 5 });
  assert.equal(mobileLoopyProfile.header.title, "Loopy");
  assertNoPublicAtlasLeak(mobileLoopyProfile);
  assert.equal(mobileLoopyProfile.entityMerge.available, true);
  assert.equal(mobileLoopyProfile.retrieval.entityMergeSidecarEnabled, true);
  assert.ok(mobileLoopyProfile.entityMerge.aliases.some((row) => row.name === "LOOPY俱乐部"));
  assert.ok(!mobileLoopyProfile.entityMerge.aliases.some((row) => row.name === "akkoii [loopy]"));
  const loopyRelationshipSection = mobileLoopyProfile.sections.find((row) => row.id === "relationships");
  assert.ok(loopyRelationshipSection.items.some((row) => row.label === "MaFoL" && row.relationshipScore === 8));
  const loopyHistorySection = mobileLoopyProfile.sections.find((row) => row.id === "history");
  assert.ok(loopyHistorySection.items.some((row) => row.title === "MaFoL Night"));
  const mobileLoopyAliasProfile = await store.getGraphMobileProfile({ id: "venue:loopy-club", eventLimit: 5, collaboratorLimit: 5 });
  assert.equal(mobileLoopyAliasProfile.header.title, "Loopy");
  assert.equal(mobileLoopyAliasProfile.header.primaryId, "org:loopy");
  assert.ok(mobileLoopyAliasProfile.header.stats.some((row) => row.label === "关系" && row.value > 0));

  const mobileOilProfile = await store.getGraphMobileProfile({ q: "OIL油", eventLimit: 5, collaboratorLimit: 5 });
  assert.equal(mobileOilProfile.header.title, "OIL");
  assertNoPublicAtlasLeak(mobileOilProfile);
  assert.equal(mobileOilProfile.entityMerge.memberCount, oilMergeMembers.length);
  assert.equal(mobileOilProfile.retrieval.entityMergePlan.aggregationTruncated, true);
  assert.ok(mobileOilProfile.retrieval.entityMergePlan.aggregationMemberCount <= 96);
  assert.ok(mobileOilProfile.sections.find((row) => row.id === "history").items.some((row) => row.title === "深圳 Bass Night"));

  const eventFamilyProfile = await store.getAtlasFamilyProfile({ id: "event:a", eventLimit: 5, collaboratorLimit: 5 });
  assert.equal(eventFamilyProfile.schemaVersion, "atlas.family_profile.v1");
  assert.equal(eventFamilyProfile.found, true);
  assert.equal(eventFamilyProfile.center.kind, "event");
  assert.equal(eventFamilyProfile.sections.explore.title, "以活动为中心");
  assert.deepEqual(eventFamilyProfile.sections.explore.rings.slice(0, 2).map((row) => row.id), ["relatedDjs", "clubs"]);
  assert.ok(eventFamilyProfile.sections.relatedDjs.items.some((row) => row.label === "MaFoL" && row.relationshipScore > 0));
  assert.ok(eventFamilyProfile.sections.clubs.items.some((row) => row.label === "ALL"));
  assertNoPublicAtlasLeak(eventFamilyProfile);

  const detail = await store.getDetail("events", "event:a", { relatedLimit: 5 });
  assert.equal(detail.item.ticketing_text, "Door 70");
  assert.deepEqual(detail.item.participants, ["MaFoL", "DaRou"]);
  assert.equal(detail.item.activity.sourceHash, "sha256:source");
  assert.equal(detail.activityEvidence[0].field_path, "ticketing_text");
  assert.equal(detail.activityEvidence[0].quote, "Door 70");

  const loopySeed = await store.getGraphSeed({ q: "Loopy", limit: 30 });
  assert.equal(loopySeed.seed.primaryId, "org:loopy");
  assertNoPublicAtlasLeak(loopySeed);
  assert.equal(loopySeed.seed.label, "Loopy");
  assert.equal(loopySeed.retrieval.mode, "atlas_serving_subject_graph");
  assert.equal(loopySeed.retrieval.exactEntitySeeded, true);
  assert.ok(loopySeed.nodes.some((node) => node.primaryId === "dj:mafol"));
  assert.ok(loopySeed.edges.some((edge) => edge.kind === "organized_by"));
  assert.ok(!loopySeed.nodes.some((node) => node.primaryId === "dj:akkoii" && node.seed));
  for (const alias of ["Loopy俱乐部", "loopy Club", "杭州 Loopy"]) {
    const aliasSeed = await store.getGraphSeed({ q: alias, limit: 30 });
    assert.equal(aliasSeed.seed.primaryId, "org:loopy");
    assert.equal(aliasSeed.seed.label, "Loopy");
    assert.equal(aliasSeed.retrieval.aliasExpanded, true);
  }
  const aliasSearch = await store.search({ q: "Loopy俱乐部", limit: 5 });
  assert.equal(aliasSearch.results[0].item.eid, "org:loopy");
  assert.equal(aliasSearch.retrieval.entityMergeOverlayEnabled, true);

  const shortCitySearch = await store.search({ q: "深圳", kind: "events", limit: 5 });
  assert.ok(shortCitySearch.results.some((row) => row.item.evid === "event:b"));
  assert.equal(shortCitySearch.results.find((row) => row.item.evid === "event:b").item.city, "深圳");
  const shortCjkCitySearch = await store.search({ q: "岜沙", kind: "events", limit: 5 });
  assert.ok(shortCjkCitySearch.results.some((row) => row.item.evid === "event:c"));
  assert.equal(shortCjkCitySearch.results.find((row) => row.item.evid === "event:c").item.city, "岜沙");
});

test("serving search falls back to unicode companion FTS when legacy trigram misses", async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), "atlas-serving-fts-companion-"));
  const servingDbPath = path.join(tmp, "atlas_serving.sqlite");
  const db = new Database(servingDbPath);
  db.exec(`
    CREATE TABLE search_document (
      doc_rowid INTEGER PRIMARY KEY,
      subject_id TEXT,
      subject_type TEXT,
      display_name TEXT,
      normalized_name TEXT,
      aliases_text TEXT,
      city_text TEXT,
      taxon_path TEXT,
      rank_score REAL,
      last_seen_at TEXT,
      public_state TEXT,
      search_text TEXT
    );
    CREATE VIRTUAL TABLE search_document_fts USING fts5(
      search_text,
      content='search_document',
      content_rowid='doc_rowid',
      tokenize='trigram'
    );
    CREATE VIRTUAL TABLE search_document_fts_unicode61 USING fts5(
      search_text,
      content='search_document',
      content_rowid='doc_rowid',
      tokenize='unicode61'
    );
    CREATE TABLE dj_profile (
      dj_id TEXT PRIMARY KEY,
      display_name TEXT,
      normalized_name TEXT,
      aliases_json TEXT,
      city_primary TEXT,
      avatar_asset_id TEXT,
      source_article_count INTEGER,
      event_count INTEGER,
      venue_count INTEGER,
      collaborator_count INTEGER,
      organization_count INTEGER,
      media_count INTEGER,
      first_seen_at TEXT,
      last_seen_at TEXT,
      confidence REAL
    );
    CREATE TABLE performance_event (
      event_id TEXT PRIMARY KEY,
      event_title TEXT,
      starts_at TEXT,
      time_text TEXT,
      venue_id TEXT,
      venue_name TEXT,
      city TEXT,
      source_ref_id TEXT,
      participant_count INTEGER,
      organizer_count INTEGER,
      confidence REAL
    );
  `);
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    1,
    "dj:alpha",
    "dj",
    "DJ Alpha",
    "dj alpha",
    "Alpha",
    "深圳",
    "atlas/dj",
    100,
    "2026-06-05",
    "public",
    "DJ Alpha 深圳 artist performer",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(1, "DJ Alpha 深圳 artist performer");
  db.prepare("INSERT INTO search_document_fts_unicode61(rowid, search_text) VALUES (?, ?)").run(1, "DJ Alpha 深圳 artist performer");
  db.prepare("INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "dj:alpha",
    "DJ Alpha",
    "dj alpha",
    "[\"Alpha\"]",
    "深圳",
    "",
    1,
    0,
    0,
    0,
    0,
    0,
    "2026-06-05",
    "2026-06-05",
    1,
  );
  assert.equal(db.prepare("SELECT COUNT(*) AS count FROM search_document_fts WHERE search_document_fts MATCH ?").get("\"DJ\"").count, 0);
  assert.equal(db.prepare("SELECT COUNT(*) AS count FROM search_document_fts_unicode61 WHERE search_document_fts_unicode61 MATCH ?").get("\"DJ\"").count, 1);
  db.close();

  const store = new Stage7AtlasSqliteStore({
    stage7SqliteDbPath: servingDbPath,
    env: { ATLAS_SQLITE_READONLY: "1" },
  });
  const result = await store.search({ q: "DJ", limit: 5 });
  assert.equal(result.resultCount, 1);
  assert.equal(result.results[0].title, "DJ Alpha");
  assert.equal(result.retrieval.mode, "atlas_serving_search_document_fts5");
  store.dbHandle?.close();
});

test("ATLAS_CORE_SQLITE_DB selects an opt-in core exported serving read model", async () => {
  const tmp = await mkdtemp(path.join(os.tmpdir(), "atlas-core-env-serving-"));
  const servingDbPath = path.join(tmp, "atlas_serving.sqlite");
  const db = new Database(servingDbPath);
  db.exec(`
    CREATE TABLE search_document (
      doc_rowid INTEGER PRIMARY KEY,
      subject_id TEXT,
      subject_type TEXT,
      display_name TEXT,
      normalized_name TEXT,
      aliases_text TEXT,
      city_text TEXT,
      taxon_path TEXT,
      rank_score REAL,
      last_seen_at TEXT,
      public_state TEXT,
      search_text TEXT
    );
    CREATE VIRTUAL TABLE search_document_fts USING fts5(
      search_text,
      content='search_document',
      content_rowid='doc_rowid'
    );
    CREATE TABLE dj_profile (
      dj_id TEXT PRIMARY KEY,
      display_name TEXT,
      normalized_name TEXT,
      aliases_json TEXT,
      city_primary TEXT,
      avatar_asset_id TEXT,
      source_article_count INTEGER,
      event_count INTEGER,
      venue_count INTEGER,
      collaborator_count INTEGER,
      organization_count INTEGER,
      media_count INTEGER,
      first_seen_at TEXT,
      last_seen_at TEXT,
      confidence REAL
    );
    CREATE TABLE performance_event (
      event_id TEXT PRIMARY KEY,
      event_title TEXT,
      starts_at TEXT,
      time_text TEXT,
      venue_id TEXT,
      venue_name TEXT,
      city TEXT,
      source_ref_id TEXT,
      participant_count INTEGER,
      organizer_count INTEGER,
      confidence REAL
    );
  `);
  db.prepare("INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    1,
    "dj:core-alpha",
    "dj",
    "CoreDJ Alpha",
    "coredj alpha",
    "Alpha",
    "深圳",
    "atlas/dj",
    100,
    "2026-06-05",
    "public",
    "CoreDJ Alpha 深圳 artist performer",
  );
  db.prepare("INSERT INTO search_document_fts(rowid, search_text) VALUES (?, ?)").run(1, "CoreDJ Alpha 深圳 artist performer");
  db.prepare("INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
    "dj:core-alpha",
    "CoreDJ Alpha",
    "coredj alpha",
    "[\"Alpha\"]",
    "深圳",
    "",
    1,
    0,
    0,
    0,
    0,
    0,
    "2026-06-05",
    "2026-06-05",
    1,
  );
  db.close();

  const store = new Stage7AtlasSqliteStore({
    env: {
      ATLAS_CORE_SQLITE_DB: servingDbPath,
      ATLAS_SQLITE_READONLY: "1",
    },
  });
  assert.equal(store.dbPath, servingDbPath);
  const result = await store.search({ q: "CoreDJ", limit: 5 });
  assert.equal(result.resultCount, 1);
  assert.equal(result.results[0].title, "CoreDJ Alpha");
  assert.equal(result.retrieval.mode, "atlas_serving_search_document_fts5");
  store.dbHandle?.close();
});

test("serves full entity profile rollup for historical clubs and performers", async () => {
  const profileRes = await fetch(`${baseUrl}/api/v1/stage7/graph/profile?q=MaFoL&limit=20&eventLimit=10&collaboratorLimit=10`);
  assert.equal(profileRes.status, 200);
  const profile = await profileRes.json();
  assert.equal(profile.schemaVersion, "stage7_atlas_api.graph_entity_profile.v1");
  assert.equal(profile.found, true);
  assert.equal(profile.canonical.name, "MaFoL");
  assert.equal(profile.summary.sourceArticleCount, 2);
  assert.equal(profile.summary.loadedSourceArticles, 2);
  assert.ok(profile.summary.eventCount >= 2);
  assert.ok(profile.sources.accounts.some((row) => row.label === "DONG 洞"));
  assert.ok(profile.sources.accounts.some((row) => row.label === "All俱乐部"));
  assert.ok(profile.history.events.some((row) => row.name === "南馄北饺大决斗"));
  assert.ok(profile.history.events.some((row) => row.name === "ALL Club MaFoL night"));
  assert.ok(profile.history.venues.some((row) => row.label === "DONG 洞"));
  assert.ok(profile.history.venues.some((row) => row.label === "All Club"));
  assert.ok(profile.relationships.collaborators.some((row) => row.label === "DaRou"));
  assert.ok(profile.relationships.collaborators.some((row) => row.label === "Masher"));
  assert.equal(profile.retrieval.mode, "sqlite_full_entity_profile_rollup");
  assert.equal(profile.safety.sqliteWriteExecuted, false);
  assert.equal(profile.safety.bulkExportEnabled, false);
});

test("serves mobile-first Atlas graph profile contract for mini-program", async () => {
  const res = await fetch(`${baseUrl}/api/v1/stage7/graph/mobile-profile?q=MaFoL&eventLimit=5&collaboratorLimit=5&articleLimit=3`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schemaVersion, "stage7_atlas_api.graph_mobile_profile.v1");
  assert.equal(body.found, true);
  assert.equal(body.header.title, "MaFoL");
  assert.equal(body.payloadPolicy.target, "wechat_miniprogram");
  assert.equal(body.payloadPolicy.fullGraphExport, false);
  assert.ok(body.quickActions.some((row) => row.action === "open_graph_seed" && row.apiPath.includes("limit=48")));
  assert.ok(body.sections.some((row) => row.id === "history" && row.layout === "timeline"));
  assert.ok(body.sections.some((row) => row.id === "relationships" && row.items.some((item) => item.relationshipScore > 0 && item.tap.action === "open_entity_profile")));
  assert.ok(body.sections.some((row) => row.id === "sources" && row.items.every((item) => item.tap.action === "open_source_evidence" && item.snippet)));
  assert.equal(body.retrieval.entityMergeSidecarEnabled, false);
  assert.equal(body.safety.sqliteWriteExecuted, false);
});

test("serves Atlas family profile product API without exposing raw internals", async () => {
  const res = await fetch(`${baseUrl}/api/v1/atlas/family/profile?q=MaFoL&eventLimit=5&collaboratorLimit=5&articleLimit=3`);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.schemaVersion, "atlas.family_profile.v1");
  assert.equal(body.found, true);
  assert.equal(body.canonical.name, "MaFoL");
  assert.ok(body.canonical.primaryId);
  assert.equal(body.trust.facts, "public_fact");
  assert.equal(body.trust.merge, "report_only");
  assert.equal(body.trust.social, "candidate");
  assert.equal(body.trust.avatar, "blocked");
  assert.ok(body.stats.events >= 2);
  assert.equal(body.center.kind, "dj");
  assert.equal(body.sections.explore.layout, "radial-orbit");
  assert.equal(body.sections.explore.title, "以 DJ 为中心");
  assert.deepEqual(body.sections.explore.rings.slice(0, 3).map((row) => row.id), ["relatedDjs", "clubs", "events"]);
  assert.ok(body.sections.relatedDjs.items.some((row) => row.label === "DaRou" && row.tap.apiPath.includes("/api/v1/atlas/family/profile")));
  assert.ok(body.sections.clubs.items.some((row) => row.label === "DONG 洞" || row.label === "All Club"));
  assert.ok(body.sections.events.items.some((row) => row.title === "南馄北饺大决斗" && row.tap.apiPath.includes("/api/v1/atlas/family/profile?id=")));
  assert.ok(body.sections.history.items.some((row) => row.title === "南馄北饺大决斗"));
  assert.ok(body.sections.relationships.items.some((row) => row.label === "DaRou" && row.relationshipScore > 0));
  assert.ok(body.sections.relationships.items.every((row) => !Object.hasOwn(row, "sameEventCount")));
  assert.ok(body.sections.relationships.items.some((row) => row.evidence.some((item) => item.sourceRefId === "DONG/article-mafol")));
  assert.ok(body.sections.sources.items.every((row) => row.state === "public_fact" && row.tap.action === "open_source_evidence"));
  assert.equal(body.sections.candidates.state, "candidate");
  assert.equal(body.navigation.graphSeedApi.includes("limit=48"), true);
  assert.equal(body.safety.rawDbPathHidden, true);
  assert.equal(body.safety.rawUrlHiddenUnlessPublicAllowed, true);
  assert.equal(body.safety.boundedPayload, true);
  assertNoPublicAtlasLeak(body);
});

test("serves Atlas family relationship and evidence APIs with public-safe fields", async () => {
  const relationshipsRes = await fetch(`${baseUrl}/api/v1/atlas/family/relationships?id=dj:mafol&limit=5`);
  assert.equal(relationshipsRes.status, 200);
  const relationships = await relationshipsRes.json();
  assert.equal(relationships.schemaVersion, "atlas.family_relationships.v1");
  assert.equal(relationships.target.label, "MaFoL");
  assert.ok(relationships.relationships.some((row) => row.label === "DaRou" && row.relationshipScore > 0));
  assert.ok(relationships.relationships.every((row) => typeof row.relationshipScore === "number"));
  assert.ok(relationships.relationships.every((row) => !Object.hasOwn(row, "sameEventCount")));
  assert.ok(relationships.relationships.some((row) => row.metrics.sameEventCount >= 1));
  assertNoPublicAtlasLeak(relationships);

  const evidenceRes = await fetch(`${baseUrl}/api/v1/atlas/evidence/${encodeURIComponent("DONG/article-mafol")}`);
  assert.equal(evidenceRes.status, 200);
  const evidence = await evidenceRes.json();
  assert.equal(evidence.schemaVersion, "atlas.evidence.v1");
  assert.equal(evidence.sourceRefId, "DONG/article-mafol");
  assert.equal(evidence.sourceAccount, "DONG 洞");
  assert.equal(evidence.sourceTitle, "南馄北饺大决斗");
  assert.equal(evidence.publicUrl.status, "not_public");
  assert.equal(evidence.safety.rawLocalPathExposed, false);
  assert.equal(evidence.safety.rawSourceUrlExposed, false);
  assertNoPublicAtlasLeak(evidence);
});

test("expands venue profile across canonical aliases without oil false positives", async () => {
  const profileRes = await fetch(
    `${baseUrl}/api/v1/stage7/graph/profile?q=OIL&limit=20&sourceLimit=20&eventLimit=20&collaboratorLimit=20&venueLimit=20`,
  );
  assert.equal(profileRes.status, 200);
  const profile = await profileRes.json();
  assert.equal(profile.found, true);
  assert.equal(profile.retrieval.canonicalAliasExpanded, true);
  assert.ok(profile.canonical.names.includes("OIL油"));
  assert.ok(profile.canonical.names.includes("OIL Club"));
  assert.ok(!profile.canonical.names.includes("Boiler Room"));
  assert.equal(profile.summary.sourceArticleCount, 2);
  assert.equal(profile.summary.eventCount, 2);
  assert.ok(profile.history.venues.some((row) => row.label === "OIL Club"));
  assert.ok(profile.sources.accounts.some((row) => row.label === "OIL油"));
  assert.ok(!profile.sources.articles.some((row) => /Boiler/.test(row.title)));
});

test("self-tests high-confidence graph searches with related database context", async () => {
  const report = await runAtlasGraphSearchSelfTest({
    dbPath: fixtureDbPath,
    manualSeeds: ["MaFoL", "DADA Beijing"],
    autoLimit: 0,
    maxSeeds: 2,
    graphLimit: 40,
    subgraphLimit: 40,
    relatedLimit: 10,
    seedLatencyBudgetMs: 5000,
    writeReport: false,
  });
  assert.equal(report.schemaVersion, "atlas_graph_search_selftest.v1");
  assert.equal(report.decision, "PASS");
  assert.equal(report.summary.seedCount, 2);
  assert.equal(report.summary.passCount, 2);
  assert.equal(report.summary.relatedCount, 2);
  assert.equal(report.safety.sqliteWriteExecuted, false);
  assert.ok(report.results.every((row) => row.checks.exactNodeFound));
  assert.ok(report.results.every((row) => row.checks.detailHasRelated));
  assert.ok(report.results.every((row) => row.graph.nodes >= 3));
  assert.ok(report.results.every((row) => row.graph.edges >= 2));
});

test("filters alcohol menu and product entities from public Atlas graph surfaces", async () => {
  const searchRes = await fetch(`${baseUrl}/api/v1/stage7/search?q=${encodeURIComponent("葡萄酒")}&limit=10`);
  assert.equal(searchRes.status, 200);
  const search = await searchRes.json();
  assert.equal(search.resultCount, 0);

  const productRes = await fetch(`${baseUrl}/api/v1/stage7/entities/entity-wine`);
  assert.equal(productRes.status, 404);

  const orgRes = await fetch(`${baseUrl}/api/v1/stage7/entities/entity-hakka?relatedLimit=10`);
  assert.equal(orgRes.status, 404);

  const graphRes = await fetch(`${baseUrl}/api/v1/stage7/graph/seed?q=${encodeURIComponent("葡萄酒")}&limit=20`);
  assert.equal(graphRes.status, 200);
  const graph = await graphRes.json();
  assert.equal(graph.nodes.some((node) => /葡萄酒|酒单|wine|product/i.test(`${node.label} ${node.subtype} ${node.summary}`)), false);
});

test("filters non-electronic art, cafe, class, and reading-club noise from public Atlas graph surfaces", async () => {
  for (const term of ["艺术展", "读书会", "课程表", "咖啡"]) {
    const searchRes = await fetch(`${baseUrl}/api/v1/stage7/search?q=${encodeURIComponent(term)}&limit=10`);
    assert.equal(searchRes.status, 200);
    const search = await searchRes.json();
    assert.equal(search.resultCount, 0, term);
  }

  const artDetailRes = await fetch(`${baseUrl}/api/v1/stage7/entities/entity-art`);
  assert.equal(artDetailRes.status, 404);
  const readingDetailRes = await fetch(`${baseUrl}/api/v1/stage7/entities/entity-reading`);
  assert.equal(readingDetailRes.status, 404);

  const graphRes = await fetch(`${baseUrl}/api/v1/stage7/graph/seed?q=${encodeURIComponent("艺术展")}&limit=20`);
  assert.equal(graphRes.status, 200);
  const graph = await graphRes.json();
  assert.equal(graph.nodes.some((node) => /艺术展|读书会|课程表|咖啡|cafe|exhibition/i.test(`${node.label} ${node.subtype} ${node.summary}`)), false);
});

test("gates Atlas data APIs behind Turnstile session when enabled", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "stage7-atlas-gated-"));
  const dbPath = path.join(dir, "atlas.sqlite");
  createAtlasDb(dbPath);
  let gatedServer;
  let gatedBaseUrl;
  for (let port = 18930; port < 18960; port += 1) {
    gatedServer = createServer({
      stage7SqliteDbPath: dbPath,
      env: {
        NODE_ENV: "test",
        ATLAS_REQUIRE_SESSION: "1",
        ATLAS_TURNSTILE_TEST_MODE: "pass",
        ATLAS_TURNSTILE_SITE_KEY: "1x00000000000000000000AA",
        ATLAS_TURNSTILE_SECRET_KEY: "test-turnstile-secret",
        ATLAS_SESSION_SECRET: "test-session-secret",
        ATLAS_FALLBACK_POW_DIFFICULTY: "8",
        ATLAS_COOKIE_SECURE: "0",
      },
      llmClient: { publicStatus: () => ({ provider: "deepseek", configured: false }) },
    });
    try {
      await new Promise((resolve, reject) => {
        gatedServer.once("error", reject);
        gatedServer.listen(port, "127.0.0.1", resolve);
      });
      gatedBaseUrl = `http://127.0.0.1:${port}`;
      break;
    } catch (error) {
      await new Promise((resolve) => gatedServer.close(resolve));
      if (error?.code !== "EADDRINUSE") throw error;
    }
  }

  try {
    assert.ok(gatedBaseUrl);

    const blockedRes = await fetch(`${gatedBaseUrl}/api/v1/stage7/graph/seed?q=DADA&limit=20`);
    assert.equal(blockedRes.status, 403);
    const blocked = await blockedRes.json();
    assert.equal(blocked.error.code, "ATLAS_SESSION_REQUIRED");

    const statusRes = await fetch(`${gatedBaseUrl}/api/v1/atlas/session/status`);
    assert.equal(statusRes.status, 200);
    const status = await statusRes.json();
    assert.equal(status.requireSession, true);
    assert.equal(status.hasSession, false);
    assert.equal(status.fallbackChallengeEnabled, true);
    assert.equal(status.safety.turnstileSecretExposed, false);

    const challengeRes = await fetch(`${gatedBaseUrl}/api/v1/atlas/session/fallback-challenge`);
    assert.equal(challengeRes.status, 200);
    const challenge = await challengeRes.json();
    assert.equal(challenge.algorithm, "sha256-leading-zero-bits");
    assert.equal(challenge.difficulty, 8);
    assert.equal(challenge.safety.darkDatabaseExposed, false);
    assert.equal(challenge.safety.bulkExportEnabled, false);

    const fallbackRes = await fetch(`${gatedBaseUrl}/api/v1/atlas/session/fallback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        payload: challenge.payload,
        signature: challenge.signature,
        proof: solveFallbackChallenge(challenge),
      }),
    });
    assert.equal(fallbackRes.status, 200);
    const fallbackCookie = fallbackRes.headers.get("set-cookie");
    assert.match(fallbackCookie, /atlas_session=/);
    assert.doesNotMatch(fallbackCookie, /test-session-secret/);
    assert.doesNotMatch(fallbackCookie, /test-turnstile-secret/);

    const fallbackAllowedRes = await fetch(`${gatedBaseUrl}/api/v1/stage7/graph/seed?q=DADA&limit=20`, {
      headers: { Cookie: fallbackCookie },
    });
    assert.equal(fallbackAllowedRes.status, 200);

    const sessionRes = await fetch(`${gatedBaseUrl}/api/v1/atlas/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: "test-pass" }),
    });
    assert.equal(sessionRes.status, 200);
    const cookie = sessionRes.headers.get("set-cookie");
    assert.match(cookie, /atlas_session=/);
    assert.doesNotMatch(cookie, /test-turnstile-secret/);

    const allowedRes = await fetch(`${gatedBaseUrl}/api/v1/stage7/graph/seed?q=DADA&limit=20`, {
      headers: { Cookie: cookie },
    });
    assert.equal(allowedRes.status, 200);
    const allowed = await allowedRes.json();
    assert.equal(allowed.safety.bulkExportEnabled, false);
    assert.ok(allowed.nodes.some((node) => node.id === "entities:entity-a"));

    const honeyRes = await fetch(`${gatedBaseUrl}/atlas.sqlite`, { headers: { Cookie: cookie } });
    assert.equal(honeyRes.status, 403);
  } finally {
    if (gatedServer) await new Promise((resolve) => gatedServer.close(resolve));
  }
});

test("serves graph API but blocks local ledger writes in read-only SQLite mode", async () => {
  let readOnlyServer;
  let readOnlyBaseUrl;
  for (let port = 18931; port < 18950; port += 1) {
    readOnlyServer = createServer({
      stage7SqliteDbPath: fixtureDbPath,
      env: { ATLAS_SQLITE_READONLY: "1" },
      llmClient: { publicStatus: () => ({ provider: "deepseek", configured: false }) },
    });
    try {
      await new Promise((resolve, reject) => {
        readOnlyServer.once("error", reject);
        readOnlyServer.listen(port, "127.0.0.1", resolve);
      });
      readOnlyBaseUrl = `http://127.0.0.1:${port}`;
      break;
    } catch (error) {
      await new Promise((resolve) => readOnlyServer.close(resolve));
      if (error?.code !== "EADDRINUSE") throw error;
    }
  }

  try {
    assert.ok(readOnlyBaseUrl, "read-only test server should start");
    const seedRes = await fetch(`${readOnlyBaseUrl}/api/v1/stage7/graph/seed?q=DADA&limit=20`);
    assert.equal(seedRes.status, 200);
    const seed = await seedRes.json();
    assert.equal(seed.retrieval.dbIdentity.readOnly, true);
    assert.equal(seed.retrieval.dbIdentity.mutableLedgerEnabled, false);

    const postRes = await fetch(`${readOnlyBaseUrl}/api/v1/stage7/local/geocode-review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewId: "review:place:unknown", action: "review_only" }),
    });
    assert.equal(postRes.status, 403);
    const blocked = await postRes.json();
    assert.equal(blocked.error.details.message, "Atlas SQLite store is running in read-only mode");
  } finally {
    if (readOnlyServer) await new Promise((resolve) => readOnlyServer.close(resolve));
  }
});

test("persists geocode review actions in the local SQLite ledger", async () => {
  const postRes = await fetch(`${baseUrl}/api/v1/stage7/local/geocode-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      reviewId: "review:place:unknown",
      action: "needs_more_source",
      decision: "needs_more_source",
      reviewer: "test",
      note: "fixture geocode smoke",
    }),
  });
  assert.equal(postRes.status, 200);
  const result = await postRes.json();
  assert.equal(result.schemaVersion, "stage7_atlas_api.geocode_review_action_result.v1");
  assert.equal(result.ok, true);
  assert.equal(result.safety.sqliteWriteExecuted, true);
  assert.equal(result.safety.graphWriteExecuted, false);
  assert.equal(result.safety.mapFactPromoted, false);

  const statusRes = await fetch(`${baseUrl}/api/v1/stage7/local/status`);
  assert.equal(statusRes.status, 200);
  const status = await statusRes.json();
  assert.equal(status.geocodeReview.actions, 1);
  assert.equal(status.geocodeReview.stateRows, 1);

  const reviewRes = await fetch(`${baseUrl}/api/v1/stage7/local/geocode-review?limit=5`);
  assert.equal(reviewRes.status, 200);
  const review = await reviewRes.json();
  const item = review.items.find((candidate) => candidate.reviewId === "review:place:unknown");
  assert.equal(item.currentState.action, "needs_more_source");

  const invalidRes = await fetch(`${baseUrl}/api/v1/stage7/local/geocode-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewId: "review:place:unknown", action: "unsupported" }),
  });
  assert.equal(invalidRes.status, 400);

  const missingRes = await fetch(`${baseUrl}/api/v1/stage7/local/geocode-review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewId: "missing", action: "review_only" }),
  });
  assert.equal(missingRes.status, 404);
});

test("persists adjudication actions in the local SQLite ledger", async () => {
  const postRes = await fetch(`${baseUrl}/api/v1/stage7/local/adjudication`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      itemId: "initial:1",
      action: "needs_more_source",
      decision: "needs_more_source",
      reviewer: "test",
      note: "fixture smoke",
    }),
  });
  assert.equal(postRes.status, 200);
  const result = await postRes.json();
  assert.equal(result.ok, true);
  assert.equal(result.safety.sqliteWriteExecuted, true);
  assert.equal(result.safety.graphWriteExecuted, false);

  const ledgerRes = await fetch(`${baseUrl}/api/v1/stage7/local/adjudication-ledger?limit=5`);
  assert.equal(ledgerRes.status, 200);
  const ledger = await ledgerRes.json();
  assert.equal(ledger.actions[0].itemId, "initial:1");
  assert.equal(ledger.actions[0].action, "needs_more_source");

  const queueRes = await fetch(`${baseUrl}/api/v1/stage7/identity-review?limit=5`);
  assert.equal(queueRes.status, 200);
  const queue = await queueRes.json();
  const item = queue.items.find((candidate) => candidate.id === "initial:1");
  assert.equal(item.currentState.action, "needs_more_source");

  const invalidRes = await fetch(`${baseUrl}/api/v1/stage7/local/adjudication`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ itemId: "initial:1", action: "unsupported" }),
  });
  assert.equal(invalidRes.status, 400);
});
