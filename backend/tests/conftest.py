"""Configurazione comune dei test.

- Aggiunge backend/ alla sys.path così l'import 'app.*' funziona (stessa
  convenzione di 'uvicorn app.main:app'). Lancia pytest da backend/.
- Isola l'ambiente PRIMA che qualunque modulo app venga importato: DB e report
  in una cartella temporanea, nessuna email di notifica, token di test, e host
  privati ammessi (le fixture HTTP girano su 127.0.0.1).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = Path(tempfile.mkdtemp(prefix="siteiq-tests-"))
os.environ["USAGE_DB"] = str(_TMP / "usage.db")
os.environ["REPORTS_DIR"] = str(_TMP / "reports")
os.environ["AUTH_CLIENTS"] = "fabio=test-token-fabio"
os.environ["SITEIQ_ALLOW_PRIVATE_TARGETS"] = "1"
os.environ["REPORT_NOTIFY_EMAIL"] = ""
# vuote ma presenti: load_env usa setdefault, quindi un backend/.env locale
# non può reintrodurre SMTP o chiavi reali durante i test
for _k in ("SMTP_HOST", "LLM_API_KEY", "AUTH_TOKEN"):
    os.environ[_k] = ""

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """I limiti per IP sono globali di processo: azzerali tra un test e l'altro."""
    from app.best import router as best_router
    from app.best import service as best_service
    from app.routers import lead
    for limiter in (lead.lead_ip_limiter, lead.lead_email_limiter, lead.scan_ip_limiter,
                    best_router.command_limiter):
        limiter.reset()
    best_service.idempotency.clear()
    yield
