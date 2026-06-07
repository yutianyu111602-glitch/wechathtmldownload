const STYLE_RULES = [
  { label: "techno", aliases: ["techno", "industrial techno", "工业techno", "工业科技舞曲"] },
  { label: "house", aliases: ["house", "浩室", "deep house", "afro house", "progressive house", "tech house"] },
  { label: "hip-hop", aliases: ["hiphop", "hip hop", "hip-hop", "说唱", "嘻哈", "rap", "trap", "drill", "boom bap"] },
  { label: "bass", aliases: ["bass", "低音", "uk bass", "bass music", "dubstep", "garage", "ukg", "grime", "footwork", "juke", "jungle"] },
  { label: "drum & bass", aliases: ["drum and bass", "drum&bass", "dnb", "d&b", "liquid dnb", "neurofunk"] },
  { label: "electro", aliases: ["electro", "电子放克", "electroclash"] },
  { label: "breaks", aliases: ["breakbeat", "breaks", "碎拍"] },
  { label: "trance", aliases: ["trance", "psytrance", "psy trance"] },
  { label: "disco", aliases: ["disco", "迪斯科", "nu-disco", "italo disco", "boogie"] },
  { label: "ambient", aliases: ["ambient", "氛围", "drone", "experimental ambient"] },
  { label: "industrial", aliases: ["industrial", "工业", "noise", "power electronics", "ebm"] },
  { label: "dub", aliases: ["dub", "dub reggae", "steppers"] },
  { label: "reggae", aliases: ["reggae", "dancehall", "ska", "rocksteady"] },
  { label: "funk", aliases: ["funk", "放克", "soul", "r&b", "rnb", "rhythm and blues"] },
  { label: "jazz", aliases: ["jazz", "free jazz", "spiritual jazz"] },
  { label: "4x4", aliases: ["4x4", "four on the floor", "four-on-the-floor"] },
  { label: "club trax", aliases: ["club trax", "club tracks", "club music", "club edits", "club edit"] },
  { label: "leftfield", aliases: ["leftfield", "experimental", "avant-garde", "experimental electronic"] },
  { label: "post-punk", aliases: ["post-punk", "post punk", "darkwave", "coldwave", "goth"] },
  { label: "hardcore", aliases: ["hardcore", "hardstyle", "gabber", "speedcore", "happy hardcore"] },
  { label: "pop", aliases: ["pop", "synthpop", "electropop", "dream pop", "indie pop"] },
  { label: "rock", aliases: ["rock", "indie rock", "psych rock", "krautrock"] },
  { label: "world", aliases: ["world", "afrobeat", "latin", "cumbia", "baile funk", "reggaeton"] },
  { label: "minimal", aliases: ["minimal", "minimal techno", "microhouse"] },
  { label: "acid", aliases: ["acid", "acid house", "acid techno", "acid trance", "303"] },
];

const NON_ARTIST_LINEUP_NAMES = [
  "aurora", "aurorabj", "lineup", "support", "nighttour", "夜游", "阵容",
];

const TRUSTED_TIME_SOURCES = [
  "source_text", "article_text", "official_text",
  "poster_ocr", "poster_text", "manual_verified",
];

module.exports = { STYLE_RULES, NON_ARTIST_LINEUP_NAMES, TRUSTED_TIME_SOURCES };
