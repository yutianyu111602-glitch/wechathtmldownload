import type { AssetsJson, FooterInfo, MetaJson } from "../types.js";
import type { SidecarJson } from "../archive/types.js";
import { cleanLlmContentMarkdown } from "./cleanLlmContent.js";

function buildImageLabel(index: number, title: string, alt: string): string {
  const label = title || alt;
  return label ? `[${index + 1}] ${label}` : `[${index + 1}] 图片`;
}

function buildImageDetail(widthHint: string, ratioHint: string): string {
  const parts = [
    widthHint ? `width=${widthHint}` : "",
    ratioHint ? `ratio=${ratioHint}` : "",
  ].filter(Boolean);
  return parts.length > 0 ? ` (${parts.join(", ")})` : "";
}

function firstNonEmpty(...values: Array<string | undefined | null>): string {
  for (const value of values) {
    const normalized = String(value ?? "").trim();
    if (normalized) {
      return normalized;
    }
  }
  return "";
}

function buildPosterOcrText(sidecar: SidecarJson): string {
  const plainText = firstNonEmpty(sidecar.poster_ocr.plain_text);
  if (plainText) {
    return plainText.replace(/\r\n/g, "\n").trim();
  }

  const blockText = (sidecar.poster_ocr.blocks ?? [])
    .map((block) => block.text.trim())
    .filter(Boolean)
    .join("\n")
    .trim();
  return blockText;
}

export function buildLlmInputMd(
  meta: MetaJson,
  footerInfo: FooterInfo,
  bodyMarkdown: string,
  assets: AssetsJson,
): string {
  const lines: string[] = [];

  lines.push(`# ${meta.title || "Untitled"}`);
  lines.push("");

  if (meta.account_name) {
    lines.push(`- 来源公众号: ${meta.account_name}`);
  }
  if (meta.author_display) {
    lines.push(`- 作者: ${meta.author_display}`);
  }
  if (meta.publish_time_text) {
    lines.push(`- 发布时间: ${meta.publish_time_text}`);
  }
  if (meta.source_url) {
    lines.push(`- 原文链接: ${meta.source_url}`);
  }

  if (
    footerInfo.venue_name_candidate ||
    footerInfo.venue_address_lines.length > 0 ||
    footerInfo.date_texts.length > 0 ||
    footerInfo.lineup_lines.length > 0
  ) {
    lines.push("");
    lines.push("## 结构化提示");

    if (footerInfo.venue_name_candidate) {
      lines.push(`- 场地候选: ${footerInfo.venue_name_candidate}`);
    }
    if (footerInfo.venue_address_lines.length > 0) {
      lines.push("- 地址行:");
      for (const line of footerInfo.venue_address_lines) {
        lines.push(`  - ${line}`);
      }
    }
    if (footerInfo.date_texts.length > 0) {
      lines.push("- 日期文本:");
      for (const line of footerInfo.date_texts) {
        lines.push(`  - ${line}`);
      }
    }
    if (footerInfo.lineup_lines.length > 0) {
      lines.push("- 名单行:");
      for (const line of footerInfo.lineup_lines) {
        lines.push(`  - ${line}`);
      }
    }
  }

  lines.push("");
  lines.push("## 正文");
  lines.push(cleanLlmContentMarkdown(bodyMarkdown));

  if (
    assets.images.length > 0 ||
    assets.audio_cards.length > 0 ||
    assets.video_cards.length > 0 ||
    assets.links.length > 0 ||
    meta.og_image
  ) {
    lines.push("");
    lines.push("## 媒体线索");

    if (meta.og_image) {
      lines.push(`- 封面图: ${meta.og_image}`);
    }

    if (assets.images.length > 0) {
      lines.push(`- 图片数量: ${assets.images.length}`);
      lines.push("- 图片条目:");
      for (const image of assets.images) {
        const imageUrl = image.data_src || image.src;
        lines.push(
          `  - ${buildImageLabel(image.index, image.title, image.alt)}${buildImageDetail(image.width_hint, image.ratio_hint)} ${imageUrl}`,
        );
      }
    }
    if (assets.audio_cards.length > 0) {
      lines.push(`- 音频卡数量: ${assets.audio_cards.length}`);
      lines.push("- 音频条目:");
      for (const audio of assets.audio_cards) {
        const parts = [
          audio.title,
          audio.author,
          audio.duration_text,
          audio.cover,
        ].filter(Boolean);
        lines.push(`  - ${parts.join(" | ")}`);
      }
    }
    if (assets.video_cards.length > 0) {
      lines.push(`- 视频卡数量: ${assets.video_cards.length}`);
      lines.push("- 视频条目:");
      for (const video of assets.video_cards) {
        const parts = [video.title || video.vid, video.cover].filter(Boolean);
        lines.push(`  - ${parts.join(" | ")}`);
      }
    }
    const externalLinks = assets.links.filter(
      (link) => link.type === "external",
    );
    if (externalLinks.length > 0) {
      lines.push(`- 外链数量: ${externalLinks.length}`);
      lines.push("- 外链条目:");
      for (const link of externalLinks.slice(0, 20)) {
        lines.push(`  - ${link.text || "链接"} | ${link.href}`);
      }
    }
  }

  lines.push("");
  return `${lines.join("\n").trim()}\n`;
}

export function buildLlmInputMdFromSidecar(sidecar: SidecarJson): string {
  const lines: string[] = [];
  const title = firstNonEmpty(sidecar.meta.title, sidecar.archive?.title);
  const accountName = firstNonEmpty(sidecar.meta.account_name, sidecar.archive?.account_key);
  const sourceUrl = firstNonEmpty(
    sidecar.meta.source_url,
    sidecar.archive?.source_url,
    sidecar.archive?.final_url,
  );

  lines.push(`# ${title || "Untitled"}`);
  lines.push("");
  if (accountName) {
    lines.push(`- 来源公众号: ${accountName}`);
  }
  if (sidecar.meta.author_display) {
    lines.push(`- 作者: ${sidecar.meta.author_display}`);
  }
  if (sidecar.meta.publish_time_text) {
    lines.push(`- 发布时间: ${sidecar.meta.publish_time_text}`);
  }
  if (sourceUrl) {
    lines.push(`- 原文链接: ${sourceUrl}`);
  }
  if (sidecar.archive?.archived_at) {
    lines.push(`- 归档时间: ${sidecar.archive.archived_at}`);
  }

  if (
    sidecar.footer_info.venue_name_candidate ||
    sidecar.footer_info.venue_address_lines.length > 0 ||
    sidecar.footer_info.date_texts.length > 0 ||
    sidecar.footer_info.lineup_lines.length > 0
  ) {
    lines.push("");
    lines.push("## 结构化提示");
    if (sidecar.footer_info.venue_name_candidate) {
      lines.push(`- 场地候选: ${sidecar.footer_info.venue_name_candidate}`);
    }
    if (sidecar.footer_info.venue_address_lines.length > 0) {
      lines.push("- 地址行:");
      for (const line of sidecar.footer_info.venue_address_lines) {
        lines.push(`  - ${line}`);
      }
    }
    if (sidecar.footer_info.date_texts.length > 0) {
      lines.push("- 日期文本:");
      for (const line of sidecar.footer_info.date_texts) {
        lines.push(`  - ${line}`);
      }
    }
    if (sidecar.footer_info.lineup_lines.length > 0) {
      lines.push("- 名单行:");
      for (const line of sidecar.footer_info.lineup_lines) {
        lines.push(`  - ${line}`);
      }
    }
  }

  lines.push("");
  lines.push("## Main Content");
  lines.push(cleanLlmContentMarkdown(sidecar.main_content));

  const backgroundRecall = cleanLlmContentMarkdown(sidecar.background_recall);
  if (backgroundRecall) {
    lines.push("");
    lines.push("## Background Recall");
    lines.push(backgroundRecall);
  }

  if (sidecar.links.length > 0) {
    lines.push("");
    lines.push("## Links");
    for (const link of sidecar.links.slice(0, 30)) {
      lines.push(`- ${link.text || "链接"} | ${link.href}`);
    }
  }

  if (sidecar.images.length > 0) {
    lines.push("");
    lines.push("## Images");
    for (const image of sidecar.images) {
      const detail = [image.remote_url, image.local_path].filter(Boolean).join(" | ");
      lines.push(`- ${image.label} | ${detail}`);
    }
  }

  const posterOcrText = buildPosterOcrText(sidecar);
  const hasPosterOcrRecovered =
    Boolean(sidecar.poster_ocr.recovered.venue_name_candidate) ||
    (sidecar.poster_ocr.recovered.lineup_lines ?? []).length > 0 ||
    (sidecar.poster_ocr.recovered.date_texts ?? []).length > 0;

  if (sidecar.poster_ocr.imageHeavy || posterOcrText || hasPosterOcrRecovered) {
    lines.push("");
    lines.push("## Poster OCR");
    if (posterOcrText) {
      lines.push(posterOcrText);
    }
    if (sidecar.poster_ocr.candidates.length > 0) {
      for (const candidate of sidecar.poster_ocr.candidates) {
        lines.push(`- 候选图片: ${candidate.local_path} (score=${candidate.score})`);
      }
    }
    if (sidecar.poster_ocr.recovered.venue_name_candidate) {
      lines.push(`- OCR 场地候选: ${sidecar.poster_ocr.recovered.venue_name_candidate}`);
    }
    for (const line of sidecar.poster_ocr.recovered.lineup_lines ?? []) {
      lines.push(`- OCR 名单: ${line}`);
    }
    for (const line of sidecar.poster_ocr.recovered.date_texts ?? []) {
      lines.push(`- OCR 日期: ${line}`);
    }
  }

  lines.push("");
  return `${lines.join("\n").trim()}\n`;
}
