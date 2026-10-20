"""
U4 — Adapters FR (AMF), IT (CONSOB) y NL (AFM) en estado SANDBOX/REPLAY. DE se migra con el ``BaFinAdapter`` existente.

Los tipos documentales proceden de ``config/sources.yaml`` (ESEF->``ESEF_PACKAGE`` canónico, URD, DPEF, RFA, DNF,
informes anuales). ALLOWED_DOMAIN_REVIEW_REQUIRED: los dominios son los ``base_url`` de ese catálogo; no se ha demostrado
con tráfico real que sirvan los documentos de cada adapter, y la clasificación ``source_type`` es conservadora
(``OFFICIAL_INDEX``) hasta contar con evidencia por fuente. Ningún adapter declara contrato de identidad.
"""
from __future__ import annotations

from mod_01_ingestion.src.unified.adapters.standard import StandardRecordAdapter
from mod_01_ingestion.src.unified.domain.enums import SourceType
from mod_01_ingestion.src.unified.source_adapter import register_adapter


class AMFAdapter(StandardRecordAdapter):
    authority, country_code, name = "AMF", "FR", "AMF"
    allowed_domains = ("bdif.amf-france.org",)
    source_type = SourceType.OFFICIAL_INDEX
    accepted_doc_types = frozenset({"ESEF_PACKAGE", "URD", "DPEF", "ANNUAL_REPORT"})


class CONSOBAdapter(StandardRecordAdapter):
    authority, country_code, name = "CONSOB", "IT", "CONSOB"
    allowed_domains = ("www.consob.it",)
    source_type = SourceType.OFFICIAL_INDEX
    accepted_doc_types = frozenset({"ESEF_PACKAGE", "RFA", "DNF", "ANNUAL_REPORT"})


class AFMAdapter(StandardRecordAdapter):
    authority, country_code, name = "AFM", "NL", "AFM"
    allowed_domains = ("www.afm.nl",)
    source_type = SourceType.OFFICIAL_INDEX
    accepted_doc_types = frozenset({"ESEF_PACKAGE", "ANNUAL_REPORT"})


register_adapter("AMF", lambda: AMFAdapter([]))
register_adapter("CONSOB", lambda: CONSOBAdapter([]))
register_adapter("AFM", lambda: AFMAdapter([]))
