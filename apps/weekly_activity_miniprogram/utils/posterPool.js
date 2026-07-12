const DEFAULT_POSTER_LIMIT = 48;
const DEFAULT_MIN_POSTER_ITEMS = 24;

function safeText(value) {
  return String(value || "").trim();
}

function normalizePosterUrl(value) {
  return safeText(value)
    .replace(/\?.*$/, "")
    .replace(/\/+$/, "")
    .toLowerCase();
}

function posterVisualKey(item) {
  const rawCover = normalizePosterUrl(item.cover_image_url || item.cover_url || item.raw_cover_url || "");
  if (rawCover) return `cover:${rawCover}`;
  const sourceHash = safeText(item.sourceHash || item.source_action?.url_hash || item.source_article?.url_hash || "");
  if (sourceHash && item.coverUrl) return `source:${sourceHash}`;
  const coverUrl = normalizePosterUrl(item.coverUrl || "");
  if (coverUrl && !/\/api\/v1\/weekly\/poster\//.test(coverUrl)) return `cover:${coverUrl}`;
  return `id:${safeText(item.id)}`;
}

function countList(value) {
  return Array.isArray(value) ? value.filter(Boolean).length : 0;
}

function compactText(value) {
  if (Array.isArray(value)) return value.map(safeText).filter(Boolean).join("\n");
  if (value && typeof value === "object") {
    return [
      value.text,
      value.ocr_text,
      value.poster_text,
      value.body_text,
      value.summary,
      value.digest,
    ].map(safeText).filter(Boolean).join("\n");
  }
  return safeText(value);
}

function posterEvidenceText(item) {
  return [
    item.displayTitle,
    item.title,
    item.poster_source,
    item.poster_url,
    item.flyer_url,
    item.cover_image_url,
    item.cover_url,
    item.poster_ocr_text,
    item.posterOcrText,
    item.ocr_text,
    item.ocrText,
    item.source_evidence_text,
    item.description_text,
    compactText(item.poster_ocr),
    compactText(item.ocr),
    compactText(item.source_evidence),
    compactText(item.description_original_lines),
  ].map(safeText).filter(Boolean).join("\n");
}

function posterSuppressed(item) {
  return item && (
    item.poster_suppressed === true ||
    item.posterSuppressed === true ||
    item.main_poster_suppressed === true ||
    item.mainPosterSuppressed === true
  );
}

function textBlockCount(item) {
  const explicit = Number(
    item.poster_text_block_count ||
    item.posterTextBlockCount ||
    item.ocr_text_block_count ||
    item.ocrTextBlockCount ||
    0,
  );
  if (Number.isFinite(explicit) && explicit > 0) return explicit;
  const text = posterEvidenceText(item);
  if (!text) return 0;
  return text.split(/\n+|[|｜]/).map(safeText).filter(Boolean).length;
}

function nonMainPosterPenalty(item) {
  const haystack = posterEvidenceText(item).toLowerCase();
  if (!haystack) return 0;
  const weakSignals = [
    /qr\s*code|qrcode|barcode|wechat|weixin|mini\s*program/,
    /二维码|小程序码|扫码|长按|收款|付款|赞赏|菜单|酒单|地图|购票二维码/,
    /avatar|logo|sponsor|partner|ticket|payment|map|menu/,
  ];
  return weakSignals.reduce((sum, pattern) => sum + (pattern.test(haystack) ? 8 : 0), 0);
}

function posterScore(item) {
  if (posterSuppressed(item)) return -Infinity;
  const lineupCount = Math.max(countList(item.lineupItems), countList(item.lineup), countList(item.lineup_artists));
  const descriptionCount = Math.max(countList(item.descriptionLines), countList(item.description_original_lines));
  const priceCount = Math.max(countList(item.price), countList(item.ticketing_tiers));
  const sourceHash = safeText(item.sourceHash || item.source_action?.url_hash || item.source_article?.url_hash);
  const infoScore =
    Math.min(lineupCount, 10) * 4 +
    Math.min(descriptionCount, 8) * 2 +
    Math.min(priceCount, 4) * 2 +
    Math.min(textBlockCount(item), 12) +
    (item.mimo_ocr_lineup || item.mimoOcrLineup ? 6 : 0) +
    (sourceHash ? 4 : 0) +
    (eventDateSortKey(item) ? 3 : 0) +
    (item.hasSoundSystem || countList(item.soundSystemItems) ? 3 : 0) +
    (item.mapLocation || item.hasMapLocation ? 2 : 0);
  return (
    (item.coverUrl ? 20 : 0) +
    (item.hasStyle ? 4 : 0) +
    (item.hasLineup ? 3 : 0) +
    (item.hasDescription ? 2 : 0) +
    (item.hasAddress ? 1 : 0) +
    infoScore -
    nonMainPosterPenalty(item)
  );
}

function first(value, fallback = "") {
  return Array.isArray(value) ? value[0] || fallback : value || fallback;
}

function eventDateSortKey(item) {
  return safeText(item.event_date_start || item.event_date_iso_guess || first(item.event_date_iso_guesses, "") || item.dateLabel);
}

function sortPosterCandidates(items, tab) {
  const copy = [...items];
  if (tab === "new") {
    return copy.sort((a, b) => {
      const eventDateCompare = eventDateSortKey(b).localeCompare(eventDateSortKey(a));
      if (eventDateCompare) return eventDateCompare;
      return safeText(a.dateLabel).localeCompare(safeText(b.dateLabel));
    });
  }
  return copy.sort((a, b) => {
    const scoreCompare = posterScore(b) - posterScore(a);
    if (scoreCompare) return scoreCompare;
    const dateCompare = safeText(a.dateLabel).localeCompare(safeText(b.dateLabel));
    if (dateCompare) return dateCompare;
    return safeText(a.displayTitle).localeCompare(safeText(b.displayTitle));
  });
}

function addUnique(target, seenIds, seenVisuals, candidates, maxItems) {
  for (const item of candidates) {
    if (!item || !item.id || seenIds.has(item.id)) continue;
    const visualKey = posterVisualKey(item);
    if (visualKey && seenVisuals.has(visualKey)) continue;
    seenIds.add(item.id);
    if (visualKey) seenVisuals.add(visualKey);
    target.push(item);
    if (target.length >= maxItems) break;
  }
}

function toPosterCard(item, index) {
  return {
    id: item.id,
    posterKey: `${item.id}::poster::${index}`,
    coverUrl: item.coverUrl || "",
    posterFileId: item.posterFileId || item.poster_file_id || item.coverFileId || item.cover_file_id || "",
    posterTempUrl: item.posterTempUrl || "",
    displayTitle: item.displayTitle || item.title || "",
    weekdayLabel: item.weekdayLabel || "",
    dateRangeCompact: item.dateRangeCompact || "",
    dateCompact: item.dateCompact || "",
    isCalendarPreview: Boolean(item.isCalendarPreview),
    isSourceOverview: Boolean(item.isSourceOverview),
    calendarPreviewLabel: item.calendarPreviewLabel || "",
    cardLocationLabel: item.cardLocationLabel || "",
    hasStyle: Boolean(item.hasStyle),
    styleLabel: item.styleLabel || "",
  };
}

function buildPosterPool(primaryItems, broadItems, tab, options = {}) {
  const maxItems = Math.max(1, Number(options.maxItems || DEFAULT_POSTER_LIMIT));
  const minItems = Math.min(maxItems, Math.max(1, Number(options.minItems || DEFAULT_MIN_POSTER_ITEMS)));
  const primary = Array.isArray(primaryItems) ? primaryItems.filter((item) => !posterSuppressed(item)) : [];
  const broad = Array.isArray(broadItems) ? broadItems.filter((item) => !posterSuppressed(item)) : [];
  const selected = [];
  const seenIds = new Set();
  const seenVisuals = new Set();

  addUnique(
    selected,
    seenIds,
    seenVisuals,
    sortPosterCandidates(primary.filter((item) => item && item.coverUrl), tab),
    maxItems,
  );
  addUnique(
    selected,
    seenIds,
    seenVisuals,
    sortPosterCandidates(broad.filter((item) => item && item.coverUrl), tab),
    maxItems,
  );
  addUnique(selected, seenIds, seenVisuals, sortPosterCandidates(primary, tab), maxItems);
  addUnique(selected, seenIds, seenVisuals, sortPosterCandidates(broad, tab), maxItems);

  if (selected.length === 0) return [];

  const looped = [...selected];
  let cursor = 0;
  while (looped.length < minItems && selected.length > 0) {
    looped.push(selected[cursor % selected.length]);
    cursor += 1;
  }
  return looped.slice(0, maxItems).map(toPosterCard);
}

module.exports = {
  buildPosterPool,
  posterVisualKey,
  posterScore,
  sortPosterCandidates,
};
