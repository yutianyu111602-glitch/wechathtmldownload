export interface RuntimeCaptureOptions {
  enabled: boolean;
  outputPath: string;
  waitMs: number;
  quitAfterCapture: boolean;
  workspace: RuntimeCaptureWorkspace;
}

export type RuntimeCaptureWorkspace = "task-bus" | "collect" | "archive" | "process" | "artifact";

const DEFAULT_WORKSPACE: RuntimeCaptureWorkspace = "task-bus";
const RUNTIME_CAPTURE_WORKSPACES = new Set<RuntimeCaptureWorkspace>([
  "task-bus",
  "collect",
  "archive",
  "process",
  "artifact",
]);

function readTruthy(value: string | undefined): boolean {
  return value === "1" || value === "true" || value === "yes";
}

function readWaitMs(value: string | undefined, fallback: number): number {
  const parsed = Number(value || "");
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return Math.floor(parsed);
}

function readWorkspace(value: string | undefined): RuntimeCaptureWorkspace {
  const normalized = String(value || "").trim();
  if (RUNTIME_CAPTURE_WORKSPACES.has(normalized as RuntimeCaptureWorkspace)) {
    return normalized as RuntimeCaptureWorkspace;
  }
  return DEFAULT_WORKSPACE;
}

export function readRuntimeCaptureOptions(
  env: Record<string, string | undefined>,
  defaultOutputPath: string,
): RuntimeCaptureOptions {
  return {
    enabled: readTruthy(env.WECHAT_CAPTURE_SCREENSHOT),
    outputPath: env.WECHAT_CAPTURE_SCREENSHOT_PATH || defaultOutputPath,
    waitMs: readWaitMs(env.WECHAT_CAPTURE_SCREENSHOT_WAIT_MS, 1200),
    quitAfterCapture: readTruthy(env.WECHAT_CAPTURE_SCREENSHOT_QUIT),
    workspace: readWorkspace(env.WECHAT_CAPTURE_SCREENSHOT_WORKSPACE),
  };
}
