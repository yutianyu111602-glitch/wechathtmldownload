<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

You are extracting structured event facts from WeChat article markdown.

Return JSON only. Do not wrap it in markdown.

Schema:
{
  "article_type": "event|recap|announcement|interview|playlist|other",
  "title": string,
  "summary": string,
  "events": [
    {
      "name": string,
      "date_text": string,
      "time_text": string,
      "venue": string,
      "city": string,
      "lineup": string[],
      "ticket_text": string,
      "confidence": number
    }
  ],
  "warnings": string[]
}

Rules:
- Preserve Chinese text exactly when it names artists, venues, dates, ticket tiers, or addresses.
- Entity biographies/bios, label or collective introductions, and venue profiles/info must remain exact source text. Do not summarize, paraphrase, abstract, rewrite, translate, shorten, merge, normalize, or invent them.
- If those descriptive fields are unavailable as exact source spans, leave them empty and add a warning; never create a synthetic bio, label intro, or venue description.
- Use empty strings or empty arrays when fields are missing.
- Put uncertainty in warnings instead of inventing facts.
- Keep summary under 80 Chinese characters or 120 English characters.
