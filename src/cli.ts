import { basename, resolve } from "node:path";
import { readFile } from "node:fs/promises";

import { runAccountUrlPrefetch } from "./accounts/runAccountUrlPrefetch.js";
import { archiveArticle } from "./archive/archiveArticle.js";
import { downloadArticleAssets } from "./archive/downloadArticleAssets.js";
import { extractIncompleteArchiveQueue } from "./archive/extractIncompleteArchiveQueue.js";
import { filterDajialaRepairCandidates } from "./archive/filterDajialaRepairCandidates.js";
import { runArchiveBatch } from "./archive/runArchiveBatch.js";
import { runAssetDownloadBatch } from "./archive/runAssetDownloadBatch.js";
import { runDajialaArchiveRepairBatch } from "./archive/runDajialaArchiveRepairBatch.js";
import { runMptextArchiveBatch } from "./archive/runMptextArchiveBatch.js";
import type { ArchiveQueueRecord } from "./archive/types.js";
import { finalizeLlmPack } from "./artifacts/finalizeLlmPack.js";
import type { FinalLlmQualityGrade } from "./artifacts/types.js";
import { runArchiveAudit } from "./artifacts/runArchiveAudit.js";
import { buildGraphCandidatePack } from "./graph/graphCandidatePack.js";
import { runIgnukeDryRunImport } from "./ignuke/dryRunImport.js";
import { runDownstreamLlmBatch } from "./llm/runDownstreamLlmBatch.js";
import { runDownstreamLlmStage } from "./llm/runDownstreamLlmStage.js";
import {
  assertNoRunningArchiveAssets,
  assertNoRunningLlmExport,
} from "./ops/archiveAssetRunGuard.js";
import { assertNoRunningMptextArchive } from "./ops/archiveRunGuard.js";
import { withLiveStageLockIfProduction } from "./ops/liveStageLock.js";
import { registerPack, type RegisteredPackType } from "./packs/packRegistry.js";
import { processArticle } from "./pipeline/processArticle.js";
import { processArchiveBundleDualTrack } from "./pipeline/processArchiveBundleDualTrack.js";
import { processArticleDualTrack } from "./pipeline/processArticleDualTrack.js";
import { runLlmExportBatch } from "./pipeline/runLlmExportBatch.js";
import { runMarkitdownBatch } from "./pipeline/runMarkitdownBatch.js";
import { runDualTrackBatch } from "./pipeline/runDualTrackBatch.js";
import { splitManifestIntoShards } from "./pipeline/shardManifest.js";
import { runPosterOcrBatch } from "./poster/runPosterOcrBatch.js";
import {
  createRunnerJobPack,
  validateRunnerResultPack,
} from "./runners/runnerPack.js";
import type { StageRunnerId } from "./stage/contracts.js";
import type { BatchSnapshot } from "./types.js";

interface CliArgs {
  command: string;
  input: string;
  inputDir: string;
  outDir: string;
  mirrorDir: string;
  statusPath: string;
  resultLogPath: string;
  statePath: string;
  manifestPath: string;
  intakeManifestPath: string;
  auditItems: string;
  artifactRoot: string;
  artifactListPath: string;
  archiveRoot: string;
  intakeOnly: boolean;
  accountsPath: string;
  queuePath: string;
  endpoint: string;
  key: string;
  fallbackEndpoint: string;
  fallbackKey: string;
  formats: string;
  statuses: string;
  concurrency: number;
  concurrencyProvided: boolean;
  requestDelayMs?: number;
  accountConcurrency: number;
  maxPages?: number;
  limitAccounts?: number;
  inputMode: "html" | "archive";
  stageName: string;
  onlyQuality: string;
  runnerId: StageRunnerId;
  schemaVersion: string;
  promptId: string;
  promptPath: string;
  modelId: string;
  paramsJson: string;
  paramsPath: string;
  packType: string;
  packId: string;
  sourcePackId: string;
  limit?: number;
  shardSize: number;
  resume: boolean;
  once: boolean;
  noFallback: boolean;
  deferExistingPartialOnResume: boolean;
  requireSignedLongLink: boolean;
}

function parseArgs(argv: string[]): CliArgs {
  const [first = "", ...restArgs] = argv;
  const command = first.startsWith("--") ? "process-article" : first;
  const rest = first.startsWith("--") ? argv : restArgs;
  let input = "";
  let inputDir = "";
  let outDir = "";
  let mirrorDir = "";
  let statusPath = "";
  let resultLogPath = "";
  let statePath = "";
  let manifestPath = "";
  let intakeManifestPath = "";
  let auditItems = "";
  let artifactRoot = "";
  let artifactListPath = "";
  let archiveRoot = "";
  let intakeOnly = false;
  let accountsPath = "";
  let queuePath = "";
  let endpoint = "";
  let key = "";
  let fallbackEndpoint = "";
  let fallbackKey = "";
  let formats = "";
  let statuses = "";
  let concurrency = 3;
  let concurrencyProvided = false;
  let requestDelayMs: number | undefined;
  let accountConcurrency = 2;
  let maxPages: number | undefined;
  let limitAccounts: number | undefined;
  let inputMode: "html" | "archive" = "html";
  let stageName = "entity_extract";
  let onlyQuality = "";
  let runnerId: StageRunnerId = "windows-4090";
  let schemaVersion = "";
  let promptId = "default";
  let promptPath = "";
  let modelId = "";
  let paramsJson = "";
  let paramsPath = "";
  let packType = "";
  let packId = "";
  let sourcePackId = "";
  let limit: number | undefined;
  let shardSize = 5000;
  let resume = false;
  let once = false;
  let noFallback = false;
  let deferExistingPartialOnResume = false;
  let requireSignedLongLink = false;
  const positional: string[] = [];

  for (let index = 0; index < rest.length; index += 1) {
    const arg = rest[index];
    if (arg === "--input") {
      input = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--outDir") {
      outDir = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--inputDir") {
      inputDir = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--statusPath") {
      statusPath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--resultLogPath") {
      resultLogPath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--mirrorDir") {
      mirrorDir = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--statePath") {
      statePath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--manifestPath") {
      manifestPath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--intakeManifestPath") {
      intakeManifestPath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--intakeOnly" || arg === "--skipArtifactRootScan") {
      intakeOnly = true;
      continue;
    }

    if (arg === "--auditItems") {
      auditItems = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--artifactRoot") {
      artifactRoot = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--artifactListPath") {
      artifactListPath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--archiveRoot") {
      archiveRoot = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--accountsPath") {
      accountsPath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--queuePath") {
      queuePath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--endpoint") {
      endpoint = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--key") {
      key = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--fallbackEndpoint") {
      fallbackEndpoint = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--fallbackKey") {
      fallbackKey = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--formats") {
      formats = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--statuses") {
      statuses = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--concurrency") {
      const parsed = Number(rest[index + 1]);
      if (Number.isFinite(parsed) && parsed > 0) {
        concurrency = parsed;
        concurrencyProvided = true;
      }
      index += 1;
      continue;
    }

    if (arg === "--requestDelayMs") {
      const parsed = Number(rest[index + 1]);
      if (Number.isFinite(parsed) && parsed >= 0) {
        requestDelayMs = parsed;
      }
      index += 1;
      continue;
    }

    if (arg === "--accountConcurrency") {
      const parsed = Number(rest[index + 1]);
      if (Number.isFinite(parsed) && parsed > 0) {
        accountConcurrency = parsed;
      }
      index += 1;
      continue;
    }

    if (arg === "--maxPages") {
      const parsed = Number(rest[index + 1]);
      if (Number.isFinite(parsed) && parsed > 0) {
        maxPages = parsed;
      }
      index += 1;
      continue;
    }

    if (arg === "--limitAccounts") {
      const parsed = Number(rest[index + 1]);
      if (Number.isFinite(parsed) && parsed > 0) {
        limitAccounts = parsed;
      }
      index += 1;
      continue;
    }

    if (arg === "--inputMode") {
      inputMode = rest[index + 1] === "archive" ? "archive" : "html";
      index += 1;
      continue;
    }

    if (arg === "--stageName") {
      stageName = rest[index + 1] ?? stageName;
      index += 1;
      continue;
    }

    if (arg === "--onlyQuality") {
      onlyQuality = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--runnerId") {
      const parsed = rest[index + 1] ?? "windows-4090";
      runnerId =
        parsed === "mac-m3pro" || parsed === "cloud-5090"
          ? parsed
          : "windows-4090";
      index += 1;
      continue;
    }

    if (arg === "--schemaVersion") {
      schemaVersion = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--promptId") {
      promptId = rest[index + 1] ?? promptId;
      index += 1;
      continue;
    }

    if (arg === "--promptPath") {
      promptPath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--modelId") {
      modelId = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--paramsJson") {
      paramsJson = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--paramsPath") {
      paramsPath = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--packType") {
      packType = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--packId") {
      packId = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--sourcePackId") {
      sourcePackId = rest[index + 1] ?? "";
      index += 1;
      continue;
    }

    if (arg === "--limit") {
      const parsed = Number(rest[index + 1]);
      if (Number.isFinite(parsed) && parsed > 0) {
        limit = parsed;
      }
      index += 1;
      continue;
    }

    if (arg === "--shardSize") {
      const parsed = Number(rest[index + 1]);
      if (Number.isFinite(parsed) && parsed > 0) {
        shardSize = parsed;
      }
      index += 1;
      continue;
    }

    if (arg === "--resume") {
      resume = true;
      continue;
    }

    if (arg === "--once") {
      once = true;
      continue;
    }

    if (arg === "--noFallback") {
      noFallback = true;
      continue;
    }

    if (arg === "--deferExistingPartialOnResume") {
      deferExistingPartialOnResume = true;
      continue;
    }

    if (arg === "--requireSignedLongLink") {
      requireSignedLongLink = true;
      continue;
    }

    positional.push(arg);
  }

  if (!input) {
    input = positional[0] ?? "";
  }
  if (!inputDir) {
    inputDir = positional[0] ?? "";
  }
  if (!outDir) {
    outDir = positional[1] ?? "";
  }
  if (command === "prefetch-account-urls") {
    if (!accountsPath) {
      accountsPath = positional[0] ?? "";
    }
    if (!outDir) {
      outDir = positional[1] ?? "";
    }
    if (positional[2]) {
      const parsed = Number(positional[2]);
      if (Number.isFinite(parsed) && parsed > 0) {
        accountConcurrency = parsed;
      }
    }
    if (positional[3]) {
      const parsed = Number(positional[3]);
      if (Number.isFinite(parsed) && parsed > 0) {
        maxPages = parsed;
      }
    }
    if (positional[4]) {
      const parsed = Number(positional[4]);
      if (Number.isFinite(parsed) && parsed > 0) {
        limitAccounts = parsed;
      }
    }
  }
  if (positional.length >= 3 && (positional[2] === "archive" || positional[2] === "html")) {
    inputMode = positional[2] as "html" | "archive";
  }

  return {
    command,
    input,
    inputDir,
    outDir,
    mirrorDir,
    statusPath,
    resultLogPath,
    statePath,
    manifestPath,
    intakeManifestPath,
    auditItems,
    artifactRoot,
    artifactListPath,
    archiveRoot,
    intakeOnly,
    accountsPath,
    queuePath,
    endpoint,
    key,
    fallbackEndpoint,
    fallbackKey,
    formats,
    statuses,
    concurrency,
    concurrencyProvided,
    requestDelayMs,
    accountConcurrency,
    maxPages,
    limitAccounts,
    inputMode,
    stageName,
    onlyQuality,
    runnerId,
    schemaVersion,
    promptId,
    promptPath,
    modelId,
    paramsJson,
    paramsPath,
    packType,
    packId,
    sourcePackId,
    limit,
    shardSize,
    resume,
    once,
    noFallback,
    deferExistingPartialOnResume,
    requireSignedLongLink,
  };
}

function parseQualityList(value: string): FinalLlmQualityGrade[] | undefined {
  if (!value) {
    return undefined;
  }
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item): item is FinalLlmQualityGrade =>
      item === "ready" || item === "review" || item === "blocked",
    );
}

function cliCommandText(): string {
  return process.argv.slice(2).join(" ");
}

async function parseParams(args: CliArgs): Promise<Record<string, unknown> | undefined> {
  if (args.paramsPath && args.paramsJson) {
    throw new Error("Use only one of --paramsJson or --paramsPath.");
  }
  const raw = args.paramsPath
    ? await readFile(resolve(args.paramsPath), "utf-8")
    : args.paramsJson;
  if (!raw) {
    return undefined;
  }
  const parsed = JSON.parse(raw) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Downstream params must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  if (args.command === "process-article") {
    if (!args.input || !args.outDir) {
      throw new Error(
        "Usage: process-article --input path/to/raw.html --outDir path/to/out",
      );
    }
    await processArticle(resolve(args.input), resolve(args.outDir));
    return;
  }

  if (args.command === "process-dual-track") {
    if (!args.input || !args.outDir) {
      throw new Error(
        "Usage: process-dual-track --input path/to/raw.html --outDir path/to/out",
      );
    }
    const resolvedInput = resolve(args.input);
    if (args.inputMode === "archive") {
      await processArchiveBundleDualTrack(resolvedInput, resolve(args.outDir));
    } else {
      await processArticleDualTrack(
        resolvedInput,
        resolve(args.outDir),
        (event) => {
          console.error(
            `[${event.step}/${event.totalSteps}] ${event.phase} ${event.message}`,
          );
        },
      );
    }
    return;
  }

  if (args.command === "archive-article") {
    if (!args.input || !args.outDir) {
      throw new Error(
        "Usage: archive-article --input <article-url> --outDir path/to/archive-bundle --manifestPath optional-record.json",
      );
    }

    const record: ArchiveQueueRecord = {
      account_key: "manual",
      token: "manual",
      source_url: args.input,
      title: "",
      author: "",
      cover_url: "",
      post_time: "",
      post_date: "",
      page: 1,
      discovered_at: new Date().toISOString(),
      discovery_source: "manual",
    };
    await archiveArticle(record, resolve(args.outDir));
    return;
  }

  if (args.command === "archive-batch") {
    if (!args.manifestPath || !args.outDir) {
      throw new Error(
        "Usage: archive-batch --manifestPath path/to/archive_queue.jsonl --outDir path/to/archive-root [--statusPath path/to/archive-status.json] [--resume] [--concurrency 1]",
      );
    }
    await withLiveStageLockIfProduction(
      {
        rootPath: resolve(args.outDir),
        stageName: "archive-batch",
        command: cliCommandText(),
      },
      () =>
        runArchiveBatch({
          queuePath: resolve(args.manifestPath),
          archiveRoot: resolve(args.outDir),
          statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
          resume: args.resume,
          concurrency: args.concurrencyProvided ? args.concurrency : undefined,
        }),
    );
    return;
  }

  if (args.command === "prefetch-account-urls") {
    if (!args.accountsPath || !args.outDir) {
      throw new Error(
        "Usage: prefetch-account-urls --accountsPath D:\\DDownload\\公众号.json --outDir D:\\DDownload [--endpoint http://127.0.0.1:17300] [--key <auth-key>] [--accountConcurrency 2] [--maxPages 200] [--limitAccounts 2] [--resume]",
      );
    }
    const snapshot = await runAccountUrlPrefetch({
      accountsPath: resolve(args.accountsPath),
      outDir: resolve(args.outDir),
      queuePath: args.queuePath ? resolve(args.queuePath) : undefined,
      statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
      endpoint: args.endpoint || undefined,
      key: args.key || undefined,
      accountConcurrency: args.accountConcurrency,
      maxPages: args.maxPages,
      limitAccounts: args.limitAccounts,
      resume: args.resume,
    });
    console.log(
      JSON.stringify(
        {
          statusPath: snapshot.statusPath,
          queuePath: snapshot.queuePath,
          totalAccounts: snapshot.totalAccounts,
          completedAccounts: snapshot.completedAccounts,
          totalDiscovered: snapshot.totalDiscovered,
          totalEnqueued: snapshot.totalEnqueued,
          duplicateCount: snapshot.duplicateCount,
          failedCount: snapshot.failedCount,
        },
        null,
        2,
      ),
    );
    return;
  }

  if (args.command === "download-archive-assets") {
    if (!args.input) {
      throw new Error(
        "Usage: download-archive-assets --input path/to/archive-bundle",
      );
    }
    await downloadArticleAssets(resolve(args.input));
    return;
  }

  if (args.command === "download-archive-assets-batch") {
    if (!args.inputDir || !args.manifestPath) {
      throw new Error(
        "Usage: download-archive-assets-batch --inputDir path/to/archive-root --manifestPath path/to/archive_queue.jsonl [--statusPath path/to/asset-retention-status.json] [--resultLogPath path/to/asset-retention-results.jsonl] [--resume]",
      );
    }
    await assertNoRunningMptextArchive(resolve(args.inputDir), "download-archive-assets-batch");
    await assertNoRunningArchiveAssets(
      resolve(args.inputDir),
      "download-archive-assets-batch",
      args.statusPath ? resolve(args.statusPath) : undefined,
    );
    await withLiveStageLockIfProduction(
      {
        rootPath: resolve(args.inputDir),
        stageName: "download-archive-assets-batch",
        command: cliCommandText(),
      },
      () =>
        runAssetDownloadBatch({
          archiveRoot: resolve(args.inputDir),
          manifestPath: resolve(args.manifestPath),
          statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
          resultLogPath: args.resultLogPath ? resolve(args.resultLogPath) : undefined,
          concurrency: args.concurrency,
          resume: args.resume,
        }),
    );
    return;
  }

  if (args.command === "audit-archive-run") {
    if (!args.inputDir || !args.manifestPath || !args.outDir) {
      throw new Error(
        "Usage: audit-archive-run --inputDir path/to/archive-root --manifestPath path/to/archive_queue.jsonl --outDir path/to/audit-report-dir [--resultLogPath path/to/archive-results.jsonl]",
      );
    }
    const summary = await runArchiveAudit({
      archiveRoot: resolve(args.inputDir),
      manifestPath: resolve(args.manifestPath),
      outDir: resolve(args.outDir),
      resultLogPath: args.resultLogPath ? resolve(args.resultLogPath) : undefined,
    });
    console.log(JSON.stringify(summary, null, 2));
    return;
  }

  if (args.command === "extract-incomplete-archive-queue") {
    if (!args.manifestPath || !args.inputDir || !args.outDir) {
      throw new Error(
        "Usage: extract-incomplete-archive-queue --manifestPath path/to/archive_queue.jsonl --inputDir path/to/archive-root --outDir path/to/partial_queue.jsonl [--statuses partial,failed,missing]",
      );
    }
    const result = await extractIncompleteArchiveQueue({
      manifestPath: resolve(args.manifestPath),
      archiveRoot: resolve(args.inputDir),
      outPath: resolve(args.outDir),
      statuses: args.statuses
        ? args.statuses
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean)
        : undefined,
    });
    console.log(JSON.stringify(result, null, 2));
    return;
  }

  if (args.command === "filter-dajiala-repair-candidates") {
    if (!args.auditItems || !args.outDir) {
      throw new Error(
        "Usage: filter-dajiala-repair-candidates --auditItems path/to/archive-audit-items.jsonl --outDir path/to/dajiala-candidates.jsonl [--requireSignedLongLink]",
      );
    }
    const summary = await filterDajialaRepairCandidates({
      auditItemsPath: resolve(args.auditItems),
      outPath: resolve(args.outDir),
      requireSignedLongLink: args.requireSignedLongLink,
    });
    console.log(JSON.stringify(summary, null, 2));
    return;
  }

  if (args.command === "mptext-archive-batch") {
    if (!args.manifestPath || !args.outDir) {
      throw new Error(
        "Usage: mptext-archive-batch --manifestPath path/to/archive_queue.jsonl --outDir path/to/archive-root [--endpoint http://127.0.0.1:17300] [--key <auth-key>] [--resultLogPath path/to/results.jsonl] [--fallbackEndpoint http://127.0.0.1:17301] [--fallbackKey <auth-key>] [--noFallback] [--formats html] [--concurrency 3] [--resume] [--deferExistingPartialOnResume]",
      );
    }
    await withLiveStageLockIfProduction(
      {
        rootPath: resolve(args.outDir),
        stageName: "mptext-archive-batch",
        command: cliCommandText(),
      },
      () =>
        runMptextArchiveBatch({
          manifestPath: resolve(args.manifestPath),
          archiveRoot: resolve(args.outDir),
          statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
          endpoint: args.endpoint || undefined,
          key: args.key || undefined,
          fallbackEndpoint: args.fallbackEndpoint || undefined,
          fallbackKey: args.fallbackKey || undefined,
          disableFallback: args.noFallback,
          resultLogPath: args.resultLogPath ? resolve(args.resultLogPath) : undefined,
          formats: args.formats
            ? (args.formats
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean) as Array<"html" | "json" | "markdown" | "text">)
            : undefined,
          concurrency: args.concurrency,
          resume: args.resume,
          deferExistingPartialOnResume: args.deferExistingPartialOnResume,
        }),
    );
    return;
  }

  if (args.command === "dajiala-repair-archive-batch") {
    if (!args.manifestPath || !args.outDir) {
      throw new Error(
        "Usage: dajiala-repair-archive-batch --manifestPath path/to/archive_queue.partial.jsonl --outDir path/to/archive-root [--endpoint https://www.dajiala.com] [--key <api-key>] [--concurrency 1] [--requestDelayMs 1200] [--resume]",
      );
    }
    await assertNoRunningMptextArchive(resolve(args.outDir), "dajiala-repair-archive-batch");
    await withLiveStageLockIfProduction(
      {
        rootPath: resolve(args.outDir),
        stageName: "dajiala-repair-archive-batch",
        command: cliCommandText(),
      },
      () =>
        runDajialaArchiveRepairBatch({
          manifestPath: resolve(args.manifestPath),
          archiveRoot: resolve(args.outDir),
          statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
          endpoint: args.endpoint || undefined,
          key: args.key || undefined,
          concurrency: args.concurrencyProvided ? args.concurrency : undefined,
          requestDelayMs: args.requestDelayMs,
          resultLogPath: args.resultLogPath ? resolve(args.resultLogPath) : undefined,
          resume: args.resume,
        }),
    );
    return;
  }

  if (args.command === "process-batch") {
    if (!args.inputDir || !args.outDir) {
      throw new Error(
        "Usage: process-batch --inputDir path/to/html-root --outDir path/to/out-root [--statusPath path/to/batch-status.json] [--resume]",
      );
    }

    if (args.inputMode === "archive") {
      await assertNoRunningMptextArchive(resolve(args.inputDir), "process-batch archive mode");
      await assertNoRunningArchiveAssets(resolve(args.inputDir), "process-batch archive mode");
    }
    await assertNoRunningLlmExport(resolve(args.outDir), "process-batch output root");
    await withLiveStageLockIfProduction(
      {
        rootPath: resolve(args.outDir),
        stageName: "process-batch",
        command: cliCommandText(),
      },
      () =>
        runDualTrackBatch({
          inputRoot: resolve(args.inputDir),
          outRoot: resolve(args.outDir),
          statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
          inputMode: args.inputMode,
          manifestPath: args.manifestPath ? resolve(args.manifestPath) : undefined,
          resume: args.resume,
          concurrency: args.concurrencyProvided ? args.concurrency : undefined,
          onSnapshot: (snapshot: BatchSnapshot) => {
            const currentName = snapshot.currentFile
              ? basename(snapshot.currentFile)
              : "-";
            const currentPhase = snapshot.currentPhase || "idle";
            console.error(
              `[${snapshot.completedCount}/${snapshot.totalItems}] queued=${snapshot.queuedCount} running=${snapshot.runningCount} ok=${snapshot.succeededCount} fail=${snapshot.failedCount} skip=${snapshot.skippedCount} phase=${currentPhase} file=${currentName}`,
            );
          },
        }),
    );
    return;
  }

  if (args.command === "export-markitdown-batch") {
    if (!args.inputDir || !args.outDir) {
      throw new Error(
        "Usage: export-markitdown-batch --inputDir path/to/html-root --outDir path/to/md-root [--statusPath path/to/markitdown-batch-status.json] [--resume]",
      );
    }

    await runMarkitdownBatch({
      inputRoot: resolve(args.inputDir),
      outRoot: resolve(args.outDir),
      statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
      resume: args.resume,
      onSnapshot: (snapshot) => {
        const currentName = snapshot.currentFile
          ? basename(snapshot.currentFile)
          : "-";
        console.error(
          `[${snapshot.completedCount}/${snapshot.totalItems}] ok=${snapshot.succeededCount} fail=${snapshot.failedCount} skip=${snapshot.skippedCount} file=${currentName}`,
        );
      },
    });
    return;
  }

  if (args.command === "export-llm-batch") {
    if (!args.inputDir || !args.outDir || !args.mirrorDir) {
      throw new Error(
        "Usage: export-llm-batch --inputDir path/to/html-root --outDir path/to/artifact-root --mirrorDir path/to/md-root [--statusPath path/to/batch-status.json] [--resume]",
      );
    }

    if (args.inputMode === "archive") {
      await assertNoRunningMptextArchive(resolve(args.inputDir), "export-llm-batch archive mode");
      await assertNoRunningArchiveAssets(resolve(args.inputDir), "export-llm-batch archive mode");
    }
    await assertNoRunningLlmExport(
      resolve(args.outDir),
      "export-llm-batch",
      args.statusPath ? resolve(args.statusPath) : undefined,
    );
    await withLiveStageLockIfProduction(
      {
        rootPath: resolve(args.outDir),
        stageName: "export-llm-batch",
        command: cliCommandText(),
      },
      () =>
        runLlmExportBatch({
          inputRoot: resolve(args.inputDir),
          outRoot: resolve(args.outDir),
          mirrorRoot: resolve(args.mirrorDir),
          statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
          inputMode: args.inputMode,
          manifestPath: args.manifestPath ? resolve(args.manifestPath) : undefined,
          resume: args.resume,
          concurrency: args.concurrencyProvided ? args.concurrency : undefined,
          onSnapshot: (snapshot: BatchSnapshot) => {
            const currentName = snapshot.currentFile
              ? basename(snapshot.currentFile)
              : snapshot.currentPhase === "mirror_llm_md"
                ? "mirroring"
                : "-";
            const currentPhase = snapshot.currentPhase || "idle";
            console.error(
              `[${snapshot.completedCount}/${snapshot.totalItems}] queued=${snapshot.queuedCount} running=${snapshot.runningCount} ok=${snapshot.succeededCount} fail=${snapshot.failedCount} skip=${snapshot.skippedCount} phase=${currentPhase} file=${currentName}`,
            );
          },
        }),
    );
    return;
  }

  if (args.command === "finalize-llm-pack") {
    if (!args.inputDir || !args.outDir) {
      throw new Error(
        "Usage: finalize-llm-pack --inputDir path/to/artifact-root --outDir path/to/release-root [--archiveRoot path/to/archive-root] [--manifestPath path/to/archive_queue.jsonl] [--intakeManifestPath path/to/llm_intake_manifest.json] [--intakeOnly] [--limit N]",
      );
    }
    if (args.intakeOnly && !args.intakeManifestPath) {
      throw new Error("finalize-llm-pack --intakeOnly requires --intakeManifestPath");
    }

    if (args.archiveRoot) {
      await assertNoRunningMptextArchive(resolve(args.archiveRoot), "finalize-llm-pack");
      await assertNoRunningArchiveAssets(resolve(args.archiveRoot), "finalize-llm-pack");
    }
    await assertNoRunningLlmExport(resolve(args.inputDir), "finalize-llm-pack");
    const manifest = await withLiveStageLockIfProduction(
      {
        rootPath: resolve(args.outDir),
        stageName: "finalize-llm-pack",
        command: cliCommandText(),
      },
      () =>
        finalizeLlmPack({
          artifactRoot: resolve(args.inputDir),
          releaseRoot: resolve(args.outDir),
          archiveRoot: args.archiveRoot ? resolve(args.archiveRoot) : undefined,
          manifestPath: args.manifestPath ? resolve(args.manifestPath) : undefined,
          intakeManifestPath: args.intakeManifestPath
            ? resolve(args.intakeManifestPath)
            : undefined,
          intakeOnly: args.intakeOnly,
          maxArticles: args.limit,
        }),
    );
    console.log(JSON.stringify(manifest, null, 2));
    return;
  }

  if (args.command === "run-keeper") {
    if (!args.inputDir || !args.outDir) {
      throw new Error(
        "Usage: run-keeper --inputDir path/to/html-root --outDir path/to/artifact-root [--statePath path/to/job-store.json] [--resume] [--once]",
      );
    }
    const { runKeeperOnce } = await import("./orchestrator/pipelineKeeper.js");
    await runKeeperOnce({
      inputRoot: resolve(args.inputDir),
      outRoot: resolve(args.outDir),
      statePath: args.statePath ? resolve(args.statePath) : undefined,
      resume: args.resume,
      once: args.once,
      onProgress: (message) => {
        console.error(message);
      },
    });
    return;
  }

  if (args.command === "run-downstream-llm") {
    if (!args.inputDir || !args.outDir) {
      throw new Error(
        "Usage: run-downstream-llm --inputDir path/to/artifact-dir --outDir path/to/out-dir [--stageName entity_extract]",
      );
    }
    await runDownstreamLlmStage({
      artifactDir: resolve(args.inputDir),
      outDir: resolve(args.outDir),
      stageName: args.stageName,
      modelId: args.modelId || undefined,
      schemaVersion: args.schemaVersion || undefined,
      params: await parseParams(args),
    });
    return;
  }

  if (args.command === "run-downstream-llm-batch") {
    if (!args.inputDir) {
      throw new Error(
        "Usage: run-downstream-llm-batch --inputDir path/to/artifact-root [--outDir path/to/output-root] [--stageName event_extract] [--statusPath path/to/status.json] [--resultLogPath path/to/results.jsonl] [--resume] [--concurrency 1]",
      );
    }
    await assertNoRunningLlmExport(resolve(args.inputDir), "run-downstream-llm-batch");
    const summary = await withLiveStageLockIfProduction(
      {
        rootPath: resolve(args.outDir || args.inputDir),
        stageName: "run-downstream-llm-batch",
        command: cliCommandText(),
      },
      async () =>
        runDownstreamLlmBatch({
          inputDir: resolve(args.inputDir),
          outDir: args.outDir ? resolve(args.outDir) : undefined,
          stageName: args.stageName,
          statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
          resultLogPath: args.resultLogPath ? resolve(args.resultLogPath) : undefined,
          modelId: args.modelId || undefined,
          schemaVersion: args.schemaVersion || undefined,
          params: await parseParams(args),
          resume: args.resume,
          concurrency: args.concurrency,
        }),
    );
    console.log(JSON.stringify(summary, null, 2));
    return;
  }

  if (args.command === "ocr-poster-batch") {
    const artifactRoot = args.artifactRoot || args.inputDir;
    if (!artifactRoot || !args.archiveRoot) {
      throw new Error(
        "Usage: ocr-poster-batch --artifactRoot path/to/artifact-root --archiveRoot path/to/archive-root [--artifactListPath path/to/list.txt] [--onlyQuality review,blocked] [--statusPath path/to/status.json] [--resultLogPath path/to/results.jsonl] [--resume] [--concurrency 1] [--limit 20]",
      );
    }
    await assertNoRunningMptextArchive(resolve(args.archiveRoot), "ocr-poster-batch");
    await assertNoRunningArchiveAssets(resolve(args.archiveRoot), "ocr-poster-batch");
    await assertNoRunningLlmExport(resolve(artifactRoot), "ocr-poster-batch");
    const summary = await withLiveStageLockIfProduction(
      {
        rootPath: resolve(artifactRoot),
        stageName: "ocr-poster-batch",
        command: cliCommandText(),
      },
      () =>
        runPosterOcrBatch({
          artifactRoot: resolve(artifactRoot),
          archiveRoot: resolve(args.archiveRoot),
          artifactListPath: args.artifactListPath ? resolve(args.artifactListPath) : undefined,
          onlyQuality: parseQualityList(args.onlyQuality),
          statusPath: args.statusPath ? resolve(args.statusPath) : undefined,
          resultLogPath: args.resultLogPath ? resolve(args.resultLogPath) : undefined,
          resume: args.resume,
          concurrency: args.concurrency,
          limit: args.limit,
        }),
    );
    console.log(JSON.stringify(summary, null, 2));
    return;
  }

  if (args.command === "create-runner-job-pack") {
    if (!args.inputDir || !args.outDir || !args.stageName || !args.modelId) {
      throw new Error(
        "Usage: create-runner-job-pack --inputDir path/to/release/articles --outDir path/to/job-pack --stageName ocr|downstream|embedding --runnerId windows-4090|mac-m3pro|cloud-5090 --modelId model-name [--promptId id] [--promptPath prompt.md] [--schemaVersion v1] [--limit 50]",
      );
    }
    const promptText = args.promptPath
      ? (await import("node:fs/promises")).readFile(resolve(args.promptPath), "utf-8")
      : undefined;
    const summary = await createRunnerJobPack({
      inputDir: resolve(args.inputDir),
      outDir: resolve(args.outDir),
      stage: args.stageName,
      runnerId: args.runnerId,
      modelId: args.modelId,
      promptId: args.promptId,
      promptText: promptText ? await promptText : undefined,
      schemaVersion: args.schemaVersion || undefined,
      limit: args.limit,
    });
    console.log(JSON.stringify(summary, null, 2));
    return;
  }

  if (args.command === "validate-runner-result-pack") {
    if (!args.inputDir) {
      throw new Error(
        "Usage: validate-runner-result-pack --inputDir path/to/result-pack [--manifestPath path/to/job-pack/manifest.jsonl]",
      );
    }
    const validation = await validateRunnerResultPack({
      inputDir: resolve(args.inputDir),
      manifestPath: args.manifestPath ? resolve(args.manifestPath) : undefined,
    });
    console.log(JSON.stringify(validation, null, 2));
    return;
  }

  if (args.command === "build-graph-candidate-pack") {
    if (!args.inputDir || !args.outDir) {
      throw new Error(
        "Usage: build-graph-candidate-pack --inputDir path/to/final-pack/articles --outDir path/to/graph-pack [--sourcePackId id]",
      );
    }
    const manifest = await buildGraphCandidatePack({
      inputDir: resolve(args.inputDir),
      outDir: resolve(args.outDir),
      sourcePackId: args.sourcePackId,
    });
    console.log(JSON.stringify(manifest, null, 2));
    return;
  }

  if (args.command === "ignuke-dry-run-import") {
    if (!args.inputDir) {
      throw new Error(
        "Usage: ignuke-dry-run-import --inputDir path/to/graph-pack [--outDir path/to/report-dir]",
      );
    }
    const report = await runIgnukeDryRunImport({
      inputDir: resolve(args.inputDir),
      outDir: args.outDir ? resolve(args.outDir) : undefined,
    });
    console.log(JSON.stringify(report, null, 2));
    return;
  }

  if (args.command === "register-pack") {
    if (!args.inputDir || !args.outDir || !args.packType) {
      throw new Error(
        "Usage: register-pack --inputDir path/to/pack --outDir path/to/registry --packType final_pack|graph_candidate_pack|runner_job_pack|runner_result_pack|vector_pack [--packId id] [--schemaVersion v1]",
      );
    }
    const record = await registerPack({
      packDir: resolve(args.inputDir),
      registryRoot: resolve(args.outDir),
      packType: args.packType as RegisteredPackType,
      packId: args.packId || undefined,
      schemaVersion: args.schemaVersion || undefined,
    });
    console.log(JSON.stringify(record, null, 2));
    return;
  }

  if (args.command === "split-manifest-shards") {
    if (!args.manifestPath || !args.outDir) {
      throw new Error(
        "Usage: split-manifest-shards --manifestPath path/to/queue.jsonl --outDir path/to/shard-dir [--shardSize 5000]",
      );
    }
    const summary = await splitManifestIntoShards({
      sourcePath: resolve(args.manifestPath),
      outDir: resolve(args.outDir),
      shardSize: args.shardSize,
    });
    console.log(JSON.stringify(summary, null, 2));
    return;
  }

  throw new Error(
    [
      "Usage:",
      "  process-article --input path/to/raw.html --outDir path/to/out",
      "  process-dual-track --input path/to/raw.html --outDir path/to/out",
      "  process-dual-track --input path/to/archive-bundle --outDir path/to/out --inputMode archive",
      "  archive-article --input https://mp.weixin.qq.com/s/... --outDir path/to/archive-bundle",
      "  archive-batch --manifestPath path/to/archive_queue.jsonl --outDir path/to/archive-root [--statusPath path/to/archive-status.json] [--resume] [--concurrency 1]",
      "  prefetch-account-urls --accountsPath D:\\DDownload\\公众号.json --outDir D:\\DDownload [--endpoint http://127.0.0.1:17300] [--key <auth-key>] [--accountConcurrency 2] [--maxPages 200] [--limitAccounts 2] [--resume]",
      "  mptext-archive-batch --manifestPath path/to/archive_queue.jsonl --outDir path/to/archive-root [--endpoint http://127.0.0.1:17300] [--key <auth-key>] [--resultLogPath path/to/results.jsonl] [--fallbackEndpoint http://127.0.0.1:17301] [--fallbackKey <auth-key>] [--noFallback] [--formats html] [--concurrency 3] [--resume] [--deferExistingPartialOnResume]",
      "  dajiala-repair-archive-batch --manifestPath path/to/archive_queue.partial.jsonl --outDir path/to/archive-root [--endpoint https://www.dajiala.com] [--key <api-key>] [--concurrency 1] [--requestDelayMs 1200] [--resume]",
      "  filter-dajiala-repair-candidates --auditItems path/to/archive-audit-items.jsonl --outDir path/to/dajiala-candidates.jsonl [--requireSignedLongLink]",
      "  extract-incomplete-archive-queue --manifestPath path/to/archive_queue.jsonl --inputDir path/to/archive-root --outDir path/to/partial_queue.jsonl [--statuses partial,failed,missing]",
      "  audit-archive-run --inputDir path/to/archive-root --manifestPath path/to/archive_queue.jsonl --outDir path/to/audit-report-dir [--resultLogPath path/to/archive-results.jsonl]",
      "  download-archive-assets --input path/to/archive-bundle",
      "  download-archive-assets-batch --inputDir path/to/archive-root --manifestPath path/to/archive_queue.jsonl [--statusPath path/to/asset-retention-status.json] [--resultLogPath path/to/asset-retention-results.jsonl] [--resume]",
      "  process-batch --inputDir path/to/html-root --outDir path/to/out-root [--statusPath path/to/batch-status.json] [--resume]",
      "  process-batch --inputDir path/to/archive-root --outDir path/to/out-root --inputMode archive --manifestPath path/to/archive_queue.jsonl [--statusPath path/to/batch-status.json] [--resume]",
      "  export-markitdown-batch --inputDir path/to/html-root --outDir path/to/md-root [--statusPath path/to/markitdown-batch-status.json] [--resume]",
      "  export-llm-batch --inputDir path/to/html-root --outDir path/to/artifact-root --mirrorDir path/to/md-root [--statusPath path/to/batch-status.json] [--resume]",
      "  export-llm-batch --inputDir path/to/archive-root --outDir path/to/artifact-root --mirrorDir path/to/md-root --inputMode archive --manifestPath path/to/archive_queue.jsonl [--statusPath path/to/batch-status.json] [--resume]",
      "  finalize-llm-pack --inputDir path/to/artifact-root --outDir path/to/release-root [--archiveRoot path/to/archive-root] [--manifestPath path/to/archive_queue.jsonl] [--intakeManifestPath path/to/llm_intake_manifest.json] [--intakeOnly] [--limit N]",
      "  run-keeper --inputDir path/to/html-root --outDir path/to/artifact-root [--statePath path/to/job-store.json] [--resume] [--once]",
      "  run-downstream-llm --inputDir path/to/artifact-dir --outDir path/to/out-dir [--stageName entity_extract]",
      "  run-downstream-llm-batch --inputDir path/to/artifact-root [--outDir path/to/output-root] [--stageName event_extract] [--statusPath path/to/status.json] [--resultLogPath path/to/results.jsonl] [--resume] [--concurrency 1]",
      "  ocr-poster-batch --artifactRoot path/to/artifact-root --archiveRoot path/to/archive-root [--artifactListPath path/to/list.txt] [--onlyQuality review,blocked] [--statusPath path/to/status.json] [--resultLogPath path/to/results.jsonl] [--resume] [--concurrency 1] [--limit 20]",
      "  create-runner-job-pack --inputDir path/to/release/articles --outDir path/to/job-pack --stageName ocr|downstream|embedding --runnerId windows-4090|mac-m3pro|cloud-5090 --modelId model-name [--promptId id] [--promptPath prompt.md] [--schemaVersion v1] [--limit 50]",
      "  validate-runner-result-pack --inputDir path/to/result-pack [--manifestPath path/to/job-pack/manifest.jsonl]",
      "  build-graph-candidate-pack --inputDir path/to/final-pack/articles --outDir path/to/graph-pack [--sourcePackId id]",
      "  ignuke-dry-run-import --inputDir path/to/graph-pack [--outDir path/to/report-dir]",
      "  register-pack --inputDir path/to/pack --outDir path/to/registry --packType final_pack|graph_candidate_pack|runner_job_pack|runner_result_pack|vector_pack [--packId id] [--schemaVersion v1]",
      "  split-manifest-shards --manifestPath path/to/queue.jsonl --outDir path/to/shard-dir [--shardSize 5000]",
    ].join("\n"),
  );
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  process.exitCode = 1;
});
