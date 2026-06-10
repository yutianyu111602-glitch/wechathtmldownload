import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createDjInterviewStore } from "../src/interviewStore.mjs";
import { createServer } from "../src/server.mjs";

async function listen(server) {
  for (let port = 18880; port < 18910; port += 1) {
    try {
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(port, "127.0.0.1", resolve);
      });
      return `http://127.0.0.1:${port}`;
    } catch (error) {
      await new Promise((resolve) => server.close(resolve));
      if (error?.code !== "EADDRINUSE") throw error;
    }
  }
  throw new Error("No free local test port in 18880-18909.");
}

test("DJ interview API stores consented submissions as private sidecar entries", async () => {
  const interviewDir = await mkdtemp(path.join(os.tmpdir(), "dj-interview-api-"));
  const server = createServer({
    env: { ATLAS_MINIAPP_PRELOAD: "0" },
    interviewStore: createDjInterviewStore({ interviewDir }),
    llmClient: {
      publicStatus: () => ({ provider: "deepseek", configured: false, thinking: "disabled" }),
    },
  });
  const baseUrl = await listen(server);
  try {
    const postRes = await fetch(`${baseUrl}/api/v1/atlas/dj-interviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        djName: "DJ Spell",
        city: "上海",
        contact: "private-contact",
        instagramUrl: "https://instagram.com/djspell",
        mixtapeUrl: "https://soundcloud.com/djspell/mix-001",
        consent: { internalProcessing: true, publicFacts: true, graphCandidate: true },
      }),
    });
    assert.equal(postRes.status, 201);
    const postBody = await postRes.json();
    assert.equal(postBody.schemaVersion, "atlas_dj_interview_submission_result.v1");
    assert.equal(postBody.safety.audioDownloadExecuted, false);
    assert.equal(postBody.safety.publicGraphWriteExecuted, false);

    const listRes = await fetch(`${baseUrl}/api/v1/atlas/dj-interviews`);
    assert.equal(listRes.status, 200);
    const listBody = await listRes.json();
    assert.equal(listBody.total, 1);
    assert.equal(listBody.items[0].djName, "DJ Spell");
    assert.equal(listBody.items[0].hasMixtapeUrl, true);
    assert.equal(listBody.items[0].contact, undefined);
    assert.equal(listBody.safety.rawContactExposed, false);

    const reviewRes = await fetch(`${baseUrl}/api/v1/atlas/dj-interviews/review-queue`);
    assert.equal(reviewRes.status, 200);
    const reviewBody = await reviewRes.json();
    assert.equal(reviewBody.schemaVersion, "atlas_dj_interview_review_queue.v1");
    assert.equal(reviewBody.total, 1);
    assert.equal(reviewBody.items[0].djName, "DJ Spell");
    assert.equal(reviewBody.items[0].contact, undefined);
    assert.equal(reviewBody.items[0].answerText, undefined);
    assert.equal(reviewBody.items[0].sourceEvidence.hasSourceUrl, false);
    assert.equal(reviewBody.items[0].promotionGate.writes.graph, false);
    assert.equal(reviewBody.safety.rawContactExposed, false);
    assert.equal(reviewBody.safety.productionWriteExecuted, false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
