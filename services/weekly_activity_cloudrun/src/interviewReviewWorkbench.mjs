import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { buildDjInterviewReviewPacket } from "./interviewReviewPacket.mjs";

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function statusClass(item) {
  if (item.promotionGate?.result === "ready_for_human_review") return "status-ok";
  if (asArray(item.promotionGate?.blockers).includes("source_evidence_missing")) return "status-warn";
  return "status-blocked";
}

function tableRows(packet) {
  if (!packet.items.length) {
    return '<tr><td colspan="6" class="empty">No interview submissions in the selected sidecar.</td></tr>';
  }
  return packet.items.map((item) => {
    const blockers = asArray(item.promotionGate?.blockers).join(", ") || "none";
    const actions = asArray(item.reviewActions).join(", ");
    const source = item.sourceEvidence?.sourceRefId || item.sourceEvidence?.sourceUrlHash || "missing";
    return `<tr>
      <td><strong>${escapeHtml(item.djName)}</strong><span>${escapeHtml(item.city)}</span></td>
      <td>${escapeHtml(item.consentStatus)}</td>
      <td>${escapeHtml(source)}</td>
      <td>${escapeHtml(asArray(item.linkSummary?.musicPlatforms).join(", ") || "none")}</td>
      <td><mark class="${statusClass(item)}">${escapeHtml(blockers)}</mark></td>
      <td>${escapeHtml(actions)}</td>
    </tr>`;
  }).join("\n");
}

function jsonScript(packet) {
  return JSON.stringify(packet).replace(/</g, "\\u003c");
}

export function renderDjInterviewReviewWorkbenchHtml(packet) {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Atlas DJ Interview Review</title>
  <style>
    :root{--bg:#111214;--panel:#17191d;--panel2:#1d2026;--line:#2a2e36;--text:#e9e6dc;--muted:#9b9b92;--accent:#b6ff3b;--blue:#7eb8da;--warn:#d9a441;--bad:#e46d52;--ok:#67c587}
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--text);font:13px/1.45 "Segoe UI",Arial,sans-serif}
    .shell{height:100vh;display:grid;grid-template-rows:42px minmax(0,1fr) 28px}
    .topbar{display:flex;align-items:center;gap:12px;padding:0 14px;border-bottom:1px solid var(--line);background:#0e0f11}
    .brand{font-weight:700;letter-spacing:.02em}
    .cmd{margin-left:auto;display:flex;gap:8px;color:var(--muted)}
    .cmd span{border:1px solid var(--line);background:var(--panel);border-radius:5px;padding:4px 8px}
    .main{min-height:0;display:grid;grid-template-columns:220px minmax(0,1fr) 300px}
    aside,.inspector{min-height:0;background:var(--panel);border-right:1px solid var(--line);padding:14px;overflow:auto}
    .inspector{border-right:0;border-left:1px solid var(--line)}
    .nav-title,.pane-title{color:var(--muted);font-size:11px;text-transform:uppercase;margin-bottom:8px}
    .metric{display:grid;grid-template-columns:1fr auto;gap:8px;padding:7px 0;border-bottom:1px solid var(--line)}
    .metric span{color:var(--muted)}
    .metric strong{font-weight:700}
    .content{min-width:0;overflow:auto;background:#131519}
    .toolbar{height:38px;display:flex;align-items:center;gap:10px;padding:0 12px;border-bottom:1px solid var(--line);background:var(--panel2)}
    .filter{border:1px solid var(--line);border-radius:5px;background:#101216;color:var(--text);height:26px;padding:0 8px;min-width:260px}
    table{width:100%;border-collapse:collapse}
    th,td{border-bottom:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}
    th{position:sticky;top:0;background:#181b20;color:var(--muted);font-size:11px;text-transform:uppercase;z-index:1}
    td strong{display:block;font-size:13px}
    td span{display:block;color:var(--muted);font-size:12px;margin-top:2px}
    mark{display:inline-block;border-radius:4px;padding:2px 6px;background:#262a31;color:var(--text)}
    .status-ok{color:var(--ok);border:1px solid rgba(103,197,135,.4)}
    .status-warn{color:var(--warn);border:1px solid rgba(217,164,65,.45)}
    .status-blocked{color:var(--bad);border:1px solid rgba(228,109,82,.45)}
    .empty{height:160px;text-align:center;color:var(--muted)}
    .checklist{display:grid;gap:8px}
    .check{display:grid;grid-template-columns:1fr auto;gap:8px;border-bottom:1px solid var(--line);padding:7px 0}
    .check span{color:var(--muted)}
    .footer{display:flex;align-items:center;gap:12px;padding:0 12px;border-top:1px solid var(--line);background:#0e0f11;color:var(--muted);font-size:12px}
    .dot{width:7px;height:7px;border-radius:50%;background:var(--accent)}
  </style>
</head>
<body>
  <div class="shell" data-role="review-workbench">
    <header class="topbar">
      <div class="brand">Atlas DJ Interview Review</div>
      <div class="cmd"><span>Read only</span><span>No graph writes</span><span>No raw export</span></div>
    </header>
    <main class="main">
      <aside>
        <div class="nav-title">Packet</div>
        <div class="metric"><span>Total</span><strong>${packet.summary.total}</strong></div>
        <div class="metric"><span>Exported</span><strong>${packet.summary.exported}</strong></div>
        <div class="metric"><span>Source evidence</span><strong>${packet.summary.withSourceEvidence}</strong></div>
        <div class="metric"><span>Music links</span><strong>${packet.summary.withMusicLinks}</strong></div>
        <div class="metric"><span>Blocked</span><strong>${packet.summary.blockedBeforePromotion}</strong></div>
      </aside>
      <section class="content">
        <div class="toolbar">
          <input class="filter" aria-label="Filter" placeholder="Filter by DJ, city, blocker, source" oninput="filterRows(this.value)">
          <span>${escapeHtml(packet.generatedAt)}</span>
        </div>
        <table id="reviewTable">
          <thead><tr><th>DJ</th><th>Consent</th><th>Source</th><th>Music</th><th>Blockers</th><th>Actions</th></tr></thead>
          <tbody>${tableRows(packet)}</tbody>
        </table>
      </section>
      <aside class="inspector">
        <div class="pane-title">Safety</div>
        <div class="checklist">
          <div class="check"><span>Raw contact exported</span><strong>${packet.safety.rawContactExported}</strong></div>
          <div class="check"><span>Raw interview text exported</span><strong>${packet.safety.rawInterviewTextExported}</strong></div>
          <div class="check"><span>Public graph write</span><strong>${packet.safety.publicGraphWriteExecuted}</strong></div>
          <div class="check"><span>Production DB write</span><strong>${packet.safety.productionWriteExecuted}</strong></div>
          <div class="check"><span>Media cache/proxy</span><strong>${packet.safety.mediaCacheWritten || packet.safety.mediaProxyEnabled}</strong></div>
        </div>
      </aside>
    </main>
    <footer class="footer"><span class="dot"></span><span>Local reviewer workbench. Keep promotion blocked until human review, artist confirmation, source quote ref, and consent scope are complete.</span></footer>
  </div>
  <script id="packet-data" type="application/json">${jsonScript(packet)}</script>
  <script>
    function filterRows(query) {
      const needle = String(query || "").toLowerCase();
      for (const row of document.querySelectorAll("#reviewTable tbody tr")) {
        row.style.display = row.textContent.toLowerCase().includes(needle) ? "" : "none";
      }
    }
  </script>
</body>
</html>
`;
}

export async function writeDjInterviewReviewWorkbench(options = {}) {
  const outDir = options.outDir;
  if (!outDir) throw new Error("writeDjInterviewReviewWorkbench requires outDir.");
  const packet = options.packet || await buildDjInterviewReviewPacket(options);
  await mkdir(outDir, { recursive: true });
  const htmlPath = path.join(outDir, "dj_interview_review_workbench.html");
  await writeFile(htmlPath, renderDjInterviewReviewWorkbenchHtml(packet), "utf8");
  return { packet, htmlPath };
}
