"""
EXTRACTOR Y SEGMENTADOR DOCUMENTAL (ALEMANIA) - ARGOS MOTOR
Procesa los paquetes ESEF y Geschäftsberichte de emisores alemanes (DAX 40).
"""

import os
import json
import argparse
from pathlib import Path

BASE_DE = Path("ARGOS_MOTOR/data/raw/DE_BAFIN")

def analyze_german_filing(comp_dir, year):
    files = [f for f in comp_dir.rglob('*') if f.is_file()]
    file_names = [f.name.lower() for f in files]
    total_size_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)

    has_zip = any(f.endswith('.zip') for f in file_names)
    has_htm = any(f.endswith('.htm') or f.endswith('.html') or f.endswith('.xhtml') for f in file_names)

    if has_zip or (has_htm and total_size_mb > 1.5):
        completeness = 'COMPLETO_GESCHAEFTSBERICHT'
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

def run_german_extraction(target_year="2025"):
    print(f"=== EXTRACCIÓN Y SEGMENTACIÓN ALEMANIA (BAFIN - FY{target_year}) ===")
    year_dir = BASE_DE / str(target_year)
    if not year_dir.exists():
        print(f"No hay directorio para el año {target_year} en {BASE_DE}")
        return

    records = []
    for c_dir in sorted(year_dir.iterdir()):
        if not c_dir.is_dir(): continue
        rec = analyze_german_filing(c_dir, target_year)
        records.append(rec)

    completos = sum(1 for r in records if 'COMPLETO' in r['status'])
    pendientes = sum(1 for r in records if 'METADATA' in r['status'])

    print(f"Total empresas procesadas: {len(records)}")
    print(f"   Completas (Geschäftsbericht / Paquete descargado): {completos}")
    print(f"   Pendientes de descarga primaria: {pendientes}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=str, default='2025')
    args = parser.parse_args()
    run_german_extraction(args.year)
