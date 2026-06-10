import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { createAbortError } from "./abort.js";

// Protocol types
export interface MarkitdownRequest {
  action: "convert";
  inputPath: string;
  id: string;
}

export interface MarkitdownSuccessResponse {
  id: string;
  success: true;
  markdown: string;
}

export interface MarkitdownErrorResponse {
  id: string;
  success: false;
  error: string;
}

export type MarkitdownResponse = MarkitdownSuccessResponse | MarkitdownErrorResponse;

function resolveMarkitdownPython(): string {
  const resourcesPath = Reflect.get(process, "resourcesPath");
  const packagedRuntime =
    typeof resourcesPath === "string"
      ? join(resourcesPath, "markitdown-runtime", ".venv", "Scripts", "python.exe")
      : "";
  const stagedRuntime = resolve("vendor/markitdown-runtime/.venv/Scripts/python.exe");
  const localFallback = "C:/code/githubstar/markitdown/.venv/Scripts/python.exe";

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

export interface MarkitdownWorkerOptions {
  pythonPath?: string;
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  onError?: (error: Error) => void;
}

export class MarkitdownWorker {
  private _child: ChildProcess | null = null;
  private _pending = new Map<string, { resolve: (value: string) => void; reject: (error: Error) => void }>();
  private _buffer = "";
  private _closed = false;
  private _pythonPath: string;
  private _cwd: string;
  private _env: NodeJS.ProcessEnv;
  private _onError?: (error: Error) => void;

  constructor(options: MarkitdownWorkerOptions = {}) {
    this._pythonPath = options.pythonPath || resolveMarkitdownPython();
    this._cwd = options.cwd || resolveMarkitdownCwd(this._pythonPath);
    this._env = options.env || { ...process.env, PYTHONUTF8: "1" };
    this._onError = options.onError;
  }

  get isRunning(): boolean {
    return this._child !== null && !this._child.killed && !this._closed;
  }

  start(): void {
    if (this.isRunning) {
      return;
    }

    const script = [
      "import json, sys",
      "from markitdown import MarkItDown",
      "md = MarkItDown(enable_plugins=False)",
      "for line in sys.stdin:",
      "    req = json.loads(line)",
      "    try:",
      "        result = md.convert(req['inputPath']).text_content",
      "        resp = {'id': req['id'], 'success': True, 'markdown': result}",
      "    except Exception as e:",
      "        resp = {'id': req['id'], 'success': False, 'error': str(e)}",
      "    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + '\\n')",
      "    sys.stdout.flush()",
    ].join("\n");

    this._child = spawn(this._pythonPath, ["-c", script], {
      cwd: this._cwd,
      env: this._env,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });

    this._buffer = "";
    this._closed = false;

    this._child.stdout?.on("data", (chunk: Buffer | string) => {
      this._buffer += Buffer.isBuffer(chunk) ? chunk.toString("utf-8") : chunk;
      this._processBuffer();
    });

    this._child.stderr?.on("data", (chunk: Buffer | string) => {
      const text = Buffer.isBuffer(chunk) ? chunk.toString("utf-8") : chunk;
      this._onError?.(new Error(`MarkItDown stderr: ${text.trim()}`));
    });

    this._child.on("error", (error) => {
      this._onError?.(new Error(`MarkItDown worker error: ${error.message}`));
      this._rejectAllPending(new Error(`Worker process error: ${error.message}`));
    });

    this._child.on("close", (code) => {
      this._closed = true;
      if (code !== 0 && code !== null) {
        this._rejectAllPending(new Error(`Worker exited with code ${code}`));
      }
    });
  }

  private _processBuffer(): void {
    const lines = this._buffer.split("\n");
    // Keep the last partial line in the buffer
    this._buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const response = JSON.parse(line) as MarkitdownResponse;
        const pending = this._pending.get(response.id);
        if (pending) {
          this._pending.delete(response.id);
          if (response.success) {
            pending.resolve(response.markdown);
          } else {
            pending.reject(new Error(response.error));
          }
        }
      } catch {
        this._onError?.(new Error(`Invalid JSON from worker: ${line}`));
      }
    }
  }

  private _rejectAllPending(error: Error): void {
    for (const pending of this._pending.values()) {
      pending.reject(error);
    }
    this._pending.clear();
  }

  async convert(inputPath: string, signal?: AbortSignal): Promise<string> {
    if (signal?.aborted) {
      throw createAbortError("MarkItDown conversion cancelled before start");
    }

    if (!this.isRunning) {
      this.start();
    }

    const id = `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const request: MarkitdownRequest = { action: "convert", inputPath, id };

    return new Promise((resolve, reject) => {
      this._pending.set(id, { resolve, reject });

      const handleAbort = () => {
        this._pending.delete(id);
        reject(createAbortError("MarkItDown conversion cancelled"));
      };

      signal?.addEventListener("abort", handleAbort, { once: true });

      try {
        this._child!.stdin!.write(JSON.stringify(request) + "\n");
      } catch (error) {
        this._pending.delete(id);
        signal?.removeEventListener("abort", handleAbort);
        const message = error instanceof Error ? error.message : String(error);
        reject(new Error(`Failed to send request to worker: ${message}`));
      }
    });
  }

  stop(): void {
    if (this._child && !this._child.killed) {
      this._child.kill();
    }
    this._rejectAllPending(new Error("Worker stopped"));
    this._closed = true;
  }
}

// Fake worker for headless testing (no real binary spawn)
export class FakeMarkitdownWorker extends MarkitdownWorker {
  private _handler: (inputPath: string) => Promise<string>;

  constructor(handler: (inputPath: string) => Promise<string>) {
    super({ pythonPath: "fake" });
    this._handler = handler;
  }

  start(): void {
    // No-op: fake worker doesn't start a real process
  }

  async convert(inputPath: string, signal?: AbortSignal): Promise<string> {
    if (signal?.aborted) {
      throw createAbortError("MarkItDown conversion cancelled before start");
    }
    return this._handler(inputPath);
  }

  stop(): void {
    // No-op
  }
}

export interface MarkitdownWorkerPoolOptions {
  poolSize: number;
  workerOptions?: MarkitdownWorkerOptions;
  fakeHandler?: (inputPath: string) => Promise<string>;
}

export class MarkitdownWorkerPool {
  private _workers: MarkitdownWorker[];
  private _currentIndex = 0;

  constructor(options: MarkitdownWorkerPoolOptions) {
    if (options.fakeHandler) {
      this._workers = Array.from(
        { length: options.poolSize },
        () => new FakeMarkitdownWorker(options.fakeHandler!),
      );
    } else {
      this._workers = Array.from(
        { length: options.poolSize },
        () => new MarkitdownWorker(options.workerOptions),
      );
    }

    // Pre-warm workers
    for (const worker of this._workers) {
      worker.start();
    }
  }

  async convert(inputPath: string, signal?: AbortSignal): Promise<string> {
    const worker = this._nextWorker();
    try {
      return await worker.convert(inputPath, signal);
    } catch (error) {
      // Kill and respawn on failure
      worker.stop();
      worker.start();
      throw error;
    }
  }

  private _nextWorker(): MarkitdownWorker {
    const worker = this._workers[this._currentIndex];
    this._currentIndex = (this._currentIndex + 1) % this._workers.length;
    return worker;
  }

  stop(): void {
    for (const worker of this._workers) {
      worker.stop();
    }
  }
}
