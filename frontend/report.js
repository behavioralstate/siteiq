/* SiteIQ — render del report scan (scoreboard espandibile + priorità + checks). */
"use strict";

const GRADE_CLASS = { A: "sg-A", B: "sg-B", C: "sg-C", D: "sg-D", F: "sg-F" };
const LABELS = {
  performance: "Performance",
  accessibility: "Accessibilità",
  security: "Sicurezza",
  seo: "SEO",
  development: "Sviluppo Web",
};

function renderReport(report) {
  const box = $("#scan-report");
  box.hidden = false;
  if (!report) { box.textContent = "Risultato vuoto."; return; }

  const verdictClass = report.summary.verdict === "ok" ? "good"
    : report.summary.verdict === "critical" ? "critical" : "attention";
  const urlText = esc(report.url);
  const domain = esc(siteDomain(report.url));
  const checks = report.checks || {};

  let scores = "";
  for (const name of ["performance", "accessibility", "security", "seo", "development"]) {
    const s = report.scores[name];
    if (!s) continue;
    const cat = LABELS[name] || name;
    // lista check della categoria (se presenti)
    const catChecks = checks[name] || [];
    const checkBadges = catChecks.map((c) => {
      const icon = c.status === "ok" ? "✓" : c.status === "warn" ? "!" : "✗";
      const sevCls = "chk-" + c.status;
      return `<div class="check-item ${sevCls}">
                <span class="check-icon" aria-hidden="true">${icon}</span>
                <span class="check-label">${esc(c.label)}</span>
                <span class="check-detail">${esc(c.detail)}</span>
              </div>`;
    }).join("");
    const expandable = catChecks.length > 0
      ? `<button class="btn btn-ghost chk-toggle" data-cat="${esc(name)}" aria-expanded="false"
                 aria-controls="chk-${esc(name)}">Dettaglio verifiche (${catChecks.length})</button>
         <div class="check-list" id="chk-${esc(name)}" hidden>${checkBadges}</div>`
      : "";

    scores += `
      <div class="score-card">
        <div class="score-name">${cat}</div>
        <div class="score-row">
          <span class="score-val">${s.value}</span><span class="score-grade ${GRADE_CLASS[s.grade] || ""}">${s.grade}</span>
        </div>
        <div class="score-track"><i style="width:${s.value}%"></i></div>
        ${expandable}
      </div>`;
  }

  let recs = "";
  for (const rec of (report.recommendations || [])) {
    const pill = `pill-${rec.priority}`;
    recs += `
      <div class="rec-card">
        <div class="rec-head-static">
          <span class="rec-pill ${pill}">${rec.priority}</span>
          <span class="rec-title">${esc(rec.title)}</span>
          <span class="rec-effort">sforzo ${esc(rec.effort || "")}</span>
        </div>
        <div class="rec-body open">
          <p class="rec-detail">${esc(rec.detail)}</p>
          <p class="rec-evidence"><b>Evidenza:</b> ${esc(rec.evidence_ref || "")}</p>
        </div>
      </div>`;
  }
  if (!recs) recs = `<p class="empty-note">Nessun problema urgente rilevato. 🎉</p>`;

  // Sezione WordPress (solo se presente)
  let wpHtml = "";
  const wp = report.wordpress_security;
  if (wp && wp.is_wordpress) {
    const coreV = wp.core ? wp.core.version : "—";
    const coreVuln = wp.core && wp.core.vulnerabilities ? wp.core.vulnerabilities.length : 0;
    const coreBadge = coreVuln > 0 ? `<span class="wp-badge wp-bad">${coreVuln} vulnerabilita' core</span>`
      : coreVuln === 0 ? `<span class="wp-badge wp-ok">core ok</span>` : "";
    let pluginRows = "";
    for (const pl of (wp.plugins || [])) {
      const n = (pl.vulnerabilities || []).length;
      if (pl.status === "unknown") {
        // versione non rilevata dal crawler: non è un verdetto di vulnerabilità
        pluginRows += `
        <div class="wp-plugin">
          <span class="check-icon" aria-hidden="true">?</span>
          <span class="wp-name">${esc(pl.slug)} (versione non rilevata)</span>
          <span class="wp-n">non verificabile</span>
        </div>`;
        continue;
      }
      const state = n > 0 ? "vuln" : "safe";
      const vols = pl.vulnerabilities.slice(0, 3).map(v =>
        `<div class="wp-cve">${esc(v.cve || v.title)}</div>`).join("");
      const vers = pl.version ? ` v${esc(pl.version)}` : " (versione sconosciuta)";
      pluginRows += `
        <div class="wp-plugin ${state}">
          <span class="check-icon" aria-hidden="true">${n > 0 ? "✗" : "✓"}</span>
          <span class="wp-name">${esc(pl.slug)}${vers}</span>
          <span class="wp-n">${n > 0 ? n + " vulnerabilita'" : "safe"}</span>
        </div>${vols}`;
    }
    wpHtml = `
    <h3>Sicurezza WordPress</h3>
    <div class="wp-panel">
      <div class="wp-core">Core: <strong>${esc(String(coreV))}</strong> ${coreBadge}</div>
      <div class="wp-plugins">${pluginRows}</div>
    </div>`;
  }

  box.innerHTML = `
    <div class="inline-site"><b>${domain || urlText}</b></div>
    <h3>Verdetto</h3>
    <div class="verdict ${verdictClass}">
      <p>${esc(report.summary.most_urgent || "Nessun verdetto")}</p>
      <p class="form-hint">${esc((report.summary.highlights || []).join(" · ") || urlText)}</p>
    </div>
    <h3>Punteggi per area</h3>
    <div class="scoreboard">${scores}</div>
    ${wpHtml}
    ${renderAreas(report)}
    ${renderOverall(report)}
    ${renderPlan(report)}
    ${renderOpportunities(report)}
    <h3>Cosa sistemare</h3>
    ${recs}
    ${renderGlossary(report)}`;

  // toggle espansione dei dettagli verifiche
  box.querySelectorAll(".chk-toggle").forEach((b) => {
    b.addEventListener("click", () => {
      const id = b.getAttribute("aria-controls");
      const list = document.getElementById(id);
      const open = list.hidden;
      list.hidden = !open;
      b.setAttribute("aria-expanded", String(open));
    });
  });
}

function renderAreas(report) {
  const areas = report.areas || [];
  if (!areas.length) return "";
  const rows = areas.map((a) => {
    const sc = a.score10 || 0;
    const cls = sc >= 7 ? "gA" : sc >= 5 ? "gC" : "gF";
    const str = (a.strengths || []).join(" · ");
    const wkn = (a.weaknesses || []).join(" · ");
    return `<div class="area-line">
      <span class="area-score ${cls}">${sc}/10</span>
      <div>
        <b>${esc(a.name)}</b>
        <div class="area-txt">${esc(a.analysis || "")}</div>
        ${str ? `<div class="area-str">+ ${esc(str)}</div>` : ""}
        ${wkn ? `<div class="area-wk">− ${esc(wkn)}</div>` : ""}
      </div>
    </div>`;
  }).join("");
  return `<h3>Le ${areas.length} aree esaminate</h3><div class="area-list">${rows}</div>`;
}

function renderOverall(report) {
  const ov = report.overall || {};
  if (!Object.keys(ov).length) return "";
  const sc = ov.score10 || 0;
  const cls = sc >= 7 ? "gA" : sc >= 5 ? "gC" : "gF";
  const macro = Object.entries(ov.macro_areas || {})
    .map(([k, v]) => `<span><b class="${v >= 7 ? "gA" : v >= 5 ? "gC" : "gF"}">${v}/10</b> ${esc(k)}</span>`)
    .join("");
  return `<h3>Giudizio finale</h3><div class="overall-box">
    <div class="ov-big ${cls}">${sc}/10</div>
    <div><b>${esc(ov.verdict || "")}</b><div class="area-txt" style="margin-top:4px">${macro}</div></div>
  </div>`;
}

function renderPlan(report) {
  const p = report.action_plan || {};
  if (!Object.keys(p).length) return "";
  const cols = [
    ["Da fare subito (0-30 gg)", p.immediate_0_30],
    ["Medio termine (30-90 gg)", p.medium_30_90],
    ["A lungo termine (90-365 gg)", p.long_90_365],
  ];
  const html = cols.map(([t, items]) =>
    `<div class="plan-col"><b>${esc(t)}</b><ul>${(items || []).map(i => `<li>${esc(i)}</li>`).join("") || "<li>—</li>"}</ul></div>`
  ).join("");
  return `<h3>Piano d'azione</h3><div class="plan-grid">${html}</div>`;
}

function renderOpportunities(report) {
  const opp = report.opportunities || [];
  if (!opp.length) return "";
  const html = opp.slice(0, 5).map((o) =>
    `<div class="rec-card opp"><b>${esc(o.title)} <span class="opp-pill p-${(o.priority || "").toLowerCase()}">${esc(o.priority)}</span></b>
     <p class="rec-detail">${esc(o.benefit)}</p></div>`
  ).join("");
  return `<h3>Le opportunità principali</h3>${html}`;
}

function renderGlossary(report) {
  const glo = report.glossary || [];
  if (!glo.length) return "";
  const html = glo.slice(0, 10).map((g) =>
    `<div class="gloss-item"><b>${esc(g.term)}</b> · <span>${esc(g.definition)}</span></div>`
  ).join("");
  return `<h3>Glossario</h3><div class="gloss-box">${html}</div>`;
}

function showError(el, msg) { el.textContent = msg; el.hidden = false; }
function siteDomain(url) {
  try { return new URL(url).hostname.replace(/^www\./, "") || url; }
  catch { return url || ""; }
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function esc(s) {
  return String(s == null ? "" : s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function isValidUrl(s) {
  try { const u = new URL(s); return u.protocol === "http:" || u.protocol === "https:"; }
  catch { return false; }
}
function isValidEmail(s) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s); }