import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { createAbortError } from "./abort.js";

function resolveMarkitdownPython(): string {
  const resourcesPath = Reflect.get(process, "resourcesPath");
  const packagedRuntime =
    typeof resourcesPath === "string"
      ? join(
          resourcesPath,
          "markitdown-runtime",
          ".venv",
          "Scripts",
          "python.exe",
        )
      : "";
  const stagedRuntime = resolve(
    "vendor/markitdown-runtime/.venv/Scripts/python.exe",
  );
  const localFallback =
    "C:/code/githubstar/markitdown/.venv/Scripts/python.exe";

  const candidates = [
    process.env.MARKITDOWN_PYTHON || "",
    packagedRuntime,
    stagedRuntime,
    localFallback,
  ];
  for (const candidate of candidates) {
    if (candidate && existsSync(candidate)) {
      return candidate;
    }
  }

  return process.env.MARKITDOWN_PYTHON || localFallback;
}

function resolveMarkitdownCwd(pythonPath: string): string {
  if (process.env.MARKITDOWN_CWD) {
    return process.env.MARKITDOWN_CWD;
  }

  return dirname(dirname(pythonPath));
}

export async function convertWithMarkItDown(
  inputPath: string,
  signal?: AbortSignal,
): Promise<string> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(createAbortError("MarkItDown conversion cancelled before start"));
      return;
    }

    const pythonPath = resolveMarkitdownPython();
    const cwdPath = resolveMarkitdownCwd(pythonPath);
    const script = [
      "import json, sys",
      "from markitdown import MarkItDown",
      "path = sys.argv[1]",
      "markdown = MarkItDown(enable_plugins=False).convert(path).text_content",
      "sys.stdout.write(json.dumps({'markdown': markdown}, ensure_ascii=False))",
    ].join("\n");

    const child = spawn(pythonPath, ["-c", script, inputPath], {
      cwd: cwdPath,
      env: {
        ...process.env,
        PYTHONUTF8: "1",
      },
      windowsHide: true,
    });

    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    let settled = false;

    const cleanupAbortListener = () => {
      if (signal) {
        signal.removeEventListener("abort", handleAbort);
      }
    };

    const settleReject = (error: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanupAbortListener();
      reject(error);
    };

    const settleResolve = (value: string) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanupAbortListener();
      resolve(value);
    };

    const handleAbort = () => {
      child.kill();
      settleReject(createAbortError("MarkItDown conversion cancelled"));
    };

    signal?.addEventListener("abort", handleAbort, { once: true });

    child.stdout.on("data", (chunk: Buffer | string) => {
      stdoutChunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    });

    child.stderr.on("data", (chunk: Buffer | string) => {
      stderrChunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    });

    child.on("error", (error) => {
      settleReject(
        new Error(`Failed to launch MarkItDown Python: ${error.message}`),
      );
    });

    child.on("close", (code) => {
      if (settled) {
        return;
      }

      const stdoutText = Buffer.concat(stdoutChunks).toString("utf-8");
      const stderrText = Buffer.concat(stderrChunks).toString("utf-8").trim();

      if (code !== 0) {
        settleReject(
          new Error(
            `MarkItDown failed with exit code ${code}: ${stderrText || "unknown error"}`,
          ),
        );
        return;
      }

      try {
        const parsed = JSON.parse(stdoutText) as { markdown?: string };
        settleResolve(parsed.markdown || "");
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        settleReject(
          new Error(`Failed to parse MarkItDown output: ${message}`),
        );
      }
    });
  });
}
