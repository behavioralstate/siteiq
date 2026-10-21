/* SiteIQ — render del report scan (scoreboard espandibile + priorità + checks).
   Testi dal catalogo condiviso (I18N, vedi i18n.js): stesse chiavi "report.*"
   dell'email e della pagina report generate dal backend. */
"use strict";

const GRADE_CLASS = { A: "sg-A", B: "sg-B", C: "sg-C", D: "sg-D", F: "sg-F" };
const SCORE_ORDER = ["performance", "accessibility", "security", "seo", "development"];
const PLAN_COLUMNS = [
  ["immediate_0_30", "report.plan.immediate"],
  ["medium_30_90", "report.plan.medium"],
  ["long_90_365", "report.plan.long"],
];
const t = (key, params) => I18N.t(key, params);

function renderReport(report) {
  const box = $("#scan-report");
  box.hidden = false;
  if (!report) { box.textContent = t("web.report.empty"); return; }

  const verdictClass = report.summary.verdict === "ok" ? "good"
    : report.summary.verdict === "critical" ? "critical" : "attention";
  const urlText = esc(report.url);
  const domain = esc(siteDomain(report.url));
  const checks = report.checks || {};

  let scores = "";
  for (const name of SCORE_ORDER) {
    const s = report.scores[name];
    if (!s) continue;
    // lista check della categoria (se presenti)
    const catChecks = checks[name] || [];
    const checkBadges = catChecks.map((c) => {
      const icon = c.status === "ok" ? "✓" : c.status === "warn" ? "!" : "✗";
      const sevCls = "chk-" + esc(c.status);
      return `<div class="check-item ${sevCls}">
                <span class="check-icon" aria-hidden="true">${icon}</span>
                <span class="check-label">${esc(c.label)}</span>
                <span class="check-detail">${esc(c.detail)}</span>
              </div>`;
    }).join("");
    const expandable = catChecks.length > 0
      ? `<button class="btn btn-ghost chk-toggle" data-cat="${esc(name)}" aria-expanded="false"
                 aria-controls="chk-${esc(name)}">${esc(t("web.report.checks_toggle", { count: catChecks.length }))}</button>
         <div class="check-list" id="chk-${esc(name)}" hidden>${checkBadges}</div>`
      : "";

    scores += `
      <div class="score-card">
        <div class="score-name">${esc(t("categories." + name))}</div>
        <div class="score-row">
          <span class="score-val">${num(s.value)}</span><span class="score-grade ${GRADE_CLASS[s.grade] || ""}">${esc(s.grade)}</span>
        </div>
        <div class="score-track"><i style="width:${num(s.value)}%"></i></div>
        ${expandable}
      </div>`;
  }

  let recs = "";
  for (const rec of (report.recommendations || [])) {
    const pill = `pill-${esc(rec.priority)}`;
    const effort = I18N.optional("report.effort." + rec.effort) || rec.effort || "";
    recs += `
      <div class="rec-card">
        <div class="rec-head-static">
          <span class="rec-pill ${pill}">${esc(rec.priority)}</span>
          <span class="rec-title">${esc(rec.title)}</span>
          <span class="rec-effort">${esc(t("web.report.effort", { effort }))}</span>
        </div>
        <div class="rec-body open">
          <p class="rec-detail">${esc(rec.detail)}</p>
          <p class="rec-evidence"><b>${esc(t("web.report.evidence"))}</b> ${esc(rec.evidence_ref || "")}</p>
        </div>
      </div>`;
  }
  if (!recs) recs = `<p class="empty-note">${esc(t("web.report.no_urgent"))}</p>`;

  // Sezione WordPress (solo se presente)
  let wpHtml = "";
  const wp = report.wordpress_security;
  if (wp && wp.is_wordpress) {
    const coreV = wp.core ? wp.core.version : "—";
    const coreVuln = wp.core && wp.core.vulnerabilities ? wp.core.vulnerabilities.length : 0;
    const coreBadge = coreVuln > 0
      ? `<span class="wp-badge wp-bad">${esc(t("web.report.wp_core_vulns", { count: coreVuln }))}</span>`
      : `<span class="wp-badge wp-ok">${esc(t("web.report.wp_core_ok"))}</span>`;
    let pluginRows = "";
    for (const pl of (wp.plugins || [])) {
      const n = (pl.vulnerabilities || []).length;
      if (pl.status === "unknown") {
        // versione non rilevata dal crawler: non è un verdetto di vulnerabilità
        pluginRows += `
        <div class="wp-plugin">
          <span class="check-icon" aria-hidden="true">?</span>
          <span class="wp-name">${esc(t("web.report.wp_plugin_unknown", { slug: pl.slug }))}</span>
          <span class="wp-n">${esc(t("web.report.wp_not_verifiable"))}</span>
        </div>`;
        continue;
      }
      const state = n > 0 ? "vuln" : "safe";
      const vols = (pl.vulnerabilities || []).slice(0, 3).map(v =>
        `<div class="wp-cve">${esc(v.cve || v.title)}</div>`).join("");
      const name = pl.version
        ? t("web.report.wp_plugin_version", { slug: pl.slug, version: pl.version })
        : t("web.report.wp_plugin_unknown_version", { slug: pl.slug });
      pluginRows += `
        <div class="wp-plugin ${state}">
          <span class="check-icon" aria-hidden="true">${n > 0 ? "✗" : "✓"}</span>
          <span class="wp-name">${esc(name)}</span>
          <span class="wp-n">${esc(n > 0 ? t("web.report.wp_plugin_vulns", { count: n }) : t("web.report.wp_safe"))}</span>
        </div>${vols}`;
    }
    wpHtml = `
    <h3>${esc(t("report.wp.title"))}</h3>
    <div class="wp-panel">
      <div class="wp-core">${esc(t("web.report.wp_core"))} <strong>${esc(String(coreV))}</strong> ${coreBadge}</div>
      <div class="wp-plugins">${pluginRows}</div>
    </div>`;
  }

  box.innerHTML = `
    <div class="inline-site"><b>${domain || urlText}</b></div>
    <h3>${esc(t("web.report.verdict"))}</h3>
    <div class="verdict ${verdictClass}">
      <p>${esc(report.summary.most_urgent || t("web.report.no_verdict"))}</p>
      <p class="form-hint">${esc((report.summary.highlights || []).join(" · ") || report.url)}</p>
    </div>
    <h3>${esc(t("report.scores_by_area"))}</h3>
    <div class="scoreboard">${scores}</div>
    ${wpHtml}
    ${renderAreas(report)}
    ${renderOverall(report)}
    ${renderPlan(report)}
    ${renderOpportunities(report)}
    <h3>${esc(t("web.report.what_to_fix"))}</h3>
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
    const sc = num(a.score10);
    const cls = sc >= 7 ? "gA" : sc >= 5 ? "gC" : "gF";
    const str = (a.strengths || []).join(" · ");
    const wkn = (a.weaknesses || []).join(" · ");
    const label = (a.id && I18N.optional("areas." + a.id)) || a.name || "";
    return `<div class="area-line">
      <span class="area-score ${cls}">${esc(I18N.number(sc))}/10</span>
      <div>
        <b>${esc(label)}</b>
        <div class="area-txt">${esc(a.analysis || "")}</div>
        ${str ? `<div class="area-str">+ ${esc(str)}</div>` : ""}
        ${wkn ? `<div class="area-wk">− ${esc(wkn)}</div>` : ""}
      </div>
    </div>`;
  }).join("");
  return `<h3>${esc(t("report.areas_examined", { count: areas.length }))}</h3><div class="area-list">${rows}</div>`;
}

function renderOverall(report) {
  const ov = report.overall || {};
  if (!Object.keys(ov).length) return "";
  const sc = num(ov.score10);
  const cls = sc >= 7 ? "gA" : sc >= 5 ? "gC" : "gF";
  const macro = Object.entries(ov.macro_areas || {})
    .filter(([, v]) => typeof v === "number")
    .map(([k, v]) => {
      const label = I18N.optional("macro." + k) || k;
      return `<span><b class="${v >= 7 ? "gA" : v >= 5 ? "gC" : "gF"}">${esc(I18N.number(num(v)))}/10</b> ${esc(label)}</span>`;
    })
    .join("");
  return `<h3>${esc(t("report.final_verdict"))}</h3><div class="overall-box">
    <div class="ov-big ${cls}">${esc(I18N.number(sc))}/10</div>
    <div><b>${esc(ov.verdict || "")}</b><div class="area-txt" style="margin-top:4px">${macro}</div></div>
  </div>`;
}

function renderPlan(report) {
  const p = report.action_plan || {};
  if (!Object.keys(p).length) return "";
  const html = PLAN_COLUMNS.map(([field, key]) =>
    `<div class="plan-col"><b>${esc(t(key))}</b><ul>${(p[field] || []).map(i => `<li>${esc(i)}</li>`).join("") || "<li>—</li>"}</ul></div>`
  ).join("");
  return `<h3>${esc(t("report.action_plan"))}</h3><div class="plan-grid">${html}</div>`;
}

function renderOpportunities(report) {
  const opp = report.opportunities || [];
  if (!opp.length) return "";
  const html = opp.slice(0, 5).map((o) => {
    const priority = I18N.optional("report.opportunity_priority." + o.priority) || o.priority || "";
    return `<div class="rec-card opp"><b>${esc(o.title)} <span class="opp-pill p-${esc((o.priority || "").toLowerCase())}">${esc(priority)}</span></b>
     <p class="rec-detail">${esc(o.benefit)}</p></div>`;
  }).join("");
  return `<h3>${esc(t("report.opportunities"))}</h3>${html}`;
}

function renderGlossary(report) {
  const glo = report.glossary || [];
  if (!glo.length) return "";
  const html = glo.slice(0, 10).map((g) =>
    `<div class="gloss-item"><b>${esc(g.term)}</b> · <span>${esc(g.definition)}</span></div>`
  ).join("");
  return `<h3>${esc(t("report.glossary"))}</h3><div class="gloss-box">${html}</div>`;
}

function showError(el, msg) { el.textContent = msg; el.hidden = false; }
function siteDomain(url) {
  try { return new URL(url).hostname.replace(/^www\./, "") || url; }
  catch { return url || ""; }
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
// valori numerici del report (LLM): mai interpolare stringhe arbitrarie
function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }
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
