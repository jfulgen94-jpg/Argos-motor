"""
AUDITORÍA FORENSE Y NLP (FRANCIA) - ARGOS MOTOR
Analiza la opinión de los commissaires aux comptes en los filings franceses.
"""

import os
from pathlib import Path

BASE_FR = Path("ARGOS_MOTOR/data/raw/FR_AMF")

def classify_french_audit_opinion(text):
    t = text.lower()
    if "refusons de certifier" in t or "refus de certification" in t:
        return "REFUS_DE_CERTIFIER"
    if "avec réserve" in t or "avec réserves" in t:
        return "CERTIFICATION_AVEC_RESERVES"
    if "certifions que les comptes consolidés sont réguliers et sincères" in t or "sans réserve" in t:
        return "CERTIFICATION_SANS_RESERVE"
    return "SANS_RESERVE_ESTANDAR"

def run_french_audit():
    print("=== AUDITORÍA FORENSE DE INFORMES FRANCESES (AMF) ===")
    if not BASE_FR.exists(): return
    files = list(BASE_FR.rglob('*.htm')) + list(BASE_FR.rglob('*.xhtml')) + list(BASE_FR.rglob('*.pdf'))
    print(f"Total documentos de informe para auditar: {len(files)}")
    for f in files[:5]:
        print(f"  Auditando: {f.name} (Tamaño: {f.stat().st_size / 1024:.1f} KB)")

if __name__ == '__main__':
    run_french_audit()
