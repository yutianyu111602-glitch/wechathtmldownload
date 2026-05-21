function safeText(value) {
  return String(value || "").trim();
}

function sourceHashOf(item) {
  return safeText(item && (item.sourceHash || item.source_action?.url_hash || item.source_article?.url_hash));
}

function sourceHashOfRef(ref) {
  return safeText(ref && (ref.source_hash || ref.hash || ref.url_hash));
}

function isAggregateLikeItem(item) {
  return safeText(item && (item.id || item.event_id || item.article_id)).startsWith("agg-child-");
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
  const sourceArticle = item && typeof item.source_article === "object" ? item.source_article : {};
  const hash = sourceHashOf(item);
  if (!hash) return null;
  return {
    source_hash: hash,
    title: safeText(item && (item.source_title || sourceArticle.title)),
    account_name: safeText(item && (item.source_account_name || item.account || item.promoter || sourceArticle.account_name)),
    published_at: safeText(item && (item.source_published_at || sourceArticle.published_at)),
    is_primary: true,
  };
}

function mergedSourceRefs(item) {
  const provenance = item && typeof item.merge_provenance === "object" ? item.merge_provenance : null;
  if (!provenance || provenance.schema_version !== "weekly_merge_provenance.v1") return [];
  return (Array.isArray(provenance.sources) ? provenance.sources : [])
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

function buildVenueSourceArticles(events) {
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
    .filter(({ group }) => group.events.length > 1 || group.events.some(isAggregateLikeItem) || group.isMergedSource)
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
    }));
}

module.exports = {
  buildDetailSourceArticles,
  buildVenueSourceArticles,
  isAggregateLikeItem,
  sourceHashOf,
  sourceRefsForItem,
};
