import { sha256Hex } from "../utils/hash.js";

function cleanTokenPart(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
}

export function normalizeArticleToken(sourceUrl: string): string {
  try {
    const url = new URL(sourceUrl);
    const biz = cleanTokenPart(
      url.searchParams.get("__biz") || url.searchParams.get("biz") || "",
    );
    const mid = cleanTokenPart(url.searchParams.get("mid") || "");
    const appmsgid = cleanTokenPart(url.searchParams.get("appmsgid") || "");
    const idx = cleanTokenPart(url.searchParams.get("idx") || "");
    const itemidx = cleanTokenPart(url.searchParams.get("itemidx") || "");
    const sn = cleanTokenPart(url.searchParams.get("sn") || "");
    const sign = cleanTokenPart(url.searchParams.get("sign") || "");
    const directToken = cleanTokenPart(
      url.searchParams.get("token") || url.searchParams.get("article_token") || "",
    );

    const candidate = [directToken || biz, mid || appmsgid, idx || itemidx, sn || sign]
      .filter(Boolean)
      .join("_");
    if (candidate) {
      return candidate.slice(0, 160);
    }

    const pathToken = cleanTokenPart(url.pathname.split("/").filter(Boolean).at(-1) || "");
    if (pathToken) {
      return pathToken.slice(0, 160);
    }
  } catch {
    // Fall through to hash-based token.
  }

  return sha256Hex(sourceUrl).slice(0, 24);
}
