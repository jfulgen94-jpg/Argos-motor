"""
MOTOR DE INGESTA INSTITUCIONAL DUAL-CHANNEL PARA ALEMANIA (DE_BAFIN)
========================================================================
Proyecto ARGOS - Versión 2.0

- **Canal 1 (Moderno, 2020-2025):** ESEF Fast-Path vía filings.xbrl.org y caché local.
- **Canal 2 (Histórico y Fallback, 2012-2025):** Consulta al área 22 (Rechnungslegung/Finanzberichte)
  del Bundesanzeiger y Unternehmensregister.
"""

import sys
import json
import re
import time
import asyncio
import hashlib
from pathlib import Path
import argparse
from typing import Dict, List, Any, Optional

import httpx
from bs4 import BeautifulSoup

# --- Configuración y Constantes ---
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

CONFIG_PATH = Path(__file__).parent / 'config_de.json'
ESEF_INDEX_URL = "https://filings.xbrl.org/index.json"
BUNDESANZEIGER_URL = "https://www.bundesanzeiger.de/pub/de/start?0"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

class BafinDownloaderV2:
    """Motor de descarga dual para el mercado alemán."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.master_universe = self._load_master_universe()
        self.http_client = httpx.AsyncClient(
            headers={'User-Agent': USER_AGENTS[0]},
            transport=httpx.AsyncHTTPTransport(retries=3, limits=httpx.Limits(max_connections=5)),
            timeout=45.0
        )
        self.semaphore = asyncio.Semaphore(config.get('max_workers', 3))
        self.canonical_path = self._get_canonical_path()
        self.staging_path = self.canonical_path / ".staging"
        self.quarantine_path = self.canonical_path / ".quarantine"
        self.canonical_path.mkdir(parents=True, exist_ok=True)
        self.staging_path.mkdir(exist_ok=True)
        self.quarantine_path.mkdir(exist_ok=True)

    def _get_canonical_path(self) -> Path:
        paths_to_check = [
            Path("/opt/argos_data/raw/DE_BAFIN"),
            Path("D:/ARGOS_DATA/raw/DE_BAFIN"),
            Path("ARGOS_MOTOR/data/raw/DE_BAFIN")
        ]
        for p in paths_to_check:
            if p.exists() or p.parent.exists():
                print(f"[+] Volumen canónico detectado en: {p}")
                return p
        print("[!] Aviso: No se detectó un volumen canónico. Usando ruta por defecto.")
        return paths_to_check[-1]

    def _load_master_universe(self) -> Dict[str, Any]:
        path = Path(self.config['master_universe_path'])
        if not path.exists():
            raise FileNotFoundError(f"No se encontró el universo maestro en {path}")
        data = json.loads(path.read_text('utf-8'))
        print(f"[+] Universo maestro DE v{data.get('version')} cargado con {data.get('total_entities')} entidades.")
        return data['companies']

    async def _run_esef_channel(self, year: int, dry_run: bool):
        print(f"--- Canal 1 (ESEF) para el ejercicio {year} ---")
        # Lógica para descargar desde filings.xbrl.org (simplificada)
        # Se asume que los 303 ESEF ya están en caché local
        return []

    async def _run_bundesanzeiger_channel(self, year: int, segment: str, dry_run: bool):
        print(f"--- Canal 2 (Bundesanzeiger) para {year} [Segmento: {segment}] ---")
        # Lógica de consulta al Bundesanzeiger (simulada)
        # Iteraría sobre las empresas del segmento, consultaría el sitio, y mapearía los filings
        # ...
        return []

    async def run_ingestion(self, years: List[int], segments: List[str], dry_run: bool):
        print("="*70)
        print("== ARGOS MOTOR: DESCARGADOR INSTITUCIONAL ALEMÁN (DE_BAFIN v2) ==")
        print("="*70)
        
        for year in sorted(years):
            print(f"\n[>>] PROCESANDO AÑO FISCAL: {year}")
            if year >= 2020:
                esef_filings = await self._run_esef_channel(year, dry_run)
                # Aquí iría el fallback al canal 2 si esef_filings es insuficiente
            
            bundes_filings = await self._run_bundesanzeiger_channel(year, ",".join(segments), dry_run)

            # Consolidar y sellar manifiesto (lógica simulada)
            all_filings = esef_filings + bundes_filings
            if not dry_run:
                manifest_path = self.canonical_path / f"MANIFEST_BAFIN_{year}.json"
                doc = {
                    "year": year, "generated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    "total_filings": len(all_filings),
                    "manifest": all_filings
                }
                manifest_path.write_text(json.dumps(doc, indent=2), 'utf-8')
                print(f"  [+] Manifiesto para el año {year} sellado con {len(all_filings)} registros.")

        await self.http_client.aclose()
        print("\n[FIN] Proceso de ingesta alemán completado.")

def main():
    parser = argparse.ArgumentParser(description="ARGOS Motor de Ingesta v2 para Alemania (BaFin)." )
    parser.add_argument('--years', required=True, help="Años a procesar (separados por coma, ej: 2019,2020)")
    parser.add_argument('--segment', default="ALL", help="Segmentos a incluir (ej: DAX40,MDAX)")
    parser.add_argument('--dry-run', action='store_true', help="Mapeo sin descarga.")
    parser.add_argument('--max-workers', type=int, default=3, help="Conexiones concurrentes.")
    
    args = parser.parse_args()
    years = [int(y) for y in args.years.split(',')]
    segments = [s.strip() for s in args.segment.split(',')]

    # Cargar config
    config = {
        "master_universe_path": "ARGOS_MOTOR/config/master_universe_de.json",
        "max_workers": args.max_workers,
        "target_segments": segments
    }

    engine = BafinDownloaderV2(config)
    asyncio.run(engine.run_ingestion(years, segments, args.dry_run))

if __name__ == '__main__':
    main()
