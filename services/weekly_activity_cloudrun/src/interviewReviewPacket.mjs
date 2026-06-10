import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const REQUIRED_NEXT = ["human_review", "artist_confirmed", "source_quote_ref", "consent_scope"];

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function countWhere(items, predicate) {
  return items.reduce((total, item) => total + (predicate(item) ? 1 : 0), 0);
}

function tally(values) {
  const counts = {};
  for (const value of values.filter(Boolean)) {
    counts[value] = (counts[value] || 0) + 1;
  }
  return counts;
}

function reviewActionsFor(item) {
  const blockers = new Set(asArray(item.promotionGate?.blockers));
  const actions = ["human_review", "artist_confirmed"];
  if (blockers.has("source_evidence_missing")) actions.push("collect_source_quote_ref");
  if (blockers.has("public_facts_consent_missing")) actions.push("confirm_public_facts_consent_or_keep_private");
  if (blockers.has("graph_consent_missing")) actions.push("confirm_graph_consent_or_keep_private");
  if (!blockers.size && item.linkSummary?.musicLinkCount) actions.push("verify_original_platform_music_links");
  actions.push("record_consent_scope");
  return [...new Set(actions)];
}

function packetItem(item) {
  return {
    id: item.id,
    djName: item.djName,
    normalizedName: item.normalizedName,
    city: item.city,
    status: item.status,
    submittedAt: item.submittedAt,
    consentStatus: item.consentStatus,
    hasContact: Boolean(item.hasContact),
    hasAnswerText: Boolean(item.hasAnswerText),
    linkSummary: item.linkSummary,
    sourceEvidence: item.sourceEvidence,
    externalLinks: asArray(item.externalLinks),
    musicLinks: asArray(item.musicLinks),
    promotionGate: item.promotionGate,
    reviewActions: reviewActionsFor(item),
  };
}

function markdownEscape(value) {
  return String(value || "").replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

export async function buildDjInterviewReviewPacket(options = {}) {
  if (!options.store || typeof options.store.reviewQueue !== "function") {
    throw new Error("buildDjInterviewReviewPacket requires a store with reviewQueue().");
  }

  const queue = await options.store.reviewQueue({ limit: options.limit || 200 });
  const items = asArray(queue.items).map(packetItem);
  const blockers = items.flatMap((item) => asArray(item.promotionGate?.blockers));
  const platforms = items.flatMap((item) => asArray(item.linkSummary?.platforms));
  const musicPlatforms = items.flatMap((item) => asArray(item.linkSummary?.musicPlatforms));

  return {
    schemaVersion: "atlas_dj_interview_review_packet.v1",
    generatedAt: options.generatedAt || new Date().toISOString(),
    sourceSchemaVersion: queue.schemaVersion,
    summary: {
      total: queue.total || items.length,
      exported: items.length,
      withSourceEvidence: countWhere(items, (item) => item.sourceEvidence?.hasSourceUrl),
      withMusicLinks: countWhere(items, (item) => Number(item.linkSummary?.musicLinkCount || 0) > 0),
      blockedBeforePromotion: countWhere(items, (item) => item.promotionGate?.result === "blocked_before_promotion"),
      readyForHumanReview: countWhere(items, (item) => item.promotionGate?.result === "ready_for_human_review"),
      blockers: tally(blockers),
      platforms: tally(platforms),
      musicPlatforms: tally(musicPlatforms),
    },
    policy: {
      requiredNext: REQUIRED_NEXT,
      publicWritesDuringPacketBuild: false,
      copyrightMode: "original_platform_links_only",
    },
    safety: {
      rawContactExported: false,
      rawInterviewTextExported: false,
      rawAudioExported: false,
      publicGraphWriteExecuted: false,
      productionWriteExecuted: false,
      mediaDownloadExecuted: false,
      mediaCacheWritten: false,
      mediaProxyEnabled: false,
    },
    items,
  };
}

export function renderDjInterviewReviewPacketMarkdown(packet) {
  const lines = [
    "# DJ Interview Review Packet",
    "",
    `Generated: ${packet.generatedAt}`,
    `Schema: ${packet.schemaVersion}`,
    "",
    "## Summary",
    "",
    `- Total submissions: ${packet.summary.total}`,
    `- Exported rows: ${packet.summary.exported}`,
    `- With source evidence: ${packet.summary.withSourceEvidence}`,
    `- With music links: ${packet.summary.withMusicLinks}`,
    `- Blocked before promotion: ${packet.summary.blockedBeforePromotion}`,
    "",
    "## Review Queue",
    "",
    "| DJ | City | Source | Music links | Blockers | Actions |",
    "| --- | --- | --- | --- | --- | --- |",
  ];

  for (const item of packet.items) {
    lines.push([
      markdownEscape(item.djName),
      markdownEscape(item.city),
      markdownEscape(item.sourceEvidence?.sourceRefId || item.sourceEvidence?.sourceUrlHash || ""),
      String(item.linkSummary?.musicLinkCount || 0),
      markdownEscape(asArray(item.promotionGate?.blockers).join(", ")),
      markdownEscape(asArray(item.reviewActions).join(", ")),
    ].join(" | ").replace(/^/, "| ").replace(/$/, " |"));
  }

  lines.push(
    "",
    "## Safety",
    "",
    "- Raw contact exported: false",
    "- Raw interview text exported: false",
    "- Public graph write executed: false",
    "- Production DB write executed: false",
    "- Media download/cache/proxy executed: false",
  );
  return `${lines.join("\n")}\n`;
}

export async function writeDjInterviewReviewPacket(options = {}) {
  const outDir = options.outDir;
  if (!outDir) throw new Error("writeDjInterviewReviewPacket requires outDir.");
  const packet = await buildDjInterviewReviewPacket(options);
  await mkdir(outDir, { recursive: true });
  const jsonPath = path.join(outDir, "dj_interview_review_packet.json");
  const markdownPath = path.join(outDir, "dj_interview_review_packet.md");
  await writeFile(jsonPath, JSON.stringify(packet, null, 2), "utf8");
  await writeFile(markdownPath, renderDjInterviewReviewPacketMarkdown(packet), "utf8");
  return { packet, jsonPath, markdownPath };
}
