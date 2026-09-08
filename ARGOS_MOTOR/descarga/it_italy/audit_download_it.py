"""
AUDITORÍA DE DESCARGAS (ITALIA) - ARGOS MOTOR
Verifica los registros y archivos primarios en data/raw/IT_CONSOB/.
"""

import os
from pathlib import Path

BASE_IT = Path("ARGOS_MOTOR/data/raw/IT_CONSOB")

def audit_italian_downloads():
    print("=== AUDITORÍA DE ARCHIVOS DESCARGADOS EN ITALIA (IT_CONSOB) ===")
    if not BASE_IT.exists():
        print(f"Directorio no encontrado: {BASE_IT}")
        return

    files = [f for f in BASE_IT.rglob('*') if f.is_file()]
    print(f"Total archivos encontrados: {len(files)}")

    by_ext = {}
    for f in files:
        ext = f.suffix.lower()
        by_ext[ext] = by_ext.get(ext, 0) + 1

    print("Distribución por extensión:", by_ext)

    companies = set()
    completos = 0
    metas = 0

    for year_dir in BASE_IT.iterdir():
        if not year_dir.is_dir(): continue
        for cdir in year_dir.iterdir():
            if not cdir.is_dir(): continue
            companies.add(cdir.name)
            c_files = [f.name.lower() for f in cdir.iterdir() if f.is_file()]
            if any(f.endswith('.zip') or f.endswith('.xhtml') or f.endswith('.htm') for f in c_files):
                completos += 1
            elif any(f.endswith('.json') for f in c_files):
                metas += 1

    print(f"Empresas únicas en IT_CONSOB: {len(companies)}")
    print(f"Paquetes con documento primario (.zip/.htm): {completos}")
    print(f"Registros en espera con metadatos sellados (.json): {metas}")

if __name__ == '__main__':
    audit_italian_downloads()
