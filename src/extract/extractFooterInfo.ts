import type { BodyBlock, FooterInfo } from "../types.js";
import { collectDateTexts } from "../utils/regex.js";
import {
  cleanInlineText,
  splitCleanLines,
  uniqueStrings,
} from "../utils/text.js";

const ADDRESS_KEYWORDS = [
  "市",
  "区",
  "路",
  "号",
  "大厦",
  "层",
  "Street",
  "Road",
  "Rd",
  "Avenue",
  "Ave",
  "Lu",
  "No.",
  "Beijing",
  "Shanghai",
];
const EXCLUDED_LINE_PARTS = [
  "地址",
  "原文",
  "感谢",
  "阅读全文",
  "阅读原文",
  "扫码",
  "点击",
  "赞赏",
  "声明",
  "来源",
  "社交媒体",
  "SOCIAL MEDIA",
  "WeChat:",
  "Redbook:",
  "IG:",
  "OPENING HOURS",
  "营业时间",
  "Closed on",
  "开门迎客",
  "Min.SPEND",
];
const SENTENCE_MARKERS = ["。", "！", "？", "；"];

function isAddressLine(value: string): boolean {
  return (
    value.length <= 90 &&
    !looksLikeSentence(value) &&
    !isExcludedLine(value) &&
    ADDRESS_KEYWORDS.some((keyword) => value.includes(keyword))
  );
}

function isShortLine(value: string): boolean {
  return value.length >= 1 && value.length <= 40;
}

function looksLikeSentence(value: string): boolean {
  return (
    SENTENCE_MARKERS.some((marker) => value.includes(marker)) &&
    value.length > 24
  );
}

function isExcludedLine(value: string): boolean {
  return EXCLUDED_LINE_PARTS.some((part) => value.includes(part));
}

function isLineupCandidate(value: string): boolean {
  return (
    isShortLine(value) &&
    !looksLikeSentence(value) &&
    !isAddressLine(value) &&
    collectDateTexts(value).length === 0 &&
    !isExcludedLine(value)
  );
}

function isVenueCandidate(value: string): boolean {
  return (
    isShortLine(value) &&
    !isAddressLine(value) &&
    collectDateTexts(value).length === 0 &&
    !isExcludedLine(value) &&
    !/[。！？；，,]/.test(value)
  );
}

export function extractFooterInfo(bodyBlocks: BodyBlock[]): FooterInfo {
  const paragraphTexts = bodyBlocks
    .filter((block) => block.type === "paragraph" && block.text)
    .map((block) => cleanInlineText(block.text ?? ""))
    .filter(Boolean);

  const tailSize = Math.max(5, Math.ceil(paragraphTexts.length * 0.2));
  const footerParagraphs = paragraphTexts.slice(-tailSize);
  const footerLines = footerParagraphs.flatMap((text) => splitCleanLines(text));

  const dateTexts = uniqueStrings(
    footerLines.flatMap((line) => collectDateTexts(line)),
  );
  const venueAddressLines = uniqueStrings(
    footerLines.filter((line) => isAddressLine(line)),
  );

  const lineupGroups: string[][] = [];
  let currentGroup: string[] = [];
  for (const line of footerLines) {
    if (isLineupCandidate(line)) {
      currentGroup.push(line);
      continue;
    }

    if (currentGroup.length >= 2) {
      lineupGroups.push([...currentGroup]);
    }
    currentGroup = [];
  }
  if (currentGroup.length >= 2) {
    lineupGroups.push([...currentGroup]);
  }
  const lineupLines = lineupGroups.at(-1) ?? [];

  let venueNameCandidate = "";
  for (let index = 0; index < footerLines.length; index += 1) {
    const line = footerLines[index] ?? "";
    if (!isVenueCandidate(line)) {
      continue;
    }

    const previousLine = footerLines[index - 1] ?? "";
    const nextLine = footerLines[index + 1] ?? "";
    if (
      isAddressLine(previousLine) ||
      collectDateTexts(previousLine).length > 0 ||
      isAddressLine(nextLine) ||
      collectDateTexts(nextLine).length > 0
    ) {
      venueNameCandidate = line;
      break;
    }
  }

  return {
    venue_name_candidate: venueNameCandidate,
    venue_address_lines: venueAddressLines,
    date_texts: dateTexts,
    lineup_lines: uniqueStrings(lineupLines),
    raw_footer_text: footerLines.join("\n").trim(),
  };
}
