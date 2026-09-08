"""
AUDITORÍA DE DESCARGAS (ALEMANIA) - ARGOS MOTOR
Verifica la integridad de los paquetes y metadatos en data/raw/DE_BAFIN.
"""

import os
from pathlib import Path

BASE_DE = Path("ARGOS_MOTOR/data/raw/DE_BAFIN")

def audit_german_downloads():
    print("=== AUDITORÍA DE ARCHIVOS DESCARGADOS EN ALEMANIA (DE_BAFIN) ===")
    if not BASE_DE.exists():
        print(f"Directorio no encontrado: {BASE_DE}")
        return

    files = [f for f in BASE_DE.rglob('*') if f.is_file()]
    print(f"Total archivos encontrados: {len(files)}")

    by_ext = {}
    for f in files:
        ext = f.suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1

    print("Distribución por extensión:", by_ext)

    companies = set()
    completos = 0
    metas = 0

    for year_dir in BASE_DE.iterdir():
        if not year_dir.is_dir(): continue
        for cdir in year_dir.iterdir():
            if not cdir.is_dir(): continue
            companies.add(cdir.name)
            c_files = [f.name.lower() for f in cdir.iterdir() if f.is_file()]
            if any(f.endswith('.zip') or f.endswith('.xhtml') or f.endswith('.htm') for f in c_files):
                completos += 1
            elif any(f.endswith('.json') for f in c_files):
                metas += 1

    print(f"Empresas únicas en DE_BAFIN: {len(companies)}")
    print(f"Paquetes con informe primario descargado (.zip/.htm): {completos}")
    print(f"Registros en espera con metadatos sellados (.json): {metas}")

if __name__ == '__main__':
    audit_german_downloads()
