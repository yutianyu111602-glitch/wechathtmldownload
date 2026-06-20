import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const appDir = path.resolve(__dirname, "..");
const outDir = path.join(appDir, "test-artifacts");
const layoutPath = path.join(appDir, "public", "atlas_layout.json");
const viteBin = path.join(appDir, "node_modules", "vite", "bin", "vite.js");

function readLayout() {
  const layout = JSON.parse(fs.readFileSync(layoutPath, "utf8"));
  const firstNode = Array.isArray(layout.nodes)
    ? layout.nodes.find((node) => String(node?.name || "").trim())
    : null;
  if (!firstNode) throw new Error("atlas_layout.json has no searchable node");
  return {
    nodeCount: layout.nodes.length,
    edgeCount: Array.isArray(layout.edges) ? layout.edges.length : 0,
    firstNodeName: String(firstNode.name).trim(),
  };
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

function waitForHttp(url, timeoutMs = 20_000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      });
      req.on("error", retry);
      req.setTimeout(1000, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(tick, 250);
    };
    tick();
  });
}

function startVite(port) {
  fs.mkdirSync(outDir, { recursive: true });
  const out = fs.createWriteStream(path.join(appDir, "playwright-vite.out.log"));
  const err = fs.createWriteStream(path.join(appDir, "playwright-vite.err.log"));
  const child = spawn(
    process.execPath,
    [viteBin, "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
    {
      cwd: appDir,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    },
  );
  child.stdout.pipe(out);
  child.stderr.pipe(err);
  return child;
}

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

function pngStats(buffer) {
  const signature = buffer.subarray(0, 8).toString("hex");
  if (signature !== "89504e470d0a1a0a") throw new Error("screenshot is not a PNG");

  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idat = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString("ascii");
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
    } else if (type === "IDAT") {
      idat.push(data);
    } else if (type === "IEND") {
      break;
    }
    offset += 12 + length;
  }

  if (bitDepth !== 8 || (colorType !== 2 && colorType !== 6)) {
    throw new Error(`unsupported PNG format: bitDepth=${bitDepth}, colorType=${colorType}`);
  }

  const channels = colorType === 6 ? 4 : 3;
  const stride = width * channels;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const rows = Buffer.alloc(stride * height);

  for (let y = 0; y < height; y += 1) {
    const srcOffset = y * (stride + 1);
    const filter = raw[srcOffset];
    const src = raw.subarray(srcOffset + 1, srcOffset + 1 + stride);
    const rowOffset = y * stride;
    const prevOffset = (y - 1) * stride;
    for (let x = 0; x < stride; x += 1) {
      const left = x >= channels ? rows[rowOffset + x - channels] : 0;
      const up = y > 0 ? rows[prevOffset + x] : 0;
      const upLeft = y > 0 && x >= channels ? rows[prevOffset + x - channels] : 0;
      let predictor = 0;
      if (filter === 1) predictor = left;
      else if (filter === 2) predictor = up;
      else if (filter === 3) predictor = Math.floor((left + up) / 2);
      else if (filter === 4) predictor = paeth(left, up, upLeft);
      else if (filter !== 0) throw new Error(`unsupported PNG filter: ${filter}`);
      rows[rowOffset + x] = (src[x] + predictor) & 0xff;
    }
  }

  let bright = 0;
  let colored = 0;
  let nonBlack = 0;
  for (let i = 0; i < rows.length; i += channels * 4) {
    const r = rows[i];
    const g = rows[i + 1];
    const b = rows[i + 2];
    if (r + g + b > 24) nonBlack += 1;
    if (r + g + b > 180) bright += 1;
    if (Math.max(r, g, b) - Math.min(r, g, b) > 16) colored += 1;
  }
  return {
    ok: nonBlack > 500 && (bright > 50 || colored > 40),
    width,
    height,
    bright,
    colored,
    nonBlack,
  };
}

async function runViewport(browser, baseUrl, viewport, name, firstNodeName) {
  const page = await browser.newPage({
    viewport,
    deviceScaleFactor: name === "mobile" ? 2 : 1,
  });
  const result = { name, viewport };
  await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 45_000 });
  await page.waitForSelector("canvas", { timeout: 20_000 });
  await page.getByText(/(DJs|节点)\s*\//).waitFor({ timeout: 20_000 });
  await page.waitForTimeout(1200);
  const canvas = page.locator("canvas").first();
  const canvasPng = await canvas.screenshot({ path: path.join(outDir, `${name}-canvas.png`) });
  const stats = pngStats(canvasPng);
  result.canvas = stats;
  if (!stats.ok) throw new Error(`${name} canvas pixel check failed: ${JSON.stringify(stats)}`);

  await page.screenshot({ path: path.join(outDir, `${name}.png`), fullPage: true });

  if (name === "mobile") {
    await page.getByRole("button", { name: "打开搜索筛选" }).click();
  }
  const input = page.locator('input[placeholder*="搜索"]').first();
  await input.fill(firstNodeName);
  await page.getByRole("button", { name: new RegExp(firstNodeName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).first().click();
  await page.getByText("直接关系").waitFor({ timeout: 10_000 });
  await page.screenshot({ path: path.join(outDir, `${name}-detail.png`), fullPage: true });
  result.detailVisible = true;
  await page.close();
  return result;
}

async function main() {
  const layout = readLayout();
  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}/atlas-starmap-assets/`;
  const server = startVite(port);
  const started = Date.now();
  const result = {
    ok: false,
    baseUrl,
    layout,
    started_at: new Date().toISOString(),
    desktop: null,
    mobile: null,
  };

  try {
    await waitForHttp(`${baseUrl}atlas_layout.json`);
    const browser = await chromium.launch({ headless: true });
    try {
      result.desktop = await runViewport(browser, baseUrl, { width: 1365, height: 900 }, "desktop", layout.firstNodeName);
      result.mobile = await runViewport(browser, baseUrl, { width: 390, height: 844 }, "mobile", layout.firstNodeName);
    } finally {
      await browser.close();
    }
    result.ok = true;
    result.elapsed_ms = Date.now() - started;
    fs.writeFileSync(path.join(outDir, "playwright-result.json"), `${JSON.stringify(result, null, 2)}\n`, "utf8");
  } catch (error) {
    result.error = error instanceof Error ? error.message : String(error);
    result.elapsed_ms = Date.now() - started;
    fs.writeFileSync(path.join(outDir, "playwright-result.json"), `${JSON.stringify(result, null, 2)}\n`, "utf8");
    throw error;
  } finally {
    server.kill();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
