import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createDjInterviewStore } from "../src/interviewStore.mjs";

test("DJ interview store accepts authorized mixtape links without exposing private fields", async () => {
  const interviewDir = await mkdtemp(path.join(os.tmpdir(), "dj-interviews-"));
  const store = createDjInterviewStore({ interviewDir });

  const result = await store.submit({
    djName: "DJ Spell",
    city: "上海",
    contact: "private-contact",
    instagramUrl: "https://instagram.com/djspell",
    mixtapeUrl: "https://soundcloud.com/djspell/mix-001",
    answerText: "This is a private review answer.",
    consent: {
      internalProcessing: true,
      publicFacts: true,
      graphCandidate: false,
    },
  });

  assert.equal(result.ok, true);
  assert.equal(result.safety.rawAudioStored, false);
  assert.equal(result.safety.publicGraphWriteExecuted, false);

  const list = await store.list();
  assert.equal(list.total, 1);
  assert.equal(list.items[0].djName, "DJ Spell");
  assert.equal(list.items[0].hasMixtapeUrl, true);
  assert.equal(list.items[0].hasInstagramUrl, true);
  assert.equal(list.items[0].externalLinkCount, 2);
  assert.equal(list.items[0].musicLinkCount, 1);
  assert.equal(list.items[0].contact, undefined);
  assert.equal(list.items[0].answerText, undefined);
  assert.equal(list.safety.rawContactExposed, false);
});

test("DJ interview store builds a redacted review queue with promotion blockers", async () => {
  const interviewDir = await mkdtemp(path.join(os.tmpdir(), "dj-interviews-"));
  const store = createDjInterviewStore({ interviewDir });

  await store.submit({
    djName: "DJ Spell",
    city: "上海",
    contact: "private-contact",
    instagramUrl: "https://instagram.com/djspell",
    mixtapeUrl: "https://soundcloud.com/djspell/mix-001",
    sourceUrl: "https://mp.weixin.qq.com/s/source001",
    sourceRefId: "wechat:source001",
    answerText: "Raw private answer for reviewer only.",
    consent: {
      internalProcessing: true,
      publicFacts: true,
      graphCandidate: false,
    },
  });

  const queue = await store.reviewQueue();
  assert.equal(queue.schemaVersion, "atlas_dj_interview_review_queue.v1");
  assert.equal(queue.total, 1);
  assert.equal(queue.safety.rawContactExposed, false);
  assert.equal(queue.safety.rawInterviewTextExposed, false);
  assert.equal(queue.safety.productionWriteExecuted, false);

  const item = queue.items[0];
  assert.equal(item.djName, "DJ Spell");
  assert.equal(item.hasContact, true);
  assert.equal(item.hasAnswerText, true);
  assert.equal(item.contact, undefined);
  assert.equal(item.answerText, undefined);
  assert.equal(item.sourceEvidence.hasSourceUrl, true);
  assert.equal(item.sourceEvidence.sourceRefId, "wechat:source001");
  assert.equal(item.linkSummary.musicLinkCount, 1);
  assert.ok(item.externalLinks.every((link) => link.url === undefined));
  assert.ok(item.externalLinks.every((link) => link.urlHash));
  assert.ok(item.promotionGate.blockers.includes("graph_consent_missing"));
  assert.equal(item.promotionGate.writes.db1, false);
  assert.equal(item.promotionGate.writes.db2, false);
  assert.equal(item.promotionGate.writes.db3, false);
  assert.equal(item.promotionGate.writes.graph, false);
});

test("DJ interview store requires internal processing consent", async () => {
  const interviewDir = await mkdtemp(path.join(os.tmpdir(), "dj-interviews-"));
  const store = createDjInterviewStore({ interviewDir });

  await assert.rejects(
    () => store.submit({ djName: "DJ Spell", consent: { internalProcessing: false } }),
    /Interview consent is required/,
  );
});

test("DJ interview store drops direct media file urls from mixtape fields", async () => {
  const interviewDir = await mkdtemp(path.join(os.tmpdir(), "dj-interviews-"));
  const store = createDjInterviewStore({ interviewDir });

  await store.submit({
    djName: "DJ Spell",
    mixtapeUrl: "https://cdn.example.com/private/live-set.mp3?download=1",
    sourceUrl: "https://mixcloud.com/djspell/session",
    consent: {
      internalProcessing: true,
      publicFacts: false,
      graphCandidate: false,
    },
  });

  const list = await store.list();
  assert.equal(list.items[0].hasMixtapeUrl, false);
  assert.equal(list.items[0].hasSourceUrl, true);
  assert.equal(list.items[0].externalLinkCount, 1);
  assert.equal(list.items[0].musicLinkCount, 1);
});
