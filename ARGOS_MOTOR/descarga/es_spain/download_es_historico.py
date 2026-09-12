"""
LANZADOR POR LOTES HISTÓRICO CNMV ESPAÑA (2012 - 2019) — ARGOS MOTOR
=====================================================================
Módulo institucional para la adquisición masiva y secuencial de informes
de auditoría y cuentas anuales en PDF custodiados en el portal oficial de la CNMV.

Genera un MANIFEST_CNMV_<AÑO>.json individual y sellado por cada ejercicio fiscal.
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Añadir raíz al sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ARGOS_MOTOR.descarga.es_spain.cnmv_engine import CNMVEngine

def run_historical(years=None):
    if years is None:
        # Por defecto, rango histórico pre-ESEF completo: 2019 a 2012 descendente
        years = [2019, 2018, 2017, 2016, 2015, 2014, 2013, 2012]

    print("=========================================================================")
    print("=== INICIANDO DESCARGA HISTÓRICA INSTITUCIONAL CNMV (2012 - 2019) =======")
    print("=========================================================================")
    print(f"Ejercicios programados: {years}")
    print(f"Inicio: {datetime.now().isoformat()}")
    print("=========================================================================\n")

    summary = {}
    for yr in years:
        print(f"\n>>>>>>>> INICIANDO EJERCICIO FISCAL {yr} <<<<<<<<")
        engine = CNMVEngine(target_year=yr)
        stats = engine.execute_year_download(yr)
        summary[yr] = {
            'mapped': stats.get('total_mapped', 0),
            'downloaded': stats.get('downloaded', 0),
            'cache_hits': stats.get('cache_hits', 0),
            'failed': stats.get('failed', 0),
            'quarantined': stats.get('quarantined', 0)
        }
        print(f">>>>>>>> EJERCICIO {yr} COMPLETADO: {summary[yr]['downloaded']} nuevos | {summary[yr]['cache_hits']} en caché | {summary[yr]['failed']} fallidos <<<<<<<<\n")

    print("\n=========================================================================")
    print("=== RESUMEN GLOBAL DE LA INGESTA HISTÓRICA CNMV (2012 - 2019) ===========")
    print("=========================================================================")
    for yr, s in summary.items():
        print(f"  Año {yr} -> Mapeados: {s['mapped']} | Descargados: {s['downloaded']} | Caché: {s['cache_hits']} | Fallidos: {s['failed']}")
    print("=========================================================================")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Lanzador Histórico CNMV España (2012-2019)")
    parser.add_argument('--years', type=str, default=None, help="Años separados por coma, ej: 2019,2018,2017")
    args = parser.parse_args()

    selected_years = None
    if args.years:
        selected_years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]

    run_historical(selected_years)
