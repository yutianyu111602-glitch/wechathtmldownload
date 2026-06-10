export function detectCollectAnomalies(account) {
  const codes = [];
  if (!account.discoveredCount && account.status !== "listing") {
    codes.push("PREFETCH_MISSING");
  }
  if (account.enqueuedCount !== account.discoveredCount && account.discoveredCount > 0) {
    codes.push("QUEUE_MISMATCH");
  }
  if (account.status === "unknown" || !account.status) {
    codes.push("STATUS_SOURCE_FALLBACK");
  }
  return codes;
}

export function detectArchiveAnomalies(item) {
  const codes = [];
  if (item.livePhase && item.archiveStatus === "running") {
    return codes;
  }
  if (!item.captureComplete) {
    codes.push("CAPTURE_PARTIAL");
  }
  if (item.archiveStatus === "succeeded" && !item.captureComplete) {
    codes.push("CAPTURE_JSON_SCAN_CONFLICT");
  }
  if (!item.assetsComplete && item.captureComplete) {
    codes.push("ASSETS_LOCAL_MISSING");
  }
  if (item.assetsComplete && !item.imageCount && item.captureComplete) {
    codes.push("ASSET_STATUS_MISMATCH");
  }
  return codes;
}

export function getHighestAnomalySeverity(codes) {
  const severe = ["CAPTURE_PARTIAL", "CAPTURE_JSON_SCAN_CONFLICT", "ASSETS_LOCAL_MISSING", "ASSET_STATUS_MISMATCH"];
  const warning = ["PREFETCH_MISSING", "QUEUE_MISMATCH"];
  const info = ["STATUS_SOURCE_FALLBACK"];

  if (codes.some((code) => severe.includes(code))) return "error";
  if (codes.some((code) => warning.includes(code))) return "warning";
  if (codes.some((code) => info.includes(code))) return "idle";
  return null;
}

export function formatAnomalyShort(codes) {
  if (!codes.length) return "-";
  const first = codes[0];
  if (codes.length > 1) {
    return `${first} +${codes.length - 1}`;
  }
  return first;
}
