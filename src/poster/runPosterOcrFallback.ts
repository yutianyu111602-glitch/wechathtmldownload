import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { promisify } from "node:util";

import type {
  AssetsLocalJson,
  PosterCandidate,
  PosterOcrBlock,
  PosterOcrResult,
} from "../archive/types.js";

interface RunPosterOcrOptions {
  bundleDir: string;
  mainText: string;
  localAssets: AssetsLocalJson | null;
}

interface PosterOcrDependencies {
  runImageOcr?: (imagePath: string) => Promise<string>;
  convertGifToStaticImage?: (gifPath: string, outputPath: string) => Promise<string | null>;
}

const execFileAsync = promisify(execFile);
const OCR_STATIC_IMAGE_SUFFIXES = new Set([".jpg", ".jpeg", ".png"]);
const OCR_GIF_SUFFIXES = new Set([".gif"]);

interface ParsedOcrCommandOutput {
  backend?: string;
  plainText: string;
  blocks: PosterOcrBlock[];
}

interface RawOcrOutput {
  backend?: string;
  text: string;
}

function isWslCommand(command: string): boolean {
  const normalized = command.replace(/\\/g, "/").toLowerCase();
  const executable = normalized.split("/").pop() || normalized;
  return executable === "wsl" || executable === "wsl.exe";
}

function isPowerShellScriptCommand(command: string): boolean {
  return command.replace(/\\/g, "/").toLowerCase().endsWith(".ps1");
}

export function buildOcrCommandInvocation(
  ocrCommand: string,
  imagePath: string,
): { command: string; args: string[] } | null {
  const [command, ...baseArgs] = ocrCommand.split(/\s+/).filter(Boolean);
  if (!command) {
    return null;
  }

  const commandImagePath = normalizeOcrImagePathForCommand(command, imagePath);
  if (process.platform === "win32" && isPowerShellScriptCommand(command)) {
    return {
      command: process.env.WECHAT_POWERSHELL_EXE?.trim() || "powershell.exe",
      args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", command, ...baseArgs, commandImagePath],
    };
  }

  return {
    command,
    args: [...baseArgs, commandImagePath],
  };
}

export function normalizeOcrImagePathForCommand(command: string, imagePath: string): string {
  if (!isWslCommand(command)) {
    return imagePath;
  }
  const match = imagePath.match(/^([a-zA-Z]):[\\/](.*)$/);
  if (!match) {
    return imagePath;
  }
  const drive = match[1].toLowerCase();
  const rest = match[2].replace(/\\/g, "/");
  return `/mnt/${drive}/${rest}`;
}

function dedupe(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function extractRecoveredFields(rawText: string) {
  const lines = rawText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const dateTexts = dedupe(lines.filter((line) => /\d{4}[-./年]\d{1,2}[-./月]\d{1,2}/.test(line)));
  const lineupLines = dedupe(lines.filter((line) => /DJ|LIVE|ACT|VJ/i.test(line)));
  return {
    venue_name_candidate: lines.find((line) => /club|venue|room|space/i.test(line)) || "",
    date_texts: dateTexts,
    lineup_lines: lineupLines,
  };
}

async function defaultRunImageOcr(imagePath: string): Promise<RawOcrOutput> {
  const ocrCommand = process.env.WECHAT_OCR_COMMAND?.trim();
  if (ocrCommand) {
    const invocation = buildOcrCommandInvocation(ocrCommand, imagePath);
    if (invocation) {
      try {
        const { stdout } = await execFileAsync(invocation.command, invocation.args, {
          timeout: 120000,
          windowsHide: true,
          maxBuffer: 8 * 1024 * 1024,
        });
        if (stdout.trim()) {
          return { backend: "command", text: stdout };
        }
      } catch {
        // Fall back to sidecar text.
      }
    }
  }

  try {
    const content = await readFile(`${imagePath}.ocr.txt`, "utf-8");
    return { backend: "sidecar-text", text: content };
  } catch {
    return { text: "" };
  }
}

function stripMarkdownCodeFence(value: string): string {
  const trimmed = value.trim();
  const match = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return match ? match[1].trim() : trimmed;
}

function buildBlocksFromLines(rawText: string): PosterOcrBlock[] {
  return rawText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((text) => ({
      text,
      score: 1,
    }));
}

function normalizeBlocks(value: unknown): PosterOcrBlock[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const blocks: PosterOcrBlock[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const record = item as Record<string, unknown>;
    const text =
      typeof record.text === "string"
        ? record.text.trim()
        : typeof record.value === "string"
          ? record.value.trim()
          : "";
    if (!text) {
      continue;
    }
    blocks.push({
      text,
      score:
        typeof record.score === "number" && Number.isFinite(record.score)
          ? record.score
          : undefined,
      box: Array.isArray(record.box) ? (record.box as number[][]) : undefined,
    });
  }
  return blocks;
}

function parseOcrCommandOutput(output: string): ParsedOcrCommandOutput {
  const normalized = stripMarkdownCodeFence(output);
  if (!normalized) {
    return {
      plainText: "",
      blocks: [],
    };
  }

  try {
    const parsed = JSON.parse(normalized) as Record<string, unknown>;
    const explicitPlainText =
      typeof parsed.plain_text === "string"
        ? parsed.plain_text.trim()
        : typeof parsed.text === "string"
          ? parsed.text.trim()
          : "";
    const blocks = normalizeBlocks(parsed.blocks);
    const plainText =
      explicitPlainText ||
      blocks.map((block) => block.text).join("\n").trim() ||
      normalized;
    return {
      backend: typeof parsed.backend === "string" ? parsed.backend.trim() : undefined,
      plainText,
      blocks: blocks.length > 0 ? blocks : buildBlocksFromLines(plainText),
    };
  } catch {
    return {
      plainText: normalized,
      blocks: buildBlocksFromLines(normalized),
    };
  }
}

function buildBlocks(rawText: string): PosterOcrBlock[] {
  return rawText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((text) => ({
      text,
      score: 1,
    }));
}

function normalizedImageSuffix(localPath: string): string {
  const normalizedPath = localPath.split(/[?#]/, 1)[0]?.toLowerCase() || "";
  return normalizedPath.includes(".")
    ? normalizedPath.slice(normalizedPath.lastIndexOf("."))
    : "";
}

function isStaticOcrImageCandidate(localPath: string, contentType: string): boolean {
  const suffix = normalizedImageSuffix(localPath);
  if (suffix && !OCR_STATIC_IMAGE_SUFFIXES.has(suffix)) {
    return false;
  }
  const normalizedType = contentType.trim().toLowerCase();
  if (normalizedType && !["image/jpeg", "image/jpg", "image/png"].includes(normalizedType)) {
    return false;
  }
  return Boolean(localPath.trim());
}

function isGifOcrImageCandidate(localPath: string, contentType: string): boolean {
  const suffix = normalizedImageSuffix(localPath);
  const normalizedType = contentType.trim().toLowerCase();
  return Boolean(localPath.trim()) && (OCR_GIF_SUFFIXES.has(suffix) || normalizedType === "image/gif");
}

function convertedGifFramePath(bundleDir: string, assetId: string, localPath: string): string {
  const hash = createHash("sha256")
    .update(`${assetId}\0${localPath}`)
    .digest("hex")
    .slice(0, 16);
  return join(bundleDir, ".poster_ocr_frames", `${hash}.jpg`);
}

async function defaultConvertGifToStaticImage(
  gifPath: string,
  outputPath: string,
): Promise<string | null> {
  await mkdir(dirname(outputPath), { recursive: true });
  const ffmpeg = process.env.WECHAT_FFMPEG_EXE?.trim() || "ffmpeg";
  try {
    await execFileAsync(
      ffmpeg,
      [
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        gifPath,
        "-frames:v",
        "1",
        outputPath,
      ],
      {
        timeout: 60000,
        windowsHide: true,
        maxBuffer: 4 * 1024 * 1024,
      },
    );
    return outputPath;
  } catch {
    return null;
  }
}

async function buildPosterCandidates(
  options: RunPosterOcrOptions,
  dependencies: PosterOcrDependencies,
): Promise<PosterCandidate[]> {
  const imageHeavy = options.mainText.trim().length < 280;
  const images = options.localAssets?.images ?? [];
  const convertGifToStaticImage =
    dependencies.convertGifToStaticImage || defaultConvertGifToStaticImage;
  const candidates: PosterCandidate[] = [];

  for (const asset of images) {
    if (isStaticOcrImageCandidate(asset.local_path, asset.content_type)) {
      candidates.push({
        asset_id: asset.asset_id,
        local_path: asset.local_path,
        score: (asset.file_size || 0) + (asset.content_type.startsWith("image/") ? 5000 : 0),
      });
      continue;
    }

    if (!isGifOcrImageCandidate(asset.local_path, asset.content_type)) {
      continue;
    }

    const gifPath = join(options.bundleDir, asset.local_path);
    const outputPath = convertedGifFramePath(options.bundleDir, asset.asset_id, asset.local_path);
    const convertedPath = await convertGifToStaticImage(gifPath, outputPath);
    if (!convertedPath) {
      continue;
    }
    candidates.push({
      asset_id: `${asset.asset_id}:gif-frame`,
      local_path: relative(options.bundleDir, convertedPath),
      score: (asset.file_size || 0) + 5000,
    });
  }

  return candidates
    .sort((left, right) => right.score - left.score)
    .slice(0, imageHeavy ? 4 : 2);
}

export async function runPosterOcrFallback(
  options: RunPosterOcrOptions,
  dependencies: PosterOcrDependencies = {},
): Promise<PosterOcrResult> {
  const imageHeavy = options.mainText.trim().length < 280;
  const candidates = await buildPosterCandidates(options, dependencies);

  const runImageOcr = dependencies.runImageOcr;
  const recoveredOutputs: ParsedOcrCommandOutput[] = [];
  for (const candidate of candidates) {
    const imagePath = join(options.bundleDir, candidate.local_path);
    const rawOutput = runImageOcr
      ? { text: await runImageOcr(imagePath) }
      : await defaultRunImageOcr(imagePath);
    const parsed = parseOcrCommandOutput(rawOutput.text);
    if (!parsed.backend && rawOutput.backend) {
      parsed.backend = rawOutput.backend;
    }
    recoveredOutputs.push(parsed);
  }

  const plainText = recoveredOutputs
    .map((item) => item.plainText)
    .filter(Boolean)
    .join("\n")
    .trim();
  const commandBackends = dedupe(
    recoveredOutputs.map((item) => item.backend || "").filter(Boolean),
  );
  const blocks = recoveredOutputs.flatMap((item) => item.blocks);
  const recovered = extractRecoveredFields(plainText);
  return {
    backend: plainText ? commandBackends[0] || "command-or-sidecar" : "none",
    image_path: candidates[0] ? join(options.bundleDir, candidates[0].local_path) : "",
    blocks: blocks.length > 0 ? blocks : buildBlocks(plainText),
    plain_text: plainText,
    imageHeavy,
    candidates,
    recovered,
    warnings: imageHeavy && candidates.length === 0 ? ["image-heavy article without local poster candidates"] : [],
  };
}
