export function renderAtlasLocalPage() {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>本地图鉴数据库</title>
  <style>
    :root{--bg:#f6f4ef;--fg:#171714;--muted:#6c675f;--line:#d7d0c5;--panel:#fffdf8;--ink:#111;--green:#1f6f55;--red:#a8473a;--blue:#285d75;--amber:#9f7523}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);font-family:"Inter","Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0}
    a{color:inherit} button,input,select,textarea{font:inherit}
    header{border-bottom:1px solid var(--line);background:#fffaf0}
    .bar{max-width:1500px;margin:0 auto;padding:18px 24px;display:grid;grid-template-columns:minmax(260px,1fr) auto;gap:18px;align-items:center}
    .brand{display:flex;gap:16px;align-items:center;min-width:0}.brand img{width:144px;height:36px;object-fit:contain;background:#111;border-radius:4px;padding:5px}
    h1{margin:0;font-size:28px;line-height:1.08;font-weight:760}.sub{margin-top:5px;color:var(--muted);font-size:13px;overflow-wrap:anywhere;word-break:break-word}.brand>div{min-width:0}
    .nav{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.nav a{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:9px 11px;text-decoration:none;color:#3f3a34}.nav .active{background:#171714;color:#fff;border-color:#171714}
    main{max-width:1500px;margin:0 auto;padding:22px 24px 42px}
    .metrics{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));gap:10px;margin-bottom:16px}.metric{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:14px}.metric span{display:block;color:var(--muted);font-size:12px}.metric strong{display:block;margin-top:8px;font-size:22px;line-height:1}
    .toolbar{display:grid;grid-template-columns:minmax(220px,1fr) 150px auto;gap:10px;margin-bottom:16px}.toolbar input,.toolbar select{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:11px;color:var(--fg)}.toolbar button{border:0;background:#171714;color:#fff;border-radius:8px;padding:0 16px;cursor:pointer}
    .layout{display:grid;grid-template-columns:minmax(280px,390px) minmax(0,1fr);gap:16px}.panel{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:16px;min-width:0}.stack{display:grid;gap:16px}
    h2{margin:0 0 14px;font-size:16px;line-height:1.2}.map{height:280px;border:1px solid #ded6c9;border-radius:8px;background:#f8f3e8;position:relative;overflow:hidden}.dot{position:absolute;width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 0 6px rgba(31,111,85,.13)}
    .list{display:grid;gap:10px}.row{border:1px solid #e4ddd2;background:#fff;border-radius:8px;padding:12px;min-width:0}.row h3{margin:0;font-size:15px;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.row p{margin:7px 0 0;color:var(--muted);font-size:12px;line-height:1.45}.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.tag{border:1px solid #e3d8c5;border-radius:999px;padding:4px 7px;color:#5c554b;font-size:11px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .queue-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px}.geo-row{grid-template-columns:minmax(0,1fr)}.geo-row .actions{justify-content:flex-start}.actions{display:flex;gap:6px;flex-wrap:wrap;align-content:start;justify-content:flex-end}.actions button{border:1px solid var(--line);background:#fffdf8;border-radius:8px;padding:7px 9px;cursor:pointer}.actions button:disabled{opacity:.55;cursor:wait}.actions button[data-action="accept"]{border-color:#b7d8c5;color:var(--green)}.actions button[data-action="reject"]{border-color:#e1bbb3;color:var(--red)}.actions button[data-action="needs_more_source"]{border-color:#d7c18b;color:var(--amber)}.actions button[data-action="hold"],.actions button[data-action="review_only"]{border-color:#b7c6d8;color:var(--blue)}
    .empty{color:var(--muted);font-size:13px;padding:14px;border:1px dashed var(--line);border-radius:8px}.foot{margin-top:18px;color:var(--muted);font-size:12px}
    @media (max-width:1050px){.bar{grid-template-columns:1fr}.nav{justify-content:flex-start}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.layout{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr}.toolbar button{padding:11px}.queue-row{grid-template-columns:1fr}.actions{justify-content:flex-start}}
    @media (max-width:560px){.bar,main{padding-left:14px;padding-right:14px}.brand{align-items:flex-start;flex-direction:column}.brand img{width:128px}.metrics{grid-template-columns:1fr}h1{font-size:24px}}
  </style>
</head>
<body>
  <header><div class="bar"><div class="brand"><img src="/assets/huaidj-logo-nav-512x128.png" alt="HUAIDJ"><div><h1>本地图鉴数据库</h1><div class="sub" id="dbLine">SQLite explorer</div></div></div><nav class="nav"><a href="/atlas">图鉴</a><a href="/atlas/identity">身份</a><a class="active" href="/atlas/local">本地库</a><a href="/api/v1/stage7/local/status">API</a></nav></div></header>
  <main>
    <section class="metrics" id="metrics"></section>
    <section class="toolbar"><input id="q" autocomplete="off" placeholder="DADA / OIL / TAG / 北京 / 场景"><select id="kind"><option value="">All</option><option value="articles">Articles</option><option value="entities">Entities</option><option value="events">Events</option></select><button id="searchBtn" type="button">Search</button></section>
    <section class="layout">
      <div class="stack"><section class="panel"><h2>地图</h2><div class="map" id="map"></div></section><section class="panel"><h2>Geocode</h2><div class="list" id="places"></div></section><section class="panel"><h2>Geocode Review</h2><div class="list" id="geocodeReview"></div></section></div>
      <div class="stack"><section class="panel"><h2>Search</h2><div class="list" id="results"></div></section><section class="panel"><h2>Adjudication</h2><div class="list" id="queue"></div></section><section class="panel"><h2>Ledger</h2><div class="list" id="ledger"></div></section></div>
    </section>
    <div class="foot" id="footnote"></div>
  </main>
  <script>
    const state = { status:null, map:null, geocodeReview:null, search:null, identity:null, ledger:null };
    const fmt = new Intl.NumberFormat("en-US");
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[ch]));
    async function json(path, options) {
      const res = await fetch(path, options);
      const body = await res.json();
      if (!res.ok) throw new Error(body.error?.message || path + " " + res.status);
      return body;
    }
    function metric(label, value, color) { return '<div class="metric"><span>'+esc(label)+'</span><strong style="color:'+color+'">'+esc(value)+'</strong></div>'; }
    function row(title, meta, tags=[]) { return '<article class="row"><h3>'+esc(title||"Untitled")+'</h3><p>'+esc(meta||"")+'</p><div class="tags">'+tags.filter(Boolean).map((tag)=>'<span class="tag">'+esc(tag)+'</span>').join("")+'</div></article>'; }
    function renderStatus() {
      const s = state.status || {};
      const counts = s.manifest?.counts || {};
      const map = s.map || {};
      const adj = s.adjudication || {};
      const review = s.geocodeReview || {};
      document.getElementById("dbLine").textContent = s.dbPath || "STAGE7_ATLAS_SQLITE_DB";
      document.getElementById("metrics").innerHTML = [
        metric("Articles", fmt.format(counts.articles||0), "#171714"),
        metric("Entities", fmt.format(counts.entities||0), "#1f6f55"),
        metric("Events", fmt.format(counts.events||0), "#a8473a"),
        metric("Places", fmt.format(map.placeRows||0), "#285d75"),
        metric("Geocoded", fmt.format(map.geocodedRows||0), "#1f6f55"),
        metric("Geo review", fmt.format(review.reviewRows||0), "#285d75"),
        metric("Geo actions", fmt.format(review.actions||0), "#285d75"),
        metric("Adj actions", fmt.format(adj.actions||0), "#9f7523"),
      ].join("");
    }
    function renderMap() {
      const places = state.map?.places || [];
      const mapEl = document.getElementById("map");
      mapEl.innerHTML = places.filter((p)=>p.lat && p.lon).slice(0,80).map((p)=>{
        const left = Math.min(92, Math.max(8, ((Number(p.lon) - 73) / 62) * 100));
        const top = Math.min(92, Math.max(8, (1 - ((Number(p.lat) - 18) / 36)) * 100));
        return '<span class="dot" title="'+esc(p.label)+'" style="left:'+left+'%;top:'+top+'%"></span>';
      }).join("");
      document.getElementById("places").innerHTML = places.slice(0,10).map((p)=>row(p.label, [p.city, p.geocodeStatus, "events "+fmt.format(p.eventCount||0)].filter(Boolean).join(" · "), [p.precision, p.sampleArticleUid])).join("") || '<div class="empty">No geocoded rows</div>';
    }
    function renderGeocodeReview() {
      const items = state.geocodeReview?.items || [];
      document.getElementById("geocodeReview").innerHTML = items.slice(0,12).map((item)=>{
        const meta = [item.bucket, item.candidateCity || "unresolved", "score "+fmt.format((item.eventCount||0)+(item.entityCount||0)), item.currentState?.action].filter(Boolean).join(" · ");
        const tags = [item.candidateSource, item.reason, item.sampleArticleUid].filter(Boolean).map((tag)=>'<span class="tag">'+esc(tag)+'</span>').join("");
        const id = esc(item.reviewId);
        return '<article class="row queue-row geo-row"><div><h3>'+esc(item.label)+'</h3><p>'+esc(meta)+'</p><div class="tags">'+tags+'</div></div><div class="actions"><button data-review-id="'+id+'" data-action="review_only">Review</button><button data-review-id="'+id+'" data-action="accept">Accept</button><button data-review-id="'+id+'" data-action="reject">Reject</button><button data-review-id="'+id+'" data-action="needs_more_source">More source</button><button data-review-id="'+id+'" data-action="hold">Hold</button></div></article>';
      }).join("") || '<div class="empty">No geocode review rows</div>';
    }
    function renderSearch() {
      const results = state.search?.results || [];
      document.getElementById("results").innerHTML = results.map((r)=>row(r.title, r.kind, [r.item?.source_account, r.item?.type, r.item?.place, r.item?.source_article_uid])).join("") || '<div class="empty">No search results</div>';
    }
    function actionPayload(item, action) {
      return { itemId:item.id, action, subjectName:item.subjectName, subjectType:item.subjectType, sourceUrl:item.url, sourceArticleUid:item.sourceArticleUid, decision: action, reviewer:"local", note:"" };
    }
    function geocodeActionPayload(item, action) {
      return { reviewId:item.reviewId, action, decision: action, reviewer:"local", note:"local map review only" };
    }
    function renderQueue() {
      const items = state.identity?.items || [];
      document.getElementById("queue").innerHTML = items.slice(0,12).map((item)=>'<article class="row queue-row"><div><h3>'+esc(item.subjectName||item.id)+'</h3><p>'+esc([item.domain,item.status,item.currentState?.action].filter(Boolean).join(" · "))+'</p><div class="tags">'+[item.queue,item.bucket,item.sourceArticleUid].filter(Boolean).map((tag)=>'<span class="tag">'+esc(tag)+'</span>').join("")+'</div></div><div class="actions"><button data-id="'+esc(item.id)+'" data-action="accept">Accept</button><button data-id="'+esc(item.id)+'" data-action="reject">Reject</button><button data-id="'+esc(item.id)+'" data-action="needs_more_source">More source</button></div></article>').join("") || '<div class="empty">No adjudication rows</div>';
    }
    function renderLedger() {
      const actions = state.ledger?.actions || [];
      document.getElementById("ledger").innerHTML = actions.slice(0,10).map((a)=>row(a.action + " · " + a.subjectName, a.createdAt, [a.itemId, a.reviewer, a.sourceArticleUid])).join("") || '<div class="empty">No persisted actions yet</div>';
    }
    function renderAll(){ renderStatus(); renderMap(); renderGeocodeReview(); renderSearch(); renderQueue(); renderLedger(); document.getElementById("footnote").textContent="Local SQLite writes are limited to adjudication and geocode review ledger tables; no graph/vector/model/network write."; }
    async function reload() {
      const [status, map, geocodeReview, identity, ledger] = await Promise.all([
        json("/api/v1/stage7/local/status"),
        json("/api/v1/stage7/local/map?limit=200&status=geocoded"),
        json("/api/v1/stage7/local/geocode-review?limit=40"),
        json("/api/v1/stage7/identity-review?limit=100"),
        json("/api/v1/stage7/local/adjudication-ledger?limit=20"),
      ]);
      state.status = status; state.map = map; state.geocodeReview = geocodeReview; state.identity = identity; state.ledger = ledger;
      renderAll();
    }
    async function search() {
      const q = document.getElementById("q").value.trim();
      const kind = document.getElementById("kind").value;
      state.search = await json("/api/v1/stage7/search?q="+encodeURIComponent(q)+"&kind="+encodeURIComponent(kind)+"&limit=30");
      renderSearch();
    }
    document.getElementById("searchBtn").addEventListener("click", search);
    document.getElementById("q").addEventListener("keydown", (event)=>{ if(event.key==="Enter") search(); });
    document.getElementById("geocodeReview").addEventListener("click", async (event)=>{
      const button = event.target.closest("button[data-action]");
      if(!button) return;
      const item = (state.geocodeReview?.items || []).find((candidate)=>candidate.reviewId === button.dataset.reviewId);
      if(!item) return;
      button.disabled = true;
      await json("/api/v1/stage7/local/geocode-review", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(geocodeActionPayload(item, button.dataset.action)) });
      await reload();
    });
    document.getElementById("queue").addEventListener("click", async (event)=>{
      const button = event.target.closest("button[data-action]");
      if(!button) return;
      const item = (state.identity?.items || []).find((candidate)=>candidate.id === button.dataset.id);
      if(!item) return;
      button.disabled = true;
      await json("/api/v1/stage7/local/adjudication", { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(actionPayload(item, button.dataset.action)) });
      await reload();
    });
    reload().catch((error)=>{ document.getElementById("results").innerHTML='<div class="empty">'+esc(error.message)+'</div>'; });
  </script>
</body>
</html>`;
}
