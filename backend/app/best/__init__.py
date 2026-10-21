"""Superficie BEST (Behavioral State Protocol) di SiteIQ.

Strato sottile davanti alla pipeline esistente (jobs.py): discovery
(/.well-known/best), comando AnalyzeSite, eventi (log + SSE) e query.
Pubblica e senza persistenza in questo primo giro: analisi solo deterministiche
(nessun costo LLM), tutto in memoria per circa un'ora.
Spec: https://behavioralstate.io/specs
"""
