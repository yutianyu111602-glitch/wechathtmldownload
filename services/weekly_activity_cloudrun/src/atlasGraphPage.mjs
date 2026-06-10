export function renderAtlasGraphPage() {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>坏DJ Atlas 图谱</title>
  <style>
    :root{--bg:#070807;--fg:#e9e5cf;--muted:#8c927d;--line:#26311b;--panel:#0d100c;--panel2:#090b08;--canvas:#050605;--canvas2:#0b1008;--ink:#f1f1ec;--cyan:#18a8b8;--green:#8fdc65;--acid:#b6ff3b;--amber:#c28a2d;--orange:#c85f3c;--violet:#756c90;--blue:#376f8f}
    *{box-sizing:border-box}
    html,body{height:100%}
    body{margin:0;background:var(--bg);color:var(--fg);font-family:"Inter","Noto Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:0;overflow:hidden}
    a{color:inherit}button,input,select{font:inherit}
    .app{height:100vh;display:grid;grid-template-rows:auto minmax(0,1fr) auto}
    .topbar{height:58px;border-bottom:1px solid var(--line);background:#070807;display:grid;grid-template-columns:315px minmax(520px,1fr) auto;gap:12px;align-items:center;padding:10px 14px}
    .brand{display:flex;align-items:center;gap:12px;min-width:0;overflow:hidden}.brand>div{min-width:0}.brand img{width:122px;height:31px;object-fit:contain;background:#030403;border-radius:4px;padding:4px;flex:0 0 auto}.brand h1{margin:0;font-size:18px;line-height:1.1;font-weight:760;white-space:nowrap;color:var(--fg)}.brand span{display:block;margin-top:3px;color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .search{display:grid;grid-template-columns:minmax(180px,1fr) 92px 96px 112px auto;gap:8px;min-width:0}.search input,.search select{min-width:0;border:1px solid var(--line);background:var(--panel);border-radius:4px;padding:9px 10px;color:var(--fg);outline:0}.search input::placeholder{color:#56604f}.search input:focus,.search select:focus{border-color:#3c4f24;box-shadow:0 0 0 2px rgba(182,255,59,.12)}
    .cmds{display:flex;gap:7px;justify-content:flex-end;align-items:center}.btn{border:1px solid var(--line);background:#10150d;color:#e9e5cf;border-radius:4px;padding:9px 11px;cursor:pointer;white-space:nowrap}.btn.primary{border-color:#3c4f24;background:#151c10;color:var(--acid)}.btn.active{border-color:#4f6d2c;background:#1a2412;color:var(--acid)}.btn:disabled{opacity:.55;cursor:wait}
    .workspace{min-height:0;display:grid;grid-template-columns:370px minmax(640px,1fr);background:var(--panel2)}
    .rail{min-height:0;overflow:auto;background:var(--panel);border-right:1px solid var(--line)}
    .inspector{background:var(--panel);border-top:1px solid var(--line)}
    .pane{padding:14px;border-bottom:1px solid var(--line)}.pane h2{margin:0 0 10px;font-size:12px;line-height:1.2;text-transform:uppercase;color:#8fdc65;letter-spacing:.12em}.stack{display:grid;gap:8px}.split{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center}
    .chiprow{display:flex;gap:6px;flex-wrap:wrap}.chip{border:1px solid #26311b;background:#10150d;border-radius:4px;padding:6px 8px;font-size:12px;color:#8c927d;cursor:pointer}.chip.active{background:#151c10;color:var(--acid);border-color:#3c4f24}
    .check{display:grid;grid-template-columns:18px minmax(0,1fr) auto;gap:8px;align-items:center;font-size:13px;color:#e9e5cf}.check input{width:16px;height:16px;accent-color:#8fdc65}.count{color:var(--muted);font-variant-numeric:tabular-nums}
    .queue{display:grid;gap:7px}.queue button,.result{border:1px solid #26311b;background:#10150d;border-radius:4px;padding:9px;text-align:left;cursor:pointer;min-width:0;color:#e9e5cf}.queue b,.result b{display:block;font-size:13px;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.queue span,.result span{display:block;margin-top:4px;color:var(--muted);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .result-row{display:grid;grid-template-columns:minmax(0,1fr) 54px;gap:6px}.result-main,.pick{border:1px solid #26311b;background:#10150d;border-radius:4px;color:#e9e5cf;cursor:pointer}.result-main{padding:9px;text-align:left;min-width:0}.result-main:hover,.queue button:hover,.click-row:hover{border-color:#3c4f24;background:#131b0f}.pick{display:flex;align-items:center;justify-content:center;color:var(--acid);font-size:12px}.pick.active{background:#1a2412;border-color:#4f6d2c}
    .graph-wrap{position:relative;min-height:0;background:#030403;overflow:hidden}
    .graph-wrap:before{content:"";position:absolute;inset:0;z-index:1;pointer-events:none;background-image:linear-gradient(rgba(182,255,59,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(24,168,184,.045) 1px,transparent 1px);background-size:52px 52px;opacity:.55}
    .graph-wrap:after{content:"";position:absolute;inset:0;z-index:2;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(182,255,59,.09),transparent);transform:translateX(-120%);animation:sweep 9s linear infinite;opacity:.5}@keyframes sweep{to{transform:translateX(120%)}}
    .graph-head{position:absolute;z-index:4;left:14px;top:14px;display:flex;gap:8px;flex-wrap:wrap;max-width:calc(100% - 28px)}.badge{border:1px solid rgba(255,255,255,.18);background:rgba(16,20,24,.76);color:#dce2e2;border-radius:8px;padding:7px 9px;font-size:12px;backdrop-filter:saturate(120%) blur(6px)}.badge strong{color:#fff}
    #forceHost,#sigmaHost,#cosmosHost,#graphCanvas{position:absolute;inset:0;width:100%;height:100%;z-index:0}#forceHost,#sigmaHost,#cosmosHost{display:none}.force-on #forceHost{display:block}.sigma-on #sigmaHost{display:block}.cosmos-on #cosmosHost{display:block}.force-on #graphCanvas,.force-on #sigmaHost,.force-on #cosmosHost,.sigma-on #graphCanvas,.sigma-on #forceHost,.sigma-on #cosmosHost,.cosmos-on #graphCanvas,.cosmos-on #forceHost,.cosmos-on #sigmaHost{display:none}
    .legend{position:absolute;z-index:4;left:14px;bottom:14px;display:flex;gap:8px;flex-wrap:wrap}.legend span{border:1px solid rgba(255,255,255,.16);background:rgba(16,20,24,.76);color:#dfe4e4;border-radius:8px;padding:7px 8px;font-size:11px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:-1px}
    .hint{position:absolute;z-index:3;right:14px;bottom:14px;color:#aeb8b8;font-size:12px;background:rgba(16,20,24,.62);border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:8px 10px}
    .gate{display:none;position:absolute;z-index:8;inset:0;align-items:center;justify-content:center;background:rgba(7,8,7,.82);backdrop-filter:saturate(90%) blur(4px)}.gate.active{display:flex}.gate-card{width:min(420px,calc(100% - 32px));border:1px solid #26311b;background:#0d100c;border-radius:8px;padding:18px;color:#e9e5cf;box-shadow:0 18px 60px rgba(0,0,0,.34)}.gate-card h2{margin:0;font-size:18px;line-height:1.2}.gate-card p{margin:10px 0 0;color:#8c927d;font-size:13px;line-height:1.55}.gate-box{margin-top:14px;min-height:70px}.gate-card button{margin-top:14px;border:1px solid #3c4f24;background:#151c10;color:#b6ff3b;border-radius:6px;padding:9px 11px;cursor:pointer}
    .inspector .title{font-size:22px;line-height:1.15;margin:0 0 8px;font-weight:760;overflow-wrap:anywhere;color:#f1f1ec}.meta{display:flex;gap:6px;flex-wrap:wrap}.tag{border:1px solid #26311b;background:#10150d;border-radius:4px;padding:5px 7px;color:#8c927d;font-size:11px;max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tag.cyan{border-color:#1b5d63;color:#18a8b8}.tag.green{border-color:#3c4f24;color:#b6ff3b}.tag.amber{border-color:#674a1d;color:#c28a2d}.tag.orange{border-color:#6f3526;color:#c85f3c}
    .section{padding:14px;border-bottom:1px solid var(--line)}.section h3{margin:0 0 10px;font-size:12px;line-height:1.2;text-transform:uppercase;color:#8fdc65;letter-spacing:.12em}.section p{margin:0;color:#b7bda9;font-size:13px;line-height:1.55;overflow-wrap:anywhere}.kv{display:grid;gap:7px}.kv div{display:grid;grid-template-columns:104px minmax(0,1fr);gap:10px;font-size:12px}.kv span:first-child{color:var(--muted)}.kv span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#e9e5cf}.links{display:grid;gap:8px}.links a{border:1px solid #26311b;background:#10150d;border-radius:4px;padding:9px;text-decoration:none;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#e9e5cf}.links a.external:after{content:" ↗";color:var(--muted)}
    .statgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.stat{border:1px solid #26311b;background:#10150d;border-radius:4px;padding:8px}.stat b{display:block;font-size:16px;color:#f1f1ec;font-variant-numeric:tabular-nums}.stat span{display:block;margin-top:3px;color:var(--muted);font-size:11px}.mini-list{display:grid;gap:6px}.mini,.click-row{border:1px solid #26311b;background:#10150d;border-radius:4px;padding:8px;min-width:0;color:#e9e5cf;text-align:left;cursor:pointer}.mini b,.click-row b{display:block;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mini span,.click-row span{display:block;margin-top:3px;color:var(--muted);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.click-row p{margin:5px 0 0;color:#aeb5a2;font-size:12px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
    .compare-tray{display:flex;gap:6px;flex-wrap:wrap}.target-chip{border:1px solid #3c4f24;background:#151c10;color:var(--acid);border-radius:4px;padding:6px 8px;font-size:12px;cursor:pointer;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.target-chip.empty{border-style:dashed;background:#10150d;color:var(--muted);cursor:default}.hint-copy{font-size:12px;line-height:1.5;color:#aeb5a2}.modebar{display:flex;gap:6px;flex-wrap:wrap}.modebar .btn{padding:7px 9px;font-size:12px}
    .actionbar{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.avatar-card{display:grid;grid-template-columns:68px minmax(0,1fr);gap:12px;align-items:center;border:1px solid #26311b;background:#10150d;border-radius:6px;padding:10px}.avatar-card img{width:68px;height:68px;border-radius:50%;object-fit:cover;border:1px solid #3c4f24;background:#050605}.avatar-card b{display:block;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.avatar-card span{display:block;margin-top:4px;color:var(--muted);font-size:11px}.tiny{color:var(--muted);font-size:11px;line-height:1.45}
    .statusbar{height:30px;border-top:1px solid var(--line);background:#070807;color:#8c927d;display:flex;align-items:center;gap:14px;padding:0 12px;font-size:12px;white-space:nowrap;overflow:hidden}.statusbar span{overflow:hidden;text-overflow:ellipsis}
    .empty{border:1px dashed #26311b;border-radius:4px;padding:11px;color:var(--muted);font-size:13px;background:#10150d}.err{color:#d76b55}
    @media (max-width:1380px){.topbar{height:auto;grid-template-columns:280px minmax(0,1fr)}.cmds{grid-column:1 / -1;justify-content:flex-start;flex-wrap:wrap}.search{grid-template-columns:minmax(180px,1fr) 82px 88px 104px auto}}
    @media (max-width:1180px){body{overflow:auto}.app{height:auto;min-height:100vh}.topbar{height:auto;grid-template-columns:1fr}.cmds{justify-content:flex-start}.workspace{display:flex;flex-direction:column}.graph-wrap{order:1;height:68vh;min-height:520px}.rail{order:2;border:0;border-bottom:1px solid var(--line)}.inspector{border-top:1px solid var(--line)}.search{grid-template-columns:1fr 1fr}.search .primary{grid-column:1 / -1}.hint{display:none}}
    @media (max-width:620px){.topbar{padding:10px}.brand{width:100%;align-items:flex-start;flex-direction:column}.brand>div{width:100%;max-width:100%}.brand h1,.brand span{max-width:100%;overflow:hidden;text-overflow:ellipsis}.search{grid-template-columns:1fr}.graph-wrap{height:62vh;min-height:440px}.statusbar{height:auto;min-height:30px;flex-wrap:wrap;padding:7px 10px}.cmds{flex-wrap:wrap}.pane,.section{padding:12px}}
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand"><img src="/assets/huaidj-logo-nav-512x128.png" alt="HUAIDJ"><div><h1>坏DJ Atlas</h1><span id="dbLine">私有读模型 / 公开窗口</span></div></div>
      <form class="search" id="searchForm">
        <input id="q" autocomplete="off" placeholder="搜 DJ / 场地 / 厂牌 / 活动 / mixtape">
        <input id="kind" type="hidden" value="">
        <select id="depth"><option value="1">1 跳</option><option value="2">2 跳</option><option value="3">3 跳</option></select>
        <select id="layout"><option value="radial">径向</option><option value="rings">环形</option><option value="columns">分栏</option></select>
        <select id="lod"><option value="focus">Focus 3D</option><option value="overview">Overview GPU</option><option value="detail">Detail</option></select>
        <button class="btn primary" type="submit">搜索</button>
      </form>
      <div class="cmds">
        <button class="btn active" data-renderer="auto" type="button">Auto</button>
        <button class="btn" data-renderer="cosmos" type="button">Overview</button>
        <button class="btn" data-renderer="sigma" type="button">2D</button>
        <button class="btn" id="roamBtn" type="button">漫游</button>
        <button class="btn" id="fitBtn" type="button">适配</button>
        <button class="btn" id="resetBtn" type="button">重置</button>
        <button class="btn" id="shotBtn" type="button">导出 PNG</button>
      </div>
    </header>
    <main class="workspace">
      <aside class="rail">
        <section class="pane">
          <h2>常用入口</h2>
          <div class="chiprow" id="savedSearches"></div>
        </section>
        <section class="pane">
          <h2>节点过滤</h2>
          <div class="stack" id="nodeFilters"></div>
        </section>
        <section class="pane">
          <h2>关系过滤</h2>
          <div class="stack" id="edgeFilters"></div>
        </section>
        <section class="pane">
          <h2>搜索结果</h2>
          <div class="queue" id="results"></div>
        </section>
        <section class="pane">
          <h2>关系探索</h2>
          <p class="hint-copy">多选两个或多个 DJ / 场地 / 厂牌，直接展开它们的共同网络。</p>
          <div class="compare-tray" id="compareTray"></div>
          <div class="actionbar">
            <button class="btn primary" id="exploreRelationBtn" type="button">探索关系</button>
            <button class="btn" id="clearCompareBtn" type="button">清空</button>
          </div>
        </section>
        <section class="pane">
          <h2>探索记录</h2>
          <div class="queue" id="queue"></div>
        </section>
        <div class="inspector" id="inspector">
          <section class="section"><h3>详情</h3><div class="empty">点击搜索结果、图谱节点或多选关系目标。</div></section>
        </div>
      </aside>
      <section class="graph-wrap" id="graphWrap">
        <div class="graph-head" id="graphBadges"></div>
        <div id="forceHost"></div>
        <div id="cosmosHost"></div>
        <canvas id="graphCanvas"></canvas>
        <div id="sigmaHost"></div>
        <div class="legend">
          <span><i class="dot" style="background:#18a8b8"></i>人物 / DJ</span>
          <span><i class="dot" style="background:#c28a2d"></i>俱乐部 / 场地</span>
          <span><i class="dot" style="background:#2f8f5b"></i>厂牌 / 组织</span>
          <span><i class="dot" style="background:#c85f3c"></i>活动 / 演出</span>
          <span><i class="dot" style="background:#76808a"></i>来源文章</span>
        </div>
        <div class="hint" id="renderHint">正在载入图谱</div>
        <div class="gate" id="sessionGate"></div>
      </section>
    </main>
    <footer class="statusbar" id="statusbar"><span>Atlas 图谱启动中</span></footer>
  </div>
  <script>
    const state = {
      nodes: new Map(),
      edges: new Map(),
      positions: new Map(),
      selectedId: "",
      filters: { nodes: new Set(["articles","entities","events"]), edges: new Set(["mentions_entity","mentions_event","same_article","dj_collaboration","performed_at","hosted_at","frequent_venue","organized_by"]) },
      queue: [],
      results: [],
      payload: null,
      renderer: "canvas",
      rendererPreference: "auto",
      lod: "focus",
      forceGraph: null,
      ForceGraph3D: null,
      cosmosGraph: null,
      CosmosGraphCtor: null,
      cosmosFailed: false,
      nodeObjectCache: new Map(),
      sigma: null,
      sigmaGraph: null,
      GraphCtor: null,
      SigmaCtor: null,
      session: { requireSession: false, hasSession: false, siteKey: "", configured: false, fallbackChallengeEnabled: false, fallbackBusy: false, turnstileWidgetId: null, turnstileFallbackTimer: null },
      roamTimer: null,
      pinned: new Set(),
      relationTargets: new Map(),
      identityReviewItems: null,
      meta: {},
      cosmosNodeIds: [],
      cosmosEdgeIds: [],
      lastClick: { id: "", at: 0 },
      busy: false,
      lastLatency: 0,
      pan: { x: 0, y: 0, scale: 1 },
      drag: null
    };
    const colors = {
      article: "#76808a",
      event: "#c85f3c",
      person: "#18a8b8",
      dj: "#18a8b8",
      venue: "#c28a2d",
      club: "#c28a2d",
      place: "#c28a2d",
      location: "#c28a2d",
      label: "#2f8f5b",
      organization: "#2f8f5b",
      brand: "#2f8f5b",
      group: "#2f8f5b",
      project: "#2f8f5b",
      entity: "#376f8f"
    };
    const edgeColors = { mentions_entity: "#6a767e", mentions_event: "#b96447", same_article: "#444d55", dj_collaboration: "#18a8b8", performed_at: "#d46a3c", hosted_at: "#c28a2d", frequent_venue: "#a88732", organized_by: "#2f8f5b" };
    const fmt = new Intl.NumberFormat("zh-CN");
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[ch]));
    const nodeKindLabels = { entities: "实体", events: "活动", articles: "来源文章" };
    const edgeKindLabels = { mentions_entity: "提及实体", mentions_event: "提及活动", same_article: "同文共现", dj_collaboration: "DJ 关系", performed_at: "参演活动", hosted_at: "发生场地", frequent_venue: "常演场地", organized_by: "组织/厂牌" };
    const actionLabels = { select: "查看", expand: "展开", pin: "固定", unpin: "取消固定" };
    const modeLabels = { seed: "种子窗口", expand: "展开窗口", "random-walk": "漫游窗口", random_walk: "漫游窗口" };
    const labelOf = (value, map) => map[String(value || "")] || String(value || "");
    const finite = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
    const scoreText = (value) => {
      const score = finite(value);
      if (!score) return "";
      return Number.isInteger(score) ? fmt.format(score) : score.toFixed(1).replace(/\\.0$/, "");
    };
    const relationshipScoreOf = (edge) => finite(edge?.relationshipScore ?? edge?.relationScore ?? edge?.metrics?.relationshipScore ?? edge?.metrics?.relationScore);
    const edgeDisplayLabel = (edge) => {
      const kindLabel = labelOf(edge?.kind, edgeKindLabels) || "关系";
      const label = String(edge?.label || "").trim();
      if (edge?.kind === "dj_collaboration" && (!label || label.includes("同台"))) return kindLabel;
      return label || kindLabel;
    };
    const api = async (path) => {
      const started = performance.now();
      const res = await fetch(path);
      const body = await res.json();
      state.lastLatency = Math.round(performance.now() - started);
      if (!res.ok) throw new Error(body.error?.message || path + " " + res.status);
      return body;
    };
    const loadScript = (src, id) => {
      if (document.getElementById(id)) {
        return new Promise((resolve, reject) => {
          const script = document.getElementById(id);
          if (script.dataset.loaded === "1") resolve();
          else {
            script.addEventListener("load", resolve, { once: true });
            script.addEventListener("error", reject, { once: true });
          }
        });
      }
      return new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.id = id;
        script.src = src;
        script.async = true;
        script.onload = () => { script.dataset.loaded = "1"; resolve(); };
        script.onerror = reject;
        document.head.appendChild(script);
      });
    };
    const nodeColor = (node) => {
      if (state.selectedId === node.id) return "#ffffff";
      if (state.pinned.has(node.id)) return "#b6ff3b";
      return node.visual?.color || colors[String(node.subtype || node.kind || "").toLowerCase()] || colors[node.kind === "articles" ? "article" : node.kind === "events" ? "event" : "entity"];
    };
    const nodeRadius = (node) => Math.max(5, Math.min(24, Number(node.visual?.size || (5 + Number(node.weight || 2)))));
    const visibleNodes = () => Array.from(state.nodes.values()).filter((node) => state.filters.nodes.has(node.kind));
    const visibleEdges = () => Array.from(state.edges.values()).filter((edge) => state.filters.edges.has(edge.kind) && state.nodes.has(edge.source) && state.nodes.has(edge.target) && state.filters.nodes.has(state.nodes.get(edge.source).kind) && state.filters.nodes.has(state.nodes.get(edge.target).kind));
    const activeLod = () => document.getElementById("lod")?.value || state.lod || "focus";

    function chooseRenderer() {
      if (state.rendererPreference === "cosmos" || (state.rendererPreference === "auto" && state.lod === "overview")) {
        if (state.CosmosGraphCtor && !state.cosmosFailed) return "cosmos";
      }
      if (state.rendererPreference === "sigma" && state.GraphCtor && state.SigmaCtor) return "sigma";
      if (state.ForceGraph3D) return "3d-force-graph";
      if (state.GraphCtor && state.SigmaCtor) return "sigma";
      return "canvas";
    }

    function syncRenderer() {
      const renderer = chooseRenderer();
      state.renderer = renderer;
      const wrap = document.getElementById("graphWrap");
      wrap.classList.toggle("force-on", renderer === "3d-force-graph");
      wrap.classList.toggle("sigma-on", renderer === "sigma");
      wrap.classList.toggle("cosmos-on", renderer === "cosmos");
      const labels = {
        "3d-force-graph": "3D Focus / Three.js",
        cosmos: "Cosmos.gl GPU Overview",
        sigma: "Sigma.js + Graphology",
        canvas: "Canvas 备用渲染",
      };
      document.getElementById("renderHint").textContent = labels[renderer] || labels.canvas;
      for (const button of document.querySelectorAll("[data-renderer]")) {
        button.classList.toggle("active", button.dataset.renderer === state.rendererPreference);
      }
      renderGraph();
      renderStatus();
    }

    async function bootRenderer() {
      try {
        await loadScript("https://cdn.jsdelivr.net/npm/3d-force-graph@1.80.0/dist/3d-force-graph.min.js", "force-graph-3d-script");
        if (window.ForceGraph3D) state.ForceGraph3D = window.ForceGraph3D;
      } catch {
        state.ForceGraph3D = null;
      }
      try {
        const cosmos = await import("https://esm.sh/@cosmos.gl/graph@2.6.1");
        state.CosmosGraphCtor = cosmos.Graph || cosmos.default?.Graph || cosmos.default || null;
      } catch {
        state.CosmosGraphCtor = null;
      }
      try {
        const mods = await Promise.all([
          import("https://esm.sh/graphology@0.25.4"),
          import("https://esm.sh/sigma@3.0.2")
        ]);
        state.GraphCtor = mods[0].default || mods[0].Graph;
        state.SigmaCtor = mods[1].default || mods[1].Sigma;
      } catch {
        state.GraphCtor = null;
        state.SigmaCtor = null;
      }
      syncRenderer();
    }

    function setBusy(value) {
      state.busy = value;
      for (const id of ["roamBtn","fitBtn","resetBtn"]) document.getElementById(id).disabled = value;
    }

    function putQueue(node, action) {
      if (!node) return;
      state.queue = [{ id: node.id, label: node.label, meta: labelOf(action, actionLabels) + " · " + labelOf(node.kind, nodeKindLabels) }].concat(state.queue.filter((item) => item.id !== node.id)).slice(0, 12);
      renderQueue();
    }

    function stableHash(value) {
      let hash = 0;
      const raw = String(value || "");
      for (let i = 0; i < raw.length; i += 1) hash = (hash * 31 + raw.charCodeAt(i)) >>> 0;
      return hash;
    }

    function forceSeedPosition(node, index, total) {
      const hash = stableHash(node.id);
      const spread = node.seed ? 38 : node.kind === "articles" ? 130 : node.kind === "events" ? 185 : 165;
      const t = Math.max(1, total);
      const golden = Math.PI * (3 - Math.sqrt(5));
      const y = 1 - (index / Math.max(1, t - 1)) * 2;
      const radius = Math.sqrt(Math.max(0, 1 - y * y));
      const angle = golden * index + (hash % 628) / 100;
      const jitter = ((hash % 29) - 14) / 14;
      return {
        x: Math.cos(angle) * radius * spread + jitter * 12,
        y: y * spread * 0.68,
        z: Math.sin(angle) * radius * spread - jitter * 12
      };
    }

    function ensurePositions(nodes) {
      const mode = document.getElementById("layout").value;
      const total = Math.max(1, nodes.length);
      nodes.forEach((node, index) => {
        const existing = state.positions.get(node.id);
        if (existing && existing.mode === mode) return;
        const hash = stableHash(node.id);
        const angle = (index / total) * Math.PI * 2 + (hash % 180) / 180;
        let radius = 0.2 + ((hash % 100) / 100) * 0.68;
        if (node.seed || node.id === state.selectedId) radius = 0.06;
        if (mode === "rings") {
          const ring = node.kind === "articles" ? 0.26 : node.kind === "entities" ? 0.52 : 0.78;
          radius = ring + ((hash % 13) - 6) / 140;
        }
        if (mode === "columns") {
          const x = node.kind === "articles" ? -0.55 : node.kind === "entities" ? 0 : 0.55;
          const y = -0.82 + ((index % 34) / 33) * 1.64;
          state.positions.set(node.id, { x, y, mode });
          return;
        }
        state.positions.set(node.id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, mode });
      });
    }

    function normalizeViewportPayload(payload) {
      const meta = payload.meta || {};
      return {
        ...payload,
        meta,
        nodes: (payload.nodes || []).map((node) => ({
          ...node,
          role: node.role || (node.seed ? "seed" : node.kind === "events" ? "event" : node.kind === "articles" ? "evidence" : "related"),
          clusterId: node.clusterId || "cluster:" + (node.subtype || node.kind || "entity"),
          metrics: node.metrics || {},
          publicState: node.publicState || "public_rollup",
          visual: {
            ...(node.visual || {}),
            color: node.visual?.color || nodeColor(node),
            size: node.visual?.size || nodeRadius(node),
          },
        })),
        edges: (payload.edges || []).map((edge) => ({
          ...edge,
          label: edgeDisplayLabel(edge),
          relationshipScore: relationshipScoreOf(edge),
          relationScore: relationshipScoreOf(edge),
          evidenceCount: Number(edge.evidenceCount || 0),
          sampleEvidenceIds: edge.sampleEvidenceIds || [],
          publicState: edge.publicState || "public_rollup",
          metrics: edge.metrics || {},
        })),
      };
    }

    function applyPayload(rawPayload, merge) {
      const payload = normalizeViewportPayload(rawPayload || {});
      state.payload = payload;
      state.meta = payload.meta || {};
      state.lod = payload.meta?.lod || state.lod;
      const lodSelect = document.getElementById("lod");
      if (lodSelect && lodSelect.value !== state.lod) lodSelect.value = state.lod;
      if (!merge) {
        state.nodes.clear();
        state.edges.clear();
        state.positions.clear();
      }
      for (const node of payload.nodes || []) {
        const existing = state.nodes.get(node.id);
        if (existing) Object.assign(existing, node);
        else state.nodes.set(node.id, node);
      }
      for (const edge of payload.edges || []) state.edges.set(edge.id, edge);
      state.results = (payload.nodes || []).slice(0, 10).map((node) => ({ id: node.id, label: node.label, meta: [labelOf(node.kind, nodeKindLabels), node.subtype, node.city].filter(Boolean).join(" · ") }));
      syncRenderer();
      renderAll();
    }

    function bestVisibleNodeForQuery(query) {
      const nodes = visibleNodes();
      const normalized = normalizeNameForMatch(query);
      if (!normalized) return nodes[0] || null;
      return nodes.find((node) => normalizeNameForMatch(node.label) === normalized)
        || nodes.find((node) => normalizeNameForMatch(node.label).startsWith(normalized))
        || nodes.find((node) => normalizeNameForMatch(node.summary).includes(normalized))
        || nodes[0]
        || null;
    }

    function renderAll() {
      ensurePositions(visibleNodes());
      renderFilters();
      renderResults();
      renderQueue();
      renderCompareTray();
      renderBadges();
      renderStatus();
      renderGraph();
    }

    function renderFilters() {
      const nodeCounts = { articles: 0, entities: 0, events: 0 };
      const edgeCounts = {};
      state.nodes.forEach((node) => { nodeCounts[node.kind] = (nodeCounts[node.kind] || 0) + 1; });
      state.edges.forEach((edge) => { edgeCounts[edge.kind] = (edgeCounts[edge.kind] || 0) + 1; });
      document.getElementById("nodeFilters").innerHTML = ["entities","events","articles"].map((kind) => '<label class="check"><input type="checkbox" data-node-filter="'+kind+'" '+(state.filters.nodes.has(kind) ? "checked" : "")+'><span>'+esc(labelOf(kind, nodeKindLabels))+'</span><span class="count">'+fmt.format(nodeCounts[kind] || 0)+'</span></label>').join("");
      const edgeKinds = Array.from(new Set(["dj_collaboration","performed_at","hosted_at","frequent_venue","organized_by","mentions_entity","mentions_event","same_article", ...Array.from(state.edges.values()).map((edge) => edge.kind).filter(Boolean)]));
      document.getElementById("edgeFilters").innerHTML = edgeKinds.map((kind) => '<label class="check"><input type="checkbox" data-edge-filter="'+kind+'" '+(state.filters.edges.has(kind) ? "checked" : "")+'><span>'+esc(labelOf(kind, edgeKindLabels))+'</span><span class="count">'+fmt.format(edgeCounts[kind] || 0)+'</span></label>').join("");
      for (const input of document.querySelectorAll("[data-node-filter]")) {
        input.onchange = () => { input.checked ? state.filters.nodes.add(input.dataset.nodeFilter) : state.filters.nodes.delete(input.dataset.nodeFilter); renderAll(); };
      }
      for (const input of document.querySelectorAll("[data-edge-filter]")) {
        input.onchange = () => { input.checked ? state.filters.edges.add(input.dataset.edgeFilter) : state.filters.edges.delete(input.dataset.edgeFilter); renderAll(); };
      }
    }

    function renderSavedSearches() {
      const items = ["DADA","OIL","TAG","DONG 洞","MaFoL","Do Hits","Howie Lee","俱乐部","厂牌","mixtape"];
      document.getElementById("savedSearches").innerHTML = items.map((item) => '<button class="chip" type="button" data-search="'+esc(item)+'">'+esc(item)+'</button>').join("");
      for (const button of document.querySelectorAll("[data-search]")) {
        button.onclick = () => {
          document.getElementById("q").value = button.dataset.search;
          loadSeed();
        };
      }
    }

    function renderResults() {
      document.getElementById("results").innerHTML = state.results.map((item) => {
        const active = state.relationTargets.has(item.id);
        return '<div class="result-row"><button class="result-main" type="button" data-jump-node="'+esc(item.id)+'"><b>'+esc(item.label)+'</b><span>'+esc(item.meta)+'</span></button><button class="pick '+(active ? "active" : "")+'" type="button" data-pick-node="'+esc(item.id)+'">'+(active ? "已选" : "多选")+'</button></div>';
      }).join("") || '<div class="empty">没有结果</div>';
      bindJumpButtons(document.getElementById("results"));
    }

    function renderQueue() {
      document.getElementById("queue").innerHTML = state.queue.map((item) => '<button type="button" data-jump-node="'+esc(item.id)+'"><b>'+esc(item.label)+'</b><span>'+esc(item.meta)+'</span></button>').join("") || '<div class="empty">还没有探索记录</div>';
      bindJumpButtons(document.getElementById("queue"));
    }

    function renderCompareTray() {
      const tray = document.getElementById("compareTray");
      if (!tray) return;
      const targets = Array.from(state.relationTargets.values());
      tray.innerHTML = targets.length
        ? targets.map((node) => '<button class="target-chip" type="button" data-remove-target="'+esc(node.id)+'">'+esc(node.label || node.id)+'</button>').join("")
        : '<span class="target-chip empty">还没有多选目标</span>';
      for (const button of tray.querySelectorAll("[data-remove-target]")) {
        button.onclick = () => {
          state.relationTargets.delete(button.dataset.removeTarget);
          renderCompareTray();
          renderResults();
        };
      }
    }

    function setSearchFromNode(node) {
      if (!node) return;
      const input = document.getElementById("q");
      if (input) input.value = node.label || node.primaryId || node.id;
    }

    function toggleRelationTarget(nodeId) {
      const node = state.nodes.get(nodeId);
      if (!node) return;
      if (state.relationTargets.has(nodeId)) state.relationTargets.delete(nodeId);
      else state.relationTargets.set(nodeId, node);
      renderCompareTray();
      renderResults();
    }

    function bindJumpButtons(root) {
      if (!root) return;
      for (const button of root.querySelectorAll("[data-jump-node]")) {
        button.onclick = () => {
          const node = state.nodes.get(button.dataset.jumpNode);
          setSearchFromNode(node);
          selectNode(button.dataset.jumpNode);
          if (node) focusForceNode(node);
        };
      }
      for (const button of root.querySelectorAll("[data-pick-node]")) {
        button.onclick = (event) => {
          event.stopPropagation();
          toggleRelationTarget(button.dataset.pickNode);
        };
      }
      for (const button of root.querySelectorAll("[data-search-label]")) {
        button.onclick = () => {
          const label = button.dataset.searchLabel || "";
          if (!label) return;
          document.getElementById("q").value = label;
          loadSeed();
        };
      }
    }

    async function exploreRelationTargets() {
      const targets = Array.from(state.relationTargets.values());
      if (!targets.length) return;
      document.getElementById("q").value = targets.map((node) => node.label || node.primaryId).join(" ↔ ");
      await selectNode(targets[0].id);
      for (const node of targets) {
        await expandNode(node.id);
      }
      fitGraph();
    }

    function renderBadges() {
      const payload = state.payload || {};
      const meta = payload.meta || {};
      const avatarCount = Array.from(state.nodes.values()).filter((node) => node.visual?.hasAvatar).length;
      const outlinkCount = Array.from(state.nodes.values()).filter((node) => node.hasExternalLinks).length;
      document.getElementById("graphBadges").innerHTML = [
        '<span class="badge"><strong>'+fmt.format(state.nodes.size)+'</strong> 节点</span>',
        '<span class="badge"><strong>'+fmt.format(state.edges.size)+'</strong> 关系</span>',
        '<span class="badge"><strong>'+fmt.format(state.pinned.size)+'</strong> 固定</span>',
        meta.lens ? '<span class="badge">'+esc(meta.lens)+' · '+esc(meta.lod || state.lod)+'</span>' : '',
        meta.truncation?.nodesTruncated || meta.truncation?.edgesTruncated ? '<span class="badge">LOD 截断</span>' : '',
        avatarCount || outlinkCount ? '<span class="badge"><strong>'+fmt.format(avatarCount)+'</strong> 头像 · <strong>'+fmt.format(outlinkCount)+'</strong> 外链</span>' : '',
        '<span class="badge">'+esc(labelOf(payload.mode || "seed", modeLabels))+'</span>',
        payload.notFound ? '<span class="badge err">未找到</span>' : ''
      ].join("");
    }

    function renderStatus() {
      const payload = state.payload || {};
      const safety = payload.safety || {};
      const meta = payload.meta || {};
      const db = payload.retrieval?.dbPath || "atlas.sqlite";
      const identity = payload.retrieval?.dbIdentity;
      const dbLabel = identity?.source || identity?.label || db;
      document.getElementById("dbLine").textContent = dbLabel;
      document.getElementById("statusbar").innerHTML = [
        '<span>节点 '+fmt.format(state.nodes.size)+'</span>',
        '<span>关系 '+fmt.format(state.edges.size)+'</span>',
        '<span>延迟 '+fmt.format(state.lastLatency)+'ms</span>',
        '<span>渲染 '+state.renderer+'</span>',
        '<span>LOD '+esc(meta.lod || state.lod)+'</span>',
        '<span>Lens '+esc(meta.lens || "atlas")+'</span>',
        '<span>只读 '+(identity?.readOnly ? "是" : "否")+'</span>',
        '<span>批量导出 '+(safety.bulkExportEnabled ? "开启" : "关闭")+'</span>',
        '<span>Raw DB '+(meta.safety?.rawDbExposed ? "暴露" : "隐藏")+'</span>',
        '<span>数据 '+esc(dbLabel)+'</span>'
      ].join("");
    }

    async function ensureAtlasSession() {
      const status = await api("/api/v1/atlas/session/status");
      state.session = { ...state.session, ...status };
      if (!status.requireSession || status.hasSession) {
        document.getElementById("sessionGate").classList.remove("active");
        return true;
      }
      renderSessionGate(status);
      return false;
    }

    async function fetchWithTimeout(url, options = {}, timeoutMs = 10000) {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), timeoutMs);
      try {
        return await fetch(url, { ...options, signal: controller.signal });
      } catch (error) {
        if (error?.name === "AbortError") throw new Error("请求超时 " + Math.round(timeoutMs / 1000) + "s");
        throw error;
      } finally {
        window.clearTimeout(timer);
      }
    }

    function loadTurnstileScript() {
      if (window.turnstile?.render) return Promise.resolve();
      const existing = document.getElementById("cf-turnstile-script");
      if (existing) return new Promise((resolve, reject) => {
        existing.addEventListener("load", resolve, { once: true });
        existing.addEventListener("error", reject, { once: true });
      });
      return new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.id = "cf-turnstile-script";
        script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
        script.async = true;
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }

    function clearTurnstileFallbackTimer() {
      if (state.session.turnstileFallbackTimer) {
        window.clearTimeout(state.session.turnstileFallbackTimer);
        state.session.turnstileFallbackTimer = null;
      }
    }

    function resetTurnstileWidget() {
      clearTurnstileFallbackTimer();
      if (state.session.turnstileWidgetId != null && window.turnstile) {
        try {
          if (typeof window.turnstile.remove === "function") window.turnstile.remove(state.session.turnstileWidgetId);
          else if (typeof window.turnstile.reset === "function") window.turnstile.reset(state.session.turnstileWidgetId);
        } catch {}
      }
      state.session.turnstileWidgetId = null;
      const box = document.getElementById("turnstileBox");
      if (box) box.innerHTML = "";
    }

    function scheduleTurnstileFallback() {
      clearTurnstileFallbackTimer();
      if (!state.session.fallbackChallengeEnabled) return;
      state.session.turnstileFallbackTimer = window.setTimeout(() => {
        const gate = document.getElementById("sessionGate");
        if (!gate?.classList.contains("active") || state.session.fallbackBusy) return;
        runFallbackAtlasSession("Turnstile 未完成，正在切换备用浏览器验证。");
      }, 1800);
    }

    async function sha256Hex(input) {
      const bytes = new TextEncoder().encode(input);
      const digest = await window.crypto.subtle.digest("SHA-256", bytes);
      return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    }

    function leadingZeroBits(hex) {
      let count = 0;
      for (const char of String(hex || "")) {
        const value = Number.parseInt(char, 16);
        if (!Number.isFinite(value)) return -1;
        if (value === 0) {
          count += 4;
          continue;
        }
        return count + (4 - value.toString(2).length);
      }
      return count;
    }

    function nextFrame() {
      return new Promise((resolve) => {
        if (typeof window.requestAnimationFrame === "function") window.requestAnimationFrame(resolve);
        else window.setTimeout(resolve, 0);
      });
    }

    async function solveFallbackChallenge(challenge) {
      const payload = String(challenge?.payload || "");
      const signature = String(challenge?.signature || "");
      const difficulty = Number(challenge?.difficulty || 12);
      if (!payload || !signature || !Number.isFinite(difficulty)) throw new Error("备用验证挑战无效");
      if (!window.crypto?.subtle) throw new Error("当前浏览器不支持 WebCrypto");
      for (let attempt = 0; attempt < 1000000; attempt += 1) {
        const proof = String(attempt);
        const hash = await sha256Hex(payload + "." + signature + "." + proof);
        if (leadingZeroBits(hash) >= difficulty) return proof;
        if (attempt > 0 && attempt % 200 === 0) await nextFrame();
      }
      throw new Error("备用验证计算超时");
    }

    async function runFallbackAtlasSession(reason = "正在执行备用浏览器验证。") {
      if (state.session.fallbackBusy) return;
      clearTurnstileFallbackTimer();
      state.session.fallbackBusy = true;
      const msg = document.getElementById("gateMsg");
      if (msg) msg.textContent = reason;
      try {
        const challengeRes = await fetchWithTimeout("/api/v1/atlas/session/fallback-challenge", { headers: { Accept: "application/json" } }, 8000);
        const challenge = await challengeRes.json().catch(() => null);
        if (!challengeRes.ok) throw new Error(challenge?.error?.message || "备用验证挑战返回 " + challengeRes.status);
        const proof = await solveFallbackChallenge(challenge);
        if (msg) msg.textContent = "正在建立只读访问会话。";
        const sessionRes = await fetchWithTimeout("/api/v1/atlas/session/fallback", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ payload: challenge.payload, signature: challenge.signature, proof })
        }, 10000);
        const payload = await sessionRes.json().catch(() => null);
        if (!sessionRes.ok) throw new Error(payload?.error?.message || "备用验证返回 " + sessionRes.status);
        state.session.hasSession = true;
        document.getElementById("sessionGate").classList.remove("active");
        await loadSeed();
      } catch (error) {
        if (msg) msg.textContent = "备用验证失败：" + (error?.message || "未知错误");
      } finally {
        state.session.fallbackBusy = false;
      }
    }

    function turnstileErrorMessage(code) {
      if (String(code).startsWith("110200")) return "验证域名未授权（Turnstile " + code + "）。请打开保护域验证。";
      if (String(code).startsWith("200500")) return "验证 iframe 加载失败（Turnstile " + code + "）。请检查浏览器插件或网络拦截。";
      if (String(code).startsWith("600")) return "Cloudflare 安全检查失败（Turnstile " + code + "）。正在切换备用浏览器验证。";
      return "验证加载失败（Turnstile " + code + "）。请刷新状态或使用备用验证。";
    }

    function renderSessionGate(status) {
      const gate = document.getElementById("sessionGate");
      const canVerify = Boolean(status.configured && status.siteKey);
      const canFallback = Boolean(status.fallbackChallengeEnabled);
      state.session.fallbackChallengeEnabled = canFallback;
      gate.classList.add("active");
      gate.innerHTML =
        '<div class="gate-card"><h2>Atlas 已锁定</h2><p>图谱数据面需要通过浏览器验证后才能加载。公开层只返回限量图谱视图，不暴露暗数据库、SQLite 文件或完整导出。</p>'+
        (canVerify ? '<div class="gate-box" id="turnstileBox"></div><p id="gateMsg">等待验证。</p>' : '<p class="err">会话门禁已开启，但 Turnstile 站点密钥未配置。</p>')+
        '<div class="gate-actions">'+
        (canFallback ? '<button id="gateFallbackBtn" type="button">备用验证</button>' : '')+
        '<button id="gateRefreshBtn" type="button">刷新状态</button>'+
        '<button id="gateProtectedBtn" type="button">打开保护域验证</button></div>'+
        '</div>';
      document.getElementById("gateRefreshBtn")?.addEventListener("click", async () => {
        resetTurnstileWidget();
        await ensureAtlasSession();
      });
      document.getElementById("gateFallbackBtn")?.addEventListener("click", () => runFallbackAtlasSession());
      document.getElementById("gateProtectedBtn")?.addEventListener("click", () => {
        window.open("https://atlas.huaidj.club/atlas/graph", "_top", "noopener");
      });
      if (!canVerify) return;
      scheduleTurnstileFallback();
      loadTurnstileScript().then(() => {
        if (!gate.classList.contains("active") || state.session.hasSession) return;
        resetTurnstileWidget();
        state.session.turnstileWidgetId = window.turnstile.render("#turnstileBox", {
          sitekey: status.siteKey,
          callback: async (token) => {
            clearTurnstileFallbackTimer();
            document.getElementById("gateMsg").textContent = "正在建立只读访问会话。";
            let res;
            try {
              res = await fetchWithTimeout("/api/v1/atlas/session", {
                method: "POST",
                headers: { "Content-Type": "application/json", Accept: "application/json" },
                body: JSON.stringify({ token })
              }, 8000);
            } catch (error) {
              resetTurnstileWidget();
              if (canFallback) {
                await runFallbackAtlasSession("Turnstile 会话建立超时，正在切换备用验证。");
                return;
              }
              document.getElementById("gateMsg").textContent = "验证失败：" + (error?.message || "网络错误");
              return;
            }
            if (!res.ok) {
              const payload = await res.json().catch(() => null);
              resetTurnstileWidget();
              if (canFallback) {
                await runFallbackAtlasSession("Turnstile 未能建立会话，正在切换备用验证。");
                return;
              }
              document.getElementById("gateMsg").textContent = payload?.error?.message || "验证失败，请刷新后重试。";
              return;
            }
            gate.classList.remove("active");
            await loadSeed();
          },
          "error-callback": (errorCode) => {
            const code = String(errorCode || "unknown");
            resetTurnstileWidget();
            const msg = document.getElementById("gateMsg");
            if (msg) msg.textContent = turnstileErrorMessage(code);
            if (canFallback && code.startsWith("600")) window.setTimeout(() => runFallbackAtlasSession(), 250);
          },
          "expired-callback": () => {
            resetTurnstileWidget();
            const msg = document.getElementById("gateMsg");
            if (msg) msg.textContent = "验证已过期，请重新验证。";
            window.setTimeout(() => renderSessionGate(status), 250);
          },
          "timeout-callback": () => {
            resetTurnstileWidget();
            if (canFallback) runFallbackAtlasSession("Cloudflare 验证超时，正在切换备用浏览器验证。");
          },
          "unsupported-callback": () => {
            resetTurnstileWidget();
            if (canFallback) runFallbackAtlasSession("当前浏览器不支持 Turnstile，正在切换备用浏览器验证。");
          }
        });
        scheduleTurnstileFallback();
      }).catch(() => {
        const msg = document.getElementById("gateMsg");
        if (msg) msg.textContent = "Turnstile 脚本加载失败，正在切换备用验证。";
        if (canFallback) runFallbackAtlasSession();
      });
    }

    function avatarTextureCanvas(node) {
      const canvas = document.createElement("canvas");
      canvas.width = 128;
      canvas.height = 128;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#10150d";
      ctx.fillRect(0, 0, 128, 128);
      ctx.beginPath();
      ctx.arc(64, 64, 59, 0, Math.PI * 2);
      ctx.fillStyle = nodeColor(node);
      ctx.globalAlpha = 0.34;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 5;
      ctx.strokeStyle = nodeColor(node);
      ctx.stroke();
      ctx.fillStyle = "#e9e5cf";
      ctx.font = "700 34px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(node.label || "?").trim().slice(0, 2).toUpperCase(), 64, 66);
      return canvas;
    }

    function drawAvatarIntoCanvas(canvas, img, node) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, 128, 128);
      ctx.save();
      ctx.beginPath();
      ctx.arc(64, 64, 58, 0, Math.PI * 2);
      ctx.clip();
      const ratio = Math.max(128 / img.width, 128 / img.height);
      const width = img.width * ratio;
      const height = img.height * ratio;
      ctx.drawImage(img, (128 - width) / 2, (128 - height) / 2, width, height);
      ctx.restore();
      ctx.lineWidth = 5;
      ctx.strokeStyle = nodeColor(node);
      ctx.beginPath();
      ctx.arc(64, 64, 59, 0, Math.PI * 2);
      ctx.stroke();
    }

    function build3dNodeObject(node) {
      const THREE = window.THREE;
      const avatarUrl = node.visual?.avatarUrl || "";
      if (!THREE) return undefined;
      const cacheKey = node.id + "|" + avatarUrl + "|" + nodeColor(node) + "|" + state.pinned.has(node.id) + "|" + (state.selectedId === node.id);
      if (state.nodeObjectCache.has(cacheKey)) return state.nodeObjectCache.get(cacheKey);
      const size = Math.max(6, nodeRadius(node));
      if (!avatarUrl) {
        const group = new THREE.Group();
        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(size, 16, 16),
          new THREE.MeshBasicMaterial({ color: nodeColor(node), transparent: true, opacity: 0.94 })
        );
        group.add(sphere);
        if (node.seed || state.pinned.has(node.id) || state.selectedId === node.id) {
          const ring = new THREE.Mesh(
            new THREE.RingGeometry(size * 1.42, size * 1.62, 40),
            new THREE.MeshBasicMaterial({ color: node.seed ? 0xffffff : nodeColor(node), transparent: true, opacity: 0.48, side: THREE.DoubleSide })
          );
          group.add(ring);
        }
        state.nodeObjectCache.set(cacheKey, group);
        return group;
      }
      const group = new THREE.Group();
      const canvas = avatarTextureCanvas(node);
      const texture = new THREE.CanvasTexture(canvas);
      const spriteSize = Math.max(22, nodeRadius(node) * 2.2);
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
      sprite.scale.set(spriteSize, spriteSize, 1);
      group.add(sprite);
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(spriteSize * 0.53, spriteSize * 0.61, 40),
        new THREE.MeshBasicMaterial({ color: nodeColor(node), transparent: true, opacity: 0.72, side: THREE.DoubleSide })
      );
      group.add(ring);
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        drawAvatarIntoCanvas(canvas, img, node);
        texture.needsUpdate = true;
      };
      img.src = avatarUrl;
      state.nodeObjectCache.set(cacheKey, group);
      return group;
    }

    function forceGraphData() {
      const nodes = visibleNodes();
      return {
        nodes: nodes.map((node, index) => {
          if (!Number.isFinite(node.x) || !Number.isFinite(node.y) || !Number.isFinite(node.z)) {
            Object.assign(node, forceSeedPosition(node, index, nodes.length));
          }
          node.name = node.label;
          node.val = Math.max(1, Number(node.weight || 2));
          node.color = nodeColor(node);
          if (state.pinned.has(node.id)) {
            node.fx = Number.isFinite(node.x) ? node.x : 0;
            node.fy = Number.isFinite(node.y) ? node.y : 0;
            node.fz = Number.isFinite(node.z) ? node.z : 0;
          } else {
            delete node.fx;
            delete node.fy;
            delete node.fz;
          }
          return node;
        }),
        links: visibleEdges().map((edge) => ({
          ...edge,
          source: edge.source,
          target: edge.target,
          color: edgeColors[edge.kind] || "#5a646b",
          width: edge.kind === "same_article" ? 0.35 : Math.max(0.55, Math.min(1.8, (relationshipScoreOf(edge) || Number(edge.weight || 1)) / 6))
        }))
      };
    }

    function renderForceGraph() {
      const host = document.getElementById("forceHost");
      if (!state.ForceGraph3D || !host) return;
      const data = forceGraphData();
      if (!state.forceGraph) {
        try {
          state.forceGraph = new state.ForceGraph3D(host, { controlType: "orbit", rendererConfig: { antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: "high-performance" } });
        } catch {
          state.forceGraph = state.ForceGraph3D({ controlType: "orbit", rendererConfig: { antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: "high-performance" } })(host);
        }
        state.forceGraph
          .backgroundColor("#030403")
          .showNavInfo(false)
          .nodeId("id")
          .nodeVal("val")
          .nodeLabel((node) => esc(node.label || node.id))
          .nodeColor((node) => node.color || nodeColor(node))
          .nodeThreeObject((node) => build3dNodeObject(node))
          .nodeOpacity(0.94)
          .nodeResolution(12)
          .linkColor((link) => link.color || "#5a646b")
          .linkOpacity(0.38)
          .linkWidth((link) => link.width || 0.6)
          .linkDirectionalParticles((link) => link.kind === "same_article" ? 0 : 1)
          .linkDirectionalParticleSpeed(0.003)
          .linkDirectionalParticleWidth(0.8)
          .enableNodeDrag(true)
          .onNodeClick((node, event) => handleNodeActivate(node, event))
          .onNodeRightClick((node) => expandNode(node.id))
          .onLinkClick((link) => renderInspectorEdge(link));
        if (state.forceGraph.d3Force) {
          state.forceGraph.d3Force("charge").strength(-145);
          state.forceGraph.d3Force("link").distance((link) => link.kind === "same_article" ? 58 : 92);
        }
        if (state.forceGraph.d3VelocityDecay) state.forceGraph.d3VelocityDecay(0.24);
        if (state.forceGraph.cooldownTicks) state.forceGraph.cooldownTicks(90);
      }
      state.forceGraph.graphData(data);
      state.forceGraph.width(host.clientWidth || 800).height(host.clientHeight || 600);
      if (data.nodes.length && !state.selectedId) setTimeout(() => state.forceGraph.zoomToFit(800, 80), 120);
    }

    function colorToRgbaFloats(color, fallback) {
      let raw = String(color || fallback || "#76808a").trim();
      if (/^#[0-9a-f]{3}$/i.test(raw)) raw = "#" + raw.slice(1).split("").map((ch) => ch + ch).join("");
      const match = /^#([0-9a-f]{6})$/i.exec(raw);
      if (!match) return colorToRgbaFloats(fallback || "#76808a", "#76808a");
      const value = Number.parseInt(match[1], 16);
      return [((value >> 16) & 255) / 255, ((value >> 8) & 255) / 255, (value & 255) / 255, 1];
    }

    function cosmosData() {
      const nodes = visibleNodes();
      ensurePositions(nodes);
      const nodeIndex = new Map(nodes.map((node, index) => [node.id, index]));
      const edges = visibleEdges().filter((edge) => nodeIndex.has(edge.source) && nodeIndex.has(edge.target));
      const positions = new Float32Array(nodes.length * 2);
      const pointColors = new Float32Array(nodes.length * 4);
      const pointSizes = new Float32Array(nodes.length);
      nodes.forEach((node, index) => {
        const pos = state.positions.get(node.id) || { x: 0, y: 0 };
        const rgba = colorToRgbaFloats(nodeColor(node), "#76808a");
        positions[index * 2] = pos.x * 720;
        positions[index * 2 + 1] = pos.y * 720;
        pointColors.set(rgba, index * 4);
        pointSizes[index] = Math.max(2.5, Math.min(16, nodeRadius(node) * 0.72));
      });
      const links = new Float32Array(edges.length * 2);
      const linkColors = new Float32Array(edges.length * 4);
      const linkWidths = new Float32Array(edges.length);
      edges.forEach((edge, index) => {
        links[index * 2] = nodeIndex.get(edge.source);
        links[index * 2 + 1] = nodeIndex.get(edge.target);
        linkColors.set(colorToRgbaFloats(edgeColors[edge.kind] || "#5a646b", "#5a646b"), index * 4);
        linkWidths[index] = Math.max(0.35, Math.min(2.4, (relationshipScoreOf(edge) || Number(edge.weight || 1)) / 5));
      });
      return {
        nodes,
        edges,
        positions,
        pointColors,
        pointSizes,
        links,
        linkColors,
        linkWidths,
      };
    }

    function renderCosmos() {
      const host = document.getElementById("cosmosHost");
      if (!host || !state.CosmosGraphCtor) return renderCanvas();
      const data = cosmosData();
      try {
        if (!state.cosmosGraph) {
          state.cosmosGraph = new state.CosmosGraphCtor(host, {
            backgroundColor: "#030403",
            pointSize: 4,
            pointColor: "#18a8b8",
            linkWidth: 0.8,
            linkColor: "#5a646b",
            pixelRatio: Math.min(2, window.devicePixelRatio || 1),
            fitViewOnInit: true,
            fitViewDelay: 80,
            fitViewPadding: 0.18,
            enableDrag: true,
            simulation: { gravity: 0.18, repulsion: 1.4, linkSpring: 0.7, linkDistance: 18, friction: 0.88 },
            onPointClick: (index, position, event) => {
              const node = state.nodes.get(state.cosmosNodeIds[index]);
              if (node) handleNodeActivate(node, event || {});
            },
            onLinkClick: (index) => {
              const edge = state.edges.get(state.cosmosEdgeIds[index]);
              if (edge) renderInspectorEdge(edge);
            },
          });
        }
        if (state.cosmosGraph._isDestroyed) throw new Error("Cosmos.gl WebGL runtime unavailable");
        if (typeof state.cosmosGraph.setPointPositions !== "function" || typeof state.cosmosGraph.setLinks !== "function") {
          throw new Error("Unsupported Cosmos.gl runtime API");
        }
        state.cosmosNodeIds = data.nodes.map((node) => node.id);
        state.cosmosEdgeIds = data.edges.map((edge) => edge.id);
        state.cosmosGraph.setPointPositions(data.positions);
        state.cosmosGraph.setPointColors(data.pointColors);
        state.cosmosGraph.setPointSizes(data.pointSizes);
        state.cosmosGraph.setLinks(data.links);
        state.cosmosGraph.setLinkColors(data.linkColors);
        state.cosmosGraph.setLinkWidths(data.linkWidths);
        state.cosmosGraph.render(1);
        if (typeof state.cosmosGraph.fitView === "function") window.setTimeout(() => state.cosmosGraph?.fitView?.(250, 0.18), 120);
      } catch (error) {
        state.cosmosFailed = true;
        state.rendererPreference = state.ForceGraph3D ? "auto" : "sigma";
        syncRenderer();
      }
    }

    function renderGraph() {
      if (state.renderer === "cosmos" && state.CosmosGraphCtor) {
        renderCosmos();
        return;
      }
      if (state.renderer === "3d-force-graph" && state.ForceGraph3D) {
        renderForceGraph();
        return;
      }
      if (state.renderer === "sigma" && state.GraphCtor && state.SigmaCtor) {
        renderSigma();
        return;
      }
      renderCanvas();
    }

    function renderSigma() {
      const host = document.getElementById("sigmaHost");
      if (!state.sigmaGraph) state.sigmaGraph = new state.GraphCtor({ multi: true });
      state.sigmaGraph.clear();
      const nodes = visibleNodes();
      const edges = visibleEdges();
      ensurePositions(nodes);
      for (const node of nodes) {
        const pos = state.positions.get(node.id) || { x: 0, y: 0 };
        state.sigmaGraph.addNode(node.id, { x: pos.x, y: pos.y, label: node.label, size: nodeRadius(node), color: nodeColor(node) });
      }
      for (const edge of edges) {
        if (!state.sigmaGraph.hasNode(edge.source) || !state.sigmaGraph.hasNode(edge.target)) continue;
        state.sigmaGraph.addEdgeWithKey(edge.id, edge.source, edge.target, { color: edgeColors[edge.kind] || "#5a646b", size: edge.kind === "same_article" ? 0.7 : 1.2 });
      }
      if (!state.sigma) {
        state.sigma = new state.SigmaCtor(state.sigmaGraph, host, { renderLabels: true, labelDensity: 0.1, labelRenderedSizeThreshold: 9, defaultEdgeColor: "#5a646b" });
        state.sigma.on("clickNode", (event) => selectNode(event.node));
        state.sigma.on("doubleClickNode", (event) => expandNode(event.node));
        state.sigma.on("clickEdge", (event) => renderInspectorEdge(state.edges.get(event.edge)));
      }
      state.sigma.refresh();
    }

    function canvasScale(canvas) {
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      const w = Math.max(1, Math.floor(rect.width * ratio));
      const h = Math.max(1, Math.floor(rect.height * ratio));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      return { rect, ratio, width: w, height: h };
    }

    function toCanvas(pos, size) {
      const scale = Math.min(size.width, size.height) * 0.45 * state.pan.scale;
      return {
        x: size.width / 2 + state.pan.x + pos.x * scale,
        y: size.height / 2 + state.pan.y + pos.y * scale
      };
    }

    function renderCanvas() {
      const canvas = document.getElementById("graphCanvas");
      const size = canvasScale(canvas);
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, size.width, size.height);
      const nodes = visibleNodes();
      const edges = visibleEdges();
      ensurePositions(nodes);
      ctx.lineCap = "round";
      for (const edge of edges) {
        const source = state.nodes.get(edge.source);
        const target = state.nodes.get(edge.target);
        const sp = state.positions.get(edge.source);
        const tp = state.positions.get(edge.target);
        if (!source || !target || !sp || !tp) continue;
        const a = toCanvas(sp, size);
        const b = toCanvas(tp, size);
        ctx.beginPath();
        ctx.strokeStyle = edgeColors[edge.kind] || "#5a646b";
        ctx.globalAlpha = edge.kind === "same_article" ? 0.24 : 0.48;
        ctx.lineWidth = edge.kind === "same_article" ? 0.8 * size.ratio : 1.35 * size.ratio;
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      for (const node of nodes) {
        const pos = state.positions.get(node.id);
        if (!pos) continue;
        const p = toCanvas(pos, size);
        const r = nodeRadius(node) * size.ratio;
        const selected = node.id === state.selectedId;
        ctx.beginPath();
        ctx.fillStyle = selected ? "#fff" : nodeColor(node);
        ctx.strokeStyle = selected ? nodeColor(node) : "rgba(255,255,255,.58)";
        ctx.lineWidth = selected ? 3 * size.ratio : 1 * size.ratio;
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        if (node.seed) {
          ctx.beginPath();
          ctx.strokeStyle = "rgba(255,255,255,.42)";
          ctx.lineWidth = 1 * size.ratio;
          ctx.arc(p.x, p.y, r + 6 * size.ratio, 0, Math.PI * 2);
          ctx.stroke();
        }
        if (state.pinned.has(node.id) || node.visual?.hasAvatar) {
          ctx.beginPath();
          ctx.strokeStyle = state.pinned.has(node.id) ? "rgba(182,255,59,.72)" : "rgba(24,168,184,.62)";
          ctx.lineWidth = 2 * size.ratio;
          ctx.arc(p.x, p.y, r + 10 * size.ratio, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
      const labelNodes = nodes.filter((node) => node.seed || node.id === state.selectedId || Number(node.weight || 0) > 6).slice(0, 34);
      ctx.font = Math.max(11, 12 * size.ratio) + "px Inter, Noto Sans SC, Segoe UI, sans-serif";
      ctx.textBaseline = "top";
      for (const node of labelNodes) {
        const pos = state.positions.get(node.id);
        if (!pos) continue;
        const p = toCanvas(pos, size);
        const label = String(node.label || "").slice(0, 32);
        const width = ctx.measureText(label).width;
        const y = p.y + (nodeRadius(node) + 5) * size.ratio;
        ctx.fillStyle = "rgba(16,20,24,.72)";
        ctx.fillRect(p.x - width / 2 - 5 * size.ratio, y - 2 * size.ratio, width + 10 * size.ratio, 17 * size.ratio);
        ctx.fillStyle = "#e8eeee";
        ctx.fillText(label, p.x - width / 2, y);
      }
    }

    function hitTest(clientX, clientY) {
      const canvas = document.getElementById("graphCanvas");
      const size = canvasScale(canvas);
      const x = (clientX - size.rect.left) * size.ratio;
      const y = (clientY - size.rect.top) * size.ratio;
      let best = null;
      let bestDistance = Infinity;
      for (const node of visibleNodes()) {
        const pos = state.positions.get(node.id);
        if (!pos) continue;
        const p = toCanvas(pos, size);
        const d = Math.hypot(p.x - x, p.y - y);
        if (d < nodeRadius(node) * size.ratio + 7 * size.ratio && d < bestDistance) {
          best = node;
          bestDistance = d;
        }
      }
      return best;
    }

    function focusForceNode(node) {
      if (!state.forceGraph || !node) return;
      const distance = 220;
      const distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
      state.forceGraph.cameraPosition(
        { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
        node,
        700,
      );
    }

    function togglePinNode(nodeId) {
      if (!nodeId) return;
      if (state.pinned.has(nodeId)) state.pinned.delete(nodeId);
      else state.pinned.add(nodeId);
      const node = state.nodes.get(nodeId);
      if (node) putQueue(node, state.pinned.has(nodeId) ? "pin" : "unpin");
      renderAll();
      if (node && state.selectedId === nodeId) renderInspectorNode(node, null, null);
    }

    function handleNodeActivate(node, event) {
      if (!node) return;
      if (event?.shiftKey) {
        togglePinNode(node.id);
        return;
      }
      const now = Date.now();
      const isDouble = state.lastClick.id === node.id && now - state.lastClick.at < 360;
      state.lastClick = { id: node.id, at: now };
      if (isDouble) expandNode(node.id);
      else selectNode(node.id);
      focusForceNode(node);
    }

    async function selectNode(nodeId) {
      const node = state.nodes.get(nodeId);
      if (!node) return;
      state.selectedId = nodeId;
      putQueue(node, "select");
      renderGraph();
      renderInspectorNode(node, null, null);
      try {
        const detailPromise = api("/api/v1/stage7/" + node.kind + "/" + encodeURIComponent(node.primaryId) + "?relatedLimit=20");
        const profilePromise = node.kind === "entities"
          ? api("/api/v1/stage7/graph/profile?id=" + encodeURIComponent(node.primaryId) + "&limit=40&eventLimit=18&collaboratorLimit=18&venueLimit=12&articleLimit=10")
          : Promise.resolve(null);
        const [detail, profile] = await Promise.all([detailPromise, profilePromise]);
        renderInspectorNode(node, detail, profile);
        renderIdentityCandidates(node);
      } catch (error) {
        renderInspectorError(node, error);
      }
    }

    async function expandNode(nodeId) {
      const node = state.nodes.get(nodeId);
      if (!node || state.busy) return;
      setBusy(true);
      putQueue(node, "expand");
      try {
        const depth = document.getElementById("depth").value || "1";
        const payload = await api("/api/v1/stage7/graph/expand?nodeId=" + encodeURIComponent(node.id) + "&depth=" + encodeURIComponent(depth) + "&limit=180&lod=" + encodeURIComponent(activeLod()));
        applyPayload(payload, true);
        state.selectedId = node.id;
      } catch (error) {
        renderInspectorError(node, error);
      } finally {
        setBusy(false);
      }
    }

    function externalLinkHtml(link) {
      if (!link?.url) return "";
      const label = link.label || link.domain || link.url;
      const meta = [link.domain, link.kind].filter(Boolean).join(" · ");
      return '<a class="external" target="_blank" rel="noopener noreferrer nofollow" href="'+esc(link.url)+'">'+esc(label)+(meta ? '<span class="tiny"> · '+esc(meta)+'</span>' : '')+'</a>';
    }

    function normalizeNameForMatch(value) {
      return String(value || "").toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, "");
    }

    async function identityCandidatesFor(node) {
      if (!node || node.kind !== "entities") return [];
      if (!state.identityReviewItems) {
        const payload = await api("/api/v1/stage7/identity-review?limit=200");
        state.identityReviewItems = payload.items || [];
      }
      const label = normalizeNameForMatch(node.label);
      const primary = normalizeNameForMatch(node.primaryId);
      return state.identityReviewItems
        .filter((item) => {
          const subject = normalizeNameForMatch(item.subjectName);
          return subject && (subject === label || subject === primary || label.includes(subject) || subject.includes(label));
        })
        .slice(0, 6);
    }

    async function renderIdentityCandidates(node) {
      const target = document.getElementById("identityCandidates");
      if (!target || !node || node.id !== state.selectedId) return;
      try {
        const candidates = await identityCandidatesFor(node);
        if (!candidates.length) {
          target.innerHTML = '<h3>候选主页</h3><div class="empty">暂无候选主页</div>';
          return;
        }
        target.innerHTML = '<h3>候选主页</h3><div class="links">'+candidates.map((item) => {
          const proof = item.identityProof ? "身份已举证" : item.acceptedForGraph ? "已接受候选" : "需要举证";
          return externalLinkHtml({ url: item.url, label: item.domain || item.subjectName || "候选主页", domain: item.domain, kind: proof });
        }).join("")+'</div><p class="tiny">候选主页只作为证据入口，不等于已接受图谱关系。</p>';
      } catch (error) {
        target.innerHTML = '<h3>候选主页</h3><div class="empty err">'+esc(error.message || error)+'</div>';
      }
    }

    function edgeEndpointId(value) {
      return typeof value === "object" ? value.id : value;
    }

    function renderInspectorEdge(edge) {
      if (!edge) return;
      const sourceId = edgeEndpointId(edge.source);
      const targetId = edgeEndpointId(edge.target);
      const source = state.nodes.get(sourceId);
      const target = state.nodes.get(targetId);
      const relationScore = scoreText(relationshipScoreOf(edge));
      const evidenceLabel = edge.evidenceCount ? "公开证据 " + fmt.format(edge.evidenceCount) : "证据待展开";
      document.getElementById("inspector").innerHTML =
        '<section class="section"><h2 class="title">'+esc(edgeDisplayLabel(edge))+'</h2><div class="meta">'+
        '<span class="tag green">'+esc(labelOf(edge.kind, edgeKindLabels) || "关系")+'</span>'+
        '<span class="tag">'+esc(edge.directed ? "有方向" : "无方向")+'</span>'+
        '</div></section>'+
        '<section class="section"><h3>关系指标</h3><div class="statgrid">'+
        '<div class="stat"><b>'+esc(relationScore || "-")+'</b><span>关系分</span></div>'+
        '<div class="stat"><b>'+esc(edge.evidenceCount ? fmt.format(edge.evidenceCount) : "-")+'</b><span>公开证据</span></div>'+
        '</div><p class="tiny">'+esc(evidenceLabel)+'；活动交集只作为后台证据字段，不作为主展示口径。</p></section>'+
        '<section class="section"><h3>两端节点</h3><div class="links">'+
        (source ? '<a href="#" data-edge-node="'+esc(source.id)+'">'+esc(source.label || source.id)+'</a>' : '<div class="empty">'+esc(sourceId || "缺少来源节点")+'</div>')+
        (target ? '<a href="#" data-edge-node="'+esc(target.id)+'">'+esc(target.label || target.id)+'</a>' : '<div class="empty">'+esc(targetId || "缺少目标节点")+'</div>')+
        '</div></section>'+
        '<section class="section"><h3>证据规则</h3><p>'+esc(edge.kind === "same_article" ? "同一来源文章中共同出现；这不是身份接受边，只是公开读模型的上下文关系。" : edge.kind === "mentions_entity" ? "来源文章提及该实体。" : edge.kind === "mentions_event" ? "来源文章包含该活动。" : "公开读模型关系。")+'</p></section>';
      for (const button of document.querySelectorAll("[data-edge-node]")) {
        button.onclick = (event) => {
          event.preventDefault();
          selectNode(button.dataset.edgeNode);
        };
      }
    }

    function miniMetric(row, countKey) {
      const relationScore = scoreText(row.relationshipScore ?? row.relationScore ?? row.relationship_score ?? row.score);
      if (relationScore) return "关系分 " + relationScore;
      if (countKey === "confidence") {
        const confidence = scoreText(row[countKey]);
        return confidence ? "置信度 " + confidence : "";
      }
      const evidence = finite(row.evidenceCount ?? row.evidence_count);
      if (evidence) return "公开证据 " + fmt.format(evidence);
      const activity = finite(row.activityCount ?? row.activity_count);
      if (activity) return "活动记录 " + fmt.format(activity);
      const count = finite(row[countKey]);
      return count ? "记录 " + fmt.format(count) : "";
    }

    function miniRows(rows, labelKey = "label", countKey = "count", limit = 8) {
      const selected = (rows || []).slice(0, limit);
      if (!selected.length) return '<div class="empty">暂无数据</div>';
      return '<div class="mini-list">'+selected.map((row) => {
        const label = row[labelKey] || row.name || row.title || row.source_account || "";
        const metric = miniMetric(row, countKey);
        const sample = row.sample && !String(row.sample).includes("同台") ? row.sample : "";
        const meta = [metric, sample || row.place || row.time_text || row.source_account || ""].filter(Boolean).join(" · ");
        return '<button class="mini" type="button" data-search-label="'+esc(label)+'"><b>'+esc(label)+'</b><span>'+esc(meta || "点击跳转")+'</span></button>';
      }).join("")+'</div>';
    }

    function sourceRows(rows, limit = 10) {
      const selected = (rows || []).slice(0, limit);
      if (!selected.length) return '<div class="empty">暂无公开来源</div>';
      return '<div class="mini-list">'+selected.map((row) => {
        const id = row.article_uid || row.article_id || "";
        const title = row.title || id || "来源文章";
        const meta = [row.source_account, row.publish_time_status, row.event_count ? fmt.format(row.event_count) + " 活动" : ""].filter(Boolean).join(" · ");
        const href = id ? '/atlas/articles/'+encodeURIComponent(id) : '#';
        return '<a class="click-row" href="'+esc(href)+'"><b>'+esc(title)+'</b><span>'+esc(meta || "公开来源")+'</span></a>';
      }).join("")+'</div>';
    }

    function renderEvidencePanel(node, detail, profile) {
      const evidence = detail?.evidence || {};
      const refs = profile?.sources?.articles || [];
      const sampleEdges = Array.from(state.edges.values())
        .filter((edge) => edge.source === node.id || edge.target === node.id)
        .slice(0, 8);
      const edgeRows = sampleEdges.length
        ? '<div class="mini-list">'+sampleEdges.map((edge) => {
            const otherId = edge.source === node.id ? edge.target : edge.source;
            const other = state.nodes.get(otherId);
            const relationScore = scoreText(relationshipScoreOf(edge));
            return '<button class="mini" type="button" data-jump-node="'+esc(otherId)+'"><b>'+esc(other?.label || otherId)+'</b><span>'+esc([edgeDisplayLabel(edge), relationScore ? "关系分 " + relationScore : "", edge.evidenceCount ? "公开证据 " + fmt.format(edge.evidenceCount) : ""].filter(Boolean).join(" · "))+'</span></button>';
          }).join("")+'</div>'
        : '<div class="empty">暂无已载入关系证据</div>';
      return '<section class="section"><h3>信息来源</h3><p>'+esc(evidence.vectorTextPreview || node.summary || "当前节点来自 Atlas 公开只读聚合。")+'</p></section>'+
        '<section class="section"><h3>公开来源文章</h3>'+sourceRows(refs, 10)+'</section>'+
        '<section class="section"><h3>已载入关系证据</h3>'+edgeRows+'</section>';
    }

    function renderProfileSection(profile) {
      if (!profile) return '<section class="section"><h3>全量档案</h3><div class="empty">正在载入实体档案</div></section>';
      if (!profile.found) return '<section class="section"><h3>全量档案</h3><div class="empty">未找到实体档案</div></section>';
      const s = profile.summary || {};
      return '<section class="section"><h3>全量档案</h3><div class="statgrid">'+
        '<div class="stat"><b>'+fmt.format(s.exactEntityRows || 0)+'</b><span>实体出现</span></div>'+
        '<div class="stat"><b>'+fmt.format(s.sourceArticleCount || 0)+'</b><span>来源文章</span></div>'+
        '<div class="stat"><b>'+fmt.format(s.eventCount || 0)+'</b><span>历史活动</span></div>'+
        '<div class="stat"><b>'+fmt.format(s.collaboratorCount || 0)+'</b><span>关系人物</span></div>'+
        '</div>'+(s.sourceWindowTruncated ? '<p class="tiny">当前为公开窗口聚合；全量计数已保留，关系列表按权重截断。</p>' : '')+'</section>'+
        '<section class="section"><h3>常见账号 / 俱乐部</h3>'+miniRows(profile.sources?.accounts, "label", "count", 8)+'</section>'+
        '<section class="section"><h3>历史场地</h3>'+miniRows(profile.history?.venues, "label", "activityCount", 8)+'</section>'+
        '<section class="section"><h3>关系人物</h3>'+miniRows(profile.relationships?.collaborators, "label", "relationshipScore", 10)+'</section>'+
        '<section class="section"><h3>厂牌 / 组织</h3>'+miniRows(profile.relationships?.organizations, "label", "count", 8)+'</section>'+
        '<section class="section"><h3>历史活动样本</h3>'+miniRows(profile.history?.events, "name", "confidence", 8)+'</section>';
    }

    function renderInspectorNode(node, detail, profile) {
      const evidence = detail?.evidence || {};
      const related = detail?.related || {};
      const item = detail?.item || {};
      const visual = detail?.visual || node.visual || {};
      const externalLinks = [];
      const seenLinks = new Set();
      for (const link of [...(node.externalLinks || []), ...(detail?.externalLinks || []), ...(profile?.publicProfiles?.externalLinks || [])]) {
        if (!link?.url || seenLinks.has(link.url)) continue;
        seenLinks.add(link.url);
        externalLinks.push(link);
      }
      const links = [];
      if (node.detailHref) links.push('<a href="'+esc(node.detailHref)+'">打开详情页</a>');
      if (related.sourceArticle?.article_uid) links.push('<a href="/atlas/articles/'+encodeURIComponent(related.sourceArticle.article_uid)+'">'+esc(related.sourceArticle.title || related.sourceArticle.article_uid)+'</a>');
      const relatedEvents = (related.events || []).slice(0, 8).map((event) => '<a href="/atlas/events/'+encodeURIComponent(event.evid)+'">'+esc(event.name || event.evid)+'</a>').join("");
      const relatedEntities = (related.entities || []).slice(0, 8).map((entity) => '<a href="/atlas/entities/'+encodeURIComponent(entity.eid)+'">'+esc(entity.name || entity.eid)+'</a>').join("");
      const mediaHtml = visual.avatarUrl
        ? '<div class="avatar-card"><img src="'+esc(visual.avatarUrl)+'" alt=""><div><b>'+esc(node.label)+'</b><span>头像来自公开 Atlas 资产清单</span></div></div>'
        : '<div class="empty">头像位已预留，后续实体资产清单加入 /atlas-assets/... 后展示。</div>';
      document.getElementById("inspector").innerHTML =
        '<section class="section"><h2 class="title">'+esc(node.label)+'</h2><div class="meta">'+
        '<span class="tag '+(node.kind === "entities" ? "cyan" : node.kind === "events" ? "orange" : "")+'">'+esc(labelOf(node.kind, nodeKindLabels))+'</span>'+
        '<span class="tag">'+esc(node.subtype || "")+'</span>'+
        '<span class="tag green">'+esc(node.role || "related")+'</span>'+
        '<span class="tag">'+esc(node.clusterId || "")+'</span>'+
        '<span class="tag">'+esc(node.publicState || "public_rollup")+'</span>'+
        (node.city ? '<span class="tag amber">'+esc(node.city)+'</span>' : '')+
        (node.sourceArticleUid ? '<span class="tag green">'+esc(node.sourceArticleUid)+'</span>' : '')+
        (state.pinned.has(node.id) ? '<span class="tag green">已固定</span>' : '')+
        '</div><div class="actionbar"><button class="btn" id="pinNodeBtn" type="button">'+(state.pinned.has(node.id) ? "取消固定" : "固定")+'</button><button class="btn" id="expandNodeBtn" type="button">展开</button><button class="btn" id="targetNodeBtn" type="button">'+(state.relationTargets.has(node.id) ? "移出关系探索" : "加入关系探索")+'</button><button class="btn" id="searchNodeBtn" type="button">搜索同名</button></div></section>'+
        '<section class="section"><h3>媒体</h3>'+mediaHtml+'</section>'+
        renderEvidencePanel(node, detail, profile)+
        (node.kind === "entities" ? renderProfileSection(profile) : '')+
        '<section class="section"><h3>字段</h3><div class="kv">'+
        '<div><span>主 ID</span><span>'+esc(node.primaryId)+'</span></div>'+
        '<div><span>城市 / 地点</span><span>'+esc([node.city || item.city, node.place || item.place].filter(Boolean).join(" / "))+'</span></div>'+
        '<div><span>来源</span><span>'+esc(node.sourceArticleUid || evidence.sourceArticleUid || "")+'</span></div>'+
        '<div><span>置信度</span><span>'+esc(item.confidence ?? "")+'</span></div>'+
        '<div><span>权重 / 度</span><span>'+esc([node.metrics?.weight || node.weight || "", node.metrics?.degreeHint || ""].filter((v) => v !== "").join(" / "))+'</span></div>'+
        '<div><span>时间</span><span>'+esc(item.time_text || evidence.timeText || evidence.publishTimeStatus || "")+'</span></div>'+
        '</div></section>'+
        '<section class="section"><h3>外部链接</h3><div class="links">'+(externalLinks.map(externalLinkHtml).join("") || '<div class="empty">暂无已接受外链</div>')+'</div></section>'+
        '<section class="section" id="identityCandidates"><h3>候选主页</h3><div class="empty">选择已载入实体后查看候选主页</div></section>'+
        '<section class="section"><h3>本地链接</h3><div class="links">'+(links.join("") || '<div class="empty">暂无链接</div>')+'</div></section>'+
        '<section class="section"><h3>相关活动</h3><div class="links">'+(relatedEvents || '<div class="empty">暂无活动</div>')+'</div></section>'+
        '<section class="section"><h3>相关实体</h3><div class="links">'+(relatedEntities || '<div class="empty">暂无实体</div>')+'</div></section>';
      const pinButton = document.getElementById("pinNodeBtn");
      if (pinButton) pinButton.onclick = () => togglePinNode(node.id);
      const expandButton = document.getElementById("expandNodeBtn");
      if (expandButton) expandButton.onclick = () => expandNode(node.id);
      const targetButton = document.getElementById("targetNodeBtn");
      if (targetButton) targetButton.onclick = () => { toggleRelationTarget(node.id); renderInspectorNode(node, detail, profile); };
      const searchButton = document.getElementById("searchNodeBtn");
      if (searchButton) searchButton.onclick = () => { setSearchFromNode(node); loadSeed(); };
      bindJumpButtons(document.getElementById("inspector"));
    }

    function renderInspectorError(node, error) {
      document.getElementById("inspector").innerHTML = '<section class="section"><h2 class="title">'+esc(node?.label || "错误")+'</h2><p class="err">'+esc(error.message || error)+'</p></section>';
    }

    async function loadSeed() {
      if (state.busy) return;
      setBusy(true);
      try {
        if (state.session.requireSession && !state.session.hasSession) {
          const ok = await ensureAtlasSession();
          if (!ok) return;
        }
        const q = document.getElementById("q").value.trim();
        const kind = document.getElementById("kind").value;
        state.lod = activeLod();
        const path = "/api/v1/stage7/graph/seed?q=" + encodeURIComponent(q) + "&kind=" + encodeURIComponent(kind) + "&limit=140&lod=" + encodeURIComponent(state.lod);
        const payload = await api(path);
        state.session.hasSession = true;
        applyPayload(payload, false);
        const first = bestVisibleNodeForQuery(q);
        if (first) selectNode(first.id);
      } catch (error) {
        document.getElementById("results").innerHTML = '<div class="empty err">'+esc(error.message || error)+'</div>';
      } finally {
        setBusy(false);
      }
    }

    async function randomWalk() {
      if (state.busy) return;
      setBusy(true);
      try {
        const nodeId = state.selectedId || (visibleNodes()[0]?.id || "");
        const payload = await api("/api/v1/stage7/graph/random-walk?nodeId=" + encodeURIComponent(nodeId) + "&steps=3&fanout=10&limit=180&lod=" + encodeURIComponent(activeLod()));
        applyPayload(payload, true);
      } catch (error) {
        document.getElementById("results").innerHTML = '<div class="empty err">'+esc(error.message || error)+'</div>';
      } finally {
        setBusy(false);
      }
    }

    function fitGraph() {
      state.pan = { x: 0, y: 0, scale: 1 };
      if (state.sigma) state.sigma.getCamera().animatedReset();
      if (state.forceGraph) state.forceGraph.zoomToFit(900, 80);
      renderGraph();
    }

    function resetGraph() {
      state.selectedId = "";
      state.queue = [];
      fitGraph();
      loadSeed();
    }

    function saveSnapshot() {
      const a = document.createElement("a");
      if (state.forceGraph?.renderer) {
        const dom = state.forceGraph.renderer().domElement;
        a.href = dom.toDataURL("image/png");
      } else {
        renderCanvas();
        const canvas = document.getElementById("graphCanvas");
        a.href = canvas.toDataURL("image/png");
      }
      a.download = "atlas-graph-snapshot.png";
      a.click();
    }

    function bindCanvas() {
      const canvas = document.getElementById("graphCanvas");
      canvas.addEventListener("click", (event) => {
        const node = hitTest(event.clientX, event.clientY);
        if (node) handleNodeActivate(node, event);
      });
      canvas.addEventListener("dblclick", (event) => {
        const node = hitTest(event.clientX, event.clientY);
        if (node) expandNode(node.id);
      });
      canvas.addEventListener("wheel", (event) => {
        event.preventDefault();
        state.pan.scale = Math.max(0.35, Math.min(3, state.pan.scale * (event.deltaY > 0 ? 0.9 : 1.1)));
        renderGraph();
      }, { passive: false });
      canvas.addEventListener("pointerdown", (event) => {
        state.drag = { x: event.clientX, y: event.clientY, panX: state.pan.x, panY: state.pan.y };
        canvas.setPointerCapture(event.pointerId);
      });
      canvas.addEventListener("pointermove", (event) => {
        if (!state.drag) return;
        const ratio = window.devicePixelRatio || 1;
        state.pan.x = state.drag.panX + (event.clientX - state.drag.x) * ratio;
        state.pan.y = state.drag.panY + (event.clientY - state.drag.y) * ratio;
        renderGraph();
      });
      canvas.addEventListener("pointerup", () => { state.drag = null; });
    }

    document.getElementById("searchForm").addEventListener("submit", (event) => { event.preventDefault(); loadSeed(); });
    document.getElementById("layout").addEventListener("change", () => { state.positions.clear(); renderGraph(); });
    document.getElementById("lod").addEventListener("change", () => {
      state.lod = activeLod();
      if (state.rendererPreference === "auto") syncRenderer();
      loadSeed();
    });
    for (const button of document.querySelectorAll("[data-renderer]")) {
      button.addEventListener("click", () => {
        state.rendererPreference = button.dataset.renderer || "auto";
        syncRenderer();
      });
    }
    document.getElementById("roamBtn").addEventListener("click", () => {
      const btn = document.getElementById("roamBtn");
      if (state.roamTimer) {
        clearInterval(state.roamTimer);
        state.roamTimer = null;
        if (state.forceGraph?.controls) state.forceGraph.controls().autoRotate = false;
        btn.classList.remove("active");
      } else {
        if (state.forceGraph?.controls) {
          const controls = state.forceGraph.controls();
          controls.autoRotate = true;
          controls.autoRotateSpeed = 0.9;
        }
        randomWalk();
        state.roamTimer = setInterval(randomWalk, 4800);
        btn.classList.add("active");
      }
    });
    document.getElementById("fitBtn").addEventListener("click", fitGraph);
    document.getElementById("resetBtn").addEventListener("click", resetGraph);
    document.getElementById("shotBtn").addEventListener("click", saveSnapshot);
    document.getElementById("exploreRelationBtn").addEventListener("click", exploreRelationTargets);
    document.getElementById("clearCompareBtn").addEventListener("click", () => {
      state.relationTargets.clear();
      renderCompareTray();
      renderResults();
    });
    window.addEventListener("keydown", (event) => {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (event.key === "Escape") {
        state.selectedId = "";
        renderGraph();
        document.getElementById("inspector").innerHTML = '<section class="section"><h3>详情</h3><div class="empty">请选择一个节点</div></section>';
      }
      if ((event.key === "p" || event.key === "P") && state.selectedId) togglePinNode(state.selectedId);
      if ((event.key === "e" || event.key === "E") && state.selectedId) expandNode(state.selectedId);
    });
    window.addEventListener("resize", renderGraph);

    window.__atlasGraphRuntime = () => ({
      renderer: state.renderer,
      rendererPreference: state.rendererPreference,
      lod: state.lod,
      lens: state.meta?.lens || "",
      nodeCount: state.nodes.size,
      edgeCount: state.edges.size,
      schemaVersion: state.meta?.schemaVersion || "",
      truncated: state.meta?.truncated || false,
      safetyFlags: state.meta?.safetyFlags || [],
      rawDbExposed: state.meta?.safety?.rawDbExposed === true,
      cosmos: state.cosmosGraph ? {
        destroyed: state.cosmosGraph._isDestroyed === true,
        pointsNumber: state.cosmosGraph.graph?.pointsNumber || 0,
        linksNumber: state.cosmosGraph.graph?.linksNumber || 0,
        pointPositionsLength: state.cosmosGraph.graph?.pointPositions?.length || 0,
        linksLength: state.cosmosGraph.graph?.links?.length || 0,
        canvasWidth: state.cosmosGraph.canvas?.width || 0,
        canvasHeight: state.cosmosGraph.canvas?.height || 0,
        running: state.cosmosGraph.isSimulationRunning === true,
      } : null,
    });

    renderSavedSearches();
    bindCanvas();
    bootRenderer();
    ensureAtlasSession().then((ok) => { if (ok) loadSeed(); });
  </script>
</body>
</html>`;
}
