"""
AUDITORÍA DE DESCARGAS (PAÍSES BAJOS) - ARGOS MOTOR
Inspecciona y valida los registros y archivos en data/raw/NL_AFM/.
"""

import os
from pathlib import Path

BASE_NL = Path("ARGOS_MOTOR/data/raw/NL_AFM")

def audit_dutch_downloads():
    print("=== AUDITORÍA DE ARCHIVOS DESCARGADOS EN PAÍSES BAJOS (NL_AFM) ===")
    if not BASE_NL.exists():
        print(f"Directorio no encontrado: {BASE_NL}")
        return

    files = [f for f in BASE_NL.rglob('*') if f.is_file()]
    print(f"Total archivos encontrados: {len(files)}")

    by_ext = {}
    for f in files:
        ext = f.suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1

    print("Distribución por extensión:", by_ext)

    companies = set()
    completos = 0
    metas = 0

    for year_dir in BASE_NL.iterdir():
        if not year_dir.is_dir(): continue
        for cdir in year_dir.iterdir():
            if not cdir.is_dir(): continue
            companies.add(cdir.name)
            c_files = [f.name.lower() for f in cdir.iterdir() if f.is_file()]
            if any(f.endswith('.zip') or f.endswith('.xhtml') or f.endswith('.htm') for f in c_files):
                completos += 1
            elif any(f.endswith('.json') for f in c_files):
                metas += 1

    print(f"Empresas únicas en NL_AFM: {len(companies)}")
    print(f"Paquetes con informe primario completo (.zip/.htm): {completos}")
    print(f"Registros en espera con metadatos sellados (.json): {metas}")

if __name__ == '__main__':
    audit_dutch_downloads()
