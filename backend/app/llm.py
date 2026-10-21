"""Client LLM per SiteIQ (astrazione OpenAI-compatible).

Due implementazioni:
  - StubLlm     : deterministico, offline, per test (Task 13 test).
  - OpenRouterLlm: chiama OpenRouter (o qualsiasi endpoint OpenAI-compatible)
                   impostando LLM_BASE_URL / LLM_API_KEY / LLM_MODEL via env.

Il prompt di orchestrazione (Task 14) usa le 3 skill: pagespeed-insights,
impeccable, accessibility — deve EMETTERE solo JSON conforme a
final_report.schema.json, con vincolo anti-allucinazione: ogni
recommendation/priority DEVE portare un evidence_ref verso il crawl_report.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx


def _load_env(path: str | None = None):
    """Carica un semplice .env (key=value, # commenti) senza dipendenze."""
    env_path = Path(path or (Path(__file__).resolve().parent.parent / ".env"))
    if not env_path.is_file():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


class BaseLlm:
    """Unit goette interface: analyze(raw_report: dict) -> dict (final_report)."""

    name = "base"

    def analyze(self, raw_report: dict) -> dict:
        raise NotImplementedError


class StubLlm(BaseLlm):
    """Restituisce un final_report controllato (deterministico, offline)."""

    name = "stub"

    def analyze(self, raw_report: dict) -> dict:
        pages = raw_report.get("pages", [])
        ok_pages = [p for p in pages if p.get("status") == "ok"]
        a11y_violations = sum(
            len(p.get("accessibility", {}).get("violations", [])) for p in ok_pages
        )
        missing_alt = sum(p.get("images_missing_alt", 0) for p in ok_pages)

        recommendations = []
        if a11y_violations:
            recommendations.append({
                "priority": "P0",
                "title": "Risolvi le violazioni di accessibilità",
                "detail": (
                    f"Trovate {a11y_violations} violazioni axe-core sul sito. "
                    "Le più comuni sono contrasto colore, attributi alt mancanti "
                    "e landmarks. Correggetele per conformità WCAG 2.2 AA."
                ),
                "evidence_ref": "accessibility.violations",
                "effort": "medium",
            })
        if missing_alt:
            recommendations.append({
                "priority": "P1",
                "title": "Aggiungi testi alternativi alle immagini",
                "detail": f"Almeno {missing_alt} immagini senza attributo alt.",
                "evidence_ref": "images_missing_alt",
                "effort": "low",
            })

        # Score: penalità proporzionale ma non annullante (0-100 realistico).
        # violazioni axe: -1.5 punti l'una; alt mancanti: -1 a testa; soft-cap minimo 10.
        a11y_penalty = min(70, a11y_violations * 1.5)
        alt_penalty = min(20, missing_alt * 1.0)
        score_val = max(10, round(100 - a11y_penalty - alt_penalty))
        grade = "A" if score_val >= 90 else "B" if score_val >= 80 else "C" \
            if score_val >= 70 else "D" if score_val >= 60 else "F"
        a11y_score = max(10, round(100 - a11y_penalty))

        return {
            "schema_version": "1.0.0",
            "url": raw_report.get("url", ""),
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "summary": {
                "verdict": ("ok" if score_val >= 80 else "attention"),
                "highlights": [
                    f"Analizzate {len(ok_pages)} pagine valide su {len(pages)} totali."
                ],
                "most_urgent": recommendations[0]["title"] if recommendations
                else "Nessun problema urgente rilevato.",
            },
            "scores": {
                "development": {"value": score_val, "grade": grade},
                "seo": {"value": score_val, "grade": grade},
                "security": {"value": score_val, "grade": grade},
                "accessibility": {"value": a11y_score, "grade": grade},
                "performance": {"value": score_val, "grade": grade},
            },
            "priorities": [
                {"level": r["priority"], "title": r["title"],
                 "evidence_refs": [r["evidence_ref"]]}
                for r in recommendations
            ],
            "recommendations": recommendations,
            "areas": [
                {"name": "Business/posizionamento", "score10": 7,
                 "analysis": "Comunicazione chiara di posizionamento e servizi.",
                 "strengths": ["Proposta completa", "Testo su ubicazione"],
                 "weaknesses": ["Sezioni incomplete"], "evidence_ref": None},
                {"name": "Differenziazione", "score10": 8,
                 "analysis": "Vantaggi chiari per prenotazione diretta.",
                 "strengths": ["Vantaggi misurabili", "Segmentazione"],
                 "weaknesses": ["Promessa distintiva mancante"], "evidence_ref": None},
                {"name": "UX", "score10": 5,
                 "analysis": "Struttura ampia ma performance mobile critica.",
                 "strengths": ["Architettura coerente", "Nessuna pagina rotta"],
                 "weaknesses": ["LCP alto", "H1 mancanti"],
                 "evidence_ref": "pages[0].vitals.LCP_ms"},
                {"name": "Design/Branding", "score10": 6,
                 "analysis": "Logo e favicon presenti, manca padding social.",
                 "strengths": ["Logo personalizzato", "Favicon"],
                 "weaknesses": ["Nessun og:image"],
                 "evidence_ref": "pages[0].qualitative.branding.has_og_image"},
                {"name": "Contenuti", "score10": 5,
                 "analysis": "Testi curati su molte pagine, placeholder su camere.",
                 "strengths": ["Testi descrittivi"],
                 "weaknesses": ["Lorem ipsum"],
                 "evidence_ref": "pages[0].qualitative.content.lorem_ipsum"},
                {"name": "CRO", "score10": 7,
                 "analysis": "Moduli e canali diffusi, funnel su piattaforma esterna.",
                 "strengths": ["Canali di contatto", "Vantaggi diretti"],
                 "weaknesses": ["Booking esterno"],
                 "evidence_ref": "pages[0].qualitative.booking_external_hosts"},
                {"name": "SEO tecnica", "score10": 8,
                 "analysis": "HTTPS, sitemap, canonical corretti.",
                 "strengths": ["HTTPS valido", "Sitemap completa"],
                 "weaknesses": ["Nessuna criticità bloccante"], "evidence_ref": None},
                {"name": "SEO on-page", "score10": 5,
                 "analysis": "Home ottimizzata, pagine interne con title duplicati.",
                 "strengths": ["Home corretta", "Punteggio SEO alto"],
                 "weaknesses": ["H1 mancanti su interne"],
                 "evidence_ref": "pages[0].seo.headings"},
                {"name": "SEO off-page", "score10": 4,
                 "analysis": "Solo un canale social rilevato; backlink non misurabili.",
                 "strengths": ["Profilo social presente"],
                 "weaknesses": ["Autorevolezza non misurabile"], "evidence_ref": None},
                {"name": "Performance (Lighthouse/CWV)", "score10": 3,
                 "analysis": "Performance mobile critica.",
                 "strengths": ["CLS eccellente"],
                 "weaknesses": ["LCP 15s", "TBT alto"],
                 "evidence_ref": "pages[0].vitals.LCP_ms"},
                {"name": "Performance (risorse)", "score10": 4,
                 "analysis": "TTFB buono, ma risorse render-blocking non ottimizzate.",
                 "strengths": ["TTFB nella norma"],
                 "weaknesses": ["Immagini non ottimizzate"],
                 "evidence_ref": "pages[0].qualitative.media.total_images"},
                {"name": "Mobile", "score10": 4,
                 "analysis": "Layout adattato ma performance su smartphone pessima.",
                 "strengths": ["Viewport corretto"],
                 "weaknesses": ["LCP mobile alto"],
                 "evidence_ref": "pages[0].vitals.LCP_ms"},
                {"name": "Accessibilità", "score10": 8,
                 "analysis": "Punteggio axe discreto, contrasto e alt da sistemare.",
                 "strengths": ["Lang corretto"],
                 "weaknesses": ["Contrasto", "Alt mancanti"],
                 "evidence_ref": "pages[0].accessibility.violations"},
                {"name": "Sicurezza", "score10": 4,
                 "analysis": "HTTPS valido ma header di sicurezza assenti.",
                 "strengths": ["HTTPS valido", "Redirect corretto"],
                 "weaknesses": ["Header mancanti"],
                 "evidence_ref": "pages[0].http_headers"},
                {"name": "Marketing analytics", "score10": 7,
                 "analysis": "GTM e GA4 presenti.",
                 "strengths": ["GA4+GTM installati"],
                 "weaknesses": ["Nessuna conversione configurata"],
                 "evidence_ref": "pages[0].qualitative.tracking"},
                {"name": "Commerciale", "score10": 6,
                 "analysis": "Forte impronta commerciale ma booking delegato.",
                 "strengths": ["Vantaggi diretti", "Molti canali"],
                 "weaknesses": ["Funnel esterno"],
                 "evidence_ref": "pages[0].qualitative.booking_external_hosts"},
                {"name": "Potenziale di crescita", "score10": 7,
                 "analysis": "Base di contenuti ricca, problemi risolvibili con priorità.",
                 "strengths": ["Struttura ricca", "Brand storico"],
                 "weaknesses": ["Performance e contenuti da sistemare"],
                 "evidence_ref": None},
            ],
            "overall": {
                "score10": 5,
                "verdict": "Il sito ha problemi seri da sistemare.",
                "macro_areas": {
                    "Business": 7, "Facilità d'uso": 5, "Da visite a clienti": 7,
                    "Visibilità su Google": 6, "Velocità": 4, "Marketing": 7,
                    "Commerciale": 6,
                },
            },
            "action_plan": {
                "immediate_0_30": [
                    "Aggiungere header di sicurezza",
                    "Inserire H1 mancanti",
                    "Correggere titoli duplicati",
                    "Attivare compressione testo",
                ],
                "medium_30_90": [
                    "Ottimizzare risorse render-blocking",
                    "Configurare conversioni in GA4",
                    "Ottimizzare immagini con lazy loading",
                ],
                "long_90_365": [
                    "Integrare il booking engine nel sito",
                    "Creare landing page per segmenti",
                    "Sviluppare strategia social e reputazione",
                ],
            },
            "opportunities": [
                {"title": "Ottimizzazione performance completa",
                 "benefit": "Riduzione tempi di caricamento e miglioramento UX",
                 "priority": "High"},
                {"title": "Correzione struttura H1 e titoli",
                 "benefit": "Migliore accessibilità e SEO",
                 "priority": "High"},
                {"title": "Completamento contenuti",
                 "benefit": "Aumento fiducia e conversione",
                 "priority": "Medium"},
                {"title": "Integrazione booking engine",
                 "benefit": "Controllo diretto del funnel",
                 "priority": "Medium"},
                {"title": "Landing page per nicchie",
                 "benefit": "Catturare segmenti specifici",
                 "priority": "Strategic"},
            ],
            "glossary": [
                {"term": "LCP", "definition": "Tempo in cui il contenuto principale diventa visibile."},
                {"term": "TBT", "definition": "Tempo in cui la pagina non risponde all'utente."},
                {"term": "CLS", "definition": "Stabilità visiva della pagina."},
                {"term": "H1", "definition": "Intestazione principale di una pagina."},
                {"term": "Alt", "definition": "Testo alternativo delle immagini per screen reader."},
            ],
            "commercial_proposal": None,
        }


class OpenRouterLlm(BaseLlm):
    """Chiama qualsiasi endpoint OpenAI-compatible (default OpenRouter)."""

    name = "openrouter"

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None):
        _load_env()
        self.base_url = os.environ.get("LLM_BASE_URL", base_url or "https://openrouter.ai/api/v1")
        self.api_key = os.environ.get("LLM_API_KEY", api_key or "")
        self.model = os.environ.get("LLM_MODEL", model or "deepseek/deepseek-chat-v3.1")

    def analyze(self, raw_report: dict) -> dict:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY non impostata (usa --stub per test/offline)")
        from app.prompt import build_user_prompt, get_system_prompt
        system = get_system_prompt()
        user = build_user_prompt(raw_report)
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        last_err = None
        for attempt in range(2):  # fino a 2 tentativi: il 1° può restituire JSON troncato
            r = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                    "max_tokens": 8000,
                },
                timeout=180,
            )
            r.raise_for_status()
            payload = r.json()
            content = payload["choices"][0]["message"]["content"]
            self.last_usage = payload.get("usage", {})
            try:
                data = self._extract_json(content)
                self._validate(data)
                return data
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt == 0:
                    user += ("\n\nNota: la risposta precedente non era un JSON valido "
                             "(probabilmente troncato). Ricomponi l'intero final_report "
                             "come UN SOLO oggetto JSON completo, senza troncarlo.")
        raise RuntimeError(f"LLM ha prodotto JSON non valido dopo 2 tentativi: {last_err}")

    @staticmethod
    def _extract_json(content: str) -> dict:
        """Trova l'oggetto JSON nella risposta (gestendo testo o preambolo) e lo decodifica."""
        import json as _json
        s = content.strip()
        # se non parte con '{', cerca la prima '{'
        start = s.find("{")
        if start > 0:
            s = s[start:]
        try:
            return _json.loads(s)
        except _json.JSONDecodeError:
            # JSON troncato: trova l'ultima '}' bilanciata
            depth = 0
            end = -1
            in_str = False
            esc = False
            for i, ch in enumerate(s):
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
            if end > 0:
                return _json.loads(s[: end + 1])
            raise

    # Ultimo utilizzo token registrato (dict: prompt_tokens, completion_tokens, total_tokens, ...)
    last_usage: dict = {}

    def _validate(self, data: dict):
        """Normalizza scostamenti comuni dell'LLM e valida contro final_report.schema.json."""
        self._normalize(data)
        import json as _json
        from pathlib import Path as _P
        from jsonschema import Draft202012Validator
        schema = _json.load(
            open(_P(__file__).resolve().parent.parent.parent / "schema" / "final_report.schema.json")
        )
        errs = list(Draft202012Validator(schema).iter_errors(data))
        if errs:
            raise RuntimeError(f"LLM ha prodotto report non conforme: {errs[:3]}")

    def _normalize(self, d: dict):
        """Sistema i formati vicini ma non conformi emessi dai modelli:
        - glossary come dict {term: definition} → lista di {term, definition};
        - opportunities come dict {title: benefit} → lista di {title, benefit, priority};
        - action_plan chiavi eventualmente in italiano → forma attesa inglese."""
        # glossary: dict {term: definition}
        g = d.get("glossary")
        if isinstance(g, dict):
            d["glossary"] = [{"term": str(k), "definition": str(v)} for k, v in g.items()]
        # opportunities: dict {title: benefit}
        o = d.get("opportunities")
        if isinstance(o, dict):
            d["opportunities"] = [{"title": str(k), "benefit": str(v),
                                   "priority": "Medium"} for k, v in o.items()]
        # action_plan: uniforma le chiavi attese in inglese
        ap = d.get("action_plan")
        if isinstance(ap, dict):
            EXPECTED = {"immediate_0_30", "medium_30_90", "long_90_365"}
            found = set(ap.keys()) & EXPECTED
            if not found:  # nessuna chiave attesa: prova a mappare da parole corte
                alias = {"immediat": "immediate_0_30", "subit": "immediate_0_30",
                         "0-30": "immediate_0_30", "medio": "medium_30_90",
                         "30-90": "medium_30_90", "lungo": "long_90_365",
                         "90-365": "long_90_365", "90-365 ": "long_90_365"}
                rebuilt = {}
                for k, v in ap.items():
                    kl = str(k).lower()
                    tgt = next((n for a, n in alias.items() if a in kl), None)
                    if tgt:
                        rebuilt.setdefault(tgt, []).extend(v if isinstance(v, list) else [v])
                d["action_plan"] = rebuilt if rebuilt else ap


def make_llm(stub: bool = False) -> BaseLlm:
    if stub:
        return StubLlm()
    return OpenRouterLlm()