"""
==============================================================================
ARGOS MOTOR — DOWNLOADER INSTITUCIONAL FRANCIA v3.0.0
==============================================================================
Jurisdicción: Francia (FR) — Autorité des Marchés Financiers (AMF)
Almacenamiento Canónico Local: D:/ARGOS_DATA/raw/FR_AMF

Arquitectura Multicanal de Ingestión:
  - Canal 1: ESEF Oficial (filings.xbrl.org API / Índice Central Europeo, 2020-2026)
  - Canal 2: AMF BDIF API (bdif.amf-france.org, 2012-2025 para URD y Document de Référence)
  - Canal 3: Recherche Entreprises API (recherche-entreprises.api.gouv.fr / INPI / RNE)
             para enriquecimiento registral oficial (SIREN, facturación, resultado neto)
  - Canal 4: Euronext Paris / Info-Financière OAM Fallback

Garantías de Integridad Institucional:
  - Sellado criptográfico SHA-256 estricto.
  - Validación de Magic Bytes (%PDF, PK\\x03\\x04 ZIP ESEF, HTML/XHTML).
  - Sidecar de auditoría companion *.meta.json para cada archivo.
  - Generación de MANIFEST_AMF_{year}.json por ejercicio fiscal.
==============================================================================
"""

import os
import sys
import json
import time
import re
import hashlib
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

# Reconfiguración UTF-8 en Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass

VERSION = "3.0.0"
CONFIG_PATH = Path(__file__).parent / 'config_fr.json'
BDIF_BASE = "https://bdif.amf-france.org"
BDIF_API_SEARCH = f"{BDIF_BASE}/back/api/v1/informations"
BDIF_API_DOC = f"{BDIF_BASE}/back/api/v1/documents"
XBRL_API = "https://filings.xbrl.org/api/filings"
GOUV_API = "https://recherche-entreprises.api.gouv.fr/search"

# Spin-offs o incorporaciones conocidas
SPINOFF_INCEPTION_FR = {
    'FDJ': 2019,
    'ALVIV': 2021,
    'PLUX': 2024,
    'OVH': 2021,
}

# --- Resolución Automática de Rutas Canónicas ---

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        "jurisdiction": "FR",
        "canonical_raw_path": "D:/ARGOS_DATA/raw/FR_AMF",
        "fallback_raw_path": "ARGOS_MOTOR/data/raw/FR_AMF",
        "staging_path": "D:/ARGOS_DATA/staging",
        "user_agent": "ARGOS-Institutional-Data-Auditor/3.0 (Compliance; Regulatory Research)"
    }


def resolve_data_root(override_path: Optional[str] = None) -> Path:
    if override_path:
        p = Path(override_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    cfg = load_config()
    canonical_cfg = cfg.get("canonical_raw_path", "D:/ARGOS_DATA/raw/FR_AMF")

    # 1. Prioridad absoluta local: Disco D: si está disponible en Windows
    if os.path.exists("D:/") or Path("D:/").exists():
        primary_d = Path(canonical_cfg)
        primary_d.mkdir(parents=True, exist_ok=True)
        return primary_d

    # 2. Variable de entorno explícita (para contenedores cloud / Qwen Coder / OpenHands)
    env_root = os.environ.get("ARGOS_DATA_ROOT", "")
    if env_root:
        p_env = Path(env_root) / "raw" / "FR_AMF" if "raw" not in env_root else Path(env_root)
        p_env.mkdir(parents=True, exist_ok=True)
        return p_env

    # 3. Fallbacks secundarios para contenedores Linux
    candidates = [
        Path("/opt/argos_data/raw/FR_AMF"),
        Path("ARGOS_DATA_DISK/raw/FR_AMF"),
        Path("ARGOS_MOTOR/data/raw/FR_AMF"),
    ]
    for c in candidates:
        if c.exists():
            return c

    p = Path(__file__).resolve().parents[2] / "data" / "raw" / "FR_AMF"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_staging_dir(data_root: Path) -> Path:
    if "D:" in str(data_root):
        staging = Path("D:/ARGOS_DATA/staging/tmp_download_fr")
    else:
        staging = data_root.parent.parent / "staging" / "tmp_download_fr"
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def resolve_universe() -> Dict[str, Any]:
    candidates = [
        Path(__file__).resolve().parents[2] / "config" / "master_universe_fr.json",
        Path("ARGOS_MOTOR/config/master_universe_fr.json"),
        Path("/opt/workspace_base/ARGOS_MOTOR/config/master_universe_fr.json"),
        Path("C:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/config/master_universe_fr.json"),
    ]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                return data.get("companies", {})
            except Exception as e:
                print(f"[!] Error leyendo {p}: {e}")
    raise FileNotFoundError("master_universe_fr.json no encontrado")


# --- Funciones Criptográficas y de Integridad ---

def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_magic_bytes(filepath: Path) -> str:
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


# --- Verificación de Caché Local ---

def check_local_cache(data_root: Path, ticker: str, name_legal: str, year: int) -> Optional[Dict[str, Any]]:
    year_dir = data_root / str(year)
    if not year_dir.exists():
        return None

    tick_lower = ticker.lower()
    safe_name = "".join(c for c in name_legal if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_').lower()

    # Buscar carpetas que coincidan con ticker o nombre de empresa
    for cdir in year_dir.iterdir():
        if not cdir.is_dir():
            continue
        c_name = cdir.name.lower()
        if (c_name.startswith(f"{tick_lower}_") or 
            c_name.endswith(f"_{tick_lower}") or 
            c_name == tick_lower or
            safe_name in c_name or
            c_name in safe_name):
            
            # Buscar archivo primario
            for f in cdir.iterdir():
                if f.is_file() and not f.name.endswith(".meta.json"):
                    ext = f.suffix.lower()
                    if ext in ['.zip', '.pdf', '.xhtml', '.htm', '.html'] and f.stat().st_size >= 3000:
                        # Verificar o crear hash
                        actual_sha = sha256_file(f)
                        return {
                            'status': 'cache_hit',
                            'file': str(f),
                            'sha256': actual_sha,
                            'size_bytes': f.stat().st_size,
                            'channel': 'CACHE'
                        }
    return None


# --- Gestor de Descargas Institucionales Francia ---

class FranceDownloader:
    def __init__(self, data_root: Optional[Path] = None, dry_run: bool = False):
        self.config = load_config()
        self.data_root = data_root or resolve_data_root()
        self.staging_dir = resolve_staging_dir(self.data_root)
        self.dry_run = dry_run
        self.ua = self.config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        self.companies = resolve_universe()
        self.esef_index = self._load_or_sync_esef_index()
        self.bdif_cache = {}

    def _load_or_sync_esef_index(self) -> Dict[Tuple[str, int], dict]:
        """Carga el índice oficial ESEF francés desde disco o lo sincroniza."""
        index_candidates = [
            self.data_root / "esef_filings_index_fr.json",
            Path("ARGOS_MOTOR/data/raw/esef_filings_index_fr.json"),
            Path("scratch/esef_filings_index_fr.json")
        ]
        for p in index_candidates:
            if p.exists() and p.stat().st_size > 50_000:
                try:
                    data = json.loads(p.read_text(encoding='utf-8'))
                    mapping = {}
                    for item in data:
                        lei = item.get('lei', '').upper().strip()
                        yr = item.get('year')
                        if lei and yr:
                            mapping[(lei, yr)] = item
                    print(f" [ESEF] Índice oficial Francia cargado: {len(mapping)} filings indexados ({p.name})")
                    return mapping
                except Exception as e:
                    print(f"[!] Error leyendo índice {p}: {e}")

        print(" [ESEF] Sincronizando índice oficial ESEF Francia desde filings.xbrl.org...")
        return self._sync_esef_index_from_api()

    def _sync_esef_index_from_api(self) -> Dict[Tuple[str, int], dict]:
        filing_map = {}
        page = 1
        page_size = 200
        headers = {'User-Agent': self.ua, 'Accept': 'application/json'}

        while True:
            url = f"{XBRL_API}?filter[country]=FR&include=entity&page[size]={page_size}&page[number]={page}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    items = data.get('data', [])
                    included = {item['id']: item['attributes'] for item in data.get('included', []) if item.get('type') == 'entity'}

                    if not items:
                        break

                    for item in items:
                        attrs = item.get('attributes', {})
                        pkg_url = attrs.get('package_url', '')
                        period_end = attrs.get('period_end', '')
                        year = int(period_end[:4]) if period_end and period_end[:4].isdigit() else None
                        if not year:
                            continue

                        rel_ent = item.get('relationships', {}).get('entity', {}).get('data', {})
                        ent_id = rel_ent.get('id') if rel_ent else None
                        ent_attrs = included.get(ent_id, {}) if ent_id else {}

                        lei = ent_attrs.get('identifier')
                        if not lei and pkg_url:
                            lei = pkg_url.strip('/').split('/')[0].upper()
                        if not lei:
                            lei = attrs.get('entity', {}).get('identifier', 'UNKNOWN')

                        lei = lei.upper().strip()
                        key = (lei, year)
                        if key not in filing_map:
                            filing_map[key] = {
                                'lei': lei,
                                'year': year,
                                'package_url': f"https://filings.xbrl.org{pkg_url}" if pkg_url else None,
                                'report_url': f"https://filings.xbrl.org{attrs.get('report_url', '')}" if attrs.get('report_url') else None,
                                'period_end': period_end,
                                'sha256': attrs.get('sha256', '')
                            }

                    if len(items) < page_size:
                        break
                    page += 1
                    time.sleep(0.2)
            except Exception as e:
                print(f"[!] Fin de paginación o error ESEF: {e}")
                break

        # Persistir índice para acelerar futuras ejecuciones
        try:
            serializable = [{'lei': k[0], 'year': k[1], **v} for k, v in filing_map.items()]
            save_path = self.data_root / "esef_filings_index_fr.json"
            save_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f" [ESEF] Guardado nuevo índice ESEF con {len(serializable)} registros en {save_path}")
        except Exception:
            pass

        return filing_map

    # --- Canal 1: ESEF Official Repository ---
    def channel1_esef(self, company: dict, year: int, comp_dir: Path) -> Optional[str]:
        if year < 2020:
            return None

        lei = company.get('lei', '').upper().strip()
        ticker = company.get('ticker', '')
        if not lei:
            return None

        filing = self.esef_index.get((lei, year))
        if not filing or not filing.get('package_url'):
            return None

        pkg_url = filing['package_url']
        if self.dry_run:
            return f"DRY_RUN:CANAL1_ESEF:{pkg_url}"

        tmp_path = self.staging_dir / f"esef_{ticker}_{year}_{int(time.time()*1000)}.tmp"
        headers = {'User-Agent': self.ua}

        try:
            safe_url = urllib.parse.quote(pkg_url, safe=':/?&=#')
            req = urllib.request.Request(safe_url, headers=headers)
            with urllib.request.urlopen(req, timeout=40) as resp:
                with open(tmp_path, 'wb') as f_out:
                    while chunk := resp.read(65536):
                        f_out.write(chunk)

            magic = check_magic_bytes(tmp_path)
            if magic != 'ZIP_ESEF':
                tmp_path.unlink(missing_ok=True)
                return None

            comp_dir.mkdir(parents=True, exist_ok=True)
            target_file = comp_dir / f"{ticker}_{year}_esef.zip"
            if target_file.exists():
                target_file.unlink()
            tmp_path.replace(target_file)

            actual_sha = sha256_file(target_file)
            size_mb = target_file.stat().st_size / (1024 * 1024)

            # Metadata companion
            meta = {
                "ticker": ticker,
                "lei": lei,
                "year": year,
                "source_url": pkg_url,
                "sha256": actual_sha,
                "size_bytes": target_file.stat().st_size,
                "size_mb": round(size_mb, 2),
                "magic_verified": "ZIP_ESEF",
                "channel": "CANAL1_ESEF",
                "supervisor": company.get('supervisor', 'AMF / Euronext Paris'),
                "downloaded_at": datetime.now(timezone.utc).isoformat()
            }
            meta_path = comp_dir / f"{ticker}_{year}_esef.meta.json"
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f"  [+] SELLADO [CANAL1_ESEF]: {target_file.name} ({size_mb:.2f} MB, SHA256:{actual_sha[:10]})")
            return str(target_file)

        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return None

    # --- Canal 2: AMF BDIF API (Document de Référence / URD) ---
    def channel2_bdif(self, company: dict, year: int, comp_dir: Path) -> Optional[str]:
        ticker = company.get('ticker', '')
        name_legal = company.get('name_legal', ticker)

        # Cargar catálogo BDIF para el año si no está en memoria
        if year not in self.bdif_cache:
            self.bdif_cache[year] = self._fetch_bdif_catalog_year(year)

        catalog = self.bdif_cache[year]
        if not catalog:
            return None

        # Coincidencia por nombre o ticker
        match = self._match_bdif_filing(company, catalog)
        if not match:
            return None

        if self.dry_run:
            return f"DRY_RUN:CANAL2_BDIF:{match['download_url']}"

        tmp_path = self.staging_dir / f"bdif_{ticker}_{year}_{int(time.time()*1000)}.tmp"
        headers = {
            'User-Agent': self.ua,
            'Referer': f"{BDIF_BASE}/"
        }

        try:
            req = urllib.request.Request(match['download_url'], headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                with open(tmp_path, 'wb') as f_out:
                    while chunk := resp.read(65536):
                        f_out.write(chunk)

            magic = check_magic_bytes(tmp_path)
            if magic != 'PDF':
                tmp_path.unlink(missing_ok=True)
                return None

            comp_dir.mkdir(parents=True, exist_ok=True)
            doc_type = match.get('doc_type', 'URD')
            target_file = comp_dir / f"{ticker}_{year}_{doc_type}.pdf"
            if target_file.exists():
                target_file.unlink()
            tmp_path.replace(target_file)

            actual_sha = sha256_file(target_file)
            size_mb = target_file.stat().st_size / (1024 * 1024)

            meta = {
                "ticker": ticker,
                "company_name": match.get('company_name', name_legal),
                "year": year,
                "doc_type": doc_type,
                "amf_numero": match.get('numero'),
                "source_url": match['download_url'],
                "sha256": actual_sha,
                "size_bytes": target_file.stat().st_size,
                "size_mb": round(size_mb, 2),
                "magic_verified": "PDF",
                "channel": "CANAL2_BDIF",
                "date_publication_amf": match.get('date_publication'),
                "supervisor": "AMF (France)",
                "downloaded_at": datetime.now(timezone.utc).isoformat()
            }
            meta_path = comp_dir / f"{ticker}_{year}_{doc_type}.meta.json"
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f"  [+] SELLADO [CANAL2_BDIF]: {target_file.name} ({size_mb:.2f} MB, SHA256:{actual_sha[:10]})")
            return str(target_file)

        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return None

    def _fetch_bdif_catalog_year(self, year: int) -> List[dict]:
        doc_types = ['DocumentReference', 'DocumentEnregistrementUniversel']
        catalog = []
        headers = {'User-Agent': self.ua, 'Accept': 'application/json', 'Referer': f"{BDIF_BASE}/"}

        for dt in doc_types:
            offset = 0
            page_size = 100
            while True:
                params = [
                    ('AnneesComptables', str(year)),
                    ('TypesDocument', dt),
                    ('From', str(offset)),
                    ('Size', str(page_size))
                ]
                url = f"{BDIF_API_SEARCH}?{urllib.parse.urlencode(params)}"
                try:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                        results = data.get('result', [])
                        total = data.get('total', 0)

                        if not results:
                            break

                        for item in results:
                            docs = item.get('documents', [])
                            if not docs:
                                continue
                            socs = item.get('societes', [])
                            c_name = socs[0].get('raisonSociale', '') if socs else ''
                            jeton = socs[0].get('jeton', '') if socs else ''

                            target_docs = [d for d in docs if not d.get('docRegulateur') and d.get('path')]
                            if not target_docs:
                                target_docs = [d for d in docs if d.get('path')]

                            for d in target_docs:
                                path_val = d.get('path')
                                if path_val:
                                    catalog.append({
                                        'company_name': c_name,
                                        'jeton': jeton,
                                        'year': year,
                                        'doc_type': dt,
                                        'download_url': f"{BDIF_API_DOC}/{path_val}",
                                        'numero': item.get('numero'),
                                        'date_publication': item.get('datePublication')
                                    })

                        offset += len(results)
                        if offset >= total or len(results) < page_size:
                            break
                        time.sleep(0.1)
                except Exception:
                    break

        return catalog

    def _match_bdif_filing(self, company: dict, catalog: List[dict]) -> Optional[dict]:
        name_legal = company.get('name_legal', '').upper()
        ticker = company.get('ticker', '').upper()
        clean_name = re.sub(r'\b(SA|SE|SAS|SCA|PLC|INC|CORP|NV)\b', '', name_legal).strip()

        for item in catalog:
            bdif_name = item.get('company_name', '').upper()
            if not bdif_name:
                continue
            if clean_name and (clean_name in bdif_name or bdif_name in clean_name):
                return item
            if ticker and ticker in bdif_name:
                return item
        return None

    # --- Canal 3: Recherche Entreprises API (Gouv.fr / INPI / RNE) ---
    def channel3_enrich_rne(self, company: dict, comp_dir: Path) -> Optional[dict]:
        """Obtiene datos societarios oficiales de Francia (SIREN, facturación, dirigentes)."""
        ticker = company.get('ticker', '')
        name_legal = company.get('name_legal', ticker)
        query = re.sub(r'\b(SA|SE|SAS|SCA|PLC|INC|CORP|NV)\b', '', name_legal).strip()

        try:
            url = f"{GOUV_API}?q={urllib.parse.quote(query)}&per_page=1"
            req = urllib.request.Request(url, headers={'User-Agent': self.ua})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                results = data.get('results', [])
                if not results:
                    return None

                top = results[0]
                rne_info = {
                    "siren": top.get('siren'),
                    "nom_complet": top.get('nom_complet'),
                    "date_creation": top.get('date_creation'),
                    "nature_juridique": top.get('nature_juridique'),
                    "activite_principale": top.get('activite_principale'),
                    "finances": top.get('finances'),
                    "dirigeants": [
                        {"nom": d.get('nom'), "prenoms": d.get('prenoms'), "qualite": d.get('qualite')}
                        for d in top.get('dirigeants', [])[:5]
                    ]
                }

                # Guardar sidecar RNE
                comp_dir.mkdir(parents=True, exist_ok=True)
                rne_file = comp_dir / f"{ticker}_rne_corporate_profile.json"
                rne_file.write_text(json.dumps(rne_info, indent=2, ensure_ascii=False), encoding='utf-8')
                return rne_info

        except Exception:
            return None


# --- Orquestación por Empresa y Ejercicio ---

def process_company_year(downloader: FranceDownloader, company: dict, year: int,
                         dry_run: bool = False, skip_canal: List[int] = None) -> dict:
    skip_canal = skip_canal or []
    ticker = company.get('ticker', '')
    name_legal = company.get('name_legal', ticker)
    lei = company.get('lei', '')
    data_root = downloader.data_root

    # Nombre seguro para carpeta
    safe_name = "".join(c for c in name_legal if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    comp_dir = data_root / str(year) / f"{ticker}_{safe_name}"

    result_base = {
        'ticker': ticker,
        'company': name_legal,
        'lei': lei,
        'year': year,
        'comp_dir': str(comp_dir)
    }

    # Verificar spin-off o no incorporada
    inception = SPINOFF_INCEPTION_FR.get(ticker)
    if inception and year < inception:
        print(f"  [SKIP] {ticker} {year}: No incorporada aún (desde {inception}) -> NOT_INCORPORATED_YET")
        return {**result_base, 'status': 'NOT_INCORPORATED_YET', 'channel': None}

    # 1. Comprobación en Caché Local (disco D:)
    cache = check_local_cache(data_root, ticker, name_legal, year)
    if cache:
        fpath = Path(cache['file'])
        print(f"  [CACHE] {ticker} {year}: {fpath.name} (SHA256:{cache['sha256'][:10]})")
        return {**result_base, 'status': 'cache_hit', 'channel': 'CACHE', 'file': str(fpath), 'sha256': cache['sha256']}

    print(f"\n{'-'*60}\n  {ticker} | {name_legal} | AÑO {year}")

    # 2. Canal 1: ESEF Oficial (2020-2026)
    if 1 not in skip_canal and year >= 2020:
        res1 = downloader.channel1_esef(company, year, comp_dir)
        if res1:
            if dry_run and str(res1).startswith('DRY_RUN'):
                return {**result_base, 'status': 'dry_run_hit', 'channel': 'CANAL1_ESEF', 'file': res1}
            downloader.channel3_enrich_rne(company, comp_dir)
            return {**result_base, 'status': 'downloaded', 'channel': 'CANAL1_ESEF', 'file': res1}

    # 3. Canal 2: AMF BDIF API (2012-2025)
    if 2 not in skip_canal:
        res2 = downloader.channel2_bdif(company, year, comp_dir)
        if res2:
            if dry_run and str(res2).startswith('DRY_RUN'):
                return {**result_base, 'status': 'dry_run_hit', 'channel': 'CANAL2_BDIF', 'file': res2}
            downloader.channel3_enrich_rne(company, comp_dir)
            return {**result_base, 'status': 'downloaded', 'channel': 'CANAL2_BDIF', 'file': res2}

    print(f"  [-] SIN FUENTE DISPONIBLE: {ticker} {year}")
    return {**result_base, 'status': 'missing', 'channel': None}


# --- Generación de Manifiestos Institucionales ---

def create_manifest(year: int, data_root: Path, results: List[dict]):
    manifest_path = data_root / f"MANIFEST_AMF_{year}.json"
    entries = []

    # Cargar manifiesto preexistente (AMF o BDIF)
    candidate_manifests = [manifest_path, data_root / f"MANIFEST_AMF_BDIF_{year}.json"]
    for m_cand in candidate_manifests:
        if m_cand.exists():
            try:
                raw = json.loads(m_cand.read_text(encoding='utf-8'))
                if isinstance(raw, list):
                    entries = raw
                    break
                elif isinstance(raw, dict):
                    entries = raw.get('manifest', raw.get('filings', []))
                    if entries:
                        break
            except Exception:
                pass

    existing_identifiers = {
        (e.get('ticker') or e.get('company_name') or e.get('company'))
        for e in entries if isinstance(e, dict)
    }

    # Agregar archivos presentes en disco para el año
    year_dir = data_root / str(year)
    if year_dir.exists():
        for meta_file in year_dir.glob("*/*.meta.json"):
            try:
                m_data = json.loads(meta_file.read_text(encoding='utf-8'))
                ident = m_data.get('ticker') or m_data.get('company_name')
                if ident and ident not in existing_identifiers:
                    entries.append(m_data)
                    existing_identifiers.add(ident)
            except Exception:
                pass

    # Agregar resultados de la ejecución
    for r in results:
        t = r.get('ticker')
        if t and t not in existing_identifiers:
            entries.append({
                'ticker': t,
                'company': r.get('company'),
                'year': year,
                'status': r.get('status'),
                'channel': r.get('channel'),
                'file': r.get('file'),
                'sha256': r.get('sha256'),
                'recorded_at': datetime.now(timezone.utc).isoformat()
            })
            existing_identifiers.add(t)

    manifest_data = {
        "manifest_version": "3.0.0",
        "jurisdiction": "FR",
        "supervisor": "AMF / Euronext Paris",
        "reporting_year": year,
        "total_filings": len(entries),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": entries
    }
    manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f" [MANIFIESTO] MANIFEST_AMF_{year}.json -> {len(entries)} registros")


# --- Auditoría Documental Francia ---

def run_audit(data_root: Path):
    print(f"\n{'='*60}\nAUDITORIA DE DATA LAKE FR_AMF (FRANCIA)\n{'='*60}")
    print(f"  Ruta Canónica: {data_root}")
    if not data_root.exists():
        print(f"  [!] Data root no existe: {data_root}")
        return

    pdfs = list(data_root.rglob("*.pdf"))
    zips = list(data_root.rglob("*.zip"))
    htmls = list(data_root.rglob("*.htm*"))
    metas = list(data_root.rglob("*.meta.json"))
    total_size = sum(f.stat().st_size for f in data_root.rglob("*") if f.is_file())

    print(f"  PDFs:         {len(pdfs):>6}")
    print(f"  ZIPs (ESEF):  {len(zips):>6}")
    print(f"  HTMLs:        {len(htmls):>6}")
    print(f"  Meta.jsons:   {len(metas):>6}")
    print(f"  Tamaño Total: {total_size/1024/1024:.1f} MB")

    print("\n  Desglose por Ejercicio Fiscal:")
    for yr in range(2012, 2027):
        yd = data_root / str(yr)
        if yd.exists():
            y_pdfs = len(list(yd.rglob("*.pdf")))
            y_zips = len(list(yd.rglob("*.zip")))
            y_htmls = len(list(yd.rglob("*.htm*")))
            tot = y_pdfs + y_zips + y_htmls
            print(f"    {yr}: {tot:>4} docs  (PDF={y_pdfs}, ZIP={y_zips}, HTML={y_htmls})")

    print("\n  Estado de Manifiestos Anuales:")
    for yr in range(2012, 2027):
        m = data_root / f"MANIFEST_AMF_{yr}.json"
        if not m.exists():
            m = data_root / f"MANIFEST_AMF_BDIF_{yr}.json"
        if m.exists():
            try:
                raw_m = json.loads(m.read_text(encoding='utf-8'))
                ent = raw_m.get('manifest', raw_m.get('filings', [])) if isinstance(raw_m, dict) else raw_m
                ok = sum(1 for e in ent if isinstance(e, dict) and (e.get('sha256') or e.get('status') in ['cache_hit', 'downloaded']))
                print(f"    {yr}: {len(ent):>4} registros en {m.name} (ok={ok})")
            except Exception as ex:
                print(f"    {yr}: ERROR ({ex})")


# --- Entrypoint Principal ---

def parse_years(years_str: str) -> List[int]:
    years = []
    for part in years_str.split(','):
        part = part.strip()
        if '-' in part:
            try:
                start, end = part.split('-')
                years.extend(range(int(start), int(end) + 1))
            except ValueError:
                pass
        elif part.isdigit():
            years.append(int(part))
    return sorted(set(years))


def main():
    parser = argparse.ArgumentParser(
        description=f"ARGOS MOTOR -- Descargador Institucional Francia v{VERSION}"
    )
    parser.add_argument('--segment', type=str, default='')
    parser.add_argument('--years', type=str, default='2012-2025')
    parser.add_argument('--tickers', type=str, default='')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-canal', type=str, default='')
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--manifest-only', action='store_true')
    parser.add_argument('--data-root', type=str, default=None, help='Ruta raíz personalizada para datos')
    parser.add_argument('--max', type=int, default=None, help='Límite de empresas a procesar')
    args = parser.parse_args()

    print(f"\n{'='*60}\nARGOS MOTOR -- DOWNLOADER FRANCE v{VERSION}\n{'='*60}")
    print(f"  Dry-run:      {args.dry_run}")

    data_root = resolve_data_root(args.data_root)
    print(f"  Data root:    {data_root}")

    if args.audit:
        run_audit(data_root)
        return

    downloader = FranceDownloader(data_root=data_root, dry_run=args.dry_run)
    universe = downloader.companies
    print(f"  Universo FR:  {len(universe)} entidades maestras")

    companies = list(universe.values())

    if args.tickers:
        tickers_filter = [t.strip().upper() for t in args.tickers.split(',')]
        companies = [c for c in companies if c.get('ticker', '').upper() in tickers_filter]
        print(f"  Filtro tickers: {tickers_filter} -> {len(companies)} empresas")

    if args.segment:
        segments_filter = [s.strip().upper() for s in args.segment.split(',')]
        companies = [c for c in companies if c.get('segment', '').upper() in segments_filter]
        print(f"  Filtro segmento: {segments_filter} -> {len(companies)} empresas")

    if args.max:
        companies = companies[:args.max]
        print(f"  Límite --max: {args.max} empresas")

    years = parse_years(args.years)
    print(f"  Años:         {years[0]}-{years[-1]} ({len(years)} ejercicios)")

    skip_canal = [int(x.strip()) for x in args.skip_canal.split(',') if x.strip().isdigit()] if args.skip_canal else []
    if skip_canal:
        print(f"  Skip canales: {skip_canal}")

    if args.manifest_only:
        for y in years:
            create_manifest(y, data_root, [])
        print("\n[OK] Manifiestos regenerados.")
        return

    all_results = {y: [] for y in years}
    total = len(companies) * len(years)
    processed = downloaded = cached = missing = 0
    start_time = time.time()

    print(f"\n{'='*60}\nINICIO DESCARGA FRANCIA: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}\n")

    for company in companies:
        for y in years:
            processed += 1
            res = process_company_year(downloader, company, y, dry_run=args.dry_run, skip_canal=skip_canal)
            all_results[y].append(res)
            st = res.get('status', '')
            if st == 'cache_hit':
                cached += 1
            elif st in ['downloaded', 'dry_run_hit']:
                downloaded += 1
            else:
                missing += 1

    print(f"\n{'='*60}\nGENERANDO MANIFIESTOS FRANCIA\n{'='*60}")
    for y in years:
        create_manifest(y, data_root, all_results[y])

    elapsed = time.time() - start_time
    print(f"\n{'='*60}\nRESUMEN FINAL FRANCIA\n{'='*60}")
    print(f"  Total procesadas:   {processed:,}")
    print(f"  Cache hits:         {cached:,}")
    print(f"  Nuevas descargas:   {downloaded:,}")
    print(f"  Sin fuente:         {missing:,}")
    print(f"  Tasa éxito:         {100*(cached+downloaded)/max(processed,1):.1f}%")
    print(f"  Tiempo total:       {elapsed:.1f} s")
    print(f"\n[DONE] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == '__main__':
    main()
