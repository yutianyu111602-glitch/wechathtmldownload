import { hostname } from "node:os";
import { readFile, rm, writeFile } from "node:fs/promises";

const DEFAULT_SHARD_CLAIM_TTL_MS = 30 * 60 * 1000; // 30 minutes

export interface ShardClaim {
  claimedAt: string;
  pid: number;
  hostname: string;
}

function claimPathForShard(shardPath: string): string {
  return `${shardPath}.claimed`;
}

export async function readShardClaim(
  shardPath: string,
): Promise<ShardClaim | null> {
  try {
    const text = await readFile(claimPathForShard(shardPath), "utf-8");
    return JSON.parse(text) as ShardClaim;
  } catch {
    return null;
  }
}

export async function isShardClaimed(
  shardPath: string,
  ttlMs = DEFAULT_SHARD_CLAIM_TTL_MS,
): Promise<{ claimed: boolean; expired: boolean; claim?: ShardClaim }> {
  const claim = await readShardClaim(shardPath);
  if (!claim) {
    return { claimed: false, expired: false };
  }

  const claimedAt = new Date(claim.claimedAt).getTime();
  const now = Date.now();
  const expired = now - claimedAt > ttlMs;

  return { claimed: true, expired, claim };
}

export async function claimShard(
  shardPath: string,
): Promise<{ claimed: boolean; claimPath: string }> {
  const claimPath = claimPathForShard(shardPath);
  const claim: ShardClaim = {
    claimedAt: new Date().toISOString(),
    pid: process.pid,
    hostname: hostname(),
  };

  try {
    await writeFile(claimPath, JSON.stringify(claim), { flag: "wx" });
    return { claimed: true, claimPath };
  } catch {
    return { claimed: false, claimPath };
  }
}

export async function releaseShard(shardPath: string): Promise<void> {
  try {
    await rm(claimPathForShard(shardPath));
  } catch {
    // Ignore errors if claim file doesn't exist
  }
}

export interface RunShardIfNotClaimedOptions {
  ttlMs?: number;
  force?: boolean;
}

export async function runShardIfNotClaimed<T>(
  shardPath: string,
  run: () => Promise<T>,
  options: RunShardIfNotClaimedOptions = {},
): Promise<{ result?: T; skipped: boolean; reason?: string }> {
  const { ttlMs = DEFAULT_SHARD_CLAIM_TTL_MS, force = false } = options;

  const status = await isShardClaimed(shardPath, ttlMs);

  if (status.claimed && !status.expired && !force) {
    return {
      skipped: true,
      reason: `Shard already claimed by pid=${status.claim?.pid} on ${status.claim?.hostname} at ${status.claim?.claimedAt}`,
    };
  }

  if (status.claimed && status.expired && !force) {
    // Expired claim: remove it and try to claim it ourselves
    await releaseShard(shardPath);
    const claimResult = await claimShard(shardPath);
    if (!claimResult.claimed) {
      return {
        skipped: true,
        reason: "Shard was claimed by another process during contention",
      };
    }
  } else if (!status.claimed || force) {
    // Not claimed or force override
    const claimResult = await claimShard(shardPath);
    if (!claimResult.claimed && !force) {
      return {
        skipped: true,
        reason: "Shard was claimed by another process during contention",
      };
    }
  }

  try {
    const result = await run();
    return { result, skipped: false };
  } finally {
    await releaseShard(shardPath);
  }
}
