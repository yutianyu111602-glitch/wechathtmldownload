import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createDjInterviewStore } from "../src/interviewStore.mjs";
import { writeDjInterviewReviewWorkbench } from "../src/interviewReviewWorkbench.mjs";

test("DJ interview review workbench renders a redacted local tool surface", async () => {
  const interviewDir = await mkdtemp(path.join(os.tmpdir(), "dj-interview-workbench-"));
  const outDir = await mkdtemp(path.join(os.tmpdir(), "dj-interview-workbench-out-"));
  const store = createDjInterviewStore({ interviewDir });

  await store.submit({
    djName: "DJ Spell",
    city: "上海",
    contact: "private-contact",
    instagramUrl: "https://instagram.com/djspell",
    mixtapeUrl: "https://soundcloud.com/djspell/mix-001",
    sourceUrl: "https://mp.weixin.qq.com/s/source001",
    sourceRefId: "wechat:source001",
    answerText: "raw private answer must not render",
    consent: { internalProcessing: true, publicFacts: true, graphCandidate: false },
  });

  const result = await writeDjInterviewReviewWorkbench({
    store,
    outDir,
    generatedAt: "2026-05-31T10:25:00+08:00",
  });
  const html = await readFile(result.htmlPath, "utf8");

  assert.match(html, /data-role="review-workbench"/);
  assert.match(html, /DJ Spell/);
  assert.match(html, /wechat:source001/);
  assert.match(html, /confirm_graph_consent_or_keep_private/);
  assert.match(html, /Raw contact exported<\/span><strong>false<\/strong>/);
  assert.equal(html.includes("private-contact"), false);
  assert.equal(html.includes("raw private answer"), false);
  assert.doesNotMatch(html, /hero/i);
  assert.equal(result.packet.summary.exported, 1);
});
