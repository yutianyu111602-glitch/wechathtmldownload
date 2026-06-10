#!/usr/bin/env node
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createDeepSeekClient } from "../src/deepSeekClient.mjs";
import { storageSlug } from "../src/dataStore.mjs";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.resolve(moduleDir, "../data/current_release");
const CONCURRENCY = 3;
const REQUEST_TIMEOUT_MS = 60000;

async function main() {
  const current = JSON.parse(await readFile(path.join(DATA_DIR, "current.json"), "utf8"));
  const items = current.items;
  const enrichDir = path.join(DATA_DIR, "llm", "enrichments");
  await mkdir(enrichDir, { recursive: true });

  const client = createDeepSeekClient(process.env);
  const existing = new Set();
  
  // 找已有 enrichment
  const { readdir } = await import("node:fs/promises");
  try {
    for (const f of await readdir(enrichDir)) {
      if (f.endsWith('.json')) existing.add(f.replace('.json', ''));
    }
  } catch {}

  // 找未富化的 (排除已有 enrichment 文件的)
  const todo = items.filter(i => !existing.has(storageSlug(i.id || i.event_id || '')));
  if (todo.length === 0) {
    console.log('所有 item 已富化，无需处理');
    return;
  }
  console.log(`总: ${items.length}, 已有: ${existing.size}, 待处理: ${todo.length}`);

  let done = 0, fail = 0;
  const queue = [...todo];
  
  async function worker() {
    while (queue.length) {
      const item = queue.shift();
      const safeId = storageSlug(item.id);
      try {
        const enriched = await client.enrichEvent(item);
        await writeFile(
          path.join(enrichDir, `${safeId}.json`),
          JSON.stringify({
            schemaVersion: "weekly_activity_api.materialized_enrichment.v1",
            generatedAt: new Date().toISOString(),
            id: item.id,
            enriched,
          }, null, 2)
        );
        done++;
        if (done % 10 === 0) console.log(`  进度: ${done}/${todo.length} (失败: ${fail})`);
      } catch (err) {
        fail++;
        console.error(`  ✗ ${item.id}: ${err.message}`);
      }
    }
  }

  const workers = Array(Math.min(CONCURRENCY, todo.length)).fill(0).map(() => worker());
  await Promise.all(workers);
  console.log(`完成: ${done} 成功, ${fail} 失败`);
}

main().catch(e => { console.error(e.message); process.exit(1); });
