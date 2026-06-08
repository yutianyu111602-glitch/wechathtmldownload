function safeText(value) {
  return String(value || "").trim();
}

function isAtlasEvidenceRef(value) {
  return /^(src|source|source_ref|evidence|activity_src|atlas_src):/i.test(safeText(value));
}

function sourceActionDisabled(item) {
  return item && item.source_action && item.source_action.available === false;
}

function isAggregateLikeItem(item) {
  return Boolean(item && (item.aggregation_child === true || item.aggregationChild === true))
    || safeText(item && (item.id || item.event_id || item.article_id)).startsWith("agg-child-");
}

function sourceHashOf(item) {
  if (sourceActionDisabled(item) || isAggregateLikeItem(item)) return "";
  const sourceRefId = safeText(item && (item.sourceRefId || item.source_ref_id));
  if (isAtlasEvidenceRef(sourceRefId)) return sourceRefId;
  return safeText(item && (item.sourceHash || sourceRefId || item.source_action?.url_hash || item.source_article?.url_hash));
}

function sourceHashOfRef(ref) {
  const sourceRefId = safeText(ref && (ref.source_ref_id || ref.sourceRefId));
  if (isAtlasEvidenceRef(sourceRefId)) return sourceRefId;
  return safeText(ref && (ref.source_hash || ref.hash || ref.url_hash || sourceRefId));
}

function isAggregateLikeRef(ref) {
  return Boolean(ref && ref.aggregation_child === true)
    || safeText(ref && (ref.event_id || ref.id || ref.source_event_id)).startsWith("agg-child-");
}

function compactDate(value) {
  const text = safeText(value);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text.slice(5).replace("-", ".") : text;
}

function sourceArticleTitle(events) {
  const first = events[0] || {};
  const account = safeText(first.source_account_name || first.account || first.promoter || "公众号");
  const aggregate = events.some(isAggregateLikeItem);
  return aggregate ? `${account} 排期原文` : `${account} 原文`;
}

function primarySourceRef(item) {
  if (isAggregateLikeItem(item)) return null;
  const sourceArticle = item && typeof item.source_article === "object" ? item.source_article : {};
  const hash = sourceHashOf(item);
  if (!hash) return null;
  return {
    source_hash: hash,
    source_ref_id: safeText(item && (item.sourceRefId || item.source_ref_id)),
    title: safeText(item && (item.source_title || item.sourceTitle || sourceArticle.title)),
    account_name: safeText(item && (item.source_account_name || item.sourceAccountName || item.account || item.promoter || sourceArticle.account_name)),
    published_at: safeText(item && (item.source_published_at || item.sourcePublishedAt || sourceArticle.published_at)),
    is_primary: true,
  };
}

function mergedSourceRefs(item) {
  if (sourceActionDisabled(item)) return [];
  const provenance = item && typeof item.merge_provenance === "object" ? item.merge_provenance : null;
  if (!provenance || provenance.schema_version !== "weekly_merge_provenance.v1") return [];
  return (Array.isArray(provenance.sources) ? provenance.sources : [])
    .filter((ref) => !isAggregateLikeRef(ref))
    .map((ref) => ({
      source_hash: sourceHashOfRef(ref),
      title: safeText(ref && ref.title),
      account_name: safeText(ref && ref.account_name),
      published_at: safeText(ref && ref.published_at),
      is_primary: sourceHashOfRef(ref) === safeText(provenance.retained_source_hash),
      is_merged_source: true,
    }))
    .filter((ref) => ref.source_hash);
}

function sourceRefsForItem(item) {
  if (sourceActionDisabled(item)) return [];
  const byHash = new Map();
  const primary = primarySourceRef(item);
  if (primary) byHash.set(primary.source_hash, primary);
  for (const ref of mergedSourceRefs(item)) {
    const current = byHash.get(ref.source_hash) || {};
    byHash.set(ref.source_hash, {
      ...current,
      ...ref,
      title: ref.title || current.title || "",
      account_name: ref.account_name || current.account_name || "",
      published_at: ref.published_at || current.published_at || "",
      is_primary: Boolean(current.is_primary || ref.is_primary),
      is_merged_source: true,
    });
  }
  const refs = [...byHash.values()];
  return refs.sort((left, right) => Number(right.is_primary) - Number(left.is_primary));
}

function titleFromRef(ref, events) {
  if (safeText(ref && ref.title)) return safeText(ref.title);
  if ((Array.isArray(events) ? events : []).some(isAggregateLikeItem)) return sourceArticleTitle(events);
  const account = safeText(ref && ref.account_name);
  if (account) return `${account} 原文`;
  return sourceArticleTitle(events);
}

function sourceArticleSubtitle(events) {
  const dates = [...new Set(events.map((item) => safeText(item.dateCompact || compactDate(item.event_date_start || item.dateLabel))).filter(Boolean))];
  const first = events[0] || {};
  const published = compactDate(first.source_published_at || first.source_article?.published_at);
  const count = `${events.length}场`;
  const parts = [];
  if (published) parts.push(`发布 ${published}`);
  if (dates.length) parts.push(dates.length > 2 ? `${dates[0]}-${dates[dates.length - 1]}` : dates.join(" / "));
  parts.push(count);
  return parts.join(" · ");
}

function sourceArticleSubtitleFromRef(ref, events) {
  const dates = [...new Set(events.map((item) => safeText(item.dateCompact || compactDate(item.event_date_start || item.dateLabel))).filter(Boolean))];
  const published = compactDate(ref && ref.published_at);
  const count = `${events.length}场`;
  const parts = [];
  if (published) parts.push(`发布 ${published}`);
  if (dates.length) parts.push(dates.length > 2 ? `${dates[0]}-${dates[dates.length - 1]}` : dates.join(" / "));
  parts.push(count);
  return parts.join(" · ");
}

function buildDetailSourceArticles(item) {
  const refs = sourceRefsForItem(item);
  if (refs.length <= 1) return [];
  const event = item || {};
  return refs.map((ref) => {
    const hash = sourceHashOfRef(ref);
    return {
      id: `source-${hash}`,
      hash,
      fallbackDetailId: safeText(event.id),
      title: titleFromRef(ref, [event]),
      subtitle: sourceArticleSubtitleFromRef(ref, [event]),
      eventCount: 1,
      isAggregate: isAggregateLikeItem(event),
      isMergedSource: true,
      isPrimary: ref.is_primary === true,
    };
  });
}

function buildVenueSourceArticles(events, options = {}) {
  const includeSingles = options.includeSingles === true;
  const maxArticles = Math.max(0, Number(options.maxArticles || 0));
  const groups = new Map();
  for (const item of Array.isArray(events) ? events : []) {
    for (const ref of sourceRefsForItem(item)) {
      const hash = sourceHashOfRef(ref);
      if (!hash) continue;
      if (!groups.has(hash)) {
        groups.set(hash, {
          events: [],
          eventIds: new Set(),
          refs: [],
          isMergedSource: false,
        });
      }
      const group = groups.get(hash);
      const eventId = safeText(item && (item.id || item.event_id || item.article_id));
      if (!eventId || !group.eventIds.has(eventId)) {
        group.events.push(item);
        if (eventId) group.eventIds.add(eventId);
      }
      group.refs.push(ref);
      if (ref.is_merged_source) group.isMergedSource = true;
    }
  }
  return [...groups.entries()]
    .map(([hash, group]) => ({ hash, group }))
    .filter(({ group }) => includeSingles || group.events.length > 1 || group.events.some(isAggregateLikeItem) || group.isMergedSource)
    .map(({ hash, group }) => ({
      id: `source-${hash}`,
      hash,
      fallbackDetailId: safeText(group.events[0] && group.events[0].id),
      title: titleFromRef(group.refs[0], group.events),
      subtitle: group.isMergedSource
        ? sourceArticleSubtitleFromRef(group.refs[0], group.events)
        : sourceArticleSubtitle(group.events),
      eventCount: group.events.length,
      isAggregate: group.events.some(isAggregateLikeItem),
      isMergedSource: group.isMergedSource,
    }))
    .slice(0, maxArticles || undefined);
}

module.exports = {
  buildDetailSourceArticles,
  buildVenueSourceArticles,
  isAtlasEvidenceRef,
  isAggregateLikeItem,
  isAggregateLikeRef,
  sourceHashOf,
  sourceRefsForItem,
};
