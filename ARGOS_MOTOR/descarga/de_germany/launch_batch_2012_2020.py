#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LANZADOR POR LOTES — UNIVERSO MAESTRO ALEMANIA 2012-2020
Bundesanzeiger Canal B con ventana anual exacta + alias canónicos.

Procesa sólo las empresas/años realmente faltantes.
Se puede relanzar sin duplicar, ya que el canal B verifica cobertura.
"""
import os, sys, json, time, logging
from pathlib import Path

# Agregar el root del workspace
ROOT_DIR = Path(__file__).resolve().parents[1] / 'ARGOS_MOTOR'
WORKSPACE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE_DIR / 'tools' / 'deutschland' / 'src'))

from descarga.de_germany.mega_downloader_de_universe import (
    load_companies, run_canal_bundesanzeiger, run_canal_eqs,
    print_coverage_matrix, update_manifest, sync_azure
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('argos_batch_launch')

# Configuración por lotes
BATCH_SIZE = 50
MAX_PAGES = 3
BASE_YEARS_A = ['2012', '2013', '2014', '2015', '2016']
BASE_YEARS_B = ['2017', '2018', '2019', '2020']

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', type=int, default=0, help='Número de lote (0 = todos)')
    parser.add_argument('--tramo', choices=['A', 'B', 'AB'], default='AB',
                        help='A=2012-2016, B=2017-2020, AB=todos')
    parser.add_argument('--segment', default=None)
    parser.add_argument('--no-azure', action='store_true')
    args = parser.parse_args()

    # Configurar años por tramo
    if args.tramo == 'A':
        years = BASE_YEARS_A
    elif args.tramo == 'B':
        years = BASE_YEARS_B
    else:
        years = BASE_YEARS_A + BASE_YEARS_B

    # Cargar universo
    companies = load_companies(segment_filter=args.segment)
    logger.info(f'Universo cargado: {len(companies)} empresas | Años: {years}')

    # Canal A: EQS links (sin CAPTCHA, inmediato)
    logger.info('--- Iniciando Canal A: EQS PDFs directos ---')
    eqs_new = run_canal_eqs(years)
    logger.info(f'Canal A completado: {eqs_new} nuevos documentos')

    # Canal B: Bundesanzeiger por lotes
    tickers = list(companies.keys())
    if args.batch > 0:
        start = (args.batch - 1) * BATCH_SIZE
        end = start + BATCH_SIZE
        tickers_batch = tickers[start:end]
        companies_batch = {t: companies[t] for t in tickers_batch if t in companies}
        logger.info(f'Lote {args.batch}: empresas {start+1} a {end} ({len(companies_batch)} total)')
    else:
        companies_batch = companies
        logger.info(f'Procesando todas: {len(companies_batch)} empresas')

    logger.info(f'--- Iniciando Canal B: Bundesanzeiger Area 22 ({len(companies_batch)} empresas, {len(years)} años) ---')
    banz_new = run_canal_bundesanzeiger(companies_batch, years, max_pages=MAX_PAGES)
    logger.info(f'Canal B completado: {banz_new} nuevos documentos')

    total = eqs_new + banz_new
    logger.info(f'\n=== RESUMEN LOTE ===')
    logger.info(f'Total nuevos: {total}')
    print_coverage_matrix(years, companies)

    if not args.no_azure and total > 0:
        sync_azure()

if __name__ == '__main__':
    main()
