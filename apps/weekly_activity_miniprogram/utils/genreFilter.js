// utils/genreFilter.js
// JS mirror of tools/atlas_rebuild/genre_filter.py — keep underground electronic,
// drop obviously non-electronic items from the feed. Substring keyword allowlist,
// no API. ES5 (WeChat sandbox), pure functions.
// ponytail: same ceiling as the python ("house" matches "warehouse"); keep the two
// keyword sets in sync. Electronic wins over non-electronic (a techno+jazz bill stays).

var ELECTRONIC = [
  "techno", "house", "trance", "dnb", "drum and bass", "dubstep", "bass music",
  "ambient", "experimental", "electro", "acid", "breakbeat", "breaks", "hardgroove",
  "psytrance", "goa", "downtempo", "idm", "minimal", "deep house", "tech house",
  "disco", "italo", "ebm", "industrial", "gabber", "hardcore", "garage", "ukg",
  "jungle", "footwork", "juke", "leftfield", "electronic", "club night", "rave",
  "afterhours", "wave", "synth", "modular", "edm", "hard techno", "progressive house",
  "电子", "浩室", "铁克诺", "锐舞", "实验音乐", "氛围", "迷幻电子",
];

var NON_ELECTRONIC = [
  "民谣", "folk", "摇滚乐队", "rock band", "乐队专场", "说唱专场", "rap show",
  "爵士现场", "jazz night", "婚礼", "wedding", "相声", "脱口秀", "stand-up",
  "古典", "classical", "合唱", "民歌", "流行演唱会",
  "hiphop", "hip-hop", "嘻哈", "说唱", "rap", "jazz", "爵士", "rock", "摇滚",
  "乐队", "post-rock", "后摇", "器乐摇滚", "math rock", "instrumental rock",
  "punk", "朋克", "emo", "pop", "流行", "film", "screening", "放映",
  "tango", "acg", "funk", "swing",
  // non-music-event class that leaked into the feed (mirror in genre_filter.py):
  "鸡尾酒", "cocktail", "酒节", "市集", "漫展", "喜剧", "comedy",
  "长笛", "flute", "话剧", "音乐剧", "脱口秀大会",
];

function genreOf(stylesList, textBlob) {
  var blob = ((Array.isArray(stylesList) ? stylesList.join(" ") : "") + " " + (textBlob || "")).toLowerCase();
  var blobE = blob.replace(/non[_ -]?electronic/g, " ");
  for (var i = 0; i < ELECTRONIC.length; i++) {
    if (blobE.indexOf(ELECTRONIC[i]) !== -1) return "electronic";
  }
  for (var j = 0; j < NON_ELECTRONIC.length; j++) {
    if (blob.indexOf(NON_ELECTRONIC[j]) !== -1) return "non_electronic";
  }
  return "unknown";
}

function itemGenreOf(item) {
  if (!item || typeof item !== "object") return "unknown";
  var styles = []
    .concat(Array.isArray(item.genres) ? item.genres : [])
    .concat(Array.isArray(item.music_styles) ? item.music_styles : [])
    .concat(Array.isArray(item.styles) ? item.styles : [])
    .concat(item.styleLabel ? [item.styleLabel] : [])
    .concat(item.genre ? [item.genre] : []);
  var title = String(item.displayTitle || item.title || item.title_display || item.title_original || "");
  return genreOf(styles, title);
}

// Drop only confidently non-electronic items; keep "electronic" and "unknown"
// (poster-only / no style signal must not be over-dropped).
function filterItemsByElectronic(items) {
  var source = Array.isArray(items) ? items : [];
  return source.filter(function (item) { return itemGenreOf(item) !== "non_electronic"; });
}

module.exports = {
  ELECTRONIC: ELECTRONIC,
  NON_ELECTRONIC: NON_ELECTRONIC,
  genreOf: genreOf,
  itemGenreOf: itemGenreOf,
  filterItemsByElectronic: filterItemsByElectronic,
};
