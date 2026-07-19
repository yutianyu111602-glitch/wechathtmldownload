const https = require("node:https");
const { URL } = require("node:url");

const DEFAULT_BASE_URL = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com";
const DEFAULT_CLOUDBASE_AI_PROVIDER = "hunyuan-v3";
const DEFAULT_CLOUDBASE_AI_MODEL = "hy3-preview";
const DEFAULT_AI_TIMEOUT_MS = 60000;
const DEFAULT_ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e";
const DEFAULT_HEALTH_PROBE_TIMEOUT_MS = 2500;
const MAX_CONTEXT_CHARS = 7000;
const ALLOWED_PATHS = new Set([
  "/api/v1/weekly/llm/status",
  "/api/v1/weekly/llm/health-check",
  "/api/v1/weekly/llm/materialized-summary",
  "/api/v1/weekly/llm/materialized-enrichments",
  "/api/v1/weekly/llm/weekly-summary",
]);

let cloudbaseApp = null;

function normalizeMethod(value) {
  const method = String(value || "GET").trim().toUpperCase();
  return method === "POST" ? "POST" : "GET";
}

function normalizePath(value) {
  const path = String(value || "").trim();
  if (!path.startsWith("/api/v1/weekly/llm/")) return "";
  if (ALLOWED_PATHS.has(path)) return path;
  if (path.startsWith("/api/v1/weekly/llm/materialized-enrichments/")) return path;
  if (path === "/api/v1/weekly/llm/enrich") return path;
  return "";
}

function appendQuery(url, query) {
  const input = query && typeof query === "object" ? query : {};
  Object.keys(input).forEach((key) => {
    const value = input[key];
    if (value === undefined || value === null || value === "") return;
    url.searchParams.set(key, String(value));
  });
}

function requestJson(url, { method, body, timeoutMs }) {
  return new Promise((resolve, reject) => {
    const payload = method === "POST" && body ? Buffer.from(JSON.stringify(body), "utf8") : null;
    const req = https.request(url, {
      method,
      timeout: timeoutMs,
      headers: {
        Accept: "application/json",
        ...(payload ? {
          "Content-Type": "application/json",
          "Content-Length": String(payload.length),
        } : {}),
      },
    }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        let data = null;
        try {
          data = raw ? JSON.parse(raw) : {};
        } catch (error) {
          reject(Object.assign(new Error("AI proxy upstream returned non-JSON response"), {
            code: "UPSTREAM_NON_JSON",
            statusCode: res.statusCode,
          }));
          return;
        }
        if (res.statusCode < 200 || res.statusCode >= 300 || data.error) {
          reject(Object.assign(new Error("AI proxy upstream request failed"), {
            code: "UPSTREAM_FAILED",
            statusCode: res.statusCode,
            data,
          }));
          return;
        }
        resolve(data);
      });
    });
    req.on("timeout", () => {
      req.destroy(Object.assign(new Error("AI proxy upstream timed out"), { code: "UPSTREAM_TIMEOUT" }));
    });
    req.on("error", reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function getCloudBaseApp() {
  const tcb = require("@cloudbase/node-sdk");
  if (!cloudbaseApp) {
    cloudbaseApp = tcb.init({
      env: process.env.TCB_ENV || process.env.ENV_ID || process.env.SCF_NAMESPACE || DEFAULT_ENV_ID,
      timeout: Number(process.env.WEEKLY_CLOUDBASE_AI_TIMEOUT_MS || DEFAULT_AI_TIMEOUT_MS),
    });
  }
  return cloudbaseApp;
}

function getCloudBaseAiModel() {
  const app = getCloudBaseApp();
  const provider = process.env.WEEKLY_CLOUDBASE_AI_PROVIDER || DEFAULT_CLOUDBASE_AI_PROVIDER;
  return {
    provider,
    modelName: process.env.WEEKLY_CLOUDBASE_AI_MODEL || DEFAULT_CLOUDBASE_AI_MODEL,
    model: app.ai().createModel(provider),
  };
}

function compactJson(value) {
  let text = "";
  try {
    text = JSON.stringify(value || {}, null, 2);
  } catch (error) {
    text = String(value || "");
  }
  if (text.length <= MAX_CONTEXT_CHARS) return text;
  return `${text.slice(0, MAX_CONTEXT_CHARS)}\n...[truncated]`;
}

function firstDoc(result) {
  if (!result) return null;
  if (Array.isArray(result.data)) return result.data[0] || null;
  return result.data || null;
}

function payloadShape(payload) {
  return {
    schemaVersion: payload && (payload.schemaVersion || payload.schema_version) || null,
    status: payload && payload.status || null,
    service: payload && payload.service || null,
    source: payload && payload.source || null,
    generatedAt: payload && (payload.generatedAt || payload.generated_at) || null,
    itemCount: payload && Array.isArray(payload.items) ? payload.items.length : null,
    cityCount: payload && Array.isArray(payload.cities) ? payload.cities.length : null,
    total: payload && payload.page && typeof payload.page.total === "number" ? payload.page.total : null,
  };
}

async function probeWeeklyApi(baseUrl, path, timeoutMs) {
  const startedAt = Date.now();
  try {
    const payload = await requestJson(new URL(`${baseUrl}${path}`), {
      method: "GET",
      body: {},
      timeoutMs,
    });
    return {
      ok: true,
      path,
      ms: Date.now() - startedAt,
      ...payloadShape(payload),
    };
  } catch (error) {
    return {
      ok: false,
      path,
      ms: Date.now() - startedAt,
      code: error.code || "PROBE_FAILED",
      message: error.message || String(error),
      statusCode: error.statusCode || 0,
    };
  }
}

async function readCloudBaseDatabaseHealth() {
  try {
    const db = getCloudBaseApp().database();
    const [currentResult, eventSampleResult, citySampleResult, summarySampleResult, configSampleResult] = await Promise.all([
      db.collection("weekly_current").doc("current").get(),
      db.collection("weekly_events").limit(1).get(),
      db.collection("weekly_cities").limit(1).get(),
      db.collection("weekly_ai_summary").limit(1).get(),
      db.collection("weekly_config").limit(1).get(),
    ]);
    const current = firstDoc(currentResult) || {};
    return {
      ok: true,
      source: "cloudbase-database",
      collections: {
        weekly_current: {
          readable: Boolean(current && current._id),
          syncId: current.syncId || null,
          syncedAt: current.syncedAt || null,
          generatedAt: current.generatedAt || null,
          itemCount: typeof current.itemCount === "number" ? current.itemCount : null,
          source: current.source || null,
          sourceBaseUrl: current.sourceBaseUrl || null,
        },
        weekly_events: {
          sampleReadable: Boolean(eventSampleResult && Array.isArray(eventSampleResult.data) && eventSampleResult.data.length),
        },
        weekly_cities: {
          sampleReadable: Boolean(citySampleResult && Array.isArray(citySampleResult.data) && citySampleResult.data.length),
        },
        weekly_ai_summary: {
          sampleReadable: Boolean(summarySampleResult && Array.isArray(summarySampleResult.data) && summarySampleResult.data.length),
        },
        weekly_config: {
          sampleReadable: Boolean(configSampleResult && Array.isArray(configSampleResult.data) && configSampleResult.data.length),
        },
      },
    };
  } catch (error) {
    return {
      ok: false,
      source: "cloudbase-database",
      code: error.code || error.errCode || "DATABASE_HEALTH_FAILED",
      message: error.message || error.errMsg || String(error),
    };
  }
}

function parseJsonObject(text) {
  const raw = String(text || "").trim();
  if (!raw) return null;
  const candidates = [
    raw,
    raw.replace(/^```json\s*/i, "").replace(/```$/i, "").trim(),
  ];
  const match = raw.match(/\{[\s\S]*\}/);
  if (match) candidates.push(match[0]);
  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch {}
  }
  return null;
}

function cloudFunctionMeta(extra = {}) {
  return {
    name: "weeklyAiProxy",
    source: "wechat-cloudbase-ai",
    aiProvider: process.env.WEEKLY_CLOUDBASE_AI_PROVIDER || DEFAULT_CLOUDBASE_AI_PROVIDER,
    aiModel: process.env.WEEKLY_CLOUDBASE_AI_MODEL || DEFAULT_CLOUDBASE_AI_MODEL,
    fallback: "cloudrun-weekly-api",
    ...extra,
  };
}

async function generateCloudBaseHealthCheck({ baseUrl, timeoutMs, frontendEvidence = null }) {
  const probeTimeoutMs = Number(process.env.WEEKLY_HEALTH_PROBE_TIMEOUT_MS || DEFAULT_HEALTH_PROBE_TIMEOUT_MS);
  const expectedAiProvider = process.env.WEEKLY_CLOUDBASE_AI_PROVIDER || DEFAULT_CLOUDBASE_AI_PROVIDER;
  const expectedAiModel = process.env.WEEKLY_CLOUDBASE_AI_MODEL || DEFAULT_CLOUDBASE_AI_MODEL;
  const [healthz, current, cities, materializedSummary, database] = await Promise.all([
    probeWeeklyApi(baseUrl, "/healthz", probeTimeoutMs),
    probeWeeklyApi(baseUrl, "/api/v1/weekly/current?limit=3", probeTimeoutMs),
    probeWeeklyApi(baseUrl, "/api/v1/weekly/cities", probeTimeoutMs),
    probeWeeklyApi(baseUrl, "/api/v1/weekly/llm/materialized-summary", probeTimeoutMs),
    readCloudBaseDatabaseHealth(),
  ]);

  const evidence = {
    checkedAt: new Date().toISOString(),
    envId: process.env.TCB_ENV || process.env.ENV_ID || process.env.SCF_NAMESPACE || DEFAULT_ENV_ID,
    appId: "wx0bc0a1d9d892af2d",
    miniProgram: {
      frontendPages: ["pages/index/index", "pages/ai/ai"],
      dataReadOrder: ["CloudBase Database via weeklyDataSync", "CloudRun weekly-api fallback"],
      frontendProbe: frontendEvidence || {
        ok: null,
        note: "No rendered frontend probe was supplied by the caller. Server-side CloudBase functions cannot render Mini Program pages.",
      },
    },
    cloudFunctions: ["weeklyAiProxy", "weeklyDataSync", "weekly-api"],
    cloudbaseAI: {
      provider: expectedAiProvider,
      model: expectedAiModel,
      healthRoutePrimary: "cloudbase-ai",
      note: "This health-check route itself calls CloudBase AI. If this route returns schemaVersion weekly_activity_api.health_check.v1 with source cloudbase-ai and no error, the AI generation path is available.",
    },
    cloudRun: {
      baseUrl,
      probes: [healthz, current, cities, materializedSummary],
    },
    database,
    expected: {
      aiProvider: expectedAiProvider,
      aiModel: expectedAiModel,
      collections: ["weekly_current", "weekly_events", "weekly_cities", "weekly_ai_summary", "weekly_config"],
      resourcePackageDefinition: "The resource package means the weekly activity data package exposed by CloudRun and mirrored into CloudBase Database: current events, city index, and materialized AI summary. It does not mean Tencent Cloud billing quota.",
      noSecretPolicy: true,
    },
  };

  const { provider, modelName, model } = getCloudBaseAiModel();
  const result = await model.generateText({
    model: modelName,
    messages: [
      {
        role: "system",
        content: [
          "你是 HUAIDJ Weekly 微信小程序的云开发健康检查助手。",
          "你必须只根据用户给出的 JSON 证据判断，不要编造控制台额度、隐藏日志或未给出的信息。",
          "输出必须是严格 JSON 对象，不要 Markdown，不要代码块，不要解释性前后缀。",
          "字段必须包含 overallStatus, frontend, backend, cloudbaseDatabase, cloudbaseAI, resourcePackage, risks, nextActions。",
          "overallStatus 只能是 healthy、degraded、blocked 之一。",
          "每个模块必须包含 status、evidence、reason。status 只能是 ok、warning、fail、unknown。",
          "resourcePackage 指活动数据包 current/cities/materialized-summary，不是腾讯云套餐额度。",
          "若 miniProgram.frontendProbe.ok 为 true，前端可按该证据判断 ok；若为 null，前端必须 unknown。",
          "若本路由成功返回 cloudbase-ai 生成结果，则 cloudbaseAI 可根据 cloudbaseAI 证据判断 ok。",
          "如果证据不足，status 用 unknown 或 warning，并说明缺少什么证据。",
        ].join("\n"),
      },
      {
        role: "user",
        content: `请检查小程序当前健康状态。只允许依据以下证据输出 JSON。\n\n证据：\n${compactJson(evidence)}`,
      },
    ],
    temperature: 0.1,
    topP: 0.5,
  });

  const text = result.text || "";
  const parsed = parseJsonObject(text);
  return {
    schemaVersion: "weekly_activity_api.health_check.v1",
    generatedAt: new Date().toISOString(),
    provider,
    model: modelName,
    source: "cloudbase-ai",
    evidence,
    health: parsed,
    aiText: parsed ? undefined : text.slice(0, 4000),
    usage: result.usage || null,
    cloudFunction: cloudFunctionMeta({
      route: "health-check",
      primary: "cloudbase-ai",
      fallbackUsed: false,
    }),
  };
}

function cloudBaseStatus() {
  const provider = process.env.WEEKLY_CLOUDBASE_AI_PROVIDER || DEFAULT_CLOUDBASE_AI_PROVIDER;
  const model = process.env.WEEKLY_CLOUDBASE_AI_MODEL || DEFAULT_CLOUDBASE_AI_MODEL;
  return {
    schemaVersion: "weekly_activity_api.llm_status.v1",
    llm: {
      provider,
      configured: true,
      baseUrl: "cloudbase-ai",
      model,
      timeoutMs: Number(process.env.WEEKLY_CLOUDBASE_AI_TIMEOUT_MS || DEFAULT_AI_TIMEOUT_MS),
      timeoutDisabled: false,
      thinking: "disabled",
      primary: "cloudbase-ai",
      fallback: "cloudrun-weekly-api",
    },
    cloudFunction: cloudFunctionMeta({
      route: "status",
    }),
  };
}

async function generateCloudBaseWeeklySummary({ baseUrl, timeoutMs }) {
  let sourcePayload = null;
  let sourceError = null;
  try {
    sourcePayload = await requestJson(new URL(`${baseUrl}/api/v1/weekly/llm/materialized-summary`), {
      method: "GET",
      body: {},
      timeoutMs: Math.min(timeoutMs, 2500),
    });
  } catch (error) {
    sourceError = {
      code: error.code || "SOURCE_UNAVAILABLE",
      message: error.message || String(error),
    };
  }

  const { provider, modelName, model } = getCloudBaseAiModel();
  const sourceText = compactJson(sourcePayload || {
    note: "No materialized summary was available. Generate a concise status note for HUAIDJ Weekly and mention that source data needs refresh.",
  });
  const result = await model.generateText({
    model: modelName,
    messages: [
      {
        role: "system",
        content: "你是坏DJclub本周电音活动小程序的云开发AI摘要助手。输出中文，简洁、克制、像运营后台摘要，不编造具体活动。若资料不足，明确说明需要刷新数据。",
      },
      {
        role: "user",
        content: `请基于以下本周活动资料生成一段小程序内可展示的摘要，控制在 180 字以内。\n\n资料：\n${sourceText}`,
      },
    ],
    temperature: 0.3,
    topP: 0.8,
  });

  return {
    schemaVersion: "weekly_activity_api.weekly_summary.v1",
    summary: result.text || "",
    generatedAt: new Date().toISOString(),
    provider,
    model: modelName,
    usage: result.usage || null,
    source: "cloudbase-ai",
    sourcePayloadAvailable: Boolean(sourcePayload),
    sourceError,
    cloudFunction: cloudFunctionMeta({
      route: "weekly-summary",
      primary: "cloudbase-ai",
    }),
  };
}

async function proxyUpstream({ baseUrl, path, method, query, body, timeoutMs, fallbackReason }) {
  const url = new URL(`${baseUrl}${path}`);
  appendQuery(url, query);
  const payload = await requestJson(url, {
    method,
    body: body || {},
    timeoutMs,
  });
  return {
    ...payload,
    cloudFunction: cloudFunctionMeta({
      source: "wechat-cloudbase",
      upstream: baseUrl,
      fallbackUsed: Boolean(fallbackReason),
      fallbackReason: fallbackReason || null,
    }),
  };
}

exports.main = async (event = {}) => {
  const path = normalizePath(event.path);
  if (!path) {
    return {
      error: {
        code: "AI_PROXY_PATH_NOT_ALLOWED",
        message: "Only weekly LLM routes are allowed.",
      },
    };
  }

  const baseUrl = String(process.env.WEEKLY_AI_PROXY_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, "");
  const method = normalizeMethod(event.method);
  const timeoutMs = Number(process.env.WEEKLY_AI_PROXY_TIMEOUT_MS || 2500);

  if (path === "/api/v1/weekly/llm/status") {
    return cloudBaseStatus();
  }

  if (path === "/api/v1/weekly/llm/health-check" && method === "GET") {
    try {
      return await generateCloudBaseHealthCheck({
        baseUrl,
        timeoutMs: Number(process.env.WEEKLY_CLOUDBASE_AI_TIMEOUT_MS || DEFAULT_AI_TIMEOUT_MS),
        frontendEvidence: event.frontendEvidence || null,
      });
    } catch (error) {
      return {
        schemaVersion: "weekly_activity_api.health_check.v1",
        generatedAt: new Date().toISOString(),
        error: {
          code: error.code || "CLOUDBASE_AI_HEALTH_CHECK_FAILED",
          message: error.message || String(error),
        },
        cloudFunction: cloudFunctionMeta({
          route: "health-check",
          primary: "cloudbase-ai",
        }),
      };
    }
  }

  if (path === "/api/v1/weekly/llm/weekly-summary" && method === "GET") {
    try {
      return await generateCloudBaseWeeklySummary({
        baseUrl,
        timeoutMs: Number(process.env.WEEKLY_CLOUDBASE_AI_TIMEOUT_MS || DEFAULT_AI_TIMEOUT_MS),
      });
    } catch (error) {
      try {
        return await proxyUpstream({
          baseUrl,
          path,
          method,
          query: event.query,
          body: event.body || {},
          timeoutMs,
          fallbackReason: {
            code: error.code || "CLOUDBASE_AI_FAILED",
            message: error.message || String(error),
          },
        });
      } catch (fallbackError) {
        return {
          error: {
            code: fallbackError.code || error.code || "AI_PROXY_FAILED",
            message: fallbackError.message || error.message || String(error),
            statusCode: fallbackError.statusCode || 0,
            primaryError: {
              code: error.code || "CLOUDBASE_AI_FAILED",
              message: error.message || String(error),
            },
            upstreamError: fallbackError.data || null,
          },
          cloudFunction: cloudFunctionMeta({
            route: "weekly-summary",
            primary: "cloudbase-ai",
            fallbackUsed: true,
          }),
        };
      }
    }
  }

  try {
    return await proxyUpstream({
      baseUrl,
      path,
      method,
      query: event.query,
      body: event.body || {},
      timeoutMs,
    });
  } catch (error) {
    return {
      error: {
        code: error.code || "AI_PROXY_FAILED",
        message: error.message || String(error),
        statusCode: error.statusCode || 0,
        upstreamError: error.data || null,
      },
      cloudFunction: cloudFunctionMeta({
        source: "wechat-cloudbase",
        upstream: baseUrl,
      }),
    };
  }
};
