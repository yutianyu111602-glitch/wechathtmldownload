import { readdir } from "node:fs/promises";
import { join } from "node:path";

export async function collectFiles(
  rootDir: string,
  predicate: (filePath: string, fileName: string) => boolean,
): Promise<string[]> {
  const collected: string[] = [];
  const pendingDirs = [rootDir];

  while (pendingDirs.length > 0) {
    const dir = pendingDirs.pop();
    if (!dir) {
      continue;
    }

    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const entry of entries) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        pendingDirs.push(fullPath);
        continue;
      }

      if (entry.isFile() && predicate(fullPath, entry.name)) {
        collected.push(fullPath);
      }
    }
  }

  collected.sort((left, right) => left.localeCompare(right));
  return collected;
}
