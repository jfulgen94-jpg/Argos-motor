"""
WRAPPER COMPATIBLE — DOWNLOADER CNMV / ESEF (ESPAÑA)
Redirige llamadas heredadas al motor multicanal modular `cnmv_engine.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ARGOS_MOTOR.descarga.es_spain.run_download_spain import main

if __name__ == '__main__':
    main()

