import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";

import { ensureDir, writeJson } from "../utils/fs.js";

export interface ArtifactEntry {
  fileName: string;
  relativePath: string;
  sha256: string;
  size: number;
}

export interface ArtifactManifest {
  articleId: string;
  inputPath: string;
  generatedAt: string;
  requiredOutputs: ArtifactEntry[];
  optionalOutputs: ArtifactEntry[];
  schemaVersion: string;
}

export const REQUIRED_ARTIFACTS = [
  "meta.json",
  "assets.json",
  "rule_extract.json",
  "llm_input.md",
  "sidecar.json",
  "quality_report.json",
];

export const OPTIONAL_ARTIFACTS = [
  "clean.md",
  "markitdown.raw.md",
  "markitdown.cleaned.md",
  "background_recall.md",
  "sidecar.md",
  "poster_ocr.json",
  "markitdown_warnings.json",
];

async function computeSha256(filePath: string): Promise<string> {
  const buffer = await readFile(filePath);
  return createHash("sha256").update(buffer).digest("hex");
}

export async function writeArtifactManifest(
  options: {
    outDir: string;
    articleId: string;
    inputPath: string;
    schemaVersion?: string;
  },
): Promise<ArtifactManifest> {
  const { outDir, articleId, inputPath } = options;
  const schemaVersion = options.schemaVersion ?? "v1";
  const generatedAt = new Date().toISOString();

  const requiredOutputs: ArtifactEntry[] = [];
  for (const fileName of REQUIRED_ARTIFACTS) {
    const filePath = join(outDir, fileName);
    try {
      const sha256 = await computeSha256(filePath);
      const stats = await import("node:fs/promises").then((fs) => fs.stat(filePath));
      requiredOutputs.push({
        fileName,
        relativePath: fileName,
        sha256,
        size: stats.size,
      });
    } catch {
      // Skip missing required artifacts; validation will catch this
    }
  }

  const optionalOutputs: ArtifactEntry[] = [];
  for (const fileName of OPTIONAL_ARTIFACTS) {
    const filePath = join(outDir, fileName);
    try {
      const sha256 = await computeSha256(filePath);
      const stats = await import("node:fs/promises").then((fs) => fs.stat(filePath));
      optionalOutputs.push({
        fileName,
        relativePath: fileName,
        sha256,
        size: stats.size,
      });
    } catch {
      // Optional artifact may legitimately be missing
    }
  }

  const manifest: ArtifactManifest = {
    articleId,
    inputPath,
    generatedAt,
    requiredOutputs,
    optionalOutputs,
    schemaVersion,
  };

  await writeJson(join(outDir, "artifact_manifest.json"), manifest);
  return manifest;
}

export async function readArtifactManifest(
  outDir: string,
): Promise<ArtifactManifest | null> {
  try {
    const text = await readFile(join(outDir, "artifact_manifest.json"), "utf-8");
    return JSON.parse(text) as ArtifactManifest;
  } catch {
    return null;
  }
}

export async function validateArtifactManifest(
  manifest: ArtifactManifest,
  outDir: string,
): Promise<{ valid: boolean; missing: string[]; mismatched: string[] }> {
  const missing: string[] = [];
  const mismatched: string[] = [];

  for (const entry of manifest.requiredOutputs) {
    const filePath = join(outDir, entry.relativePath);
    try {
      const actualSha256 = await computeSha256(filePath);
      if (actualSha256 !== entry.sha256) {
        mismatched.push(entry.fileName);
      }
    } catch {
      missing.push(entry.fileName);
    }
  }

  return {
    valid: missing.length === 0 && mismatched.length === 0,
    missing,
    mismatched,
  };
}

export async function shouldSkipOnResume(
  outDir: string,
  articleId?: string,
): Promise<{ skip: boolean; reason: string }> {
  const manifest = await readArtifactManifest(outDir);
  if (!manifest) {
    return { skip: false, reason: "No artifact_manifest.json found" };
  }

  if (articleId && manifest.articleId !== articleId) {
    return { skip: false, reason: `Article ID mismatch: ${manifest.articleId} vs ${articleId}` };
  }

  // Fast-resume mode: trust manifest existence, skip SHA256 validation.
  // Cuts initial scan time on large batches from ~30min to ~1min on HDD.
  if (process.env.WECHAT_RESUME_FAST === "1") {
    return { skip: true, reason: "Fast-resume: manifest present (sha256 check skipped)" };
  }

  const validation = await validateArtifactManifest(manifest, outDir);
  if (!validation.valid) {
    const reasons: string[] = [];
    if (validation.missing.length > 0) {
      reasons.push(`missing: ${validation.missing.join(", ")}`);
    }
    if (validation.mismatched.length > 0) {
      reasons.push(`mismatched: ${validation.mismatched.join(", ")}`);
    }
    return { skip: false, reason: reasons.join("; ") };
  }

  return { skip: true, reason: "All required artifacts present and valid" };
}
