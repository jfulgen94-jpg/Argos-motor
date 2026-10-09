#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Crawler EQS News (ARCHIVADO / DESACTIVADO)
==================================================================
ESTADO: DESACTIVADO / CÓDIGO MUERTO (2026-09-27)

Motivo de archivado (Autopsia técnica):
1. El endpoint de API https://www.eqs-news.com/api/news/?format=json no existe
   públicamente (devuelve 404 / redirect HTML).
2. Patrones de URL en irpages2 bloqueados: Peticiones automatizadas HEAD/GET
   sin sesión Akamai/Cloudflare devuelven HTTP 503.

No ejecutar para no consumir CPU ni ancho de banda.
"""

import sys

def main():
    print("[ARCHIVADO] crawler_eqs_news.py está desactivado por autopsia técnica.")
    print("  Motivo: Endpoint inexistente y bloqueo Akamai en irpages2.")
    print("  Consulte la documentación de autopsia técnica en el repositorio.")
    sys.exit(0)

if __name__ == "__main__":
    main()


# ─── Config ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path("D:/ARGOS_DATA/raw/DE_BAFIN")
UNIVERSE_FILE = ROOT / "config" / "master_universe_de.json"
OUTPUT_DISCOVERED = ROOT / "config" / "eqs_news_discovered.json"

YEARS = list(range(2012, 2026))
CONCURRENCY_SEARCH = 5    # búsquedas EQS news (respetuoso con el servidor)
CONCURRENCY_DOWNLOAD = 15  # descargas de PDF desde CDN
TIMEOUT_SEARCH = 15.0
TIMEOUT_DOWNLOAD = 90.0
MAX_PAGES = 20             # páginas máximas por empresa en EQS news

# Headers anti-bot mínimos
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Referer": "https://www.eqs-news.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eqs_news")


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


async def search_eqs_news_for_company(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    ticker: str,
    company: Dict,
) -> List[Dict]:
    """
    Busca en EQS News todos los informes anuales de una empresa.
    Prueba múltiples estrategias de búsqueda por nombre, ISIN y ticker.
    """
    results = []
    name_common = company.get("name_common", "")
    name_legal = company.get("name_legal", "")
    isin = company.get("isin", "") or ""

    # Candidatos de búsqueda: nombres limpiados
    legal_suffixes = r"\s+(AG|SE|GmbH|KGaA|Co\.|&|Aktiengesellschaft|Holding|Group|plc|NV|SA|Inc\.).*$"
    name_root = re.sub(legal_suffixes, "", name_legal, flags=re.IGNORECASE).strip()

    search_terms = [name_common, name_root]
    if isin and isin.startswith("DE"):
        search_terms.append(isin)

    # Eliminar duplicados y vacíos
    search_terms = list(dict.fromkeys(t for t in search_terms if t and len(t) > 2))

    async with sem:
        for term in search_terms[:3]:  # máx 3 términos por empresa
            # API JSON interna de EQS News
            url = "https://www.eqs-news.com/api/news/"
            params = {
                "format": "json",
                "q": term,
                "category": "annual_report,financial_report",
                "language": "de",
                "page_size": 50,
            }
            try:
                resp = await client.get(url, params=params, timeout=TIMEOUT_SEARCH)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("results", data.get("items", []))
                    for item in items:
                        year = _extract_year(item)
                        if year and year in YEARS:
                            pdf_url = _extract_pdf_url(item)
                            if pdf_url:
                                results.append({
                                    "ticker": ticker,
                                    "isin": isin,
                                    "year": year,
                                    "url": pdf_url,
                                    "title": item.get("title", ""),
                                    "source": "eqs_news_api",
                                    "search_term": term,
                                })
            except Exception:
                pass

            # Fallback: scrape HTML del news-feed público por ISIN
            if isin and isin.startswith("DE"):
                try:
                    feed_url = f"https://www.eqs-news.com/news-feed/?isin={isin}&category=annual_report"
                    resp2 = await client.get(feed_url, timeout=TIMEOUT_SEARCH)
                    if resp2.status_code == 200:
                        html = resp2.text
                        pdf_links = re.findall(r'href="(https://[^"]+irpages2\.eqs\.com[^"]+\.pdf)"', html)
                        for link in pdf_links:
                            year = _extract_year_from_url(link)
                            if year and year in YEARS:
                                results.append({
                                    "ticker": ticker,
                                    "isin": isin,
                                    "year": year,
                                    "url": link,
                                    "title": f"Annual Report {year} - {name_common}",
                                    "source": "eqs_news_html_scrape",
                                    "search_term": isin,
                                })
                except Exception:
                    pass

    return results


def _extract_year(item: Dict) -> Optional[int]:
    """Extrae el año fiscal del item de noticia."""
    for field in ["fiscal_year", "year", "publication_date", "date"]:
        val = str(item.get(field, ""))
        m = re.search(r"20(1[2-9]|2[0-5])", val)
        if m:
            return int(m.group(0))
    title = str(item.get("title", ""))
    m = re.search(r"20(1[2-9]|2[0-5])", title)
    if m:
        return int(m.group(0))
    return None


def _extract_year_from_url(url: str) -> Optional[int]:
    m = re.search(r"20(1[2-9]|2[0-5])", url)
    return int(m.group(0)) if m else None


def _extract_pdf_url(item: Dict) -> Optional[str]:
    """Extrae la URL del PDF del item."""
    for field in ["pdf_url", "document_url", "file_url", "url", "link"]:
        val = item.get(field, "")
        if val and (".pdf" in val.lower() or "irpages2.eqs.com" in val):
            return val
    # Buscar en attachments/documents
    for att_key in ["attachments", "documents", "files"]:
        atts = item.get(att_key, [])
        if isinstance(atts, list):
            for att in atts:
                if isinstance(att, dict):
                    url = att.get("url", att.get("file", ""))
                    if url and ".pdf" in url.lower():
                        return url
    return None


async def download_report(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    entry: Dict,
    stats: Dict,
) -> bool:
    """Descarga un PDF a D:/ARGOS_DATA/raw/DE_BAFIN/{year}/"""
    year = entry["year"]
    ticker = entry["ticker"]
    url = entry["url"]

    year_dir = DATA_ROOT / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)

    # Nombre de archivo: TICKER_EQS_YEAR.pdf
    safe_name = re.sub(r"[^\w\-]", "_", f"{ticker}_EQS_{year}")
    ext = ".pdf"
    out_path = year_dir / f"{safe_name}{ext}"
    meta_path = year_dir / f"{safe_name}{ext}.meta.json"

    if out_path.exists():
        stats["skipped"] += 1
        return False

    async with sem:
        try:
            async with client.stream("GET", url, timeout=TIMEOUT_DOWNLOAD) as resp:
                if resp.status_code not in (200, 206):
                    stats["failed"] += 1
                    return False
                content_type = resp.headers.get("content-type", "")
                if "html" in content_type and ".pdf" in url:
                    # Redirigido a HTML, skip
                    stats["failed"] += 1
                    return False

                with open(out_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        f.write(chunk)

            # Verificar tamaño mínimo (un PDF válido es >10KB)
            size = out_path.stat().st_size
            if size < 10_000:
                out_path.unlink(missing_ok=True)
                stats["failed"] += 1
                return False

            # SHA-256 meta
            sha = sha256_file(out_path)
            meta = {
                "ticker": ticker,
                "isin": entry.get("isin", ""),
                "year": year,
                "url": url,
                "title": entry.get("title", ""),
                "source": entry.get("source", "eqs_news"),
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "size_bytes": size,
                "sha256": sha,
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            stats["downloaded"] += 1
            log.info(f"[OK] {ticker} {year} -> {out_path.name} ({size/1024:.0f} KB)")
            return True

        except Exception as e:
            out_path.unlink(missing_ok=True)
            stats["failed"] += 1
            log.debug(f"[FAIL] {ticker} {year} {url}: {e}")
            return False


async def main():
    log.info("=== EQS News Crawler - Fase 2 ===")
    log.info(f"Universo: {UNIVERSE_FILE}")
    log.info(f"Destino: {DATA_ROOT}")

    companies = load_universe()
    total_cos = len(companies)
    log.info(f"Empresas en universo: {total_cos}")

    # Filtrar foráneas sin obligación DE (no-DE ISIN, no dual-listed)
    DUAL_LISTED = {"NL0000235190", "IE000S9YS762"}
    cos_filtered = {
        t: c for t, c in companies.items()
        if not c.get("isin") or c.get("isin","").startswith("DE") or c.get("isin","") in DUAL_LISTED
    }
    log.info(f"Empresas activas (excl. foraneas): {len(cos_filtered)}")

    transport = httpx.AsyncHTTPTransport(retries=2)
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)

    async with httpx.AsyncClient(
        headers=BASE_HEADERS,
        follow_redirects=True,
        limits=limits,
        transport=transport,
    ) as client:

        # ── Fase 2a: Discovery de links en EQS News ─────────────────────────
        log.info("\n[Fase 2a] Buscando informes anuales en EQS News...")
        sem_search = asyncio.Semaphore(CONCURRENCY_SEARCH)

        tasks = [
            search_eqs_news_for_company(client, sem_search, ticker, company)
            for ticker, company in cos_filtered.items()
        ]

        all_discovered = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            results = await coro
            all_discovered.extend(results)
            done += 1
            if done % 50 == 0:
                log.info(f"  Buscados: {done}/{len(cos_filtered)} | Encontrados: {len(all_discovered)}")

        log.info(f"\n[Discovery] Total links encontrados: {len(all_discovered)}")

        # Deduplicar por (ticker, year, url)
        seen = set()
        unique = []
        for entry in all_discovered:
            key = (entry["ticker"], entry["year"], entry["url"])
            if key not in seen:
                seen.add(key)
                unique.append(entry)

        log.info(f"[Discovery] Únicos tras deduplicar: {len(unique)}")

        # Guardar catálogo de descubrimiento
        OUTPUT_DISCOVERED.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_DISCOVERED, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "total": len(unique),
                "items": unique,
            }, f, indent=2, ensure_ascii=False)
        log.info(f"[Discovery] Catálogo guardado: {OUTPUT_DISCOVERED}")

        if not unique:
            log.warning("No se encontraron links. Verificar acceso a eqs-news.com")
            log.info("Intentando fallback directo con ISINs conocidos...")
            # Fallback: probar directamente la URL patrón de irpages2.eqs.com
            await _run_fallback_eqs_direct(client, cos_filtered)
            return

        # ── Fase 2b: Descarga de PDFs ────────────────────────────────────────
        log.info(f"\n[Fase 2b] Descargando {len(unique)} PDFs...")
        sem_dl = asyncio.Semaphore(CONCURRENCY_DOWNLOAD)
        stats = {"downloaded": 0, "skipped": 0, "failed": 0}

        dl_tasks = [
            download_report(client, sem_dl, entry, stats)
            for entry in unique
        ]

        done_dl = 0
        for coro in asyncio.as_completed(dl_tasks):
            await coro
            done_dl += 1
            if done_dl % 25 == 0:
                log.info(f"  Descargados: {stats['downloaded']} | Skip: {stats['skipped']} | Fail: {stats['failed']}")

    log.info("\n=== RESUMEN FINAL ===")
    log.info(f"  Descargados:  {stats['downloaded']}")
    log.info(f"  Ya existían:  {stats['skipped']}")
    log.info(f"  Fallidos:     {stats['failed']}")


async def _run_fallback_eqs_direct(client: httpx.AsyncClient, cos: Dict):
    """
    Fallback: construye URLs directas al CDN irpages2.eqs.com usando
    el patrón conocido y prueba con HEAD request.
    """
    log.info("[Fallback] Probando URLs directas irpages2.eqs.com por ISIN...")
    YEARS_TO_TRY = list(range(2015, 2026))
    found = 0
    stats = {"downloaded": 0, "skipped": 0, "failed": 0}
    sem_dl = asyncio.Semaphore(15)

    for ticker, company in list(cos.items())[:200]:  # primeras 200 por fallback
        isin = company.get("isin", "") or ""
        if not isin.startswith("DE"):
            continue
        name_slug = re.sub(r"[^\w]", "", company.get("name_common", ticker))

        for year in YEARS_TO_TRY:
            for lang in ["de", "en"]:
                candidates = [
                    f"https://irpages2.eqs.com/websites/{isin}/German/2201010/gesch%C3%A4ftsbericht-{year}.pdf",
                    f"https://irpages2.eqs.com/websites/{isin}/English/2201010/annual-report-{year}.pdf",
                    f"https://irpages2.eqs.com/Download.aspx?ID={isin}_{year}_{lang.upper()}.pdf",
                ]
                for url in candidates:
                    try:
                        r = await client.head(url, timeout=7.0)
                        if r.status_code in (200, 206):
                            entry = {
                                "ticker": ticker,
                                "isin": isin,
                                "year": year,
                                "url": url,
                                "title": f"Annual Report {year}",
                                "source": "eqs_direct_fallback",
                            }
                            ok = await download_report(client, sem_dl, entry, stats)
                            if ok:
                                found += 1
                            break
                    except Exception:
                        pass

    log.info(f"[Fallback] Descargados por URL directa: {found}")


if __name__ == "__main__":
    asyncio.run(main())
