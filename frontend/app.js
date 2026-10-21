/* SiteIQ — landing pubblica: flusso lead -> conferma email -> 1 scan.
   Endpoint backend pubblici: /api/lead, /api/confirm, /api/scan, /api/scan/{id}
   Testi dal catalogo (I18N, vedi i18n.js); ogni chiamata invia Accept-Language,
   così anche i messaggi del server arrivano nella lingua scelta.
*/
"use strict";
const $ = (s) => document.querySelector(s);

/** Messaggio d'errore del server se è testo, altrimenti uno nostro (le 422 di
    validazione di FastAPI hanno `detail` come lista). */
function apiError(data, fallbackKey) {
  return data && typeof data.detail === "string" ? data.detail : I18N.t(fallbackKey);
}

window.addEventListener("DOMContentLoaded", async () => {
  await I18N.ready;
  const params = new URLSearchParams(location.search);

  // Arrivati dal link di conferma: valida il token SERVER-SIDE (marca confirmed
  // nel DB), poi mostra lo scan. Senza /api/confirm il lead resta pending -> 403.
  const token = params.get("token");
  if (params.get("confirmed") === "1" && token) {
    confirmAndShow(token);
    return;
  }
  initLeadForm();
});

async function confirmAndShow(token) {
  try {
    const r = await fetch(`/api/confirm?token=${encodeURIComponent(token)}`, { headers: I18N.headers() });
    const data = await r.json();
    if (!r.ok || data.status !== "confirmed") {
      showLandingError(I18N.t("web.app.still_pending", { reason: apiError(data, "web.app.confirm_invalid") }));
      return;
    }
    // conferma ok: mostra lo scan
    let storedUrl = "";
    try { storedUrl = localStorage.getItem("siteiq_scan_url") || ""; } catch { /* storage non disponibile */ }
    showScan(token, data.url || storedUrl);
  } catch (e) {
    showLandingError(I18N.t("web.app.confirm_failed"));
  }
}

function showLandingError(msg) {
  // rende visibile la sezione contatti e il suo errore
  const stage = $("#stage-lead");
  if (stage) stage.hidden = false;
  const err = $("#lead-error");
  if (err) { err.textContent = msg; err.hidden = false; }
}

function initLeadForm() {
  const form = $("#lead-form");
  if (!form) return;
  const urlInput = $("#lead-url");
  const emailInput = $("#lead-email");
  const error = $("#lead-error");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    const url = urlInput.value.trim();
    const email = emailInput.value.trim();
    if (!isValidUrl(url)) return showError(error, I18N.t("web.app.url_invalid"));
    if (!isValidEmail(email)) return showError(error, I18N.t("web.app.email_invalid"));

    try {
      const r = await fetch("/api/lead", {
        method: "POST",
        headers: I18N.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({ email, url }),
      });
      const data = await r.json();
      if (!r.ok) return showError(error, apiError(data, "web.app.request_failed"));
      // memorizza il sito per lo stadio scan (riletto dopo la conferma)
      try { localStorage.setItem("siteiq_scan_url", url); } catch { /* storage non disponibile */ }
      $("#wait-email").textContent = email;
      $("#stage-lead").hidden = true;
      $("#stage-wait").hidden = false;
    } catch (err) {
      showError(error, I18N.t("web.app.server_unreachable"));
    }
  });

  $("#wait-retry").addEventListener("click", (e) => {
    e.preventDefault();
    $("#stage-wait").hidden = true;
    $("#stage-lead").hidden = false;
  });
}

function showScan(token, url) {
  $("#stage-lead").hidden = true;
  $("#stage-wait").hidden = true;
  $("#stage-scan").hidden = false;
  $("#scan-url").textContent = url || I18N.t("web.app.your_site");
  $("#scan-btn").addEventListener("click", () => runScan(token));
}

async function runScan(token) {
  const btn = $("#scan-btn");
  const err = $("#scan-error");
  err.hidden = true;
  btn.disabled = true;
  $("#scan-progress").hidden = false;
  $("#scan-status").textContent = I18N.t("web.app.scan_starting");
  try {
    const r = await fetch("/api/scan", {
      method: "POST",
      headers: I18N.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ token }),
    });
    const data = await r.json();
    if (!r.ok) {
      showError(err, apiError(data, "web.app.scan_not_allowed"));
      btn.disabled = false;
      return;
    }
    await pollScan(data.job_id);
  } catch (e2) {
    showError(err, I18N.t("web.app.network_error"));
    btn.disabled = false;
  }
}

async function pollScan(jobId) {
  const statusEl = $("#scan-status");
  for (let i = 0; i < 90; i++) {
    const r = await fetch(`/api/scan/${encodeURIComponent(jobId)}`, { headers: I18N.headers() });
    const j = await r.json();
    if (!j.status) throw new Error("invalid response");
    if (j.status === "done") {
      statusEl.textContent = I18N.t("web.app.scan_done");
      renderReport(j.result);
      return;
    }
    if (j.status === "error") {
      statusEl.textContent = I18N.t("web.app.scan_failed");
      showError($("#scan-error"), j.error || I18N.t("web.app.scan_error"));
      return;
    }
    statusEl.textContent = I18N.t("web.app.scan_running");
    await sleep(2000);
  }
  statusEl.textContent = I18N.t("web.app.scan_timeout");
}
