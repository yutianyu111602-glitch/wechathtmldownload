function safeText(value) {
  return String(value || "").trim();
}

function listLocationLabel(item, selectedCity) {
  if (!item) return "";
  if (item.isSourceOverview) return "";
  const city = safeText(item.cityLabel || item.city_key || "");
  const venue = safeText(
    item.venueLabel || item.venue_name || item.promoter || item.account || ""
  );
  if (city && venue) return city + " · " + venue;
  return city || venue || "";
}

function withListLocationLabels(items, selectedCity) {
  return (Array.isArray(items) ? items : []).map((item) => ({
    ...item,
    listLocationLabel: listLocationLabel(item, selectedCity),
  }));
}

module.exports = {
  listLocationLabel,
  withListLocationLabels,
};
