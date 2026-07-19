// 自检：searchEvents 为活动卡片（event-list 原子组件）准备的数据形态。
// 纯 node 运行，注入 options.items 跳过 wx.request。
const assert = require("assert");
const searchEvents = require("../ai_packages/weekly/weekly-events-skill/apis/searchEvents");

(async () => {
  const items = [
    {
      id: "e1",
      title: "Techno Night",
      city: "上海",
      venue: "ALL Club",
      event_date_start: "2026-06-25",
      lineup: ["DJ A", "DJ B"],
      coverUrl: "https://cdn.example.com/p1.jpg",
    },
    {
      id: "e2",
      title: "House Day",
      city: "北京",
      venue: "招待所",
      event_date_start: "2026-06-26",
      posterFileId: "cloud://env-x.appid/posters/p2.png",
    },
    {
      id: "e3",
      title: "No Poster Show",
      city: "成都",
      venue: ".TAG",
      event_date_start: "2026-06-27",
    },
  ];

  const res = await searchEvents({ limit: 10 }, { items, now: new Date("2026-06-24T12:00:00+08:00") });

  assert.strictEqual(res.isError, false, "should not error");
  assert.strictEqual(res.structuredContent.total, 3, "all 3 match (no date filter)");
  assert.strictEqual(res.structuredContent.events.length, 3, "3 public events");
  assert.ok(res._meta && res._meta.posters, "_meta.posters present");

  // https 直链原样保留
  assert.strictEqual(res._meta.posters.e1, "https://cdn.example.com/p1.jpg", "https cover kept");
  // cloud:// fileId 转成 tcb 公网 https
  assert.strictEqual(res._meta.posters.e2, "https://env-x.tcb.qcloud.la/posters/p2.png", "cloud fileId -> https");
  // 无海报的活动不进 posters，但仍在卡片数据里（卡片显示占位）
  assert.strictEqual(res._meta.posters.e3, undefined, "no poster -> no entry");
  assert.ok(res.structuredContent.events.some((e) => e.id === "e3"), "e3 still rendered in card");

  // 事实 + 动作两段式：有结果时 content 引导出卡片
  assert.ok(/卡片/.test(res.content[0].text), "content guides card render");

  // 空结果分支：不应携带误导性卡片引导
  const empty = await searchEvents({ city: "不存在城市", limit: 10 }, { items, now: new Date("2026-06-24T12:00:00+08:00") });
  assert.strictEqual(empty.structuredContent.total, 0, "no match");
  assert.ok(!/请用活动卡片/.test(empty.content[0].text), "empty result has no card-render directive");

  console.log("ai-skill-event-list self-check OK");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
