#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
STATER / ARGOS MOTOR — ORQUESTADOR MAESTRO POR LOTES DE 5 AÑOS (ALEMANIA 2012–2026)
========================================================================================
Orquesta la descarga, sellado criptográfico y sincronización a disco D: y Azure
en 3 lotes institucionales homogéneos de 5 años:

  • LOTE 1 (2021–2026): Post-DiRUG + Mandato ESEF digital (Engine: Post-DiRUG / XBRL ESEF)
  • LOTE 2 (2016–2020): Transición ESEF + Bundesanzeiger Área 22 (Engine: Bundesanzeiger ONNX)
  • LOTE 3 (2012–2015): Histórico Puro Pre-DiRUG (Engine: Bundesanzeiger Área 22 ONNX)

Uso:
  python master_downloader_germany_batches.py --lote 2 --sync-azure
  python master_downloader_germany_batches.py --lote 3 --sync-azure
  python master_downloader_germany_batches.py --all-lotes --sync-azure
========================================================================================
"""

import sys
import json
import time
import argparse
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = ROOT_DIR.parent
DE_GERMANY_DIR = ROOT_DIR / "descarga" / "de_germany"
POST_DIRUG_SCRIPT = DE_GERMANY_DIR / "downloader_germany_post_dirug_2021_2025.py"
BANZ_SCRIPT = DE_GERMANY_DIR / "downloader_germany_bundesanzeiger.py"
SYNC_SCRIPT = ROOT_DIR / "cloud" / "azure_data_lake_sync.py"

LOTES_CONFIG = {
    1: {
        "name": "LOTE 1 (2021–2026): Post-DiRUG + Mandato ESEF Digital",
        "years": ["2021", "2022", "2023", "2024", "2025", "2026"],
        "script": POST_DIRUG_SCRIPT,
        "pages": 3,
    },
    2: {
        "name": "LOTE 2 (2016–2020): Transición ESEF + Bundesanzeiger Área 22",
        "years": ["2016", "2017", "2018", "2019", "2020"],
        "script": BANZ_SCRIPT,
        "pages": 2,
    },
    3: {
        "name": "LOTE 3 (2012–2015): Histórico Puro Bundesanzeiger Área 22",
        "years": ["2012", "2013", "2014", "2015"],
        "script": BANZ_SCRIPT,
        "pages": 2,
    },
}


def run_lote(lote_id: int, limit: int = None, sync_azure: bool = True):
    cfg = LOTES_CONFIG.get(lote_id)
    if not cfg:
        print(f"[ERROR] Lote {lote_id} no reconocido.")
        return False

    print(f"\n=========================================================================")
    print(f"=== INICIANDO {cfg['name']} ===")
    print(f"=========================================================================")
    years_str = ",".join(cfg["years"])

    cmd = [
        sys.executable,
        str(cfg["script"]),
        "--years", years_str,
        "--pages", str(cfg.get("pages", 2)),
    ]
    if limit:
        cmd.extend(["--limit", str(limit)])
    if sync_azure:
        cmd.append("--sync-azure")

    start = time.time()
    proc = subprocess.run(cmd)
    elapsed = time.time() - start

    if proc.returncode == 0:
        print(f"[OK] {cfg['name']} completado en {elapsed:.1f} s.")
        return True
    else:
        print(f"[ERROR] {cfg['name']} finalizó con código {proc.returncode}.")
        return False


def main():
    parser = argparse.ArgumentParser(description="Master Downloader Alemania en Lotes de 5 Años")
    parser.add_argument("--lote", type=int, choices=[1, 2, 3], help="Número del lote a ejecutar (1, 2 o 3)")
    parser.add_argument("--all-lotes", action="store_true", help="Ejecutar secuencialmente los lotes 2 y 3")
    parser.add_argument("--limit", type=int, default=None, help="Límite opcional de empresas por lote")
    parser.add_argument("--sync-azure", action="store_true", default=True, help="Sincronizar automáticamente a Azure")
    args = parser.parse_args()

    if args.lote:
        run_lote(args.lote, limit=args.limit, sync_azure=args.sync_azure)
    elif args.all_lotes:
        for l_id in [2, 3]:
            ok = run_lote(l_id, limit=args.limit, sync_azure=args.sync_azure)
            if not ok:
                print(f"[WARN] Deteniendo ejecución secuencial por error en Lote {l_id}.")
                break
    else:
        print("Especifique --lote [1|2|3] o --all-lotes.")
        parser.print_help()


if __name__ == "__main__":
    main()
