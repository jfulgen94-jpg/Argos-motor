"""
DESCARGA INTEGRAL CNMV ESPAÑA — AÑO FISCAL 2023
Módulo para la adquisición de informes regulatorios del ejercicio 2023.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ARGOS_MOTOR.descarga.es_spain.cnmv_engine import CNMVEngine

def run():
    engine = CNMVEngine(target_year=2023)
    engine.execute_year_download(2023)

if __name__ == '__main__':
    run()

