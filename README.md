# SiteIQ

Analizzatore web AI-first: scansiona un sito (performance, accessibilità, sicurezza,
SEO) e l'AI interpreta i dati in linguaggio naturale — **17 aree**, piano d'azione,
giudizio finale, e verifica WordPress (CVE di core e plugin). Frontend pubblica di
marketing + pannello admin protetto da Bearer token.

## Struttura

```
siteiq/
├── backend/
│   ├── app/            # FastAPI: client LLM, crawler, checks, wpvuln, jobs, netguard…
│   │   └── best/       # superficie BEST per agenti (manifest, comandi, eventi, query)
│   ├── tests/          # suite pytest
│   └── .env.example    # modello configurazione (copia in .env)
├── frontend/           # landing + admin + report (vanilla, serviti da FastAPI)
├── schema/             # contratti JSON condivisi crawler↔LLM
│   └── best/           # JSON Schema di comandi, eventi e query BEST (fonte del catalogo)
├── tests_fixture/      # siti statici per i test del crawler
└── requirements.txt
```

## Avvio in locale

### 1. Requisiti
Python 3.13+ (testato su 3.14), `pip`.

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
- `AUTH_CLIENTS` — `utente=token`, più utenti separati da virgola (es. `anna=tok1,bruno=tok2`). Genera il token con `openssl rand -hex 24`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` — solo se vuoi l'invio email di report/conferma. In locale puoi lasciare `SMTP_HOST` e `REPORT_NOTIFY_EMAIL` vuoti.
- `PUBLIC_BASE_URL=http://localhost:8000`.
- Limiti opzionali (`SITEIQ_MAX_CONCURRENT_JOBS`, rate limit della landing…): vedi `.env.example`.

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

## Superficie BEST (agenti)

SiteIQ espone una superficie [BEST — Behavioral State Protocol](https://behavioralstate.io/specs)
per agenti AI: il punto di ingresso è il manifest `GET /.well-known/best`, da cui un agente
scopre da solo comandi, eventi e query. Dai client MCP si usa con
[`best-mcp`](https://github.com/behavioralstate/spec/tree/main/mcp-server) puntato
all'URL del servizio.

Questo primo giro è volutamente minimo:
- **pubblica**, senza autenticazione, con rate limit per IP (`SITEIQ_BEST_COMMANDS_PER_IP_PER_HOUR`);
- **solo analisi deterministica** (crawl, check, WordPress): niente LLM, quindi niente costi
  OpenRouter da chiamate anonime, niente pagina report e niente email;
- **in memoria**: comandi accettati con `202`, analisi ed eventi tenuti circa un'ora
  (`SITEIQ_JOB_TTL_S`), persi al riavvio.

Il catalogo nasce dai file in `schema/best/`. Conformità alla spec:

```bash
npx @behavioralstate/best-validate http://127.0.0.1:8000
```

`PUBLIC_BASE_URL` deve essere l'indirizzo pubblico: da lì derivano `http.endpoint` e gli URI
`dataschema` del manifest.

## Test
```bash
cd backend
python -m pytest tests/ -q        # suite completa (~1.5 min, usa browser Playwright)
python -m pytest tests/test_schemas.py tests/test_llm.py -q   # test veloci (~1s)
```

## Note operative
- **Crawler single-URL**: scansiona solo l'URL inserito (niente BFS).
- **SSRF**: si analizzano solo host pubblici. Il browser del crawler esce da un
  proxy interno che si collega solo a IP pubblici verificati (redirect e
  sotto-risorse inclusi). Per analizzare `localhost`/LAN in sviluppo:
  `SITEIQ_ALLOW_PRIVATE_TARGETS=1` (mai in produzione).
- **Landing pubblica**: 1 scansione gratuita per casella confermata (minuscole e
  `+etichetta` normalizzate), rate limit per IP/email, coda di job limitata.
  Dietro nginx avvia uvicorn con `--proxy-headers --forwarded-allow-ips=127.0.0.1`,
  altrimenti tutti i client hanno l'IP del proxy.
- **Un solo processo uvicorn**: job e rate limit sono in memoria (niente `--workers`).
- **Anti-allucinazione**: ogni raccomandazione porta `evidence_ref` al dato; i check
  per-categoria sono deterministici (non LLM).
- **WordPress**: versione core dal meta generator o dal feed RSS; plugin dai
  `?ver=` (scartati se uguali alla versione core, che è il default di WP) o dal
  `readme.txt` pubblico; CVE da WPVulnerability API. Plugin con versione non
  rilevata → "non verificabile" (mai "vulnerabile" per difetto).
- **`--reload`** ricarica il codice a ogni modifica — comodo per sviluppare.
- Il `.env` reale NON si committa (nel `.gitignore`).

## Docs
- `REPORT_DI_SVILUPPO.md` — stato e decisioni di progetto.
- `docs/DESIGN.md` — design system.
- `docs/SISTEMISTI_systemd.md` — deploy come servizio systemd (user, zero sudo) su VPS.