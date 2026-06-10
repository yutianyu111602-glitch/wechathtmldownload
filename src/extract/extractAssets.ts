import type { CheerioAPI } from "cheerio";

import type {
  AssetsJson,
  AudioCard,
  ImageAsset,
  LinkAsset,
  VideoCard,
} from "../types.js";
import {
  extractVideoId,
  getAttr,
  isHttpUrl,
  stripUrlFragment,
} from "../utils/dom.js";
import { cleanInlineText } from "../utils/text.js";

const IMAGE_SELECTOR =
  "#js_content img, #page_bottom_area img, #js_extra_content img";
const LINK_SELECTOR = "#js_content a, #page_bottom_area a, #js_extra_content a";
const VIDEO_SELECTOR = [
  "#js_content [vid]",
  "#js_content .wx_video_iframe",
  '#js_content iframe[data-src*="vid="]',
  '#js_content iframe[src*="vid="]',
  "#page_bottom_area [vid]",
  "#page_bottom_area .wx_video_iframe",
  '#page_bottom_area iframe[data-src*="vid="]',
  '#page_bottom_area iframe[src*="vid="]',
].join(", ");

function classifyLink(text: string, href: string, sourceUrl: string): string {
  if (!href) {
    return "unknown";
  }

  if (text.includes("阅读全文")) {
    return "read_original";
  }

  if (isHttpUrl(href)) {
    return href === sourceUrl ? "internal" : "external";
  }

  if (
    href.startsWith("/") ||
    href.startsWith("javascript:") ||
    href.startsWith("#")
  ) {
    return "internal";
  }

  return "unknown";
}

export function extractAssets($: CheerioAPI, sourceUrl: string): AssetsJson {
  const images: ImageAsset[] = [];
  const audioCards: AudioCard[] = [];
  const videoCards: VideoCard[] = [];
  const links: LinkAsset[] = [];

  const imageSeen = new Set<string>();
  const audioSeen = new Set<string>();
  const videoSeen = new Set<string>();
  const linkSeen = new Set<string>();

  $(IMAGE_SELECTOR).each((_, element) => {
    const $element = $(element);
    const dataSrc = stripUrlFragment(getAttr($element, ["data-src"]));
    const src = stripUrlFragment(getAttr($element, ["src"]));
    const key = dataSrc || src;
    if (!key || imageSeen.has(key)) {
      return;
    }

    imageSeen.add(key);
    images.push({
      src,
      data_src: dataSrc,
      alt: cleanInlineText(String($element.attr("alt") ?? "")),
      title: cleanInlineText(
        String($element.attr("title") ?? $element.attr("data-title") ?? ""),
      ),
      width_hint: cleanInlineText(
        String($element.attr("data-w") ?? $element.attr("width") ?? ""),
      ),
      ratio_hint: cleanInlineText(String($element.attr("data-ratio") ?? "")),
      index: images.length,
    });
  });

  $("mp-common-mpaudio").each((_, element) => {
    const $element = $(element);
    const voiceEncodeFileId = getAttr($element, ["voice_encode_fileid"]);
    const title = getAttr($element, ["name", "data-name", "title"]);
    const key = voiceEncodeFileId || title;
    if (!key || audioSeen.has(key)) {
      return;
    }

    audioSeen.add(key);
    audioCards.push({
      title,
      author: getAttr($element, ["author", "data-author"]),
      duration_text: getAttr($element, [
        "play_length",
        "duration",
        "data-duration",
      ]),
      cover: stripUrlFragment(getAttr($element, ["cover", "data-cover"])),
      voice_encode_fileid: voiceEncodeFileId,
    });
  });

  $(VIDEO_SELECTOR).each((_, element) => {
    const $element = $(element);
    const rawVid = getAttr($element, ["vid"]);
    const rawSrc = getAttr($element, ["data-src", "src"]);
    const vid = rawVid || extractVideoId(rawSrc);
    const key = vid || rawSrc;
    if (!key || videoSeen.has(key)) {
      return;
    }

    videoSeen.add(key);
    videoCards.push({
      vid,
      title: getAttr($element, ["title", "data-title"]),
      cover: stripUrlFragment(
        getAttr($element, ["data-cover", "poster", "cover"]),
      ),
    });
  });

  $(LINK_SELECTOR).each((_, element) => {
    const $element = $(element);
    const text = cleanInlineText($element.text());
    const href = stripUrlFragment(getAttr($element, ["href"]));
    const key = `${text}|${href}`;
    if (!href || linkSeen.has(key)) {
      return;
    }

    linkSeen.add(key);
    links.push({
      text,
      href,
      type: classifyLink(text, href, sourceUrl),
    });
  });

  return {
    images,
    audio_cards: audioCards,
    video_cards: videoCards,
    links,
  };
}
