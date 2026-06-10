import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { copyFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";

export interface RustSidecarResult {
  tool: string;
  version: string;
  status: "ok" | "fallback" | "error";
  durationMs: number;
  inputCount: number;
  outputPath: string;
  errorMessage?: string;
}

export interface RustSidecarOptions {
  tool: string;
  args: string[];
  inputCount: number;
  outputPath: string;
  timeoutMs?: number;
}

async function normalizeFallbackOutput(
  result: RustSidecarResult,
  outputPath: string,
): Promise<RustSidecarResult> {
  if (result.outputPath && result.outputPath !== outputPath && existsSync(result.outputPath)) {
    await mkdir(dirname(outputPath), { recursive: true });
    await copyFile(result.outputPath, outputPath);
  }
  return {
    ...result,
    outputPath,
  };
}

function discoverRustBinary(tool: string): string | null {
  // 1. Explicit env path
  const envPath = process.env[`WECHAT_RUST_${tool.toUpperCase()}_PATH`];
  if (envPath && existsSync(envPath)) {
    return envPath;
  }

  // 2. Repo-local binary path
  const repoLocal = resolve(`tools/rust/target/release/${tool}.exe`);
  if (existsSync(repoLocal)) {
    return repoLocal;
  }

  // 3. Global path (Windows)
  const globalPath = resolve(`C:/Program Files/wechat-rust/${tool}.exe`);
  if (existsSync(globalPath)) {
    return globalPath;
  }

  return null;
}

export function isRustSidecarAvailable(tool: string): boolean {
  return discoverRustBinary(tool) !== null;
}

export async function runRustSidecar(
  options: RustSidecarOptions,
  fallback: () => Promise<RustSidecarResult>,
): Promise<RustSidecarResult> {
  const binaryPath = discoverRustBinary(options.tool);

  if (!binaryPath) {
    // Fallback to TypeScript implementation
    const result = await normalizeFallbackOutput(await fallback(), options.outputPath);
    return {
      ...result,
      status: "fallback",
      tool: options.tool,
      inputCount: options.inputCount,
      outputPath: options.outputPath,
    };
  }

  const start = performance.now();

  return new Promise((resolve, reject) => {
    const child = spawn(binaryPath, options.args, {
      windowsHide: true,
      timeout: options.timeoutMs,
    });

    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    let settled = false;

    const settle = (result: RustSidecarResult) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    child.stdout.on("data", (chunk: Buffer) => {
      stdoutChunks.push(chunk);
    });

    child.stderr.on("data", (chunk: Buffer) => {
      stderrChunks.push(chunk);
    });

    child.on("error", (error) => {
      settle({
        tool: options.tool,
        version: "unknown",
        status: "error",
        durationMs: performance.now() - start,
        inputCount: options.inputCount,
        outputPath: options.outputPath,
        errorMessage: `Failed to spawn Rust sidecar: ${error.message}`,
      });
    });

    child.on("close", async (code) => {
      if (settled) return;

      const durationMs = performance.now() - start;
      const stdoutText = Buffer.concat(stdoutChunks).toString("utf-8").trim();
      const stderrText = Buffer.concat(stderrChunks).toString("utf-8").trim();

      if (code !== 0) {
        // Try fallback on Rust failure
        try {
          const fallbackResult = await normalizeFallbackOutput(await fallback(), options.outputPath);
          settle({
            ...fallbackResult,
            status: "fallback",
            tool: options.tool,
            durationMs,
            inputCount: options.inputCount,
            outputPath: options.outputPath,
            errorMessage: `Rust exited ${code}: ${stderrText || "unknown error"}`,
          });
        } catch {
          settle({
            tool: options.tool,
            version: "unknown",
            status: "error",
            durationMs,
            inputCount: options.inputCount,
            outputPath: options.outputPath,
            errorMessage: `Rust exited ${code} and fallback failed: ${stderrText || "unknown error"}`,
          });
        }
        return;
      }

      try {
        const parsed = JSON.parse(stdoutText) as Partial<RustSidecarResult>;
        settle({
          tool: options.tool,
          version: parsed.version || "unknown",
          status: "ok",
          durationMs,
          inputCount: options.inputCount,
          outputPath: options.outputPath,
          errorMessage: parsed.errorMessage,
        });
      } catch {
        settle({
          tool: options.tool,
          version: "unknown",
          status: "error",
          durationMs,
          inputCount: options.inputCount,
          outputPath: options.outputPath,
          errorMessage: `Invalid JSON from Rust sidecar: ${stdoutText}`,
        });
      }
    });
  });
}

export interface BenchmarkGate {
  requiredSpeedup: number;
  requiredMemoryReduction: number;
}

export function shouldEnableRust(
  rustResult: RustSidecarResult,
  tsResult: RustSidecarResult,
  gate: BenchmarkGate = { requiredSpeedup: 3, requiredMemoryReduction: 0.5 },
): { enabled: boolean; reason: string } {
  if (rustResult.status !== "ok") {
    return { enabled: false, reason: `Rust status=${rustResult.status}, fallback used` };
  }

  if (tsResult.status !== "ok" && tsResult.status !== "fallback") {
    return { enabled: false, reason: `TypeScript status=${tsResult.status}, cannot compare` };
  }

  const speedup = tsResult.durationMs / rustResult.durationMs;
  if (speedup >= gate.requiredSpeedup) {
    return { enabled: true, reason: `Speedup ${speedup.toFixed(1)}x meets ${gate.requiredSpeedup}x gate` };
  }

  return {
    enabled: false,
    reason: `Speedup ${speedup.toFixed(1)}x below ${gate.requiredSpeedup}x gate`,
  };
}
