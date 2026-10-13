"""
AUDITORÍA FORENSE Y NLP (PAÍSES BAJOS) - ARGOS MOTOR
Analiza la Controleverklaring van de onafhankelijke accountant en los filings neerlandeses.
"""

import os
from pathlib import Path
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
from mod_01_ingestion.src.unified.legacy_exclusions import is_unified_reserved  # U5D

BASE_NL = Path("ARGOS_MOTOR/data/raw/NL_AFM")

def classify_dutch_audit_opinion(text):
    t = text.lower()
    if "oordeelsonthouding" in t:
        return "OORDEELSONTHOUDING"
    if "afkeurende controleverklaring" in t or "afkeurend oordeel" in t:
        return "AFKEURENDE_CONTROLEVERKLARING"
    if "met beperking" in t:
        return "CONTROLEVERKLARING_MET_BEPERKING"
    if "goedkeurend oordeel" in t or "goedkeurende controleverklaring" in t or "getrouw beeld" in t:
        return "GOEDKEURENDE_CONTROLEVERKLARING"
    return "GOEDKEUREND_ESTANDAR"

def run_dutch_audit():
    print("=== AUDITORÍA FORENSE DE INFORMES NEERLANDESES (AFM / NBA) ===")
    if not BASE_NL.exists(): return
    files = list(BASE_NL.rglob('*.htm')) + list(BASE_NL.rglob('*.xhtml')) + list(BASE_NL.rglob('*.pdf'))
    files = [x for x in files if not is_unified_reserved(x)]  # U5D
    print(f"Total documentos de informe para auditar: {len(files)}")
    for f in files[:5]:
        print(f"  Auditando: {f.name} (Tamaño: {f.stat().st_size / 1024:.1f} KB)")

if __name__ == '__main__':
    run_dutch_audit()
