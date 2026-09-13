"""
ORQUESTADOR MAESTRO DE DESCARGA CNMV ESPAÑA — ARGOS MOTOR
Permite ejecutar la descarga completa de todos los ejercicios (2020 a 2025)
o la ejecución individual por año especificado.

Uso:
  python run_download_spain.py
  python run_download_spain.py --year 2023
  python run_download_spain.py --years 2021 2022 2023 2024
"""

import sys
import argparse
from pathlib import Path

# Añadir raíz al path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ARGOS_MOTOR.descarga.es_spain.cnmv_engine import CNMVEngine

def main():
    parser = argparse.ArgumentParser(description="Orquestador Maestro de Descarga CNMV (España)")
    parser.add_argument('--year', type=int, help="Año específico a descargar (ej: 2023)")
    parser.add_argument('--years', nargs='+', type=int, help="Lista de años a descargar (ej: 2020 2021 2022 2023 2024)")
    parser.add_argument('--output-dir', type=str, help="Directorio de salida personalizado")

    args = parser.parse_args()

    years_to_run = [2020, 2021, 2022, 2023, 2024, 2025]
    if args.year:
        years_to_run = [args.year]
    elif args.years:
        years_to_run = args.years

    # Set output directory with robust multi-platform detection
    if args.output_dir:
        output_dir = args.output_dir
    elif Path("D:/ARGOS_DATA/raw/ES_CNMV").parent.exists():
        output_dir = "D:/ARGOS_DATA/raw/ES_CNMV"
    elif Path("/opt/argos_data/raw/ES_CNMV").parent.exists():
        output_dir = "/opt/argos_data/raw/ES_CNMV"
    elif Path("/workspace/project/Argos-motor/ARGOS_MOTOR/data/raw/ES_CNMV").parent.exists():
        output_dir = "/workspace/project/Argos-motor/ARGOS_MOTOR/data/raw/ES_CNMV"
    else:
        output_dir = "ARGOS_MOTOR/data/raw/ES_CNMV"

    print("=========================================================================")
    print("=== ORQUESTADOR DE DESCARGA CNMV / ESEF ESPAÑA (1.000 ARCHIVOS / PAÍS) ===")
    print("=========================================================================")
    print(f"Años a procesar: {years_to_run}")

    summary_reports = []

    for yr in years_to_run:
        engine = CNMVEngine(target_year=yr, output_dir=output_dir)
        stats = engine.execute_year_download(yr)
        summary_reports.append(stats)

    print("\n" + "=" * 80)
    print("=== RESUMEN GLOBAL DE DESCARGA INTEGRAL ESPAÑA ===")
    print("=" * 80)
    total_dl = sum(s['downloaded'] for s in summary_reports)
    total_ch = sum(s['cache_hits'] for s in summary_reports)
    total_fl = sum(s['failed'] for s in summary_reports)
    total_qu = sum(s['quarantined'] for s in summary_reports)

    for s in summary_reports:
        print(f" • Año {s['year']}: Mapeados={s['total_mapped']} | Descargados Nuevos={s['downloaded']} | Caché={s['cache_hits']} | Fallos/Cuarentena={s['failed'] + s['quarantined']}")

    print("-" * 80)
    print(f" TOTAL COMPLETO PROCESADO: Nuevos: {total_dl} | Válidos en Caché: {total_ch} | Total Efectivo: {total_dl + total_ch}")
    print(f" Fallos / En Cuarentena: {total_fl + total_qu}")
    print("=" * 80)

if __name__ == '__main__':
    main()

