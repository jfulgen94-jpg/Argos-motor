"""
STATER MOTOR ARGOS — MOD_01: Automated Raw Filings Organizer.
Toma los archivos descargados en bruto en `data/raw/landing_raw/`, valida su completitud
con `DocumentCompletenessValidator`, los organiza en su carpeta canónica por empresa y año,
y genera los manifiestos `.meta.json` con su hash SHA-256 inmutable.
"""
import os
import sys
import json
import time
import shutil
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional

# Añadir ARGOS_MOTOR al path
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.sha256_sealer import seal_file
from mod_04_data_lake.src.lake_manager import LakeManager


class RawFilingsOrganizer:
    """Organizador automático de archivos en bruto a carpetas canónicas con SHA-256."""

    def __init__(self, landing_dir: Optional[Path] = None, output_base_dir: Optional[Path] = None):
        self.landing_dir = Path(landing_dir or "data/raw/landing_raw")
        self.output_base_dir = Path(output_base_dir or "data/raw")
        self.validator = DocumentCompletenessValidator()
        self.lake = LakeManager(db_path="data/lake/duckdb/stater_motor.duckdb")

    def organize_all(self) -> List[Dict[str, Any]]:
        """Escanea landing_raw y organiza todos los archivos pendientes."""
        if not self.landing_dir.exists():
            print("[INFO] La carpeta landing_raw no existe aún.")
            return []

        meta_files = sorted(list(self.landing_dir.glob("*.raw_meta.json")))
        print(f"=== ORGANIZANDO {len(meta_files)} ARCHIVOS EN BRUTO DESDE LANDING RAW ===")

        organized = []
        for mf in meta_files:
            with open(mf, "r", encoding="utf-8") as f:
                meta = json.load(f)

            raw_file_p = Path(meta["landing_path"])
            if not raw_file_p.exists():
                continue

            hints = meta.get("hints", {})
            ticker = hints.get("issuer") or "SAN"
            year = hints.get("year") or 2024
            doc_type = hints.get("doc_type") or "CCAA_AUDITED"
            filename_hint = hints.get("filename") or raw_file_p.name

            # Validar con validador forense
            val_res = self.validator.validate_document(raw_file_p)
            sha = meta.get("sha256") or seal_file(raw_file_p)

            # Destino en estructura humana
            target_folder = self.output_base_dir / "ES_CNMV" / str(year) / f"{ticker}_EMPRESA"
            target_folder.mkdir(parents=True, exist_ok=True)
            final_file_p = target_folder / filename_hint

            shutil.copy2(raw_file_p, final_file_p)

            # Generar .meta.json de sellado
            meta_record = {
                "filename": filename_hint,
                "ticker": ticker,
                "fiscal_year": year,
                "doc_type": doc_type,
                "file_size_bytes": final_file_p.stat().st_size,
                "sha256": sha,
                "validation_status": val_res.get("completeness_status"),
                "is_complete": val_res.get("is_complete"),
                "organized_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }

            meta_dest_p = target_folder / f"{ticker.lower()}_{year}_checksum_sha256.meta.json"
            with open(meta_dest_p, "w", encoding="utf-8") as f:
                json.dump(meta_record, f, indent=2, ensure_ascii=False)

            # Registro en DuckDB
            try:
                self.lake.insert_document_raw({
                    "doc_id": f"ES_CNMV_{ticker}_{year}_{doc_type}",
                    "source": "CNMV",
                    "country_code": "ES",
                    "issuer_lei": f"LEI_{ticker}",
                    "issuer_isin": None,
                    "ticker": ticker,
                    "company_name": ticker,
                    "doc_type": doc_type,
                    "fiscal_year": year,
                    "download_url": meta.get("original_url"),
                    "file_path": str(final_file_p.as_posix()),
                    "file_size_bytes": final_file_p.stat().st_size,
                    "sha256_hash": sha,
                    "status": "FINAL_COMPLETO" if val_res.get("is_complete") else "PARCIAL"
                })
            except Exception:
                pass

            organized.append(meta_record)
            print(f"  -> Organizado: {final_file_p.name} ({final_file_p.stat().st_size:,} bytes | SHA: {sha[:12]}...)")

        print(f"=== PROCESO COMPLETADO: {len(organized)} ARCHIVOS ORGANIZADOS Y SELLADOS ===")
        return organized


if __name__ == "__main__":
    organizer = RawFilingsOrganizer()
    organizer.organize_all()
