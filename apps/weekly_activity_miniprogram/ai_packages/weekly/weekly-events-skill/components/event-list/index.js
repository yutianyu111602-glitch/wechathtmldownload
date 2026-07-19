// 原子组件：活动卡片（event-list）
// 承接 searchEvents 原子接口返回的 structuredContent.events，渲染成对话流里的横滑 GUI 卡片。
// 约束（官方运行机制）：非虚拟组件；仅 tap / image load|error 事件；无网络请求；高度初始化后固定；禁止 overflow-y。

function safeText(value) {
  return value === undefined || value === null ? "" : String(value).trim();
}

Component({
  data: {
    events: [],
    hint: "",
  },
  lifetimes: {
    created() {
      if (typeof wx === "undefined" || !wx.modelContext) return;
      const modelCtx = wx.modelContext.getContext(this);
      const { NotificationType } = wx.modelContext;
      this._viewCtx = wx.modelContext.getViewContext(this);

      modelCtx.on(NotificationType.Result, (data) => {
        const result = (data && data.result) || {};
        const structured = result.structuredContent || {};
        const meta = result._meta || {};
        const posters = meta.posters || {};
        const rawEvents = Array.isArray(structured.events) ? structured.events : [];

        const events = rawEvents.map((event) => ({
          id: safeText(event.id),
          title: safeText(event.title) || "未命名活动",
          line: [safeText(event.date), safeText(event.city), safeText(event.venue)].filter(Boolean).join(" · "),
          lineup: Array.isArray(event.lineup) ? event.lineup.slice(0, 3).join(" / ") : "",
          poster: safeText(posters[safeText(event.id)]),
        }));

        this.setData({
          events,
          hint: events.length ? "" : "当前没有匹配到可确认活动",
        });

        // 卡片右上角「进入小程序」入口：固定指向活动列表页（path 在 mcp.json relatedPage 声明），这里只补 query。
        const query = (structured.query || {});
        const city = safeText(query.city);
        this._viewCtx.setRelatedPage({ query: city ? `city=${encodeURIComponent(city)}` : "" });
      });
    },
  },
  methods: {
    onTapEvent(e) {
      const id = safeText(e.currentTarget.dataset.id);
      if (!id || !this._viewCtx || typeof this._viewCtx.openDetailPage !== "function") return;
      // 复用现有详情页，以半屏页面打开（详情页 onLoad 只取数据、不路由，半屏安全）。
      this._viewCtx.openDetailPage({ url: `/pages/detail/detail?id=${encodeURIComponent(id)}` });
    },
  },
});
