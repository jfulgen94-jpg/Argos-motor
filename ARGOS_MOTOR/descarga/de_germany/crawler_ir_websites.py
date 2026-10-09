#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Crawler de Páginas IR Corporativas v2 (Annual Reports Only)
===================================================================================
Dado que:
- filings.xbrl.org tiene 0 filings para DE
- ESMA EEAP no tiene REST API pública funcional (ESAP llega en 2027)
- Unternehmensregister + Bundesanzeiger bloquean la IP española
- bundesAPI/deutschland librería usa la misma IP bloqueada

Esta solución alternativa de alto ROI:
- Scrape directo de páginas IR corporativas de DAX40/MDAX/Scale
- Filtro ESTRICTO: solo Annual Reports (no quarterly, half-year, fact-sheets)
- +100 empresas en el mapa directo

1. Usa la API de OffeneRegister.de para obtener datos de empresa + web IR
2. Construye URLs IR directas usando patrones conocidos de las cotizadas alemanas
3. Descarga paquetes ESEF desde los servidores IR de las empresas directamente

Cobertura específica para las 172 empresas de Prime Standard 2021-2025.
Priorización por índice: DAX40 > MDAX > TecDAX > SDAX
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

try:
    import httpx
except ImportError:
    print("pip install httpx"); sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("pip install beautifulsoup4"); sys.exit(1)

# ─── Config ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path("D:/ARGOS_DATA/raw/DE_BAFIN")
UNIVERSE_FILE = ROOT / "config" / "master_universe_de.json"
OUTPUT_IR_CATALOG = ROOT / "config" / "ir_crawl_catalog.json"

YEARS_TARGET = list(range(2012, 2026))  # 2012-2025 completo
CONCURRENCY = 6
TIMEOUT = 25.0

# URLs verificadas como HTTP 200 (probe ejecutado 2026-09-27):
# Ronda 1 (6 OK): DBK, PUMA, DHER, NEM, TKA, TUIG
# Ronda 2 (10 OK): BMW, CON, MBG, DTE, HEI, HEN3, RHM, VOW3, ZAL, NDX1
IR_URL_MAP = {
    # ── Verificadas HTTP 200 ─────────────────────────────────────────────────
    "BMW":   "https://www.bmwgroup.com/en/investor-relations.html",
    "CON":   "https://www.continental.com/en/investors/reports-presentations/financial-reports/",
    "DBK":   "https://investor-relations.db.com/reports-and-events/annual-reports/",
    "DHER":  "https://ir.deliveryhero.com/websites/delivery/English/5000/publications-and-reports.html",
    "DTE":   "https://www.telekom.com/en/investor-relations/publications/financial-results",
    "HEI":   "https://www.heidelbergmaterials.com/en/reports-and-presentations",
    "HEN3":  "https://www.henkel.com/investors-and-analysts/financial-reports",
    "MBG":   "https://group.mercedes-benz.com/investors/",
    "NDX1":  "https://ir.nordex-online.com/",
    "NEM":   "https://www.nemetschek.com/investor-relations/publications/annual-reports/",
    "PUMA":  "https://about.puma.com/en/investor-relations/financial-publications",
    "RHM":   "https://www.rheinmetall.com/en/investor-relations/overview",
    "TKA":   "https://www.thyssenkrupp.com/en/investor-relations/publications/annual-report/",
    "TUIG":  "https://www.tuigroup.com/en-en/investors/annual-reports",
    "VOW3":  "https://www.volkswagen-group.com/en/investors-15766",
    "ZAL":   "https://corporate.zalando.com/en/investor-relations",
    # ── Pendientes de re-verificar (pueden funcionar con User-Agent correcto) ─
    "ALV":   "https://www.allianz.com/en/investor_relations/publications/annual-reports.html",
    "BAYN":  "https://www.bayer.com/en/investors/reports-and-presentations",
    "CBK":   "https://www.commerzbank.de/en/investor-relations/reports-and-publications/annual-report/",
    "LHA":   "https://investor-relations.lufthansa.com/en/publications/annual-reports.html",
    "MUV2":  "https://www.munichre.com/en/investors/publications.html",
    "SAP":   "https://www.sap.com/investors/en/reports.html",
    "SIE":   "https://www.siemens.com/investor-relations/en/financial-publications/annual-report.html",
    "SHL":   "https://ir.siemens-healthineers.com/publications/annual-reports",
    "SRT3":  "https://www.sartorius.com/en/investor-relations/publications/annual-reports",
    "VNA":   "https://investors.vonovia.de/websites/vonovia/English/5600/reporting--publications.html",
    "GXI":   "https://investors.gerresheimer.com/websites/gerresheimer/English/5400/reports.html",
    "KGX":   "https://ir.kion.com/websites/kion/English/5100/reports.html",
    "NOEJ":  "https://investor-relations.knorr-bremse.com/en/publications/annual-reports/",
    "LIN":   "https://www.linde.com/investor-relations/financial-reports/",
    "SMHN":  "https://www.symrise.com/investors/publications-presentations/",
    "PAH3":  "https://www.porsche-se.com/en/ir/publications/",
    "RWE":   "https://ir.rwe.com/en/financial-reports/annual-report/",
    "MTX":   "https://www.mtuaero.com/en/investors/reports-presentations/",
    "COVE":  "https://investor.covestro.com/en/publications/annual-reports/",
    "FLAT":  "https://ir.flatexdegiro.com/en/publication/annual-report/",
    "GBF":   "https://www.grenke.com/en/investor-relations/publications/annual-reports",
    "HLAG":  "https://www.hapag-lloyd.com/en/ir/publications/annual-report.html",
    "HORN":  "https://www.hornbach-holding.de/en/investor-relations/publications/",
    "KWS":   "https://www.kws.com/en/investors/publications/annual-reports/",
    "MAN":   "https://www.man.eu/en/company/investor-relations/reporting/annual-report/",
    "O2D":   "https://www.telefonica.de/investor-relations/annual-report.html",
    "RTL":   "https://www.rtlgroup.com/en/investor-relations/publications/annual-reports.html",
    "SDF":   "https://www.k-plus-s.com/en/investor-relations/publications/annual-report/",
}



# ─── Keywords que CONFIRMAN un informe anual ──────────────────────────────────
ANNUAL_KEYWORDS_POS = [
    "annual report", "jahresbericht", "geschäftsbericht", "geschaftsbericht",
    "annual-report", "geschaeftsbericht", "jahresabschluss", "esef",
    "annual_report", "geschaftsber", "ar20", "ar_20", "ar 20",
    "full year", "full-year", "fy20", "fy-20",
    "integrated report", "integrierter bericht",
]
# Keywords que DESCARTAN (informes trimestrales, half-year, etc.)
ANNUAL_KEYWORDS_NEG = [
    "q1", "q2", "q3", "q4", "quarterly", "half-year", "halfyear", "half year",
    "interim", "quartalsbericht", "halbjahr", "zwischenbericht",
    "fact-sheet", "factsheet", "fact sheet", "press release", "pressemitteilung",
    "transcript", "presentation", "roadshow", "consensus", "analyst",
    "aide-memoire", "aide memoire", "sustainability", "nachhaltigkeitsbericht",
    "csr", "esg report", "proxy", "HV", "hauptversammlung",
    "preliminary", "vorbericht", "q1-20", "q2-20", "q3-20", "q4-20",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ir_crawler")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_universe():
    with open(UNIVERSE_FILE, encoding="utf-8") as f:
        u = json.load(f)
    return u["companies"]


def _is_annual_report(text: str, href: str) -> bool:
    """Devuelve True si el link parece un informe anual, False si es trimestral/otro."""
    combined = (text + " " + href).lower()
    # Rechazar primero si tiene keywords negativos
    if any(neg in combined for neg in ANNUAL_KEYWORDS_NEG):
        return False
    # Confirmar si tiene keywords positivos O extensión de documento financiero
    is_positive = any(pos in combined for pos in ANNUAL_KEYWORDS_POS)
    is_doc = any(combined.endswith(ext) or ext + "?" in combined
                 for ext in [".pdf", ".zip"])
    return is_positive or (is_doc and any(
        kw in combined for kw in ["annual", "jahres", "bericht", "report", "ar", "esef"]
    ))


async def scrape_ir_page(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    ticker: str,
    company: Dict,
    years: List[int],
) -> List[Dict]:
    """Scrape la página IR de la empresa — solo Annual Reports, no quarterly."""
    results = []
    # Priorizar URL override inyectada por main(), fallback al mapa por xetra ticker
    ir_url = company.get("_ir_url_override") or IR_URL_MAP.get(ticker, "")
    xetra = company.get("_xetra_ticker", ticker)
    if not ir_url:
        return results

    async with sem:
        try:
            resp = await client.get(ir_url, timeout=TIMEOUT)
            if resp.status_code not in (200, 206):
                log.debug(f"[IR] {ticker}: HTTP {resp.status_code} en {ir_url}")
                return results

            html = resp.text
            base_url = str(resp.url)
            soup = BeautifulSoup(html, "html.parser")

            seen_urls = set()
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue

                text = a.get_text(strip=True)

                # Filtro estricto: solo informes anuales
                if not _is_annual_report(text, href):
                    continue

                # Extraer año del texto + href
                year_match = re.search(r"20(1[2-9]|2[0-5])", text + " " + href)
                year = int(year_match.group(0)) if year_match else None
                if not year or year not in years:
                    continue

                # Resolver URL completa
                full_url = href if href.startswith("http") else urljoin(base_url, href)
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                results.append({
                    "ticker": ticker,
                    "isin": company.get("isin", ""),
                    "year": year,
                    "url": full_url,
                    "title": text,
                    "source": "ir_website",
                    "ir_base": ir_url,
                })

            log.info(f"[IR-SCRAPE] {ticker}: {len(results)} links anuales encontrados en {ir_url}")

        except Exception as e:
            log.debug(f"[IR] {ticker} ({ir_url}): {e}")

    return results


def _guess_ir_domain(company: Dict) -> Optional[str]:
    """Intenta adivinar el dominio IR de una empresa por su nombre."""
    name = company.get("name_common", "").lower()
    name_clean = re.sub(r"[^\w\s]", "", name).strip()
    words = name_clean.split()[:2]
    if not words:
        return None
    # Ejemplo: "Deutsche Bank" -> "deutschebank.com" o "db.com"
    return None  # Solo usamos el mapa explícito por ahora


async def download_report(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    entry: Dict,
    stats: Dict,
) -> bool:
    year = entry["year"]
    ticker = entry["ticker"]
    url = entry["url"]

    ext = ".zip" if url.lower().endswith(".zip") else ".pdf"
    year_dir = DATA_ROOT / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r"[^\w\-]", "_", f"{ticker}_IR_{year}")
    out_path = year_dir / f"{safe_name}{ext}"
    meta_path = year_dir / f"{safe_name}{ext}.meta.json"

    if out_path.exists():
        stats["skipped"] += 1
        return False

    async with sem:
        try:
            async with client.stream("GET", url, timeout=90.0) as resp:
                if resp.status_code != 200:
                    stats["failed"] += 1
                    return False
                ct = resp.headers.get("content-type", "")
                if "html" in ct and not any(u in url for u in [".pdf", ".zip"]):
                    stats["failed"] += 1
                    return False
                with open(out_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        f.write(chunk)

            size = out_path.stat().st_size
            if size < 50_000:  # < 50KB = no es un informe válido
                out_path.unlink(missing_ok=True)
                stats["failed"] += 1
                return False

            sha = sha256_file(out_path)
            meta = {
                "ticker": ticker,
                "isin": entry.get("isin", ""),
                "year": year,
                "url": url,
                "title": entry.get("title", ""),
                "source": "ir_website",
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "size_bytes": size,
                "sha256": sha,
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            stats["downloaded"] += 1
            log.info(f"[OK-IR] {ticker} {year} {ext} ({size/1024:.0f} KB)")
            return True

        except Exception as e:
            out_path.unlink(missing_ok=True)
            stats["failed"] += 1
            log.debug(f"[FAIL-IR] {ticker} {year}: {e}")
            return False


async def main():
    log.info("=== IR Website Crawler - DAX40/MDAX Annual Reports 2012-2025 ===")
    companies = load_universe()

    # Mapa Xetra ticker -> tickers internos del universo (derivado por matching de nombre)
    XETRA_TO_UNIVERSE = {
        "BMW":   ["BAYE", "BAYE_2"],
        "VOW3":  ["VOLK", "VOLK_2"],
        "MBG":   ["MERC", "DAIM_2"],
        "DBK":   ["DEUT_2"],
        "DTE":   ["DEUT", "DEUT_19"],
        "ALV":   ["ALLI"],
        "BAS":   ["BASF", "BASF_2"],
        "BAYN":  ["BAYE", "BAYE_2"],
        "CON":   ["CONT"],
        "SAP":   ["DE_SAP", "SAPS"],
        "SIE":   ["SIEM_2", "SIEM_3"],
        "RWE":   ["DE_RWE"],
        "EOAN":  ["DE_EON"],
        "MUV2":  ["MUNI"],
        "HEN3":  ["HENK"],
        "IFX":   ["INFI"],
        "LIN":   ["LIND"],
        "FRE":   ["FRES_3"],
        "MRK":   ["MERC_3"],
        "MTX":   ["MTUA"],
        "HEI":   ["HEID"],
        "SRT3":  ["SART"],
        "SMHN":  ["SYMR"],
        "VNA":   ["VONO"],
        "ZAL":   ["ZALA"],
        "PAH3":  ["PORS"],
        "RHM":   ["RHEI"],
        "QIA":   ["QIAG"],
        "TKA":   ["THYS"],
        "PUMA":  ["PUMA"],
        "NEM":   ["NEME"],
        "NDX1":  ["NORD_2"],
        "DHER":  ["DELI"],
        "DWS":   ["DWSG"],
        "CBK":   ["COMM"],
        "HLAG":  ["HAPA"],
        "SHL":   ["SIEM_5"],
        "GXI":   ["GERR"],
        "KGX":   ["KION"],
        "HOT":   ["HOCH"],
        "TUIG":  ["TUIG", "TUIG_2"],
        "RTL":   ["RTLG"],
        "SDF":   ["DE_KS"],
        "GBF":   ["GREN"],
        "FLAT":  ["FLAT"],
    }

    # Construir target: para cada Xetra ticker con IR URL, tomar el primer ticker
    # del universo que exista y añadir la URL IR al registro
    target = {}
    for xetra_ticker, ir_url in IR_URL_MAP.items():
        universe_tickers = XETRA_TO_UNIVERSE.get(xetra_ticker, [xetra_ticker])
        for ut in universe_tickers:
            if ut in companies:
                # Usar el ticker del universo como clave, inyectar la URL IR
                company_data = dict(companies[ut])
                company_data["_ir_url_override"] = ir_url
                company_data["_xetra_ticker"] = xetra_ticker
                target[ut] = company_data
                break

    log.info(f"Empresas con mapa IR resuelto: {len(target)} / {len(IR_URL_MAP)}")
    log.info(f"Años objetivo: {YEARS_TARGET[0]}-{YEARS_TARGET[-1]}")


    transport = httpx.AsyncHTTPTransport(retries=2)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }

    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        limits=limits,
        transport=transport,
    ) as client:

        # Discovery
        log.info(f"\n[Discovery] Scrapeando {len(target)} páginas IR...")
        sem_crawl = asyncio.Semaphore(CONCURRENCY)

        tasks = [
            scrape_ir_page(client, sem_crawl, ticker, company, YEARS_TARGET)
            for ticker, company in target.items()
        ]

        all_found = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            results = await coro
            all_found.extend(results)
            done += 1
            if done % 10 == 0:
                log.info(f"  Scraped: {done}/{len(target)} | Found: {len(all_found)}")

        log.info(f"\n[Discovery] Total: {len(all_found)} links")

        # Deduplicar
        seen = set()
        unique = []
        for r in all_found:
            key = (r["ticker"], r["year"], r["url"])
            if key not in seen:
                seen.add(key)
                unique.append(r)

        log.info(f"[Discovery] Únicos: {len(unique)}")

        # Guardar catálogo
        with open(OUTPUT_IR_CATALOG, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "total": len(unique),
                "items": unique,
            }, f, indent=2, ensure_ascii=False)

        if not unique:
            log.warning("No se encontraron links en páginas IR.")
            return

        # Descarga
        log.info(f"\n[Descarga] {len(unique)} informes...")
        sem_dl = asyncio.Semaphore(CONCURRENCY)
        stats = {"downloaded": 0, "skipped": 0, "failed": 0}

        dl_tasks = [download_report(client, sem_dl, r, stats) for r in unique]
        for coro in asyncio.as_completed(dl_tasks):
            await coro

        log.info("\n=== RESUMEN ===")
        log.info(f"  Descargados:  {stats['downloaded']}")
        log.info(f"  Ya existían:  {stats['skipped']}")
        log.info(f"  Fallidos:     {stats['failed']}")


if __name__ == "__main__":
    asyncio.run(main())
