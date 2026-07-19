const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 1024 * 1024;
const ALLOWED_MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

function evidenceError(code, message, cause = null) {
  const error = Object.assign(new Error(`${code}: ${message}`), { code, statusCode: 422 });
  if (cause) error.cause = cause;
  return error;
}

function normalizedMime(value) {
  return String(value || "").split(";", 1)[0].trim().toLowerCase();
}

function matchesMagic(mimeType, data) {
  if (mimeType === "image/jpeg") {
    return data.length >= 3 && data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff;
  }
  if (mimeType === "image/png") {
    return data.length >= 8 && data.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  }
  if (mimeType === "image/webp") {
    return data.length >= 12
      && data.subarray(0, 4).toString("ascii") === "RIFF"
      && data.subarray(8, 12).toString("ascii") === "WEBP";
  }
  return false;
}

function resultFileList(result) {
  if (Array.isArray(result?.fileList)) return result.fileList;
  if (Array.isArray(result?.data?.fileList)) return result.data.fileList;
  return [];
}

function resultFileId(entry) {
  return String(entry?.fileID || entry?.fileId || entry?.file_id || "");
}

function resultTempUrl(entry) {
  return String(entry?.tempFileURL || entry?.tempFileUrl || entry?.download_url || "");
}

async function readBoundedBody(response, limit) {
  const declared = Number.parseInt(String(response?.headers?.get?.("content-length") || ""), 10);
  if (Number.isFinite(declared) && declared > limit) {
    throw evidenceError("SOUND_EVIDENCE_IMAGE_TOO_LARGE", `Image exceeds ${limit} bytes`);
  }

  if (response?.body && typeof response.body.getReader === "function") {
    const reader = response.body.getReader();
    const chunks = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = Buffer.from(value);
        total += chunk.length;
        if (total > limit) throw evidenceError("SOUND_EVIDENCE_IMAGE_TOO_LARGE", `Image exceeds ${limit} bytes`);
        chunks.push(chunk);
      }
    } finally {
      reader.releaseLock?.();
    }
    return Buffer.concat(chunks, total);
  }

  const data = Buffer.from(await response.arrayBuffer());
  if (data.length > limit) throw evidenceError("SOUND_EVIDENCE_IMAGE_TOO_LARGE", `Image exceeds ${limit} bytes`);
  return data;
}

export function createCloudbaseSoundEvidence({
  env = process.env,
  cloudbaseApp = null,
  fetchImpl = globalThis.fetch,
} = {}) {
  let appPromise = null;
  const downloadTimeoutMs = Math.min(60_000, Math.max(1_000, Number.parseInt(String(env.SOUND_EVIDENCE_DOWNLOAD_TIMEOUT_MS || "15000"), 10) || 15_000));

  async function app() {
    if (cloudbaseApp) return cloudbaseApp;
    if (!appPromise) {
      const envId = String(env.CLOUDBASE_ENV_ID || "").trim();
      if (!envId) throw evidenceError("SOUND_EVIDENCE_NOT_CONFIGURED", "CloudBase environment id is missing");
      appPromise = import("@cloudbase/js-sdk")
        .then((module) => {
          const cloudbase = module.default || module;
          return cloudbase.init({ env: envId });
        })
        .catch((error) => {
          appPromise = null;
          throw evidenceError("SOUND_EVIDENCE_NOT_CONFIGURED", "CloudBase storage client is unavailable", error);
        });
    }
    return appPromise;
  }

  async function resolveTempUrls(fileIds) {
    const unique = [...new Set(fileIds.map((value) => String(value || "")))];
    if (!unique.length) return new Map();
    const client = await app();
    if (typeof client?.getTempFileURL !== "function") {
      throw evidenceError("SOUND_EVIDENCE_NOT_CONFIGURED", "CloudBase temporary URL API is unavailable");
    }
    let result;
    try {
      result = await client.getTempFileURL({ fileList: unique });
    } catch (error) {
      throw evidenceError("SOUND_EVIDENCE_LOOKUP_FAILED", "Cloud storage evidence lookup failed", error);
    }
    const resultCode = String(result?.code || "").trim().toUpperCase();
    if (resultCode && resultCode !== "SUCCESS" && resultCode !== "0") {
      throw evidenceError("SOUND_EVIDENCE_LOOKUP_FAILED", "Cloud storage evidence lookup was rejected");
    }
    const resolved = new Map();
    for (const entry of resultFileList(result)) {
      const fileId = resultFileId(entry);
      const tempUrl = resultTempUrl(entry);
      const statusOk = entry?.status === undefined || Number(entry.status) === 0;
      const code = String(entry?.code || "").trim().toUpperCase();
      const codeOk = !code || code === "0" || code === "SUCCESS";
      if (!unique.includes(fileId) || !statusOk || !codeOk) continue;
      try {
        const parsed = new URL(tempUrl);
        if (parsed.protocol === "https:") resolved.set(fileId, tempUrl);
      } catch {
        // An invalid or non-HTTPS URL is treated as unresolved below.
      }
    }
    for (const fileId of unique) {
      if (!resolved.has(fileId)) {
        throw evidenceError("SOUND_EVIDENCE_OBJECT_UNAVAILABLE", "One or more evidence objects could not be resolved");
      }
    }
    return resolved;
  }

  return {
    async verifySubmissionFiles({ soundFileIds = [], paymentFileIds = [] } = {}) {
      await resolveTempUrls([...soundFileIds, ...paymentFileIds]);
    },

    async loadSoundImages(fileIds = []) {
      if (!Array.isArray(fileIds) || !fileIds.length) {
        throw evidenceError("SOUND_EVIDENCE_REQUIRED", "Sound-system images are required");
      }
      if (fileIds.length > MAX_IMAGES) {
        throw evidenceError("SOUND_EVIDENCE_TOO_MANY_IMAGES", `At most ${MAX_IMAGES} sound images may be analyzed`);
      }
      if (typeof fetchImpl !== "function") {
        throw evidenceError("SOUND_EVIDENCE_NOT_CONFIGURED", "Image download is unavailable");
      }
      const urls = await resolveTempUrls(fileIds);
      const images = [];
      for (const fileId of fileIds) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), downloadTimeoutMs);
        try {
          const response = await fetchImpl(urls.get(fileId), {
            method: "GET",
            redirect: "error",
            headers: { accept: "image/jpeg,image/png,image/webp" },
            signal: controller.signal,
          });
          if (!response?.ok) {
            throw evidenceError("SOUND_EVIDENCE_DOWNLOAD_FAILED", `Sound image download returned HTTP ${response?.status || "unknown"}`);
          }
          const mimeType = normalizedMime(response.headers?.get?.("content-type"));
          if (!ALLOWED_MIME_TYPES.has(mimeType)) {
            throw evidenceError("SOUND_EVIDENCE_INVALID_IMAGE", "Sound evidence is not an allowed image type");
          }
          const data = await readBoundedBody(response, MAX_IMAGE_BYTES);
          if (!matchesMagic(mimeType, data)) {
            throw evidenceError("SOUND_EVIDENCE_INVALID_IMAGE", "Sound evidence bytes do not match the declared image type");
          }
          images.push({ mimeType, data });
        } catch (error) {
          if (error?.code) throw error;
          throw evidenceError("SOUND_EVIDENCE_DOWNLOAD_FAILED", "Sound image download failed", error);
        } finally {
          clearTimeout(timeout);
        }
      }
      return images;
    },
  };
}

export const SOUND_EVIDENCE_LIMITS = Object.freeze({ maxImages: MAX_IMAGES, maxImageBytes: MAX_IMAGE_BYTES });
