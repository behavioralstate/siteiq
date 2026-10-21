# Surface Brief — Analyze (app Operate)

## Successo del visitatore
L'utente inserisce un URL, vede l'avanzamento della scansione, e capisce in <60s **cosa va sistemato e perché**, senza essere un tecnico.

## Struttura della surface
1. **Hero form** — campo URL + CTA "Analizza gratis". Placeholder: `https://iltuosito.it`. Label visibile (non solo placeholder).
2. **Live progress** — stepper 4 passi: Crawl → Performance → Accessibilità → Report AI. `div role="status" aria-live="polite"` che annuncia "Analizzata pagina 3 di 12…".
3. **Scoreboard** — 5 card (Sviluppo, SEO, Sicurezza, Accessibilità, Performance), ognuna: donut 0-100 + grade (A-F). Ordine: Accessibilità prima se scopo a11y, altrimenti Performance prima — decidi in Fase 4 Task 18 con test utente.
4. **Priorità** — P0 (rosso), P1 (ambra), P2 (neutro). Ogni item collassabile, con ref al finding grezzo.
5. **Recommendazioni AI** — testo naturale per priorità + effort (low/medium/high).

## Stati
- **Empty**: "Nessuna violazione 🎉" o "Inserisci un URL per iniziare".
- **Error**: URL non valido / sito irraggiungibile → messaggio in `role=alert` chiaro, CTA riprova.
- **Loading**: stepper attivo; niente skeleton confusi — mostra cosa sta passando.

## Vincoli WCAG su questa surface
- All form: label + `aria-describedby` per help; errore inline in `role=alert`.
- Donut: mai colore da solo → sempre affiancato dal numero e grade testuale.
- Collassabili: funzionanti solo da tastiera, stato espresso con `aria-expanded`.
- Contrasto: token DESIGN.md (§), range tutti AA.

## Criteri di accettazione
- Scansione singolo URL completa end-to-end in <90s (target, non bloccante).
- Utente non-tecnico sa dire "il problema più urgente" leggendo la schermata.
- Zero violazioni axe di severity serious/critical in CI.

---

## Direction contract (code-led — aggiunto 2026-10-06)

**THESIS.** Per una tool che si usa per operare (non ammirare), questa page rifiuta sia il banner-SaaS di analytics sia il dashboard-crusco stile GooUX. Il meccanismo — *il dato tecnico che diventa una frase di consulenza in italiano, col suo `evidence_ref`* — è protagonista dal primo viewport, non nascosto in un secondo schermo.

**OWN-WORLD.** Paleta grafite scura `#0F1115`, testo `#E8EAED`, accenti semantici verde `#34C77B` / ambra `#E2A63A` / rosso `#F2645A`, focus-ring azzurro `#7AA2FF`; tutto ≥ AA. Sans workhorse (Inter/system) con heading a peso v25, mai gradiente né glow. Componenti dal lessico proprio: score = numero + grade + tratto (mai il solo colore); evidenza = bolla del finding grezzo.

**STORY.** Il visitatore incolla un URL e in <60s vede 5 score + 3-4 frasi che dicono *la cosa più urgente e perché conta*, ciascuna riconducibile al dato. Capisce: "posso passarlo a qualcuno che sistemi."

**FIRST VIEWPORT.** Header sottile (brand + stato). Al centro assoluto il **form di analisi**: campo URL largo + CTA verde "Analizza gratis"; sotto, una riga quieta con 3 chip passivi (Performance · Accessibilità · Sicurezza). Niente hero-metric né kicker: la macchina in azione è la prima cosa.

**FORM.** Form = surface Operate "analyze" dentro il world DESIGN.md (estension, code-led: niente concept roll per una Operate col world già fissato). Seed/key: `design` (world esistente).

**FINISH.** unreviewed and undocumented is unfinished; questo build si conclude con la finish review (audit axe sull'app servita), il verdetto, DESIGN.md aggiornato, e ogni raster pubblicato con la propria provenienza.