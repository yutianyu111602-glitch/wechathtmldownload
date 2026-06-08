# Atlas Outlink / Avatar Field Contract - 2026-05-22

Scope: DeepSeekTUI is currently useful for public profile, outlink, avatar, and social evidence collection. It must not write production graph rows directly.

2026-05-23 lifecycle note: this contract remains the T6 sidecar field-shape reference for avatar/outlink/profile candidates, but its "Current Atlas V2 Context" counts are a 2026-05-22 12:14 snapshot. For the latest local DJ-first public-safe serving candidate, read `reports\ATLAS_DJ_GRAPH_COMPLETION_CANDIDATE_20260522.md` and `docs\current-runtime.md` before using this packet.

## Output Shape

Each candidate row should contain:

- `subject_id`: canonical `dj_profile.dj_id` if known.
- `display_name`: DJ display name.
- `normalized_name`: normalized search key.
- `alias_used`: alias or handle that produced the hit.
- `platform`: `instagram`, `soundcloud`, `residentadvisor`, `bandcamp`, `mixcloud`, `youtube`, `bilibili`, `weibo`, `douban`, `beatport`, `spotify`, `linktree`, or `other_public_profile`.
- `handle`: public handle if present.
- `url_normalized`: canonical public profile URL.
- `avatar_url`: public avatar URL only.
- `avatar_source_url`: page where avatar was observed.
- `bio_snippet`: short public bio snippet.
- `evidence_source_url`: source page used as evidence.
- `evidence_source_title`: source page title.
- `evidence_text`: short text proving the profile belongs to the DJ.
- `match_type`: `official_source_link`, `profile_name_exact`, `alias_exact`, `same_article_profile`, `search_candidate`, or `maigret_candidate`.
- `confidence`: 0..1.
- `identity_proof`: boolean; true only for direct official or multi-source proof.
- `accepted_for_graph`: boolean; default false until a strict graph gate accepts it.
- `review_status`: `accepted`, `needs_review`, or `rejected`.
- `risk_flags`: array such as `short_name`, `common_word`, `fanpage`, `venue_account`, `label_account`, `private_or_login_required`, `mismatch_city`.
- `fetched_at`: ISO timestamp.

## Acceptance Rules

- Official source link from the DJ, venue lineup, RA/Bandcamp/SoundCloud verified-looking page, or two independent public sources can become `identity_proof=true`.
- SearXNG, Maigret, or search snippets alone are candidate evidence only.
- Short or ambiguous names such as `DaRou` require extra proof.
- Public serving must never expose cookies, tokens, private pages, follower lists, raw HTML, raw source URLs, archive paths, or unreviewed identity candidates.

## Current Atlas V2 Context

Codex completed deterministic public graph recovery v2:

- Strict public DB: `C:\code\githubstar\wechathtmldownload\reports\atlas_serving_recovered_public_v2_20260522\atlas_serving.sqlite`
- Report: `C:\code\githubstar\wechathtmldownload\reports\ATLAS_PUBLIC_GRAPH_RECOVERY_V2_20260522.md`
- Public events: `482,108`
- DJ profiles: `52,503`
- Venue missing dropped to `95,724`
- City missing dropped to `103,313`
- Remaining public gap is mainly participant identity confidence, not venue/city.

Later current candidate overlay: the 2026-05-22 23:48 DJ-complete activity-aware participant-delta v2 candidate is `reports\atlas_serving_activity_participant_candidate_139123_publicsafe_djcomplete_v2_20260522-2335\atlas_serving.sqlite`, with performance events `508,020`, DJ profiles `53,462`, DJ-event edges `1,285,415`, directed relation edges `699,816`, search docs `590,788`, graph windows `53,462`, evidence refs `130,592`, leak hits `0`, and search LIKE/FTS missing `0/40`. It is still a local candidate; promotion/deploy and graph/vector/database writes remain separate explicit gates.
