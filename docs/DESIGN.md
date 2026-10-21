# DESIGN.md — SiteIQ (reshape 2026-10-07)

## World visuale (design system "AI SaaS Editorial Premium")

Il brief fissa un design system esplicito (`design-system.md`) — **le parole del
brief vincono**, applicate letteralmente. Mood: **premium, luminoso, minimalista,
card-based, B2B SaaS** — sfondo esterno grigio chiaro, contenuto in un pannello
off-white arrotondato che galleggia, superfici bianche dentro, ink navy e accenti
pastel (blue/mint/peach/lilac/yellow). Manrope, pill CTA scura, radius grandi,
una sola ombra soft.

Sostituisce i world precedenti ("carta fredda + un accento" e, prima, "grafite
scura + verde acid").

**Momento memorabile**: l'anteprima del report in hero — score grande a scala con
barre animate per area (Performance/Accessibilità/Sicurezza), in card bianca. Serve
il principio della skill "apri con la cosa più caratteristica" (il report come
oggetto). Tutto il resto è quieto e disciplinato.

## Tokens colore (da design-system.md, contrato AA verificato)

| Token | Hex | Uso |
|---|---|---|
| `--page-bg` | `#E7E8EA` | sfondo pagina |
| `--panel-bg` | `#F4F3F1` | pannello off-white |
| `--surface` | `#FFFFFF` | superfici bianche |
| `--ink-900` | `#1B2231` | testo principale |
| `--ink-700` | `#5C6674` | testo secondario |
| `--ink-500` | `#8C96A3` | decorativo/luoghi (non testo — sotto AA) |
| `--line` | `#E2E3E7` | bordi |
| `--primary` | `#1F2A38` | CTA scura |
| `--blue/mint/peach/lilac/yellow-soft` | — | card pastel |
| `--success` | `#2F7D4F` | verdetto ok (AA su chiaro) |
| `--warn` | `#B07D24` | attenzione (AA) |
| `--danger` | `#C2413B` | errore P0 (AA) |
| `--focus` | `#2A4E8C` | focus ring |

> Nota AA: `--ink-500` NON è usato per testo (2.7:1 — sotto soglia); i testi muted
> usano `--ink-700`. Testo nelle card pastel scurito a `#414B5C` per stare ≥4.5:1
> sul pastel più chiaro.

## Tipografia

- **Manrope** (una sola famiglia, chiaramente scontata su body/UI e numeri).
- H1: 60-64px, weight 800, tracking -0.04em, line-height ~1.05.
- H2 34-42 / H3 24-30; body 16px (1.5-1.7); meta 12-14px; button 14-16px w600.
- **Vietati** (tells di default): accent da singola parola nei heading, ALL-CAPS
  decorativi, label "WORD — fragment", meta con punti medi.

## Layout

- **Contenitore**: pagina su sfondo grigio; contenuto in pannello `--panel-bg`
  con `radius-lg` e `--shadow-soft`, che galleggia (media 1240px, padding 20px).
- **2 colonne** in hero/CTA con sinistra dominante; gutter 40-48px.
- Sezioni con padding 32-44px; header 56-64px.
- Navbar: logo sinistra · menu centro · **CTA pill scura** destra (su mobile resta solo il CTA).

## Componenti

- Navbar (pill), hero (headline + kpi pastel + CTA scura), feature cards pastel
  (4 aree, icone SVG, stat pill), steps (numerati, sequenza), KPI row (numeri
  grandi), FAQ accordion (card bianche, bordo sottile, icona plus→minus),
  CTA finale (pannello scuro) con form lead.

## Motion & icone

- **Un solo momento orchestrato all'hero** (reveal) + barre che crescono (growBar).
- Hover risponde all'azione: feature card lift, FAQ plus→minus, focus-visible.
- `prefers-reduced-motion` disattiva animazioni/transizioni.
- Icone: **SVG inline** (`stroke`), non emoji/font-icon.

## Accessibilità (non negoziabile)

- Contrasto AA verificato con axe (WCAG 2.1 A/AA) su desktop e mobile: **0 violazioni**.
- Focus visibile (`--focus` outline 3px), aria-expanded su accordion, label associate.
- Tastiera full; `prefers-reduced-motion`.

## Allineamento esistente

- Frontend: `landing.css` (base) + `admin.css` (interfaccia). `styles.css` rimosso.
- La **pagina report HTML** (backend `email_report.py`, carta chiara) è coerente col
  world chiaro; non è stata ancora rifatta coi token pastel — task separato.