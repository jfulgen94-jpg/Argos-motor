"""
DOWNLOADER INSTITUCIONAL ALEMANIA (BAFIN / ESEF / UNTERNEHMENSREGISTER / BUNDESANZEIGER) — ARGOS MOTOR
Conector multicanal institucional para la adquisición y sellado criptográfico de cuentas anuales auditadas de Alemania (2012–2025).
"""

import os
import sys
import json
import time
import re
import hashlib
import argparse
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass

CONFIG_PATH = Path(__file__).parent / 'config_de.json'
UNIVERSE_PATH = Path(__file__).resolve().parents[2] / 'config' / 'master_universe_de.json'

DEFAULT_YEARS = [2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        "canonical_raw_path": "D:/ARGOS_DATA/raw/DE_BAFIN",
        "fallback_raw_path": "ARGOS_MOTOR/data/raw/DE_BAFIN",
        "staging_path": "D:/ARGOS_DATA/staging",
        "rate_limit": {"delay_between_requests_seconds": 1.0, "concurrent_downloads": 3},
        "retry_policy": {"max_retries": 3, "backoff_factor": 5},
        "user_agent": "ARGOS-Institutional-Data-Auditor/1.0 (Compliance; Regulatory Research)"
    }

def calculate_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def check_magic_bytes(filepath):
    if not filepath.exists() or filepath.stat().st_size == 0:
        return 'EMPTY'
    with open(filepath, 'rb') as f:
        header = f.read(1024)
    if header.startswith(b'PK\x03\x04'):
        return 'ZIP_ESEF'
    if header.startswith(b'%PDF'):
        return 'PDF'
    header_lower = header.lower()
    if b'<!doctype html' in header_lower or b'<html' in header_lower or b'<?xml' in header_lower:
        return 'HTML_XHTML'
    return 'UNKNOWN'

BOILERPLATE_HASHES = {
    "3f418fa15253013f4dc73620d471cb567e0f2e1b46f7981c71ffff427ff6ff6b",
    "2ac7a66b8489ec150d1feef7759323851317657b1a6ebbc8d18faf7618171552",
}

REJECTION_SIGNATURES = [
    b'__NEXT_DATA__', b'/_next/static/', b'Sicherheitsabfrage',
    b'captcha~panel-captcha', b'Zeichen eingeben', b'Ich bin ein Mensch',
    b'suchergebnis',
]

FINANCIAL_KEYWORDS = [
    'Aktiva', 'Passiva', 'TEUR', 'Eigenkapital', 'Bilanzsumme',
    'Jahresueberschuss', 'Konzernjahresergebnis', 'Jahresuberschuss',
    'Gewinn- und Verlustrechnung', 'Konzernabschluss', 'Jahresabschluss'
]

def is_valid_financial_document(filepath: Path) -> tuple:
    if not filepath.exists():
        return False, "Fichero no existe"
    size = filepath.stat().st_size
    if size < 5000:
        return False, f"Fichero demasiado pequeño ({size} bytes)"
    
    sha256 = calculate_sha256(filepath)
    if sha256 in BOILERPLATE_HASHES:
        return False, f"Hash boilerplate conocido ({sha256[:12]})"

    content = filepath.read_bytes()
    if content.startswith(b'PK\x03\x04'):
        return True, f"Paquete ZIP ESEF válido ({size:,} bytes)"

    if content.startswith(b'%PDF'):
        return True, f"PDF válido ({size:,} bytes)"

    probe = content[:8192] + content[-4096:]
    for sig in REJECTION_SIGNATURES:
        if sig in probe:
            return False, f"Firma de rechazo / CAPTCHA detectada: {sig[:30]!r}"

    # Para documentos HTML/XHTML: verificación contable obligatoria
    content_lower = content.lower()
    hits = sum(1 for k in FINANCIAL_KEYWORDS
               if k.lower().encode('utf-8') in content_lower or k.lower().encode('latin-1') in content_lower)
    if hits < 2:
        return False, f"Solo {hits} keywords financieros encontrados (mínimo 2 requeridos)"

    return True, f"Documento financiero válido ({hits} keywords, {size:,} bytes)"

def load_master_universe():
    if UNIVERSE_PATH.exists():
        data = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8'))
        return data.get('companies', {})
    return {}

class GermanyDownloader:
    def __init__(self, segment=None, dry_run=False, max_workers=None, tickers=None):
        self.config = load_config()
        self.dry_run = dry_run
        self.segment = None if (segment is None or segment.strip().upper() == 'ALL') else segment
        self.tickers = tickers

        # Detección de ruta canónica de almacenamiento
        canonical = Path(self.config.get('canonical_raw_path', 'D:/ARGOS_DATA/raw/DE_BAFIN'))
        if canonical.parent.exists():
            self.raw_base = canonical
        else:
            self.raw_base = Path(self.config.get('fallback_raw_path', 'ARGOS_MOTOR/data/raw/DE_BAFIN'))
        self.raw_base.mkdir(parents=True, exist_ok=True)

        staging_cfg = Path(self.config.get('staging_path', 'D:/ARGOS_DATA/staging'))
        if staging_cfg.parent.exists():
            self.staging_dir = staging_cfg / f"de_run_{time.strftime('%Y%m%d_%H%M%S')}"
        else:
            self.staging_dir = Path("ARGOS_MOTOR/data/staging/tmp_download") / f"de_run_{time.strftime('%Y%m%d_%H%M%S')}"

        self.universe = load_master_universe()
        max_conn = max_workers or self.config.get('rate_limit', {}).get('concurrent_downloads', 3)
        self.semaphore = asyncio.Semaphore(max_conn)
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": self.config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'),
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            limits=httpx.Limits(max_connections=max_conn, max_keepalive_connections=max_conn),
            timeout=httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0),
            follow_redirects=True
        )
        self.esef_index = {}
        self.ureg_token = None
        self.ureg_token_expires = 0
        self.ba_offline_until = 0
        self.token_lock = asyncio.Lock()

    async def load_esef_central_index(self):
        """Carga y cachea el índice central europeo filings.xbrl.org/index.json"""
        index_cache_file = Path("scratch/esef_index.json")
        data = None
        if index_cache_file.exists() and (time.time() - index_cache_file.stat().st_mtime) < 86400:
            try:
                data = json.loads(index_cache_file.read_text(encoding='utf-8'))
                print(f"  -> [Caché Local] Índice ESEF cargado ({len(data)} entidades).")
            except Exception:
                pass

        if not data:
            print("  -> Descargando índice central europeo ESEF (filings.xbrl.org/index.json)...")
            try:
                resp = await self.client.get("https://filings.xbrl.org/index.json", timeout=30.0)
                if resp.status_code == 200:
                    data = resp.json()
                    index_cache_file.parent.mkdir(parents=True, exist_ok=True)
                    index_cache_file.write_text(json.dumps(data), encoding='utf-8')
                    print(f"  -> [OK] Índice ESEF indexado y guardado en caché local ({len(data)} entidades).")
            except Exception as e:
                print(f"  -> [Aviso] No se pudo descargar index.json de XBRL.org: {e}")
                data = {}

        # Mapear por LEI y Año
        self.esef_index = {}
        for lei, ent in (data or {}).items():
            filings = ent.get('filings', {})
            for f_key, f_val in filings.items():
                dt = f_val.get('date', '')
                yr_str = dt[:4] if dt else ''
                pkg = f_val.get('report-package', '')
                if yr_str.isdigit() and pkg:
                    y = int(yr_str)
                    k = (lei.upper(), y)
                    self.esef_index[k] = {
                        'url': f"https://filings.xbrl.org/{f_key}/{pkg}",
                        'sha256': f_val.get('sha256sum', ''),
                        'date': dt,
                        'pkg': pkg
                    }
        print(f"  -> Filings ESEF mapeados en índice europeo: {len(self.esef_index)} registros.")

    async def get_ureg_search_token(self):
        """Obtiene un token válido de búsqueda para Unternehmensregister de forma segura entre corrutinas"""
        if self.ureg_token and time.time() * 1000 < self.ureg_token_expires - 60000:
            return self.ureg_token
        if time.time() * 1000 < self.ureg_token_expires:
            return None
        async with self.token_lock:
            if self.ureg_token and time.time() * 1000 < self.ureg_token_expires - 60000:
                return self.ureg_token
            if time.time() * 1000 < self.ureg_token_expires:
                return None
            try:
                r = await self.client.get("https://www.unternehmensregister.de/api/search-token", timeout=10.0)
                if r.status_code == 200:
                    data = r.json()
                    self.ureg_token = data.get('token')
                    self.ureg_token_expires = data.get('expiresAt', 0)
                    return self.ureg_token
            except Exception as e:
                err_type = type(e).__name__
                print(f"  [Info] Portal UREG no disponible ({err_type}) - pausa 60s")
                self.ureg_token_expires = (time.time() + 60) * 1000
            return None

    async def query_channel_b_filing(self, comp, year):
        """Canal B: Unternehmensregister / Bundesanzeiger para informes 2012-2025"""
        name_common = comp.get('name_common', '')
        name_legal = comp.get('name_legal', '')
        ticker = comp.get('ticker', '')

        # Extraer nombre base para búsqueda insensible a cambios de forma societaria (AG a SE)
        search_query = name_common if name_common else re.sub(r'\b(SE|AG|GmbH|KGaA|Co\.\s*KG)\b', '', name_legal).strip()
        if not search_query:
            search_query = ticker

        # 1. Búsqueda en Unternehmensregister con ventana temporal del ejercicio (sourceDateFrom / sourceDateTo)
        token = await self.get_ureg_search_token()
        if token:
            try:
                date_from = f"{year}-01-01"
                date_to = f"{year+1}-12-31"
                url = f"https://www.unternehmensregister.de/de/suche?companyName={quote_plus(search_query)}&searchToken={token}&formType=ACCOUNTING&sourceDateFrom={date_from}&sourceDateTo={date_to}"
                r = await self.client.get(url, timeout=25.0)
                if r.status_code == 200:
                    pattern = re.compile(
                        r'\\"sourceName\\":\\"(?P<source>.*?)\\",\\"sourceDate\\":\\"(?P<date>.*?)\\",\\"title\\":\\"(?P<title>.*?)\\".*?'
                        r'\\"encryptedPayload\\":\\"(?P<payload>[^\\"]+)\\"',
                        re.DOTALL
                    )
                    yr_str = str(year)
                    for m in pattern.finditer(r.text):
                        d = m.groupdict()
                        title = d['title']
                        title_lower = title.lower()
                        src = d['source']
                        is_annual = any(k in title_lower for k in ['jahresabschluss', 'konzernabschluss', 'jahresfinanzbericht', 'finanzbericht', 'geschäftsbericht'])
                        if yr_str in title and is_annual:
                            if title_lower.startswith('hinweis auf'):
                                continue
                            if src.startswith('http') and ('.pdf' in src.lower() or 'download' in src.lower()):
                                return {
                                    "url": src,
                                    "format": "PDF",
                                    "title": title,
                                    "source": "Unternehmensregister"
                                }
                            elif d.get('payload'):
                                pub_url = f"https://www.unternehmensregister.de/publication?payload={d['payload']}"
                                return {
                                    "url": pub_url,
                                    "format": "HTML_XHTML",
                                    "title": title,
                                    "source": "Unternehmensregister"
                                }
            except Exception:
                pass

        # 2. Fallback: Bundesanzeiger con sesión y Área 22
        if time.time() < self.ba_offline_until:
            return None
        try:
            r_home = await self.client.get("https://www.bundesanzeiger.de/pub/de/start", timeout=10.0)
            if r_home.status_code == 200:
                soup_home = BeautifulSoup(r_home.text, 'html.parser')
                form = [f for f in soup_home.find_all('form') if f.get('method') == 'get']
                if form:
                    action = form[0].get('action', 'https://www.bundesanzeiger.de/pub/de/start')
                    params = {
                        '0-1.-top~content~panel-left~card-form': '',
                        'fulltext': f"{search_query} {year}",
                        'area_select': '22',
                        'search_button': 'Suchen'
                    }
                    r_ba = await self.client.get(action, params=params, timeout=15.0)
                    if r_ba.status_code == 200:
                        soup_ba = BeautifulSoup(r_ba.text, 'html.parser')
                        pub_links = soup_ba.find_all('a', href=lambda h: h and 'search~table~row~panel-publication~link' in h)
                        yr_str = str(year)
                        for a in pub_links:
                            txt = a.text.strip()
                            txt_lower = txt.lower()
                            is_annual = any(k in txt_lower for k in ['jahresabschluss', 'konzernabschluss', 'finanzbericht', 'geschäftsbericht'])
                            if yr_str in txt and is_annual:
                                href = a['href']
                                return {
                                    "url": href,
                                    "format": "HTML_XHTML",
                                    "title": txt,
                                    "source": "Bundesanzeiger"
                                }
        except Exception:
            self.ba_offline_until = time.time() + 60

        return None

    def get_target_companies(self):
        comps = list(self.universe.values())
        if self.tickers:
            target_tickers = [t.strip().upper() for t in self.tickers.split(',') if t.strip()]
            comps = [c for c in comps if (
                c.get('ticker', '').upper() in target_tickers or
                c.get('ticker', '').upper().replace('DE_', '') in target_tickers or
                c.get('name_common', '').upper() in target_tickers
            )]
        if self.segment:
            segments = [s.strip().upper() for s in self.segment.split(',')]
            filtered = []
            for c in comps:
                c_seg = c.get('segment', '').upper()
                c_indices = [i.upper() for i in c.get('index_membership', [])]
                if any(s in c_seg for s in segments) or any(s in c_indices for s in segments):
                    filtered.append(c)
            return filtered
        return comps

    async def discover_and_download_async(self, years=DEFAULT_YEARS):
        await self.load_esef_central_index()
        companies = self.get_target_companies()

        print("\n=========================================================================")
        print("=== INICIANDO DESCARGA INSTITUCIONAL ALEMANIA (BAFIN / ESEF / UREG) ===")
        print("=========================================================================")
        print(f"Directorio Canónico Base: {self.raw_base.resolve()}")
        print(f"Empresas en Universo:     {len(companies)} (Filtro Segmento: {self.segment or 'TODOS'})")
        print(f"Ejercicios Fiscales:      {years}")
        print("=========================================================================\n")

        if not self.dry_run:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            self.raw_base.mkdir(parents=True, exist_ok=True)

        all_results = []
        chunk_size = 10
        for year in years:
            print(f"\n>>> [AÑO {year}] Iniciando escaneo e ingesta ({len(companies)} sociedades)...")
            year_results = []
            for i in range(0, len(companies), chunk_size):
                chunk = companies[i:i+chunk_size]
                chunk_tasks = [self.download_filing(comp, year) for comp in chunk]
                chunk_res = await asyncio.gather(*chunk_tasks)
                year_results.extend(chunk_res)
                if i + chunk_size < len(companies):
                    await asyncio.sleep(0.5)

            all_results.extend(year_results)

            if not self.dry_run:
                self.generate_manifest(year, year_results)

        await self.client.aclose()
        return all_results

    async def download_filing(self, comp, year):
        ticker = comp['ticker']
        lei = comp.get('lei', '')
        name = comp.get('name_legal', comp.get('name_common', ticker))
        segment = comp.get('segment', 'DE')
        hrb = comp.get('hrb_reg', '')

        tax_id = hrb.replace(' ', '_') if hrb else lei
        tax_id = re.sub(r'[^A-Za-z0-9_\-]', '_', tax_id) if tax_id else "UNKNOWN"
        comp_dir = self.raw_base / str(year) / f"{tax_id}_{ticker}"

        # 1. Comprobación de Caché Inmutable (en comp_dir o carpetas previas {ticker}_*)
        candidate_dirs = [comp_dir]
        year_dir = self.raw_base / str(year)
        if year_dir.exists():
            for d in year_dir.iterdir():
                if d.is_dir() and (d.name == f"{tax_id}_{ticker}" or d.name.endswith(f"_{ticker}") or d.name.startswith(f"{ticker}_")):
                    if d not in candidate_dirs:
                        candidate_dirs.append(d)

        for target_dir in candidate_dirs:
            if not target_dir.exists():
                continue
            for c_file in target_dir.iterdir():
                if c_file.is_file() and c_file.stat().st_size > 1000:
                    ext_l = c_file.suffix.lower()
                    if ext_l in ['.zip', '.pdf', '.html', '.htm']:
                        valid, reason = is_valid_financial_document(c_file)
                        if not valid:
                            c_file.unlink(missing_ok=True)
                            c_file.with_suffix('.meta.json').unlink(missing_ok=True)
                            continue
                        c_fmt = 'ZIP_ESEF' if ext_l == '.zip' else ('PDF' if ext_l == '.pdf' else 'HTML_XHTML')
                        sha = calculate_sha256(c_file)
                        canonical_meta = c_file.with_suffix('.meta.json')
                        if canonical_meta.exists():
                            try:
                                meta = json.loads(canonical_meta.read_text(encoding='utf-8'))
                                if meta.get('sha256') == sha:
                                    return {
                                        "status": "cache_hit", "ticker": ticker, "year": year,
                                        "file_path": str(c_file), "sha256": sha,
                                        "byte_size": c_file.stat().st_size, "format": c_fmt
                                    }
                            except Exception:
                                pass
                        # Generar meta si falta
                        meta = {
                            "file_name": c_file.name,
                            "sha256": sha,
                            "byte_size": c_file.stat().st_size,
                            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                            "source_url": "CACHE_LOCAL",
                            "reporting_year": year,
                            "ticker": ticker,
                            "legal_name": name,
                            "lei": lei,
                            "hrb_reg": hrb,
                            "segment": segment,
                            "magic_mime_verified": c_fmt
                        }
                        canonical_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
                        return {
                            "status": "cache_hit", "ticker": ticker, "year": year,
                            "file_path": str(c_file), "sha256": sha,
                            "byte_size": c_file.stat().st_size, "format": c_fmt
                        }

        if self.dry_run:
            esef_hit = (lei.upper(), year) in self.esef_index if lei else False
            status_str = "DISPONIBLE_ESEF" if esef_hit else "CANAL_B_BUNDESANZEIGER"
            print(f"[DRY-RUN] [{segment}] {ticker:<6} | {name[:26]:<26} (LEI: {lei[:10]}...) | Año {year} -> {status_str}")
            return {"status": "dry_run", "ticker": ticker, "year": year, "esef_available": esef_hit}

        # 2. Operaciones de Red (Canal A y Canal B) protegidas por Semáforo de Concurrencia
        async with self.semaphore:
            # Canal A: ESEF Central Repository (Años >= 2020)
            if year >= 2020:
                esef_info = self.esef_index.get((lei.upper(), year)) if lei else None
                if esef_info:
                    pkg_url = esef_info['url']
                    res = await self.download_and_process(pkg_url, comp, year, "ESEF", official_sha=esef_info.get('sha256'))
                    await asyncio.sleep(self.config.get('rate_limit', {}).get('delay_between_requests_seconds', 1.0))
                    return res

            # Canal B: Unternehmensregister / Bundesanzeiger (2012–2025)
            channel_b_res = await self.query_channel_b_filing(comp, year)
            if channel_b_res:
                tag = "ANUAL"
                res = await self.download_and_process(channel_b_res['url'], comp, year, tag, expected_format=channel_b_res.get('format'))
                await asyncio.sleep(self.config.get('rate_limit', {}).get('delay_between_requests_seconds', 1.0))
                return res

            await asyncio.sleep(0.3)
            return {"status": "not_found", "ticker": ticker, "year": year}

    async def download_and_process(self, url, comp, year, tag, official_sha="", expected_format=None):
        ticker = comp['ticker']
        lei = comp.get('lei', '')
        name = comp.get('name_legal', comp.get('name_common', ticker))
        hrb = comp.get('hrb_reg', '')
        segment = comp.get('segment', 'DE')

        tax_id = hrb.replace(' ', '_') if hrb else lei
        tax_id = re.sub(r'[^A-Za-z0-9_\-]', '_', tax_id) if tax_id else "UNKNOWN"
        comp_dir = self.raw_base / str(year) / f"{tax_id}_{ticker}"

        for attempt in range(self.config.get('retry_policy', {}).get('max_retries', 3)):
            try:
                async with self.client.stream("GET", url, timeout=90) as resp:
                    if resp.status_code == 200:
                        tmp_file = self.staging_dir / f"de_{ticker}_{year}_{tag}.bin"
                        with open(tmp_file, 'wb') as f:
                            async for chunk in resp.aiter_bytes(chunk_size=65536):
                                f.write(chunk)

                        magic = check_magic_bytes(tmp_file)
                        valid, reason = is_valid_financial_document(tmp_file)
                        if not valid:
                            if tmp_file.exists(): tmp_file.unlink()
                            print(f"  [-] Rechazado ({reason}) para {ticker} {year}")
                            return {"status": "rejected_boilerplate", "ticker": ticker, "year": year, "reason": reason}

                        comp_dir.mkdir(parents=True, exist_ok=True)
                        if magic == 'ZIP_ESEF': ext = ".zip"
                        elif magic == 'PDF': ext = ".pdf"
                        else: ext = ".html"

                        dest_file = comp_dir / f"{ticker}_{year}_{tag}{ext}"
                        if dest_file.exists():
                            dest_file.unlink()
                        tmp_file.replace(dest_file)

                        sha = calculate_sha256(dest_file)
                            meta = {
                                "file_name": dest_file.name,
                                "sha256": sha,
                                "byte_size": dest_file.stat().st_size,
                                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                                "source_url": url,
                                "reporting_year": year,
                                "ticker": ticker,
                                "legal_name": name,
                                "lei": lei,
                                "hrb_reg": hrb,
                                "segment": segment,
                                "magic_mime_verified": magic
                            }
                            meta_dest = comp_dir / f"{ticker}_{year}_{tag}.meta.json"
                            meta_dest.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
                            print(f"  [OK] Descargado y sellado: {dest_file.name} ({round(dest_file.stat().st_size/1024/1024, 2)} MB) | SHA: {sha[:12]}...")
                            await asyncio.sleep(self.config.get('rate_limit', {}).get('delay_between_requests_seconds', 1.0))
                            return {
                                "status": "downloaded", "ticker": ticker, "year": year,
                                "file_path": str(dest_file), "sha256": sha,
                                "byte_size": dest_file.stat().st_size, "format": magic
                            }
                        else:
                            if tmp_file.exists(): tmp_file.unlink()
                            print(f"  [-] Archivo corrupto o no reconocido ({magic}) para {ticker} {year}")
                            return {"status": "quarantined", "ticker": ticker, "year": year}
                    elif resp.status_code in [429, 503]:
                        backoff = self.config.get('retry_policy', {}).get('backoff_factor', 5) * (attempt + 1)
                        print(f"  [429/503 Rate limit] {ticker} {year}. Esperando {backoff}s...")
                        await asyncio.sleep(backoff)
                    else:
                        break
            except Exception as e:
                print(f"  [Error descarga {ticker} {year} intento {attempt+1}]: {e}")
                await asyncio.sleep(2)

        return {"status": "failed", "ticker": ticker, "year": year}

    def generate_manifest(self, year, results):
        manifest = {
            "year": year,
            "country": "DE",
            "supervisor": "BaFin",
            "oam": "Unternehmensregister / Bundesanzeiger / ESEF",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "total_mapped": len(self.universe),
            "downloaded": 0,
            "cache_hits": 0,
            "failed": 0,
            "quarantined": 0,
            "manifest": []
        }

        for res in results:
            if res and res.get('year') == year:
                if res['status'] == 'cache_hit':
                    manifest['cache_hits'] += 1
                elif res['status'] == 'downloaded':
                    manifest['downloaded'] += 1
                elif res['status'] == 'quarantined':
                    manifest['quarantined'] += 1
                elif res['status'] == 'failed':
                    manifest['failed'] += 1

                if res['status'] in ['cache_hit', 'downloaded']:
                    doc_tag = "ESEF_PACKAGE" if res.get('format') == 'ZIP_ESEF' else "ANNUAL_AUDITED_REPORT"
                    manifest['manifest'].append({
                        "ticker": res['ticker'],
                        "year": year,
                        "doc_type": doc_tag,
                        "status": res['status'].upper(),
                        "sha256": res['sha256'],
                        "size_bytes": res['byte_size'],
                        "path": res['file_path']
                    })

        manifest_path = self.raw_base / f"MANIFEST_BAFIN_{year}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"[MANIFEST] Manifiesto anual {year} guardado en: {manifest_path} (Hits: {manifest['cache_hits']}, Descargas: {manifest['downloaded']})")

        # Copia de seguridad en audits/manifests y cloud/audits/manifests para versionado Git
        for backup_dir in [Path("audits/manifests"), Path("ARGOS_MOTOR/cloud/audits/manifests"), Path("ARGOS_MOTOR/audits/manifests")]:
            try:
                backup_dir.mkdir(parents=True, exist_ok=True)
                (backup_dir / f"MANIFEST_BAFIN_{year}.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
            except Exception:
                pass

BafinDownloaderV2 = GermanyDownloader

def main():
    parser = argparse.ArgumentParser(description="Downloader Institucional Alemania (BaFin / ESEF / Unternehmensregister / Bundesanzeiger)")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar")
    parser.add_argument('--tickers', type=str, default=None, help="Filtrar por tickers específicos (ej. SAP,ADS,BMW)")
    parser.add_argument('--segment', type=str, default=None, help="Filtrar por índice: DAX40, MDAX, SDAX, PRIME_STANDARD")
    parser.add_argument('--years', type=str, default=",".join(map(str, DEFAULT_YEARS)), help="Años a consultar separados por coma (ej. 2012-2025)")
    parser.add_argument('--max-workers', type=int, default=3, help="Conexiones concurrentes máximas")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    downloader = GermanyDownloader(segment=args.segment, dry_run=args.dry_run, max_workers=args.max_workers, tickers=args.tickers)
    asyncio.run(downloader.discover_and_download_async(years=years))

if __name__ == '__main__':
    main()

