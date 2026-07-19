const { EventEmitter } = require("node:events");
const path = require("node:path");
const WebSocket = require("ws");

function connectWebSocket(endpoint, timeoutMs) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(endpoint);
    const timer = setTimeout(() => {
      try { socket.close(); } catch { /* noop */ }
      reject(new Error(`DevTools websocket open timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    socket.on("open", () => {
      clearTimeout(timer);
      resolve(socket);
    });
    socket.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

class AutomatorProtocolAdapter extends EventEmitter {
  constructor(miniProgram) {
    super();
    this.miniProgram = miniProgram;
    this.readyState = WebSocket.OPEN;
  }

  send(rawMessage) {
    let message;
    try {
      message = JSON.parse(String(rawMessage));
    } catch (error) {
      queueMicrotask(() => this.emit("error", error));
      return;
    }
    Promise.resolve(this.miniProgram.connection.send(message.method, message.params || {})).then(
      (result) => {
        this.emit("message", Buffer.from(JSON.stringify({ id: message.id, result })));
      },
      (error) => {
        this.emit("message", Buffer.from(JSON.stringify({
          id: message.id,
          error: { message: error && error.message ? error.message : String(error) },
        })));
      },
    );
  }

  close() {
    if (this.readyState === WebSocket.CLOSED) return;
    this.readyState = WebSocket.CLOSED;
    try { this.miniProgram.disconnect(); } catch { /* noop */ }
    queueMicrotask(() => this.emit("close"));
  }
}

async function connectRawDevtools(options = {}) {
  const endpoint = String(options.endpoint || "").trim();
  const timeoutMs = Number(options.timeoutMs || 120000);
  if (endpoint) return connectWebSocket(endpoint, timeoutMs);

  let automator;
  try {
    automator = require("miniprogram-automator");
  } catch (error) {
    throw new Error(`miniprogram-automator is required for DevTools launch mode: ${error.message}`);
  }
  const projectPath = options.projectPath
    || process.env.MINIPROGRAM_PROJECT_PATH
    || path.resolve(__dirname, "..");
  const cliPath = options.cliPath
    || process.env.MINIPROGRAM_DEVTOOLS_CLI
    || "C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat";
  const port = Number(options.port || process.env.MINIPROGRAM_AUTOMATOR_PORT || 9420);
  const idePort = Number(options.idePort || process.env.MINIPROGRAM_DEVTOOLS_IDE_PORT || port);
  const miniProgram = await automator.launch({
    projectPath,
    cliPath,
    port,
    idePort,
    trustProject: true,
    timeout: timeoutMs,
  });
  return new AutomatorProtocolAdapter(miniProgram);
}

module.exports = {
  AutomatorProtocolAdapter,
  connectRawDevtools,
};
