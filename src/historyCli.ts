import { resolve } from "node:path";

import {
  DEFAULT_MPTEXT_AUTH_KEY,
  DEFAULT_MPTEXT_BASE_URL,
} from "./mptext/client.js";
import {
  DEFAULT_DAJIALA_API_KEY,
  fetchHistoryUrls,
  type HistoryAuthOptions,
} from "./api/fetchHistoryUrls.js";

interface CliArgs {
  key: string;
  appid: string;
  secret: string;
  url: string;
  outDir: string;
  maxPages?: number;
  endpoint: string;
  provider: "dajiala" | "mptext";
}

function parseArgs(argv: string[]): CliArgs {
  const args: CliArgs = {
    key: "",
    appid: "",
    secret: "",
    url: "",
    outDir: "D:\\rawwechat",
    endpoint: "",
    provider: "mptext",
  };

  for (let index = 0; index < argv.length; index += 1) {
    const current = argv[index] ?? "";
    const next = argv[index + 1] ?? "";

    if (current === "--key") {
      args.key = next;
      index += 1;
      continue;
    }
    if (current === "--appid") {
      args.appid = next;
      index += 1;
      continue;
    }
    if (current === "--secret") {
      args.secret = next;
      index += 1;
      continue;
    }
    if (current === "--url") {
      args.url = next;
      index += 1;
      continue;
    }
    if (current === "--outDir") {
      args.outDir = next;
      index += 1;
      continue;
    }
    if (current === "--maxPages") {
      const parsed = Number(next);
      if (Number.isFinite(parsed) && parsed > 0) {
        args.maxPages = parsed;
      }
      index += 1;
      continue;
    }
    if (current === "--endpoint") {
      args.endpoint = next;
      index += 1;
      continue;
    }
    if (current === "--provider") {
      if (next === "dajiala" || next === "mptext") {
        args.provider = next;
      }
      index += 1;
      continue;
    }
  }

  if (!args.key) {
    args.key =
      args.provider === "dajiala"
        ? DEFAULT_DAJIALA_API_KEY
        : DEFAULT_MPTEXT_AUTH_KEY;
  }
  if (!args.endpoint && args.provider === "mptext") {
    args.endpoint = process.env.MPTEXT_BASE_URL || DEFAULT_MPTEXT_BASE_URL;
  }

  return args;
}

function resolveAuth(args: CliArgs): HistoryAuthOptions {
  if (args.key) {
    return { key: args.key };
  }

  if (args.appid && args.secret) {
    return {
      appid: args.appid,
      secret: args.secret,
    };
  }

  throw new Error(
    "Usage: fetch-history-urls --url <article-url-or-biz-or-fakeid-or-keyword> [--key <api-key>] [--provider mptext|dajiala] [--outDir D:\\rawwechat] [--maxPages 400] [--endpoint http://127.0.0.1:17300]",
  );
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  if (!args.url) {
    throw new Error(
      "Usage: fetch-history-urls --url <article-url-or-biz-or-fakeid-or-keyword> [--key <api-key>] [--provider mptext|dajiala] [--outDir D:\\rawwechat] [--maxPages 400] [--endpoint http://127.0.0.1:17300]",
    );
  }

  const result = await fetchHistoryUrls({
    query: args.url,
    outDir: resolve(args.outDir),
    maxPages: args.maxPages,
    endpoint: args.endpoint || undefined,
    auth: resolveAuth(args),
    provider: args.provider,
  });

  console.log(
    JSON.stringify(
      {
        outDir: result.outDir,
        jsonPath: result.jsonPath,
        txtPath: result.txtPath,
        archiveQueuePath: result.archiveQueuePath,
        pagesFetched: result.pagesFetched,
        uniqueUrlCount: result.uniqueUrlCount,
        stoppedReason: result.stoppedReason,
      },
      null,
      2,
    ),
  );
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  process.exitCode = 1;
});
