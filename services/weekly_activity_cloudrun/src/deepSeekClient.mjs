import { buildWeeklyItemEnrichmentMessages } from "./llmEnrichment.mjs";

const DEFAULT_BASE_URL = "https://api.deepseek.com";
const DEFAULT_MODEL = "deepseek-v4-pro";
const DEFAULT_TIMEOUT_MS = 0;
const DEFAULT_THINKING_TYPE = "disabled";
const WEEKLY_SUMMARY_MAX_TOKENS = 4096;

function normalizeBaseUrl(value) {
  return String(value || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

function readTimeoutMs(value, fallback) {
  if (value === null || value === undefined || String(value).trim() === "") {
    return fallback;
  }
  const parsed = Number.parseInt(String(value), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function redactConfig(config) {
  return {
    provider: "deepseek",
    configured: Boolean(config.apiKey),
    baseUrl: config.baseUrl,
    model: config.model,
    timeoutMs: config.timeoutMs || null,
    timeoutDisabled: !config.timeoutMs,
    thinking: config.thinkingType,
  };
}

export class DeepSeekClient {
  constructor(config = {}, fetchImpl = globalThis.fetch) {
    this.config = {
      apiKey: config.apiKey || "",
      baseUrl: normalizeBaseUrl(config.baseUrl),
      model: config.model || DEFAULT_MODEL,
      timeoutMs: readTimeoutMs(config.timeoutMs, DEFAULT_TIMEOUT_MS),
      thinkingType: config.thinkingType || DEFAULT_THINKING_TYPE,
    };
    this.fetchImpl = fetchImpl;
  }

  publicStatus() {
    return redactConfig(this.config);
  }

  assertConfigured() {
    if (!this.config.apiKey) {
      throw new Error("DEEPSEEK_API_KEY is not configured.");
    }
    if (typeof this.fetchImpl !== "function") {
      throw new Error("fetch is not available for DeepSeek API calls.");
    }
  }

  async createJsonChat({ messages, temperature = 0.1, maxTokens = 1200 } = {}) {
    this.assertConfigured();
    const controller = this.config.timeoutMs > 0 ? new AbortController() : null;
    const timeout = controller ? setTimeout(() => controller.abort(), this.config.timeoutMs) : null;
    try {
      const request = {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.config.apiKey}`,
        },
        body: JSON.stringify({
          model: this.config.model,
          messages,
          thinking: { type: this.config.thinkingType },
          temperature,
          max_tokens: maxTokens,
          response_format: { type: "json_object" },
          stream: false,
          // Keep thinking disabled for automation. With thinking enabled, DeepSeek V4 can
          // spend the whole token budget in reasoning_content and return empty content.
        }),
      };
      if (controller) request.signal = controller.signal;
      const response = await this.fetchImpl(`${this.config.baseUrl}/chat/completions`, request);

      const raw = await response.text();
      if (!response.ok) {
        throw new Error(`DeepSeek API ${response.status}: ${raw.slice(0, 500)}`);
      }

      const payload = JSON.parse(raw);
      const message = payload?.choices?.[0]?.message || {};
      // content field may be empty for reasoning models (thinking tokens consumed all output)
      let content = message.content || "";

      // DeepSeek V4 Pro may put hidden reasoning in reasoning_content.
      // The actual JSON answer may live there when content is empty.
      // Use lastIndexOf to find the LAST { } pair, which is the final JSON answer
      // rather than any intermediate JSON fragments in the thinking trace.
      if (!content && message.reasoning_content) {
        const rc = message.reasoning_content;
        const lastBrace = rc.lastIndexOf("{");
        if (lastBrace !== -1) {
          const candidate = rc.slice(lastBrace);
          const closeIdx = candidate.lastIndexOf("}");
          if (closeIdx !== -1) {
            content = candidate.slice(0, closeIdx + 1);
          }
        }
      }

      if (!content) {
        console.error(
          `[deepseek] empty content in response. usage=${JSON.stringify(payload.usage)}, finish_reason=${
            message.finish_reason || payload?.choices?.[0]?.finish_reason
          }`,
        );
        throw new Error("DeepSeek response did not include message content.");
      }

      let parsedJson;
      try {
        parsedJson = JSON.parse(content);
      } catch (parseErr) {
        // Try to extract JSON from the content if direct parse fails
        const jsonMatch = content.match(/\{[\s\S]*\}/);
        if (jsonMatch) {
          parsedJson = JSON.parse(jsonMatch[0]);
        } else {
          throw parseErr;
        }
      }

      return {
        json: parsedJson,
        usage: payload.usage || null,
        model: payload.model || this.config.model,
      };
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  }

  async enrichEvent(item) {
    this.assertConfigured();

    // Use the detailed prompt from llmEnrichment.mjs with anti-hallucination rules
    const result = await this.createJsonChat({
      messages: buildWeeklyItemEnrichmentMessages(item),
      temperature: 0,
      maxTokens: 2400,
    });

    return {
      provider: "deepseek",
      model: result.model,
      usage: result.usage,
      enrichment: result.json,
    };
  }

  async generateWeeklySummary(items) {
    this.assertConfigured();

    const batch = items.slice(0, 30).map((item) => ({
      title: item.title || item.display_title || "",
      city: (item.city || [])[0] || item.city_key || "",
      venue: item.venue_name || (item.venue || [])[0] || "",
      date: item.event_date_iso_guess || item.event_date_start || "",
      lineup: (item.lineup || item.artist_lineup || []).slice(0, 5),
    }));

    const result = await this.createJsonChat({
      messages: [
        {
          role: "system",
          content: `You are an electronic music scene editor. Given a batch of weekly events, produce a weekly summary. Return ONLY valid JSON.

Output schema:
{
  "highlight_events": [                          // top 3-5 must-see events
    { "title": "", "reason_zh": "", "reason_en": "" }
  ],
  "city_breakdown": {                            // events per city
    "shanghai": 0, "beijing": 0, ...
  },
  "trending_artists": ["name1","name2"],         // artists appearing multiple times
  "style_distribution": {                        // music style counts
    "techno": 0, "house": 0, ...
  },
  "editor_note_zh": "",                          // 2-3 sentence weekly overview in Chinese
  "editor_note_en": ""                           // 2-3 sentence weekly overview in English
}`,
        },
        {
          role: "user",
          content: JSON.stringify({ events: batch, week_label: new Date().toISOString().slice(0, 10) }),
        },
      ],
      temperature: 0.3,
      maxTokens: WEEKLY_SUMMARY_MAX_TOKENS,
    });

    return result.json;
  }
}

export function createDeepSeekClient(env = process.env, fetchImpl = globalThis.fetch) {
  return new DeepSeekClient(
    {
      apiKey: env.DEEPSEEK_API_KEY || "",
      baseUrl: env.DEEPSEEK_BASE_URL || DEFAULT_BASE_URL,
      model: env.DEEPSEEK_MODEL || DEFAULT_MODEL,
      timeoutMs: env.DEEPSEEK_TIMEOUT_MS || DEFAULT_TIMEOUT_MS,
      thinkingType: env.DEEPSEEK_THINKING_TYPE || DEFAULT_THINKING_TYPE,
    },
    fetchImpl,
  );
}
