// Pure ES5. Groups a flat DJ outlink list into role→platform→{primary,more} structure.
// Input: [{url, platform, role, label, ...}] from backend externalLinksForDj DTO.
// Output: role-sorted array, each entry has { role, roleLabel, platforms[] }.
// Each platform entry: { platform, platformLabel, primary, more[], moreCount, total }.

var ROLE_ORDER = { listen: 1, profile: 2, social: 3, video: 4, interview: 5, radio: 6, source: 7 };

var ROLE_LABELS = {
  zh: { listen: "去听", profile: "主页", social: "社交", video: "视频", interview: "采访", radio: "电台", source: "来源" },
  en: { listen: "Listen", profile: "Profile", social: "Social", video: "Video", interview: "Interview", radio: "Radio", source: "Source" },
};

var PLATFORM_LABELS = {
  soundcloud: "SoundCloud", bandcamp: "Bandcamp", mixcloud: "Mixcloud",
  instagram: "Instagram", youtube: "YouTube", beatport: "Beatport",
  linktree: "Linktree", facebook: "Facebook", twitter: "Twitter",
  ra: "Resident Advisor", residentadvisor: "Resident Advisor", resident_advisor: "Resident Advisor",
  spotify: "Spotify", applemusic: "Apple Music", apple_music: "Apple Music",
  bilibili: "B站", weibo: "微博", xiaohongshu: "小红书", netease: "网易云",
};

// Classify a URL as an "account/profile" page vs a "deep link" (track/album/show).
// Used to pick the primary display URL for each role+platform group.
function isAccountUrl(url, platform) {
  var p = String(platform || "").toLowerCase();
  var u = String(url || "");
  try {
    // Parse without relying on globalThis.URL — works in WeChat JS engine too.
    var withoutHash = u.split("#")[0].split("?")[0];
    var afterProto = withoutHash.replace(/^https?:\/\//i, "");
    var slashIdx = afterProto.indexOf("/");
    var pathname = slashIdx === -1 ? "" : afterProto.slice(slashIdx);
    var segments = pathname.replace(/^\/+|\/+$/g, "").split("/").filter(function(s) { return s.length > 0; });

    if (p === "bandcamp") {
      // subdomain.bandcamp.com → 0 path segments → account
      // subdomain.bandcamp.com/album/... or /track/... or /music or /community → deep
      if (segments.length === 0) return true;
      var first = segments[0].toLowerCase();
      return first !== "album" && first !== "track" && first !== "music" && first !== "community" && first !== "releases";
    }
    if (p === "soundcloud") {
      // soundcloud.com/handle → 1 segment → account
      // soundcloud.com/handle/track-name or /popular-tracks etc. → 2+ segments → deep
      return segments.length <= 1;
    }
    if (p === "mixcloud") {
      // mixcloud.com/handle → 1 segment → account
      // mixcloud.com/handle/show-name → 2+ segments → deep
      // mixcloud.com/handle/stream → treat as account (it's the feed)
      if (segments.length <= 1) return true;
      return segments[1].toLowerCase() === "stream";
    }
    if (p === "beatport") {
      // beatport.com/artist/slug/id → 3 segments → account
      // /artist/slug/id/charts or /tracks or /releases → 4+ segments → deep
      return segments.length <= 3;
    }
    if (p === "youtube") {
      // youtube.com/watch?v= → deep (caught by ? strip above, path stays /watch)
      // youtube.com/@handle or /c/name or /channel/id → account
      if (segments.length === 0) return true;
      var ytFirst = segments[0].toLowerCase();
      return ytFirst.charAt(0) === "@" || ytFirst === "c" || ytFirst === "channel" || ytFirst === "user";
    }
    // instagram / linktree / facebook / twitter / ra / spotify / website:
    // single path-segment = handle = account
    return segments.length <= 1;
  } catch (e) {
    return true;
  }
}

function groupOutlinks(links, lang) {
  var l = lang === "en" ? "en" : "zh";
  // role → platform → { primary, more[] }
  var roleMap = {};

  for (var i = 0; i < (links || []).length; i++) {
    var lk = links[i];
    if (!lk || !lk.url || !lk.role || !lk.platform) continue;
    var role = String(lk.role).toLowerCase();
    var platform = String(lk.platform).toLowerCase();
    if (!ROLE_ORDER[role]) continue;  // skip unknown roles

    if (!roleMap[role]) roleMap[role] = {};
    if (!roleMap[role][platform]) roleMap[role][platform] = { primary: null, more: [] };

    var bucket = roleMap[role][platform];
    var item = { url: lk.url, label: lk.label || lk.url };

    if (!bucket.primary && isAccountUrl(lk.url, platform)) {
      bucket.primary = item;
    } else {
      bucket.more.push(item);
    }
  }

  var roleKeys = Object.keys(roleMap).sort(function(a, b) {
    return (ROLE_ORDER[a] || 99) - (ROLE_ORDER[b] || 99);
  });

  var result = [];
  for (var ri = 0; ri < roleKeys.length; ri++) {
    var role = roleKeys[ri];
    var platformMap = roleMap[role];
    var platformKeys = Object.keys(platformMap).sort();
    var platforms = [];

    for (var pi = 0; pi < platformKeys.length; pi++) {
      var plat = platformKeys[pi];
      var bkt = platformMap[plat];
      // If no account URL found, promote first deep link to primary
      var primary = bkt.primary || (bkt.more.length > 0 ? bkt.more.shift() : null);
      if (!primary) continue;
      platforms.push({
        platform: plat,
        platformLabel: PLATFORM_LABELS[plat] || plat,
        primary: primary,
        more: bkt.more,
        moreCount: bkt.more.length,
        total: 1 + bkt.more.length,
      });
    }

    if (!platforms.length) continue;
    result.push({
      role: role,
      roleLabel: ROLE_LABELS[l][role] || role,
      platforms: platforms,
    });
  }

  return result;
}

module.exports = { groupOutlinks: groupOutlinks, isAccountUrl: isAccountUrl };
