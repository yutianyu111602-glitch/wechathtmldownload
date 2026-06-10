#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { createDeepSeekClient } from "../../../services/weekly_activity_cloudrun/src/deepSeekClient.mjs";

const DEFAULT_QUEUE =
  "D:\\downstream_results\\stage7_rewrite\\longrun\\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\\latest_queue.jsonl";
const DEFAULT_CURRENT =
  "D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260521_TICKETING_REPAIR_V2\\current.json";
const DEFAULT_OUT_DIR = "tools/stage7_rewrite/reports/weekly_ticketing_strategy_eval_20260521";

const TIME_CONDITIONAL_FREE_RE =
  /(?:\b[0-2]?\d\s*(?:am|pm)|[0-2]?\d[:：][0-5]\d|凌晨\s*[0-9]{1,2}\s*点(?:半)?)\s*(?:后|之后|以后|前|之前|以前)\s*(?:免费入场|免票入场|免票|free\s*entry)/gi;
const FREE_ENTRY_RE = /(?:免费入场|免票入场|免票|free\s*entry)/i;
const TICKETING_LABEL_RE =
  /(预售|早鸟|双人|单人|现场|门票|票价|学生|全价|入场|presale|pre-sale|advance|door|onsite|on\s*site|at\s*door|tickets?|enter)/i;
const TICKETING_TIER_RE =
  /(预售|早鸟|双人|单人|现场|门票|票价|学生|全价|入场|presale|pre-sale|advance|door|onsite|on\s*site|at\s*door|tickets?|enter)\s*[:：/]?\s*(?:¥|￥|RMB\s*|CNY\s*)?\s*\d+(?:\.\d+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny)?/gi;
const VISIBLE_AMOUNT_RE = /(?:¥|￥|RMB\s*|CNY\s*)?\s*\d+(?:\.\d+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny)?/i;
const QR_ONLY_TICKETING_RE = /(芋圆|yuyuan|小程序码|二维码|扫码|购票链接|点击购票|click\s+for\s+tickets?)/i;
const DRINK_SPECIAL_RE = /(金汤力|啤酒|酒水|特调|鸡尾酒|杯|shot|drink|drinks|bottle|套餐|放送)/i;

const SAMPLE_SPECS = [
  {
    id: "exit_0522_tiered",
    queueId: "exit_shanghai:3082bf6846c3bd22",
    expected: ["预售 70¥", "双人 128¥", "现场 100¥", "3am 后免费入场"],
  },
  {
    id: "exit_0523_tiered",
    queueId: "exit_shanghai:369ef80068badd45",
    expected: ["预售 98¥", "现场 148¥", "双人 188¥", "3am 后免费入场"],
  },
  {
    id: "giftspace_yuyuan_only",
    queueId: "giftspacedlc:2f0bd98adf32e438",
    expected: [],
  },
  {
    id: "defun_free_drink_special",
    queueId: "defun:9ac649cd6bd809f9",
    expected: ["FREE ENTRY"],
  },
  {
    id: "exit_okvlt13_tiered",
    queueId: "exit_shanghai:83b8ba7aa53732b7",
    expected: ["预售 88¥", "双人 158¥", "现场 118¥", "3am 后免费入场"],
  },
  {
    id: "exit_eurostar_tiered",
    queueId: "exit_shanghai:7d9c33fdfdbd8fbe",
    expected: ["早鸟 68¥", "预售 88¥", "双人 158¥", "现场 118¥", "3am 后免费入场"],
  },
  {
    id: "reactor_after_0300_free_only",
    queueId: "reactor_shanghai:b0735f918c501fc6",
    expected: ["03:00 后免票入场"],
  },
  {
    id: "aurora_tiers_and_before_free",
    queueId: "aurora_bj:3d959d0fe14de5eb",
    expected: ["预售: ¥79", "现场: ¥99", "21:30 前免费入场"],
  },
  {
    id: "powderblack_enter_35",
    queueId: "powderblackdancefloor:d312f79843362ef0",
    expected: ["Enter: 35RMB"],
  },
  {
    id: "nu_lab_store_yuyuan_only",
    queueId: "nu_lab:c946f647676b1887",
    expected: [],
  },
];

function parseArgs(argv) {
  const args = {
    queue: DEFAULT_QUEUE,
    current: DEFAULT_CURRENT,
    outDir: DEFAULT_OUT_DIR,
    runs: 1,
    noLlm: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--queue") args.queue = argv[++i];
    else if (arg === "--current") args.current = argv[++i];
    else if (arg === "--out-dir") args.outDir = argv[++i];
    else if (arg === "--runs") args.runs = Number.parseInt(argv[++i], 10) || 1;
    else if (arg === "--no-llm") args.noLlm = true;
  }
  return args;
}

function readJsonlByQueueId(filePath) {
  const rows = new Map();
  if (!fs.existsSync(filePath)) return rows;
  const raw = fs.readFileSync(filePath, "utf8");
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const row = JSON.parse(line);
    rows.set(row.queue_id || row.token || row.article_id, row);
  }
  return rows;
}

function readCurrentItems(filePath) {
  if (!fs.existsSync(filePath)) return [];
  const payload = JSON.parse(fs.readFileSync(filePath, "utf8"));
  if (Array.isArray(payload)) return payload;
  return payload.items || payload.events || payload.data || [];
}

function sampleText(row) {
  return [
    row.title,
    row.digest,
    row.summary_digest,
    row.body_text,
    row.source_evidence_text,
    row.evidence,
  ]
    .flat()
    .filter(Boolean)
    .join("\n");
}

function normalizeTicketingValue(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/￥/g, "¥")
    .replace(/\s+(元|¥)$/i, "¥")
    .replace(/\s+(rmb|cny)$/i, (_, unit) => unit.toUpperCase())
    .replace(/\s*¥\b/g, "¥");
}

function keyValue(value) {
  return normalizeTicketingValue(value)
    .toLowerCase()
    .replace(/[，,;；。]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function looksLikeDrinkPrice(value, sourceText) {
  const cleaned = normalizeTicketingValue(value);
  const amount = cleaned.match(/\d+(?:\.\d+)?/);
  if (!amount) return false;
  const normalizedSource = String(sourceText || "").normalize("NFKC");
  const re = new RegExp(escapeRegExp(amount[0]), "g");
  for (const match of normalizedSource.matchAll(re)) {
    const start = Math.max(0, match.index - 16);
    const end = Math.min(normalizedSource.length, match.index + amount[0].length + 24);
    const local = normalizedSource.slice(start, end);
    if (DRINK_SPECIAL_RE.test(local) && !TICKETING_LABEL_RE.test(local)) return true;
  }
  return false;
}

function qrOnlyTicketingText(value) {
  const cleaned = normalizeTicketingValue(value);
  return QR_ONLY_TICKETING_RE.test(cleaned) && !VISIBLE_AMOUNT_RE.test(cleaned) && !FREE_ENTRY_RE.test(cleaned);
}

function sourceRegexConservative(text) {
  const normalized = String(text || "").normalize("NFKC");
  const out = [];
  const seen = new Set();
  const add = (value) => {
    const cleaned = normalizeTicketingValue(value);
    const key = keyValue(cleaned);
    if (key && !seen.has(key)) {
      seen.add(key);
      out.push(cleaned);
    }
  };

  if (qrOnlyTicketingText(normalized)) return [];

  for (const match of normalized.matchAll(TICKETING_TIER_RE)) {
    const value = String(match[0] || "");
    const amount = value.match(/\d+(?:\.\d+)?/);
    if (amount && Number(amount[0]) < 10) continue;
    if (looksLikeDrinkPrice(value, normalized)) continue;
    add(value);
  }
  const timedFree = [];
  for (const match of normalized.matchAll(TIME_CONDITIONAL_FREE_RE)) {
    timedFree.push(match[0]);
    add(match[0]);
  }
  if (timedFree.length === 0) {
    const free = normalized.match(FREE_ENTRY_RE);
    if (free) add(free[0]);
  }
  return out.slice(0, 8);
}

function findPublishedCurrent(sample, currentItems) {
  const keys = new Set([sample.queueId, sample.row?.token, sample.row?.source_url, sample.row?.title].filter(Boolean));
  const found = currentItems.find((item) =>
    [item.id, item.article_id, item.queue_id, item.source_url, item.title, item.displayTitle]
      .filter(Boolean)
      .some((value) => keys.has(value)),
  );
  return found ? normalizeArray(found.price || found.price_text || found.ticketing_text || []) : [];
}

function normalizeArray(value) {
  const raw = Array.isArray(value) ? value : String(value || "").split(/\s*(?:\/|,|，|;|；|\|)\s*/);
  return raw.map(normalizeTicketingValue).filter(Boolean);
}

function splitTicketingValues(value) {
  const raw = Array.isArray(value) ? value : [value];
  const out = [];
  for (const item of raw) {
    if (typeof item !== "string") {
      out.push(item);
      continue;
    }
    const regexValues = sourceRegexConservative(item);
    if (regexValues.length > 1) out.push(...regexValues);
    else out.push(...normalizeArray(item));
  }
  return normalizeArray(out);
}

function collectLlmTicketing(json) {
  const textValues = [];
  for (const key of ["ticketing_text", "prices", "price", "ticket_prices", "entry_rules"]) {
    if (Array.isArray(json?.[key])) textValues.push(...json[key]);
    else if (typeof json?.[key] === "string") textValues.push(json[key]);
  }
  if (textValues.length > 0) {
    return splitTicketingValues(textValues);
  }
  const values = [];
  if (Array.isArray(json?.ticketing_tiers)) {
    for (const tier of json.ticketing_tiers) {
      if (typeof tier === "string") {
        values.push(tier);
      } else if (tier && typeof tier === "object") {
        if (tier.rule) values.push(tier.rule);
        else {
          const label = tier.label || tier.type || "";
          const amount = tier.amount || tier.price || "";
          const currency = tier.currency || "";
          const text = [label, amount ? `${amount}${currency}` : ""].filter(Boolean).join(" ");
          if (text) values.push(text);
        }
      }
    }
  }
  return normalizeArray(values);
}

function scoreResult(expected, actual) {
  const expectedKeys = new Set(expected.map(keyValue));
  const actualKeys = new Set(actual.map(keyValue));
  const missing = [...expectedKeys].filter((value) => !actualKeys.has(value));
  const extra = [...actualKeys].filter((value) => !expectedKeys.has(value));
  const correct = [...actualKeys].filter((value) => expectedKeys.has(value)).length;
  return {
    expected,
    actual,
    exact: missing.length === 0 && extra.length === 0,
    precision: actualKeys.size ? correct / actualKeys.size : expectedKeys.size ? 0 : 1,
    recall: expectedKeys.size ? correct / expectedKeys.size : actualKeys.size ? 0 : 1,
    missing,
    extra,
  };
}

function strategyMessages(strategy, sample) {
  const source = sample.text.slice(0, 6000);
  const baseSystem = "Return strict JSON only. Extract only ticket price or entry rules from the provided WeChat event source.";
  if (strategy === "llm_prompt_baseline") {
    return [
      { role: "system", content: baseSystem },
      { role: "user", content: JSON.stringify({ source, output: { ticketing_text: ["string"] } }) },
    ];
  }
  if (strategy === "llm_prompt_strict_tiers") {
    return [
      {
        role: "system",
        content: [
          baseSystem,
          "Every ticketing_text item must copy a visible amount or free-entry rule from source evidence.",
          "Do not infer ticket prices from QR codes, YuYuan/芋圆 links, click-for-ticket text, poster buttons, or activity URLs without visible amounts.",
          "Separate 早鸟/early bird, 预售/presale, 现场/door/onsite, 双人/pair, 学生/discount, and time-conditional free-entry.",
          "3am, 03:00, and 凌晨3点 are time conditions, never price 3.",
          "Drink specials and drink package prices are not ticket prices unless admission/entry is explicitly included.",
          "If no exact visible ticketing amount/rule exists, return empty arrays and an abstain_reason.",
        ].join("\n"),
      },
      {
        role: "user",
        content: JSON.stringify({
          source,
          output_schema: {
            ticketing_text: ["exact source-backed ticket price or entry rule"],
            ticketing_tiers: [{ label: "", amount: "", currency: "", rule: "", evidence_quote: "", confidence: 0 }],
            abstain_reason: "",
          },
        }),
      },
    ];
  }
  return [
    {
      role: "system",
      content: [
        baseSystem,
        "Two-pass method: first choose only source lines that explicitly discuss tickets/entry; then parse ticket tiers from those lines.",
        "Reject QR-only/YuYuan-only/link-only evidence. Reject drink specials unless the same local phrase says the price includes admission/entry.",
        "Return empty ticketing_text when uncertain.",
      ].join("\n"),
    },
    {
      role: "user",
      content: JSON.stringify({
        source,
        output_schema: {
          evidence_lines: ["short copied source line"],
          ticketing_text: ["exact source-backed ticket price or entry rule"],
          ticketing_tiers: [{ label: "", amount: "", currency: "", rule: "", evidence_quote: "", confidence: 0 }],
          abstain_reason: "",
        },
      }),
    },
  ];
}

async function runLlmStrategy(client, strategy, sample) {
  const result = await client.createJsonChat({
    messages: strategyMessages(strategy, sample),
    temperature: 0,
    maxTokens: 900,
  });
  return {
    raw: result.json,
    usage: result.usage,
    model: result.model,
    ticketing: collectLlmTicketing(result.json),
  };
}

function summarize(results) {
  const byStrategy = new Map();
  for (const row of results) {
    const bucket = byStrategy.get(row.strategy) || { strategy: row.strategy, runs: 0, exact: 0, precision: 0, recall: 0 };
    bucket.runs += 1;
    bucket.exact += row.score.exact ? 1 : 0;
    bucket.precision += row.score.precision;
    bucket.recall += row.score.recall;
    byStrategy.set(row.strategy, bucket);
  }
  return [...byStrategy.values()].map((item) => ({
    strategy: item.strategy,
    runs: item.runs,
    exact: item.exact,
    exact_rate: item.runs ? Number((item.exact / item.runs).toFixed(3)) : 0,
    avg_precision: item.runs ? Number((item.precision / item.runs).toFixed(3)) : 0,
    avg_recall: item.runs ? Number((item.recall / item.runs).toFixed(3)) : 0,
  }));
}

function writeMarkdown(outFile, payload) {
  const lines = [
    "# Weekly Ticketing Strategy Eval 2026-05-21",
    "",
    "Local script only. No CloudRun live LLM endpoint was called.",
    "",
    "## Summary",
    "",
    "| Strategy | Runs | Exact | Exact Rate | Precision | Recall |",
    "| --- | ---: | ---: | ---: | ---: | ---: |",
  ];
  for (const row of payload.summary) {
    lines.push(
      `| ${row.strategy} | ${row.runs} | ${row.exact} | ${row.exact_rate} | ${row.avg_precision} | ${row.avg_recall} |`,
    );
  }
  lines.push("", "## Cases", "");
  for (const row of payload.results) {
    lines.push(
      `- ${row.sample_id} / ${row.strategy} / run ${row.run}: exact=${row.score.exact}, actual=${JSON.stringify(
        row.score.actual,
      )}, missing=${JSON.stringify(row.score.missing)}, extra=${JSON.stringify(row.score.extra)}`,
    );
  }
  lines.push(
    "",
    "## Recommendation",
    "",
    "- 发布包默认使用 `source_regex_conservative` 作为确定性门禁：它只接受原文可见金额或免费入场规则。",
    "- LLM 只作为本地脚本的复核/补全候选，不作为无证据票价的权威来源。",
    "- QR / 芋圆 / 小程序码 / 点击购票但无金额时，票价保持空；酒水优惠不发布为门票。",
  );
  fs.writeFileSync(outFile, `${lines.join("\n")}\n`, "utf8");
}

async function main() {
  const args = parseArgs(process.argv);
  const queueRows = readJsonlByQueueId(args.queue);
  const currentItems = readCurrentItems(args.current);
  const samples = SAMPLE_SPECS.map((spec) => {
    const row = queueRows.get(spec.queueId) || {};
    return {
      ...spec,
      row,
      title: row.title || spec.id,
      text: sampleText(row) || spec.sourceText || "",
    };
  });

  const results = [];
  for (const sample of samples) {
    const published = findPublishedCurrent(sample, currentItems);
    results.push({
      sample_id: sample.id,
      queue_id: sample.queueId,
      strategy: "published_current",
      run: 1,
      score: scoreResult(sample.expected, published),
    });
    const regexValues = sourceRegexConservative(sample.text);
    results.push({
      sample_id: sample.id,
      queue_id: sample.queueId,
      strategy: "source_regex_conservative",
      run: 1,
      score: scoreResult(sample.expected, regexValues),
    });
  }

  const llmConfigured = Boolean(process.env.DEEPSEEK_API_KEY);
  if (!args.noLlm && llmConfigured) {
    process.env.DEEPSEEK_TIMEOUT_MS = process.env.DEEPSEEK_TIMEOUT_MS || "0";
    const client = createDeepSeekClient(process.env);
    for (const strategy of ["llm_prompt_baseline", "llm_prompt_strict_tiers", "llm_prompt_two_pass"]) {
      for (let run = 1; run <= args.runs; run += 1) {
        for (const sample of samples) {
          try {
            const llm = await runLlmStrategy(client, strategy, sample);
            results.push({
              sample_id: sample.id,
              queue_id: sample.queueId,
              strategy,
              run,
              model: llm.model,
              usage: llm.usage,
              raw: llm.raw,
              score: scoreResult(sample.expected, llm.ticketing),
            });
          } catch (error) {
            results.push({
              sample_id: sample.id,
              queue_id: sample.queueId,
              strategy,
              run,
              error: String(error?.message || error),
              score: scoreResult(sample.expected, []),
            });
          }
        }
      }
    }
  }

  const payload = {
    schema_version: "weekly_ticketing_strategy_eval.v1",
    generated_at: new Date().toISOString(),
    queue: args.queue,
    current: args.current,
    llm_enabled: !args.noLlm && llmConfigured,
    llm_runs: args.runs,
    samples: samples.map((sample) => ({
      id: sample.id,
      queue_id: sample.queueId,
      title: sample.title,
      expected: sample.expected,
      source_chars: sample.text.length,
    })),
    summary: summarize(results),
    results,
  };

  fs.mkdirSync(args.outDir, { recursive: true });
  const jsonPath = path.join(args.outDir, "ticketing_strategy_eval.json");
  const mdPath = path.join(args.outDir, "ticketing_strategy_eval.md");
  fs.writeFileSync(jsonPath, JSON.stringify(payload, null, 2), "utf8");
  writeMarkdown(mdPath, payload);
  console.log(JSON.stringify({ jsonPath, mdPath, summary: payload.summary }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
