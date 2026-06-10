import { normalizeTextBlock } from "../utils/text.js";

const EXACT_SHELL_LINES = new Set([
  "已关注",
  "关注",
  "取消",
  "关闭",
  "更多",
  "重播",
  "播放",
  "暂停",
  "分享",
  "倍速",
  "原速",
  "全屏",
  "退出全屏",
  "观看更多",
  "视频详情",
  "继续滑动看下一个",
  "轻触阅读原文",
  "分享视频",
  "分享点赞在看",
]);

const SHELL_LINE_PATTERNS = [
  /^当前浏览器不支持播放音乐或语音/i,
  /^视频加载中/i,
  /^音频加载中/i,
  /^进度条/i,
  /^向前\s*\d+/,
  /^向后\s*\d+/,
  /^继续滑动看下一个/i,
  /^倍速播放中/i,
  /^\d+(?:\.\d+)?倍(?:\s+\d+(?:\.\d+)?倍)+$/i,
];

function normalizeShellLine(line: string): string {
  return line
    .replace(/[*_`~]+/g, "")
    .replace(/^[-*>\s#]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function isLlmShellLine(line: string): boolean {
  const normalized = normalizeShellLine(line);
  if (!normalized) {
    return false;
  }
  if (EXACT_SHELL_LINES.has(normalized)) {
    return true;
  }
  if (normalized.includes("已关注") && normalized.length <= 32) {
    return true;
  }
  if (/重播.*分享.*赞/.test(normalized)) {
    return true;
  }
  if (/切换到竖屏全屏.*退出全屏/.test(normalized)) {
    return true;
  }
  return SHELL_LINE_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function cleanLlmContentMarkdown(value: string): string {
  const lines = value
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .filter((line) => !isLlmShellLine(line));
  return normalizeTextBlock(lines.join("\n"));
}
