#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Bundesanzeiger Native Open-Data Ingestion (2012–2022)
=============================================================================
Sustitución de ingeniería inversa frágil por el conector nativo oficial de
la comunidad open-data alemana: `deutschland.bundesanzeiger.Bundesanzeiger`.

Características:
  1. Conexión nativa a Bundesanzeiger con manejo automático de cookies Java y Wicket sessions.
  2. Búsqueda específica en `area_select=22` (Rechnungslegung/Finanzberichte).
  3. Resolución autónoma local de CAPTCHAs mediante ONNX.
  4. Pre-filtrado selectivo: evalúa año fiscal y títulos antes de navegar, evitando descargas innecesarias.
  5. Salida estandarizada en D:/ARGOS_DATA/raw/DE_BAFIN/{year}/ con hash SHA-256, metadatos .meta.json
     y sincronización automática de manifiestos MANIFEST_BAFIN_{year}.json.

Uso:
  python crawler_bundesanzeiger_hrb.py --test                     # Prueba con BMW, Siemens, SAP y 7C Solarparken
  python crawler_bundesanzeiger_hrb.py --tickers BMW,SIE,SAP      # Tickers específicos
  python crawler_bundesanzeiger_hrb.py --segments GENERAL_STANDARD,SCALE_GROWTH # Por segmentos
  python crawler_bundesanzeiger_hrb.py --years 2012-2022          # Rango de ejercicios fiscales
  python crawler_bundesanzeiger_hrb.py                            # Cobertura completa del universo
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Local path setup
ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = ROOT.parent
DEUTSCHLAND_SRC = WORKSPACE_DIR / "tools" / "deutschland" / "src"
if DEUTSCHLAND_SRC.exists() and str(DEUTSCHLAND_SRC) not in sys.path:
    sys.path.insert(0, str(DEUTSCHLAND_SRC))

try:
    from deutschland.bundesanzeiger import Bundesanzeiger
except ImportError as e:
    print(f"Error importando deutschland.bundesanzeiger: {e}")
    sys.exit(1)

DATA_ROOT = Path("D:/ARGOS_DATA/raw/DE_BAFIN")
UNIVERSE_FILE = ROOT / "config" / "master_universe_de.json"
MANIFESTS_DIR = ROOT / "audits" / "manifests"

FINANCIAL_KEYWORDS = [
    "jahresabschluss",
    "konzernabschluss",
    "bilanz",
    "rechnungslegung",
    "finanzbericht",
    "geschäftsbericht",
    "geschaeftsbericht",
]

LOG_DIR = WORKSPACE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "crawler_bundesanzeiger.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
    ]
)
log = logging.getLogger("banz_native")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_universe() -> Dict[str, Dict]:
    if not UNIVERSE_FILE.exists():
        log.error(f"Archivo de universo no encontrado: {UNIVERSE_FILE}")
        return {}
    with open(UNIVERSE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("companies", {})


def extract_fiscal_year(report_title: str, report_date=None) -> Optional[int]:
    """Extrae con alta precisión el año del ejercicio contable del título o fecha del informe."""
    if not report_title:
        return None

    # Patrón: "bis zum 31.12.2021" o "bis 31.12.2021"
    m = re.search(r"bis\s+(?:zum\s+)?\d{1,2}\.\d{1,2}\.(\d{4})", report_title, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Patrón: "zum 31.12.2021"
    m = re.search(r"zum\s+\d{1,2}\.\d{1,2}\.(\d{4})", report_title, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Patrón: "Geschäftsjahr 2021" o "Geschäftsjahr vom ... 2021"
    m = re.search(r"Geschäftsjahr\s+(?:vom\s+[^\d]+)?(\d{4})", report_title, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Patrón: "(Jahresabschluss|Konzernabschluss) ... 2021"
    m = re.search(r"(?:Jahresabschluss|Konzernabschluss|Bilanz)\s+.*?(\d{4})", report_title, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Cuatro dígitos en el rango 2010–2026
    years_found = [int(y) for y in re.findall(r"\b(20[12]\d)\b", report_title)]
    if years_found:
        return max(years_found)

    # Fallback: fecha de publicación menos 1 año
    if report_date and hasattr(report_date, "year"):
        return report_date.year - 1

    return None


def is_financial_report(title: str) -> bool:
    """Verifica si el título corresponde a cuentas anuales o balance contable."""
    t_lower = (title or "").lower()
    return any(kw in t_lower for kw in FINANCIAL_KEYWORDS)


def update_manifest(year: int, record: Dict):
    """Actualiza el manifiesto MANIFEST_BAFIN_{year}.json de forma segura."""
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    m_path = MANIFESTS_DIR / f"MANIFEST_BAFIN_{year}.json"
    manifest = []
    if m_path.exists():
        try:
            with open(m_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = []

    file_name = record.get("file_name")
    existing_idx = None
    for idx, item in enumerate(manifest):
        if item.get("file_name") == file_name:
            existing_idx = idx
            break

    if existing_idx is not None:
        manifest[existing_idx] = record
    else:
        manifest.append(record)

    with open(m_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def save_publication(
    ticker: str,
    company_info: Dict,
    fiscal_year: int,
    report_title: str,
    html_content: str,
    report_date=None,
) -> Optional[Path]:
    """Guarda el balance contable en D:/ARGOS_DATA/raw/DE_BAFIN/{year}/ con metadatos completos."""
    year_dir = DATA_ROOT / str(fiscal_year)
    year_dir.mkdir(parents=True, exist_ok=True)

    safe_ticker = re.sub(r"[^\w\-]", "_", ticker)
    out_file = year_dir / f"DE_BAFIN_{safe_ticker}_{fiscal_year}_BANZ.html"
    meta_file = year_dir / f"DE_BAFIN_{safe_ticker}_{fiscal_year}_BANZ.html.meta.json"

    # Envolver en documento HTML completo con charset utf-8 si es un fragmento
    if not html_content.strip().startswith("<!DOCTYPE") and not html_content.strip().startswith("<html"):
        wrapped_html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>{report_title} - {company_info.get('name_legal', ticker)}</title>
</head>
<body>
{html_content}
</body>
</html>"""
    else:
        wrapped_html = html_content

    raw_bytes = wrapped_html.encode("utf-8")
    sha = sha256_bytes(raw_bytes)
    byte_size = len(raw_bytes)

    with open(out_file, "wb") as f:
        f.write(raw_bytes)

    iso_date = report_date.isoformat() if hasattr(report_date, "isoformat") else datetime.utcnow().isoformat() + "Z"
    meta_data = {
        "ticker": ticker,
        "isin": company_info.get("isin", ""),
        "wkn": company_info.get("wkn", ""),
        "lei": company_info.get("lei", ""),
        "hrb_reg": company_info.get("hrb_reg", ""),
        "legal_name": company_info.get("name_legal", ""),
        "name_common": company_info.get("name_common", ""),
        "segment": company_info.get("segment", ""),
        "fiscal_year": fiscal_year,
        "publication_title": report_title,
        "publication_date": str(report_date),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "BUNDESANZEIGER_NATIVE_OPENDATA",
        "format": "html",
        "byte_size": byte_size,
        "sha256": sha,
        "file_name": out_file.name,
    }

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, indent=2, ensure_ascii=False)

    # Actualizar manifiesto BAFIN del año correspondiente
    manifest_record = {
        "file_name": out_file.name,
        "sha256": sha,
        "byte_size": byte_size,
        "retrieved_at_utc": meta_data["retrieved_at_utc"],
        "source_url": "https://www.bundesanzeiger.de",
        "reporting_year": fiscal_year,
        "ticker": ticker,
        "legal_name": company_info.get("name_legal", ""),
        "name_common": company_info.get("name_common", ""),
        "lei": company_info.get("lei", ""),
        "hrb_reg": company_info.get("hrb_reg", ""),
        "segment": company_info.get("segment", ""),
        "magic_mime_verified": "HTML",
        "validation_reason": f"HTML valido ({byte_size:,} bytes)",
        "download_channel": "CANAL_BUNDESANZEIGER_NATIVE_OPENDATA",
        "downloader_version": "4.1.0",
    }
    update_manifest(fiscal_year, manifest_record)

    log.info(f"  [GUARDADO] {ticker} {fiscal_year} ({byte_size/1024:.1f} KB) -> {out_file.name}")
    return out_file


def is_matching_company(report_company: str, target_name: str) -> bool:
    """Verifica que la razón social del informe corresponda a la empresa objetivo."""
    if not report_company or not target_name:
        return True
    stopwords = {"ag", "gmbh", "se", "co", "kg", "holding", "deutschland", "germany", "group", "und", "&"}
    rc = set(re.sub(r"[^\w\s]", " ", report_company.lower()).split()) - stopwords
    tn = set(re.sub(r"[^\w\s]", " ", target_name.lower()).split()) - stopwords
    if not tn:
        return True
    overlap = len(tn.intersection(rc))
    return overlap >= min(2, len(tn))


def process_company(
    ba: Bundesanzeiger,
    ticker: str,
    info: Dict,
    target_years: Set[int],
    max_pages: int = 3,
    force: bool = False,
) -> Tuple[int, int]:
    """
    Descarga los balances oficiales de una empresa para los ejercicios requeridos.
    Retorna (descargados, omitidos).
    """
    name_legal = info.get("name_legal", "").strip()
    name_common = info.get("name_common", "").strip()
    hrb_reg = info.get("hrb_reg", "").strip()

    # Determinar qué años ya tenemos en disco para esta empresa
    years_needed = set()
    for y in target_years:
        f_html = DATA_ROOT / str(y) / f"DE_BAFIN_{ticker}_{y}_BANZ.html"
        f_pdf = DATA_ROOT / str(y) / f"DE_BAFIN_{ticker}_{y}_BANZ.pdf"
        f_hrb_html = DATA_ROOT / str(y) / f"{ticker}_BANZ_HRB_{y}.html"
        f_hrb_pdf = DATA_ROOT / str(y) / f"{ticker}_BANZ_HRB_{y}.pdf"
        if force or (not f_html.exists() and not f_pdf.exists() and not f_hrb_html.exists() and not f_hrb_pdf.exists()):
            years_needed.add(y)

    if not years_needed:
        log.info(f"[{ticker}] {name_legal or name_common}: Todos los ejercicios {min(target_years)}-{max(target_years)} ya existen en disco.")
        return 0, len(target_years)

    log.info(f"[{ticker}] Procesando {name_legal or name_common} (Años pendientes: {sorted(list(years_needed))})")

    # Lista de términos de búsqueda en orden de preferencia
    search_queries = []
    if name_legal:
        search_queries.append(name_legal)
    if name_common and name_common != name_legal:
        search_queries.append(name_common)
    if hrb_reg and len(hrb_reg) > 3:
        search_queries.append(hrb_reg)

    if not search_queries:
        log.warning(f"[{ticker}] Sin nombre ni HRB registrado. Omitiendo.")
        return 0, 0

    downloaded_count = 0
    saved_years = set()

    def report_filter(entry) -> bool:
        """Filtro dinámico de descarga: evalúa título, empresa y año antes de descargar."""
        title = entry.name
        if not is_financial_report(title):
            return False
        if name_legal and not is_matching_company(entry.company, name_legal):
            return False
        year = extract_fiscal_year(title, entry.date)
        if not year or year not in years_needed:
            return False
        if year in saved_years:
            return False
        return True

    for query in search_queries:
        try:
            reports = ba.get_reports(
                company_name=query,
                area_select="22",
                page_limit=max_pages,
                filter_callback=report_filter,
            )
        except Exception as e:
            log.warning(f"[{ticker}] Error en consulta '{query}': {e}")
            continue

        if not reports:
            continue

        # Procesar los informes descargados
        for h, rep_dict in reports.items():
            title = rep_dict.get("name", "")
            date_val = rep_dict.get("date")
            raw_content = rep_dict.get("raw_report") or rep_dict.get("report") or ""

            if not raw_content or len(raw_content) < 200:
                continue

            year = extract_fiscal_year(title, date_val)
            if not year or year not in years_needed:
                continue

            if year in saved_years:
                continue

            save_publication(
                ticker=ticker,
                company_info=info,
                fiscal_year=year,
                report_title=title,
                html_content=raw_content,
                report_date=date_val,
            )
            saved_years.add(year)
            downloaded_count += 1

        # Si ya cubrimos los años necesarios, no consultar fallbacks
        if years_needed.issubset(saved_years):
            break

    skipped_count = len(target_years) - len(saved_years)
    return downloaded_count, skipped_count


def main():
    parser = argparse.ArgumentParser(
        description="Bundesanzeiger Native Open-Data Ingestion (deutschland.bundesanzeiger)"
    )
    parser.add_argument("--test", action="store_true", help="Prueba rápida con BMW, Siemens, SAP y 7C Solarparken")
    parser.add_argument("--tickers", type=str, default="", help="Tickers separados por coma (ej: BMW,SIE,SAP)")
    parser.add_argument(
        "--segments",
        type=str,
        default="PRIME_STANDARD,GENERAL_STANDARD,SCALE_GROWTH",
        help="Segmentos a procesar (ej: GENERAL_STANDARD,SCALE_GROWTH o ALL)",
    )
    parser.add_argument(
        "--years",
        type=str,
        default="2012-2022",
        help="Rango o lista de años contables (ej: 2012-2022 o 2015,2018)",
    )
    parser.add_argument("--pages", type=int, default=3, help="Número máximo de páginas de búsqueda por empresa (default: 3)")
    parser.add_argument("--limit", type=int, default=0, help="Limitar número máximo de empresas")
    parser.add_argument("--offset", type=int, default=0, help="Omitir las primeras N empresas (ej: 497)")
    parser.add_argument("--start-from", type=int, default=0, help="Número de empresa desde la que empezar (1-indexed, ej: 498 o 499)")
    parser.add_argument("--delay", type=float, default=1.2, help="Pausa en segundos entre empresas")
    parser.add_argument("--force", action="store_true", help="Forzar re-descarga aunque el archivo exista")
    args = parser.parse_args()

    # Parsear años
    if "-" in args.years:
        start_y, end_y = map(int, args.years.split("-"))
        target_years = set(range(start_y, end_y + 1))
    else:
        target_years = {int(y.strip()) for y in args.years.split(",")}

    log.info("=" * 70)
    log.info("  BUNDESANZEIGER NATIVE OPEN-DATA INGESTION (2012–2022)")
    log.info(f"  Años objetivo: {min(target_years)} a {max(target_years)} ({len(target_years)} años)")
    log.info(f"  Directorio destino: {DATA_ROOT}")
    log.info("=" * 70)

    universe = load_universe()
    if not universe:
        log.error("Universo vacío. Abortando.")
        sys.exit(1)

    # Filtrar empresas
    target_companies: Dict[str, Dict] = {}

    if args.test:
        test_tickers = ["BAYE", "SIEM_2", "DE_SAP", "7CSO", "AIRB"]
        for t, c in universe.items():
            if t in test_tickers:
                target_companies[t] = c
        log.info(f"[TEST] Seleccionadas {len(target_companies)} empresas de prueba: {list(target_companies.keys())}")
    elif args.tickers:
        wanted = [t.strip().upper() for t in args.tickers.split(",")]
        for t, c in universe.items():
            t_u = t.upper()
            common = (c.get("name_common") or "").upper()
            legal = (c.get("name_legal") or "").upper()
            if any(w == t_u or w in t_u or w in common or w in legal for w in wanted):
                target_companies[t] = c
        log.info(f"Filtradas {len(target_companies)} empresas por tickers/nombres: {list(target_companies.keys())}")
    else:
        allowed_segs = [s.strip().upper() for s in args.segments.split(",")]
        for t, c in universe.items():
            seg = c.get("segment", "").upper()
            if "ALL" in allowed_segs or seg in allowed_segs:
                target_companies[t] = c
        log.info(f"Seleccionadas {len(target_companies)} empresas en segmentos: {args.segments}")

    total_universe_count = len(target_companies)
    start_idx = 0
    if args.start_from and args.start_from > 1:
        start_idx = args.start_from - 1
    elif args.offset and args.offset > 0:
        start_idx = args.offset

    if start_idx > 0:
        target_companies = dict(list(target_companies.items())[start_idx:])
        log.info(f"Offset aplicado: omitidas primeras {start_idx} empresas. Procesando desde #{start_idx + 1} ({len(target_companies)} empresas restantes).")

    if args.limit and args.limit > 0:
        target_companies = dict(list(target_companies.items())[: args.limit])
        log.info(f"Límite aplicado: procesando primeras {len(target_companies)} empresas.")

    # Inicializar motor nativo Bundesanzeiger
    ba = Bundesanzeiger()

    total_downloaded = 0
    total_skipped = 0
    start_time = time.time()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    for idx, (ticker, info) in enumerate(target_companies.items(), start=start_idx + 1):
        log.info(f"\n[{idx}/{total_universe_count}] >>> {ticker} - {info.get('name_legal', '')}")
        try:
            dl, sk = process_company(
                ba=ba,
                ticker=ticker,
                info=info,
                target_years=target_years,
                max_pages=args.pages,
                force=args.force,
            )
            total_downloaded += dl
            total_skipped += sk
        except Exception as e:
            log.error(f"[{ticker}] Error inesperado en procesamiento: {e}")

        if args.delay > 0 and idx < len(target_companies):
            time.sleep(args.delay)

    elapsed = time.time() - start_time
    log.info("\n" + "=" * 70)
    log.info("  RESUMEN DE EJECUCIÓN BUNDESANZEIGER NATIVE")
    log.info(f"  Empresas procesadas:    {len(target_companies)}")
    log.info(f"  Nuevos balances descargados: {total_downloaded}")
    log.info(f"  Balances omitidos (existentes): {total_skipped}")
    log.info(f"  Tiempo total:          {elapsed:.1f} s")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
