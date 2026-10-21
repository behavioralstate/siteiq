/* SiteIQ — localizzazione del frontend.

   Catalogo condiviso col backend: /locales/<locale>.json (locales/ nel repo).
   Scelta del locale: ?lang= nell'URL (memorizzato) > scelta salvata >
   lingue del browser > it-IT.

   Nell'HTML:
     data-i18n="chiave"            -> textContent
     data-i18n-html="chiave"       -> innerHTML (solo testi del nostro catalogo)
     data-i18n-attr="attr:chiave;attr2:chiave2"
     data-set-locale="en-GB"       -> pulsante del selettore lingua
   Il testo italiano resta scritto nell'HTML: senza JS la pagina è leggibile.

   Nel JS: await I18N.ready; I18N.t("chiave", {count: 2}); I18N.headers({...}).
*/
"use strict";

(function () {
  const SUPPORTED = ["it-IT", "en-GB"];
  const DEFAULT = "it-IT";
  const STORE_KEY = "siteiq_locale";

  function match(tag) {
    if (!tag) return null;
    const t = String(tag).replace("_", "-").toLowerCase();
    const exact = SUPPORTED.find((l) => l.toLowerCase() === t);
    if (exact) return exact;
    const lang = t.split("-")[0];
    return SUPPORTED.find((l) => l.split("-")[0].toLowerCase() === lang) || null;
  }

  function readStored() {
    try { return localStorage.getItem(STORE_KEY); } catch { return null; }
  }
  function store(locale) {
    try { localStorage.setItem(STORE_KEY, locale); } catch { /* storage non disponibile */ }
  }

  function pick() {
    const fromUrl = match(new URLSearchParams(location.search).get("lang"));
    if (fromUrl) { store(fromUrl); return fromUrl; }
    const saved = match(readStored());
    if (saved) return saved;
    for (const tag of (navigator.languages || [navigator.language])) {
      const m = match(tag);
      if (m) return m;
    }
    return DEFAULT;
  }

  function flatten(node, prefix, out) {
    for (const [k, v] of Object.entries(node)) {
      const key = prefix + k;
      const isPlural = v && typeof v === "object" && !Array.isArray(v) && "other" in v &&
        Object.keys(v).every((f) => ["zero", "one", "two", "few", "many", "other"].includes(f));
      if (v && typeof v === "object" && !Array.isArray(v) && !isPlural) flatten(v, key + ".", out);
      else out[key] = v;
    }
    return out;
  }

  const locale = pick();
  let messages = {};
  const plurals = new Intl.PluralRules(locale);

  function t(key, params = {}) {
    let v = messages[key];
    if (v == null) return key;
    if (typeof v === "object" && !Array.isArray(v)) v = v[plurals.select(Number(params.count))] ?? v.other;
    if (typeof v !== "string") return key;
    return v.replace(/\{(\w+)\}/g, (m, name) => (name in params ? String(params[name]) : m));
  }

  /** Come t(), ma null se la chiave non c'è (etichette di valori facoltativi). */
  function optional(key, params) {
    return key in messages ? t(key, params) : null;
  }

  function apply(root = document) {
    document.documentElement.lang = t("meta.html_lang");
    root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    root.querySelectorAll("[data-i18n-attr]").forEach((el) => {
      for (const pair of el.dataset.i18nAttr.split(";")) {
        const [attr, key] = pair.split(":").map((s) => s.trim());
        if (attr && key) el.setAttribute(attr, t(key));
      }
    });
    root.querySelectorAll("[data-set-locale]").forEach((el) => {
      const active = el.dataset.setLocale === locale;
      el.setAttribute("aria-pressed", String(active));
      el.classList.toggle("is-active", active);
    });
  }

  function setLocale(next) {
    const m = match(next);
    if (!m || m === locale) return;
    store(m);
    const url = new URL(location.href);
    url.searchParams.delete("lang");
    location.replace(url.toString());
  }

  const ready = fetch(`/locales/${locale}.json`)
    .then((r) => (r.ok ? r.json() : {}))
    .then((json) => { messages = flatten(json, "", {}); apply(); return locale; })
    .catch(() => locale);

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-set-locale]");
    if (btn) { e.preventDefault(); setLocale(btn.dataset.setLocale); }
  });

  window.I18N = {
    SUPPORTED,
    locale,
    ready,
    t,
    optional,
    apply,
    setLocale,
    /** Header per fetch: la risposta del server arriva nella stessa lingua. */
    headers(extra = {}) { return { ...extra, "Accept-Language": locale }; },
    number(value, options) { return new Intl.NumberFormat(locale, options).format(value); },
    dateTime(value) {
      return new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
    },
  };
})();
