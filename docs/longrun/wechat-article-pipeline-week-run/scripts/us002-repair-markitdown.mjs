import fs from 'node:fs';
import path from 'node:path';

const statusPath = 'D:/rawwechat_md/markitdown-batch-status.json';
const backupPath = 'D:/rawwechat_md/markitdown-batch-status.json.bak-20260427-1320';

// Verify backup exists
if (!fs.existsSync(backupPath)) {
  console.error('BACKUP MISSING - aborting repair');
  process.exit(1);
}

const raw = fs.readFileSync(statusPath, 'utf-8');
const j = JSON.parse(raw);

console.log('Before repair:');
console.log(`  status=${j.status}`);
console.log(`  total=${j.totalItems}`);
console.log(`  succeeded=${j.succeededCount}`);
console.log(`  failed=${j.failedCount}`);
console.log(`  skipped=${j.skippedCount}`);
console.log(`  completed=${j.completedCount}`);
console.log(`  items count=${j.items ? j.items.length : 'N/A'}`);

// Find and fix stale running item
let repaired = false;
if (j.items) {
  for (const item of j.items) {
    if (item.status === 'running') {
      item.status = 'queued';
      repaired = true;
      console.log(`  Repaired stale running item: ${item.relativeInputPath || item.inputPath}`);
      break;
    }
  }
}

if (!repaired) {
  console.error('ERROR: no stale running item found');
  process.exit(1);
}

// Recompute counters from items
let queued = 0, running = 0, succeeded = 0, failed = 0, skipped = 0, cancelled = 0;
if (j.items) {
  for (const item of j.items) {
    switch (item.status) {
      case 'queued': queued++; break;
      case 'running': running++; break;
      case 'succeeded': succeeded++; break;
      case 'failed': failed++; break;
      case 'skipped': skipped++; break;
      case 'cancelled': cancelled++; break;
    }
  }
}

j.queuedCount = queued;
j.runningCount = running;
j.succeededCount = succeeded;
j.failedCount = failed;
j.skippedCount = skipped;
j.cancelledCount = cancelled;
j.completedCount = succeeded + failed + skipped + cancelled;
j.progressRatio = j.totalItems > 0 ? Math.round((j.completedCount / j.totalItems) * 10000) / 10000 : 1;
j.status = 'running';
j.endedAt = '';
j.currentFile = '';
j.currentPhase = '';

console.log('\nAfter repair:');
console.log(`  status=${j.status}`);
console.log(`  queued=${j.queuedCount}`);
console.log(`  running=${j.runningCount}`);
console.log(`  succeeded=${j.succeededCount}`);
console.log(`  failed=${j.failedCount}`);
console.log(`  skipped=${j.skippedCount}`);
console.log(`  completed=${j.completedCount}`);
console.log(`  progress=${j.progressRatio}`);

// Write back
fs.writeFileSync(statusPath, JSON.stringify(j, null, 2), 'utf-8');

// Verify parse
const verify = JSON.parse(fs.readFileSync(statusPath, 'utf-8'));
console.log('\nVERIFY OK');
console.log(`  parsed status=${verify.status}`);
console.log(`  parsed completed=${verify.completedCount}`);
console.log(`  parsed running=${verify.runningCount}`);
