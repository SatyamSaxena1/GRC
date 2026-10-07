"""Collectors: the server-side half of the connector contract (app/routers/connectors.py).

Each collector reads an external system and returns {"attributes": {...}} — facts only.
It never writes to the system it reads, and it never decides a verdict: the content packs
and app/evaluate.py do that, exactly as for an uploaded document (ADR-004, ADR-020).
"""
