import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

const base = process.argv[2];
if (!base) {
  console.error('usage: node check-current-release-consistency.mjs <current_release_dir>');
  process.exit(2);
}

const manifest = JSON.parse(await readFile(path.join(base, 'manifest.json'), 'utf8'));
const current = JSON.parse(await readFile(path.join(base, 'current.json'), 'utf8'));
const byIdDir = path.join(base, 'by-id');
const llmDir = path.join(base, 'llm', 'enrichments');

const byIdCount = (await readdir(byIdDir)).filter((x) => x.endsWith('.json')).length;
let llmCount = 0;
try {
  llmCount = (await readdir(llmDir)).filter((x) => x.endsWith('.json')).length;
} catch {
  llmCount = byIdCount;
}

const expected = manifest.item_count;
const actual = current.items.length;

const ok = expected === actual && expected === byIdCount && expected === llmCount;
const report = { expected, actual, byIdCount, llmCount, ok };

console.log(JSON.stringify(report, null, 2));
process.exit(ok ? 0 : 3);
