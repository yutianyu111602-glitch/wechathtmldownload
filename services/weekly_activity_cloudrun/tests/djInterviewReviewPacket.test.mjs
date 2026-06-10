import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createDjInterviewStore } from "../src/interviewStore.mjs";
import { buildDjInterviewReviewPacket, writeDjInterviewReviewPacket } from "../src/interviewReviewPacket.mjs";

test("DJ interview review packet exports source evidence without raw private fields", async () => {
  const interviewDir = await mkdtemp(path.join(os.tmpdir(), "dj-interview-packet-"));
  const outDir = await mkdtemp(path.join(os.tmpdir(), "dj-interview-packet-out-"));
  const store = createDjInterviewStore({ interviewDir });

  await store.submit({
    djName: "DJ Spell",
    city: "上海",
    contact: "private-contact",
    instagramUrl: "https://instagram.com/djspell",
    mixtapeUrl: "https://soundcloud.com/djspell/mix-001",
    sourceUrl: "https://mp.weixin.qq.com/s/source001",
    sourceRefId: "wechat:source001",
    answerText: "raw private answer must not leave the sidecar",
    consent: { internalProcessing: true, publicFacts: true, graphCandidate: false },
  });

  const packet = await buildDjInterviewReviewPacket({
    store,
    generatedAt: "2026-05-31T10:20:00+08:00",
  });

  assert.equal(packet.schemaVersion, "atlas_dj_interview_review_packet.v1");
  assert.equal(packet.summary.total, 1);
  assert.equal(packet.summary.withSourceEvidence, 1);
  assert.equal(packet.summary.blockedBeforePromotion, 1);
  assert.equal(packet.items[0].djName, "DJ Spell");
  assert.equal(packet.items[0].sourceEvidence.sourceRefId, "wechat:source001");
  assert.ok(packet.items[0].reviewActions.includes("confirm_graph_consent_or_keep_private"));
  assert.equal(packet.safety.rawContactExported, false);
  assert.equal(packet.safety.rawInterviewTextExported, false);
  assert.equal(packet.items[0].contact, undefined);
  assert.equal(packet.items[0].answerText, undefined);

  const result = await writeDjInterviewReviewPacket({
    store,
    outDir,
    generatedAt: "2026-05-31T10:20:00+08:00",
  });
  const jsonText = await readFile(result.jsonPath, "utf8");
  const mdText = await readFile(result.markdownPath, "utf8");
  assert.ok(jsonText.includes("wechat:source001"));
  assert.ok(mdText.includes("DJ Spell"));
  assert.equal(jsonText.includes("private-contact"), false);
  assert.equal(jsonText.includes("raw private answer"), false);
  assert.equal(mdText.includes("private-contact"), false);
  assert.equal(mdText.includes("raw private answer"), false);
});
