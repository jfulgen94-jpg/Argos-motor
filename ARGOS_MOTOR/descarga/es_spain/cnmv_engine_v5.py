"""
DEPRECATED_TEST_ONLY — NO USAR EN LIVE NI PILOT (ADR-005, U2)
================================================================================
Este motor FABRICA registros ``doc_type="SIMULATED"`` con ``sha256="placeholder"`` y ``status="CACHE_HIT"``.
Nunca debe escribir en un raw operativo (D:/ARGOS_DATA/raw, ARGOS_MOTOR/data/raw, ARGOS_DATA_ROOT).
Desde U2 solo se ejecuta en modo TEST/SANDBOX con ``--allow-simulated`` y un ``--output-root`` explícito
bajo un directorio temporal autorizado; en cualquier otro caso termina con código 2 ANTES de escribir.
Importar el módulo no ejecuta ni escribe nada. La implementación productiva es ``mod_01_ingestion/src/unified``.
================================================================================
MOTOR DE INGESTA INSTITUCIONAL v5 PARA EL MERCADO DE VALORES ESPAÑOL (ARGOS)
================================================================================
Diseñado para la máxima cobertura y resiliencia, cubriendo el periodo 2012-2026.
Implementa estrategias duales para fases históricas (barrido secuencial) y modernas (ESEF/IFA).
Resuelve la asimetría dual del CIF en las bases de datos de la CNMV.
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
import fitz  # PyMuPDF

DEPRECATED_TEST_ONLY = True

# --- Configuración y Constantes ---
CONFIG_PATH = Path(__file__).parent / 'config_es.json'
XBRL_INDEX_URL = "https://filings.xbrl.org/index.json"
CNMV_IFA_URL = "https://www.cnmv.es/portal/Consultas/IFA/ListadoIFA.aspx"
CNMV_AUDITA_URL_TPL = "https://www.cnmv.es/AUDITA/{year}/{doc_id}.pdf"

AUDITA_SEQUENTIAL_RANGES = {
    2012: (14080, 14260),
    2013: (14850, 15050),
    2014: (15580, 15780),
    2015: (16150, 16350),
    2016: (16750, 16980),
    2017: (17300, 17550),
    2018: (17780, 18050),
    2019: (18340, 18600),
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

class SimulationBlocked(Exception):
    """El motor simulado no puede ejecutarse con los parámetros dados (se lanza antes de escribir nada)."""


def assert_run_allowed(mode, allow_simulated: bool, output_root) -> Path:
    """Compuerta de seguridad. Devuelve el output_root validado o lanza ``SimulationBlocked``."""
    try:  # la política vive en el núcleo unificado; si no se puede cargar, se falla cerrado
        from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
        from mod_01_ingestion.src.unified.persistence_guard import is_authorized_sandbox_location
    except ImportError as ex:
        raise SimulationBlocked(f"no se puede cargar la política de persistencia ({ex}); ejecución denegada")
    if not allow_simulated:
        raise SimulationBlocked("DEPRECATED_TEST_ONLY: falta --allow-simulated")
    try:
        mode = ExecutionMode(str(mode).upper())
    except ValueError:
        raise SimulationBlocked("DEPRECATED_TEST_ONLY: indique --mode TEST o --mode SANDBOX")
    if mode in (ExecutionMode.LIVE, ExecutionMode.PILOT):
        raise SimulationBlocked(f"DEPRECATED_TEST_ONLY: modo {mode.value} prohibido; genera datos SIMULATED")
    if not output_root:
        raise SimulationBlocked("DEPRECATED_TEST_ONLY: --output-root explícito obligatorio")
    out = Path(output_root)
    if not is_authorized_sandbox_location(out):
        raise SimulationBlocked("DEPRECATED_TEST_ONLY: --output-root debe estar bajo un directorio temporal "
                                "autorizado y fuera de cualquier raw operativo")
    return out


class CNMVEngineV5:
    """Motor de Ingesta Institucional v5 (SIMULADO, solo pruebas)."""

    def __init__(self, config: Dict[str, Any], output_root):
        self.config = config
        # La compuerta se evalúa antes de crear cliente HTTP o directorios.
        self.canonical_path = assert_run_allowed(config.get("mode"), config.get("allow_simulated", False), output_root)
        self.master_universe = self._load_master_universe()
        self.http_client = httpx.AsyncClient(
            headers={'User-Agent': USER_AGENTS[0]},
            transport=httpx.AsyncHTTPTransport(retries=3),
            timeout=30.0
        )
        self.semaphore = asyncio.Semaphore(config.get('max_workers', 5))
        self.staging_path = self.canonical_path / ".staging"
        self.quarantine_path = self.canonical_path / ".quarantine"
        self.canonical_path.mkdir(parents=True, exist_ok=True)
        self.staging_path.mkdir(exist_ok=True)
        self.quarantine_path.mkdir(exist_ok=True)

    def _load_master_universe(self) -> Dict[str, Any]:
        path = Path(self.config['master_universe_path'])
        if not path.exists():
            raise FileNotFoundError(f"No se encontró el universo maestro en {path}")
        data = json.loads(path.read_text('utf-8'))
        print(f"[+] Universo maestro v{data.get('version')} cargado con {data.get('total_entities')} entidades.")
        return data['companies']

    @staticmethod
    def _calculate_sha256(filepath: Path) -> str:
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    async def _resolve_cif_dual(self, cif: str, year: int) -> Optional[str]:
        cif_clean = re.sub(r'[^A-Z0-9]', '', cif)
        cif_hyphen = f"{cif_clean[0]}-{cif_clean[1:]}"
        for c in [cif_clean, cif_hyphen]:
            try:
                params = {'id': 0, 'nif': c, 'ejercicio': year}
                async with self.semaphore:
                    resp = await self.http_client.get(CNMV_IFA_URL, params=params)
                    if resp.status_code == 200 and "No se han encontrado resultados" not in resp.text:
                        print(f"    [CIF RESOLVER] Éxito para {cif} con la variante '{c}'")
                        return resp.text
            except httpx.RequestError as e:
                print(f"    [!] Error de red resolviendo CIF {c}: {e}")
        return None

    async def _run_modern_phase(self, year: int, dry_run: bool):
        print(f"--- Iniciando Fase Moderna para el ejercicio {year} ---")
        manifest = []
        for ticker, company in self.master_universe.items():
            manifest.append({
                "ticker": ticker, "year": year, "doc_type": "SIMULATED", "simulated": True,
                "sha256": "placeholder", "size_bytes": 0, "status": "CACHE_HIT",
                "file_path": str(self.canonical_path / f"{year}/{company.get('cif_nif', '')}_{ticker}/{ticker}_{year}_ANUAL.pdf")
            })
        print(f"--- Fase Moderna {year} completada. {len(manifest)} registros procesados. ---")
        return manifest

    async def _run_historical_phase(self, year: int, dry_run: bool):
        print(f"--- Iniciando Fase Histórica (Barrido AUDITA) para el ejercicio {year} ---")
        if not self.config.get("allow_network", False):
            print("  [i] Sin --allow-network: el barrido HEAD contra cnmv.es está desactivado.")
            return []
        if year not in AUDITA_SEQUENTIAL_RANGES:
            return []
        min_id, max_id = AUDITA_SEQUENTIAL_RANGES[year]
        tasks = []
        async def check_id(doc_id):
            async with self.semaphore:
                url = CNMV_AUDITA_URL_TPL.format(year=year, doc_id=doc_id)
                try:
                    resp = await self.http_client.head(url, timeout=10)
                    if resp.status_code == 200:
                        print(f"  [+] ID Válido encontrado: {doc_id} (Año {year})")
                        return (doc_id, url)
                except httpx.RequestError:
                    pass
            return None
        for i in range(min_id, max_id + 1):
            tasks.append(check_id(i))
        results = await asyncio.gather(*tasks)
        valid_docs = [r for r in results if r]
        print(f"  [i] Barrido de {year} completado. {len(valid_docs)} IDs válidos detectados de {max_id - min_id + 1} posibles.")
        return [{"ticker": f"HIST_{doc_id}", "year": year, "status": "DOWNLOADED_HISTORICAL"} for doc_id, url in valid_docs]

    async def run_ingestion(self, years: List[int], segments: List[str], dry_run: bool):
        print("="*70)
        print("== ARGOS MOTOR: DESCARGADOR INSTITUCIONAL UNIVERSAL DE ESPAÑA (v5) ==")
        print("="*70)
        for year in sorted(years):
            if year >= 2020:
                manifest_data = await self._run_modern_phase(year, dry_run)
            else:
                manifest_data = await self._run_historical_phase(year, dry_run)
            if not dry_run and manifest_data:
                manifest_path = self.canonical_path / f"MANIFEST_CNMV_{year}.json"
                doc = {
                    "SIMULATED": True,
                    "execution_mode": str(self.config.get("mode")).upper(),
                    "year": year,
                    "generated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    "total_filings": len(manifest_data),
                    "cache_hits": sum(1 for f in manifest_data if f['status'] == 'CACHE_HIT'),
                    "downloaded": sum(1 for f in manifest_data if 'DOWNLOADED' in f['status']),
                    "manifest": manifest_data
                }
                manifest_path.write_text(json.dumps(doc, indent=2), 'utf-8')
                print(f"[+] Manifiesto para el año {year} sellado en {manifest_path}")
        await self.http_client.aclose()
        print("\n[FIN] Proceso de ingesta completado.")

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="[DEPRECATED_TEST_ONLY] Motor v5 SIMULADO para España. Solo TEST/SANDBOX.")
    parser.add_argument('--years', nargs='+', type=int, required=True, help="Lista de años a procesar.")
    parser.add_argument('--segments', nargs='+', default=['ALL'], help="Segmentos a incluir.")
    parser.add_argument('--dry-run', action='store_true', help="Ejecuta el mapeo sin descargar archivos.")
    parser.add_argument('--max-workers', type=int, default=5, help="Número de descargas concurrentes.")
    parser.add_argument('--mode', default=None, help="TEST o SANDBOX (LIVE y PILOT están prohibidos).")
    parser.add_argument('--allow-simulated', action='store_true', help="Autoriza explícitamente generar datos SIMULATED.")
    parser.add_argument('--output-root', default=None, help="Directorio temporal autorizado donde escribir.")
    parser.add_argument('--allow-network', action='store_true', help="Permite el barrido HEAD histórico (red).")
    args = parser.parse_args(argv)
    try:
        out = assert_run_allowed(args.mode, args.allow_simulated, args.output_root)
    except SimulationBlocked as ex:
        print(f"[BLOQUEADO] {ex}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        except Exception:
            pass
    config = {
        "master_universe_path": "ARGOS_MOTOR/config/master_universe_es.json",
        "max_workers": args.max_workers,
        "target_segments": args.segments,
        "mode": args.mode, "allow_simulated": True, "allow_network": args.allow_network,
    }
    engine = CNMVEngineV5(config, out)
    asyncio.run(engine.run_ingestion(args.years, args.segments, args.dry_run))
    return 0


if __name__ == '__main__':
    sys.exit(main())
