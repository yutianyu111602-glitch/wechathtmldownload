const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const publicExternalLinks = require(path.join(root, "utils", "publicExternalLinks.js"));

function item(overrides) {
  return {
    item_id: "link-a",
    entity_search_id: "entity-a",
    entity_name: "FullHouse",
    entity_type: "person",
    platform: "soundcloud",
    public_category: "mixtape_music",
    display_label: "SoundCloud",
    url: "https://soundcloud.com/dj-fullhouse/full-flower",
    source_ref: "entity-a",
    confidence_score: 95,
    confidence_band: "high",
    miniapp_display_allowed_candidate: true,
    action: {
      mode: "copy_original_link",
      jump_out_original_url: true,
      media_cached: false,
      media_downloaded: false,
      media_proxied: false,
    },
    ...overrides,
  };
}

test("normalizes high-confidence external links for display only", () => {
  const links = publicExternalLinks.normalizeExternalLinks(
    [
      item({ item_id: "mix", public_category: "mixtape_music", display_label: "SoundCloud" }),
      item({ item_id: "ins", platform: "instagram", public_category: "instagram", display_label: "Instagram", url: "https://www.instagram.com/example_dj/" }),
      item({ item_id: "low", public_category: "video", confidence_score: 70, confidence_band: "medium", url: "https://www.youtube.com/@low" }),
      item({ item_id: "blocked", block_reasons: ["direct_media_or_archive_url"], url: "https://cdn.example.com/raw.mp3" }),
      item({ item_id: "dup", url: "https://soundcloud.com/dj-fullhouse/full-flower/" }),
    ],
    "zh",
  );

  assert.equal(links.length, 2);
  assert.deepEqual(
    links.map((link) => link.publicCategory),
    ["instagram", "mixtape_music"],
  );
  assert.equal(links[0].action.mode, "copy_original_link");
  assert.equal(links[0].action.mediaCached, false);
  assert.equal(links[0].action.mediaDownloaded, false);
  assert.equal(links[0].action.mediaProxied, false);
});
test("groups links by entity for compact mini-program sections", () => {
  const groups = publicExternalLinks.groupExternalLinksForDisplay(
    [
      item({ item_id: "a", entity_search_id: "entity-a", entity_name: "FullHouse" }),
      item({ item_id: "b", entity_search_id: "entity-b", entity_name: "Gekko", platform: "youtube", public_category: "video", display_label: "YouTube", url: "https://www.youtube.com/@gekko" }),
    ],
    "en",
  );

  assert.equal(groups.length, 2);
  assert.equal(groups[0].entityName, "FullHouse");
  assert.equal(groups[0].links[0].displayLabel, "SoundCloud");
  assert.equal(groups[1].links[0].action.platform, "youtube");
});

test("build action from item still rejects direct media URLs", () => {
  const action = publicExternalLinks.buildExternalLinkActionFromItem(
    item({ public_category: "video", url: "https://media.example.com/show.mp4" }),
    "zh",
  );

  assert.equal(action.ok, false);
  assert.equal(action.reason, "direct_media_url");
});

test("normalizes DJ discovery sections with safe links and bio atoms", () => {
  const sections = publicExternalLinks.normalizeDjDiscoverySectionsForDisplay(
    [
      {
        name: "DINA",
        name_key: "dina",
        bio_atoms: [
          { text: "Berlin / Nachtcrew 线索，来自来源证据。", source_ref: "source:dina", verbatim_source: true },
          { text: "Berlin / Nachtcrew 线索，来自来源证据。", source_ref: "dup", verbatim_source: true },
          { text: "风格线索: trance / bassline", source_ref: "generated" },
          { text: "No source ref should be hidden." },
        ],
        links: [
          item({
            item_id: "dina-ra",
            entity_search_id: "dj:dina",
            entity_name: "DINA",
            platform: "resident_advisor",
            public_category: "public_profile",
            display_label: "Resident Advisor",
            url: "https://ra.co/dj/dina",
          }),
          item({
            item_id: "dina-interview",
            entity_search_id: "dj:dina",
            entity_name: "DINA",
            platform: "origins_sound",
            public_category: "interview",
            display_label: "Origins",
            url: "https://www.originssound.com/os-tapes/dina-mix",
          }),
          item({
            item_id: "dina-low",
            entity_search_id: "dj:dina",
            entity_name: "DINA",
            confidence_score: 70,
            confidence_band: "medium",
            url: "https://example.com/low",
          }),
        ],
      },
    ],
    "zh",
  );

  assert.equal(sections.length, 1);
  assert.equal(sections[0].name, "DINA");
  assert.equal(sections[0].bioAtoms.length, 1);
  assert.deepEqual(
    sections[0].links.map((link) => link.displayLabel),
    ["Origins", "Resident Advisor"],
  );
  assert.equal(sections[0].hasLinks, true);
  assert.equal(sections[0].hasBioAtoms, true);
});

test("radio and mixtape links stay as source-link actions without media handling", () => {
  const links = publicExternalLinks.normalizeExternalLinks(
    [
      item({
        item_id: "baihui-show",
        entity_search_id: "dj:spyfi",
        entity_name: "Spyfi",
        platform: "baihui",
        public_category: "radio",
        display_label: "BAIHUI",
        url: "https://baihui.live/shows/slumber-station-w-spyfi-26-03-25/cn/",
      }),
    ],
    "zh",
  );

  assert.equal(links.length, 1);
  assert.equal(links[0].action.mode, "copy_original_link");
  assert.equal(links[0].action.platform, "baihui");
  assert.equal(links[0].action.mediaCached, false);
  assert.equal(links[0].action.mediaDownloaded, false);
  assert.equal(links[0].action.mediaProxied, false);
});
