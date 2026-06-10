import type { CheerioAPI } from "cheerio";

import type { MetaJson } from "../types.js";
import { firstAttr, firstText, stripUrlFragment } from "../utils/dom.js";
import { sha256Hex } from "../utils/hash.js";
import { parseSimpleDateToIso } from "../utils/regex.js";

export function extractMeta(
  $: CheerioAPI,
  rawHtml: string,
  bodyText: string,
): MetaJson {
  const sourceUrl = firstAttr($, [
    { selector: 'meta[property="og:url"]', attr: "content" },
    { selector: 'link[rel="canonical"]', attr: "href" },
  ]);
  const title =
    firstAttr($, [
      { selector: 'meta[property="og:title"]', attr: "content" },
    ]) || firstText($, ["title", "#activity-name"]);
  const publishTimeText = firstText($, ["#publish_time"]);

  return {
    source_type: "wechat_article",
    source_url: stripUrlFragment(sourceUrl),
    title,
    account_name: firstText($, ["#js_name"]),
    author_display:
      firstAttr($, [{ selector: 'meta[name="author"]', attr: "content" }]) ||
      firstText($, ["#js_author_name"]),
    publish_time_text: publishTimeText,
    publish_time_iso: parseSimpleDateToIso(publishTimeText),
    page_location_text: firstText($, ["#js_ip_wording"]),
    description:
      firstAttr($, [
        { selector: 'meta[name="description"]', attr: "content" },
      ]) ||
      firstAttr($, [
        { selector: 'meta[property="og:description"]', attr: "content" },
      ]),
    og_image: stripUrlFragment(
      firstAttr($, [
        { selector: 'meta[property="og:image"]', attr: "content" },
      ]),
    ),
    content_hash: sha256Hex([title, publishTimeText, bodyText].join("\n")),
    html_length: rawHtml.length,
  };
}
