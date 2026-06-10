import { createReadStream } from "node:fs";
import { createInterface } from "node:readline/promises";

export async function readJsonlFile<T>(filePath: string): Promise<T[]> {
  const records: T[] = [];
  const rl = createInterface({
    input: createReadStream(filePath, { encoding: "utf8" }),
    crlfDelay: Infinity,
  });

  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    records.push(JSON.parse(trimmed) as T);
  }

  return records;
}
