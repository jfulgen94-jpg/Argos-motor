#!/usr/bin/env python3
"""
==============================================================================
ARGOS MOTOR — MAESTRO CLI / ENTRYPOINT CENTRAL
==============================================================================
Punto de entrada unificado para operar todo el ecosistema ARGOS MOTOR
tanto en local (Windows) como en la nube (Qwen Coder Studio, OpenHands, Linux VM).

Uso:
  python argos.py check-env
  python argos.py download --country de --years 2012-2024
  python argos.py download --country nl --years 2020-2024
  python argos.py download --country es --years 2020-2024
  python argos.py audit --country de
  python argos.py serve [--port 8000]
"""

import argparse
import os
import sys
import subprocess
from pathlib import Path

# Cargar variables de .env si existe
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))


def check_environment():
    """Verifica el estado del entorno, variables, carpetas y dependencias."""
    print("\n" + "=" * 65)
    print("  ARGOS MOTOR — DIAGNÓSTICO DE ENTORNO Y DEPENDENCIAS")
    print("=" * 65)

    # 1. Variables de entorno
    env_vars = [
        ("ARGOS_DATA_ROOT", os.getenv("ARGOS_DATA_ROOT", "[No configurada -> Usando fallback]")),
        ("PYTHONUNBUFFERED", os.getenv("PYTHONUNBUFFERED", "0")),
        ("STATER_ENV", os.getenv("STATER_ENV", "local")),
        ("ARGOS_HEADLESS", os.getenv("ARGOS_HEADLESS", "0")),
        ("PLAYWRIGHT_BROWSERS_PATH", os.getenv("PLAYWRIGHT_BROWSERS_PATH", "[Default]")),
        ("STATER_DUCKDB_PATH", os.getenv("STATER_DUCKDB_PATH", "data/lake/duckdb/stater_motor.duckdb")),
    ]
    print("\n[1] VARIABLES DE ENTORNO:")
    for k, v in env_vars:
        print(f"    - {k:25}: {v}")

    # 2. Paquetes Python
    print("\n[2] DEPENDENCIAS CRÍTICAS:")
    packages = [
        ("duckdb", "DuckDB (Data Lake)"),
        ("httpx", "HTTPX (Descarga asíncrona)"),
        ("bs4", "BeautifulSoup4 (Parsing HTML)"),
        ("playwright", "Playwright (Scraping Headless OAM)"),
        ("fastapi", "FastAPI (API Institucional)"),
        ("pyarrow", "PyArrow (Parquet)"),
    ]
    all_ok = True
    for mod, desc in packages:
        try:
            __import__(mod)
            print(f"    [OK]  {desc:30} ({mod})")
        except ImportError:
            print(f"    [FAIL]{desc:30} ({mod}) -> FALTA INSTALAR")
            all_ok = False

    # 3. Navegador Playwright
    print("\n[3] PLAYWRIGHT CHROMIUM:")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("data:text/html,<html><body>Argos Chromium OK</body></html>")
            text = page.inner_text("body")
            browser.close()
            print(f"    [OK]  Chromium headless operativo ({text.strip()})")
    except Exception as e:
        print(f"    [WARN] Playwright no listo o sin binarios: {e}")
        print("           Ejecuta: playwright install --with-deps chromium")

    # 4. Estructura de carpetas
    print("\n[4] ESTRUCTURA DE ALMACENAMIENTO:")
    data_root = os.getenv("ARGOS_DATA_ROOT")
    if data_root:
        base = Path(data_root)
    elif Path("D:/ARGOS_DATA").exists():
        base = Path("D:/ARGOS_DATA")
    else:
        base = ROOT_DIR / "data"

    for sub in ["raw/ES_CNMV", "raw/DE_BAFIN", "raw/NL_AFM", "staging", "quarantine", "lake/duckdb"]:
        p = base / sub
        status = "[EXISTE]" if p.exists() else "[CREADO AHORA]"
        p.mkdir(parents=True, exist_ok=True)
        print(f"    {status:15} {p}")

    print("\n" + "=" * 65)
    if all_ok:
        print("  ESTADO GENERAL: LISTO PARA EJECUCIÓN")
    else:
        print("  ESTADO GENERAL: FALTAN DEPENDENCIAS (ejecuta pip install -r requirements.txt)")
    print("=" * 65 + "\n")


def run_download(country: str, extra_args: list):
    """Enruta la descarga al motor específico por país."""
    country = country.lower().strip()
    script_map = {
        "de": ROOT_DIR / "ARGOS_MOTOR" / "descarga" / "de_germany" / "downloader_germany_v3.py",
        "germany": ROOT_DIR / "ARGOS_MOTOR" / "descarga" / "de_germany" / "downloader_germany_v3.py",
        "nl": ROOT_DIR / "ARGOS_MOTOR" / "descarga" / "nl_netherlands" / "downloader_netherlands_v3.py",
        "netherlands": ROOT_DIR / "ARGOS_MOTOR" / "descarga" / "nl_netherlands" / "downloader_netherlands_v3.py",
        "es": ROOT_DIR / "ARGOS_MOTOR" / "descarga" / "es_spain" / "run_download_spain.py",
        "spain": ROOT_DIR / "ARGOS_MOTOR" / "descarga" / "es_spain" / "run_download_spain.py",
    }

    if country not in script_map:
        print(f"[ERROR] País '{country}' no soportado aún en CLI unificado.")
        print(f"        Países disponibles: {list(set(['de', 'nl', 'es']))}")
        sys.exit(1)

    target_script = script_map[country]
    if not target_script.exists():
        print(f"[ERROR] No se encuentra el script de descarga: {target_script}")
        sys.exit(1)

    cmd = [sys.executable, str(target_script)] + extra_args
    print(f"\n[ARGOS CLI] Ejecutando: {' '.join(cmd)}\n")
    try:
        res = subprocess.run(cmd)
        sys.exit(res.returncode)
    except KeyboardInterrupt:
        print("\n[ARGOS CLI] Proceso interrumpido por el usuario.")
        sys.exit(130)


def run_audit(country: str):
    """Ejecuta la auditoría documental del país seleccionado."""
    country = country.lower().strip()
    if country in ["de", "germany"]:
        run_download("de", ["--audit"])
    elif country in ["nl", "netherlands"]:
        run_download("nl", ["--audit"])
    elif country in ["es", "spain"]:
        audit_script = ROOT_DIR / "ARGOS_MOTOR" / "descarga" / "es_spain" / "diagnostico_higiene_es.py"
        if audit_script.exists():
            subprocess.run([sys.executable, str(audit_script)])
    else:
        print(f"[ERROR] Auditoría no definida para {country}")


def run_server(host: str, port: int):
    """Lanza el servidor de la API Institucional FastAPI."""
    try:
        import uvicorn
        print(f"\n[ARGOS CLI] Iniciando API Gateway en http://{host}:{port} ...")
        uvicorn.run("ARGOS_MOTOR.mod_06_api_gateway.src.main:app", host=host, port=port, reload=False)
    except ImportError:
        print("[ERROR] uvicorn no instalado. Ejecuta: pip install uvicorn fastapi")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="ARGOS MOTOR — CLI Maestro",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")

    # Subcomando: check-env
    subparsers.add_parser("check-env", help="Verifica el entorno, dependencias y rutas de datos")

    # Subcomando: download
    dl_parser = subparsers.add_parser("download", help="Lanza descargas oficiales por país")
    dl_parser.add_argument("--country", "-c", required=True, help="País: de, nl, es, fr, it")
    dl_parser.add_argument("--years", "-y", help="Rango de años (ej: 2020-2024)")
    dl_parser.add_argument("--tickers", "-t", help="Lista de tickers separados por coma (ej: SAPS,BASF)")
    dl_parser.add_argument("--dry-run", action="store_true", help="Simulación sin descargar")
    dl_parser.add_argument("--audit", action="store_true", help="Ejecutar solo auditoría")
    dl_parser.add_argument("--skip-canal", help="Canales a omitir (ej: 1,3)")

    # Subcomando: audit
    aud_parser = subparsers.add_parser("audit", help="Audita la integridad y completitud documental")
    aud_parser.add_argument("--country", "-c", default="de", help="País: de, nl, es")

    # Subcomando: serve
    srv_parser = subparsers.add_parser("serve", help="Lanza la API Gateway FastAPI")
    srv_parser.add_argument("--host", default="0.0.0.0", help="Host de escucha")
    srv_parser.add_argument("--port", "-p", type=int, default=8000, help="Puerto de escucha")

    args, unknown_args = parser.parse_known_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "check-env":
        check_environment()
    elif args.command == "download":
        extra = []
        if args.years: extra.extend(["--years", args.years])
        if args.tickers: extra.extend(["--tickers", args.tickers])
        if args.dry_run: extra.append("--dry-run")
        if args.audit: extra.append("--audit")
        if args.skip_canal: extra.extend(["--skip-canal", args.skip_canal])
        extra.extend(unknown_args)
        run_download(args.country, extra)
    elif args.command == "audit":
        run_audit(args.country)
    elif args.command == "serve":
        run_server(args.host, args.port)


if __name__ == "__main__":
    main()
