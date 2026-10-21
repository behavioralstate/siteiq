# SiteIQ

Analizzatore web AI-first: scansiona un sito (performance, accessibilità, sicurezza,
SEO) e l'AI interpreta i dati in linguaggio naturale — **17 aree**, piano d'azione,
giudizio finale, e verifica WordPress (CVE di core e plugin). Frontend pubblica di
marketing + pannello admin protetto da Bearer token.

## Struttura

```
siteiq/
├── backend/
│   ├── app/            # FastAPI: client LLM promttp, crawler, checks, wpvuln, jobs…
│   ├── tests/          # suite pytest
│   └── .env.example    # modello configurazione (copia in .env)
├── frontend/           # landing + admin + report (vanilla, serviti da FastAPI)
├── schema/             # contratti JSON condivisi crawler↔LLM
├── tests_fixture/      # siti statici per i test del crawler
└── requirements.txt
```

## Avvio in locale

### 1. Requisiti
Python 3.13+, `pip`.

### 2. Installazione
```bash
cd siteiq
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium   # browser del crawler
```

### 3. Configurazione
```bash
cd backend
cp .env.example .env     # poi riempi i valori (vedi sotto)
```

Cosa inserire in `backend/.env`:
- `LLM_API_KEY` — la chiave del provider (col modello OpenRouter o un endpoint compatibile).
- `AUTH_CLIENTS` — `utente=token` (es. `fabio=il_tuo_token`). Genera il token con `openssl rand -hex 24`.
- `SMTP_*` — solo se vuoi l'invio email di report/conferma. In locale puoi lasciarle vuote e `REPORT_NOTIFY_EMAIL` vuoto.
- `PUBLIC_BASE_URL=http://localhost:8000`.

> Senza `LLM_API_KEY`, usa la modalità **stub** (offline, deterministica) — utile per sviluppo e test.

### 4. Avvio del server
```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 5. Apri nel browser
- `http://localhost:8000/` → landing pubblica (marketing + form lead)
- `http://localhost:8000/admin` → pannello admin (inserisci il **token AUTH_CLIENTS**)
- `http://localhost:8000/health` → healthcheck JSON

Per analisi reali (con LLM): pannello admin → "Nuova analisi" → motore **OpenRouter**.
Per sviluppo/test offline: motore **Stub**.

## Test
```bash
cd backend
python -m pytest tests/ -q        # suite completa (~1.5 min, usa browser Playwright)
python -m pytest tests/test_schemas.py tests/test_llm.py -q   # test veloci (~1s)
```

## Note operative
- **Crawler single-URL**: scansiona solo l'URL inserito (niente BFS).
- **Anti-allucinazione**: ogni raccomandazione porta `evidence_ref` al dato; i check
  per-categoria sono deterministici (non LLM).
- **WordPress**: versione core dal feed RSS o DOM; plugin dai `?ver=` o dal
  `readme.txt` pubblico; CVE da WPVulnerability API. Plugin con versione non
  rilevata → "non verificabile" (mai "vulnerabile" per difetto).
- **`--reload`** ricarica il codice a ogni modifica — comodo per sviluppare.
- Il `.env` reale NON si committa (nel `.gitignore`).

## Docs
- `docs/REPORT_DI_SVILUPPO.md` — stato e decisioni di progetto.
- `docs/DESIGN.md` — design system.
- `docs/SISTEMISTI_systemd.md` — deploy come servizio systemd (user, zero sudo) su VPS.