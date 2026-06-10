import { isArchiveWorkspaceRoot } from "./pcuiContract.js";
import { parseDate } from "./pcuiFormat.js";

export function buildCollectAccountsFromSnapshot(snapshot) {
  if (!snapshot?.imported || !snapshot.inputRoot) {
    return [];
  }

  const byAccount = new Map();
  for (const item of snapshot.items || []) {
    const relativePath = item.relativeInputPath || "";
    const parts = relativePath.split(/[\\/]/).filter(Boolean);
    const accountName = parts.length > 1 ? parts[0] : "Live Import";
    const current = byAccount.get(accountName) || {
      fakeid: accountName,
      nickname: accountName,
      status: "ready",
      discoveredCount: 0,
      enqueuedCount: 0,
      duplicateCount: 0,
      estimatedSize: 0,
      failedCount: 0,
      lastDiscoveredAt: "",
    };
    current.discoveredCount += 1;
    current.estimatedSize += 1;
    if (item.status === "queued") {
      current.enqueuedCount += 1;
    }
    if (item.status === "failed") {
      current.failedCount += 1;
      current.status = "failed";
    }
    if (item.status === "running") {
      current.status = "running";
    }
    current.lastDiscoveredAt = item.startedAt || item.endedAt || current.lastDiscoveredAt;
    byAccount.set(accountName, current);
  }

  return [...byAccount.values()]
    .sort((left, right) => {
      if (left.status === "running" && right.status !== "running") {
        return -1;
      }
      if (right.status === "running" && left.status !== "running") {
        return 1;
      }
      return (right.failedCount || 0) - (left.failedCount || 0);
    });
}

export function buildArchiveRowsFromSnapshot(snapshot) {
  if (!snapshot?.imported || !isArchiveWorkspaceRoot(snapshot.outRoot)) {
    return [];
  }

  return [...(snapshot.items || [])]
    .filter((item) => item.status !== "queued")
    .sort((left, right) => {
      if (left.status === "running" && right.status !== "running") {
        return -1;
      }
      if (right.status === "running" && left.status !== "running") {
        return 1;
      }
      return parseDate(right.endedAt || right.startedAt) - parseDate(left.endedAt || left.startedAt);
    })
    .map((item) => {
      const relativePath = item.relativeInputPath || item.inputPath || "";
      const parts = relativePath.split(/[\\/]/).filter(Boolean);
      const token = parts.at(-1) || item.inputPath || item.currentFile || "-";
      const accountKey = parts.length > 1 ? parts.slice(0, -1).join("\\") : "-";
      return {
        token,
        accountKey,
        archiveStatus: item.status || "queued",
        captureComplete: ["succeeded", "skipped", "completed"].includes(item.status),
        assetsComplete: false,
        imageCount: 0,
        mediaCount: 0,
        lastError: item.errorMessage || item.message || "",
        outDir: item.outDir || "",
        livePhase: item.phase || snapshot.currentPhase || "",
        sourceUrl: item.inputPath || "",
      };
    });
}
