"""
U3 — Regresión de aislamiento de tests: ningún test de la lista escribe fuera de su ``tmp_path``.

Ejecuta los tests candidatos en un subproceso cuyo cwd es un directorio centinela VACÍO. Si algún test (o un
módulo bajo prueba) escribe relativo al cwd (``data/``, ``logs/``, ``config/``...) el centinela deja de estar
vacío y esta prueba falla. Comprueba además que ``ARGOS_MOTOR/data`` y ``ARGOS_MOTOR/logs`` no cambian.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ARGOS_MOTOR = Path(__file__).resolve().parents[2]
TESTS = ARGOS_MOTOR / "mod_01_ingestion" / "tests"
ISOLATED = ["test_forensic_dataset_auditor.py", "test_ingest_runner.py", "test_universe_gap_filler.py"]
MAX_FILES = 5000   # en un checkout con datos reales (40 GiB) no se recorre el árbol completo


def _snapshot(*dirs):
    out, n = {}, 0
    for d in dirs:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                n += 1
                if n > MAX_FILES:
                    return None
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.mark.parametrize("test_file", ISOLATED)
def test_listed_tests_write_nothing_outside_tmp_path(tmp_path, test_file):
    sentinel = tmp_path / "sentinel_cwd"
    sentinel.mkdir()
    before = _snapshot(ARGOS_MOTOR / "data", ARGOS_MOTOR / "logs", ARGOS_MOTOR / "config")
    env = {k: v for k, v in os.environ.items() if k != "STATER_LOG_DIR"}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": os.pathsep.join([str(ARGOS_MOTOR), str(ARGOS_MOTOR.parent)])})
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS / test_file), "-q", "-p", "no:cacheprovider",
         "-c", str(ARGOS_MOTOR / "pyproject.toml"), "--rootdir", str(ARGOS_MOTOR),
         "--basetemp", str(tmp_path / "inner_tmp")],
        cwd=sentinel, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]
    leaked = sorted(str(p.relative_to(sentinel)) for p in sentinel.rglob("*"))
    assert leaked == [], f"{test_file} escribió fuera de tmp_path: {leaked}"
    after = _snapshot(ARGOS_MOTOR / "data", ARGOS_MOTOR / "logs", ARGOS_MOTOR / "config")
    assert before == after, f"{test_file} modificó data/, logs/ o config/ del árbol del proyecto"


@pytest.mark.parametrize("test_file", ["test_forensic_dataset_auditor.py", "test_ingest_runner.py"])
def test_listed_tests_need_no_network(tmp_path, test_file):
    """Los tests aislados deben pasar con sockets bloqueados (sin red real)."""
    code = (
        "import socket, sys\n"
        "def deny(*a, **k): raise RuntimeError('network blocked')\n"
        "socket.socket.connect = deny; socket.create_connection = deny; socket.getaddrinfo = deny\n"
        "import pytest\n"
        f"sys.exit(pytest.main([r'{TESTS / test_file}', '-q', '-p', 'no:cacheprovider', '-c', r'{ARGOS_MOTOR / 'pyproject.toml'}',"
        f" '--rootdir', r'{ARGOS_MOTOR}', '--basetemp', r'{tmp_path / 'net_tmp'}']))\n")
    sentinel = tmp_path / "sentinel_cwd"
    sentinel.mkdir()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join([str(ARGOS_MOTOR), str(ARGOS_MOTOR.parent)])}
    r = subprocess.run([sys.executable, "-c", code], cwd=sentinel, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-800:]
    assert list(sentinel.iterdir()) == []
