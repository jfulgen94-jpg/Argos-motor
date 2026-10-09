"""
FASE 4 — LEGACY_BRIDGE / DEPRECATED / KEEP_UNTIL_MIGRATION_COMPLETE.

Shims que permiten que código antiguo siga llamando a la API vieja mientras la ejecución real
se delega en el núcleo unificado (sin duplicar descarga/hash/validación/promoción).
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Dict, Optional

from mod_01_ingestion.src.unified.adapters.bafin import BaFinAdapter
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.models import DiscoveryRequest


def bafin_download_filing_via_unified(
    download_dir: Path, download_url: str, entity_lei: str, fiscal_year: int,
    ticker: Optional[str] = None, company_name: Optional[str] = None, doc_type: str = "ESEF",
    runner_factory=None,
) -> Dict[str, Any]:
    warnings.warn("BaFinClient.download_filing está DEPRECATED: delega en el núcleo unificado "
                  "(mod_01_ingestion.src.unified). LEGACY_BRIDGE.", DeprecationWarning, stacklevel=3)
    data_root = Path(download_dir).resolve().parent.parent       # <root>/raw/DE_BAFIN -> <root>
    layout = DataLayout(data_root)
    record = {"lei": entity_lei, "ticker": ticker or entity_lei, "name": company_name, "fiscal_year": fiscal_year,
              "doc_type": "ESEF_PACKAGE" if doc_type == "ESEF" else doc_type, "url": download_url}
    adapter = BaFinAdapter([lambda req: [record]])
    runner = (runner_factory or UnifiedIngestRunner)(layout, {"BAFIN": adapter})
    out = runner.run_discovery(DiscoveryRequest(authority="BAFIN")).outcomes[0]
    if out.state not in ("COMPLETED", "SKIPPED_DUPLICATE"):
        raise RuntimeError(f"Descarga unificada {out.state}: {out.error_class} {out.message}")
    size = Path(out.raw_path).stat().st_size
    return {"doc_id": f"DE_BAFIN_{entity_lei}_{fiscal_year}_{doc_type}", "source": "BAFIN", "country_code": "DE",
            "issuer_lei": entity_lei, "issuer_isin": None, "ticker": ticker, "company_name": company_name,
            "doc_type": doc_type, "fiscal_year": fiscal_year, "download_url": download_url,
            "file_path": Path(out.raw_path).as_posix(), "file_size_bytes": size, "sha256_hash": out.sha256,
            "status": "RAW", "unified_job_id": out.job_id}
