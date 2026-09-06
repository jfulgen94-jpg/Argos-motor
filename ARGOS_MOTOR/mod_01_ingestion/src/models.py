"""
STATER MOTOR ARGOS — MOD_01: Data Models for Regulatory Ingestion.
Defines canonical data structures for PublicationRecord, DocumentResource, DocumentBundle,
DiscoveryRecord, CNMVTableCellLink, and IngestionMode.
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import json


class IngestionMode(str, Enum):
    LIVE = "LIVE"
    FIXTURE = "FIXTURE"


class DocumentType(str, Enum):
    CCAA_AUDITED = "CCAA_AUDITED"
    INFORME_GESTION = "INFORME_GESTION"
    EINF_CSRD = "EINF_CSRD"
    IAGC = "IAGC"
    IARC = "IARC"
    FORM_10K = "FORM_10K"
    FORM_20F = "FORM_20F"
    FORM_6K = "FORM_6K"
    ESEF_PACKAGE = "ESEF_PACKAGE"
    OTHER = "OTHER"


class ResourceRole(str, Enum):
    PRIMARY_DOCUMENT = "PRIMARY_DOCUMENT"
    RELATED_DOCUMENT = "RELATED_DOCUMENT"
    ATTACHMENT = "ATTACHMENT"
    TAXONOMY_SCHEMA = "TAXONOMY_SCHEMA"
    LINKBASE = "LINKBASE"
    IMAGE = "IMAGE"
    COVER_PAGE = "COVER_PAGE"
    INDEX_PAGE = "INDEX_PAGE"
    VIEWER_PAGE = "VIEWER_PAGE"
    ERROR_PAGE = "ERROR_PAGE"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    DISCOVERY_PAGE = "DISCOVERY_PAGE"
    UNSPECIFIED = "UNSPECIFIED"


class CompletenessStatus(str, Enum):
    COMPLETE_CANDIDATE = "COMPLETE_CANDIDATE"
    XHTML_COMPLETE_CANDIDATE = "XHTML_COMPLETE_CANDIDATE"
    PARTIAL = "PARTIAL"
    XHTML_PARTIAL = "XHTML_PARTIAL"
    COVER_PAGE_OR_INDEX = "COVER_PAGE_OR_INDEX"
    COVER_OR_INDEX = "COVER_OR_INDEX"
    VIEWER_PAGE = "VIEWER_PAGE"
    ERROR_RESPONSE = "ERROR_RESPONSE"
    ERROR_HTML = "ERROR_HTML"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    INVALID_FORMAT = "INVALID_FORMAT"
    ZIP_BUNDLE = "ZIP_BUNDLE"
    UNKNOWN_REQUIRES_REVIEW = "UNKNOWN_REQUIRES_REVIEW"


class BundleStatus(str, Enum):
    FINAL_COMPLETO = "FINAL_COMPLETO"
    PARCIAL = "PARCIAL"
    CUARENTENA = "CUARENTENA"
    ERROR = "ERROR"


class ExtractionStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    QUARANTINED = "QUARANTINED"
    WARNING = "WARNING"
    UNVALIDATED = "UNVALIDATED"


@dataclass
class CNMVTableCellLink:
    """Representa un enlace extraído de una celda específica de la tabla de la CNMV."""
    visible_text: str
    href: str
    resolved_url: str
    column_name: str  # 'REGISTRO', 'EJERCICIO', 'TIPO_VISUALIZACION', 'PDF_AUDITORIA', 'ZIP_XBRI'
    column_index: int
    inferred_type: str  # 'ZIP_XBRI', 'PDF_AUDIT', 'VIEWER_PAGE', 'OFFICIAL_RECORD_PAGE', 'UNKNOWN'
    cell_html: str
    parent_page_url: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiscoveryRecord:
    """Representa la página de descubrimiento oficial consultada en el regulador."""
    source_page_url: str
    issuer_id: str
    reporting_period: str
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    matched_rows_count: int = 0
    extracted_links: List[Dict[str, Any]] = field(default_factory=list)
    raw_html_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PublicationRecord:
    """Representa el registro oficial de una publicación regulatoria."""
    publication_id: str
    source: str
    issuer_name: str
    issuer_identifier: str  # CIK, CIF o LEI
    reporting_period: str    # YYYY o YYYY-MM
    publication_date: str    # ISO 8601 YYYY-MM-DD
    document_type: str       # ESEF, 10-K, 20-F, CCAA, etc.
    official_record_url: str
    source_page_url: Optional[str] = None
    isin: Optional[str] = None
    lei: Optional[str] = None
    ticker: Optional[str] = None
    mode: str = IngestionMode.LIVE.value
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "DISCOVERED"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PublicationRecord":
        return cls(**data)


@dataclass
class DocumentResource:
    """Representa un recurso documental individual asociado a una publicación."""
    resource_id: str
    publication_id: str
    original_url: str
    final_url: str
    local_path: str
    filename: str
    mime_type: str
    file_size_bytes: int
    sha256: str
    http_status: int = 200
    resource_role: str = ResourceRole.UNSPECIFIED.value
    resource_type: str = "DOCUMENT"  # XHTML, PDF, ZIP, XML, SCHEMA, etc.
    source_column: Optional[str] = None  # Columna de procedencia CNMV
    parent_resource_id: Optional[str] = None
    blob_path: Optional[str] = None
    downloaded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extraction_status: str = ExtractionStatus.NOT_APPLICABLE.value
    validation_status: str = ValidationStatus.UNVALIDATED.value
    completeness_status: str = CompletenessStatus.UNKNOWN_REQUIRES_REVIEW.value
    parser_compatibility: bool = True
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    redirect_chain: List[str] = field(default_factory=list)
    extracted_files: List[Dict[str, Any]] = field(default_factory=list)
    missing_dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentResource":
        return cls(**data)


@dataclass
class DocumentBundle:
    """Agregador del expediente documental completo para una publicación."""
    bundle_id: str
    publication_id: str
    manifest_path: str
    mode: str = IngestionMode.LIVE.value
    resources_count: int = 0
    extracted_files_count: int = 0
    primary_document_path: Optional[str] = None
    related_documents: List[str] = field(default_factory=list)
    attachments: List[str] = field(default_factory=list)
    taxonomies: List[str] = field(default_factory=list)
    linkbases: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    quarantine_files: List[str] = field(default_factory=list)
    validation_status: str = BundleStatus.PARCIAL.value
    completeness_reasons: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentBundle":
        return cls(**data)
