"""
DESCARGA INTEGRAL CNMV ESPAÑA — AÑO FISCAL 2025
Módulo para la adquisición de informes regulatorios del ejercicio 2025.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ARGOS_MOTOR.descarga.es_spain.cnmv_engine import CNMVEngine

def run():
    engine = CNMVEngine(target_year=2025)
    engine.execute_year_download(2025)

if __name__ == '__main__':
    run()

