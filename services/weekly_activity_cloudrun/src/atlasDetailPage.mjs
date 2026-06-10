function scriptJson(value) {
  return JSON.stringify(value).replace(/<\//g, "<\\/");
}

export function renderAtlasDetailPage(kind, id) {
  const safeKind = ["articles", "entities", "events"].includes(kind) ? kind : "entities";
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>图鉴详情 · 中国地下电子音乐图鉴</title>
  <style>
    :root{--bg:#f6f4ef;--fg:#171714;--muted:#6c675f;--line:#d7d0c5;--panel:#fffdf8;--ink:#111;--green:#1f6f55;--red:#b44d3d;--blue:#285d75}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);font-family:"Inter","Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0}
    a{color:inherit;text-decoration:none}
    .shell{min-height:100vh}
    header{border-bottom:1px solid var(--line);background:#fffaf0}
    .bar{max-width:1320px;margin:0 auto;padding:18px 24px;display:grid;grid-template-columns:minmax(260px,1fr) auto;gap:18px;align-items:center}
    .brand{display:flex;gap:16px;align-items:center;min-width:0}
    .brand img{width:144px;height:36px;object-fit:contain;background:#111;border-radius:4px;padding:5px}
    h1{margin:0;font-size:27px;line-height:1.1;font-weight:760}
    .sub{margin-top:5px;color:var(--muted);font-size:13px;word-break:break-all}
    .nav{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
    .pill,.nav a{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:7px 10px;font-size:12px;color:#3f3a34;white-space:nowrap}
    main{max-width:1320px;margin:0 auto;padding:22px 24px 42px}
    .metrics{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin-bottom:16px}
    .metric{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:14px}
    .metric span{display:block;color:var(--muted);font-size:12px}
    .metric strong{display:block;margin-top:8px;font-size:21px;line-height:1.15;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .layout{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(280px,.9fr);gap:16px}
    .panel{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:16px;min-width:0}
    h2{margin:0 0 13px;font-size:16px;line-height:1.2}
    .title{font-size:24px;font-weight:760;line-height:1.2;margin:0 0 8px;word-break:break-word}
    .muted{color:var(--muted)}
    .rows{display:grid;gap:8px}
    .row{display:grid;grid-template-columns:170px minmax(0,1fr);gap:12px;border-bottom:1px solid #ebe5da;padding:8px 0;font-size:13px}
    .row:last-child{border-bottom:0}
    .row span:first-child{color:var(--muted)}
    .row span:last-child{word-break:break-word}
    .preview{white-space:pre-wrap;line-height:1.55;color:#3c3731}
    .list{display:grid;gap:10px}
    .item{border:1px solid #e4ddd2;border-radius:8px;background:#fff;padding:12px;min-width:0}
    .item b{display:block;font-size:15px;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .item b a{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
    .item p{margin:7px 0 0;color:var(--muted);font-size:12px;line-height:1.45;word-break:break-word}
    .tag{display:inline-block;margin:8px 6px 0 0;border:1px solid #e3d8c5;border-radius:999px;padding:4px 7px;color:#5c554b;font-size:11px}
    .empty{color:var(--muted);font-size:13px;padding:14px;border:1px dashed var(--line);border-radius:8px}
    .error{border-color:#ddb8ad;background:#fff8f5;color:#7c2f22}
    @media (max-width:900px){.bar{grid-template-columns:1fr}.nav{justify-content:flex-start}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.layout{grid-template-columns:1fr}.row{grid-template-columns:1fr;gap:4px}}
    @media (max-width:560px){.bar,main{padding-left:14px;padding-right:14px}.brand{align-items:flex-start;flex-direction:column}.brand img{width:128px}.metrics{grid-template-columns:1fr}h1{font-size:23px}.title{font-size:21px}}
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="bar">
        <div class="brand">
          <img src="/assets/huaidj-logo-nav-512x128.png" alt="HUAIDJ">
          <div>
            <h1>图鉴详情</h1>
            <div class="sub" id="subtitle">${safeKind} / ${id}</div>
          </div>
        </div>
        <nav class="nav">
          <a href="/atlas">图鉴总览</a>
          <a href="/atlas/identity">身份审阅</a>
        </nav>
      </div>
    </header>
    <main>
      <section class="metrics" id="metrics"></section>
      <section class="layout">
        <article class="panel" id="detail"></article>
        <aside class="panel" id="evidence"></aside>
      </section>
      <section class="layout" style="margin-top:16px">
        <section class="panel" id="relatedEntities"></section>
        <section class="panel" id="relatedEvents"></section>
      </section>
    </main>
  </div>
  <script>
    const DETAIL_KIND = ${scriptJson(safeKind)};
    const DETAIL_ID = ${scriptJson(id)};
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    const fmt = new Intl.NumberFormat("en-US");
    const apiPath = "/api/v1/stage7/" + DETAIL_KIND + "/" + encodeURIComponent(DETAIL_ID);
    const kindLabel = { articles: "文章", entities: "实体", events: "事件" };
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
    function row(label, value) {
      const list = Array.isArray(value) ? value.filter(Boolean).join(" / ") : value;
      if (list === undefined || list === null || String(list).trim() === "") return "";
      return '<div class="row"><span>' + esc(label) + '</span><span>' + esc(list) + '</span></div>';
    }
    function metric(label, value, color) {
      return '<div class="metric"><span>' + esc(label) + '</span><strong style="color:' + color + '">' + esc(value) + '</strong></div>';
    }
    function itemCard(kind, item, meta, tags = []) {
      const href = detailHref(kind, item);
      const title = item?.title || item?.name || detailId(kind, item) || "Untitled";
      const titleHtml = href ? '<a href="' + esc(href) + '">' + esc(title) + '</a>' : esc(title);
      const tagHtml = tags.filter(Boolean).slice(0, 4).map((tag) => '<span class="tag">' + esc(tag) + '</span>').join("");
      return '<article class="item"><b>' + titleHtml + '</b><p>' + esc(meta || "") + '</p>' + tagHtml + '</article>';
    }
    function renderList(target, title, kind, rows) {
      const body = rows && rows.length
        ? rows.map((item) => itemCard(kind, item, item.source_article_uid || item.city || item.place || item.time_text, [item.type, item.confidence != null ? "confidence " + item.confidence : "", item.time_iso].filter(Boolean))).join("")
        : '<div class="empty">No related rows in this package slice</div>';
      document.getElementById(target).innerHTML = '<h2>' + esc(title) + '</h2><div class="list">' + body + '</div>';
    }
    function render(payload) {
      document.getElementById("subtitle").textContent = kindLabel[payload.kind] + " / " + (payload.primaryId || payload.id);
      document.getElementById("metrics").innerHTML = [
        metric("Kind", kindLabel[payload.kind] || payload.kind, "#171714"),
        metric("Matched by", payload.matchedBy || "id", "#285d75"),
        metric("Related entities", fmt.format((payload.related?.entities || []).length), "#1f6f55"),
        metric("Related events", fmt.format((payload.related?.events || []).length), "#b44d3d"),
      ].join("");
      const item = payload.item || {};
      const evidence = payload.evidence || {};
      const sourceArticle = payload.related?.sourceArticle;
      const sourceHtml = sourceArticle ? itemCard("articles", sourceArticle, sourceArticle.source_account || sourceArticle.article_uid, [sourceArticle.quality_grade]) : '<div class="empty">This row is itself a source article or source article was not packaged in the lookup sample.</div>';
      document.getElementById("detail").innerHTML = [
        '<div class="title">' + esc(payload.title || payload.primaryId || payload.id) + '</div>',
        '<div class="muted">' + esc(apiPath) + '</div>',
        '<div class="rows" style="margin-top:14px">',
        row("Primary ID", payload.primaryId),
        row("Source article UID", payload.lookup?.sourceArticleUid),
        row("Source account", evidence.sourceAccount),
        row("Publish status", evidence.publishTimeStatus),
        row("Quality grade", evidence.qualityGrade),
        row("Type", evidence.type),
        row("City", evidence.city),
        row("Place", evidence.place),
        row("Time", evidence.timeIso || evidence.timeText),
        row("Participants", evidence.participants),
        row("Aliases", evidence.aliases),
        '</div>',
        '<h2 style="margin-top:18px">来源文章</h2>',
        sourceHtml,
      ].join("");
      document.getElementById("evidence").innerHTML = [
        '<h2>证据摘录</h2>',
        evidence.vectorTextPreview ? '<div class="preview">' + esc(evidence.vectorTextPreview) + '</div>' : '<div class="empty">No packaged vector text preview</div>',
        '<h2 style="margin-top:18px">只读边界</h2>',
        '<div class="rows">',
        row("LLM call", String(Boolean(payload.safety?.llmCallExecuted))),
        row("Qdrant write", String(Boolean(payload.safety?.qdrantWriteExecuted))),
        row("Neo4j write", String(Boolean(payload.safety?.neo4jWriteExecuted))),
        row("mem0 write", String(Boolean(payload.safety?.mem0WriteExecuted))),
        row("Rows scanned", [payload.lookup?.detailRowsScanned, payload.lookup?.relatedEntityRowsScanned, payload.lookup?.relatedEventRowsScanned].filter((v) => v !== undefined).join(" / ")),
        '</div>',
      ].join("");
      renderList("relatedEntities", "关联实体", "entities", payload.related?.entities || []);
      renderList("relatedEvents", "关联事件", "events", payload.related?.events || []);
    }
    fetch(apiPath, { headers: { Accept: "application/json" } }).then(async (res) => {
      const payload = await res.json();
      if (!res.ok) throw new Error(payload?.error?.message || (apiPath + " " + res.status));
      render(payload);
    }).catch((error) => {
      document.getElementById("metrics").innerHTML = metric("Load", "failed", "#b44d3d");
      document.getElementById("detail").innerHTML = '<h2>Load failed</h2><div class="empty error">' + esc(error.message) + '</div>';
      document.getElementById("evidence").innerHTML = '<h2>证据摘录</h2><div class="empty">No payload</div>';
      renderList("relatedEntities", "关联实体", "entities", []);
      renderList("relatedEvents", "关联事件", "events", []);
    });
  </script>
</body>
</html>`;
}
