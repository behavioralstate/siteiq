/* SiteIQ — pannello admin (solo admin, protetto da token).
   Lancia analisi e consulta il monitoraggio consumo via API backend.
   Testi dal catalogo (I18N, vedi i18n.js); date e numeri nel formato del locale.
*/
"use strict";

const $ = (s) => document.querySelector(s);
const TOKEN_KEY = "siteiq_admin_token";
const tr = (key, params) => I18N.t(key, params);

// Ogni valore che arriva dal server (lead, URL, email) è input di utenti
// anonimi: va sempre escapato prima di finire in innerHTML.
function esc(s) {
  return String(s == null ? "" : s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }
function money(v) { return I18N.number(num(v), { minimumFractionDigits: 6, maximumFractionDigits: 6 }); }

function token() { return localStorage.getItem(TOKEN_KEY) || ""; }
function authHeaders() {
  return I18N.headers({ "Content-Type": "application/json", "Authorization": "Bearer " + token() });
}

window.addEventListener("DOMContentLoaded", async () => {
  await I18N.ready;
  const tokenInput = $("#admin-token");
  tokenInput.value = token();

  $("#save-token").addEventListener("click", () => {
    localStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
    msg(tr("web.admin.msg_token_saved"), "ok");
    loadUsage();
  });

  $("#admin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = $("#admin-url").value.trim();
    const llm = $("#admin-llm").value;
    if (!url) return msg(tr("web.admin.msg_url_required"), "error");
    if (!token()) return msg(tr("web.admin.msg_save_token_first"), "error");
    msg(tr("web.admin.msg_starting"), "");
    try {
      const r = await fetch(`/api/analyze?llm=${encodeURIComponent(llm)}`, {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({ url, max_pages: 1 }),
      });
      if (r.status === 401) return msg(tr("web.admin.msg_token_invalid"), "error");
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        const detail = typeof data.detail === "string" ? data.detail : tr("web.admin.msg_server_error", { status: r.status });
        return msg(detail, "error");
      }
      const { job_id } = await r.json();
      msg(tr("web.admin.msg_started", { job: job_id.slice(0, 8) }), "");
      await poll(job_id);
    } catch (err) {
      msg(tr("web.admin.msg_error", { message: err.message }), "error");
    }
  });

  loadUsage();
});

async function poll(jobId) {
  for (let i = 0; i < 120; i++) {
    const r = await fetch(`/api/analyze/${encodeURIComponent(jobId)}`, { headers: authHeaders() });
    const j = await r.json();
    if (j.status === "done") {
      $("#report-out").hidden = false;
      $("#report-pre").textContent = JSON.stringify(j.result, null, 2);
      msg(tr("web.admin.msg_done"), "ok");
      loadUsage();
      return;
    }
    if (j.status === "error") { msg(tr("web.admin.msg_failed", { error: j.error || "" }), "error"); return; }
    await new Promise((r) => setTimeout(r, 2000));
  }
  msg(tr("web.admin.msg_timeout"), "error");
}

async function loadUsage() {
  if (!token()) return;
  try {
    const r = await fetch("/api/admin/usage", { headers: authHeaders() });
    if (r.status === 401) return;
    const data = await r.json();
    const totals = data.totals || {};
    $("#usage-grid").innerHTML = [
      [tr("web.admin.usage_requests"), I18N.number(num(totals.requests))],
      [tr("web.admin.usage_tokens"), I18N.number(num(totals.total_tokens))],
      [tr("web.admin.col_cost"), money(totals.total_cost_usd)],
      [tr("web.admin.usage_ok"), I18N.number(num(totals.ok))],
      [tr("web.admin.usage_errors"), I18N.number(num(totals.errors))],
    ].map(([k, v]) => `<div class="usage-cell"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("");

    const rr = await fetch("/api/admin/requests?limit=20", { headers: authHeaders() });
    const rows = (await rr.json()).requests || [];
    $("#usage-table tbody").innerHTML = rows.map((x) => `
      <tr>
        <td>${esc(I18N.dateTime(x.ts))}</td>
        <td>${esc(x.client)}</td>
        <td class="mono">${esc(x.url)}</td>
        <td>${esc(I18N.optional("web.admin.status_" + x.status) || x.status)}</td>
        <td>${esc(I18N.number(num(x.total_tokens)))}</td>
        <td>${esc(money(x.cost_usd))}</td>
      </tr>`).join("");

    const lr = await fetch("/api/admin/leads?limit=30", { headers: authHeaders() });
    const leadRows = (lr.ok ? (await lr.json()).leads : []) || [];
    $("#leads-table tbody").innerHTML = leadRows.map((x) => `
      <tr>
        <td>${esc(I18N.dateTime(x.created_at))}</td>
        <td>${esc(x.email)}</td>
        <td class="mono">${esc(x.url)}</td>
        <td>${esc(I18N.optional("web.admin.status_" + x.status) || x.status)}</td>
        <td>${esc(tr(x.scan_used ? "web.common.yes" : "web.common.no"))}</td>
      </tr>`).join("");

    const rr2 = await fetch("/api/admin/reports", { headers: authHeaders() });
    const repRows = (rr2.ok ? (await rr2.json()).reports : []) || [];
    $("#reports-table tbody").innerHTML = repRows.map((x) => `
      <tr>
        <td><a href="#" class="report-link" data-job="${esc(x.job_id)}">${esc(tr("web.admin.report_link", { id: String(x.job_id).slice(0, 8) }))}</a></td>
        <td>${esc(tr("web.admin.size_kib", { size: I18N.number(num(x.bytes) / 1024, { maximumFractionDigits: 1 }) }))}</td>
        <td>${esc(I18N.dateTime(x.modified))}</td>
      </tr>`).join("");
    $("#reports-table tbody").querySelectorAll(".report-link").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        openReport(a.getAttribute("data-job"));
      });
    });
  } catch (e) { /* silenzioso */ }
}

function openReport(jobId) {
  if (!token()) return;
  localStorage.setItem("siteiq_last_report", jobId);
  // apre in nuova scheda il viewer dedicato (carica il report con auth)
  const url = "/report_viewer.html?job=" + encodeURIComponent(jobId);
  const w = window.open(url, "_blank");
  if (!w) window.location.href = url;
}

function msg(text, kind) {
  const el = $("#admin-msg");
  el.textContent = text;
  el.className = "admin-msg" + (kind ? " " + kind : "");
}
