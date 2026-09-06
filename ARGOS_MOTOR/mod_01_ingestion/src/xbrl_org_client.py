"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Cliente Institucional para filings.xbrl.org (Canal A: ESEF Oficial ESMA OAM).

Consume la API pública JSON:API de filings.xbrl.org con:
- Paginación exhaustiva y soporte de relaciones formales (relationships.entity)
- Resolución estricta de LEI sin adivinación de nombres de fichero
- Streaming de descarga con verificación de magic bytes (PK\x03\x04) y sellado SHA-256
"""

import sys
import os
import json
import time
import hashlib
import zipfile
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

XBRL_API = "https://filings.xbrl.org/api/filings"
XBRL_BASE = "https://filings.xbrl.org"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ARGOS_MOTOR/3.0; +https://stater.es)",
    "Accept": "application/vnd.api+json, application/json, */*",
}


class XBRLOrgClient:
    """Cliente oficial para la red europea ESEF (filings.xbrl.org)."""

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.session = requests.Session()
        self.session.headers.update(headers or DEFAULT_HEADERS)
        self._cache_filings: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}

    def get_country_filings(self, country: str = "ES", year: int = 2024) -> List[Dict[str, Any]]:
        """Recupera y pagina todos los filings ESEF oficiales de un país y año."""
        cache_key = (country.upper(), int(year))
        if cache_key in self._cache_filings:
            return self._cache_filings[cache_key]

        all_filings: List[Dict[str, Any]] = []
        page = 1
        period_end = f"{year}-12-31"

        while True:
            url = (
                f"{XBRL_API}?filter[country]={country.upper()}"
                f"&filter[period_end]={period_end}"
                f"&page[size]=200&page[number]={page}"
                f"&include=entity"
            )
            try:
                resp = self.session.get(url, timeout=25)
                if resp.status_code != 200:
                    break

                payload = resp.json()
                data_items = payload.get("data", [])
                included = payload.get("included", [])
                meta = payload.get("meta", {})
                total = meta.get("count", 0)

                # Mapear entidades incluidas por ID
                entity_map: Dict[str, Dict[str, str]] = {}
                for inc in included:
                    if inc.get("type") == "entity":
                        eid = inc.get("id", "")
                        attrs = inc.get("attributes", {})
                        entity_map[eid] = {
                            "name": attrs.get("name", ""),
                            "lei": attrs.get("lei", "")
                        }

                for item in data_items:
                    attrs = item.get("attributes", {})
                    pkg_path = attrs.get("package_url", "")
                    if not pkg_path:
                        continue

                    # Extraer relación de entidad
                    rels = item.get("relationships", {})
                    entity_rel = rels.get("entity", {}).get("data", {})
                    entity_id = entity_rel.get("id", "") if isinstance(entity_rel, dict) else ""
                    entity_info = entity_map.get(entity_id, {})

                    # LEI del atributo o de la relación formal
                    resolved_lei = entity_info.get("lei") or attrs.get("lei", "")
                    if not resolved_lei:
                        # Extraer solo si está explícito en la estructura de ruta oficial
                        match = re.search(r'/([A-Z0-9]{20})/', pkg_path)
                        if match:
                            resolved_lei = match.group(1)

                    filing_entry = {
                        "lei": resolved_lei,
                        "name": entity_info.get("name") or attrs.get("name", ""),
                        "period_end": attrs.get("period_end", ""),
                        "package_url": f"{XBRL_BASE}{pkg_path}",
                        "report_url": f"{XBRL_BASE}{attrs['report_url']}" if attrs.get("report_url") else None,
                        "filing_id": item.get("id", "")
                    }
                    all_filings.append(filing_entry)

                if len(all_filings) >= total or len(data_items) == 0:
                    break
                page += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  [XBRLOrgClient] Error consultando año {year}: {e}")
                break

        self._cache_filings[cache_key] = all_filings
        return all_filings

    def find_filing_by_lei(self, lei: str, year: int, country: str = "ES") -> Optional[Dict[str, Any]]:
        """Busca el filing ESEF específico para un código LEI y ejercicio."""
        if not lei:
            return None
        clean_lei = lei.strip().upper()

        # 1. Buscar en lote del país
        filings = self.get_country_filings(country, year)
        for f in filings:
            if f.get("lei") and f["lei"].strip().upper() == clean_lei:
                return f

        # 2. Consulta directa por LEI exacto si no estaba en la primera página
        direct_url = f"{XBRL_API}?filter[entity.lei]={clean_lei}&filter[period_end]={year}-12-31&include=entity"
        try:
            resp = self.session.get(direct_url, timeout=15)
            if resp.status_code == 200:
                items = resp.json().get("data", [])
                for item in items:
                    pkg = item.get("attributes", {}).get("package_url", "")
                    if pkg:
                        return {
                            "lei": clean_lei,
                            "name": item.get("attributes", {}).get("name", ""),
                            "period_end": item.get("attributes", {}).get("period_end", f"{year}-12-31"),
                            "package_url": f"{XBRL_BASE}{pkg}",
                            "filing_id": item.get("id", "")
                        }
        except Exception:
            pass

        return None

    def download_esef_package(self, package_url: str, target_zip_path: Path) -> Dict[str, Any]:
        """Descarga en streaming un paquete ESEF ZIP y calcula su SHA-256 en vuelo."""
        target_zip_path.parent.mkdir(parents=True, exist_ok=True)

        resp = self.session.get(package_url, timeout=180, stream=True)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} al descargar paquete ESEF desde {package_url}")

        sha = hashlib.sha256()
        bytes_written = 0

        with open(target_zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    sha.update(chunk)
                    bytes_written += len(chunk)

        calculated_sha = sha.hexdigest()

        # Validar magic bytes PK\x03\x04
        with open(target_zip_path, "rb") as f:
            magic = f.read(4)
        if magic != b"PK\x03\x04":
            target_zip_path.unlink(missing_ok=True)
            raise ValueError(f"Fichero descargado no es un ZIP válido (magic={magic.hex()})")

        # Inspeccionar contenidos internos
        with zipfile.ZipFile(target_zip_path, "r") as zf:
            namelist = zf.namelist()

        return {
            "sha256": calculated_sha,
            "size_bytes": bytes_written,
            "size_mb": round(bytes_written / (1024 * 1024), 2),
            "files_count": len(namelist),
            "contents": namelist[:20],
            "downloaded_at": datetime.now(timezone.utc).isoformat()
        }
