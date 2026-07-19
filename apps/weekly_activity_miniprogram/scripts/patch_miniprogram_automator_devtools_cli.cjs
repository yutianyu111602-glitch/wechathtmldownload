const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const automatorPackagePath = require.resolve("miniprogram-automator/package.json", { paths: [root] });
const automatorRoot = path.dirname(automatorPackagePath);
const launcherPath = path.join(automatorRoot, "out", "Launcher.js");
const connectionPath = path.join(automatorRoot, "out", "Connection.js");
const miniProgramPath = path.join(automatorRoot, "out", "MiniProgram.js");

function readRequired(file) {
  if (!fs.existsSync(file)) {
    throw new Error(`Missing ${file}. Install miniprogram-automator before patching.`);
  }
  return fs.readFileSync(file, "utf8");
}

function replaceOnce(source, from, to, label) {
  if (source.includes(to)) return { source, changed: false, label };
  if (!source.includes(from)) return { source, changed: false, label: `${label}:pattern-not-found` };
  return { source: source.replace(from, to), changed: true, label };
}

let launcher = readRequired(launcherPath);
let connection = readRequired(connectionPath);
let miniProgram = readRequired(miniProgramPath);
const changes = [];

let result = replaceOnce(
  launcher,
  "      port: t = 0,\n      ticket: a = \"\",",
  "      port: t = 0,\n      idePort: h = 9430,\n      ticket: a = \"\",",
  "launcher:add-ide-port"
);
launcher = result.source;
if (result.changed) changes.push(result.label);

result = replaceOnce(
  launcher,
  "    const u = await getPort(t || 9420);\n    if (options && options.port && options.port !== u) {\n      throw Error(`Port ${options.port} is in use, please specify another port`);\n    }",
  "    const requestedPort = t || 9420;\n    const u = await getPort(requestedPort);\n    if (requestedPort !== u) {\n      try {\n        const existing = await this.connectTool({ wsEndpoint: `ws://127.0.0.1:${requestedPort}` });\n        await existing.checkVersion();\n        return existing;\n      } catch (_error) {\n        if (options && options.port) {\n          throw Error(`Port ${options.port} is in use, please specify another port`);\n        }\n      }\n    }",
  "launcher:reuse-existing-port"
);
launcher = result.source;
if (result.changed) changes.push(result.label);

result = replaceOnce(
  launcher,
  "    n = concat(n, [\"auto\", \"--project\", s, \"--port\", toStr(u)]);",
  "    n = concat(n, [\"auto\", \"--project\", s, \"--auto-port\", toStr(u)]);\n    if (h) {\n      n = concat(n, [\"--port\", toStr(h)]);\n    }",
  "launcher:use-auto-port"
);
launcher = result.source;
if (result.changed) changes.push(result.label);

result = replaceOnce(
  launcher,
  'let{args:n=[]}=t,{projectPath:s}=t;const u=await getPort_1.default(t.port||9420);if(t.port&&t.port!==u)throw Error(`Port ${t.port} is in use, please specify another port`);',
  'let{args:n=[]}=t,{projectPath:s}=t,{idePort:h=0}=t;const u=await getPort_1.default(t.port||9420);',
  "launcher:minified-dynamic-free-port"
);
launcher = result.source;
if (result.changed) changes.push(result.label);

result = replaceOnce(
  launcher,
  'n=concat_1.default(n,["auto","--project",s,"--auto-port",toStr_1.default(u)])',
  'n=concat_1.default(n,["auto","--project",s,"--auto-port",toStr_1.default(u)]),h&&(n=concat_1.default(n,["--port",toStr_1.default(h)]))',
  "launcher:minified-ide-port"
);
launcher = result.source;
if (result.changed) changes.push(result.label);

result = replaceOnce(
  launcher,
  'const _={stdio:"ignore"};o&&(_.cwd=o);',
  'const _={stdio:"ignore",shell:isWindows_1.default};o&&(_.cwd=o);',
  "launcher:minified-windows-bat-shell"
);
launcher = result.source;
if (result.changed) changes.push(result.label);

result = replaceOnce(
  connection,
  "static create(e){return new Promise(((t,r)=>{const s=new ws_1.default(e);",
  "static create(e,protocols){return new Promise(((t,r)=>{const s=new ws_1.default(e,protocols);",
  "connection:optional-ws-protocols"
);
connection = result.source;
if (result.changed) changes.push(result.label);

result = replaceOnce(
  miniProgram,
  'async checkVersion(){let t="";if(t=(await this.send("Tool.getInfo")).SDKVersion,"dev"!==t&&cmpVersion_1.default(t,"2.7.3")<0)throw Error(`SDKVersion is currently ${t}, while automator(${pkg.version}) requires at least version 2.7.3`)}',
  'async checkVersion(){let t="";const e=await this.send("Tool.getInfo");if(t=e&&e.SDKVersion||"dev","dev"!==t&&cmpVersion_1.default(t,"2.7.3")<0)throw Error(`SDKVersion is currently ${t}, while automator(${pkg.version}) requires at least version 2.7.3`)}',
  "miniprogram:default-empty-sdk-version"
);
miniProgram = result.source;
if (result.changed) changes.push(result.label);

const launcherReady = (
  launcher.includes('"--auto-port"')
  && !launcher.includes("if(t.port&&t.port!==u)throw Error")
  && (launcher.includes("idePort:h=0") || launcher.includes("idePort: h = 9430"))
  && (launcher.includes('shell:isWindows_1.default') || launcher.includes("shell: isWindows"))
);
if (!launcherReady) {
  throw new Error(`Unsupported miniprogram-automator Launcher.js format: ${launcherPath}`);
}

if (changes.length) {
  fs.writeFileSync(launcherPath, launcher, "utf8");
  fs.writeFileSync(connectionPath, connection, "utf8");
  fs.writeFileSync(miniProgramPath, miniProgram, "utf8");
}

console.log(JSON.stringify({
  ok: launcherReady,
  launcherReady,
  changes,
  launcherPath,
  connectionPath,
  miniProgramPath,
}, null, 2));
