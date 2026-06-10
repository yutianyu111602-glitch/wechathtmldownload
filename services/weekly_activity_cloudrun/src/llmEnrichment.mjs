function compactItemForPrompt(item) {
  return {
    id: item.id,
    title: item.title,
    account: item.account,
    promoter: item.promoter,
    post_date: item.post_date,
    event_date_text: item.event_date_text || [],
    event_date_iso_guess: item.event_date_iso_guess || "",
    city: item.city || [],
    venue: item.venue || [],
    address: item.address || "",
    lineup: item.lineup || [],
    genres: item.genres || [],
    music_styles: item.music_styles || [],
    style_tags: item.style_tags || [],
    price: item.price || [],
    price_text: item.price_text || "",
    ticketing_text: item.ticketing_text || "",
    sound_system: item.sound_system || item.sound_systems || [],
    sound_system_text: item.sound_system_text || item.audio_system || item.soundSystem || "",
    sound_system_evidence: item.sound_system_evidence || item.audio_system_evidence || [],
    evidence: item.evidence || [],
    description_original_lines: item.description_original_lines || [],
    source_article_title: item.source_article_title || "",
    source_article_summary_digest: item.source_article_summary_digest || "",
    source_article_digest: item.source_article_digest || "",
    source_sound_system_snippets: item.source_sound_system_snippets || [],
    source_url: item.source_url || "",
    cover_image_url: item.cover_image_url || item.cover_url || item.coverUrl || "",
  };
}

export function buildWeeklyItemEnrichmentMessages(item) {
  const compact = compactItemForPrompt(item);
  return [
    {
      role: "system",
      content: [
        "You clean and normalize Chinese club event records for a weekly activity guide.",
        "Return strict JSON only.",
        "Do not invent facts.",
        "Only copy or normalize facts that are present in the provided item.",
        "This is a staging extraction schema, not the final published truth.",
        "For music_styles, infer only from explicit source wording, artist/style metadata, lineup context, or known underground genre terms in the item.",
        "If an exact time, street address, venue, lineup member, DJ bio, or music style is not supported, return null or an empty array and add a review flag.",
        "Street addresses and geo coordinates are sourced from the venue database — do not extract or guess them.",
        "Use ONLY styles from this underground electronic music vocabulary: house, deep house, tech house, acid house, progressive house, minimal house, microhouse, afro house, melodic house, organic house, tribal house, garage house, jackin house, ghetto house; techno, detroit techno, acid techno, dub techno, industrial techno, peak time techno, raw techno, hypnotic techno, hard techno, minimal techno, berlin techno, ambient techno; minimal, deeptech, rominimal, deep minimal; trance, progressive trance, psytrance, goa trance, uplifting trance, melodic trance, hard trance, tech trance; drum and bass, jungle, liquid drum and bass, neurofunk, jump up, techstep, atmospheric drum and bass, intelligent drum and bass, halftime, drumfunk; breaks, breakbeat, uk garage, 2-step, dubstep, bass music, future garage, speed garage, grime, uk funky, footwork, juke, jungle tekno, 140, deep dubstep; bass, club, bassline, gqom, kuduro, baile funk, dancehall, reggaeton, moombahton, global club; electro, electroclash, italo disco, synthwave, dark electro, ebm, industrial, body music; disco, nu-disco, cosmic disco, boogie, funk, modern soul, rare groove, balearic; ambient, drone, field recording, soundscape, dark ambient, new age, space music; experimental, avant-garde, noise, musique concrete, electroacoustic, sound art, glitch, idm, braindance; downtempo, trip hop, chillout, lo-fi, beat tape, instrumental hip hop, jazztronica, future beats; dub, roots reggae, steppers, digital dancehall, rub-a-dub; hip hop, boom bap, abstract hip hop, conscious hip hop, trap, cloud rap, phonk, memphis rap; hardcore, gabber, speedcore, breakcore, digital hardcore, harsh noise, power electronics; deconstructed club, hyperpop, chillwave, vaporwave, witch house; jazz, spiritual jazz, free jazz, fusion, nu-jazz, acid jazz, jazz-funk, modal jazz, contemporary jazz; world music, cumbia, highlife, ethio-jazz, desert blues, tropical, latin electronic; club trax, 4x4, deep listening, sound system culture.",
        "Lineup must contain DJ/artist names only. Remove club, promoter, venue, city, platform, and account names.",
        "Ticket prices must be exact source-backed values.",
        "Do not infer ticket prices from QR codes, YuYuan/芋圆 mini-program links, click-for-ticket text, or poster buttons without visible amounts.",
        "Separate early bird, presale, door/onsite, double/pair, student/discount, and time-conditional free-entry.",
        "3am/3 AM/凌晨3点 are time conditions, not ticket price 3.",
        "Drink specials, drink packages, table minimums, and bar promotion prices are not ticket prices unless the source says they include admission/entry.",
        "For sound system, copy only explicit venue/system/equipment names present in source evidence, such as Funktion-One, F1, Void, d&b, L-Acoustics, Meyer Sound, KV2, NEXO, Martin Audio, or OIL Soundsystem.",
        "source_sound_system_snippets are exact source snippets around possible sound-system terms; use them as evidence only when they name a concrete system/equipment.",
        "Do not treat artist crew context such as OIL Soundsystem成员, soundsystem culture, or people being close to 音箱 as the venue's installed sound system.",
        "Do not infer sound systems from generic praise such as 音响效果很好, 声音很棒, sound is good, or vague venue atmosphere copy.",
        "Do not translate source titles, artist names, club names, addresses, or evidence text.",
      ].join("\n"),
    },
    {
      role: "user",
      content: JSON.stringify({
        task: "Normalize one weekly activity item for display.",
        output_schema: {
          schema_version: "weekly_event_extract.v1",
          is_event: "boolean, true only for real club/event announcements",
          title_display: "string|null, cleaned event title without date/account noise",
          event_date_start: "string|null, ISO date if supported",
          event_date_end: "string|null, ISO date if supported",
          event_time_text: "string|null, e.g. 22:00 or 22:00-04:00, only if explicitly present",
          city_name: "string|null",
          venue_name: "string|null",
          address_candidate: "string|null, sourced from venue database — do not extract",
          lineup_artists: "array<string>, DJ/artist names only; remove club/promoter/venue names",
          music_styles: "array<string>, compact underground music style tags only when supported by item evidence",
          sound_system: "array<string>, source-backed venue/system/equipment names only; leave empty for generic praise or no explicit system",
          sound_system_evidence: "array<string>, exact source quotes proving each sound_system entry",
          sound_system_confidence: "number|null, 0..1 source-backed confidence only; null when empty",
          dj_bio_lines: "array<string>, original source lines about lineup artists only",
          description_original_lines: "array<string>, useful original activity description lines without QR/account boilerplate",
          ticketing_text: "array<string>, exact source-backed ticket price or entry rules only; 3am/3 AM are time conditions, never price 3; keep '3am 后免费入场' as one entry rule; leave empty for QR/YuYuan/link-only ticketing with no visible amount",
          ticketing_tiers: "array<object>, each object has label, amount, currency, rule, evidence_quote, confidence; separate 早鸟/预售/现场/双人/学生/3am后免费入场; leave empty when no exact source-backed ticket amount/rule is visible",
          flyer_url: "string|null, main event flyer or poster image URL from the source article; use the hero/banner image when a dedicated flyer is absent",
          description_text: "string|null, 1-3 sentence event description extracted from the source article; include activity type, atmosphere, special theme or gimmick; keep original language; leave null when the source has no descriptive content beyond dates/times",
          dedupe_signals: "array<string>, compact strings useful for near-duplicate grouping",
          review_flags: "array<string>, e.g. missing_city, missing_time, venue_uncertain, lineup_uncertain, possible_duplicate, closed_or_cancelled_signal",
          notes: "array<string>, short Chinese notes about missing or ambiguous fields",
        },
        item: compact,
      }),
    },
  ];
}

export async function enrichWeeklyItemWithDeepSeek(item, deepSeekClient) {
  const result = await deepSeekClient.createJsonChat({
    messages: buildWeeklyItemEnrichmentMessages(item),
    temperature: 0,
    maxTokens: 1200,
  });
  return {
    provider: "deepseek",
    model: result.model,
    usage: result.usage,
    enrichment: result.json,
  };
}
