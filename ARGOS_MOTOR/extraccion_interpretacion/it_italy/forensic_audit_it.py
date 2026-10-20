"""
AUDITORÍA FORENSE Y NLP (ITALIA) - ARGOS MOTOR
Analiza la Relazione della Società di Revisione en los filings italianos.
"""

import os
from pathlib import Path
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
from mod_01_ingestion.src.unified.legacy_exclusions import is_unified_reserved  # U5D

BASE_IT = Path("ARGOS_MOTOR/data/raw/IT_CONSOB")

def classify_italian_audit_opinion(text):
    t = text.lower()
    if "impossibilità di esprimere un giudizio" in t or "dichiarazione di impossibilità" in t:
        return "DICHIARAZIONE_IMPOSSIBILITA"
    if "giudizio negativo" in t:
        return "GIUDIZIO_NEGATIVO"
    if "giudizio con modifiche" in t or "con rilievi" in t:
        return "GIUDIZIO_CON_MODIFICHE"
    if "esprimiamo un giudizio positivo" in t or "fornisce una rappresentazione veritiera e corretta" in t or "senza modifiche" in t:
        return "GIUDIZIO_SENZA_MODIFICHE"
    return "GIUDIZIO_ESTANDAR"

def run_italian_audit():
    print("=== AUDITORÍA FORENSE DE INFORMES ITALIANOS (CONSOB) ===")
    if not BASE_IT.exists(): return
    files = list(BASE_IT.rglob('*.htm')) + list(BASE_IT.rglob('*.xhtml')) + list(BASE_IT.rglob('*.pdf'))
    files = [x for x in files if not is_unified_reserved(x)]  # U5D
    print(f"Total documentos de informe para auditar: {len(files)}")
    for f in files[:5]:
        print(f"  Auditando: {f.name} (Tamaño: {f.stat().st_size / 1024:.1f} KB)")

if __name__ == '__main__':
    run_italian_audit()
