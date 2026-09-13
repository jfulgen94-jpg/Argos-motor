"""
AUDITORÍA DE DESCARGAS (FRANCIA) - ARGOS MOTOR
Inspecciona y valida la integridad de los paquetes descargados en data/raw/FR_AMF.
"""

import os
from pathlib import Path

CANONICAL_FR = Path("D:/ARGOS_DATA/raw/FR_AMF")
FALLBACK_FR = Path("ARGOS_MOTOR/data/raw/FR_AMF")
BASE_FR = CANONICAL_FR if CANONICAL_FR.exists() else FALLBACK_FR

def audit_french_downloads():
    print("=== AUDITORÍA DE ARCHIVOS DESCARGADOS EN FRANCIA (FR_AMF) ===")
    print(f"Ruta auditada: {BASE_FR}")
    if not BASE_FR.exists():
        print(f"Directorio no encontrado: {BASE_FR}")
        return

    files = [f for f in BASE_FR.rglob('*') if f.is_file()]
    print(f"Total archivos encontrados: {len(files)}")

    by_ext = {}
    for f in files:
        ext = f.suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1

    print("Distribución por tipo de archivo:", by_ext)

    # Revisar presencia de informes completos vs solo metadatos
    companies = set()
    completos = 0
    metas = 0

    for year_dir in BASE_FR.iterdir():
        if not year_dir.is_dir(): continue
        for cdir in year_dir.iterdir():
            if not cdir.is_dir(): continue
            companies.add(cdir.name)
            c_files = [f.name.lower() for f in cdir.iterdir() if f.is_file()]
            if any(f.endswith('.zip') or f.endswith('.xhtml') or f.endswith('.htm') for f in c_files):
                completos += 1
            elif any(f.endswith('.json') for f in c_files):
                metas += 1

    print(f"Empresas únicas registradas en FR_AMF: {len(companies)}")
    print(f"Paquetes con documento primario completo (.zip/.htm): {completos}")
    print(f"Registros únicamente con metadatos (.json): {metas}")

if __name__ == '__main__':
    audit_french_downloads()
