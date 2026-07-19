function generationIdOf(value) {
  return String(value && (value.generationId || value.generation_id) || "").trim();
}

function generatedAtOf(value) {
  return String(value && (value.generatedAt || value.generated_at || value.generated_at_iso) || "").trim();
}

function parseReleaseTimeMs(value) {
  const text = String(value || "").trim();
  if (!text) return 0;
  const parsed = Date.parse(text);
  if (Number.isFinite(parsed)) return parsed;
  const match = text.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?/);
  if (!match) return 0;
  const parts = match.slice(1).map((valuePart) => Number(valuePart || 0));
  if (!parts.every(Number.isFinite)) return 0;
  const [year, month, day, hour, minute, second] = parts;
  return Date.UTC(year, month - 1, day, hour - 8, minute, second);
}

function currentFeedBehindManifest(manifest, current, graceMs) {
  const manifestGenerationId = generationIdOf(manifest);
  const currentGenerationId = generationIdOf(current);
  if (manifestGenerationId || currentGenerationId) {
    return !manifestGenerationId || !currentGenerationId || manifestGenerationId !== currentGenerationId;
  }

  // Legacy packages did not carry generation_id. Keep their timestamp grace
  // only while both sides are legacy; never mix exact and legacy identities.
  const manifestMs = parseReleaseTimeMs(generatedAtOf(manifest));
  if (!manifestMs) return false;
  const currentMs = parseReleaseTimeMs(generatedAtOf(current));
  if (!currentMs) return Boolean(current && (current.fromCache || current.fromSnapshot));
  return manifestMs - currentMs > Math.max(0, Number(graceMs || 0));
}

module.exports = {
  currentFeedBehindManifest,
  generatedAtOf,
  generationIdOf,
};
