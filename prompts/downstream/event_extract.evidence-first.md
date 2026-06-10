<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

Extract only facts supported by the article markdown.

Return strict JSON only.

Prioritize:
1. Event date, time, venue, city, and address.
2. Artist lineup, DJ names, labels, collectives, hosts, and guests.
3. Ticket price, RSVP, door policy, age policy, and sales channel.
4. Whether the article is image-heavy or missing text evidence.

JSON shape:
{
  "is_event_related": boolean,
  "evidence_quality": "ready|review|blocked",
  "facts": {
    "dates": string[],
    "times": string[],
    "venues": string[],
    "cities": string[],
    "addresses": string[],
    "lineup": string[],
    "tickets": string[]
  },
  "needs_ocr": boolean,
  "reason": string
}

Rules:
- Entity biographies/bios, label or collective introductions, and venue profiles/info must remain exact source text. Do not summarize, paraphrase, abstract, rewrite, translate, shorten, merge, normalize, or invent them.
- If those descriptive fields are unavailable as exact source spans, leave them out and note the absence; never create a synthetic bio, label intro, or venue description.
- Never infer a venue or lineup from unrelated footer text.
- If the body is short and images/poster OCR are referenced, set needs_ocr=true.
- Keep reason short.
