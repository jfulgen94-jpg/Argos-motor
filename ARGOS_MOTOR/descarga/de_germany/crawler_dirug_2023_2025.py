#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Unternehmensregister DiRUG (2023-2025) (Fase 4 Fixed)
=============================================================================
Canal B: Unternehmensregister via proxy residencial alemán.
- Canal A (ESMA EEAP) desactivado por autopsia técnica (interfaz Angular sin endpoint JSON).
- Proxy residencial configurado explícitamente en httpx.AsyncHTTPTransport(proxy=proxy_url)
  para garantizar que el tráfico salga con IP alemana y evitar bloqueos HTTP 403 / 451.
- Extrae metadatos y publicaciones post-DiRUG (2023-2025).

Uso:
  python crawler_dirug_2023_2025.py --proxy "http://user:pass@ip:port"
  python crawler_dirug_2023_2025.py --test
  python crawler_dirug_2023_2025.py --tickers BMW,SIE,SAP
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

try:
    import httpx
except ImportError:
    print("pip install httpx")
    sys.exit(1)

# ─── Config ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path("D:/ARGOS_DATA/raw/DE_BAFIN")
UNIVERSE_FILE = ROOT / "config" / "master_universe_de.json"
OUTPUT_DIRUG = ROOT / "config" / "unternehmensregister_discovered.json"

UNTERNEHMENSREGISTER_BASE = "https://www.unternehmensregister.de"
UR_API = f"{UNTERNEHMENSREGISTER_BASE}/ureg/search!result.action"

YEARS_POST_DIRUG = [2023, 2024, 2025]
CONCURRENCY_UR = 2
TIMEOUT = 45.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dirug_2023")

_cached_ur_token = None
_cached_ur_token_expiry = 0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_universe() -> Dict:
    with open(UNIVERSE_FILE, encoding="utf-8") as f:
        u = json.load(f)
    return u["companies"]


def get_proxy_config(cli_proxy: Optional[str] = None) -> Optional[str]:
    """Lee proxy residencial alemán de CLI o variables de entorno."""
    proxy = cli_proxy or os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy:
        masked = re.sub(r":([^@]+)@", ":****@", proxy)
        log.info(f"[PROXY] Proxy configurado detectado: {masked}")
        return proxy
    log.warning("[PROXY] No se detectó proxy en CLI ni en variables de entorno (HTTP_PROXY / HTTPS_PROXY)")
    log.warning("  Para activar Canal B (Unternehmensregister), configura:")
    log.warning("  --proxy 'http://user:pass@host:port' o $env:HTTP_PROXY = '...'")
    log.warning("  Requiere proxy residencial alemán (ASN: Deutsche Telekom, Vodafone DE, Telefónica)")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# CANAL B: Unternehmensregister via Proxy Residencial Alemán
# ══════════════════════════════════════════════════════════════════════════════

async def search_unternehmensregister(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    ticker: str,
    company: Dict,
    years: List[int],
) -> List[Dict]:
    """
    Busca en Unternehmensregister.de usando el parser de RSC Next.js.
    Requiere proxy residencial alemán activo.
    """
    results = []
    name = company.get("name_legal", company.get("name_common", ticker))

    LEGAL_SUFFIX_RE = re.compile(
        r"\s+(AG|SE|GmbH|KGaA|Co\.|&|Aktiengesellschaft|Holding|Group).*$",
        re.IGNORECASE,
    )
    name_root = LEGAL_SUFFIX_RE.sub("", name).strip()
    if not name_root or len(name_root) < 3:
        name_root = company.get("name_common", ticker)

    global _cached_ur_token, _cached_ur_token_expiry
    async with sem:
        await asyncio.sleep(2.0)  # respetuoso
        try:
            # Obtener token de búsqueda si no está en caché o expiró
            now = time.time()
            if not _cached_ur_token or now >= _cached_ur_token_expiry:
                t_resp = await client.get(
                    f"{UNTERNEHMENSREGISTER_BASE}/api/search-token",
                    headers={"Accept": "application/json,*/*", "Referer": f"{UNTERNEHMENSREGISTER_BASE}/de/suche?areas=all"},
                    timeout=15.0,
                )
                if t_resp.status_code == 451:
                    log.error(f"[UR] 451 Geobloqueado por IP. Configure proxy residencial alemán.")
                    return results
                elif t_resp.status_code == 403:
                    log.error(f"[UR] 403 Forbidden. Configure proxy residencial alemán.")
                    return results
                elif t_resp.status_code == 200:
                    t_data = t_resp.json()
                    _cached_ur_token = t_data.get("token")
                    _cached_ur_token_expiry = now + 1800  # 30 minutos

            if not _cached_ur_token:
                return results

            search_params = {
                "searchToken": _cached_ur_token,
                "name": name_root,
                "areas": "accounting",
            }
            headers_ur = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,*/*",
                "Accept-Language": "de-DE,de;q=0.9",
                "Referer": f"{UNTERNEHMENSREGISTER_BASE}/de/suche",
            }
            resp = await client.get(f"{UNTERNEHMENSREGISTER_BASE}/de/suche", params=search_params, headers=headers_ur, timeout=TIMEOUT)

            if resp.status_code in (403, 451):
                log.error(f"[UR] HTTP {resp.status_code} para {ticker} - IP no alemana. Requiere proxy DE.")
                return results

            if resp.status_code == 200:
                html = resp.text
                pdf_links = _parse_unternehmensregister_html(html, ticker, years)
                results.extend(pdf_links)

        except Exception as e:
            log.debug(f"[UR] {ticker}: {e}")

    return results


def _parse_unternehmensregister_html(html: str, ticker: str, years: List[int]) -> List[Dict]:
    """Extrae links de PDFs/ZIPs del HTML de Unternehmensregister."""
    results = []
    try:
        rsc_matches = re.findall(r'self\.__next_f\.push\(\[.*?,"(.+?)"\]\)', html)
        all_text = html + " ".join(rsc_matches)

        url_patterns = [
            r'"(https://[^"]+unternehmensregister[^"]+\.pdf)"',
            r'"(https://[^"]+unternehmensregister[^"]+\.zip)"',
            r'href="(/ureg/result[^"]+)"',
        ]
        for pattern in url_patterns:
            for match in re.findall(pattern, all_text):
                year = None
                for y in years:
                    if str(y) in match:
                        year = y
                        break
                if year:
                    full_url = match if match.startswith("http") else f"https://www.unternehmensregister.de{match}"
                    results.append({
                        "ticker": ticker,
                        "year": year,
                        "url": full_url,
                        "title": f"Unternehmensregister {year}",
                        "source": "unternehmensregister",
                        "format": "pdf" if ".pdf" in full_url else "zip",
                    })
    except Exception:
        pass
    return results


# ══════════════════════════════════════════════════════════════════════════════
# Descarga
# ══════════════════════════════════════════════════════════════════════════════

async def download_filing(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    entry: Dict,
    stats: Dict,
) -> bool:
    year = entry["year"]
    ticker = entry["ticker"]
    url = entry["url"]
    fmt = entry.get("format", "pdf")
    ext = ".zip" if fmt == "zip_esef" else ".pdf"

    year_dir = DATA_ROOT / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)

    src = entry.get("source", "dirug")
    safe_name = re.sub(r"[^\w\-]", "_", f"{ticker}_{src.upper()}_{year}")
    out_path = year_dir / f"{safe_name}{ext}"
    meta_path = year_dir / f"{safe_name}{ext}.meta.json"

    if out_path.exists():
        stats["skipped"] += 1
        return False

    async with sem:
        try:
            async with client.stream("GET", url, timeout=120.0) as resp:
                if resp.status_code != 200:
                    stats["failed"] += 1
                    return False
                with open(out_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        f.write(chunk)

            size = out_path.stat().st_size
            if size < 5_000:
                out_path.unlink(missing_ok=True)
                stats["failed"] += 1
                return False

            sha = sha256_file(out_path)
            meta = {
                "ticker": ticker,
                "isin": entry.get("isin", ""),
                "lei": entry.get("lei", ""),
                "year": year,
                "url": url,
                "source": src,
                "format": fmt,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "size_bytes": size,
                "sha256": sha,
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            stats["downloaded"] += 1
            log.info(f"[OK-DIRUG] {ticker} {year} {fmt} ({size/1024:.0f} KB)")
            return True

        except Exception as e:
            out_path.unlink(missing_ok=True)
            stats["failed"] += 1
            log.debug(f"[FAIL-DIRUG] {ticker} {year}: {e}")
            return False


async def main():
    parser = argparse.ArgumentParser(description="DiRUG 2023-2025 Crawler (Canal B - Unternehmensregister)")
    parser.add_argument("--canal", choices=["B"], default="B",
                        help="Canal B: Unternehmensregister via proxy residencial alemán (Canal A archivado)")
    parser.add_argument("--proxy", type=str, default="",
                        help="URL del proxy residencial alemán (ej: http://user:pass@proxy-de.net:8080)")
    parser.add_argument("--years", default="2023,2024,2025",
                        help="Años a descargar, separados por comas")
    parser.add_argument("--tickers", type=str, default="",
                        help="Filtrar por tickers o nombres (ej: BMW,SIE,SAP)")
    parser.add_argument("--test", action="store_true",
                        help="Prueba rápida con 3 empresas (BMW, Siemens, SAP)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Límite de empresas a procesar")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(",")]
    log.info(f"=== DiRUG Crawler Fase 4 (Fixed) | Canal B | Años: {years} ===")

    companies = load_universe()

    # Filtrar universo DE
    DUAL_LISTED = {"NL0000235190", "IE000S9YS762"}
    cos_filtered = {
        t: c for t, c in companies.items()
        if not c.get("isin") or (c.get("isin", "") or "").startswith("DE") or c.get("isin", "") in DUAL_LISTED
    }

    if args.test or args.tickers:
        desired = [x.strip().lower() for x in (args.tickers.split(",") if args.tickers else ["bmw", "siemens", "sap"])]
        filtered_targets = {}
        for t, c in cos_filtered.items():
            name_c = (c.get("name_common", "") + " " + c.get("name_legal", "") + " " + t).lower()
            for d in desired:
                if d in t.lower() or d in name_c:
                    filtered_targets[t] = c
                    break
        cos_filtered = filtered_targets
        log.info(f"Modo test/filtrado activado: {len(cos_filtered)} empresas")

    if args.limit > 0:
        cos_filtered = dict(list(cos_filtered.items())[:args.limit])
        log.info(f"Límite de empresas aplicado: {len(cos_filtered)}")

    log.info(f"Empresas activas seleccionadas: {len(cos_filtered)}")

    # ── Configuración explícita del Proxy Residencial Alemán ─────────────────
    proxy_url = get_proxy_config(args.proxy)

    if proxy_url:
        transport = httpx.AsyncHTTPTransport(proxy=proxy_url, retries=2)
        log.info("[RED] AsyncHTTPTransport configurado CON proxy residencial.")
    else:
        transport = httpx.AsyncHTTPTransport(retries=2)
        log.warning("[RED] AsyncHTTPTransport configurado SIN proxy (IP local).")
        log.warning("      Unternehmensregister bloqueará peticiones directas fuera de DE.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }

    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        transport=transport,  # Ahora SÍ saldrá por el proxy configurado
        timeout=httpx.Timeout(45.0, connect=15.0),
    ) as client:

        all_results = []

        log.info(f"\n[Canal B] Unternehmensregister ({len(cos_filtered)} empresas × {len(years)} años)")
        sem_ur = asyncio.Semaphore(CONCURRENCY_UR)
        ur_tasks = [
            search_unternehmensregister(client, sem_ur, t, c, years)
            for t, c in cos_filtered.items()
        ]
        done = 0
        ur_results = []
        for coro in asyncio.as_completed(ur_tasks):
            results = await coro
            ur_results.extend(results)
            done += 1
            if done % 10 == 0 or done == len(ur_tasks):
                log.info(f"  Progreso UR: {done}/{len(ur_tasks)} | Filings encontrados: {len(ur_results)}")

        all_results.extend(ur_results)

        # Deduplicar
        seen = set()
        unique = []
        for r in all_results:
            key = (r["ticker"], r["year"], r["url"])
            if key not in seen:
                seen.add(key)
                unique.append(r)

        log.info(f"\n[Total] {len(unique)} filings únicos encontrados en Unternehmensregister")

        # Guardar catálogo
        OUTPUT_DIRUG.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_DIRUG, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "canal": "B",
                "years": years,
                "total": len(unique),
                "items": unique,
            }, f, indent=2, ensure_ascii=False)
        log.info(f"[Catálogo] Guardado en: {OUTPUT_DIRUG}")

        if not unique:
            log.info("No se descargaron filings nuevos en este lote.")
            return

        # Descarga
        log.info(f"\n[Descarga] Bajando {len(unique)} paquetes...")
        sem_dl = asyncio.Semaphore(CONCURRENCY_UR)
        stats = {"downloaded": 0, "skipped": 0, "failed": 0}
        dl_tasks = [download_filing(client, sem_dl, r, stats) for r in unique]
        for coro in asyncio.as_completed(dl_tasks):
            await coro

        log.info("\n=== RESUMEN DI-RUG FASE 4 (CANAL B FIXED) ===")
        log.info(f"  Descargados:  {stats['downloaded']}")
        log.info(f"  Ya existían:  {stats['skipped']}")
        log.info(f"  Fallidos:     {stats['failed']}")


if __name__ == "__main__":
    asyncio.run(main())
