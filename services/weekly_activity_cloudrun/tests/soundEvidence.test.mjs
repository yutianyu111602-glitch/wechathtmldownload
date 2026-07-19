import assert from "node:assert/strict";
import test from "node:test";
import { createCloudbaseSoundEvidence } from "../src/soundEvidence.mjs";

const ids = [
  "cloud://test-env.bucket/atlas/sound-submissions/stable_key_123456/sound/a.jpg",
  "cloud://test-env.bucket/atlas/sound-submissions/stable_key_123456/payment/b.jpg",
];

function appWithUrls(urls) {
  return {
    async getTempFileURL({ fileList }) {
      return {
        fileList: fileList.map((fileID) => ({
          fileID,
          tempFileURL: urls[fileID] || "",
          status: urls[fileID] ? 0 : -1,
        })),
      };
    },
  };
}

test("sound evidence verifier proves every exact object resolves before persistence", async () => {
  const seen = [];
  const app = {
    async getTempFileURL({ fileList }) {
      seen.push(...fileList);
      return { fileList: fileList.map((fileID, index) => ({ fileID, tempFileURL: `https://storage.example/${index}`, status: 0 })) };
    },
  };
  const evidence = createCloudbaseSoundEvidence({ env: { CLOUDBASE_ENV_ID: "test-env" }, cloudbaseApp: app });
  await evidence.verifySubmissionFiles({ soundFileIds: [ids[0]], paymentFileIds: [ids[1]] });
  assert.deepEqual(seen, ids);

  const missing = createCloudbaseSoundEvidence({
    env: { CLOUDBASE_ENV_ID: "test-env" },
    cloudbaseApp: appWithUrls({ [ids[0]]: "https://storage.example/ok" }),
  });
  await assert.rejects(
    missing.verifySubmissionFiles({ soundFileIds: [ids[0]], paymentFileIds: [ids[1]] }),
    /SOUND_EVIDENCE_OBJECT_UNAVAILABLE/,
  );
});

test("sound evidence loader downloads bounded sound images and validates declared and actual type", async () => {
  const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xd9]);
  let fetchedUrl = "";
  const evidence = createCloudbaseSoundEvidence({
    env: { CLOUDBASE_ENV_ID: "test-env" },
    cloudbaseApp: appWithUrls({ [ids[0]]: "https://storage.example/sound.jpg" }),
    fetchImpl: async (url) => {
      fetchedUrl = url;
      return {
        ok: true,
        headers: new Headers({ "content-type": "image/jpeg", "content-length": String(jpeg.length) }),
        async arrayBuffer() { return jpeg; },
      };
    },
  });
  const result = await evidence.loadSoundImages([ids[0]]);
  assert.equal(fetchedUrl, "https://storage.example/sound.jpg");
  assert.equal(result.length, 1);
  assert.equal(result[0].mimeType, "image/jpeg");
  assert.deepEqual(result[0].data, jpeg);

  const wrongType = createCloudbaseSoundEvidence({
    env: { CLOUDBASE_ENV_ID: "test-env" },
    cloudbaseApp: appWithUrls({ [ids[0]]: "https://storage.example/sound.jpg" }),
    fetchImpl: async () => ({
      ok: true,
      headers: new Headers({ "content-type": "text/html" }),
      async arrayBuffer() { return Buffer.from("<html>"); },
    }),
  });
  await assert.rejects(wrongType.loadSoundImages([ids[0]]), /SOUND_EVIDENCE_INVALID_IMAGE/);
});

test("sound evidence loader fails closed before reading oversized responses", async () => {
  let read = false;
  const evidence = createCloudbaseSoundEvidence({
    env: { CLOUDBASE_ENV_ID: "test-env" },
    cloudbaseApp: appWithUrls({ [ids[0]]: "https://storage.example/huge.jpg" }),
    fetchImpl: async () => ({
      ok: true,
      headers: new Headers({ "content-type": "image/jpeg", "content-length": String(1024 * 1024 + 1) }),
      async arrayBuffer() { read = true; return Buffer.alloc(1024 * 1024 + 1); },
    }),
  });
  await assert.rejects(evidence.loadSoundImages([ids[0]]), /SOUND_EVIDENCE_IMAGE_TOO_LARGE/);
  assert.equal(read, false);
});
