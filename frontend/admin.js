/* SiteIQ — pannello admin (solo admin, protetto da token).
   Lancia analisi e consulta il monitoraggio consumo via API backend.
*/
"use strict";

const $ = (s) => document.querySelector(s);
const TOKEN_KEY = "siteiq_admin_token";

function token() { return localStorage.getItem(TOKEN_KEY) || ""; }
function authHeaders() { return { "Content-Type": "application/json", "Authorization": "Bearer " + token() }; }

window.addEventListener("DOMContentLoaded", () => {
  const tokenInput = $("#admin-token");
  tokenInput.value = token();

  $("#save-token").addEventListener("click", () => {
    localStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
    msg("Chiave salvata.", "ok");
    loadUsage();
  });

  $("#admin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = $("#admin-url").value.trim();
    const llm = $("#admin-llm").value;
    if (!url) return msg("Inserisci un URL.", "error");
    if (!token()) return msg("Salva prima la chiave di accesso.", "error");
    msg("Avvio analisi…", "");
    try {
      const r = await fetch(`/api/analyze?llm=${llm}`, {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({ url, max_pages: 1 }),
      });
      if (r.status === 401) return msg("Chiave non valida.", "error");
      if (!r.ok) return msg("Errore server " + r.status, "error");
      const { job_id } = await r.json();
      msg("Analisi avviata (job " + job_id.slice(0, 8) + "…). Attendo il risultato…", "");
      await poll(job_id);
    } catch (err) {
      msg("Errore: " + err.message, "error");
    }
  });

  loadUsage();
});

async function poll(jobId) {
  for (let i = 0; i < 120; i++) {
    const r = await fetch(`/api/analyze/${jobId}`, { headers: authHeaders() });
    const j = await r.json();
    if (j.status === "done") {
      $("#report-out").hidden = false;
      $("#report-pre").textContent = JSON.stringify(j.result, null, 2);
      msg("Analisi completata.", "ok");
      loadUsage();
      return;
    }
    if (j.status === "error") { msg("Analisi fallita: " + (j.error || ""), "error"); return; }
    await new Promise((r) => setTimeout(r, 2000));
  }
  msg("Timeout in attesa del risultato.", "error");
}

async function loadUsage() {
  if (!token()) return;
  try {
    const r = await fetch("/api/admin/usage", { headers: authHeaders() });
    if (r.status === 401) return;
    const data = await r.json();
    const t = data.totals || {};
    $("#usage-grid").innerHTML = [
      ["Richieste", t.requests || 0],
      ["Token totali", (t.total_tokens || 0).toLocaleString("it-IT")],
      ["Costo $", (t.total_cost_usd || 0).toFixed(6)],
      ["OK", t.ok || 0],
      ["Errori", t.errors || 0],
    ].map(([k, v]) => `<div class="usage-cell"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

    const rr = await fetch("/api/admin/requests?log=fabio&limit=20", { headers: authHeaders() });
    const rows = (await rr.json()).requests || [];
    $("#usage-table tbody").innerHTML = rows.map((x) => `
      <tr>
        <td>${new Date(x.ts).toLocaleString("it-IT")}</td>
        <td>${x.client}</td>
        <td class="mono">${x.url}</td>
        <td>${x.status}</td>
        <td>${x.total_tokens}</td>
        <td>${(x.cost_usd || 0).toFixed(6)}</td>
      </tr>`).join("");

    const lr = await fetch("/api/admin/leads?limit=30", { headers: authHeaders() });
    const leadRows = (lr.ok ? (await lr.json()).leads : []) || [];
    $("#leads-table tbody").innerHTML = leadRows.map((x) => `
      <tr>
        <td>${new Date(x.created_at).toLocaleString("it-IT")}</td>
        <td>${x.email}</td>
        <td class="mono">${x.url}</td>
        <td>${x.status}</td>
        <td>${x.scan_used ? "sì" : "no"}</td>
      </tr>`).join("");

    const rr2 = await fetch("/api/admin/reports", { headers: authHeaders() });
    const repRows = (rr2.ok ? (await rr2.json()).reports : []) || [];
    $("#reports-table tbody").innerHTML = repRows.map((x) => `
      <tr>
        <td><a href="#" class="report-link" data-job="${x.job_id}">Report ${x.job_id.slice(0,8)}…</a></td>
        <td>${(x.bytes / 1024).toFixed(1)} KiB</td>
        <td>${new Date(x.modified).toLocaleString("it-IT")}</td>
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
  const w = window.open("/report_viewer.html?job=" + jobId, "_blank");
  if (!w) window.location.href = "/report_viewer.html?job=" + jobId;
}

function msg(text, kind) {
  const el = $("#admin-msg");
  el.textContent = text;
  el.className = "admin-msg" + (kind ? " " + kind : "");
}
