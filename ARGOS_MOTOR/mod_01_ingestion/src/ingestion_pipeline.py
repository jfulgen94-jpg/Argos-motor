"""
STATER MOTOR ARGOS — MOD_01: End-to-End Regulatory Ingestion Pipeline.
Orchestrates discovery, redirect tracking, robust downloading, ZIP extraction,
multi-signal completeness validation, quarantine isolation, manifest generation,
and DuckDB data lake registration.
"""
import time
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

from mod_01_ingestion.src.models import (
    PublicationRecord,
    DocumentResource,
    DocumentBundle,
    BundleStatus,
    ResourceRole,
    CompletenessStatus,
    ExtractionStatus,
    ValidationStatus
)
from mod_01_ingestion.src.link_resolver import LinkResolver
from mod_01_ingestion.src.robust_downloader import RobustDownloader, DownloadError
from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.bundle_manager import BundleManager
from mod_04_data_lake.src.lake_manager import LakeManager


class IngestionPipeline:
    """Pipeline integral de ingesta documental con validación y trazabilidad de expedientes."""

    def __init__(
        self,
        base_data_dir: Optional[Path] = None,
        db_path: Optional[str] = None,
        max_retries: int = 3,
        timeout: float = 45.0
    ):
        self.base_data_dir = Path(base_data_dir or "data/raw")
        self.link_resolver = LinkResolver(timeout=timeout)
        self.downloader = RobustDownloader(max_retries=max_retries, timeout=timeout)
        self.validator = DocumentCompletenessValidator()
        self.bundle_manager = BundleManager(root_data_dir=self.base_data_dir)
        self.lake = LakeManager(db_path=Path(db_path) if db_path else None)

    def process_publication(
        self,
        pub: PublicationRecord,
        candidate_urls: Optional[List[str]] = None,
        client: Optional[httpx.Client] = None
    ) -> DocumentBundle:
        """
        Ejecuta el procesamiento integral de una publicación oficial.
        """
        t0 = time.perf_counter()
        layout = self.bundle_manager.create_bundle_layout(pub)

        bundle = DocumentBundle(
            bundle_id=f"BUNDLE_{pub.publication_id}",
            publication_id=pub.publication_id,
            manifest_path=str((layout["manifests"] / "manifest.json").as_posix()),
        )

        resources: List[DocumentResource] = []
        urls_to_fetch = list(candidate_urls or [pub.official_record_url])
        primary_doc_found = False
        all_reasons = []

        should_close_client = False
        if client is None:
            client = httpx.Client(timeout=45.0, follow_redirects=True)
            should_close_client = True

        try:
            for idx, target_url in enumerate(urls_to_fetch, 1):
                # 1. Resolución de URL y seguimiento de saltos
                final_url, redirect_chain, http_status, resp_headers = self.link_resolver.follow_redirects(
                    target_url, client=client
                )

                # Determinar nombre y ruta inicial en original/
                raw_filename = final_url.split("/")[-1].split("?")[0]
                if not raw_filename or "." not in raw_filename:
                    raw_filename = f"resource_{idx}.bin"

                dest_file = layout["original"] / raw_filename

                # 2. Descarga robusta con streaming y SHA-256
                try:
                    dl_res = self.downloader.download_to_file(
                        url=final_url,
                        destination_path=dest_file,
                        client=client
                    )
                except DownloadError as dl_err:
                    # Registrar recurso con error de descarga
                    res_err = DocumentResource(
                        resource_id=f"RES_{pub.publication_id}_{idx}",
                        publication_id=pub.publication_id,
                        original_url=target_url,
                        final_url=final_url,
                        local_path=str(dest_file.as_posix()),
                        filename=raw_filename,
                        mime_type="unknown",
                        file_size_bytes=0,
                        sha256="",
                        http_status=dl_err.status_code or 500,
                        validation_status=ValidationStatus.INVALID.value,
                        completeness_status=CompletenessStatus.ERROR_RESPONSE.value,
                        error_code=dl_err.error_type,
                        error_message=str(dl_err),
                        redirect_chain=redirect_chain
                    )
                    resources.append(res_err)
                    all_reasons.append(f"Error de descarga en {target_url}: {str(dl_err)}")
                    continue

                actual_path = Path(dl_res["file_path"])

                # 3. Validación de completitud y detección de carátulas/errores
                val_res = self.validator.validate_document(actual_path)
                c_status = val_res["completeness_status"]
                is_comp = val_res["is_complete"]
                should_quarantine = val_res["should_quarantine"]
                all_reasons.extend(val_res["reasons"])

                # Manejo de CUARENTENA si es carátula o error
                if should_quarantine:
                    quarantined_p = self.bundle_manager.quarantine_file(
                        actual_path,
                        layout["quarantine"],
                        reason="; ".join(val_res["reasons"])
                    )
                    bundle.quarantine_files.append(str(quarantined_p.as_posix()))

                    res = DocumentResource(
                        resource_id=f"RES_{pub.publication_id}_{idx}",
                        publication_id=pub.publication_id,
                        original_url=target_url,
                        final_url=final_url,
                        local_path=str(quarantined_p.as_posix()),
                        filename=quarantined_p.name,
                        mime_type=dl_res["mime_type"],
                        file_size_bytes=dl_res["file_size_bytes"],
                        sha256=dl_res["sha256"],
                        http_status=dl_res["http_status"],
                        resource_role=ResourceRole.COVER_PAGE.value if c_status == CompletenessStatus.COVER_PAGE_OR_INDEX.value else ResourceRole.ERROR_PAGE.value,
                        resource_type=self.link_resolver.classify_resource_type(final_url),
                        validation_status=ValidationStatus.QUARANTINED.value,
                        completeness_status=c_status,
                        error_code="QUARANTINED_INCOMPLETE_OR_ERROR",
                        error_message="; ".join(val_res["reasons"]),
                        redirect_chain=redirect_chain
                    )
                    resources.append(res)
                    continue

                # 4. Manejo de paquetes ZIP
                extracted_list = []
                if c_status == CompletenessStatus.ZIP_BUNDLE.value:
                    # Mover o copiar el ZIP a bundles/
                    bundle_zip_p = layout["bundles"] / actual_path.name
                    if actual_path.exists():
                        if bundle_zip_p.exists():
                            bundle_zip_p.unlink()
                        shutil.move(str(actual_path), str(bundle_zip_p))

                    extracted_list = self.bundle_manager.extract_zip_package(
                        bundle_zip_p,
                        layout["extracted"]
                    )
                    bundle.extracted_files_count += len(extracted_list)

                    # Buscar documento primario dentro de los extraídos
                    for ext_item in extracted_list:
                        p_candidate = ext_item["extracted_local_path"]
                        if p_candidate.lower().endswith((".xhtml", ".htm", ".pdf")):
                            bundle.primary_document_path = p_candidate
                            primary_doc_found = True
                            break

                    res = DocumentResource(
                        resource_id=f"RES_{pub.publication_id}_{idx}",
                        publication_id=pub.publication_id,
                        original_url=target_url,
                        final_url=final_url,
                        local_path=str(bundle_zip_p.as_posix()),
                        filename=bundle_zip_p.name,
                        mime_type="application/zip",
                        file_size_bytes=dl_res["file_size_bytes"],
                        sha256=dl_res["sha256"],
                        http_status=dl_res["http_status"],
                        resource_role=ResourceRole.PRIMARY_DOCUMENT.value,
                        resource_type="ZIP",
                        extraction_status=ExtractionStatus.SUCCESS.value,
                        validation_status=ValidationStatus.VALID.value,
                        completeness_status=c_status,
                        extracted_files=extracted_list,
                        redirect_chain=redirect_chain
                    )
                    resources.append(res)

                # 5. Manejo de Documentos Directos (XHTML / PDF completos)
                else:
                    role = ResourceRole.PRIMARY_DOCUMENT.value if not primary_doc_found else ResourceRole.RELATED_DOCUMENT.value
                    if is_comp:
                        bundle.primary_document_path = str(actual_path.as_posix())
                        primary_doc_found = True

                    res = DocumentResource(
                        resource_id=f"RES_{pub.publication_id}_{idx}",
                        publication_id=pub.publication_id,
                        original_url=target_url,
                        final_url=final_url,
                        local_path=str(actual_path.as_posix()),
                        filename=actual_path.name,
                        mime_type=dl_res["mime_type"],
                        file_size_bytes=dl_res["file_size_bytes"],
                        sha256=dl_res["sha256"],
                        http_status=dl_res["http_status"],
                        resource_role=role,
                        resource_type=self.link_resolver.classify_resource_type(final_url),
                        validation_status=ValidationStatus.VALID.value,
                        completeness_status=c_status,
                        redirect_chain=redirect_chain
                    )
                    resources.append(res)

            # 6. Evaluación final del estado del Bundle
            bundle.resources_count = len(resources)
            bundle.completeness_reasons = all_reasons
            has_failed_resources = any(r.validation_status == ValidationStatus.INVALID.value for r in resources)

            if primary_doc_found and not bundle.quarantine_files and not has_failed_resources:
                bundle.validation_status = BundleStatus.FINAL_COMPLETO.value
            elif primary_doc_found and (bundle.quarantine_files or has_failed_resources):
                bundle.validation_status = BundleStatus.PARCIAL.value
            elif not primary_doc_found and bundle.quarantine_files:
                bundle.validation_status = BundleStatus.CUARENTENA.value
            else:
                bundle.validation_status = BundleStatus.PARCIAL.value

            # 7. Generación de Manifiesto y Reporte
            self.bundle_manager.generate_manifest(pub, bundle, resources, layout["manifests"])
            elapsed = time.perf_counter() - t0
            self.bundle_manager.generate_download_report(pub, bundle, layout["manifests"], elapsed)

            # 8. Registro en DuckDB
            if bundle.primary_document_path:
                prim_res = next((r for r in resources if r.resource_role == ResourceRole.PRIMARY_DOCUMENT.value), None)
                if prim_res:
                    doc_record = {
                        "doc_id": pub.publication_id,
                        "source": pub.source,
                        "country_code": pub.source.split("_")[0] if "_" in pub.source else "EU",
                        "issuer_lei": pub.lei,
                        "issuer_isin": pub.isin,
                        "ticker": pub.ticker,
                        "company_name": pub.issuer_name,
                        "doc_type": pub.document_type,
                        "fiscal_year": int(str(pub.reporting_period)[:4]) if str(pub.reporting_period)[:4].isdigit() else 2024,
                        "download_url": pub.official_record_url,
                        "file_path": bundle.primary_document_path,
                        "file_size_bytes": prim_res.file_size_bytes,
                        "sha256_hash": prim_res.sha256,
                        "status": bundle.validation_status
                    }
                    try:
                        self.lake.insert_document_raw(doc_record)
                    except Exception:
                        pass

            return bundle

        finally:
            if should_close_client:
                client.close()
