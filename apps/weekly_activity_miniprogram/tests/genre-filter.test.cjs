const { test } = require("node:test");
const assert = require("node:assert");
const { genreOf, filterItemsByElectronic } = require("../utils/genreFilter");

test("genreOf: electronic styles/titles are kept", () => {
  assert.equal(genreOf(["Techno"]), "electronic");
  assert.equal(genreOf(["House", "Disco"]), "electronic");
  assert.equal(genreOf([], "锐舞之夜 techno"), "electronic");
  assert.equal(genreOf(["电子"]), "electronic");
});

test("genreOf: non-electronic (incl. leaked non-music classes) is dropped", () => {
  assert.equal(genreOf(["jazz"]), "non_electronic");
  assert.equal(genreOf([], "张学友巡演首席 亚洲爵士长笛第一人 许凯翔 来啦!"), "non_electronic");
  assert.equal(genreOf([], "光芒·喜闻乐见 喜剧脱口秀"), "non_electronic");
  assert.equal(genreOf([], "重庆首届鸡尾酒节 端午见"), "non_electronic");
  assert.equal(genreOf(["rock"]), "non_electronic");
});

test("genreOf: electronic wins over non-electronic on a mixed bill", () => {
  assert.equal(genreOf(["techno", "jazz"]), "electronic");
});

test("genreOf: no genre signal -> unknown (kept, not dropped)", () => {
  assert.equal(genreOf([]), "unknown");
  assert.equal(genreOf(["未知风格"]), "unknown");
});

test("filterItemsByElectronic drops the screenshot cases, keeps electronic + unknown", () => {
  const items = [
    { id: "a", displayTitle: "FLAT GENERATION", genres: ["techno"] },
    { id: "b", displayTitle: "张学友巡演首席 亚洲爵士长笛第一人 许凯翔 来啦!" },
    { id: "c", displayTitle: "光芒·喜闻乐见 喜剧脱口秀" },
    { id: "d", displayTitle: "重庆首届鸡尾酒节 端午见" },
    { id: "e", displayTitle: "海报活动（无风格信号）" },
    { id: "f", displayTitle: "Night", music_styles: ["deep house"] },
  ];
  assert.deepEqual(filterItemsByElectronic(items).map((x) => x.id), ["a", "e", "f"]);
});
