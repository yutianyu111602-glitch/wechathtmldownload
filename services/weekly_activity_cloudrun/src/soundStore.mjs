import { readFile, writeFile, rename } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_SOUND_DIR = path.resolve(moduleDir, "../data/sounds");

export function createSoundStore(options = {}) {
  const soundDir = options.soundDir || process.env.SOUND_SUBMISSIONS_DIR || DEFAULT_SOUND_DIR;
  const submissionsFile = path.join(soundDir, "submissions.json");
  let writeQueue = Promise.resolve();

  async function ensureDir() {
    // mkdir is implicit in writeFile with parent creation; no op needed
  }

  async function readAll() {
    try {
      const raw = await readFile(submissionsFile, "utf8");
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  async function writeAll(submissions) {
    // 原子写入：先写临时文件，再 rename 替换，防止并发丢失
    const tmpFile = `${submissionsFile}.tmp.${randomUUID()}`;
    await writeFile(tmpFile, JSON.stringify(submissions, null, 2), "utf8");
    await rename(tmpFile, submissionsFile);
  }

  // 串行化所有写入操作，防止 read-modify-write 竞态
  function enqueueWrite(fn) {
    const prev = writeQueue;
    let resolve;
    writeQueue = new Promise((r) => { resolve = r; });
    return prev.then(async () => {
      try {
        return await fn();
      } finally {
        resolve();
      }
    });
  }

  return {
    async submit(record) {
      return enqueueWrite(async () => {
      const submissions = await readAll();
      const entry = {
        id: `sound_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        clubName: String(record.clubName || "").trim(),
        soundFileIds: Array.isArray(record.soundFileIds) ? record.soundFileIds : [],
        soundImageCount: Number(record.soundImageCount || 0),
        paymentFileIds: Array.isArray(record.paymentFileIds) ? record.paymentFileIds : [],
        paymentImageCount: Number(record.paymentImageCount || 0),
        submittedAt: record.submittedAt || new Date().toISOString(),
        version: record.version || 4,
        status: "new",
      };
      submissions.unshift(entry);
      await writeAll(submissions);
      return { ok: true, id: entry.id, total: submissions.length };
      });
    },

    async list(options = {}) {
      const limit = Math.min(Math.max(Number(options.limit) || 50, 1), 200);
      const submissions = await readAll();
      return {
        total: submissions.length,
        items: submissions.slice(0, limit),
      };
    },

    async count() {
      const submissions = await readAll();
      return { total: submissions.length };
    },
  };
}
