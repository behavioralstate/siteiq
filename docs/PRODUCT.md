# PRODUCT.md — SiteIQ (nome provvisorio)

## Problema
I siti web dei clienti SMB raccolgono problemi tecnici (Core Web Vitals, accessibilità WCAG, SEO, sicurezza) che restano invisibili finché non degenerano in performance/classifiche/liability. Gli strumenti esistenti (GooUX, Lighthouse, GTmetrix) o sono SaaS chiusi, o producono report tecnici "crusco" che un non-tecnico non sa prioritizzare.

## Visione
Un'analisi web **gratuita**, **AI-first** e **privata**: l'utente incolla un URL, il sistema scansiona il sito, e **Hermes LLM** spiega in linguaggio naturale cosa va sistemato, perché conta, e in che ordine farlo. Ogni consiglio è agganciato al dato tecnico che lo giustifica.

## Differenziazione vs GooUX
| | GooUX | SiteIQ |
|---|---|---|
| Motore | 32 analyzer deterministici + AI extra a crediti | Raccolta tecnica deterministica + interpretazione AI **nel report** |
| AI | Opzionale, consuma crediti | Parte integrante del report |
| Prezzo | SaaS | Gratis (free-tier) con fair-use |
| Privacità | SaaS chiuso | Analisi anonime non persistite | 
| Lingua | IT | IT, consulenziale |

## Utenti target
- Q1: **Piccoli/medi imprenditori** con sito WordPress (clienti tipici di una web agency).
- Q2: **Web agency** (dogfood interno + report per i propri clienti).
- Q3 (post-MVP): operatori **NIS2** che devono documentare conformità a11y/sicurezza.

## Confini del Free Tier (MVP)
- Singola analisi URL: **gratis, senza registrazione**.
- Limite pagine per scan (default 15, configurabile).
- Rate-limit anonimo per IP.
- **Nessuna persistenza** per analisi anonime (o TTL 24h).
- Registrazione/account = solo per chat -> estensioni (monitoraggio continuo, PDF condivisibile, confronti) → fuori MVP.

## Promessa WCAG (dogfooding)
Lo strumento è **conforme WCAG 2.2 AA** mentre audita l'accessibilità dei siti dei clienti. Questa è sia feature (credibilità) sia vincolo di design non negoziabile.

## Non-obiettivi (YAGNI)
- Niente monitoraggio continuo/alert in MVP.
- Niente fix automatici applicati (solo suggeriti).
- Niente multiuser/admin in MVP.
- Niente vendita dati: le analisi anonime non entrano in alcun database.

## Dati di verità
- Schema condiviso: `schema/crawl_report.schema.json` (output crawler), `schema/final_report.schema.json` (output LLM).
- Design: `DESIGN.md` + surface brief `docs/SURFACE_briefs/analyze.md`.
- Competitor reference: gooux.com/it/analyzer-docs.html, /it/funzionalita.html.
