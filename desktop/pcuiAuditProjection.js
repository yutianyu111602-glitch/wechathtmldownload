import { access } from "node:fs/promises";
import { join } from "node:path";

async function pathExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

export async function resolveAuditProjectionPath(archiveRoot) {
  const canonicalPath = join(archiveRoot, "ui-projection.json");
  if (await pathExists(canonicalPath)) {
    return canonicalPath;
  }

  const reportsPath = join(archiveRoot, "_audit_reports", "ui-projection.json");
  if (await pathExists(reportsPath)) {
    return reportsPath;
  }

  return canonicalPath;
}
