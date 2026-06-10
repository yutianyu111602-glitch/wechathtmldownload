import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createDjInterviewStore } from "../src/interviewStore.mjs";
import {
  importDjInterviewSubmissions,
  parseInterviewMarkdown,
  readInterviewIntake,
} from "../src/interviewIntake.mjs";
import { buildDjInterviewReviewPacket } from "../src/interviewReviewPacket.mjs";

async function tmpDir() {
  return mkdtemp(path.join(os.tmpdir(), "atlas-dj-interview-intake-"));
}

test("DJ interview markdown intake parses front matter and redacts output summaries", async () => {
  const [record] = parseInterviewMarkdown(`---
djName: DJ Cool
city: Shanghai
contact: private-contact
sourceUrl: https://mp.weixin.qq.com/s/source
instagramUrl: https://instagram.com/djcool
mixtapeUrl: https://soundcloud.com/djcool/mix
consentInternal: true
consentPublic: true
consentGraph: false
---
Raw interview answer that stays private.
`);

  assert.equal(record.djName, "DJ Cool");
  assert.equal(record.consentInternal, true);
  assert.equal(record.answerText, "Raw interview answer that stays private.");

  const dir = await tmpDir();
  const input = path.join(dir, "cool.md");
  await writeFile(input, `---
djName: DJ Cool
city: Shanghai
contact: private-contact
sourceUrl: https://mp.weixin.qq.com/s/source
consentInternal: true
---
Raw interview answer that stays private.
`, "utf8");

  const store = createDjInterviewStore({ interviewDir: path.join(dir, "sidecar") });
  const result = await importDjInterviewSubmissions({ inputPath: input, store, dryRun: true });
  const serialized = JSON.stringify(result);

  assert.equal(result.ok, true);
  assert.equal(result.accepted, 1);
  assert.equal(result.rejected, 0);
  assert.equal(result.items[0].hasContact, true);
  assert.equal(result.items[0].hasAnswerText, true);
  assert.match(result.items[0].sourceUrlHash, /^[a-f0-9]{16}$/);
  assert.doesNotMatch(serialized, /private-contact/);
  assert.doesNotMatch(serialized, /Raw interview answer/);
  assert.equal(result.safety.rawContactExported, false);
});

test("DJ interview intake rejects missing internal processing consent without writing sidecar", async () => {
  const dir = await tmpDir();
  const input = path.join(dir, "missing-consent.json");
  await writeFile(input, JSON.stringify({ djName: "DJ No Consent" }), "utf8");

  const store = createDjInterviewStore({ interviewDir: path.join(dir, "sidecar") });
  const result = await importDjInterviewSubmissions({ inputPath: input, store });
  const count = await store.count();

  assert.equal(result.ok, false);
  assert.equal(result.accepted, 0);
  assert.equal(result.rejected, 1);
  assert.deepEqual(result.rejectedItems[0].errors, ["internal_processing_consent_required"]);
  assert.equal(count.total, 0);
});

test("DJ interview intake imports valid records and feeds redacted review packet", async () => {
  const dir = await tmpDir();
  const input = path.join(dir, "submissions.jsonl");
  await writeFile(input, [
    JSON.stringify({
      djName: "DJ Archive",
      city: "Chengdu",
      contact: "private-contact",
      sourceRefId: "src:archive",
      mixtapeUrl: "https://mixcloud.com/archive/session",
      answerText: "private interview text",
      consent: { internalProcessing: true, publicFacts: true, graphCandidate: false },
    }),
  ].join("\n"), "utf8");

  const store = createDjInterviewStore({ interviewDir: path.join(dir, "sidecar") });
  const result = await importDjInterviewSubmissions({ inputPath: input, store });
  const packet = await buildDjInterviewReviewPacket({ store });
  const rawSidecar = await readFile(path.join(dir, "sidecar", "submissions.json"), "utf8");

  assert.equal(result.ok, true);
  assert.equal(result.imported, 1);
  assert.equal(packet.summary.exported, 1);
  assert.equal(packet.items[0].djName, "DJ Archive");
  assert.equal(packet.items[0].hasContact, true);
  assert.equal(packet.safety.rawContactExported, false);
  assert.equal(packet.safety.rawInterviewTextExported, false);
  assert.match(rawSidecar, /private-contact/);
  assert.doesNotMatch(JSON.stringify(packet), /private-contact/);
  assert.doesNotMatch(JSON.stringify(packet), /private interview text/);
});

test("DJ interview intake reads a directory of supported files only", async () => {
  const dir = await tmpDir();
  await writeFile(path.join(dir, "a.md"), `---
djName: DJ A
consentInternal: true
---
A
`, "utf8");
  await writeFile(path.join(dir, "b.json"), JSON.stringify({ djName: "DJ B", consentInternal: true }), "utf8");
  await writeFile(path.join(dir, "ignore.txt"), "ignored", "utf8");

  const intake = await readInterviewIntake(dir);

  assert.equal(intake.length, 2);
  assert.deepEqual(intake.map((item) => item.summary.djName).sort(), ["DJ A", "DJ B"]);
});
