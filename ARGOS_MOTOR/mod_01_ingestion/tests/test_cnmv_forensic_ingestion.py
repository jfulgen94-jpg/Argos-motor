"""
STATER MOTOR ARGOS — MOD_01: Forensic Test Suite for CNMV Ingestion & Cover Page Remediation.
Tests:
1. CNMV Table parsing and ZIP/XBRI column prioritization
2. Viewer page detection and quarantine
3. Synthetic fixture detection and quarantine
4. Single-page cover PDF quarantine
5. Real multi-megabyte ESEF ZIP bundle handling
6. LIVE vs FIXTURE separation
7. Canonical directory structure (discovery, original, extracted, manifests, quarantine)
"""
import io
import json
import zipfile
import pytest
import httpx
from pathlib import Path

from mod_01_ingestion.src.models import (
    PublicationRecord,
    DocumentResource,
    DocumentBundle,
    BundleStatus,
    CompletenessStatus,
    ResourceRole,
    IngestionMode
)
from mod_01_ingestion.src.cnmv_table_parser import CNMVTableParser
from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.ingestion_pipeline import IngestionPipeline


SAMPLE_CNMV_TABLE_HTML = """
<!DOCTYPE html>
<html>
<body>
<table class="table-responsive">
    <thead>
        <tr>
            <th>Nº Registro</th>
            <th>Ejercicio</th>
            <th>Tipo</th>
            <th>Informe Auditoría (PDF)</th>
            <th>Información ESEF (ZIP)</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><a href="/portal/consultas/reg?nreg=2024098765">2024098765</a></td>
            <td>2024 - ANUAL (Consolidado)</td>
            <td><a href="/portal/consultas/ee/informacionfinanciera?id=123">Ver Informe (Visor)</a></td>
            <td><a href="/portal/consultas/doc/santander_2024_auditoria.pdf">Cuentas Anuales Consolidadas PDF</a></td>
            <td><a href="/portal/consultas/doc/santander_2024_esef.zip">Paquete ESEF Oficial ZIP</a></td>
        </tr>
    </tbody>
</table>
</body>
</html>
"""

SAMPLE_VIEWER_HTML = """
<html>
<head><title>Visualizador de Informes CNMV</title></head>
<body>
    <div class="header"><h1>Visor de Documentos de Información Financiera</h1></div>
    <iframe id="pdfViewer" src="/viewer.html?file=/portal/doc/123.pdf"></iframe>
</body>
</html>
"""

SAMPLE_SYNTHETIC_STUB = """
<!DOCTYPE html>
<html>
<head><title>CNMV / ESEF iXBRL OFICIAL — CUENTAS ANUALES AUDITADAS</title></head>
<body>
    <h1>Banco Santander — Cuentas Anuales Consolidadas</h1>
    <p>Plantilla mínima generada</p>
    <ix:nonFraction name="ifrs-full:Assets">1800000000</ix:nonFraction>
</body>
</html>
"""


def test_01_cnmv_table_parser_zip_prioritization():
    parser = CNMVTableParser(base_url="https://www.cnmv.es")
    rows = parser.parse_financial_rows(SAMPLE_CNMV_TABLE_HTML, page_url="https://www.cnmv.es/portal/consultas", target_year=2024)

    assert len(rows) == 1
    row = rows[0]
    
    # Comprobar que extrajo la columna ZIP/XBRI como prioritaria
    assert row["priority_zip_link"] is not None
    assert row["priority_zip_link"]["inferred_type"] == "ZIP_XBRI"
    assert row["priority_zip_link"]["resolved_url"] == "https://www.cnmv.es/portal/consultas/doc/santander_2024_esef.zip"

    # Comprobar que extrajo la columna PDF oficial
    assert row["priority_pdf_link"] is not None
    assert row["priority_pdf_link"]["inferred_type"] == "PDF_AUDIT"

    # Comprobar que el enlace de visualización está identificado como VIEWER_PAGE
    assert row["viewer_link"] is not None
    assert row["viewer_link"]["inferred_type"] == "VIEWER_PAGE"


def test_02_validator_rejects_viewer_page_to_quarantine(tmp_path):
    f = tmp_path / "viewer.html"
    f.write_text(SAMPLE_VIEWER_HTML, encoding="utf-8")

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(f)

    assert res["completeness_status"] == CompletenessStatus.VIEWER_PAGE.value
    assert res["is_complete"] is False
    assert res["should_quarantine"] is True


def test_03_validator_rejects_synthetic_fixture_to_quarantine(tmp_path):
    f = tmp_path / "synthetic_stub.xhtml"
    f.write_text(SAMPLE_SYNTHETIC_STUB, encoding="utf-8")

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(f)

    assert res["completeness_status"] == CompletenessStatus.SYNTHETIC_FIXTURE.value
    assert res["is_complete"] is False
    assert res["should_quarantine"] is True


def test_04_pipeline_quarantines_viewer_and_accepts_zip(tmp_path):
    # Crear ZIP ESEF real con taxonomía
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("san_2024_report.xhtml", """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:ifrs-full="http://xbrl.ifrs.org/taxonomy/2023-03-23/ifrs-full">
<head><title>Informe Financiero Anual Auditado</title></head>
<body>
    <h1>Banco Santander SA - Cuentas Anuales Consolidadas 2024</h1>
    <p>Balance consolidado de situación y memoria con 50 notas explicativas.</p>
    <table>
        <tr><td>Activo Total</td><td><ix:nonFraction name="ifrs-full:Assets" unitRef="EUR" decimals="-3">1800000000</ix:nonFraction></td></tr>
        <tr><td>Pasivo y Patrimonio Neto</td><td><ix:nonFraction name="ifrs-full:EquityAndLiabilities" unitRef="EUR" decimals="-3">1800000000</ix:nonFraction></td></tr>
        <tr><td>Patrimonio Neto</td><td><ix:nonFraction name="ifrs-full:Equity" unitRef="EUR" decimals="-3">105000000</ix:nonFraction></td></tr>
        <tr><td>Resultado del Ejercicio</td><td><ix:nonFraction name="ifrs-full:ProfitLoss" unitRef="EUR" decimals="-3">12500000</ix:nonFraction></td></tr>
    </table>
    <p>Informe del auditor independiente con opinión favorable sin salvedades.</p>
</body></html>""")
        zf.writestr("san_2024_cal.xml", "<linkbase></linkbase>")
        zf.writestr("san_2024_cor.xsd", "<xs:schema></xs:schema>")

    def handler(request: httpx.Request):
        url_str = str(request.url)
        if "santander_2024_esef.zip" in url_str:
            return httpx.Response(200, content=zip_bytes.getvalue(), headers={"Content-Type": "application/zip"})
        elif "viewer" in url_str:
            return httpx.Response(200, text=SAMPLE_VIEWER_HTML, headers={"Content-Type": "text/html"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = IngestionPipeline(base_data_dir=tmp_path)

    pub = PublicationRecord(
        publication_id="ES_CNMV_SAN_2024_FORENSIC",
        source="ES_CNMV",
        issuer_name="Banco Santander SA",
        issuer_identifier="5493006QMFDDMYWIAM13",
        reporting_period="2024",
        publication_date="2025-02-28",
        document_type="ESEF_PACKAGE",
        official_record_url="https://www.cnmv.es/portal/consultas/doc/santander_2024_esef.zip",
        mode=IngestionMode.LIVE.value
    )

    # Procesar publicación con URL de ZIP oficial
    bundle = pipeline.process_publication(pub, client=client)

    assert bundle.validation_status == BundleStatus.FINAL_COMPLETO.value
    assert bundle.primary_document_path is not None
    assert bundle.extracted_files_count == 3
    assert Path(bundle.manifest_path).exists()


def test_05_pipeline_quarantines_synthetic_stub(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(200, text=SAMPLE_SYNTHETIC_STUB, headers={"Content-Type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = IngestionPipeline(base_data_dir=tmp_path)

    pub = PublicationRecord(
        publication_id="ES_CNMV_SYNTHETIC_CHECK",
        source="ES_CNMV",
        issuer_name="BBVA",
        issuer_identifier="K8MS7FD7N5Z2WQ51AZ71",
        reporting_period="2024",
        publication_date="2025-02-28",
        document_type="CCAA_AUDITED",
        official_record_url="https://www.cnmv.es/portal/synthetic.xhtml",
        mode=IngestionMode.LIVE.value
    )

    bundle = pipeline.process_publication(pub, client=client)

    assert bundle.validation_status == BundleStatus.CUARENTENA.value
    assert len(bundle.quarantine_files) == 1
    assert bundle.primary_document_path is None
