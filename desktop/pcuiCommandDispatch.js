import {
  DEFAULT_BACKGROUND_LOCK_REASON,
  getBackgroundDownloadLockReason,
} from "./pcuiRuntimeGuards.js";

export const PCUI_COMMANDS = Object.freeze({
  START_BATCH: "batch:start",
  CANCEL_BATCH: "batch:cancel",
  RUN_AUDIT: "audit:run",
  RUN_ASSETS: "assets:run",
  FINALIZE_PACK: "pack:finalize",
  INSPECTOR_PRIMARY: "inspector:primary",
  INSPECTOR_SECONDARY: "inspector:secondary",
  INSPECTOR_TERTIARY: "inspector:tertiary",
});

const BACKGROUND_LOCKED_COMMANDS = new Set([
  PCUI_COMMANDS.RUN_AUDIT,
  PCUI_COMMANDS.RUN_ASSETS,
  PCUI_COMMANDS.FINALIZE_PACK,
]);

function getErrorMessage(err) {
  return err instanceof Error ? err.message : String(err);
}

export function normalizePcuiCommandResult(command, result, {
  acceptedMessage = "命令已接受。",
  rejectedMessage = "命令被拒绝。",
} = {}) {
  const accepted = Boolean(result?.accepted);
  return {
    ...(result || {}),
    command,
    accepted,
    status: accepted ? "accepted" : "rejected",
    message: result?.message || (accepted ? acceptedMessage : rejectedMessage),
    blocked: Boolean(result?.blocked),
    error: Boolean(result?.error),
  };
}

export function createPcuiCommandDispatch({
  desktopApi,
  isBackgroundDownloadRunning = async () => false,
  getBackgroundDownloadLock = null,
  lockMessage = DEFAULT_BACKGROUND_LOCK_REASON,
} = {}) {
  const commandHandlers = {
    [PCUI_COMMANDS.START_BATCH]: (payload) => desktopApi.startBatch(payload),
    [PCUI_COMMANDS.CANCEL_BATCH]: () => desktopApi.cancelBatch(),
    [PCUI_COMMANDS.RUN_AUDIT]: (payload) => desktopApi.runAudit(payload),
    [PCUI_COMMANDS.RUN_ASSETS]: (payload) => desktopApi.runAssetsDownload(payload),
    [PCUI_COMMANDS.FINALIZE_PACK]: (payload) => desktopApi.runFinalize(payload),
  };

  async function resolveBackgroundLock(command, payload) {
    if (typeof getBackgroundDownloadLock === "function") {
      const lock = await getBackgroundDownloadLock({ command, payload });
      return lock?.isRunning
        ? { ...lock, message: getBackgroundDownloadLockReason(lock) || lockMessage }
        : { isRunning: false };
    }

    return await isBackgroundDownloadRunning()
      ? { isRunning: true, lockReason: lockMessage, message: lockMessage }
      : { isRunning: false };
  }

  async function dispatch(command, payload = {}, options = {}) {
    if (!desktopApi) {
      return normalizePcuiCommandResult(command, {
        accepted: false,
        error: true,
        message: "Desktop API is unavailable.",
      }, options);
    }

    if (BACKGROUND_LOCKED_COMMANDS.has(command)) {
      const lock = await resolveBackgroundLock(command, payload);
      if (lock.isRunning) {
        return normalizePcuiCommandResult(command, {
          accepted: false,
          blocked: true,
          message: lock.message || getBackgroundDownloadLockReason(lock) || lockMessage,
        }, options);
      }
    }

    const handler = commandHandlers[command];
    if (!handler) {
      return normalizePcuiCommandResult(command, {
        accepted: false,
        error: true,
        message: `Unknown command: ${command}`,
      }, options);
    }

    try {
      return normalizePcuiCommandResult(command, await handler(payload), options);
    } catch (err) {
      return normalizePcuiCommandResult(command, {
        accepted: false,
        error: true,
        message: getErrorMessage(err),
      }, options);
    }
  }

  async function dispatchLocal(command, handler, options = {}) {
    if (typeof handler !== "function") {
      return normalizePcuiCommandResult(command, {
        accepted: false,
        error: true,
        message: `Missing local handler: ${command}`,
      }, options);
    }

    try {
      await handler();
      return normalizePcuiCommandResult(command, {
        accepted: true,
        message: options.acceptedMessage,
      }, options);
    } catch (err) {
      return normalizePcuiCommandResult(command, {
        accepted: false,
        error: true,
        message: getErrorMessage(err),
      }, options);
    }
  }

  return {
    dispatch,
    dispatchLocal,
    isBackgroundLockedCommand: (command) => BACKGROUND_LOCKED_COMMANDS.has(command),
  };
}
