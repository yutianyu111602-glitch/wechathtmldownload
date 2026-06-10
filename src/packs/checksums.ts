import { basename, relative, resolve } from "node:path";

import { toPortablePath } from "../artifacts/pathSafety.js";
import { collectFiles } from "../utils/fileDiscovery.js";
import { ensureDir, writeText } from "../utils/fs.js";
import { sha256File } from "../utils/hash.js";

export interface ChecksumsSummary {
  checksums_path: string;
  file_count: number;
}

export async function writeChecksumsFile(
  rootDir: string,
  checksumsFileName = "checksums.sha256",
): Promise<ChecksumsSummary> {
  const resolvedRoot = resolve(rootDir);
  const checksumsPath = resolve(resolvedRoot, checksumsFileName);
  const files = (await collectFiles(resolvedRoot, (filePath) => {
    return basename(filePath) !== checksumsFileName;
  })).sort((left, right) => left.localeCompare(right));

  const lines: string[] = [];
  for (const filePath of files) {
    const hash = await sha256File(filePath);
    lines.push(`${hash}  ${toPortablePath(relative(resolvedRoot, filePath))}`);
  }

  await ensureDir(resolvedRoot);
  await writeText(checksumsPath, `${lines.join("\n")}${lines.length > 0 ? "\n" : ""}`);
  return {
    checksums_path: checksumsPath,
    file_count: lines.length,
  };
}
