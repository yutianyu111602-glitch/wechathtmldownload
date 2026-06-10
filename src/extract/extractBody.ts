import type { Cheerio, CheerioAPI } from "cheerio";

import type { BodyBlock } from "../types.js";
import { extractVideoId, getAttr, stripUrlFragment } from "../utils/dom.js";
import { normalizeTextBlock } from "../utils/text.js";

interface BodyExtractResult {
  body_text: string;
  body_blocks: BodyBlock[];
  warnings: string[];
}

const BODY_ROOT_SELECTORS = [
  "#js_content",
  ".rich_media_content",
  ".rich_media_wrp",
];
const TEXT_TAGS = new Set([
  "p",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "blockquote",
  "li",
]);
const CONTAINER_TAGS = new Set([
  "section",
  "div",
  "article",
  "figure",
  "figcaption",
  "ul",
  "ol",
]);
const TRACKED_DESCENDANT_SELECTOR = [
  "p",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "blockquote",
  "li",
  "img",
  "mp-common-mpaudio",
  ".wx_video_iframe",
  'iframe[data-src*="vid="]',
  'iframe[src*="vid="]',
  "[vid]",
].join(", ");

function getTagName($node: Cheerio<any>): string {
  const node = $node.get(0) as { tagName?: string } | undefined;
  return node?.tagName?.toLowerCase() ?? "";
}

function isImageNode($node: Cheerio<any>): boolean {
  return getTagName($node) === "img";
}

function isAudioNode($node: Cheerio<any>): boolean {
  return getTagName($node) === "mp-common-mpaudio";
}

function isVideoNode($node: Cheerio<any>): boolean {
  const tagName = getTagName($node);
  const className = String($node.attr("class") ?? "");
  const src = getAttr($node, ["data-src", "src"]);

  return (
    tagName === "iframe" ||
    className.includes("wx_video_iframe") ||
    Boolean(getAttr($node, ["vid"])) ||
    Boolean(extractVideoId(src))
  );
}

function extractParagraphText($node: Cheerio<any>): string {
  const $clone = $node.clone();
  $clone
    .find("img, mp-common-mpaudio, .wx_video_iframe, iframe, [vid]")
    .remove();
  return normalizeTextBlock($clone.text());
}

function blockToText(block: BodyBlock): string {
  if (block.type === "paragraph") {
    return block.text ?? "";
  }

  if (block.type === "image") {
    return block.src ? `[图片] ${block.src}` : "[图片]";
  }

  if (block.type === "audio") {
    return block.title ? `[音频] ${block.title}` : "[音频]";
  }

  return block.vid
    ? `[视频] ${block.vid}`
    : `[视频] ${block.title ?? ""}`.trim();
}

function pushBlock(blocks: BodyBlock[], block: BodyBlock): void {
  const textSignature = JSON.stringify(block);
  const prev = blocks.at(-1);
  if (prev && JSON.stringify(prev) === textSignature) {
    return;
  }

  blocks.push(block);
}

function collectBlocks(
  $: CheerioAPI,
  nodes: unknown[],
  blocks: BodyBlock[],
): void {
  for (const rawNode of nodes) {
    const node = rawNode as {
      type?: string;
      name?: string;
      data?: string;
      children?: unknown[];
    };

    if (node.type === "text") {
      const text = normalizeTextBlock(node.data ?? "");
      if (text) {
        pushBlock(blocks, { type: "paragraph", text });
      }
      continue;
    }

    if (node.type !== "tag") {
      continue;
    }

    const $node = $(rawNode as never);
    const tagName = node.name?.toLowerCase() ?? "";

    if (isImageNode($node)) {
      const src = stripUrlFragment(getAttr($node, ["data-src", "src"]));
      if (src) {
        pushBlock(blocks, { type: "image", src });
      }
      continue;
    }

    if (isAudioNode($node)) {
      pushBlock(blocks, {
        type: "audio",
        title: getAttr($node, ["name", "data-name", "title"]),
      });
      continue;
    }

    if (isVideoNode($node)) {
      pushBlock(blocks, {
        type: "video",
        vid:
          getAttr($node, ["vid"]) ||
          extractVideoId(getAttr($node, ["data-src", "src"])),
        title: getAttr($node, ["title", "data-title"]),
      });
      continue;
    }

    if (TEXT_TAGS.has(tagName)) {
      const text = extractParagraphText($node);
      if (text) {
        pushBlock(blocks, { type: "paragraph", text });
      }
      continue;
    }

    if (
      CONTAINER_TAGS.has(tagName) &&
      $node.find(TRACKED_DESCENDANT_SELECTOR).length === 0
    ) {
      const text = normalizeTextBlock($node.text());
      if (text) {
        pushBlock(blocks, { type: "paragraph", text });
      }
      continue;
    }

    collectBlocks($, $node.contents().toArray(), blocks);
  }
}

export function extractBody($: CheerioAPI): BodyExtractResult {
  const root = BODY_ROOT_SELECTORS.map((selector) => $(selector).first()).find(
    ($candidate) => $candidate.length > 0,
  );
  if (!root) {
    return {
      body_text: "",
      body_blocks: [],
      warnings: ["Body root not found"],
    };
  }

  const $root = root.clone();
  $root
    .find(
      "script, style, svg, .wx_bottom_modal_wrp, .weui-half-screen-dialog_wrp, .rich_media_tool_area, .appmsg_comment_con, #js_tags_preview_toast, #js_temp_bottom_area",
    )
    .remove();
  $root.find("iframe").each((_, element) => {
    const $element = $(element);
    if (!isVideoNode($element)) {
      $element.remove();
    }
  });

  const bodyBlocks: BodyBlock[] = [];
  collectBlocks($, $root.contents().toArray(), bodyBlocks);

  return {
    body_text: bodyBlocks.map(blockToText).filter(Boolean).join("\n\n").trim(),
    body_blocks: bodyBlocks,
    warnings: bodyBlocks.length === 0 ? ["No body blocks extracted"] : [],
  };
}
