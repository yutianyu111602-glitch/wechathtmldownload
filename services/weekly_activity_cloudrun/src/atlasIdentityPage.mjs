export function renderAtlasIdentityPage() {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>图鉴身份审阅</title>
  <style>
    :root{--bg:#f4f2ec;--fg:#171714;--muted:#6d675e;--line:#d9d1c4;--panel:#fffdf8;--ink:#111;--green:#1f6f55;--red:#a8473a;--blue:#285d75;--amber:#9f7523}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);font-family:"Inter","Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0}
    a{color:inherit}
    button,select{font:inherit}
    header{border-bottom:1px solid var(--line);background:#fffaf0}
    .bar{max-width:1480px;margin:0 auto;padding:18px 24px;display:grid;grid-template-columns:minmax(260px,1fr) auto;gap:18px;align-items:center}
    .brand{display:flex;gap:16px;align-items:center;min-width:0}
    .brand img{width:144px;height:36px;object-fit:contain;background:#111;border-radius:4px;padding:5px}
    h1{margin:0;font-size:28px;line-height:1.08;font-weight:760}
    .sub{margin-top:5px;color:var(--muted);font-size:13px}
    .nav{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
    .nav a,.nav button{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:9px 11px;text-decoration:none;color:#3f3a34;cursor:pointer}
    .nav .active{background:#171714;color:#fff;border-color:#171714}
    main{max-width:1480px;margin:0 auto;padding:22px 24px 42px}
    .metrics{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:10px;margin-bottom:16px}
    .metric{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:14px 14px 12px}
    .metric span{display:block;color:var(--muted);font-size:12px}
    .metric strong{display:block;margin-top:8px;font-size:23px;line-height:1}
    .toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
    select{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:10px;min-width:190px;color:var(--fg)}
    .layout{display:grid;grid-template-columns:minmax(250px,330px) minmax(0,1fr);gap:16px}
    aside,.panel{border:1px solid var(--line);background:var(--panel);border-radius:8px}
    aside{padding:16px;align-self:start;position:sticky;top:14px}
    .panel{padding:16px;min-width:0}
    h2{margin:0 0 14px;font-size:16px;line-height:1.2}
    .facet{display:grid;gap:8px}
    .facet-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;border-bottom:1px solid #ebe5da;padding:8px 0;font-size:13px}
    .facet-row:last-child{border-bottom:0}
    .facet-row span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .count{color:var(--muted)}
    .queue{display:grid;gap:10px}
    .row{border:1px solid #e4ddd2;border-radius:8px;background:#fff;padding:12px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px}
    .row h3{margin:0;font-size:15px;line-height:1.32;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .row p{margin:7px 0 0;color:var(--muted);font-size:12px;line-height:1.45}
    .tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
    .tag{border:1px solid #e3d8c5;border-radius:999px;padding:4px 7px;color:#5c554b;font-size:11px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .decision{text-align:right;display:grid;gap:6px;align-content:start;min-width:150px}
    .badge{border-radius:999px;padding:5px 8px;font-size:11px;white-space:nowrap;background:#f4eee3;color:#554a3d}
    .badge.red{background:#f8e6e1;color:var(--red)}
    .badge.green{background:#e4f1ea;color:var(--green)}
    .badge.blue{background:#e3edf2;color:var(--blue)}
    .empty{color:var(--muted);font-size:13px;padding:14px;border:1px dashed var(--line);border-radius:8px}
    .foot{margin-top:18px;color:var(--muted);font-size:12px}
    @media (max-width:980px){.bar{grid-template-columns:1fr}.nav{justify-content:flex-start}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.layout{grid-template-columns:1fr}aside{position:relative;top:0}.row{grid-template-columns:1fr}.decision{text-align:left;grid-template-columns:repeat(2,max-content)}}
    @media (max-width:560px){.bar,main{padding-left:14px;padding-right:14px}.brand{align-items:flex-start;flex-direction:column}.brand img{width:128px}.metrics{grid-template-columns:1fr}h1{font-size:24px}select{width:100%}.decision{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div class="brand">
        <img src="/assets/huaidj-logo-nav-512x128.png" alt="HUAIDJ">
        <div>
          <h1>图鉴身份审阅</h1>
          <div class="sub" id="releaseLine">Identity adjudication queue</div>
        </div>
      </div>
      <nav class="nav">
        <a href="/atlas">图鉴</a>
        <a class="active" href="/atlas/identity">身份</a>
        <a href="/api/v1/stage7/identity-review">API</a>
      </nav>
    </div>
  </header>
  <main>
    <section class="metrics" id="metrics"></section>
    <section class="toolbar">
      <select id="queueFilter" aria-label="Queue"></select>
      <select id="bucketFilter" aria-label="Bucket"></select>
      <select id="domainFilter" aria-label="Domain"></select>
    </section>
    <section class="layout">
      <aside>
        <h2>队列</h2>
        <div class="facet" id="queueFacet"></div>
        <h2 style="margin-top:18px">域名</h2>
        <div class="facet" id="domainFacet"></div>
      </aside>
      <section class="panel">
        <h2>候选</h2>
        <div class="queue" id="items"></div>
      </section>
    </section>
    <div class="foot" id="footnote"></div>
  </main>
  <script>
    const state = { data: null, filters: { queue: "", bucket: "", domain: "" } };
    const fmt = new Intl.NumberFormat("en-US");
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    async function fetchJson(path) {
      const res = await fetch(path, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(path + " " + res.status);
      return res.json();
    }
    function metric(label, value, color) {
      return '<div class="metric"><span>' + esc(label) + '</span><strong style="color:' + color + '">' + esc(value) + '</strong></div>';
    }
    function facet(rows) {
      if (!rows || !rows.length) return '<div class="empty">No rows</div>';
      return rows.slice(0, 10).map((row) => '<div class="facet-row"><span>' + esc(row.label) + '</span><b class="count">' + fmt.format(row.count || 0) + '</b></div>').join("");
    }
    function options(id, rows, label) {
      const value = state.filters[id] || "";
      const html = ['<option value="">' + esc(label) + '</option>'].concat((rows || []).slice(0, 40).map((row) => '<option value="' + esc(row.label) + '"' + (row.label === value ? " selected" : "") + '>' + esc(row.label) + ' (' + fmt.format(row.count || 0) + ')</option>')).join("");
      document.getElementById(id + "Filter").innerHTML = html;
    }
    function rowCard(row) {
      const title = row.subjectName || row.domain || row.id;
      const source = [row.sourceAccount, row.sourceTitle].filter(Boolean).join(" · ");
      const tags = [row.queue, row.bucket, row.domain, row.sourceArticleUid].filter(Boolean).slice(0, 5).map((tag) => '<span class="tag">' + esc(tag) + '</span>').join("");
      const accepted = row.acceptedForGraph ? '<span class="badge green">accepted</span>' : '<span class="badge red">not accepted</span>';
      const proof = row.identityProof ? '<span class="badge green">identity proof</span>' : '<span class="badge blue">needs proof</span>';
      const url = row.url ? '<p><a href="' + esc(row.url) + '" target="_blank" rel="noreferrer">' + esc(row.url) + '</a></p>' : "";
      return '<article class="row"><div><h3>' + esc(title) + '</h3><p>' + esc(source || row.reviewReason || row.status || "") + '</p>' + url + '<div class="tags">' + tags + '</div></div><div class="decision">' + accepted + proof + '<span class="badge">' + esc(row.status || "review") + '</span></div></article>';
    }
    function apiPath() {
      const params = new URLSearchParams({ limit: "100" });
      for (const [key, value] of Object.entries(state.filters)) {
        if (value) params.set(key, value);
      }
      return "/api/v1/stage7/identity-review?" + params.toString();
    }
    async function load() {
      state.data = await fetchJson(apiPath());
      render();
    }
    function render() {
      const d = state.data;
      if (!d) return;
      const s = d.summary || {};
      document.getElementById("releaseLine").textContent = (d.decision || "identity review") + " · " + (d.generatedAt || "");
      document.getElementById("metrics").innerHTML = [
        metric("Candidates", fmt.format(s.itemCount || 0), "#171714"),
        metric("Needs review", fmt.format(s.needsReviewCount || 0), "#a8473a"),
        metric("Accepted", fmt.format(s.acceptedForGraph || 0), "#1f6f55"),
        metric("Identity proof", fmt.format(s.identityProofCount || 0), "#285d75"),
        metric("Returned", fmt.format(d.page?.returned || 0), "#9f7523"),
      ].join("");
      const facets = d.facets || {};
      document.getElementById("queueFacet").innerHTML = facet(facets.queues);
      document.getElementById("domainFacet").innerHTML = facet(facets.domains);
      options("queue", facets.queues, "All queues");
      options("bucket", facets.buckets, "All buckets");
      options("domain", facets.domains, "All domains");
      document.getElementById("items").innerHTML = (d.items || []).length ? d.items.map(rowCard).join("") : '<div class="empty">No rows for this filter</div>';
      const safe = d.safety || {};
      document.getElementById("footnote").textContent = "Read-only identity workbench. graphWrite=" + Boolean(safe.graphWriteExecuted) + " qdrantWrite=" + Boolean(safe.qdrantWriteExecuted) + " modelCall=" + Boolean(safe.modelCallExecuted);
    }
    ["queue", "bucket", "domain"].forEach((key) => {
      document.getElementById(key + "Filter").addEventListener("change", (event) => {
        state.filters[key] = event.target.value;
        load().catch((error) => { document.getElementById("items").innerHTML = '<div class="empty">' + esc(error.message) + '</div>'; });
      });
    });
    load().catch((error) => { document.getElementById("items").innerHTML = '<div class="empty">' + esc(error.message) + '</div>'; });
  </script>
</body>
</html>`;
}
