"""
STATER MOTOR ARGOS — MOD_01: Raw Landing Downloader.
Descarga archivos en bruto directamente del servidor regulatorio oficial (CNMV/OAMs/SEC)
a la zona de aterrizaje `data/raw/landing_raw/`, calculando su hash SHA-256 inmutable
y generando un descriptor inicial antes de cualquier organización posterior.
"""
import os
import hashlib
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional
import httpx


class RawLandingDownloader:
    """Descarga en bruto a zona de aterrizaje con sellado SHA-256 inmediato."""

    def __init__(self, landing_dir: Optional[Path] = None):
        self.landing_dir = Path(landing_dir or "data/raw/landing_raw")
        self.landing_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) STATER-Transatlantic-Financial-Engine/1.0",
            "Accept": "*/*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"
        }

    def download_raw(
        self,
        url: str,
        hint_filename: Optional[str] = None,
        issuer_hint: Optional[str] = None,
        year_hint: Optional[int] = None,
        doc_type_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Descarga un archivo en bruto a la zona de aterrizaje, calculando su SHA-256.
        """
        raw_id = f"RAW_{int(time.time() * 1000)}"
        temp_path = self.landing_dir / f"{raw_id}.part"
        sha256_calc = hashlib.sha256()
        bytes_count = 0

        with httpx.Client(headers=self.headers, timeout=60.0, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(temp_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        sha256_calc.update(chunk)
                        bytes_count += len(chunk)
                        f.write(chunk)

        final_hash = sha256_calc.hexdigest()
        
        # Determinar nombre final en landing
        ext = ".bin"
        if hint_filename and "." in hint_filename:
            ext = Path(hint_filename).suffix
        elif resp.headers.get("Content-Type") == "application/pdf":
            ext = ".pdf"
        elif resp.headers.get("Content-Type") == "application/zip":
            ext = ".zip"
        elif "xhtml" in str(resp.headers.get("Content-Type")):
            ext = ".xhtml"

        final_landing_path = self.landing_dir / f"{raw_id}_{final_hash[:12]}{ext}"
        temp_path.rename(final_landing_path)

        meta_info = {
            "raw_id": raw_id,
            "original_url": url,
            "final_url": str(resp.url),
            "status_code": resp.status_code,
            "content_type": resp.headers.get("Content-Type"),
            "file_size_bytes": bytes_count,
            "sha256": final_hash,
            "landing_path": str(final_landing_path.as_posix()),
            "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "hints": {
                "filename": hint_filename,
                "issuer": issuer_hint,
                "year": year_hint,
                "doc_type": doc_type_hint
            }
        }

        # Guardar metadata raw de aterrizaje
        meta_path = final_landing_path.with_suffix(final_landing_path.suffix + ".raw_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_info, f, indent=2, ensure_ascii=False)

        return meta_info
