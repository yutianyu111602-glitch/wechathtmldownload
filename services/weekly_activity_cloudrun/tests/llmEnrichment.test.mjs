import assert from "node:assert/strict";
import { test } from "node:test";
import { buildWeeklyItemEnrichmentMessages } from "../src/llmEnrichment.mjs";

test("builds DeepSeek enrichment messages with no-hallucination constraints", () => {
  const messages = buildWeeklyItemEnrichmentMessages({
    id: "item-a",
    title: "上海 Club A",
    promoter: "Club A",
    lineup: ["Club A", "DJ A"],
    evidence: ["22:00 开始", "DJ A all night"],
  });

  assert.equal(messages.length, 2);
  assert.equal(messages[0].role, "system");
  assert.match(messages[0].content, /Do not invent facts/);
  assert.match(messages[0].content, /Do not translate/);

  const userPayload = JSON.parse(messages[1].content);
  assert.equal(userPayload.task, "Normalize one weekly activity item for display.");
  assert.equal(userPayload.item.title, "上海 Club A");
  assert.ok(userPayload.output_schema.is_event);
  assert.ok(userPayload.output_schema.event_time_text);
  assert.ok(userPayload.output_schema.music_styles);
  assert.ok(userPayload.output_schema.dj_bio_lines);
  assert.ok(userPayload.output_schema.lineup_artists);
  assert.ok(userPayload.output_schema.review_flags);
});

test("ticketing prompt requires exact evidence and abstains on QR-only links", () => {
  const messages = buildWeeklyItemEnrichmentMessages({
    id: "exit-0522",
    title: "5.22 周五 | 298 pres.",
    price: ["￥ 3", "免费入场"],
    price_text: "￥ 3 / 免费入场",
    ticketing_text: "￥ 3 / 免费入场",
    evidence: ["ENTRY ←Click for tickets 预售 70￥ 双人 128￥ 现场 100￥ 3am 后免费入场"],
    description_original_lines: ["🎫购票链接🔗 芋圆YuYuan"],
  });

  assert.match(messages[0].content, /Do not infer ticket prices from QR codes/);
  assert.match(messages[0].content, /early bird, presale, door\/onsite, double\/pair/);

  const userPayload = JSON.parse(messages[1].content);
  assert.equal(userPayload.item.price_text, "￥ 3 / 免费入场");
  assert.equal(userPayload.item.ticketing_text, "￥ 3 / 免费入场");
  assert.deepEqual(userPayload.item.description_original_lines, ["🎫购票链接🔗 芋圆YuYuan"]);
  assert.ok(userPayload.output_schema.ticketing_tiers);
  assert.match(userPayload.output_schema.ticketing_text, /exact source-backed/);
});

test("sound system prompt requires explicit source-backed equipment evidence", () => {
  const messages = buildWeeklyItemEnrichmentMessages({
    id: "sound-0523",
    title: "5.23 Sound Night",
    sound_system_text: "Funktion-One",
    evidence: ["本场使用 Funktion-One 音响系统", "音响效果很棒"],
  });

  assert.match(messages[0].content, /sound system/i);
  assert.match(messages[0].content, /Funktion-One/);
  assert.match(messages[0].content, /Do not infer sound systems from generic praise/);

  const userPayload = JSON.parse(messages[1].content);
  assert.equal(userPayload.item.sound_system_text, "Funktion-One");
  assert.ok(userPayload.output_schema.sound_system);
  assert.ok(userPayload.output_schema.sound_system_evidence);
  assert.match(userPayload.output_schema.sound_system_confidence, /source-backed/);
});
