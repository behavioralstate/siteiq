/* SiteIQ — landing pubblica: flusso lead -> conferma email -> 1 scan.
   Endpoint backend pubblici: /api/lead, /api/confirm, /api/scan, /api/analyze/{id}
*/
"use strict";
const $ = (s) => document.querySelector(s);

window.addEventListener("DOMContentLoaded", () => {
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
  const box = document.getElementById("contatti");
  try {
    const r = await fetch(`/api/confirm?token=${encodeURIComponent(token)}`);
    const data = await r.json();
    if (!r.ok || data.status !== "confirmed") {
      showLandingError(box, (data.detail || "link di conferma non valido") + " — il lead è ancora pendente.");
      return;
    }
    // conferma ok: mostra lo scan
    showScan(token, data.url || localStorage.getItem("siteiq_scan_url") || "");
  } catch (e) {
    showLandingError(box, "Impossibile verificare la conferma. Riprova.");
  }
}

function showLandingError(parent, msg) {
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
    if (!isValidUrl(url)) return showError(error, "Inserisci un URL valido (https://…)");
    if (!isValidEmail(email)) return showError(error, "Inserisci una email valida.");

    try {
      const r = await fetch("/api/lead", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, url }),
      });
      const data = await r.json();
      if (!r.ok) return showError(error, data.detail || "Errore durante la richiesta.");
      // memorizza il sito per lo stadio scan (riletto dopo la conferma)
      localStorage.setItem("siteiq_scan_url", url);
      $("#wait-email").textContent = email;
      $("#stage-lead").hidden = true;
      $("#stage-wait").hidden = false;
    } catch (err) {
      showError(error, "Impossibile contattare il server. Riprova.");
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
  $("#scan-url").textContent = url || "il tuo sito";
  $("#scan-btn").addEventListener("click", () => runScan(token));
}

async function runScan(token) {
  const btn = $("#scan-btn");
  const err = $("#scan-error");
  err.hidden = true;
  btn.disabled = true;
  $("#scan-progress").hidden = false;
  $("#scan-status").textContent = "Avvio dell'analisi…";
  try {
    const r = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const data = await r.json();
    if (!r.ok) {
      showError(err, data.detail || "Non puoi avviare l'analisi.");
      btn.disabled = false;
      return;
    }
    await pollScan(data.job_id);
  } catch (e2) {
    showError(err, "Errore di rete. Riprova.");
    btn.disabled = false;
  }
}

async function pollScan(jobId) {
  const statusEl = $("#scan-status");
  for (let i = 0; i < 90; i++) {
    const r = await fetch(`/api/scan/${jobId}`);
    const j = await r.json();
    if (!j.status) throw new Error("risposta non valida");
    if (j.status === "done") {
      statusEl.textContent = "Analisi completata.";
      renderReport(j.result);
      return;
    }
    if (j.status === "error") {
      statusEl.textContent = "Analisi fallita.";
      showError($("#scan-error"), j.error || "Errore durante l'analisi.");
      return;
    }
    statusEl.textContent = "L'AI sta analizzando il tuo sito…";
    await sleep(2000);
  }
  statusEl.textContent = "Tempo scaduto. Ricarica e riprova.";
}