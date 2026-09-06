"""
STATER MOTOR ARGOS — MOD_01: Document Bundle & Manifest Manager.
Manages immutable storage hierarchy, ZIP extraction, quarantine segregation,
and reproducible manifest.json and download_report.json generation.
"""
import os
import json
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from mod_01_ingestion.src.models import (
    PublicationRecord,
    DocumentResource,
    DocumentBundle,
    BundleStatus,
    ResourceRole,
    ExtractionStatus,
    ValidationStatus
)
from mod_01_ingestion.src.sha256_sealer import seal_file


class BundleManager:
    """Administrador de expedientes documentales (bundles) e inmutabilidad."""

    SOFTWARE_VERSION = "2.0.0-ARGOS"
    CONFIG_VERSION = "2026.1"

    def __init__(self, root_data_dir: Optional[Path] = None):
        self.root_data_dir = Path(root_data_dir or "data/raw")
        self.root_data_dir.mkdir(parents=True, exist_ok=True)

    def get_bundle_directory(self, pub: PublicationRecord) -> Path:
        """Calcula el directorio raíz canónico para la publicación."""
        clean_source = pub.source.upper().replace(" ", "_")
        clean_issuer = pub.issuer_identifier.replace(" ", "_")
        clean_period = str(pub.reporting_period).replace(" ", "_")
        clean_pub_id = pub.publication_id.replace(":", "_").replace("/", "_")

        return self.root_data_dir / clean_source / clean_issuer / clean_period / clean_pub_id

    def create_bundle_layout(self, pub: PublicationRecord) -> Dict[str, Path]:
        """Crea la estructura de subcarpetas inmutables para un expediente."""
        bundle_root = self.get_bundle_directory(pub)
        
        dirs = {
            "root": bundle_root,
            "original": bundle_root / "original",
            "bundles": bundle_root / "bundles",
            "extracted": bundle_root / "extracted",
            "attachments": bundle_root / "attachments",
            "manifests": bundle_root / "manifests",
            "validation": bundle_root / "validation",
            "quarantine": bundle_root / "quarantine",
        }

        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)

        # Guardar el registro de publicación
        pub_file = bundle_root / "publication_record.json"
        with open(pub_file, "w", encoding="utf-8") as f:
            json.dump(pub.to_dict(), f, indent=2, ensure_ascii=False)

        return dirs

    def extract_zip_package(self, zip_file_path: Path, extraction_target_dir: Path) -> List[Dict[str, Any]]:
        """
        Extrae de forma segura el contenido completo de un paquete ZIP,
        preservando la jerarquía interna y sellando con SHA-256 cada archivo extraído.
        """
        extracted_inventory = []
        zip_file_path = Path(zip_file_path)
        extraction_target_dir = Path(extraction_target_dir)
        extraction_target_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_file_path, "r") as zf:
            for member in zf.infolist():
                # Protección contra Zip Slip (recorridos relativos maliciosos ../)
                extracted_path = (extraction_target_dir / member.filename).resolve()
                if not str(extracted_path).startswith(str(extraction_target_dir.resolve())):
                    continue

                if member.is_dir():
                    extracted_path.mkdir(parents=True, exist_ok=True)
                    continue

                extracted_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source_f, open(extracted_path, "wb") as target_f:
                    shutil.copyfileobj(source_f, target_f)

                sha = seal_file(extracted_path)
                sz = extracted_path.stat().st_size

                extracted_inventory.append({
                    "inner_path": member.filename,
                    "extracted_local_path": str(extracted_path.as_posix()),
                    "file_size_bytes": sz,
                    "sha256": sha,
                    "crc32": member.CRC
                })

        return extracted_inventory

    def quarantine_file(self, source_file_path: Path, quarantine_dir: Path, reason: str) -> Path:
        """Mueve un archivo defectuoso, carátula o respuesta de error a la zona de cuarentena."""
        source_file_path = Path(source_file_path)
        quarantine_dir = Path(quarantine_dir)
        quarantine_dir.mkdir(parents=True, exist_ok=True)

        target_path = quarantine_dir / source_file_path.name
        if source_file_path.exists():
            shutil.move(str(source_file_path), str(target_path))

        # Escribir informe de motivo de cuarentena
        reason_file = target_path.with_suffix(target_path.suffix + ".quarantine_reason.json")
        with open(reason_file, "w", encoding="utf-8") as f:
            json.dump({
                "filename": source_file_path.name,
                "quarantined_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason
            }, f, indent=2, ensure_ascii=False)

        return target_path

    def generate_manifest(
        self,
        pub: PublicationRecord,
        bundle: DocumentBundle,
        resources: List[DocumentResource],
        manifest_dir: Path
    ) -> Path:
        """
        Genera el archivo manifest.json reproducible que documenta el 100% de la cadena
        de custodia, URLs originales, saltos de redirección, hashes y validaciones.
        """
        manifest_dir = Path(manifest_dir)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = manifest_dir / "manifest.json"

        manifest_data = {
            "software_version": self.SOFTWARE_VERSION,
            "config_version": self.CONFIG_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "publication": pub.to_dict(),
            "bundle": bundle.to_dict(),
            "resources": [r.to_dict() for r in resources],
        }

        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        return manifest_file

    def generate_download_report(
        self,
        pub: PublicationRecord,
        bundle: DocumentBundle,
        manifest_dir: Path,
        elapsed_seconds: float
    ) -> Path:
        """Genera download_report.json con resumen de rendimiento y estado final."""
        manifest_dir = Path(manifest_dir)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        report_file = manifest_dir / "download_report.json"

        report_data = {
            "publication_id": pub.publication_id,
            "issuer": pub.issuer_name,
            "source": pub.source,
            "reporting_period": pub.reporting_period,
            "validation_status": bundle.validation_status,
            "resources_count": bundle.resources_count,
            "extracted_files_count": bundle.extracted_files_count,
            "primary_document": bundle.primary_document_path,
            "quarantine_count": len(bundle.quarantine_files),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "completeness_reasons": bundle.completeness_reasons
        }

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        return report_file
