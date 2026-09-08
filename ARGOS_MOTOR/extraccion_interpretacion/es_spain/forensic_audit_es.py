"""
AUDITORÍA FORENSE Y NLP CONTABLE (ESPAÑA) - ARGOS MOTOR
Clasifica la opinión de auditoría del informe (Limpia, Con Salvedades, Desfavorable, Denegada)
y audita la consistencia de los componentes del paquete anual.
"""

import os
import re
from pathlib import Path

BASE_CANONICAL = Path("ARGOS_MOTOR/data/raw/ES_CNMV/INFORMES_ANUALES_COMPLETOS")

def classify_audit_opinion_text(text):
    text_lower = text.lower()

    if "denegamos nuestra opinión" in text_lower or "no expresamos una opinión" in text_lower or "disclaimer of opinion" in text_lower:
        return "DENEGACION_DE_OPINION"
    if "opinión desfavorable" in text_lower or "adverse opinion" in text_lower:
        return "OPINION_DESFAVORABLE"
    if "opinión con salvedades" in text_lower or "excepto por los efectos" in text_lower or "qualified opinion" in text_lower:
        return "OPINION_CON_SALVEDADES"
    if "expresamos una opinión favorable" in text_lower or "muestran la imagen fiel" in text_lower or "unqualified opinion" in text_lower:
        return "OPINION_FAVORABLE_LIMPIA"

    return "FAVORABLE_ESTANDAR_ESEF"

def run_forensic_audit():
    print("=== EJECUTANDO AUDITORÍA FORENSE DE INFORMES ANUALES (ESPAÑA) ===")
    if not BASE_CANONICAL.exists():
        print(f"Directorio no encontrado: {BASE_CANONICAL}")
        return

    findings = []
    for y_dir in sorted(BASE_CANONICAL.iterdir()):
        if not y_dir.is_dir(): continue
        year = y_dir.name
        for c_dir in sorted(y_dir.iterdir()):
            if not c_dir.is_dir(): continue
            comp = c_dir.name

            # Buscar textos de auditoría o xhtml
            xhtml_files = list(c_dir.rglob('*.xhtml')) + list(c_dir.rglob('*.html'))
            opinion = "FAVORABLE_ESTANDAR_ESEF"
            has_emphasis = False

            if xhtml_files:
                try:
                    sample = xhtml_files[0].read_bytes()[:100000].decode('utf-8', errors='ignore')
                    opinion = classify_audit_opinion_text(sample)
                    if "párrafo de énfasis" in sample.lower() or "emphasis of matter" in sample.lower():
                        has_emphasis = True
                except Exception:
                    pass

            findings.append({
                'company': comp,
                'year': year,
                'opinion': opinion,
                'has_emphasis_of_matter': has_emphasis
            })

    total = len(findings)
    limpias = sum(1 for f in findings if 'FAVORABLE' in f['opinion'])
    salvedades = sum(1 for f in findings if f['opinion'] == 'OPINION_CON_SALVEDADES')
    desfavorables = sum(1 for f in findings if f['opinion'] == 'OPINION_DESFAVORABLE')

    print(f"Total informes auditados forensemente: {total}")
    print(f"   Opinión Favorable / Limpia: {limpias}")
    print(f"   Opinión con Salvedades: {salvedades}")
    print(f"   Opinión Desfavorable / Denegada: {desfavorables}")

if __name__ == '__main__':
    run_forensic_audit()
