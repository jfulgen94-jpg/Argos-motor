"""
ORQUESTADOR DE DESCARGA CNMV ESPAÑA (ACCESO DIRECTO)
Uso:
  python run_spain_download.py
  python run_spain_download.py --year 2023
  python run_spain_download.py --years 2020 2021 2022 2023 2024
"""
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ARGOS_MOTOR.descarga.es_spain.run_download_spain import main

if __name__ == '__main__':
    warnings.warn('DEPRECATED / LEGACY_BRIDGE: usa mod_01_ingestion.src.unified.cli (ruta unificada). '
                  'Este lanzador conserva el discovery Track A hasta migrarlo.', DeprecationWarning)
    main()

