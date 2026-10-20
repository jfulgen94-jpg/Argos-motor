"""U3 — Aislamiento de la suite de mod_01_ingestion.

``mod_08_monitor.src.logger`` crea ``<STATER_LOG_DIR|logs>/stater_motor_<fecha>.json`` al IMPORTARSE (ruta relativa al
cwd). Se redirige a un directorio temporal antes de que cualquier test lo importe, para que la suite no escriba en
``ARGOS_MOTOR/logs``. No altera el comportamiento del logger en producción (solo fija el entorno de los tests).
"""
import atexit
import os
import shutil
import tempfile

if "STATER_LOG_DIR" not in os.environ:
    _log_dir = tempfile.mkdtemp(prefix="argos_test_logs_")
    os.environ["STATER_LOG_DIR"] = _log_dir
    atexit.register(shutil.rmtree, _log_dir, ignore_errors=True)
