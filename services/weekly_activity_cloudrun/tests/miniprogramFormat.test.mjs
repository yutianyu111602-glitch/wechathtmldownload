import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

function loadMiniProgramFormat() {
  const testDir = path.dirname(fileURLToPath(import.meta.url));
  const repoRoot = path.resolve(testDir, "../../..");
  const filePath = path.resolve(repoRoot, "apps/weekly_activity_miniprogram/utils/format.js");
  const code = fs.readFileSync(filePath, "utf8");
  const sandbox = { module: { exports: {} }, exports: {} };
  vm.runInNewContext(code, sandbox, { filename: filePath });
  return sandbox.module.exports;
}

test("cleans listing titles and does not render venue lines as DJ bio", () => {
  const { compactItem } = loadMiniProgramFormat();
  const item = compactItem({
    title: "「今晚」OONOO CLUB｜BLUE SHIFT / 蓝色偏移",
    account: "OONOO",
    promoter: "OONOO",
    event_date_iso_guess: "2026-05-03",
    city: [],
    city_key: "unknown",
    venue: ["OONOO CLUB"],
    lineup: ["OONOO CLUB", "OONOO"],
    evidence: [
      "「今晚」OONOO CLUB｜BLUE SHIFT / 蓝色偏移",
      "OONOO CLUB",
      "BLUE SHIFT / 蓝色偏移",
      "2021年独立发行《BLUE XTC》",
      "公众号: OONOO",
    ],
  });

  assert.equal(item.displayTitle, "BLUE SHIFT / 蓝色偏移");
  assert.equal(item.detailMetaLine, "2026-05-03");
  assert.equal(item.hasLineup, false);
  assert.equal(item.hasBio, false);
});

test("keeps real artist bio and removes club names from lineup", () => {
  const { compactItem } = loadMiniProgramFormat();
  const item = compactItem({
    title: "05.03 今晚｜Golden Week & Third Month Fair 复古夜行",
    account: "POOLS",
    promoter: "POOLS",
    event_date_iso_guess: "2026-05-03",
    city: ["上海"],
    city_key: "shanghai",
    venue: [],
    lineup: ["POOLS", "Akupunktur"],
    evidence: [
      "POOLS 将这一晚交给更复古、更原始的舞曲能量",
      "公众号: POOLS",
      "作为 Dj、设计师、表演者和派对发起人，Akupunktur 在十多年前就积极参与推出了上海另类场景。",
    ],
  });

  assert.equal(item.displayTitle, "Golden Week & Third Month Fair 复古夜行");
  assert.equal(item.lineupLabel, "Akupunktur");
  assert.deepEqual(item.bioLines, [
    "作为 Dj、设计师、表演者和派对发起人，Akupunktur 在十多年前就积极参与推出了上海另类场景。",
  ]);
});

test("filters operational facts out of description copy", () => {
  const { compactItem } = loadMiniProgramFormat();
  const item = compactItem({
    id: "gum-a",
    title: "0509 Sat. | Concerta Pres.「秘术 VOL.2」",
    title_display: "0509 Sat. | Concerta Pres.「秘术 VOL.2」",
    account: "GUM Guangzhou",
    promoter: "GUM Guangzhou",
    event_date_iso_guess: "2026-05-09",
    event_time_text: "22:00",
    city: ["广州"],
    city_key: "guangzhou",
    venue_name: "GUM Guangzhou",
    address_full: "广州市海珠区工业大道132号T.I.T文创园45栋104 GUM",
    cover_image_url: "https://mmbiz.qpic.cn/example/gum.jpg",
    description_original_lines: [
      "⏰时间：22:00 - Till late",
      "🎫预售/pre-sell ¥68",
      "地点:广州市海珠区工业大道132号T.I.T文创园45栋104 GUM",
      "以节奏为引线，声波再度觉醒 🔮🎚️",
    ],
  });

  assert.equal(item.coverUrl, "https://mmbiz.qpic.cn/example/gum.jpg");
  assert.deepEqual(item.descriptionLines, ["以节奏为引线，声波再度觉醒 🔮🎚️"]);
});

test("does not require post_date for card display fields", () => {
  const { compactItem } = loadMiniProgramFormat();
  const item = compactItem({
    id: "stage7-unknown-post-date",
    title: "Stage7 Staging Unknown Publish Time",
    account: "Stage7",
    promoter: "Stage7",
    post_date: "",
    publish_time_status: "unknown",
    event_date_iso_guess: "2026-05-14",
    city: ["上海"],
    city_key: "shanghai",
    lineup: ["DJ A"],
    evidence: ["DJ A all night"],
  });

  assert.equal(item.dateLabel, "2026-05-14");
  assert.equal(item.dateCompact, "05.14");
  assert.equal(item.detailMetaLine, "上海 · 2026-05-14");
  assert.equal(item.displayTitle, "Stage7 Staging Unknown Publish Time");
});
