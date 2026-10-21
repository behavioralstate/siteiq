"""Report SiteIQ — sezioni condivise + due impacchettatori.

Design: adattamento dello world DESIGN.md a sfondo CHIARO (carta) per massima
compatibilita' email e leggibilita'. Palette ricalibrata per contrasto AA su
bianco: accenti semantici scuri (verde #1f7a4d, ambra #9c6b16, rosso #a3222a).

Due output dalla STESSA base di sezioni:
  render_report_email()  -> HTML email-safe (CSS inline, table-based, no JS)
  render_report_page()   -> HTML5 autonomo moderno (flex/grid, <style>, no JS)

Tutti i testi fissi vengono dal catalogo (locales/<locale>.json, sezione
"report"); i testi del report (scritti dall'LLM) arrivano già nella lingua del job.
Regola: si traduce con i valori grezzi e si fa escape del risultato.

Niente immagini esterne: solo colori pieni.
"""
from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import urlparse

from app.i18n import DEFAULT_LOCALE, Translator

# ---- palette (AA su #ffffff) ----
INK = "#16181d"
MUTED = "#5a626e"
SUBTLINE = "#e6e8ee"
PAPER = "#ffffff"
PAPER_ALT = "#f6f7f9"
GREEN = "#1f7a4d"
GREEN_BG = "#e8f5ef"
AMBER = "#6a4a0f"
AMBER_BG = "#fbf1e3"
RED = "#a3222a"
RED_BG = "#fdecee"

SCORE_ORDER = ("performance", "accessibility", "security", "seo", "development")
PLAN_COLUMNS = (("immediate_0_30", "report.plan.immediate"),
                ("medium_30_90", "report.plan.medium"),
                ("long_90_365", "report.plan.long"))


def _num(v) -> float:
    """Voto numerico dal report (LLM): 0 se mancante o non numerico."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _score_color(v: float) -> str:
    return GREEN if v >= 7 else AMBER if v >= 5 else RED


def _sev(status: str, tr: Translator) -> tuple[str, str, str]:
    bg, fg = {"ok": (GREEN_BG, GREEN), "warn": (AMBER_BG, AMBER), "error": (RED_BG, RED)}[status]
    return escape(tr(f"severity.{status}")), bg, fg


def _verdict_line(report: dict, tr: Translator) -> tuple[str, str, str]:
    v = report.get("summary", {}).get("verdict", "attention")
    bg, fg = {"ok": (GREEN_BG, GREEN), "critical": (RED_BG, RED)}.get(v, (AMBER_BG, AMBER))
    key = v if v in ("ok", "critical") else "attention"
    return bg, fg, escape(tr(f"report.verdict.{key}"))


def _area_label(area: dict, tr: Translator) -> str:
    """Etichetta di un'area: dal catalogo per id, altrimenti il nome storico."""
    return (area.get("id") and tr.optional(f"areas.{area['id']}")) or area.get("name", "")


def _macro_label(key: str, tr: Translator) -> str:
    return tr.optional(f"macro.{key}") or str(key)


def _no_priority(tr: Translator) -> str:
    return tr("report.no_priority")


def _score_rows(report: dict, tr: Translator) -> str:
    """riga per score: label(grade) barra valore."""
    out = ""
    for key in SCORE_ORDER:
        label = escape(tr(f"categories.{key}"))
        sc = report.get("scores", {}).get(key)
        if not sc:
            continue
        val, grade = sc["value"], sc["grade"]
        color = RED if val < 60 else AMBER if val < 80 else GREEN
        out += (
            '<tr>'
            f'<td style="padding:6px 0;color:{INK};font-size:14px;font-weight:600;width:38%">{label} '
            f'<span style="color:{MUTED};font-size:12px;">({grade})</span></td>'
            f'<td style="width:52%"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td width="{val}%" style="background:{color};height:10px;"></td>'
            f'<td width="{100 - val}%" style="background:{SUBTLINE};height:10px;"></td>'
            '</tr></table></td>'
            f'<td style="width:10%;text-align:right;color:{color};font-weight:800;font-size:15px;">{val}</td>'
            '</tr>'
        )
    return out


def _check_rows(report: dict, tr: Translator) -> str:
    out = ""
    for cat, items in report.get("checks", {}).items():
        out += (f'<tr><td style="padding:9px 0;font-size:13px;font-weight:800;color:{INK};'
                f'border-bottom:1px solid {SUBTLINE}">{escape(tr(f"categories.{cat}"))}</td></tr>')
        for ck in items:
            lab, bg, fg = _sev(ck["status"], tr)
            badge = (f'<span style="background:{bg};color:{fg};font-weight:700;font-size:11px;'
                     f'padding:2px 8px;border-radius:10px;">{lab}</span>')
            out += (
                '<tr><td style="padding:5px;">'
                '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
                f'<td style="width:20%;padding:0 4px;text-align:left;">{badge}</td>'
                f'<td style="color:{INK};font-size:13px;">{escape(ck["label"])}</td>'
                f'<td style="color:{MUTED};font-size:12px;text-align:right;">{escape(ck.get("detail",""))}</td>'
                '</tr></table></td></tr>'
            )
    return out


def _wp_markup(report: dict) -> tuple[str, dict]:
    """Ritorna (html, {core, plugins}) per riuso email(html-table) e pagina(blocchi)."""
    wp = report.get("wordpress_security")
    if not (wp and wp.get("is_wordpress")):
        return "", {}
    core = wp.get("core") or {}
    core_n = len(core.get("vulnerabilities", []))
    plugins = wp.get("plugins", [])
    return "", {"core": core, "core_n": core_n, "plugins": plugins}


def _rec_html(report: dict, tr: Translator) -> str:
    urgent = [r for r in report.get("recommendations", []) if r.get("priority") in ("P0", "P1")][:5]
    out = ""
    for r in urgent:
        bg, fg = {"P0": (RED_BG, RED), "P1": (AMBER_BG, AMBER), "P2": (GREEN_BG, GREEN)} \
            .get(r.get("priority"), (AMBER_BG, AMBER))
        out += (
            '<tr>'
            f'<td style="padding:9px;background:{bg};border-radius:6px;">'
            f'<b style="color:{fg};font-size:13px;">[{escape(str(r.get("priority","")))}] {escape(r.get("title",""))}</b>'
            f'<div style="color:{INK};font-size:13px;margin-top:3px;">{escape(r.get("detail",""))}</div>'
            '</td></tr>'
        )
    return out or f'<tr><td style="color:{MUTED};font-size:13px;">{escape(_no_priority(tr))}</td></tr>'


def _overall_html(report: dict, tr: Translator) -> str:
    ov = report.get("overall")
    if not ov:
        return ""
    macro = ov.get("macro_areas") or {}
    rows = ""
    for k, v in macro.items():
        if not isinstance(v, (int, float)):
            continue
        color = GREEN if v >= 7 else AMBER if v >= 5 else RED
        rows += (f'<tr><td style="color:{INK};font-size:13px;width:60%;padding:3px 0;">{escape(_macro_label(k, tr))}</td>'
                 f'<td style="color:{color};font-weight:800;font-size:13px;text-align:right;">{v:g}/10</td></tr>')
    ov_score = ov.get("score10", "?")
    ov_color = GREEN if (isinstance(ov_score, (int, float)) and ov_score >= 7) else AMBER if (isinstance(ov_score, (int, float)) and ov_score >= 5) else RED
    return (
        '<tr><td style="padding:10px 20px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{PAPER_ALT};border:1px solid {SUBTLINE};border-radius:10px;">'
        f'<tr><td style="padding:10px 14px 4px;"><b style="font-size:15px;color:{INK};">{escape(tr("report.final_verdict"))}</b>'
        f'<span style="float:right;font-size:26px;font-weight:800;color:{ov_color};">{escape(str(ov_score))}/10</span></td></tr>'
        f'<tr><td style="padding:0 14px 6px;color:{MUTED};font-size:13px;">{escape(ov.get("verdict",""))}</td></tr>'
        + rows + '</table></td></tr>'
    )


def _areas_html(report: dict, tr: Translator) -> str:
    areas = report.get("areas") or []
    if not areas:
        return ""
    rows = ""
    for a in areas:
        sc = _num(a.get("score10"))
        color = GREEN if sc >= 7 else AMBER if sc >= 5 else RED
        w = " · ".join(a.get("weaknesses", []) or [])[:70]
        rows += (
            '<tr>'
            f'<td style="padding:6px 4px;color:{INK};font-size:13px;font-weight:600;width:58%">'
            f'{escape(_area_label(a, tr))}</td>'
            f'<td style="width:12%;color:{color};font-weight:800;font-size:14px;">{escape(str(sc))}/10</td>'
            f'<td style="color:{MUTED};font-size:12px;">{escape(w)}</td>'
            '</tr>'
        )
    return (
        '<tr><td style="padding:10px 20px;">'
        f'<b style="font-size:15px;color:{INK};">{escape(tr("report.areas_examined", count=len(areas)))}</b>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin-top:4px;border-top:1px solid {SUBTLINE};">{rows}</table>'
        '</td></tr>'
    )


def _plan_html(report: dict, tr: Translator) -> str:
    plan = report.get("action_plan") or {}
    if not plan:
        return ""
    cols = [(escape(tr(key)), plan.get(field, [])) for field, key in PLAN_COLUMNS]
    head = ""
    body = ""
    for title, items in cols:
        li = "".join(f'<div style="color:{MUTED};font-size:12px;padding:2px 0;">• {escape(i)}</div>'
                     for i in items) or '<div style="color:' + MUTED + ';font-size:12px;">—</div>'
        head += f'<td style="width:33%;font-weight:700;color:{INK};font-size:12px;padding:2px 6px;">{title}</td>'
        body += f'<td style="width:33%;vertical-align:top;padding:6px;">{li}</td>'
    return (
        '<tr><td style="padding:10px 20px;">'
        f'<b style="font-size:15px;color:{INK};">{escape(tr("report.action_plan"))}</b>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin-top:6px;background:{PAPER_ALT};border:1px solid {SUBTLINE};border-radius:10px;">'
        f'<tr>{head}</tr><tr>{body}</tr></table></td></tr>'
    )


def _opp_glossary_html(report: dict, tr: Translator) -> str:
    opp = report.get("opportunities") or []
    glo = report.get("glossary") or []
    if not opp and not glo:
        return ""
    out = ""
    if opp:
        rows = ""
        for o in opp[:5]:
            pc = {"High": RED, "Medium": AMBER, "Strategic": GREEN}.get(o.get("priority"), AMBER)
            rows += (f'<tr><td style="color:{INK};font-size:13px;width:45%;padding:4px;">{escape(o.get("title",""))}</td>'
                     f'<td style="color:{MUTED};font-size:12px;">{escape(o.get("benefit",""))}</td>'
                     f'<td style="color:{pc};font-weight:800;font-size:11px;text-align:right;">{escape(_opp_priority(o, tr))}</td></tr>')
        out += ('<tr><td style="padding:10px 20px;">'
                f'<b style="font-size:15px;color:{INK};">{escape(tr("report.opportunities"))}</b>'
                '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'style="margin-top:4px">{rows}</table></td></tr>')
    if glo:
        rows = "".join(f'<tr><td style="width:84px;vertical-align:top;color:{INK};font-weight:700;font-size:12px;padding:3px 8px;">{escape(g["term"])}</td>'
                       f'<td style="color:{MUTED};font-size:12px;padding:3px 4px;">{escape(g["definition"])}</td></tr>'
                       for g in glo[:10])
        out += ('<tr><td style="padding:10px 20px;">'
                f'<b style="font-size:15px;color:{INK};">{escape(tr("report.glossary"))}</b>'
                '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'style="margin-top:4px;background:{PAPER_ALT};border:1px solid {SUBTLINE};border-radius:10px;">'
                f'{rows}</table></td></tr>')
    return out


def _opp_priority(o: dict, tr: Translator) -> str:
    p = str(o.get("priority", ""))
    return tr.optional(f"report.opportunity_priority.{p}") or p


def _subject(report: dict, tr: Translator) -> str:
    # oggetto email: testo semplice, niente escape HTML (darebbe "&amp;" visibili)
    return tr("report.subject", url=report.get("url", ""))


def _site_domain(url: str) -> str:
    """Ritorna il dominio pulito (senza www), es. relaislacosta.it. Fallback: url."""
    u = urlparse(url or "")
    host = u.netloc or (url or "").split("/")[0] or url
    return host.removeprefix("www.") or host


# =====================================================================
# EMAIL (table-safe)
# =====================================================================
def render_report_email(report: dict, locale: str = DEFAULT_LOCALE) -> tuple[str, str]:
    tr = Translator(locale)
    s = report.get("summary", {})
    vt_bg, vt_fg, vt_line = _verdict_line(report, tr)
    verdict_row = (
        '<tr>'
        f'<td style="background:{vt_bg};border-left:6px solid {vt_line};padding:14px 20px;">'
        f'<b style="color:{vt_fg};font-size:16px;">{vt_line}</b>'
        '<div style="color:' + MUTED + ';font-size:13px;margin-top:4px;">'
        + escape(s.get("most_urgent", "") or _no_priority(tr)) +
        '</div></td></tr>'
    )

    # wp (email: tabella inline)
    _, wpd = _wp_markup(report)
    wp_html = ""
    if wpd:
        core_badge = (f'<span style="background:{RED_BG};color:{RED};padding:2px 8px;'
                      f'border-radius:10px;font-size:11px;">{escape(tr("report.wp.vulns", count=wpd["core_n"]))}</span>'
                      if wpd["core_n"] else "")
        plugin_rows = ""
        for pl in wpd["plugins"]:
            n = len(pl.get("vulnerabilities", []))
            if pl.get("status") == "unavailable":
                plugin_rows += (f'<tr><td style="color:{MUTED};font-size:13px;">{escape(pl["slug"])}</td>'
                                f'<td style="color:{AMBER}">{escape(tr("report.wp.data_unavailable"))}</td></tr>')
                continue
            if pl.get("status") == "unknown":
                # versione non rilevata dal crawler: non è un verdetto di vulnerabilità
                plugin_rows += (f'<tr><td style="color:{MUTED};font-size:13px;">{escape(pl["slug"])}</td>'
                                f'<td style="color:{AMBER}">{escape(tr("report.wp.version_unknown_unverifiable"))}</td></tr>')
                continue
            sbg, sfg, stxt = ((RED_BG, RED, escape(tr("report.wp.vulnerable_cves", count=n))) if n
                              else (GREEN_BG, GREEN, escape(tr("severity.ok"))))
            plugin_rows += (
                '<tr>'
                f'<td style="color:{INK};font-size:13px;">{escape(pl["slug"])} '
                f'<span style="color:{MUTED}">v{escape(pl["version"] or "?")}</span></td>'
                f'<td style="background:{sbg};color:{sfg};font-weight:700;font-size:12px;">'
                f'{stxt}</td></tr>'
            )
        wp_html = (
            '<tr><td style="background:' + PAPER_ALT + ';border:1px solid ' + SUBTLINE + ';padding:12px;">'
            f'<b style="color:{INK};font-size:14px;">{escape(tr("report.wp.title"))}</b>'
            '<table role="presentation" width="100%" cellpadding="4" cellspacing="0">'
            f'<tr><td style="color:{MUTED};font-size:13px;">{escape(tr("report.wp.core_version"))}</td>'
            f'<td style="font-size:13px;">{escape(wpd["core"].get("version","?"))} {core_badge}</td></tr>'
            + plugin_rows + '</table></td></tr>'
        )

    cta = (
        '<tr><td style="text-align:center;padding:16px;">'
        f'<a href="#" style="display:inline-block;background:{GREEN};color:#fff;font-weight:800;'
        f'font-size:15px;text-decoration:none;padding:12px 28px;border-radius:8px;">'
        f"{escape(tr('report.cta'))}</a></td></tr>"
    )

    site_name = escape(_site_domain(report.get("url", "")))
    body = f"""<!doctype html><html lang="{escape(tr('meta.html_lang'))}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
</head><body style="margin:0;padding:0;background:{PAPER_ALT};">
<div style="max-width:620px;margin:0 auto;background:{PAPER};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAPER};">
    <tr><td style="padding:22px 26px;border-bottom:1px solid {SUBTLINE};">
      <table role="presentation"><tr>
        <td><b style="font-size:20px;color:{INK};">SiteIQ</b>
        <div style="font-size:15px;color:{INK};font-weight:800;margin-top:2px;">{site_name}</div></td>
        <td style="text-align:right;color:{MUTED};font-size:12px;">{escape(tr("report.automatic"))}</td>
      </tr></table></td></tr>
    {verdict_row}
    <tr><td style="padding:14px 20px;">
      <b style="font-size:15px;color:{INK};">{escape(tr("report.scores_by_area"))}</b>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px;">{_score_rows(report, tr)}</table>
    </td></tr>
    {wp_html}
    {_areas_html(report, tr)}
    <tr><td style="padding:10px 20px;">
      <b style="font-size:15px;color:{INK};">{escape(tr("report.checks_detail"))}</b>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px;">{_check_rows(report, tr)}</table>
    </td></tr>
    {_overall_html(report, tr)}
    {_plan_html(report, tr)}
    {_opp_glossary_html(report, tr)}
    <tr><td style="padding:10px 20px;">
      <b style="font-size:15px;color:{INK};">{escape(tr("report.fix_first"))}</b>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px;">{_rec_html(report, tr)}</table>
    </td></tr>
    {cta}
    <tr><td style="padding:16px 20px;color:{MUTED};font-size:11px;border-top:1px solid {SUBTLINE};">
      {escape(tr("report.footer", url=report.get("url", "")))}.
      {escape(tr("report.footer_ignore"))}
    </td></tr>
  </table>
</div></body></html>"""
    return _subject(report, tr), body


# =====================================================================
# PAGINA HTML5 autonomo (stessa grafica, flessibile, ~/admin)
# =====================================================================
PAGE_CSS = """
:root{--ink:#16181d;--muted:#5a626e;--line:#e6e8ee;--paper:#fff;--alt:#f6f7f9;
--green:#1f7a4d;--green-bg:#e8f5ef;--amber:#6a4a0f;--amber-bg:#fbf1e3;--red:#a3222a;--red-bg:#fdecee;}
*{box-sizing:border-box}
body{margin:0;background:var(--alt);color:var(--ink);font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,"Helvetica Neue",sans-serif;}
.wrap{max-width:780px;margin:0 auto;background:var(--paper);box-shadow:0 12px 40px rgba(0,0,0,.08);border-radius:0 0 16px 16px;overflow:hidden}
header{display:flex;justify-content:space-between;align-items:center;padding:26px 32px;border-bottom:1px solid var(--line);flex-wrap:wrap;gap:12px}
.brand{font-size:20px;font-weight:800;letter-spacing:-0.02em}
.brand .bolt{color:var(--green)}
header .site{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:700;margin-top:2px}
.tag{color:var(--muted);font-size:12px}
.title-row{padding:22px 32px 0}
.title-site{font-size:28px;font-weight:800;letter-spacing:-0.03em;margin:0}
.title-meta{color:var(--muted);font-size:13px;margin:6px 0 0}
.verdict{margin:16px 32px;padding:18px 22px;border-left:6px solid currentColor;border-radius:10px}
.verdict.good{background:var(--green-bg);color:var(--green)}
.verdict.warn{background:var(--amber-bg);color:var(--amber)}
.verdict.crit{background:var(--red-bg);color:var(--red)}
.verdict b{font-size:17px}
.verdict p{color:var(--ink);font-size:14px;margin:6px 0 0;max-width:70ch}
h2{font-size:16px;margin:30px 32px 12px;padding-top:14px;border-top:1px solid var(--line)}
h2:first-of-type{border-top:0}
.scores{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:0 32px}
.score-card{background:var(--alt);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.score-card .n{font-size:28px;font-weight:800;letter-spacing:-0.03em;display:flex;align-items:baseline;gap:8px}
.score-card .n .lbl{font-size:13px;color:var(--ink);font-weight:600}
.score-card .g{color:var(--muted);font-size:12px}
.track{height:10px;border-radius:6px;background:var(--line);margin-top:10px;overflow:hidden}
.track i{display:block;height:100%;border-radius:6px}.track.g{background:var(--green)}.track.a{background:var(--amber)}.track.r{background:var(--red)}
.wp{background:var(--alt);border:1px solid var(--line);border-radius:12px;padding:14px;margin:0 32px}
.wp h3{font-size:14px;margin:0 0 10px}
.wp .core{color:var(--muted);font-size:13px}
.plug{display:flex;justify-content:space-between;gap:8px;font-size:13px;padding:3px 0}
.plug .st{font-weight:700}
.st-vuln{color:var(--red)}.st-ok{color:var(--green)}.st-na{color:var(--amber)}
.checks{margin-top:6px;padding:0 32px}
.chk{display:flex;align-items:baseline;gap:10px;padding:6px 0;font-size:13px}
.chk .b{flex:none;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700}
.b-ok{background:var(--green-bg);color:var(--green)}
.b-warn{background:var(--amber-bg);color:var(--amber)}
.b-error{background:var(--red-bg);color:var(--red)}
.chk .l{flex:1}.chk .d{color:var(--muted);font-size:12px}
.recs{margin-top:6px;padding:0 32px}
.rec{background:var(--alt);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:8px}
.rec .t{font-weight:700;font-size:13px}.rec-ok{color:var(--green)}.rec-warn{color:var(--amber)}.rec-error{color:var(--red)}
.rec p{color:var(--ink);font-size:13px;margin:4px 0 0}
.cta{display:block;text-align:center;margin:26px 0 8px;padding:0 32px}
.cta a{display:inline-block;background:var(--green);color:#fff;font-weight:800;font-size:15px;text-decoration:none;padding:12px 30px;border-radius:8px}
footer{padding:16px 22px;color:var(--muted);font-size:11px;border-top:1px solid var(--line)}
.url{color:var(--muted);word-break:break-all}
/* 17 aree + overall + piano + opportunità */
.areas{margin-top:6px}
.area{display:flex;align-items:baseline;gap:10px;padding:7px 2px;border-bottom:1px solid var(--line);font-size:13px}
.area .nm{flex:1;font-weight:600}
.area .sc{font-weight:800;width:54px}
.area .ws{color:var(--muted);font-size:12px;flex:1}
.overall{background:var(--alt);border:1px solid var(--line);border-radius:12px;padding:16px;margin:0 32px}
.overall .big{font-size:32px;font-weight:800;letter-spacing:-0.03em}
.macro{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:10px}
.macro span{font-size:13px}.macro b{font-weight:800}
.plan{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:6px;padding:0 32px}
.plan .pd{background:var(--alt);border:1px solid var(--line);border-radius:12px;padding:14px}
.plan h4{font-size:12px;margin:0 0 8px;color:var(--ink)}
.plan ul{margin:0;padding-left:16px;color:var(--muted);font-size:12px;line-height:1.5}
.opp{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:8px;margin-right:32px}
.opp .t{font-weight:700;font-size:13px}
.opp .b{color:var(--muted);font-size:12px}
.opp .p{font-size:10px;font-weight:800;padding:2px 8px;border-radius:10px}
.p-high{background:var(--red-bg);color:var(--red)}.p-med{background:var(--amber-bg);color:var(--amber)}.p-str{background:var(--green-bg);color:var(--green)}
.gloss{background:var(--alt);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 32px}
.gloss div{font-size:13px;padding:4px 0}.gloss b{color:var(--ink)}.gloss span{color:var(--muted)}
@media(max-width:640px){.scores{grid-template-columns:1fr}.plan{grid-template-columns:1fr}}
"""


def render_report_page(report: dict, locale: str = DEFAULT_LOCALE) -> str:
    """Pagina HTML5 autonoma con la stessa grafica (per /admin valutazione)."""
    tr = Translator(locale)
    s = report.get("summary", {})
    vb, vf, vline = _verdict_line(report, tr)
    vcls = {"ok": "good", "critical": "crit"}.get(report.get("summary", {}).get("verdict", "attention"), "warn")

    score_cards = ""
    for key in SCORE_ORDER:
        label = escape(tr(f"categories.{key}"))
        sc = report.get("scores", {}).get(key)
        if not sc:
            continue
        val, grade = sc["value"], sc["grade"]
        tcls = "g" if val >= 80 else "a" if val >= 60 else "r"
        score_cards += (
            f'<div class="score-card"><div class="n" style="color:{GREEN if val>=80 else AMBER if val>=60 else RED}">{val}'
            f' <span class="g">{escape(str(grade))} · {label}</span></div>'
            f'<div class="track {tcls}"><i style="width:{val}%"></i></div></div>'
        )

    wp_html = ""
    _, wpd = _wp_markup(report)
    if wpd:
        core_badge = (f'<span class="st st-vuln">{escape(tr("report.wp.vulns", count=wpd["core_n"]))}</span>'
                      if wpd["core_n"] else f'<span class="st st-ok">{escape(tr("report.wp.ok"))}</span>')
        plug = ""
        for pl in wpd["plugins"]:
            n = len(pl.get("vulnerabilities", []))
            if pl.get("status") == "unavailable":
                plug += (f'<div class="plug"><span>{escape(pl["slug"])}</span><span class="st st-na">{escape(tr("report.wp.data_unavailable"))}</span></div>')
                continue
            if pl.get("status") == "unknown":
                plug += (f'<div class="plug"><span>{escape(pl["slug"])}</span><span class="st st-na">{escape(tr("report.wp.version_unknown"))}</span></div>')
                continue
            scls, stxt = (("st-vuln", escape(tr("report.wp.vulnerable_count", count=n))) if n
                          else ("st-ok", escape(tr("severity.ok"))))
            plug += (f'<div class="plug"><span>{escape(pl["slug"])} <span style="color:var(--muted)">'
                     f'v{escape(pl["version"] or "?")}</span></span><span class="st {scls}">{stxt}</span></div>')
        wp_html = (
            f'<h2>{escape(tr("report.wp.title"))}</h2><div class="wp"><h3>WordPress</h3>'
            f'<div class="core">{escape(tr("report.wp.core_version_value", version=wpd["core"].get("version", "?")))} {core_badge}</div>'
            f'<div style="margin-top:8px">{plug}</div></div>'
        )

    checks_html = ""
    seen_cat = False
    for cat, items in report.get("checks", {}).items():
        if not items:
            continue
        seen_cat = True
        checks_html += (f'<h3 style="font-size:13px;color:var(--ink);border-bottom:1px solid var(--line);'
                        f'padding-bottom:2px;margin:14px 0 4px">{escape(tr(f"categories.{cat}"))}</h3>')
        for ck in items:
            checks_html += (
                '<div class="chk">'
                f'<span class="b b-{ck["status"]}">{_sev(ck["status"], tr)[0]}</span>'
                f'<span class="l">{escape(ck["label"])}</span>'
                f'<span class="d">{escape(ck.get("detail",""))}</span>'
                '</div>'
            )
    if not seen_cat:
        checks_html = f'<div class="checks"><p style="color:var(--muted)">{escape(tr("report.no_details"))}</p></div>'

    urgent = [r for r in report.get("recommendations", []) if r.get("priority") in ("P0", "P1")][:5]
    rec_html = ""
    for r in urgent:
        rc = {"P0": "rec-error", "P1": "rec-warn", "P2": "rec-ok"}.get(r.get("priority"), "rec-warn")
        rec_html += (f'<div class="rec"><div class="t {rc}">[{escape(str(r.get("priority","")))}] {escape(r.get("title",""))}</div>'
                     f'<p>{escape(r.get("detail",""))}</p></div>')
    if not rec_html:
        rec_html = f'<div class="rec" style="border:none"><p style="color:var(--muted)">{escape(_no_priority(tr))}</p></div>'

    url = escape(report.get("url", ""))

    # --- nuove sezioni (17 aree / overall / piano / opportunità / glossario) ---
    areas_html = ""
    for a in report.get("areas") or []:
        sc = _num(a.get("score10"))
        color = GREEN if sc >= 7 else AMBER if sc >= 5 else RED
        strengths = " · ".join(a.get("strengths", []) or [])
        weak = " · ".join(a.get("weaknesses", []) or [])
        areas_html += (
            f'<div class="area"><span class="sc" style="color:{color}">{escape(str(sc))}/10</span>'
            f'<div><b>{escape(_area_label(a, tr))}</b>'
            f'<div class="ws" style="font-size:12px;margin-top:2px">'
            f'#{escape(a.get("analysis",""))}</div>'
            f'<div class="ws" style="margin-top:2px"><b style="color:var(--green)">+ {escape(strengths)}</b></div>'
            f'<div class="ws"><b style="color:var(--red)">− {escape(weak)}</b></div>'
            f'</div></div>'
        )
    if not areas_html:
        areas_html = f'<p style="color:var(--muted);font-size:13px">{escape(tr("report.no_areas"))}</p>'

    ov = report.get("overall") or {}
    macro_html = ""
    for k, v in (ov.get("macro_areas") or {}).items():
        if not isinstance(v, (int, float)):
            continue
        color = GREEN if v >= 7 else AMBER if v >= 5 else RED
        macro_html += f'<span><b style="color:{color}">{v:g}/10</b> {escape(_macro_label(k, tr))}</span>'
    overall_html = (
        f'<h2>{escape(tr("report.final_verdict"))}</h2><div class="overall"><div style="display:flex;align-items:baseline;gap:10px">'
        f'<span class="big" style="color:{_score_color(_num(ov.get("score10")))}">{escape(str(ov.get("score10","?")))}/10</span>'
        f'<b style="font-size:15px">{escape(ov.get("verdict",""))}</b></div>'
        f'<div class="macro">{macro_html}</div></div>'
    ) if ov else ""

    plan = report.get("action_plan") or {}
    plan_html = ""
    if plan:
        pcols = ""
        for field, key in PLAN_COLUMNS:
            li = "".join(f"<li>{escape(i)}</li>" for i in plan.get(field, [])) or "<li>—</li>"
            pcols += f'<div class="pd"><h4>{escape(tr(key))}</h4><ul>{li}</ul></div>'
        plan_html = f'<h2>{escape(tr("report.action_plan"))}</h2><div class="plan">{pcols}</div>'

    opp_html = ""
    if report.get("opportunities"):
        oo = ""
        for o in report["opportunities"][:5]:
            pc = {"High": "p-high", "Medium": "p-med", "Strategic": "p-str"}.get(o.get("priority"), "p-med")
            oo += (f'<div class="opp"><div class="t">{escape(o.get("title",""))} '
                   f'<span class="p {pc}">{escape(_opp_priority(o, tr))}</span></div>'
                   f'<div class="b">{escape(o.get("benefit",""))}</div></div>')
        opp_html = f'<h2>{escape(tr("report.opportunities"))}</h2>{oo}'

    glo_html = ""
    if report.get("glossary"):
        gg = "".join(f'<div><b>{escape(g.get("term",""))}</b> · <span>{escape(g.get("definition",""))}</span></div>'
                     for g in report["glossary"][:10])
        glo_html = f'<h2>{escape(tr("report.glossary"))}</h2><div class="gloss">{gg}</div>'

    page_extras = (
        f'<h2>{escape(tr("report.areas_examined", count=len(report.get("areas") or [])))}</h2>'
        f'<div class="areas">{areas_html}</div>\n'
        + overall_html + "\n" + plan_html + "\n" + opp_html + "\n" + glo_html
    )

    domain = _site_domain(url)

    return f"""<!doctype html><html lang="{escape(tr('meta.html_lang'))}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>{escape(tr("report.page_title", domain=domain))}</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<header>
  <div>
    <div class="brand">SiteIQ<span class="bolt">.</span></div>
    <div class="site">{escape(tr("report.page_subtitle"))}</div>
  </div>
  <span class="tag">{escape(tr.date(date.today()))}</span>
</header>

<div class="title-row">
  <h1 class="title-site">{escape(domain)}</h1>
  <p class="title-meta">{escape(tr("report.site_analysis"))} · <span class="url">{url}</span></p>
</div>

<div class="verdict {vcls}"><b>{vline}</b>
<p>{escape(s.get("most_urgent","") or _no_priority(tr))}</p></div>

<h2>{escape(tr("report.scores_by_area"))}</h2>
<div class="scores">{score_cards}</div>

{wp_html}

<h2>{escape(tr("report.checks_detail"))}</h2>
<div class="checks">{checks_html}</div>

<h2>{escape(tr("report.fix_first"))}</h2>
<div class="recs">{rec_html}</div>

{page_extras}

<div class="cta"><a href="#">{escape(tr("report.cta"))}</a></div>

<footer>{escape(tr("report.footer_page"))} · <span class="url">{url}</span></footer>
</div></body></html>"""