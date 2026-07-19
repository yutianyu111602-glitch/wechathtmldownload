// Pure GCJ-02 nearest-city lookup — no wx dependency
var CITY_CENTERS = [
  { key: "beijing",   lat: 39.909, lng: 116.397 },
  { key: "shanghai",  lat: 31.228, lng: 121.474 },
  { key: "guangzhou", lat: 23.129, lng: 113.264 },
  { key: "shenzhen",  lat: 22.543, lng: 114.058 },
  { key: "chengdu",   lat: 30.572, lng: 104.066 },
  { key: "hangzhou",  lat: 30.274, lng: 120.155 },
  { key: "chongqing", lat: 29.563, lng: 106.551 },
  { key: "nanjing",   lat: 32.060, lng: 118.796 },
  { key: "changsha",  lat: 28.228, lng: 112.939 },
  { key: "wuhan",     lat: 30.593, lng: 114.305 },
  { key: "xian",      lat: 34.343, lng: 108.940 },
  { key: "tianjin",   lat: 39.084, lng: 117.200 },
  { key: "xiamen",    lat: 24.479, lng: 118.089 },
  { key: "foshan",    lat: 23.027, lng: 113.122 },
  { key: "dali",      lat: 25.606, lng: 100.267 },
  { key: "kunming",   lat: 25.046, lng: 102.706 },
  { key: "qingdao",   lat: 36.067, lng: 120.383 },
  { key: "jinan",     lat: 36.651, lng: 117.120 },
  { key: "zhengzhou", lat: 34.746, lng: 113.625 },
  { key: "hefei",     lat: 31.820, lng: 117.227 },
  { key: "nanchang",  lat: 28.682, lng: 115.858 },
  { key: "fuzhou",    lat: 26.075, lng: 119.296 },
  { key: "ningbo",    lat: 29.868, lng: 121.544 },
  { key: "suzhou",    lat: 31.299, lng: 120.585 },
  { key: "wenzhou",   lat: 28.016, lng: 120.672 },
  { key: "guiyang",   lat: 26.647, lng: 106.630 },
  { key: "haikou",    lat: 20.044, lng: 110.199 },
  { key: "sanya",     lat: 18.252, lng: 109.512 },
  { key: "macau",     lat: 22.197, lng: 113.543 },
  { key: "hongkong",  lat: 22.352, lng: 114.135 },
  // Provincial capitals + observed activity cities not covered above, so their
  // local feeds also get boosted. GCJ-02 city centers (the ~500m WGS offset is
  // negligible against MAX_MATCH_KM=80).
  { key: "harbin",       lat: 45.803, lng: 126.534 },
  { key: "changchun",    lat: 43.817, lng: 125.324 },
  { key: "shenyang",     lat: 41.805, lng: 123.431 },
  { key: "dalian",       lat: 38.914, lng: 121.615 },
  { key: "daqing",       lat: 46.589, lng: 125.104 },
  { key: "shijiazhuang", lat: 38.043, lng: 114.515 },
  { key: "taiyuan",      lat: 37.870, lng: 112.548 },
  { key: "hohhot",       lat: 40.842, lng: 111.750 },
  { key: "lanzhou",      lat: 36.061, lng: 103.834 },
  { key: "xining",       lat: 36.617, lng: 101.778 },
  { key: "yinchuan",     lat: 38.487, lng: 106.231 },
  { key: "urumqi",       lat: 43.825, lng: 87.617 },
  { key: "lhasa",        lat: 29.647, lng: 91.117 },
  { key: "nanning",      lat: 22.817, lng: 108.366 },
];

var MAX_MATCH_KM = 80;

function distKm(lat1, lng1, lat2, lng2) {
  var dLat = (lat1 - lat2) * 111;
  var midLat = (lat1 + lat2) / 2 * Math.PI / 180;
  var dLng = (lng1 - lng2) * 111 * Math.cos(midLat);
  return Math.sqrt(dLat * dLat + dLng * dLng);
}

function nearestCityKey(lat, lng) {
  if (typeof lat !== "number" || typeof lng !== "number") return "";
  var best = "";
  var bestDist = MAX_MATCH_KM;
  for (var i = 0; i < CITY_CENTERS.length; i++) {
    var c = CITY_CENTERS[i];
    var d = distKm(lat, lng, c.lat, c.lng);
    if (d < bestDist) {
      bestDist = d;
      best = c.key;
    }
  }
  return best;
}

module.exports = { nearestCityKey: nearestCityKey };
