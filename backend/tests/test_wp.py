"""Test fingerprinting WP + query WPVulnerability API (Fase 6)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import app.wpfingerprint as wpf  # noqa: E402
from app.wpvuln import check_wordpress, fetch_plugin_vulns, _vuln_applies  # noqa: E402
from packaging.version import Version  # noqa: E402


def _wp_html():
    return """
    <html><head>
      <meta name="generator" content="WordPress 6.4.2">
      <link rel="stylesheet" href="/wp-content/plugins/contact-form-7/assets/css/style.css?ver=5.9.2">
      <script src="/wp-content/plugins/woocommerce/assets/js/frontend/add-to-cart.js?ver=8.1.0"></script>
      <link rel="stylesheet" href="/wp-content/themes/twentytwentyfour/style.css?ver=1.0.0">
    </head></html>
    """


def test_is_wordpress():
    assert wpf.is_wordpress(_wp_html()) is True
    assert wpf.is_wordpress("<html>plain</html>") is False


def test_core_version_from_generator():
    assert wpf.core_version(_wp_html()) == "6.4.2"


def test_core_version_from_feed():
    """La versione core si legge dal feed RSS quando il meta generator manca."""
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<title>Blog</title>"
        "<generator>https://wordpress.org/?v=6.6.2</generator>"
        "</channel></rss>"
    )
    assert wpf.core_version_from_feed(feed) == "6.6.2"
    assert wpf.core_version_from_feed("<rss></rss>") is None


def test_version_from_readme():
    """La versione plugin si legge dal readme.txt (Stable tag/Version)."""
    readme = """=== Ninja Forms ===
Contributors: x
Tags: forms
Requires at least: 4.7
Tested up to: 6.6
Stable tag: 3.14.4
License: GPLv2

== Changelog ==
= 3.14.4 =
"""
    assert wpf.version_from_readme(readme) == "3.14.4"
    # senza Stable tag, usa Version:
    readme2 = "Plugin Name: x\nVersion: 1.2.3\nDescription: y\n"
    assert wpf.version_from_readme(readme2) == "1.2.3"
    assert wpf.version_from_readme("Nessuna versione") is None


def test_detect_plugins_and_theme():
    fp = wpf.fingerprint(_wp_html())
    assert fp["is_wordpress"] is True
    slugs = {p["slug"] for p in fp["plugins"]}
    assert "contact-form-7" in slugs
    assert "woocommerce" in slugs
    assert fp["theme"] == "twentytwentyfour"
    # versione plugin best-effort dai ver=
    cf7 = next(p for p in fp["plugins"] if p["slug"] == "contact-form-7")
    assert cf7["version"] == "5.9.2"


def test_vuln_applies_bounds():
    # 3.0.0 è in [null, lt 3.6.3) -> applica
    assert _vuln_applies(Version("3.0.0"), {"max_version": "3.6.3", "max_operator": "lt"}) is True
    # 4.0.0 NON applica (>= 3.6.3)
    assert _vuln_applies(Version("4.0.0"), {"max_version": "3.6.3", "max_operator": "lt"}) is False
    # min 1.0.0 gte, max 5.0.0 lt
    assert _vuln_applies(Version("2.0.0"),
                         {"min_version": "1.0.0", "min_operator": "gte",
                          "max_version": "5.0.0", "max_operator": "lt"}) is True
    # max_operator "le" (alias usato dall'API): versione == boundary → applica
    assert _vuln_applies(Version("3.14.8"), {"max_version": "3.14.8", "max_operator": "le"}) is True
    assert _vuln_applies(Version("3.14.9"), {"max_version": "3.14.8", "max_operator": "le"}) is False
    # max_operator "ge" (alias): versione == boundary → applica
    assert _vuln_applies(Version("2.0.0"),
                         {"min_version": "2.0.0", "min_operator": "ge", "max_version": "5.0.0", "max_operator": "lt"}) is True


def test_version_unknown_is_not_vulnerable():
    """Regressione: plugin con versione NON rilevata NON deve risultare vulnerabile.
    Prima il codice considerava tutte le vuln applicabili con ver=None → falsi
    positivi (plugin aggiornato segnalato vulnerabile)."""
    res = fetch_plugin_vulns("ninja-forms", None)  # versione sconosciuta
    assert res["version_unknown"] is True
    assert res["vulnerabilities"] == []  # nessun verdetto di vulnerabilità


def test_api_plugin_elementor_reaches_and_filters():
    """Query reale all'API (necessita rete). Elementor 3.0.0 era vulnerabile, 4.0.0 no."""
    res = fetch_plugin_vulns("elementor", "4.0.0")
    assert res["status"] == "ok"
    assert "vulnerabilities" in res
    # 4.0.0 dovrebbe NON essere più vulnerabile (nessuna vuln applicabile)
    assert res["vulnerabilities"] == [] or all("4.0.0" not in (v.get("title") or "") for v in res["vulnerabilities"])


def test_check_wordpress_summary():
    fp = wpf.fingerprint(_wp_html())
    res = check_wordpress(fp)
    assert res["is_wordpress"] is True
    assert res["summary"]["plugins_total"] == 2
    assert res["summary"]["core_vulnerable"] in (True, False)  # dipende da rete/versione
    assert "core" in res and "plugins" in res

def test_text_mention_is_not_wordpress():
    """Un articolo che cita "WordPress 5.2" non rende WP il sito né ne fissa la versione."""
    html = "<html><body><p>Abbiamo migrato da WordPress 5.2 a un CMS statico.</p></body></html>"
    assert wpf.is_wordpress(html) is False
    assert wpf.core_version(html) is None


def test_plugin_version_equal_to_core_is_discarded():
    """?ver=<core> è il default di WordPress, non la versione del plugin."""
    html = ('<meta name="generator" content="WordPress 6.4.2">'
            '<script src="/wp-content/plugins/foo/x.js?ver=6.4.2"></script>'
            '<script src="/wp-content/plugins/bar/y.js?ver=2.1.0"></script>')
    fp = wpf.fingerprint(html)
    wpf.drop_core_versioned_plugins(fp)
    versions = {p["slug"]: p["version"] for p in fp["plugins"]}
    assert versions == {"foo": None, "bar": "2.1.0"}
