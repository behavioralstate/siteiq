# SiteIQ — Deploy come servizio systemd (USER), istruzioni operative

**Server:** VPS `hermes.pensareweb.it` (213.152.204.110)
**Utente applicazione:** `fabio`
**Percorso repo:** `/home/fabio/siteiq`
**Backend:** FastAPI + uvicorn (Python 3.13, `/usr/bin/python3`)
**Porta:** `8000` — ascolto SOLO su `127.0.0.1` (non esposta a internet)
**Obiettivo:** SiteIQ come servizio indipendente che sopravvive alla sessione che lo ha avviato e riparte al boot.

> **Soluzione installata: USER systemd (zero sudo).** Il servizio è gestito dal manager systemd dell'utente `fabio` con **`Linger=yes`** abilitato, quindi gira anche senza login e parte al boot. Nessun privilegio di root richiesto per installare, abilitare o gestire.

---

## Stato attuale (installato e attivo)

```bash
systemctl --user status siteiq        # active (running)
systemctl --user is-enabled siteiq    # enabled
curl -s http://127.0.0.1:8000/health  # {"status":"ok","service":"siteiq-api",...}
```

---

## Punti chiave dell'implementazione

- **Unit:** `~/.config/systemd/user/siteiq.service`
- **Abilitazione al boot:** symlink in `~/.config/systemd/user/default.target.wants/`
- **Linger:** `loginctl show-user fabio | grep Linger` deve dare `Linger=yes`
  (senza linger i servizi user si fermano allo scollegamento della sessione).
- **`EnvironmentFile`:** `/home/fabio/siteiq/backend/.env` — contiene i token LLM/admin.
  ⚠️ Non copiarlo altrove; permessi restano a `fabio` (in chiaro su disco, com'era col server manuale).
- **`Restart=on-failure`:** riavvia il servizio solo se crasha (non per stop manuale).

### Contenuto della unit (`~/.config/systemd/user/siteiq.service`)

```ini
[Unit]
Description=SiteIQ — analisi siti web AI (FastAPI/uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/fabio/siteiq/backend
EnvironmentFile=/home/fabio/siteiq/backend/.env
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

---

## Comandi di gestione quotidiana

| Operazione | Comando |
|---|---|
| Stato | `systemctl --user status siteiq` |
| Riavvio | `systemctl --user restart siteiq` |
| Stop | `systemctl --user stop siteiq` |
| Avvio | `systemctl --user start siteiq` |
| Log in tempo reale | `journalctl --user -u siteiq -f` |
| Ultimi 100 log | `journalctl --user -u siteiq -n 100` |
| Ripartire al boot | `systemctl --user enable siteiq` (già fatto) |

> Le unit user sono per-utente: vanno eseguite **come `fabio`** (nessun `sudo`, nessun `systemctl` globale).

---

## Verifica end-to-end dal browser

```bash
ssh -N -L 8000:127.0.0.1:8000 fabio@hermes.pensareweb.it
# aprire http://127.0.0.1:8000  (landing) e /admin (pannello)
```

---

## Troubleshooting

- **Servizio "inactive (dead)" / muore all'uscita del terminale** → controllare il Linger:
  ```bash
  loginctl enable-linger fabio   # richiede root/sudo, se non già attivo
  ```
- **Non parte al boot** → verificare `systemctl --user is-enabled siteiq` = `enabled` e il Linger.
- **Porta occupata** → capire chi ascolta la 8000 prima di avviare il servizio:
  ```bash
  ss -ltnp | grep 8000
  ```
  Spegnere solo il processo specifico (`kill <PID>`), mai `pkill -f uvicorn` alla cieca se coesistono altri progetti uvicorn.
- **Il codice non rispecchia le modifiche** → dopo un aggiornamento in `~/siteiq`:
  `systemctl --user restart siteiq` (il nuovo codice si carica solo a nuovo avvio del processo).

---

## Note operative per la squadra

- **Porta 8000 resterà su `127.0.0.1`** (nessuna esposizione pubblica diretta). L'accesso esterno, se/quando servirà, va tramite **nginx reverso proxy + Let's Encrypt** sul dominio `siteiq.it` (task separato, non incluso qui).
- **DB SQLite** e cartella `reports/` vivono in `/home/fabio/siteiq/backend/` (working dir del servizio). Includere tutto il repo/dati nei backup (retention 7 gg, policy NIS2 dell'infra).
- **Dipendenze Python**: installate per-utente `fabio` (`pip3 install --user --break-system-packages`). Non richiedono venv con `/usr/bin/python3`.
- **Costo LLM**: ogni analisi consuma credito OpenRouter — nessun rate-limit applicativo; prima di un'esposizione pubblica serviranno limiti (fuori scope).
- **Cancellazione servizio** (se mai): `systemctl --user disable --now siteiq && rm ~/.config/systemd/user/siteiq.service`

---

*Aggiornato il 2026-10-15 · versione user-systemd installata (zero sudo). In caso di dubbi contattare l'admin di riferimento (Fabio).*
