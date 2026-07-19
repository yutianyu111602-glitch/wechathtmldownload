function effectiveFeedItems(data = {}) {
  if (!data || typeof data !== "object") return [];
  if (Array.isArray(data.viewItems) && data.viewItems.length > 0) return data.viewItems;
  if (Array.isArray(data.groups)) {
    const grouped = data.groups.flatMap((group) => (
      Array.isArray(group && group.items) ? group.items : []
    ));
    if (grouped.length > 0) return grouped;
  }
  if (Array.isArray(data.items)) return data.items;
  return [];
}

function effectiveFeedCount(data = {}) {
  const totalItems = Number(data && data.totalItems);
  if (Number.isFinite(totalItems) && totalItems > 0) return totalItems;
  return effectiveFeedItems(data).length;
}

module.exports = {
  effectiveFeedCount,
  effectiveFeedItems,
};
