"""U1 — Capa de dominio del núcleo unificado.

Invariantes de dependencia (ver ADR-001 y 05_PACKAGE_DEPENDENCY_RULES.md):
- ``domain`` solo importa biblioteca estándar y otros módulos de ``domain``.
- Sin I/O al importar; sin red, DuckDB, Arelle ni código de ``descarga/``.
"""
