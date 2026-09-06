"""
STATER MOTOR ARGOS — MOD_01: Ingestor Nacional España (CNMV).
Descarga de Informes Financieros Anuales (ESEF iXBRL / ZIP), Informes de Auditoría (KAMs ISA 701)
e Informes Anuales de Gobierno Corporativo (IAGC) de la CNMV.
"""
import json
import re
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, List

from mod_01_ingestion.src.bundle_manager import BundleManager
from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.models import BundleStatus
from mod_01_ingestion.src.robust_downloader import RobustDownloader
from mod_01_ingestion.src.sha256_sealer import seal_file


class CNMVClient:
    """Cliente de ingesta especializado para el mercado español (CNMV / BME)."""

    COUNTRY_CODE = "ES"
    REGULATOR_NAME = "CNMV"
    BASE_URL = "https://www.cnmv.es"
    REQUIRED_ANNUAL_DOCS = {
        "ESEF_PACKAGE": "cuentas_anuales_consolidadas_auditadas",
        "INFORME_GESTION": "informe_de_gestion_consolidado",
        "EINF_CSRD": "estado_informacion_no_financiera_csrd",
        "IAGC": "informe_anual_gobierno_corporativo_IAGC",
        "IARC": "informe_anual_remuneraciones_IARC",
    }
    MIME_EXTENSION_MAP = {
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "application/xhtml+xml": ".xhtml",
        "text/html": ".html",
        "application/xml": ".xml",
        "text/xml": ".xml",
    }

    def __init__(self, download_dir: Optional[Path] = None):
        self.download_dir = Path(download_dir or "data/raw/ES_CNMV")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) STATER-Transatlantic-Financial-Engine/1.0",
            "Accept": "application/zip, application/xhtml+xml, application/pdf, text/html, */*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Referer": self.BASE_URL,
        }
        self.downloader = RobustDownloader(headers=self.headers, timeout=120.0)
        self.validator = DocumentCompletenessValidator()
        self.bundle_manager = BundleManager(root_data_dir=self.download_dir)

    def build_doc_id(self, entity_lei: str, fiscal_year: int, doc_type: str = "ESEF") -> str:
        """Genera el identificador canónico de documento para España."""
        return f"ES_CNMV_{entity_lei}_{fiscal_year}_{doc_type}"

    def build_storage_dirname(self, ticker: Optional[str], company_name: Optional[str], entity_lei: str) -> str:
        """Genera un nombre de carpeta consistente para el emisor."""
        if ticker and company_name:
            base = f"{ticker.upper()}_{company_name}"
        elif company_name:
            base = company_name
        else:
            base = entity_lei
        clean = re.sub(r"[^\w]+", "_", base, flags=re.UNICODE).strip("_")
        return clean or entity_lei

    def _infer_extension(self, url: str, mime_type: str, doc_type: str) -> str:
        raw_name = url.split("/")[-1].split("?")[0]
        suffix = Path(raw_name).suffix.lower()
        if suffix:
            return suffix
        if mime_type in self.MIME_EXTENSION_MAP:
            return self.MIME_EXTENSION_MAP[mime_type]
        return ".zip" if doc_type == "ESEF_PACKAGE" else ".pdf"

    def download_annual_package(
        self,
        entity_lei: str,
        fiscal_year: int,
        document_urls: Dict[str, str],
        cif_nif: Optional[str] = None,
        ticker: Optional[str] = None,
        company_name: Optional[str] = None,
        source_page_url: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> Dict[str, Any]:
        """
        Descarga el paquete anual oficial CNMV con los 5 documentos regulatorios exigidos.
        Rechaza la ingesta sintética: si faltan URLs obligatorias no fabrica metadatos.
        """
        missing_doc_types = [doc_type for doc_type in self.REQUIRED_ANNUAL_DOCS if not document_urls.get(doc_type)]
        if missing_doc_types:
            raise ValueError(
                f"Faltan URLs oficiales CNMV para los tipos documentales obligatorios: {', '.join(missing_doc_types)}"
            )

        folder_name = self.build_storage_dirname(ticker=ticker, company_name=company_name, entity_lei=entity_lei)
        target_dir = self.download_dir / str(fiscal_year) / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)

        created_client = False
        if client is None:
            client = httpx.Client(headers=self.headers, timeout=120.0, follow_redirects=True)
            created_client = True

        documents: List[Dict[str, Any]] = []
        manifest_documents: Dict[str, Any] = {}

        try:
            for doc_type, file_slug in self.REQUIRED_ANNUAL_DOCS.items():
                download_url = document_urls[doc_type]
                provisional_ext = Path(download_url.split("/")[-1].split("?")[0]).suffix.lower()
                if not provisional_ext:
                    provisional_ext = ".bin"
                target_path = target_dir / f"{(ticker or entity_lei).lower()}_{fiscal_year}_{file_slug}{provisional_ext}"

                dl_res = self.downloader.download_to_file(
                    url=download_url,
                    destination_path=target_path,
                    client=client,
                )
                final_path = Path(dl_res["file_path"])
                resolved_ext = self._infer_extension(download_url, dl_res["mime_type"], doc_type)
                desired_path = target_dir / f"{(ticker or entity_lei).lower()}_{fiscal_year}_{file_slug}{resolved_ext}"
                if final_path != desired_path:
                    if desired_path.exists():
                        desired_path.unlink()
                    final_path.rename(desired_path)
                    final_path = desired_path

                validation = self.validator.validate_document(final_path, expected_doc_type=doc_type)
                stored_path = final_path
                status = "RAW_VALIDATED"
                if validation["should_quarantine"]:
                    stored_path = self.bundle_manager.quarantine_file(
                        source_file_path=final_path,
                        quarantine_dir=target_dir / "quarantine",
                        reason="; ".join(validation["reasons"]),
                    )
                    status = "QUARANTINED"

                extracted_files = []
                if (
                    status != "QUARANTINED"
                    and validation["completeness_status"] == "ZIP_BUNDLE"
                    and stored_path.suffix.lower() == ".zip"
                ):
                    extraction_dir = target_dir / f"{stored_path.stem}_extracted"
                    extracted_files = self.bundle_manager.extract_zip_package(stored_path, extraction_dir)

                file_size = stored_path.stat().st_size
                sha256_digest = seal_file(stored_path)
                doc_record = {
                    "doc_id": self.build_doc_id(entity_lei, fiscal_year, doc_type),
                    "source": "CNMV",
                    "country_code": self.COUNTRY_CODE,
                    "issuer_lei": entity_lei,
                    "issuer_isin": None,
                    "ticker": ticker,
                    "company_name": company_name,
                    "doc_type": doc_type,
                    "fiscal_year": fiscal_year,
                    "download_url": download_url,
                    "source_page_url": source_page_url,
                    "file_path": str(stored_path.as_posix()),
                    "file_size_bytes": file_size,
                    "sha256_hash": sha256_digest,
                    "status": status,
                    "completeness_status": validation["completeness_status"],
                    "validation_reasons": validation["reasons"],
                    "validation_metrics": validation["metrics"],
                    "extracted_files_count": len(extracted_files),
                    "extracted_files": extracted_files,
                }
                documents.append(doc_record)
                manifest_documents[doc_type] = {
                    "download_url": download_url,
                    "file_path": doc_record["file_path"],
                    "file_size_bytes": file_size,
                    "sha256_hash": sha256_digest,
                    "status": status,
                    "completeness_status": validation["completeness_status"],
                    "extracted_files_count": len(extracted_files),
                }
        finally:
            if created_client:
                client.close()

        quarantined_count = sum(1 for doc in documents if doc["status"] == "QUARANTINED")
        if quarantined_count:
            package_status = BundleStatus.CUARENTENA.value
        elif len(documents) == len(self.REQUIRED_ANNUAL_DOCS):
            package_status = BundleStatus.FINAL_COMPLETO.value
        else:
            package_status = BundleStatus.PARCIAL.value

        manifest_path = target_dir / f"{(ticker or entity_lei).lower()}_{fiscal_year}_cnmv_package_manifest.json"
        manifest_payload = {
            "package_id": f"ES_CNMV_{entity_lei}_{fiscal_year}_ANNUAL_PACKAGE",
            "source": "CNMV",
            "country_code": self.COUNTRY_CODE,
            "issuer_lei": entity_lei,
            "ticker": ticker,
            "company_name": company_name,
            "fiscal_year": fiscal_year,
            "source_page_url": source_page_url,
            "package_status": package_status,
            "documents": manifest_documents,
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=2, ensure_ascii=False)
        manifest_sha256 = seal_file(manifest_path)

        return {
            "package_id": manifest_payload["package_id"],
            "manifest_path": str(manifest_path.as_posix()),
            "manifest_sha256_hash": manifest_sha256,
            "package_status": package_status,
            "downloaded_count": len(documents),
            "quarantined_count": quarantined_count,
            "documents": documents,
        }

    def download_filing(
        self,
        download_url: str,
        entity_lei: str,
        fiscal_year: int,
        cif_nif: Optional[str] = None,
        ticker: Optional[str] = None,
        company_name: Optional[str] = None,
        doc_type: str = "ESEF"
    ) -> Dict[str, Any]:
        """
        Descarga el paquete oficial de la CNMV, lo almacena particionado en disco
        y aplica el sellado criptográfico inmutable SHA-256.
        """
        target_dir = self.download_dir / str(fiscal_year) / entity_lei
        target_dir.mkdir(parents=True, exist_ok=True)

        url_filename = download_url.split("/")[-1].split("?")[0]
        if not url_filename:
            extension = ".zip" if doc_type == "ESEF" else ".pdf"
            url_filename = f"cnmv_{entity_lei}_{fiscal_year}_{doc_type.lower()}{extension}"

        target_path = target_dir / url_filename

        with httpx.Client(headers=self.headers, timeout=120.0, follow_redirects=True) as client:
            with client.stream("GET", download_url) as r:
                r.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)

        sha256_digest = seal_file(target_path)
        file_size = target_path.stat().st_size

        return {
            "doc_id": self.build_doc_id(entity_lei, fiscal_year, doc_type),
            "source": "CNMV",
            "country_code": self.COUNTRY_CODE,
            "issuer_lei": entity_lei,
            "issuer_isin": None,
            "ticker": ticker,
            "company_name": company_name,
            "doc_type": doc_type,
            "fiscal_year": fiscal_year,
            "download_url": download_url,
            "file_path": str(target_path.as_posix()),
            "file_size_bytes": file_size,
            "sha256_hash": sha256_digest,
            "status": "RAW",
        }
