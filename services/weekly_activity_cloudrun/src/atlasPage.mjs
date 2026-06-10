export function renderAtlasPage() {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>中国地下电子音乐图鉴</title>
  <style>
    :root{--bg:#f6f4ef;--fg:#171714;--muted:#6c675f;--line:#d7d0c5;--panel:#fffdf8;--ink:#111;--green:#1f6f55;--red:#b44d3d;--yellow:#c3952d;--blue:#285d75}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);font-family:"Inter","Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0}
    a{color:inherit;text-decoration:none}
    button,input{font:inherit}
    .shell{min-height:100vh}
    header{border-bottom:1px solid var(--line);background:#fffaf0}
    .bar{max-width:1480px;margin:0 auto;padding:18px 24px;display:grid;grid-template-columns:minmax(260px,1fr) auto;gap:18px;align-items:center}
    .brand{display:flex;gap:16px;align-items:center;min-width:0}
    .brand img{width:144px;height:36px;object-fit:contain;background:#111;border-radius:4px;padding:5px}
    h1{margin:0;font-size:28px;line-height:1.08;font-weight:760}
    .sub{margin-top:5px;color:var(--muted);font-size:13px}
    .status{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
    .pill{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:7px 10px;font-size:12px;color:#3f3a34;white-space:nowrap}
    .pill strong{color:var(--ink)}
    main{max-width:1480px;margin:0 auto;padding:22px 24px 42px}
    .metrics{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin-bottom:18px}
    .metric{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:14px 14px 12px}
    .metric span{display:block;color:var(--muted);font-size:12px}
    .metric strong{display:block;margin-top:8px;font-size:24px;line-height:1}
    .toolbar{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;margin-bottom:18px}
    .search{display:flex;border:1px solid var(--line);background:var(--panel);border-radius:8px;overflow:hidden}
    .search input{width:100%;border:0;background:transparent;padding:13px 14px;outline:0;color:var(--fg)}
    .search button{border:0;border-left:1px solid var(--line);background:#171714;color:#fff;padding:0 18px;cursor:pointer}
    .tabs{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
    .tab{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:10px 12px;color:#3f3a34;cursor:pointer}
    .tab[aria-pressed="true"]{background:#171714;color:#fff;border-color:#171714}
    .layout{display:grid;grid-template-columns:minmax(260px,360px) minmax(0,1fr);gap:16px}
    aside,.panel{border:1px solid var(--line);background:var(--panel);border-radius:8px}
    aside{padding:16px;align-self:start;position:sticky;top:14px}
    .panel{padding:16px;min-width:0}
    h2{margin:0 0 14px;font-size:16px;line-height:1.2}
    .facet{display:grid;gap:8px}
    .facet-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;border-bottom:1px solid #ebe5da;padding:8px 0;font-size:13px}
    .facet-row:last-child{border-bottom:0}
    .facet-row span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .count{color:var(--muted)}
    .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
    .wide{grid-column:1 / -1}
    .list{display:grid;gap:10px}
    .item{border:1px solid #e4ddd2;border-radius:8px;background:#fff;padding:12px;min-width:0}
    .item b{display:block;font-size:15px;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .item b a{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
    .item p{margin:7px 0 0;color:var(--muted);font-size:12px;line-height:1.45}
    .item .tag{display:inline-block;margin:8px 6px 0 0;border:1px solid #e3d8c5;border-radius:999px;padding:4px 7px;color:#5c554b;font-size:11px}
    .map-band{height:178px;border:1px solid #ded6c9;border-radius:8px;background:linear-gradient(135deg,#f8f3e8,#eaf1ea 48%,#f3e7dc);position:relative;overflow:hidden;margin-bottom:12px}
    .map-band:before{content:"";position:absolute;inset:20px 26px;border:1px solid rgba(31,111,85,.28);border-radius:42% 58% 45% 55%;transform:rotate(-8deg)}
    .map-dot{position:absolute;width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 0 6px rgba(31,111,85,.13)}
    .dot-a{left:70%;top:54%}.dot-b{left:50%;top:38%;background:var(--red);box-shadow:0 0 0 6px rgba(180,77,61,.13)}.dot-c{left:58%;top:64%;background:var(--yellow);box-shadow:0 0 0 6px rgba(195,149,45,.15)}.dot-d{left:76%;top:30%;background:var(--blue);box-shadow:0 0 0 6px rgba(40,93,117,.13)}
    .empty{color:var(--muted);font-size:13px;padding:14px;border:1px dashed var(--line);border-radius:8px}
    .foot{margin-top:18px;color:var(--muted);font-size:12px}
    @media (max-width:980px){.bar{grid-template-columns:1fr}.status{justify-content:flex-start}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar{grid-template-columns:1fr}.tabs{justify-content:flex-start}.layout{grid-template-columns:1fr}aside{position:relative;top:0}.grid{grid-template-columns:1fr}}
    @media (max-width:560px){.bar,main{padding-left:14px;padding-right:14px}.brand{align-items:flex-start;flex-direction:column}.brand img{width:128px}.metrics{grid-template-columns:1fr}h1{font-size:24px}.search{display:block}.search button{width:100%;border-left:0;border-top:1px solid var(--line);padding:12px}}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="bar">
        <div class="brand">
          <img src="/assets/huaidj-logo-nav-512x128.png" alt="HUAIDJ">
          <div>
            <h1>中国地下电子音乐图鉴</h1>
            <div class="sub" id="releaseLine">Atlas product surface</div>
          </div>
        </div>
        <div class="status" id="statusPills"></div>
      </div>
    </header>
    <main>
      <section class="metrics" id="metrics"></section>
      <section class="toolbar">
        <form class="search" id="searchForm">
          <input id="searchInput" name="q" autocomplete="off" placeholder="DADA / OIL / DJ / label / city">
          <button type="submit">Search</button>
        </form>
        <nav class="tabs" id="tabs" aria-label="Atlas views">
          <button class="tab" type="button" data-view="overview" aria-pressed="true">总览</button>
          <button class="tab" type="button" data-view="map" aria-pressed="false">地图</button>
          <button class="tab" type="button" data-view="people" aria-pressed="false">人物</button>
          <button class="tab" type="button" data-view="labels" aria-pressed="false">厂牌</button>
          <button class="tab" type="button" data-view="scenes" aria-pressed="false">场景</button>
          <button class="tab" type="button" data-view="evidence" aria-pressed="false">证据</button>
          <a class="tab" href="/atlas/identity">身份</a>
        </nav>
      </section>
      <section class="layout">
        <aside>
          <h2>地图</h2>
          <div class="map-band" aria-hidden="true"><span class="map-dot dot-a"></span><span class="map-dot dot-b"></span><span class="map-dot dot-c"></span><span class="map-dot dot-d"></span></div>
          <div class="facet" id="cityFacet"></div>
        </aside>
        <div class="grid" id="content"></div>
      </section>
      <div class="foot" id="footnote"></div>
    </main>
  </div>
  <script>
    const state = { overview: null, view: "overview", searchResults: [] };
    const fmt = new Intl.NumberFormat("en-US");
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    async function fetchJson(path) {
      const res = await fetch(path, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(path + " " + res.status);
      return res.json();
    }
    function detailId(kind, item) {
      if (!item) return "";
      if (kind === "articles") return item.article_id || item.article_uid || "";
      if (kind === "entities") return item.eid || "";
      return item.evid || "";
    }
    function detailHref(kind, item) {
      const id = detailId(kind, item);
      return id ? "/atlas/" + kind + "/" + encodeURIComponent(id) : "";
    }
    function setView(view) {
      state.view = view;
      document.querySelectorAll(".tab").forEach((tab) => tab.setAttribute("aria-pressed", String(tab.dataset.view === view)));
      render();
    }
    function metric(label, value, tone) {
      return '<div class="metric"><span>' + esc(label) + '</span><strong style="color:' + tone + '">' + esc(value) + '</strong></div>';
    }
    function itemCard(title, meta, tags = [], href = "") {
      const tagHtml = tags.filter(Boolean).slice(0, 4).map((tag) => '<span class="tag">' + esc(tag) + '</span>').join("");
      const titleHtml = href ? '<a href="' + esc(href) + '">' + esc(title || "Untitled") + '</a>' : esc(title || "Untitled");
      return '<article class="item"><b>' + titleHtml + '</b><p>' + esc(meta || "") + '</p>' + tagHtml + '</article>';
    }
    function renderFacet(rows) {
      if (!rows || !rows.length) return '<div class="empty">No city facets</div>';
      return rows.slice(0, 10).map((row) => '<div class="facet-row"><span>' + esc(row.label) + '</span><b class="count">' + fmt.format(row.count || 0) + '</b></div>').join("");
    }
    function surface(id) {
      return (state.overview.browsingSurfaces || []).find((item) => item.id === id) || {};
    }
    function renderList(title, rows, toCard) {
      const body = rows && rows.length ? rows.map(toCard).join("") : '<div class="empty">No rows in this sample</div>';
      return '<section class="panel"><h2>' + esc(title) + '</h2><div class="list">' + body + '</div></section>';
    }
    function render() {
      if (!state.overview) return;
      const o = state.overview;
      const counts = o.counts || {};
      document.getElementById("releaseLine").textContent = (o.release?.decision || "release") + " · " + (o.release?.generatedAt || "");
      document.getElementById("statusPills").innerHTML = [
        '<span class="pill">REMOTE <strong>' + esc(o.release?.channel || "stage7") + '</strong></span>',
        '<span class="pill">Search <strong>' + esc(o.serviceIntegration?.searchMode || "materialized") + '</strong></span>',
        '<span class="pill">Vector <strong>' + esc(o.vector?.decision || "report") + '</strong></span>',
      ].join("");
      document.getElementById("metrics").innerHTML = [
        metric("Articles", fmt.format(counts.articles || 0), "#171714"),
        metric("Entities", fmt.format(counts.entities || 0), "#1f6f55"),
        metric("Events", fmt.format(counts.events || 0), "#b44d3d"),
        metric("Unknown publish time", fmt.format(counts.missing_publish_time_articles || 0), "#285d75"),
      ].join("");
      const mapRows = (o.facets?.mapPlaces && o.facets.mapPlaces.length ? o.facets.mapPlaces : o.facets?.cities) || [];
      document.getElementById("cityFacet").innerHTML = renderFacet(mapRows);
      document.getElementById("footnote").textContent = "Read-only atlas browser. No LLM call, no vector write, no database mutation.";

      const samples = o.samples || {};
      const people = surface("people").samples || [];
      const labels = surface("labels").samples || [];
      const scenes = surface("scenes").samples || samples.events || [];
      const search = state.searchResults || [];
      const panels = [];
      if (search.length) {
        panels.push(renderList("Search results", search, (row) => itemCard(row.title, row.kind, [row.item?.source_account, row.item?.type, row.item?.place].filter(Boolean), detailHref(row.kind, row.item))));
      }
      if (state.view === "overview" || state.view === "map") {
        panels.push(renderList("地图 / 地点线索", mapRows, (row) => itemCard(row.label, fmt.format(row.count || 0) + " sampled links", ["place"])));
      }
      if (state.view === "overview" || state.view === "people") {
        panels.push(renderList("人物", people, (row) => itemCard(row.name || row.eid, row.city || row.source_article_uid, [row.type, row.confidence != null ? "confidence " + row.confidence : ""], detailHref("entities", row))));
      }
      if (state.view === "overview" || state.view === "labels") {
        panels.push(renderList("厂牌 / 组织", labels, (row) => itemCard(row.name || row.eid, row.city || row.source_article_uid, [row.type], detailHref("entities", row))));
      }
      if (state.view === "overview" || state.view === "scenes") {
        panels.push(renderList("场景 / 事件", scenes, (row) => itemCard(row.name || row.evid, row.place || row.time_text || row.source_article_uid, [row.time_iso, (row.participants || []).slice(0, 2).join(" / ")], detailHref("events", row))));
      }
      if (state.view === "overview" || state.view === "evidence") {
        panels.push(renderList("Graph RAG", o.graphRagAnswers || [], (row) => itemCard(row.query || row.id, row.answer || "", [(row.citations || []).length + " citations"])));
        panels.push(renderList("Recommendations", o.recommendations || [], (row) => itemCard(row.title || row.id, row.type || "", [row.score != null ? "score " + row.score : ""])));
      }
      document.getElementById("content").innerHTML = panels.join("");
    }
    document.getElementById("tabs").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-view]");
      if (button) setView(button.dataset.view);
    });
    document.getElementById("searchForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const q = document.getElementById("searchInput").value.trim();
      state.searchResults = q ? (await fetchJson("/api/v1/stage7/search?q=" + encodeURIComponent(q) + "&limit=12")).results || [] : [];
      render();
    });
    fetchJson("/api/v1/stage7/overview").then((overview) => {
      state.overview = overview;
      render();
    }).catch((error) => {
      document.getElementById("content").innerHTML = '<section class="panel wide"><h2>Load failed</h2><div class="empty">' + esc(error.message) + '</div></section>';
    });
  </script>
</body>
</html>`;
}
