"""
MOD_08 — Logger Centralizado de STATER Motor Argos.

Todos los módulos del motor importan este logger:
    from mod_08_monitor.src.logger import log

Emite logs JSON estructurados a consola y a archivo rotatorio diario.
Compatible con Azure Monitor, ELK y Grafana Loki.
"""
import sys
import os
from loguru import logger

# --- Configuración -----------------------------------------------------------
LOG_LEVEL = os.getenv("STATER_LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("STATER_LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Formato JSON estructurado (una línea por evento)
JSON_FORMAT = (
    '{{"ts":"{time:YYYY-MM-DDTHH:mm:ss}Z",'
    '"level":"{level}",'
    '"module":"{extra[module]}",'
    '"event":"{message}",'
    '"extra":{extra}}}'
)

# Eliminar handler por defecto de loguru
logger.remove()

# Handler 1: Consola (legible en desarrollo)
logger.add(
    sys.stderr,
    level=LOG_LEVEL,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[module]}</cyan> | {message}",
    colorize=True,
)

# Handler 2: Archivo JSON rotatorio diario (para ingestión por Azure Monitor / Grafana)
logger.add(
    f"{LOG_DIR}/stater_motor_{{time:YYYYMMDD}}.json",
    level=LOG_LEVEL,
    format=JSON_FORMAT,
    rotation="00:00",      # Rota a medianoche
    retention="30 days",   # Retiene 30 días de logs
    compression="zip",     # Comprime logs históricos
    serialize=True,        # Fuerza serialización JSON
)


def get_logger(module_name: str):
    """
    Devuelve un logger contextualizado para un módulo específico.

    Uso:
        from mod_08_monitor.src.logger import get_logger
        log = get_logger("MOD_01")
        log.info("edgar_download_start", entity="AAPL", year=2024)
    """
    return logger.bind(module=module_name)


# Logger global por defecto (para uso rápido sin contextualización)
log = get_logger("STATER")
