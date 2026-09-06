"""
Tests unitarios para MOD_01: Edgar Client.
Verifica inicialización, cabeceras SEC y control de rate limit.
"""
import pytest
from pathlib import Path
from mod_01_ingestion.src.edgar_client import EdgarClient


def test_edgar_client_initialization():
    client = EdgarClient(user_agent="STATER Test Agent test@stater.es")
    assert "User-Agent" in client.headers
    assert "STATER Test Agent" in client.headers["User-Agent"]


def test_edgar_client_rate_limit():
    import time
    client = EdgarClient()
    t0 = time.time()
    client._rate_limit()
    client._rate_limit()
    t1 = time.time()
    # Debe haber transcurrido al menos 0.12 segundos
    assert (t1 - t0) >= 0.10
