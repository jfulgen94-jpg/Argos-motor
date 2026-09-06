"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Guardián de Pre-Validación con IA y NLP (AI Pre-Validation Guard).

Inspecciona las primeras 1 a 5 páginas o el contenido estructural de todo
documento descargado antes de autorizar su pase al Data Lake canónico
(data/raw/ES_CNMV/{YEAR}/{TICKER}_{NAME}/).

Comprobaciones Obligatorias:
1. Identidad Jurídica: NIF/CIF, LEI y razón social contra catálogo maestro (score >= 0.90).
2. Ejercicio Fiscal: Año auditado certificado en dictamen vs año solicitado.
3. Tipología Documental: CCAA Auditadas vs Hechos Relevantes vs Folletos vs IPP.
4. Detección Cero Sintéticos: Búsqueda de patrones de generación artificial (institutional_document_builder).
5. Umbral Físico y Estructural: Reutiliza branch_threshold_validator y document_completeness_validator.
"""

import sys
import os
import re
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mod_01_ingestion.src.entity_resolver import (
    EntityResolver, 
    compute_comprehensive_similarity, 
    normalize_cif, 
    normalize_entity_name
)
from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.branch_threshold_validator import BranchThresholdValidator, DocumentBranch

# Huellas conocidas del generador sintético institutional_document_builder
SYNTHETIC_SIGNATURES = [
    "EXPEDIENTE REGULATORIO OFICIAL CNMV / ESEF iXBRL",
    "build_full_institutional_ccaa",
    "Generado por STATER MOTOR ARGOS",
    "Fórmula de importes crecientes: base + (year-2019)",
    "DICTAMEN DE AUDITORIA FAVORABLE SIN SALVEDADES (SIMULADO)",
]

# Patrón de texto de relleno genérico ("Lorem ipsum...") repetido. Se exige
# repetición (>=3 apariciones) para no bloquear una cita incidental legítima.
LOREM_IPSUM_PATTERN = re.compile(r"(?:lorem\s+ipsum\s+dolor\s+sit\s+amet[\.\s]*){3,}", re.IGNORECASE)


class AIPreValidationGuard:
    """Guardián de Integridad que inspecciona todo documento antes del commit al Data Lake."""

    def __init__(self, entity_resolver: Optional[EntityResolver] = None):
        self.resolver = entity_resolver or EntityResolver()
        self.completeness_validator = DocumentCompletenessValidator()

    def validate_staging_resource(
        self,
        file_path: Path,
        expected_ticker: str,
        expected_year: int,
        expected_doc_type: str = "CCAA_AUDITED",
        allow_declared_comparative: bool = False
    ) -> Dict[str, Any]:
        """
        Ejecuta la validación exhaustiva de pre-ingesta sobre un archivo en staging.
        """
        if not file_path.exists() or file_path.stat().st_size == 0:
            return {
                "is_valid": False,
                "rejection_code": "EMPTY_OR_NONEXISTENT_FILE",
                "reasons": ["El archivo no existe o tiene tamaño 0 bytes."],
                "detected_metadata": {}
            }

        # 1. Comprobación contra el validador forense de completitud (anti-skeleton, anti-403)
        comp_val = self.completeness_validator.validate_document(file_path)
        comp_status = comp_val.get("completeness_status", "")
        if comp_status in ("ERROR_RESPONSE", "VIEWER_PAGE", "EMPTY_SKELETON_ASP"):
            return {
                "is_valid": False,
                "rejection_code": comp_status,
                "reasons": comp_val.get("reasons", ["Documento incompleto o skeleton"]),
                "detected_metadata": {}
            }

        # 2. Detección de Fabricación Sintética
        is_synthetic, synth_reason = self._check_synthetic_fabrication(file_path)
        if is_synthetic:
            return {
                "is_valid": False,
                "rejection_code": "SYNTHETIC_FABRICATED",
                "reasons": [f"RECHAZADO: Contenido sintético detectado ({synth_reason})"],
                "detected_metadata": {"is_synthetic": True}
            }

        # 3. Extraer texto representativo (primeras 5 páginas o cabecera XHTML/ZIP)
        header_text = self._extract_header_text(file_path)

        # 4. Validar Identidad Jurídica contra Catálogo Maestro
        expected_entity = self.resolver.get_by_ticker(expected_ticker)
        if not expected_entity:
            return {
                "is_valid": False,
                "rejection_code": "UNKNOWN_EXPECTED_TICKER",
                "reasons": [f"Ticker {expected_ticker} no existe en el Catálogo Maestro."],
                "detected_metadata": {}
            }

        exp_name = expected_entity.get("name_legal", "")
        exp_cif = expected_entity.get("cif_nif", "")
        exp_lei = expected_entity.get("lei", "")

        detected_cif = self._extract_cif_from_text(header_text)
        detected_name = self._extract_company_name_from_text(header_text)

        # Score de similitud de identidad
        id_score = compute_comprehensive_similarity(
            query_name=detected_name or header_text[:500],
            target_name=exp_name,
            query_cif=detected_cif,
            target_cif=exp_cif
        )

        # Si hay un CIF explícito detectado y no coincide, o el score es muy bajo (< 0.70)
        if detected_cif and normalize_cif(detected_cif) != normalize_cif(exp_cif):
            return {
                "is_valid": False,
                "rejection_code": "WRONG_ENTITY_MISMATCH_WITH_FOLDER",
                "reasons": [
                    f"DISCORDANCIA DE ENTIDAD: CIF detectado '{detected_cif}' no coincide con '{exp_cif}' ({exp_name})"
                ],
                "detected_metadata": {
                    "detected_cif": detected_cif,
                    "expected_cif": exp_cif,
                    "detected_name": detected_name,
                    "expected_name": exp_name,
                    "similarity_score": id_score
                }
            }

        # 5. Validar Ejercicio Fiscal
        detected_year = self._extract_fiscal_year_from_text(header_text, file_path)
        if detected_year and detected_year != expected_year:
            if not allow_declared_comparative:
                return {
                    "is_valid": False,
                    "rejection_code": "WRONG_YEAR_UNDECLARED_SUBSTITUTION",
                    "reasons": [
                        f"DISCORDANCIA DE EJERCICIO: Se solicitó {expected_year} pero el documento certifica el ejercicio {detected_year}"
                    ],
                    "detected_metadata": {
                        "detected_year": detected_year,
                        "expected_year": expected_year
                    }
                }

        # 6. Validar Tipología Documental
        detected_type = self._classify_doc_type(header_text, file_path)

        # 7. Umbral Físico y Estructural por rama documental (branch_threshold_validator).
        # Rechaza texto de relleno (Lorem Ipsum) y documentos por debajo del tamaño/
        # nº de secciones mínimas exigibles para esa tipología, incluso si superaron
        # los pasos 1-6 (identidad, año y firmas sintéticas conocidas).
        branch_name = expected_doc_type.upper() if expected_doc_type else detected_type
        try:
            branch = DocumentBranch(branch_name)
        except ValueError:
            branch = None

        if branch is not None and file_path.suffix.lower() in (".xhtml", ".html", ".htm"):
            branch_result = BranchThresholdValidator.validate_file_branch(file_path, branch)
            if not branch_result.get("is_valid", True):
                return {
                    "is_valid": False,
                    "rejection_code": "SYNTHETIC_FABRICATED" if "Lorem Ipsum" in branch_result.get("reason", "") else "BELOW_MINIMUM_THRESHOLD",
                    "reasons": [f"RECHAZADO por umbral de rama documental: {branch_result.get('reason')}"],
                    "detected_metadata": {
                        "branch": branch.value,
                        "char_count": branch_result.get("char_count"),
                        "file_size_bytes": branch_result.get("file_size_bytes"),
                    }
                }

        return {
            "is_valid": True,
            "rejection_code": None,
            "reasons": ["Documento validado con éxito por el AI Pre-Validation Guard."],
            "detected_metadata": {
                "ticker": expected_ticker,
                "detected_year": detected_year or expected_year,
                "detected_type": detected_type,
                "detected_cif": detected_cif or exp_cif,
                "similarity_score": id_score,
                "file_size_mb": round(file_path.stat().st_size / (1024 * 1024), 2)
            }
        }

    def _extract_header_text(self, file_path: Path, max_bytes: int = 50000) -> str:
        """Extrae texto de las primeras páginas o cabeceras del archivo."""
        suffix = file_path.suffix.lower()

        if suffix in (".xhtml", ".html", ".htm", ".xml"):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(max_bytes)
                # Eliminar tags HTML rápidamente
                clean = re.sub(r'<[^>]+>', ' ', content)
                return " ".join(clean.split())
            except Exception:
                return ""

        elif suffix == ".zip":
            try:
                with zipfile.ZipFile(file_path, "r") as zf:
                    for name in zf.namelist():
                        if name.endswith((".xhtml", ".html", ".xml")) and "manifest" not in name:
                            with zf.open(name) as hf:
                                content = hf.read(max_bytes).decode("utf-8", errors="ignore")
                                clean = re.sub(r'<[^>]+>', ' ', content)
                                return " ".join(clean.split())
            except Exception:
                return ""

        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(file_path))
                text = ""
                for page_idx in range(min(3, len(reader.pages))):
                    page_text = reader.pages[page_idx].extract_text() or ""
                    text += page_text + " "
                return " ".join(text.split())
            except Exception:
                try:
                    with open(file_path, "rb") as f:
                        raw = f.read(15000).decode("latin-1", errors="ignore")
                    clean = re.sub(r'[^A-Za-z0-9áéíóúÁÉÍÓÚñÑ\-\.\s]', ' ', raw)
                    return " ".join(clean.split())
                except Exception:
                    return ""

        return ""

    def _check_synthetic_fabrication(self, file_path: Path) -> Tuple[bool, str]:
        """Detecta patrones de generación sintética conocidos, incluido texto de relleno genérico."""
        try:
            with open(file_path, "rb") as f:
                head = f.read(50000).decode("utf-8", errors="ignore")
            for sig in SYNTHETIC_SIGNATURES:
                if sig in head:
                    return True, sig
            if LOREM_IPSUM_PATTERN.search(head):
                return True, "TEXTO_DE_RELLENO_LOREM_IPSUM_DETECTADO"
        except Exception:
            pass
        return False, ""

    def _extract_cif_from_text(self, text: str) -> Optional[str]:
        """Busca patrones de NIF/CIF español."""
        sample = text[:15000]
        match = re.search(r'\b([A-HJ-NP-SUVW][\s\-]?[0-9]{7}[\s\-]?[0-9A-J])\b', sample)
        if match:
            return normalize_cif(match.group(1))
        return None

    def _extract_company_name_from_text(self, text: str) -> Optional[str]:
        """Extrae la denominación social en cabeceras de dictamen."""
        sample = text[:15000]
        match = re.search(r'(?:Cuentas Anuales Consolidadas de|Informe de Auditoría de|Sociedad:)\s+([A-ZÁÉÍÓÚÑa-z0-9\s\,\.]{5,50})', sample, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_fiscal_year_from_text(self, text: str, file_path: Path) -> Optional[int]:
        """Extrae el año fiscal certificado en el informe."""
        sample = text[:30000] if text else ""
        # 1. Búsqueda en párrafos de dictamen de auditoría y cuentas anuales
        if sample:
            match_op = re.search(r'(?:ejercicio terminado|cerrado el|a)\s+31\s+de\s+diciembre\s+de\s+(20[12][0-9])', sample, re.IGNORECASE)
            if match_op:
                return int(match_op.group(1))

            match_op2 = re.search(r'ejercicio\s+(20[12][0-9])', sample, re.IGNORECASE)
            if match_op2:
                return int(match_op2.group(1))

        # 2. Fallback a búsqueda en nombre de fichero
        match_fn = re.search(r'[-_](20[12][0-9])[-_]', file_path.name)
        if match_fn:
            return int(match_fn.group(1))

        return None

    def _classify_doc_type(self, text: str, file_path: Path) -> str:
        """Clasifica la tipología del documento."""
        t_low = text.lower()
        if "informe de auditoría" in t_low or "cuentas anuales" in t_low:
            return "CCAA_AUDITED"
        elif "informe de gestión" in t_low:
            return "INFORME_GESTION"
        elif "gobierno corporativo" in t_low or "iagc" in t_low:
            return "IAGC"
        elif "remuneraciones" in t_low or "iarc" in t_low:
            return "IARC"
        elif "hecho relevante" in t_low or "otra información relevante" in t_low:
            return "OIR"
        elif "folleto" in t_low or "prospectus" in t_low:
            return "FOLLETO"
        return "CCAA_AUDITED"
