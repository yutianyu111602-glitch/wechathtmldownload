// utils/djLinks.js
// Turn a DJ's social_json (instagram/soundcloud/mixcloud/bandcamp/spotify/
// resident_advisor/website) into external-link items shaped for
// utils/publicExternalLinks.js (which gates on miniapp_display_allowed_candidate
// + high confidence + a known public_category). ES5, pure.
// ponytail: only emit a link when we can form a confident URL — bare handles map
// to the canonical host for IG/SC/MC; everything else needs a domain in the value.

var CATEGORY_BY_KEY = {
  instagram: "instagram",
  soundcloud: "mixtape_music",
  mixcloud: "mixtape_music",
  bandcamp: "mixtape_music",
  spotify: "mixtape_music",
  resident_advisor: "public_profile",
  ra: "public_profile",
  website: "external",
  // wechat intentionally omitted — not an openable external web link.
};

function ensureHttps(value) {
  var v = String(value || "").trim();
  if (!v) return "";
  if (/^https?:\/\//i.test(v)) return v.replace(/^http:\/\//i, "https://");
  return v.indexOf(".") !== -1 ? "https://" + v : "";
}

function urlForKey(key, value) {
  var v = String(value || "").trim();
  if (!v) return "";
  if (/^https?:\/\//i.test(v)) return v.replace(/^http:\/\//i, "https://");
  var handle = v.replace(/^@/, "").replace(/\s+/g, "");
  if (key === "instagram") return handle ? "https://instagram.com/" + handle : "";
  if (key === "soundcloud") return handle ? "https://soundcloud.com/" + handle : "";
  if (key === "mixcloud") return handle ? "https://www.mixcloud.com/" + handle : "";
  // bandcamp / spotify / resident_advisor / website: require a domain in the value
  return ensureHttps(v);
}

function socialToLinkItems(social, opts) {
  opts = opts || {};
  var out = [];
  if (!social || typeof social !== "object") return out;
  var entityName = String(opts.entityName || "");
  Object.keys(CATEGORY_BY_KEY).forEach(function (key) {
    var url = urlForKey(key, social[key]);
    if (!url) return;
    out.push({
      url: url,
      public_category: CATEGORY_BY_KEY[key],
      platform: key === "ra" ? "residentadvisor" : key,
      entity_name: entityName,
      entity_search_id: entityName,
      miniapp_display_allowed_candidate: true,
      confidence_band: "high",
      confidence_score: 90,
      source_ref: String(opts.sourceRef || ""),
    });
  });
  return out;
}

module.exports = {
  CATEGORY_BY_KEY: CATEGORY_BY_KEY,
  socialToLinkItems: socialToLinkItems,
  urlForKey: urlForKey,
};
