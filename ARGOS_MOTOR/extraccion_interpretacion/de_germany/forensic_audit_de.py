"""
AUDITORÍA FORENSE Y NLP (ALEMANIA) - ARGOS MOTOR
Analiza el Bestätigungsvermerk del Wirtschaftsprüfer en los informes anuales alemanes.
"""

import os
from pathlib import Path

BASE_DE = Path("ARGOS_MOTOR/data/raw/DE_BAFIN")

def classify_german_audit_opinion(text):
    t = text.lower()
    if "versagen wir den bestätigungsvermerk" in t:
        return "VERSAGUNGSVERMERK"
    if "mit einschränkungen" in t or "eingeschränkter bestätigungsvermerk" in t:
        return "EINGESCHRAENKTER_BESTAETIGUNGSVERMERK"
    if "erteilen wir den uneingeschränkten bestätigungsvermerk" in t or "uneingeschränkter" in t:
        return "UNEINGESCHRAENKTER_BESTAETIGUNGSVERMERK"
    return "BESTAETIGUNGSVERMERK_ESTANDAR"

def run_german_audit():
    print("=== AUDITORÍA FORENSE DE INFORMES ALEMANES (BAFIN / HGB) ===")
    if not BASE_DE.exists(): return
    files = list(BASE_DE.rglob('*.htm')) + list(BASE_DE.rglob('*.xhtml')) + list(BASE_DE.rglob('*.pdf'))
    print(f"Total documentos de informe para auditar: {len(files)}")
    for f in files[:5]:
        print(f"  Auditando: {f.name} (Tamaño: {f.stat().st_size / 1024:.1f} KB)")

if __name__ == '__main__':
    run_german_audit()
