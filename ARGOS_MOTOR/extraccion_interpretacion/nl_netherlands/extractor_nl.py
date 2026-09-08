"""
EXTRACTOR Y SEGMENTADOR DOCUMENTAL (PAÍSES BAJOS) - ARGOS MOTOR
Procesa los Geïntegreerde Jaarverslagen y paquetes ESEF de emisores neerlandeses (AEX 25).
"""

import os
import json
import argparse
from pathlib import Path

BASE_NL = Path("ARGOS_MOTOR/data/raw/NL_AFM")

def analyze_dutch_filing(comp_dir, year):
    files = [f for f in comp_dir.rglob('*') if f.is_file()]
    file_names = [f.name.lower() for f in files]
    total_size_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)

    has_zip = any(f.endswith('.zip') for f in file_names)
    has_htm = any(f.endswith('.htm') or f.endswith('.html') or f.endswith('.xhtml') for f in file_names)

    if has_zip or (has_htm and total_size_mb > 1.5):
        completeness = 'COMPLETO_JAARVERSLAG'
    elif any(f.endswith('.json') for f in file_names) and len(files) == 1:
        completeness = 'METADATA_PENDING_DOWNLOAD'
    else:
        completeness = 'PARCIAL'

    return {
        'company': comp_dir.name,
        'year': year,
        'status': completeness,
        'size_mb': round(total_size_mb, 2),
        'files_count': len(files)
    }

def run_dutch_extraction(target_year="2025"):
    print(f"=== EXTRACCIÓN Y SEGMENTACIÓN PAÍSES BAJOS (AFM - FY{target_year}) ===")
    year_dir = BASE_NL / str(target_year)
    if not year_dir.exists():
        print(f"No hay directorio para el año {target_year} en {BASE_NL}")
        return

    records = []
    for c_dir in sorted(year_dir.iterdir()):
        if not c_dir.is_dir(): continue
        rec = analyze_dutch_filing(c_dir, target_year)
        records.append(rec)

    completos = sum(1 for r in records if 'COMPLETO' in r['status'])
    pendientes = sum(1 for r in records if 'METADATA' in r['status'])

    print(f"Total empresas procesadas: {len(records)}")
    print(f"   Completas (Jaarverslag / Paquete descargado): {completos}")
    print(f"   Pendientes de descarga primaria: {pendientes}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=str, default='2025')
    args = parser.parse_args()
    run_dutch_extraction(args.year)
