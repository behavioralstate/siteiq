# Design System — AI SaaS Editorial

## 1) Identità visiva

- **Mood**: premium, luminoso, minimalista, B2B SaaS.
- **Stile**: card-based, rounded, ordinato, con gerarchia tipografica forte.
- **Direzione UI**:
  - sfondo esterno scuro/charcoal;
  - contenitore principale chiaro (off-white);
  - superfici interne bianche;
  - testo principale navy molto scuro;
  - accenti pastel (blue, mint, peach, lilac, yellow).

---

## 2) Palette colore (tokens)

```css
:root {
  --page-bg: #E7E8EA;
  --panel-bg: #F4F3F1;
  --surface: #FFFFFF;
  --surface-muted: #F4F4F2;

  --ink-900: #1B2231; /* testo principale */
  --ink-700: #5C6674; /* testo secondario */
  --ink-500: #8C96A3; /* testo muted */

  --line: #E2E3E7; /* bordi sottili */
  --primary: #1F2A38; /* CTA scura */

  --blue-soft: #DDEEFF;
  --mint-soft: #DDEFE0;
  --peach-soft: #F7DED9;
  --lilac-soft: #E9DDF7;
  --yellow-soft: #F0E8C8;
}
```

---

## 3) Tipografia

- **Font family consigliata**: `Manrope`, `Inter`, o `General Sans` (fallback: `system-ui, sans-serif`).
- **H1 / Hero**: 60–64px, weight 700–800, line-height 0.95–1.05, tracking -0.04em.
- **H2**: 34–42px, weight 700.
- **H3**: 24–30px, weight 600–700.
- **Body**: 16px, line-height 1.5–1.7.
- **Meta**: 12–14px, weight 500–600.
- **Button label**: 14–16px, weight 600.

---

## 4) Spacing, radius, shadow

```css
:root {
  --radius-sm: 16px;
  --radius-md: 22px;
  --radius-lg: 28px;
  --radius-pill: 999px;

  --space-xs: 8px;
  --space-sm: 12px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 44px;

  --shadow-soft: 0 10px 22px rgba(18, 22, 29, 0.04);
}
```

- Layout desktop a 2 colonne con sinistra dominante.
- Gutter consigliato: 24–32px.
- Section spacing verticale: 32–44px.

---

## 5) Componenti chiave

### Navbar
- Logo a sinistra, menu centrale, CTA a destra.
- Altezza 56–64px, links a 14px.

### Hero
- Titolo molto grande su 2 righe.
- Sottotitolo breve, leggibile.
- CTA primaria scura, pill, ad alto contrasto.

### Feature cards
- Card con pastel background, radius grande (20–28px).
- Mix di immagini + metriche + micro-copy.

### KPI cards
- Card bianche con numeri grandi (es. 42%, 60k, 5x).
- Label descrittiva in testo secondario.

### Brand row
- Loghi in scala grigi/muted.

### Testimonial/list cards
- Righe con avatar, nome, ruolo, bottone a destra.
- Sfondo alternato pastel.

### FAQ accordion
- Card bianche con bordo sottile.
- Domanda + icona plus/minus.

---

## 6) Regole di stile

1. Usare **alto contrasto testuale** (ink-900 su surface chiara).
2. Evitare ombre pesanti; usare solo `--shadow-soft`.
3. Privilegiare angoli arrotondati (md/lg) e bottoni pill.
4. Usare colori accento solo per gerarchia visiva secondaria.
5. Mantenere molto respiro (whitespace).
6. Prediligere microcopy breve e chiaro, tono professionale.

---

## 7) Prompt pronto per assegnare questo stile alla tua app

```text
Applica alla mia applicazione uno stile "AI SaaS Editorial Premium" con queste regole:

VISUAL LANGUAGE
- UI luminosa, pulita, minimalista, con superfici chiare.
- Card-based layout con bordi molto arrotondati.
- Contrasto forte tra testo e sfondo, niente effetti pesanti.

DESIGN TOKENS (obbligatori)
- Colori:
  --page-bg: #E7E8EA
  --panel-bg: #F4F3F1
  --surface: #FFFFFF
  --ink-900: #1B2231
  --ink-700: #5C6674
  --ink-500: #8C96A3
  --line: #E2E3E7
  --primary: #1F2A38
  --blue-soft: #DDEEFF
  --mint-soft: #DDEFE0
  --peach-soft: #F7DED9
  --lilac-soft: #E9DDF7
  --yellow-soft: #F0E8C8
- Radius:
  --radius-sm: 16px
  --radius-md: 22px
  --radius-lg: 28px
  --radius-pill: 999px
- Ombre:
  --shadow-soft: 0 10px 22px rgba(18,22,29,0.04)

TYPOGRAPHY
- Font sans moderno (Manrope/Inter o equivalente).
- H1: grande, impattante, tracking leggermente negativo.
- Body: 16px con ottima leggibilità.
- CTA: etichette 14–16px, weight 600.

COMPONENTI DA STILIZZARE
- Navbar (logo sinistra, menu centro, CTA destra).
- Hero con headline grande + sottotitolo + CTA primaria pill scura.
- Sezioni con feature cards pastel.
- KPI cards con metriche in evidenza.
- FAQ accordion con card bianche e bordi sottili.

VINCOLI IMPLEMENTATIVI
- Non cambiare logica business, solo UI.
- Rendere il tema responsive.
- Mantenere accessibilità (contrasto AA, focus visibile, stati hover/focus/active).
- Fornire codice finale pulito e componentizzato.
```

