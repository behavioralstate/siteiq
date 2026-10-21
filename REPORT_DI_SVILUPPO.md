# SiteIQ — Report di sviluppo

**Data report:** 2026-10-07
**Progetto:** `~/siteiq` (monorepo git, **20 commit**)
**Test:** **55 verdi** (`cd ~/siteiq/backend && python3 -m pytest tests/ -q`, ~1'40")
**Stato:** MVP funzionante end-to-end · prodotto utilizzabile per analisi reali · resta il deploy pubblico (nginx/dominio) e la messa in produzione

---

## 1. Contesto e obiettivo

**SiteIQ** è una web app gratuita, moderna e WCAG-compliant che audita siti internet e spiega in linguaggio naturale cosa sistemare, grazie all'interpretazione AI di dati tecnici reali raccolti dal crawler.

**Posizionamento vs. riferimento (GooUX SiteScan):** invece di 32 analyzer deterministici + AI opzionale a crediti, SiteIQ parte dalla raccolta dati **automatica** (gratis) e usa l'**interpretazione AI** (LM via OpenRouter) per spiegare priorità e motivazioni in italiano. Ogni consiglio è tracciato (`evidence_ref`) al dato che lo giustifica (anti-allucinazione).

## 2. Decisioni architetturali registrate

| Decisione | Scelta | Nota |
|---|---|---|
| Hosting | Contenitori/LXC **separati sulla stessa macchina**, HTTP su rete bridge interna | Mai `0.0.0.0` verso pubblico; solo nginx esposto |
| LLM engine | **OpenRouter oggi** (chiave condivisa con Hermes da `~/.hermes/.env`, in `backend/.env`) | Swap a vLLM alla GPU cambiando solo `LLM_BASE_URL` |
| Workflow dev | **VS Code Remote-SSH** sulla VPS + git | Niente sync locale↔server |
| Dominio | `siteiq.it` **temporaneo** (da decidere/comprare) | DNS = A record + nginx + Let's Encrypt |
| Design | Vincolo **anti-AI-slop**, skill `impeccable` | CRM: world grafite + token AA; report carte-bianco email-safe |
| Backend | **Solo admin**; frontend pubblico = landing marketing | Le analisi le lancia l'admin; la landing raccoglie lead |
| Crawler | **Single-URL** (solo la pagina inserita), non più BFS | Decisione 2026-10-07 |
| Report | **Email HTML + pagina HTML autonoma**, inviati a notifica+lead | `REPORT_NOTIFY_EMAIL` |
| Auth | **Bearer token** per admin (`AUTH_CLIENTS`) | Lead pubblico usa diritto limitato (1 scan per email confermata) |

## 3. Architettura implementata

```
Landing pubblica (/) — marketing + form lead (email+url)
   │ POST /api/lead ──▶ email di conferma (SMTP posta.xtsystem.it)
   │ GET  /api/confirm?token=  (double opt-in)
   │ POST /api/scan {token}    (1 scansione per email confermata)
   ▼
Backend FastAPI (backend/)  ── crawler Playwright single-URL ──▶  crawl_report
   │ axe-core a11y · Core Web Vitals CDP · header security · SEO · **fingerprint WordPress**
   ▼  JSON normalizzato (schema/crawl_report.schema.json)
Motore LLM — orchestrazione 3 skill (app/prompt.py + app/llm.py)
   │ pagespeed-insights · impeccable · accessibility      ▼ JSON (final_report.schema.json)
   ├─ checks per-categoria (deterministici, non-LLM)      + validazione schema
   ├─ wordpress_security (WPVulnerability API, semver)
   ├─ report_email / report_page (stessa grafica)
   └─ /admin — analisi, monitoraggio consumo (SQLite), report salvati, lead
```

## 4. Componenti del backend

### 4.1 `app/crawl.py` — Crawler **single-URL**
- Scansiona SOLO l'URL inserito (niente BFS/discovery di pagine).
- Rispetta `robots.txt`; raccoglie: HTTP status, redirect chain, axe a11y, header sicurezza, SEO, alt mancanti, charset, **fingerprint WordPress**.
- **`_extract_qualitative()`**: segnali commerciali/qualitativi per le 17 aree — contenuti (testo, lorem ipsum), canali di contatto (email/tel/whatsapp), canali social, tracker (GTM/GA4/pixel/Hotjar/Matomo), booking engine esterno, branding (logo/favicon/og:image/colore), CTA/form, media alt. Tutto ciò che è osservabile dal DOM; mancanza = assenza (anti-allucinazione).

### 4.2 `app/vitals.py` — Core Web Vitals via CDP
LCP/FCP/CLS/TBT (proxy INP) + TTFB via PerformanceObserver + CDP. Nota: usa `page.evaluate` (pagina già caricata dal crawler).

### 4.3 `app/llm.py` — Client LLM (astrazione OpenAI-compatible)
- `StubLlm` (offline, punteggio realistico) / `OpenRouterLlm` (reale, valida output contro schema).
- `_load_env()` legge `backend/.env`; espone `last_usage` (token) per il monitoraggio.

### 4.4 `app/prompt.py` — Orchestrazione **4 skill**
System prompt che combina `pagespeed-insights` (CWV Good/NI/Poor), `impeccable` (audit UX Operate), `accessibility` (WCAG 2.2 + axe) e la nuova **`business`** (audit commerciale/qualitativo sulle 17 aree, dal campo `qualitative`). Output: 5 score + **17 aree** (voto /10, analisi, punti di forza/criticità, evidence), **overall** (voto /10 + 7 macro-aree), **action_plan** (0-30/30-90/90-365 gg), **opportunities**, **glossary** — tutto con `evidence_ref` e senza inventare metriche assenti.

### 4.5 `app/checks.py` — Verifiche per-categoria (deterministiche, tipo GooUX)
Calcola da solo i check per i 5 reparti con severità `ok|warn|error` (header presenti/assenti, lunghezza title/description, H1 unico, vitals oltre soglia, violazioni axe raggruppate). Zero allucinazioni, zero token extra.

### 4.6 `app/wpfingerprint.py` + `app/wpvuln.py` — Verifica WordPress
- `wpfingerprint`: rileva WP, versione core (meta generator), **plugin** (dal path `/wp-content/plugins/<slug>/?ver=`), tema.
- `wpvuln`: query **WPVulnerability API** (pubblica, `www.wpvulnerability.net`), confronto semver con `operator` (min/max), fallback `unavailable` senza crash.

### 4.7 `app/email_report.py` + `app/mailer.py` — Report email + pagina
- `render_report_email()` → HTML email-safe (table, inline CSS, carta chiara).
- `render_report_page()` → **pagina HTML5 autonoma** (flex/grid, `<style>`), stessa grafica.
- `send_report()` multipart (text/plain + HTML) via SMTP posta.xtsystem.it.

### 4.8 `app/jobs.py` — Job manager
Esegue crawl → risultati → checks → wordpress → **salva pagina report su disco** (`reports/<job_id>.html`) → **invia email a `REPORT_NOTIFY_EMAIL` + lead** (deduplicati) → aggiorna log usage. Thread in background.

### 4.9 `app/leads.py`, `app/usage.py`, `app/auth.py` — Lead / monitoraggio / auth
- **lead**: double opt-in, `scan_used` (1 per email), idempotente.
- **usage**: SQLite con chi/quando/url/token/costo per ogni analisi.
- **auth**: Bearer token admin (`AUTH_CLIENTS`) su `/api/analyze`, `/api/admin/*`, WS.

### 4.10 `app/routers/` — API
- `analyzer.py` — `/api/analyze` (admin), `/api/analyze/{id}` (polling), `WS /ws/{id}`.
- `lead.py` — `/api/lead`, `/api/confirm`, `/api/scan`, `/api/scan/{id}` (pubblici, diritto limitato).
- `admin.py` — `/api/admin/usage`, `/requests`, `/leads`, `/reports`, `/report/{id}`.

### 4.11 Frontend (no-build, servito da FastAPI)
- **World visuale**: "carta fredda + un accento" (reshape con la skill `frontend-design`, 2026-10-07); base condivisa da `landing.css`, estesa da `admin.css`. `frontend/styles.css` (ex-tema scuro) è stato eliminato.
- `index.html` — **landing marketing** pura (no API) + flusso lead 3 stadi; hero = "report come oggetto" (timbro con score), serif display per numeri.
- `admin.html` — pannello admin: analisi, monitoraggio consumo, Lead, **Report salvati** (link → viewer), tabelle scrollabili `tabindex=0` (axe clean).
- `report_viewer.html` — apre la pagina report di un job con auth.
- `landing.css` / `admin.css` — design system AA (token carta + accento `#1E7B4C`, serif `Source Serif 4` + `Inter`); `styles.css` rimosso.
- `report.js`/`admin.js`/`app.js`.

## 5. Schema condiviso

- **`schema/crawl_report.schema.json`** v1.0.0 — output crawler (vitals, axe, header security, **wordpress**).
- **`schema/final_report.schema.json`** v1.0.0 — output LLM: `summary` + `scores` + `priorities` + `recommendations` + **`checks`** + **`wordpress_security`**. Anti-allucinazione codificata (`evidence_ref` obbligatori).

## 6. Test (55 verdi, ~1'40")

| File | Test | Verifica |
|---|---|---|
| `test_schemas.py` | 9 | Schema validi + conformità |
| `test_crawler.py` | 7 | Crawl single-URL, schema-compliant, alt, header security, vitals |
| `test_vitals.py` | 2 | Chiavi vitals + non negativi |
| `test_llm.py` | 3 | Stub conforme, factory, violazioni |
| `test_prompt.py` | 5 | 3 skill, anti-allucinazione, minify, env |
| `test_analyze.py` | 5 | Pipeline e2e + WS + auth + usage |
| `test_checks.py` | 5 | Check per-categoria (severità, threshold) |
| `test_wp.py` | 6 | Fingerprint + API WPVulnerability (reale) + semver |
| `test_wp_integration.py` | 2 | Crawl→fingerprint→API e2e |
| `test_lead.py` | 4 | Double opt-in + 1-scan + idempotenza |
| `test_email_report.py` | 6 | Render email/pagina + multipart + **notifica a lorenzo+lead** + salvataggio disco |
| `test_health.py` | 1 | Healthcheck |

**Nota:** `reports/*.db` e `*.db` sono in `.gitignore` (artefatti runtime).

## 7. Verifiche dal vivo (prove reali)

- **AI reale su pensareweb.it** (OpenRouter): report grounded (contrasto 1.57:1 citato con `evidence_ref`), validato contro schema.
- **WordPress reale**: Contact Form 7 v5.9.2 → 2 CVE; WooCommerce v8.1.0 → 20; core 6.4.2 → 35 (queries reali a WPVulnerability).
- **Flusso lead completo**: email conferma arrivata (SMTP reale) → doppio click-ott-in → 1 scan → report. **Secondo scan bloccato (403)**.
- **Email report**: arrivata in casella multipart con tutte le sezioni.
- **Report 17 aree (E2E)**: crawler reale su example.com → `qualitative` estratto (tracking, lorem, brand color `0,0,238`) valido contro schema; job admin (`stub`) → **17 aree**, overall 5/10, piano, opportunità, glossario, pagina HTML salvata. **56 test verdi.**
- **Admin report**: pagina HTML salvata su disco, servita con auth (401 senza token).

## 8. Bug trovati e corretti (rilevanti)

| Bug | Fix |
|---|---|
| Modello OpenRouter `:free` inesistente → 404 | Switch a `deepseek/deepseek-chat-v3.1` |
| `from vitals import` falliva su uvicorn | Import package `from app.vitals import` + conftest |
| Score stub implodeva a 0 | Penalità proporzionale, soft-cap ≥10 |
| **DB SQLite read-only** (file cancellato a caldo) | Non cancellare il DB con server in vita; riavvio pulito |
| **Frontend conferma lead non chiamava `/api/confirm`** → scan 403 | Il frontend ora conferma server-side prima dello scan |
| `create_lead`/`confirm_lead` non idempotenti (500/404) | Riusa per email; conferma doppia ok |
| **Versione plugin WooCommerce errata** (da altra URL) | Estratta dalla STESSA URL asset del plugin (`?ver=`) |

## 9. Stato fasi / dove siamo

| Fase | Stato |
|---|---|
| 0 — Bootstrap prodotto/design | ✅ |
| 1 — Schema condiviso + test | ✅ |
| 2 — Backend crawler | ✅ (single-URL) |
| 3 — Integrazione LLM (3 skill) | ✅ |
| 4 — Frontend | ✅ (landing marketing + admin + viewer) |
| 5 — Free tier / double-opt-in / auth / monitoraggio consumo | ✅ |
| 6 — Report email + pagina + notifica | ✅ |
| 7 — Verifica WordPress (vuln core/plugin) | ✅ |
| **8 — Deploy pubblico** (nginx, dominio `siteiq.it`, HTTPS, rate-limit/coda, README, docker-compose) | ⬜ **prossima** |

**In sintesi:** il **prodotto è funzionante end-to-end** per uso interno/agenzia: analisi AI reale con dettaglio per-categoria, verifica WordPress, report via email + pagina valutabile in admin, monitoraggio consumo, lead con double opt-in. **Manca la messa in produzione pubblica**: dominio/nginx/HTTPS, politiche di rate-limit e coda, hardcoded config pubbliche. È la naturale Fase 8.

## 10. Note operative

- **Avvio server:** `cd ~/siteiq/backend && python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000` (in accesso via tunnel VS Code, porta 8000).
- **Pubblico:** `/` (landing) · **Admin:** `/admin` (richiede token Bearer) · **Viewer report:** `/report_viewer.html?job=<id>`.
- **Config in `backend/.env`:** `LLM_*` (OpenRouter), `AUTH_CLIENTS` (token admin), `REPORT_NOTIFY_EMAIL` (=lorenzo@pensareweb.it), `PUBLIC_BASE_URL`.
- **Costo:** ogni analisi reale consuma credito OpenRouter pay-per-call → prima del lancio pubblico servono rate-limit + cache (Fase 8).
- **Dipendenze:** installate per-utente con `--break-system-packages` (PEP 668); `requirements.txt` per il Docker.
- **Skill registrata:** `siteiq-ai-analysis` (software-development).

## 11. Collegamenti

- Piano: `.hermes/plans/2026-10-06_165144-siteiq-analyzer.md`
- Skill: `software-development/siteiq-ai-analysis`
- Docs: `docs/PRODUCT.md`, `docs/DESIGN.md`, `docs/SURFACE_briefs/analyze.md`
- Schemi: `schema/crawl_report.schema.json`, `schema/final_report.schema.json`