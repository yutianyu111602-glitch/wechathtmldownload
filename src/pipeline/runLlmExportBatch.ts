import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";

import type { BatchSnapshot, RunLlmExportBatchOptions } from "../types.js";
import { isAbortError, throwIfAborted } from "../utils/abort.js";
import { collectFiles } from "../utils/fileDiscovery.js";
import { compactSnapshotItems } from "../utils/snapshotCompaction.js";
import { createQueueExecutor } from "../utils/queueExecutor.js";
import { runDualTrackBatch } from "./runDualTrackBatch.js";

interface MirrorResult {
  mirroredCount: number;
  sampleOutPath: string;
}

async function collectLlmFiles(rootDir: string): Promise<string[]> {
  return collectFiles(rootDir, (_filePath, fileName) => fileName === "llm_input.md");
}

export function deriveMirroredLlmOutPath(
  artifactFilePath: string,
  artifactRoot: string,
  mirrorRoot: string,
): string {
  const relativePath = relative(artifactRoot, artifactFilePath);
  const withoutFileName = relativePath.replace(/[/\\]llm_input\.md$/i, "");
  return `${join(mirrorRoot, withoutFileName)}.md`;
}

export async function mirrorLlmInputTree(
  artifactRoot: string,
  mirrorRoot: string,
  signal?: AbortSignal,
  concurrency = 1,
): Promise<MirrorResult> {
  throwIfAborted(signal);
  await rm(mirrorRoot, { recursive: true, force: true });
  const llmFiles = await collectLlmFiles(artifactRoot);

  if (concurrency > 1) {
    const executor = createQueueExecutor({ concurrency });
    for (const filePath of llmFiles) {
      if (signal?.aborted) break;
      const outPath = deriveMirroredLlmOutPath(filePath, artifactRoot, mirrorRoot);
      executor.add(filePath, async () => {
        throwIfAborted(signal);
        await mkdir(dirname(outPath), { recursive: true });
        await cp(filePath, outPath, { force: true });
      });
    }
    await executor.onIdle();
  } else {
    for (const filePath of llmFiles) {
      throwIfAborted(signal);
      const outPath = deriveMirroredLlmOutPath(
        filePath,
        artifactRoot,
        mirrorRoot,
      );
      await mkdir(dirname(outPath), { recursive: true });
      await cp(filePath, outPath, { force: true });
    }
  }

  return {
    mirroredCount: llmFiles.length,
    sampleOutPath: llmFiles[0]
      ? deriveMirroredLlmOutPath(llmFiles[0], artifactRoot, mirrorRoot)
      : "",
  };
}

export async function runLlmExportBatch(
  options: RunLlmExportBatchOptions,
): Promise<BatchSnapshot> {
  const outRoot = resolve(options.outRoot);
  const mirrorRoot = resolve(options.mirrorRoot);

  const snapshot = await runDualTrackBatch({
    inputRoot: resolve(options.inputRoot),
    outRoot,
    statusPath: options.statusPath,
    resume: options.resume,
    inputMode: options.inputMode,
    manifestPath: options.manifestPath,
    signal: options.signal,
    concurrency: options.concurrency,
    onSnapshot: options.onSnapshot,
  });

  if (
    snapshot.status !== "running" &&
    snapshot.status !== "completed" &&
    snapshot.status !== "cancelled"
  ) {
    return snapshot;
  }

  try {
    if (!options.signal?.aborted) {
      const mirrorStarted: BatchSnapshot = {
        ...snapshot,
        currentFile: "",
        currentPhase: "mirror_llm_md",
      };
      if (mirrorStarted.items.length > 0) {
        const activeItem =
          mirrorStarted.items.find((item) => item.status === "running") ||
          mirrorStarted.items.find((item) => item.status === "succeeded");
        if (activeItem) {
          activeItem.phase = "mirror_llm_md";
          activeItem.message = `Mirroring llm_input.md files to ${mirrorRoot}`;
        }
      }
      await options.onSnapshot?.(compactSnapshotItems(mirrorStarted));
      await mirrorLlmInputTree(outRoot, mirrorRoot, options.signal, options.concurrency);
    }
  } catch (error) {
    if (!isAbortError(error)) {
      throw error;
    }
  }

  return snapshot;
}
