"""Aggiunge backend/ alla sys.path così l'import 'app.*' funziona nei test
(stessa convenzione di 'uvicorn app.main:app'). Lancia pytest da backend/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))