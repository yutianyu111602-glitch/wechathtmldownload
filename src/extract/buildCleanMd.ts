import type { AssetsJson, FooterInfo, MetaJson } from "../types.js";

export function buildCleanMd(
  meta: MetaJson,
  footerInfo: FooterInfo,
  bodyText: string,
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
  if (meta.page_location_text) {
    lines.push(`- 页面地点标识: ${meta.page_location_text}`);
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
    lines.push("## 页面底部信息");
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
  lines.push(bodyText || "");

  const hasMedia =
    assets.audio_cards.length > 0 ||
    assets.video_cards.length > 0 ||
    assets.images.length > 0;
  if (hasMedia) {
    lines.push("");
    lines.push("## 媒体资源");
    if (assets.audio_cards.length > 0) {
      lines.push("");
      lines.push("### 音频卡");
      for (const audio of assets.audio_cards) {
        lines.push(
          `- ${audio.title || ""} / ${audio.author || ""} / ${audio.duration_text || ""}`.trim(),
        );
      }
    }
    if (assets.video_cards.length > 0) {
      lines.push("");
      lines.push("### 视频卡");
      for (const video of assets.video_cards) {
        lines.push(`- ${video.vid || video.title}`);
      }
    }
    if (assets.images.length > 0) {
      lines.push("");
      lines.push("### 图片");
      for (const image of assets.images) {
        lines.push(`- ${image.data_src || image.src}`);
      }
    }
  }

  lines.push("");
  return `${lines.join("\n").trim()}\n`;
}
