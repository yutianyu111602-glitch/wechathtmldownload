// utils/footprintCard.js
// "我的 DJ 足迹" — aggregate the DJs a user has lit up (local, anonymous) into a
// shareable card model: how many DJs, which cities they collectively span, and the
// little network among those DJs. Pure, ES5. No backend — fed by the existing
// /atlas/artist DTO. Reuses cityFootprint for the city merge. See plan 101 #8.
var cf = require("./cityFootprint");

function norm(s) { return String(s || "").trim(); }
function keyOf(s) { return norm(s).toLowerCase(); }

// profiles: [{ name, city, events:[{city,date}], peers:[name...] }]
//   peers = the DJ's collaborators + similar DJs (display names).
// Returns { djCount, cityCount, topCities:[{city,count}], miniGraph:{nodes,edges} }.
function buildFootprintCard(profiles, topCityLimit) {
  profiles = profiles || [];
  topCityLimit = topCityLimit || 6;

  // Dedupe visited DJs by name (case-insensitive) first, so a repeated visit
  // neither double-counts cities nor doubles a node.
  var uniq = [];
  var byKey = {};
  for (var i = 0; i < profiles.length; i++) {
    var p = profiles[i] || {};
    var name = norm(p.name);
    if (!name || byKey[keyOf(name)]) continue;
    byKey[keyOf(name)] = name;
    uniq.push(p);
  }

  // City footprint across every visited DJ's events (fall back to profile.city
  // when a DJ has no event list).
  var allEvents = [];
  for (var u = 0; u < uniq.length; u++) {
    var evts = Array.isArray(uniq[u].events) ? uniq[u].events : [];
    if (evts.length) { for (var j = 0; j < evts.length; j++) allEvents.push(evts[j]); }
    else if (uniq[u].city) allEvents.push({ city: uniq[u].city });
  }
  var fp = cf.cityFootprint(allEvents);
  var topCities = [];
  for (var k = 0; k < fp.order.length && k < topCityLimit; k++) {
    topCities.push({ city: fp.order[k], count: fp.counts[fp.order[k]] });
  }

  // nodes = visited DJs; undirected edge when one lists another as a peer and
  // both are in the visited set (Ghost peers outside the set are dropped).
  var nodes = [];
  for (var nn = 0; nn < uniq.length; nn++) nodes.push({ id: norm(uniq[nn].name), label: norm(uniq[nn].name) });
  var edges = [];
  var edgeSeen = {};
  for (var a = 0; a < uniq.length; a++) {
    var an = norm(uniq[a].name);
    var peers = Array.isArray(uniq[a].peers) ? uniq[a].peers : [];
    for (var b = 0; b < peers.length; b++) {
      var bn = byKey[keyOf(peers[b])];
      if (!bn || keyOf(bn) === keyOf(an)) continue;
      var pair = keyOf(an) < keyOf(bn) ? keyOf(an) + "|" + keyOf(bn) : keyOf(bn) + "|" + keyOf(an);
      if (edgeSeen[pair]) continue;
      edgeSeen[pair] = 1;
      edges.push({ a: an, b: bn });
    }
  }

  return {
    djCount: nodes.length,
    cityCount: fp.order.length,
    topCities: topCities,
    miniGraph: { nodes: nodes, edges: edges },
  };
}

module.exports = { buildFootprintCard: buildFootprintCard };
