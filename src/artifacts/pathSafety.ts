import { isAbsolute, relative, resolve } from "node:path";

export function isSafePathSegment(value: string): boolean {
  return (
    value.length > 0 &&
    value !== "." &&
    value !== ".." &&
    !value.includes("/") &&
    !value.includes("\\") &&
    !value.includes(":")
  );
}

export function assertSafeRelativePath(rootDir: string, targetPath: string): void {
  const relativePath = relative(resolve(rootDir), resolve(targetPath));
  if (
    relativePath === "" ||
    (!relativePath.startsWith("..") && !isAbsolute(relativePath))
  ) {
    return;
  }
  throw new Error(`Refusing to write outside target root: ${targetPath}`);
}

export function toPortablePath(value: string): string {
  return value.replace(/\\/g, "/");
}

export function hasSensitivePathSegment(relativePath: string): boolean {
  return relativePath
    .split(/[\\/]+/g)
    .some((segment) =>
      [
        ".mptext-data",
        "cookie",
        "cookies",
        "auth",
        "token",
        "tokens",
        "secret",
        "secrets",
        "node_modules",
      ].includes(segment.toLowerCase()),
    );
}
