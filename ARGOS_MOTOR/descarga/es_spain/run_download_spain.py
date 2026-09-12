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
    parser = argparse.ArgumentParser(description="Orquestador Maestro y Descargador Total CNMV / ESEF (España 2012-2026)")
    parser.add_argument('--year', type=int, help="Año específico a procesar (ej: 2024)")
    parser.add_argument('--years', nargs='+', type=int, help="Lista de años específicos (ej: 2020 2021 2022 2023 2024)")
    parser.add_argument('--historic', action='store_true', help="Procesar solo rango histórico pre-ESEF (2012-2019)")
    parser.add_argument('--esef', action='store_true', help="Procesar solo rango digital ESEF (2020-2026)")
    parser.add_argument('--output-dir', type=str, help="Directorio de salida personalizado (por defecto D:/ARGOS_DATA/raw/ES_CNMV)")

    args = parser.parse_args()

    if args.year:
        years_to_run = [args.year]
    elif args.years:
        years_to_run = args.years
    elif args.historic:
        years_to_run = list(range(2012, 2020))
    elif args.esef:
        years_to_run = list(range(2020, 2027))
    else:
        # Por defecto: DESCARGADOR TOTAL COMPLETO DE ESPAÑA (2012 - 2026)
        years_to_run = list(range(2012, 2027))

    print("=========================================================================")
    print("=== DESCARGADOR TOTAL UNIVERSAL CNMV / ESEF ESPAÑA (2012 - 2026) ========")
    print("=========================================================================")
    print(f"Ejercicios programados: {years_to_run}")

    summary_reports = []

    for yr in years_to_run:
        engine = CNMVEngine(target_year=yr, output_dir=args.output_dir)
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

