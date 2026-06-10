import { stat, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { analyzeArticleHtmlQuality } from "./articleHtmlQuality.js";
import type { ArchiveMetaJson, ArchiveQueueRecord } from "./types.js";
import { writeJson } from "../utils/fs.js";

interface CaptureResult {
  finalUrl: string;
  rawHtml: string;
  mhtml: string;
  pdf: Buffer;
  title: string;
  warnings: string[];
}

interface ArchiveArticleDependencies {
  capturePage?: (url: string) => Promise<CaptureResult>;
  now?: () => string;
}

function nowIso(now: (() => string) | undefined): string {
  return now ? now() : new Date().toISOString();
}

function isWeChatCaptchaCapture(capture: CaptureResult): boolean {
  return (
    /wappoc_appmsgcaptcha|appmsgcaptcha/i.test(capture.finalUrl || "") ||
    /wappoc_appmsgcaptcha|appmsgcaptcha/i.test(capture.rawHtml || "")
  );
}

function uniqueWarnings(warnings: string[]): string[] {
  return [...new Set(warnings.filter(Boolean))];
}

async function loadPlaywrightModule(): Promise<any> {
  const moduleNames = ["playwright-core", "playwright"];
  for (const moduleName of moduleNames) {
    try {
      return await import(moduleName);
    } catch {
      // Try next candidate.
    }
  }
  throw new Error(
    "Missing browser runtime. Install playwright-core or playwright before running archive capture.",
  );
}

async function defaultCapturePage(url: string): Promise<CaptureResult> {
  const playwright = await loadPlaywrightModule();
  const browser = await playwright.chromium.launch({
    channel: "chrome",
    headless: true,
  });

  try {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    });
    const page = await context.newPage();
    await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
    await page.waitForTimeout(1500);
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)");
    await page.waitForTimeout(1500);
    await page.evaluate("window.scrollTo(0, 0)");
    await page.waitForTimeout(600);

    const finalUrl = page.url();
    const title = await page.title();
    const rawHtml = await page.content();
    const cdp = await context.newCDPSession(page);
    const snapshot = await cdp.send("Page.captureSnapshot", { format: "mhtml" });
    const pdf = Buffer.from(
      await page.pdf({
        format: "A4",
        printBackground: true,
        margin: {
          top: "10mm",
          bottom: "10mm",
          left: "5mm",
          right: "5mm",
        },
      }),
    );

    await cdp.detach();
    await page.close();
    await context.close();

    return {
      finalUrl,
      rawHtml,
      mhtml: snapshot?.data || "",
      pdf,
      title,
      warnings: [],
    };
  } finally {
    await browser.close();
  }
}

export async function archiveArticle(
  record: ArchiveQueueRecord,
  outDir: string,
  dependencies: ArchiveArticleDependencies = {},
): Promise<ArchiveMetaJson> {
  const capturePage = dependencies.capturePage || defaultCapturePage;
  const archivedAt = nowIso(dependencies.now);
  const capture = await capturePage(record.source_url);

  const rawHtmlPath = join(outDir, "raw.html");
  const mhtmlPath = join(outDir, "page.mhtml");
  const pdfPath = join(outDir, "page.pdf");
  const urlPath = join(outDir, "article.url.txt");
  await writeFile(rawHtmlPath, capture.rawHtml, "utf-8");
  await writeFile(mhtmlPath, capture.mhtml, "utf-8");
  await writeFile(pdfPath, capture.pdf);
  await writeFile(urlPath, `${record.source_url}\n`, "utf-8");

  const [rawStat, mhtmlStat, pdfStat] = await Promise.all([
    stat(rawHtmlPath),
    stat(mhtmlPath),
    stat(pdfPath),
  ]);
  const quality = analyzeArticleHtmlQuality(capture.rawHtml);
  const captchaWarnings = isWeChatCaptchaCapture(capture)
    ? ["playwright capture landed on WeChat captcha page"]
    : [];
  const qualityWarnings = quality.valid
    ? []
    : quality.warnings.map((warning) => `playwright capture returned invalid html: ${warning}`);
  const hasArchiveBytes = rawStat.size > 0 && (mhtmlStat.size > 0 || pdfStat.size > 0);
  const archiveStatus: ArchiveMetaJson["status"] =
    hasArchiveBytes && quality.valid && captchaWarnings.length === 0 ? "archived" : "partial";
  const meta: ArchiveMetaJson = {
    account_key: record.account_key,
    token: record.token,
    source_url: record.source_url,
    final_url: capture.finalUrl || record.source_url,
    title: capture.title || record.title,
    archived_at: archivedAt,
    status: archiveStatus,
    capture_method: "playwright",
    raw_html_bytes: rawStat.size,
    mhtml_bytes: mhtmlStat.size,
    pdf_bytes: pdfStat.size,
    warnings: uniqueWarnings([...capture.warnings, ...captchaWarnings, ...qualityWarnings]),
  };
  await writeJson(join(outDir, "archive_meta.json"), meta);
  return meta;
}
