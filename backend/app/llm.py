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

import json
from datetime import datetime, timezone
from functools import lru_cache

import httpx
from jsonschema import Draft202012Validator

from app.config import REPO_ROOT, env_str
from app.i18n import DEFAULT_LOCALE, SUPPORTED, Translator, t
from app.prompt import AREA_IDS, MACRO_IDS

FINAL_SCHEMA_PATH = REPO_ROOT / "schema" / "final_report.schema.json"
USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "cost")


@lru_cache(maxsize=1)
def _final_report_validator() -> Draft202012Validator:
    with open(FINAL_SCHEMA_PATH, encoding="utf-8") as f:
        return Draft202012Validator(json.load(f))


class BaseLlm:
    """Interfaccia comune: analyze(raw_report, locale) -> dict (final_report),
    con i testi per l'utente nella lingua `locale`."""

    name = "base"
    is_stub = False

    def analyze(self, raw_report: dict, locale: str = DEFAULT_LOCALE) -> dict:
        raise NotImplementedError


# Stub: voti ed evidenze fissi per area; i testi dimostrativi stanno nel
# catalogo (stub.areas.<id>.analysis / strengths / weaknesses).
_STUB_AREAS = {
    "business_positioning": (7, None),
    "differentiation": (8, None),
    "ux": (5, "pages[0].vitals.LCP_ms"),
    "design_branding": (6, "pages[0].qualitative.branding.has_og_image"),
    "content": (5, "pages[0].qualitative.content.lorem_ipsum"),
    "cro": (7, "pages[0].qualitative.booking_external_hosts"),
    "technical_seo": (8, None),
    "onpage_seo": (5, "pages[0].seo.headings"),
    "offpage_seo": (4, None),
    "performance_cwv": (3, "pages[0].vitals.LCP_ms"),
    "performance_resources": (4, "pages[0].qualitative.media.total_images"),
    "mobile": (4, "pages[0].vitals.LCP_ms"),
    "accessibility": (8, "pages[0].accessibility.violations"),
    "security": (4, "pages[0].http_headers"),
    "marketing_analytics": (7, "pages[0].qualitative.tracking"),
    "commercial": (6, "pages[0].qualitative.booking_external_hosts"),
    "growth_potential": (7, None),
}
_STUB_MACRO = {"business": 7, "usability": 5, "conversion": 7, "search_visibility": 6,
               "speed": 4, "marketing": 7, "commercial": 6}
_STUB_OPPORTUNITY_PRIORITIES = ("High", "High", "Medium", "Medium", "Strategic")
_STUB_GLOSSARY = ("LCP", "TBT", "CLS", "H1", "Alt")


class StubLlm(BaseLlm):
    """Restituisce un final_report controllato (deterministico, offline)."""

    name = "stub"
    is_stub = True

    def analyze(self, raw_report: dict, locale: str = DEFAULT_LOCALE) -> dict:
        tr = Translator(locale)
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
                "title": tr("stub.rec_a11y.title"),
                "detail": tr("stub.rec_a11y.detail", count=a11y_violations),
                "evidence_ref": "accessibility.violations",
                "effort": "medium",
            })
        if missing_alt:
            recommendations.append({
                "priority": "P1",
                "title": tr("stub.rec_alt.title"),
                "detail": tr("stub.rec_alt.detail", count=missing_alt),
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
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "verdict": ("ok" if score_val >= 80 else "attention"),
                "highlights": [tr("stub.highlight", ok=len(ok_pages), total=len(pages))],
                "most_urgent": recommendations[0]["title"] if recommendations
                else tr("stub.no_urgent"),
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
                {"id": area_id, "score10": score,
                 "analysis": tr(f"stub.areas.{area_id}.analysis"),
                 "strengths": tr.list(f"stub.areas.{area_id}.strengths"),
                 "weaknesses": tr.list(f"stub.areas.{area_id}.weaknesses"),
                 "evidence_ref": evidence}
                for area_id, (score, evidence) in _STUB_AREAS.items()
            ],
            "overall": {
                "score10": 5,
                "verdict": tr("stub.overall_verdict"),
                "macro_areas": dict(_STUB_MACRO),
            },
            "action_plan": {
                "immediate_0_30": tr.list("stub.plan.immediate_0_30"),
                "medium_30_90": tr.list("stub.plan.medium_30_90"),
                "long_90_365": tr.list("stub.plan.long_90_365"),
            },
            "opportunities": [
                {"title": tr(f"stub.opportunities.{i}.title"),
                 "benefit": tr(f"stub.opportunities.{i}.benefit"),
                 "priority": priority}
                for i, priority in enumerate(_STUB_OPPORTUNITY_PRIORITIES)
            ],
            "glossary": [
                {"term": term, "definition": tr(f"stub.glossary.{term}")}
                for term in _STUB_GLOSSARY
            ],
            "commercial_proposal": None,
        }


class OpenRouterLlm(BaseLlm):
    """Chiama qualsiasi endpoint OpenAI-compatible (default OpenRouter)."""

    name = "openrouter"

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None):
        # argomenti espliciti > variabili d'ambiente > default
        self.base_url = base_url or env_str("LLM_BASE_URL") or "https://openrouter.ai/api/v1"
        self.api_key = api_key or env_str("LLM_API_KEY")
        self.model = model or env_str("LLM_MODEL") or "deepseek/deepseek-chat-v3.1"
        # consumo cumulato dell'ultima analyze() (tutti i tentativi)
        self.last_usage: dict = {}

    def _add_usage(self, usage: dict) -> None:
        for k in USAGE_KEYS:
            v = usage.get(k)
            if isinstance(v, (int, float)):
                self.last_usage[k] = self.last_usage.get(k, 0) + v

    def analyze(self, raw_report: dict, locale: str = DEFAULT_LOCALE) -> dict:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY non impostata (usa lo stub per test/offline)")
        from app.prompt import build_user_prompt, get_system_prompt
        system = get_system_prompt(locale)
        user = build_user_prompt(raw_report)
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        self.last_usage = {}
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
            self._add_usage(payload.get("usage") or {})
            content = payload["choices"][0]["message"]["content"]
            try:
                data = self._extract_json(content)
                self._validate(data)
                return data
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt == 0:
                    user += ("\n\nNota: la risposta precedente non era un JSON valido "
                             "o non rispettava lo schema. Ricomponi l'intero final_report "
                             "come UN SOLO oggetto JSON completo, senza troncarlo.")
        raise RuntimeError(f"LLM ha prodotto JSON non valido dopo 2 tentativi: {last_err}")

    @staticmethod
    def _extract_json(content: str) -> dict:
        """Trova l'oggetto JSON nella risposta (gestendo preambolo o testo dopo
        la chiusura) e lo decodifica. Un JSON davvero troncato resta un errore."""
        s = content.strip()
        # se non parte con '{', cerca la prima '{'
        start = s.find("{")
        if start > 0:
            s = s[start:]
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # testo dopo il JSON: taglia alla '}' che chiude l'oggetto radice
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
                return json.loads(s[: end + 1])
            raise

    def _validate(self, data: dict):
        """Normalizza scostamenti comuni dell'LLM e valida contro final_report.schema.json."""
        self._normalize(data)
        errs = list(_final_report_validator().iter_errors(data))
        if errs:
            raise RuntimeError(f"LLM ha prodotto report non conforme: {errs[:3]}")

    def _normalize(self, d: dict):
        """Sistema i formati vicini ma non conformi emessi dai modelli:
        - glossary come dict {term: definition} → lista di {term, definition};
        - opportunities come dict {title: benefit} → lista di {title, benefit, priority};
        - action_plan chiavi eventualmente in italiano → forma attesa inglese;
        - voti delle macro-aree come stringhe numeriche ("7") → numeri;
        - aree e macro-aree indicate col nome (in qualsiasi lingua) → id stabili."""
        _ids_from_labels(d)
        ov = d.get("overall")
        if isinstance(ov, dict) and isinstance(ov.get("macro_areas"), dict):
            for k, v in ov["macro_areas"].items():
                if isinstance(v, str):
                    try:
                        ov["macro_areas"][k] = float(v.strip().split("/")[0])
                    except ValueError:
                        pass
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


@lru_cache(maxsize=None)
def _label_index(section: str, ids: tuple) -> dict:
    """{etichetta in minuscolo (ogni locale): id} per aree o macro-aree."""
    index = {}
    for loc in SUPPORTED:
        for item_id in ids:
            index[t(loc, f"{section}.{item_id}").strip().lower()] = item_id
    return index


def _ids_from_labels(d: dict) -> None:
    """Un modello può ancora usare i nomi mostrati invece degli id: rimappa."""
    areas_by_label = _label_index("areas", AREA_IDS)
    for area in d.get("areas") or []:
        if isinstance(area, dict) and area.get("id") not in AREA_IDS:
            found = areas_by_label.get(str(area.get("name") or area.get("id") or "").strip().lower())
            if found:
                area["id"] = found
    ov = d.get("overall")
    if isinstance(ov, dict) and isinstance(ov.get("macro_areas"), dict):
        macro_by_label = _label_index("macro", MACRO_IDS)
        ov["macro_areas"] = {
            (k if k in MACRO_IDS else macro_by_label.get(str(k).strip().lower(), k)): v
            for k, v in ov["macro_areas"].items()
        }


def make_llm(stub: bool = False) -> BaseLlm:
    if stub:
        return StubLlm()
    return OpenRouterLlm()