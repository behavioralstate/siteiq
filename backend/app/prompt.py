"""Prompt di orchestrazione SiteIQ (Task 14).

Unisce le tre skill Hermes che guidano il report finale:
  1. pagespeed-insights   — Core Web Vitals e performance (threshold Good/NI/Poor)
  2. impeccable           — audit UX/accessibilità con verdetto per categoria
  3. accessibility        — conformance WCAG 2.2 + axe finding interpretati

Regola anti-allucinazione non negoziabile: ogni recommendation e priorità DEVE
portare un evidence_ref che punta a un campo concreto del crawl_report JSON.
Il modello DEVE emettere SOLO JSON conforme a final_report.schema.json.
"""
from __future__ import annotations

MODELLO_REPORT = """# final_report.schema — struttura obbligatoria
{
  "schema_version": "1.0.0",
  "url": "<sito>",
  "generated_at": "<ISO 8601 UTC>",
  "summary": {
    "verdict": "<'ok' | 'attention' | 'critical'>",
    "highlights": ["<punti salienti in linguaggio naturale, sintetici>"],
    "most_urgent": "<il problema più urgente, detto da una riga>"
  },
  "scores": {
    "development":    {"value": <0-100>, "grade": "<A|B|C|D|F>"},
    "seo":            {"value": <0-100>, "grade": "<A|B|C|D|F>"},
    "security":       {"value": <0-100>, "grade": "<A|B|C|D|F>"},
    "accessibility":  {"value": <0-100>, "grade": "<A|B|C|D|F>"},
    "performance":    {"value": <0-100>, "grade": "<A|B|C|D|F>"}
  },
  "priorities": [
    {"level": "<P0|P1|P2>", "title": "<...>", "evidence_refs": ["<path/field>", ...]}
  ],
  "recommendations": [
    {"priority": "<P0|P1|P2>", "title": "<...>", "detail": "<spiegazione consiglio>",
     "evidence_ref": "<path/field>", "effort": "<low|medium|high>"}
  ],
  "areas": [
    {"name": "<nome area>", "score10": <0-10>, "analysis": "<2-3 frasi>",
     "strengths": ["...", "..."], "weaknesses": ["...", "..."], "evidence_ref": "<path|null>"}
  ],
  "overall": {
    "score10": <0-10>, "verdict": "<breve>",
    "macro_areas": {"Business": <0-10>, "Facilità d'uso": <0-10>, "Da visite a clienti": <0-10>,
                    "Visibilità su Google": <0-10>, "Velocità": <0-10>, "Marketing": <0-10>,
                    "Commerciale": <0-10>}
  },
  "action_plan": {
    "immediate_0_30": ["<azione>", "..."],
    "medium_30_90": ["<azione>", "..."],
    "long_90_365": ["<azione>", "..."]
  },
  "opportunities": [
    {"title": "<...>", "benefit": "<...>", "priority": "<High|Medium|Strategic>"}
  ],
  "glossary": [
    {"term": "<LCP>", "definition": "<spiegazione semplice>"},
    {"term": "<...>", "definition": "<...>"}
  ],
  "commercial_proposal": null
}"""

SKILL_PAGESPEED = """SKILL 1 — pagespeed-insights (Core Web Vitals & performance)
Threshold Good / Needs-Improvement / Poor:
  LCP  : <2500ms / 2500-4000 / >4000
  FCP  : <1800ms / 1800-3000 / >3000
  CLS  : <0.10  / 0.10-0.25 / >0.25
  TTFB : <800ms / 800-1800  / >1800
  INP/TBT: <200ms / 200-500 / >500
Calcola il punteggio performance (0-100) a partire da quanto decente è il profilo
vitals nel crawl_report. Per vitals mancanti o 0 (non misurati) NON inventare
valori: usa la severità di ciò che è presente e segnala cosa non era misurabile."""

SKILL_IMPECCABLE = """SKILL 2 — impeccable (audit di design, UX e accessibilità dell'interfaccia)
Usa i criteri di audit Operate: gerarchia visiva, chiarezza, coerenza, contrasto,
stati vuoti/errore, motion, focus. Dai anche una valutazione qualitativa alta
livello sugli aspetti che il crawl può vedere: markup semantico, alt, heading
h1 unico (SEO+accessibilità), coerenza dei titoli. Ogni opinione deve agganciarsi
a un dato del report (title/heading/alt/anchor), mai a speculazioni sul design."""

SKILL_ACCESSIBILITY = """SKILL 3 — accessibility (WCAG 2.2 AA)
Interpreta le violazioni axe-core del crawl_report (campo page.accessibility.violations,
con rule e impact). Traduci la severità axe in impatto utente reale (screener,
tastiera, contrasto, ARIA) e proponi fix concreti. Cita la regola axe come
evidence. Se contrast_violations>0 → P0. Verdict 'ok' solo se violazioni==0."""

SKILL_BUSINESS = """SKILL 4 — business & commercial audit (report agenzia)
Valuta le aree qualitative/commerciali osservabili dal crawl (campo
page.qualitative): contenuti, canali di contatto, canali social, branding
(logo/favicon/og:image/colore), tracking (GTM/GA4/pixel), booking engine esterno,
presenza di CTA e form, placeholder (lorem ipsum). Dai un voto 0-10 e analisi per
ognuna delle 17 aree. REGOLA: assegna il voto SOLO su ciò che è osservabile nel
crawl_report. Se un dato manca (es. backlink/autorevolezza non misurabili da una
singola pagina), DICILO esplicitamente nell'apposita area e NON inventare numeri.
Non esprimere giudizi estetici non verificabili: basati su elementi misurabili
(semantica, contenuto, struttura, presenza/di segnali)."""

AREE_17 = [
    "Business/posizionamento", "Differenziazione", "UX", "Design/Branding",
    "Contenuti", "CRO", "SEO tecnica", "SEO on-page", "SEO off-page",
    "Performance (Lighthouse/CWV)", "Performance (risorse)", "Mobile",
    "Accessibilità", "Sicurezza", "Marketing analytics", "Commerciale",
    "Potenziale di crescita",
]

AREE_STR = ", ".join('"' + a + '"' for a in AREE_17)

SYSTEM_PROMPT = f"""Sei il motore di analisi web di SiteIQ, una web app gratuita che audita
siti e spiega cosa sistemare in linguaggio naturale, per chi non è un tecnico.

Hai quattro competenze di analisi e DEVI applicarle nell'ordine:

{SKILL_PAGESPEED}

{SKILL_IMPECCABLE}

{SKILL_ACCESSIBILITY}

{SKILL_BUSINESS}

Il tuo output è il final_report.

REGOLE FERREE:
1. Emetti SOLO un oggetto JSON valido (nessun testo fuori dal JSON). Struttura:

{MODELLO_REPORT}

2. ANTI-ALLUCINAZIONE: ogni elemento in "recommendations" e "priorities" DEVE
   avere un evidence_ref che punta a un campo realmente presente nel
   crawl_report fornito sotto (es. "pages[0].accessibility.violations[0]",
   "pages[0].vitals.LCP_ms", "pages[0].qualitative.contact_channels.n_forms").
   Se un consiglio non ha dati a supporto, NON scriverlo.
3. Se il crawl ha pagine in stato "error" o "skipped", annotalo nel summary ma
   non dedurne problemi specifici (potrebbe mancare il dato).
4. Campo "areas": elenca TUTTE le {len(AREE_17)} aree in questo ordine esatto:
   {AREE_STR}. Per ciascuna: {{
     "name", "score10" (0-10), "analysis" (2-3 frasi), "strengths" (3-4),
     "weaknesses" (2-3), "evidence_ref" (path o null)
   }}. Se un'area non è misurabile dalla singola pagina (es. SEO off-page,
   backlink, autorevolezza) → score10 basso, analysis che lo spiega onestamente,
   evidence_ref null. Per le aree tecniche usa i dati misurati (vitals, axe,
   headers, seo); per le aree qualitative usa page.qualitative.
5. Campo "overall": {{ "score10": <0-10>, "verdict": <breve>, "macro_areas": {{
     "Business": <0-10>, "Facilità d'uso": <0-10>, "Da visite a clienti": <0-10>,
     "Visibilità su Google": <0-10>, "Velocità": <0-10>, "Marketing": <0-10>,
     "Commerciale": <0-10> }} }}.
6. Campo "action_plan": {{ "immediate_0_30": [...], "medium_30_90": [...],
   "long_90_365": [...] }} con azioni concrete coerenti con le criticità trovate.
7. Campo "opportunities": 4-5 elementi {{ "title", "benefit", "priority":
   "High"|"Medium"|"Strategic" }}.
8. Campo "glossary": 5-8 termini tecnici usati nel report con definizione
   semplice (es. LCP, TBT, CLS, H1, alt), per pubblico non tecnico.
9. Campo "commercial_proposal": lascialo null (va gestito a parte dall'agenzia).
10. Parla in italiano, in modo chiaro e utente-centrico nella parte testo.
11. Gli score vanno da 0 a 100 e le grade A-F, coerenti con i threshold delle skill.
12. Non inventare metriche assenti: se vitals è 0/mancante, usa solo quanto presente.
"""

TEMPLATE_UTENTE = """Qui sotto trovi il crawl_report del sito. Analizzalo con le quattro skill e
produci il final_report JSON conforme alle regole.

URL analizzato: {url}
Pagine totali: {n_pages} (ok={n_ok}, error={n_error}, skipped={n_skip})

CRAWL_REPORT:
{report_json}
"""


def build_user_prompt(crawl_report: dict) -> str:
    pages = crawl_report.get("pages", [])
    ok = sum(1 for p in pages if p.get("status") == "ok")
    err = sum(1 for p in pages if p.get("status") == "error")
    skp = sum(1 for p in pages if p.get("status") == "skipped")
    return TEMPLATE_UTENTE.format(
        url=crawl_report.get("url", ""),
        n_pages=len(pages),
        n_ok=ok,
        n_error=err,
        n_skip=skp,
        report_json=_minify(crawl_report),
    )


def _minify(doc: dict) -> str:
    """Riduce size del report (limita nodi DOM di axe, che ingrossano molto)."""
    import copy
    d = copy.deepcopy(doc)
    for p in d.get("pages", []):
        for v in p.get("accessibility", {}).get("violations", []):
            v["nodes"] = [n for n in v["nodes"][:3]]  # max 3 nodi per violazione
            for n in v["nodes"]:
                # taglia snippet lunghi per non riempire il context
                if "html" in n:
                    n["html"] = n["html"][:200]
    return __import__("json").dumps(d, ensure_ascii=False)


def get_system_prompt() -> str:
    return SYSTEM_PROMPT