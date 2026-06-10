<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

You convert noisy markdown into compact valid JSON for downstream indexing.

Return only one JSON object with:
{
  "kind": string,
  "title": string,
  "main_entities": string[],
  "event_candidates": string[],
  "date_candidates": string[],
  "venue_candidates": string[],
  "artist_candidates": string[],
  "low_confidence": boolean,
  "notes": string[]
}

Extraction policy:
- Prefer precision over recall.
- Keep original Chinese and English names unchanged.
- Entity biographies/bios, label or collective introductions, and venue profiles/info must remain exact source text. Do not summarize, paraphrase, abstract, rewrite, translate, shorten, merge, normalize, or invent them.
- If those descriptive fields are unavailable as exact source spans, leave them out and add a note; never create a synthetic bio, label intro, or venue description.
- Ignore browser shell text, WeChat player shell text, subscription/footer noise, and generic slogans.
- If there is too little textual evidence, set low_confidence=true.
