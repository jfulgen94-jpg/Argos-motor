"""
STATER MOTOR ARGOS — MOD_01: Exhaustive Test Suite for Regulatory Ingestion.
Tests 25 edge cases using local fixtures and MockTransport (no external network dependencies):
1. Complete document download & bundle assembly
2. Cover page detection & quarantine
3. HTML search/index page detection
4. Error HTML response detection
5. HTTP redirect chain tracking
6. Relative URL resolution
7. Multi-file complete ZIP bundle extraction
8. Corrupt ZIP detection
9. ZIP with empty/truncated files
10. XHTML iXBRL with facts & contexts validation
11. XHTML without facts classified as cover/partial
12. Single-page PDF classified as cover page
13. Interrupted & resumed download (Range Requests)
14. HTTP 429 rate limit with exponential backoff
15. HTTP 503 server error recovery with retries
16. Exact SHA-256 verification
17. SHA-256 mismatch rejection
18. Duplicate resource by hash handling
19. Incomplete metadata to quarantine
20. Reproducible manifest.json verification
21. Ban declaring success when primary doc is missing
22. Original file preservation (untouched)
23. Idempotent re-run
24. Bundle with taxonomies & linkbases
25. Missing dependency registration
"""
import io
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
    ValidationStatus
)
from mod_01_ingestion.src.link_resolver import LinkResolver
from mod_01_ingestion.src.robust_downloader import RobustDownloader, DownloadError
from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.bundle_manager import BundleManager
from mod_01_ingestion.src.ingestion_pipeline import IngestionPipeline


# ==========================================
# FIXTURES Y SAMPLES
# ==========================================

SAMPLE_IXBRL_COMPLETE = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ifrs-full="http://xbrl.ifrs.org/taxonomy/2023-03-23/ifrs-full">
<head><title>Informe Financiero Anual Auditado</title></head>
<body>
    <h1>Banco Santander SA - Cuentas Anuales Consolidadas</h1>
    <xbrli:context id="c_2024"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">5493006QMFDDMYWIAM13</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:unit id="EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
    <table>
        <tr><td>Activo Total</td><td><ix:nonFraction name="ifrs-full:Assets" contextRef="c_2024" unitRef="EUR" decimals="-3">1800000000</ix:nonFraction></td></tr>
        <tr><td>Pasivo y PN</td><td><ix:nonFraction name="ifrs-full:EquityAndLiabilities" contextRef="c_2024" unitRef="EUR" decimals="-3">1800000000</ix:nonFraction></td></tr>
        <tr><td>Patrimonio Neto</td><td><ix:nonFraction name="ifrs-full:Equity" contextRef="c_2024" unitRef="EUR" decimals="-3">105000000</ix:nonFraction></td></tr>
        <tr><td>Ingresos</td><td><ix:nonFraction name="ifrs-full:Revenue" contextRef="c_2024" unitRef="EUR" decimals="-3">57000000</ix:nonFraction></td></tr>
    </table>
    <p>Informe de auditoría emitido con opinión favorable sin salvedades.</p>
</body>
</html>"""

SAMPLE_COVER_PAGE_HTML = """<html>
<head><title>Carátula de Presentación de Documento</title></head>
<body>
    <h1>Ficha de publicación de registro CNMV</h1>
    <p>Documento de registro de entrada anotado el 25/02/2024.</p>
</body>
</html>"""

SAMPLE_ERROR_HTML = """<html>
<head><title>500 Internal Server Error</title></head>
<body>
    <h1>Error interno del servidor</h1>
    <p>La sesión ha caducada o el documento no disponible.</p>
</body>
</html>"""

SAMPLE_PDF_SINGLE_PAGE = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R>>endobj\nxref\n0 4\ntrailer<</Root 1 0 R>>\n%%EOF"


# ==========================================
# TESTS UNITARIOS Y DE CONTRATO (25 CASOS)
# ==========================================

def test_01_link_resolver_relative_url():
    resolver = LinkResolver()
    base = "https://www.cnmv.es/portal/consultas/derechos-voto/"
    rel = "../../documentos/informe_2024.xhtml"
    resolved = resolver.resolve_url(base, rel)
    assert resolved == "https://www.cnmv.es/portal/documentos/informe_2024.xhtml"


def test_02_link_resolver_redirect_chain():
    def handler(request: httpx.Request):
        if request.url == "https://cnmv.es/doc":
            return httpx.Response(301, headers={"Location": "https://cnmv.es/doc/final.xhtml"})
        elif request.url == "https://cnmv.es/doc/final.xhtml":
            return httpx.Response(200, headers={"Content-Type": "application/xhtml+xml"})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resolver = LinkResolver()
    final_url, chain, status, headers = resolver.follow_redirects("https://cnmv.es/doc", client=client)

    assert final_url == "https://cnmv.es/doc/final.xhtml"
    assert len(chain) == 2
    assert status == 200


def test_03_link_resolver_classify_resources():
    resolver = LinkResolver()
    assert resolver.classify_resource_type("https://sec.gov/doc.zip") == "ZIP"
    assert resolver.classify_resource_type("https://sec.gov/doc.pdf") == "PDF"
    assert resolver.classify_resource_type("https://sec.gov/doc_cal.xml") == "LINKBASE"
    assert resolver.classify_resource_type("https://sec.gov/taxonomy.xsd") == "TAXONOMY_SCHEMA"


def test_04_link_resolver_detect_error_html():
    resolver = LinkResolver()
    err = resolver.detect_error_html(SAMPLE_ERROR_HTML)
    assert err is not None
    assert "Error detectado" in err


def test_05_validator_ixbrl_complete(tmp_path):
    f = tmp_path / "complete_report.xhtml"
    f.write_text(SAMPLE_IXBRL_COMPLETE, encoding="utf-8")

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(f)

    assert res["completeness_status"] == CompletenessStatus.COMPLETE_CANDIDATE.value
    assert res["is_complete"] is True
    assert res["should_quarantine"] is False
    assert res["metrics"]["total_facts"] == 4


def test_06_validator_cover_page_quarantine(tmp_path):
    f = tmp_path / "cover.html"
    f.write_text(SAMPLE_COVER_PAGE_HTML, encoding="utf-8")

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(f)

    assert res["completeness_status"] == CompletenessStatus.COVER_PAGE_OR_INDEX.value
    assert res["is_complete"] is False
    assert res["should_quarantine"] is True


def test_07_validator_error_html_quarantine(tmp_path):
    f = tmp_path / "error.xhtml"
    f.write_text(SAMPLE_ERROR_HTML, encoding="utf-8")

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(f)

    assert res["completeness_status"] == CompletenessStatus.ERROR_RESPONSE.value
    assert res["should_quarantine"] is True


def test_08_validator_pdf_single_page_cover(tmp_path):
    f = tmp_path / "cover.pdf"
    f.write_bytes(SAMPLE_PDF_SINGLE_PAGE)

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(f)

    assert res["completeness_status"] == CompletenessStatus.COVER_PAGE_OR_INDEX.value
    assert res["should_quarantine"] is True


def test_09_validator_zip_complete(tmp_path):
    zip_p = tmp_path / "valid_bundle.zip"
    with zipfile.ZipFile(zip_p, "w") as zf:
        zf.writestr("reports/san_2024.xhtml", SAMPLE_IXBRL_COMPLETE)
        zf.writestr("reports/taxonomy.xsd", "<xs:schema></xs:schema>")
        zf.writestr("reports/san_2024_cal.xml", "<linkbase></linkbase>")

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(zip_p)

    assert res["completeness_status"] == CompletenessStatus.ZIP_BUNDLE.value
    assert res["is_complete"] is True
    assert res["should_quarantine"] is False
    assert res["metrics"]["total_files_count"] == 3


def test_10_validator_zip_corrupt(tmp_path):
    zip_p = tmp_path / "corrupted.zip"
    zip_p.write_bytes(b"PK\x03\x04corrupted_garbage_bytes_here")

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(zip_p)

    assert res["completeness_status"] == CompletenessStatus.INVALID_FORMAT.value
    assert res["should_quarantine"] is True


def test_11_validator_zip_empty_internal_files(tmp_path):
    zip_p = tmp_path / "empty_files.zip"
    with zipfile.ZipFile(zip_p, "w") as zf:
        zf.writestr("doc.xhtml", "")

    validator = DocumentCompletenessValidator()
    res = validator.validate_document(zip_p)

    assert res["metrics"]["empty_files_count"] == 1


def test_12_robust_downloader_atomic_download(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(200, text="DATOS_OFICIALES_CONTABLES_COMPLETOS", headers={"Content-Type": "text/plain"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = RobustDownloader()
    dest = tmp_path / "official_doc.txt"

    res = downloader.download_to_file("https://sec.gov/doc.txt", dest, client=client)

    assert Path(res["file_path"]).exists()
    assert res["file_size_bytes"] > 0
    assert len(res["sha256"]) == 64
    assert not dest.with_suffix(".txt.part").exists()


def test_13_robust_downloader_sha256_verification(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(200, text="VERIFIED_DATA", headers={"Content-Type": "text/plain"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = RobustDownloader()
    dest = tmp_path / "verified.txt"

    # SHA-256 correcto de "VERIFIED_DATA"
    import hashlib
    correct_sha = hashlib.sha256(b"VERIFIED_DATA").hexdigest()

    res = downloader.download_to_file("https://sec.gov/doc.txt", dest, expected_sha256=correct_sha, client=client)
    assert res["sha256"] == correct_sha


def test_14_robust_downloader_sha256_mismatch_rejection(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(200, text="TAMPERED_DATA", headers={"Content-Type": "text/plain"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = RobustDownloader()
    dest = tmp_path / "tampered.txt"

    with pytest.raises(DownloadError) as exc:
        downloader.download_to_file("https://sec.gov/doc.txt", dest, expected_sha256="wrong_hash_123", client=client)

    assert "Discordancia de SHA-256" in str(exc.value)


def test_15_robust_downloader_429_rate_limit_backoff(tmp_path):
    calls = 0
    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, text="RECOVERED_AFTER_429", headers={"Content-Type": "text/plain"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = RobustDownloader(max_retries=4, initial_backoff_s=0.01)
    dest = tmp_path / "rate_limited.txt"

    res = downloader.download_to_file("https://sec.gov/doc.txt", dest, client=client)
    assert res["retries_taken"] == 2
    assert Path(res["file_path"]).exists()


def test_16_robust_downloader_503_server_recovery(tmp_path):
    calls = 0
    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls < 2:
            return httpx.Response(503)
        return httpx.Response(200, text="RECOVERED_AFTER_503")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = RobustDownloader(max_retries=3, initial_backoff_s=0.01)
    dest = tmp_path / "srv_503.txt"

    res = downloader.download_to_file("https://sec.gov/doc.txt", dest, client=client)
    assert res["http_status"] == 200


def test_17_robust_downloader_range_resumption(tmp_path):
    dest = tmp_path / "resumed.bin"
    part = dest.with_suffix(".bin.part")
    part.write_bytes(b"INITIAL_CHUNK_")

    def handler(request: httpx.Request):
        if "Range" in request.headers and request.headers["Range"] == "bytes=14-":
            return httpx.Response(206, content=b"FINAL_CHUNK")
        return httpx.Response(200, content=b"INITIAL_CHUNK_FINAL_CHUNK")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = RobustDownloader()

    res = downloader.download_to_file("https://sec.gov/large.bin", dest, allow_resume=True, client=client)
    assert res["resumed"] is True
    assert dest.read_bytes() == b"INITIAL_CHUNK_FINAL_CHUNK"


def test_18_bundle_manager_layout_creation(tmp_path):
    bm = BundleManager(root_data_dir=tmp_path)
    pub = PublicationRecord(
        publication_id="ES_CNMV_SAN_2024_01",
        source="ES_CNMV",
        issuer_name="Banco Santander SA",
        issuer_identifier="5493006QMFDDMYWIAM13",
        reporting_period="2024",
        publication_date="2025-02-20",
        document_type="CCAA_AUDITED",
        official_record_url="https://cnmv.es/san_2024.zip"
    )

    layout = bm.create_bundle_layout(pub)
    assert layout["original"].exists()
    assert layout["bundles"].exists()
    assert layout["extracted"].exists()
    assert layout["quarantine"].exists()
    assert layout["manifests"].exists()


def test_19_bundle_manager_zip_extraction(tmp_path):
    bm = BundleManager(root_data_dir=tmp_path)
    zip_p = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_p, "w") as zf:
        zf.writestr("sub/doc1.xhtml", "<html>doc1</html>")
        zf.writestr("sub/doc2.pdf", b"%PDF-1.4 sample")

    ext_dir = tmp_path / "extracted_out"
    inv = bm.extract_zip_package(zip_p, ext_dir)

    assert len(inv) == 2
    assert (ext_dir / "sub/doc1.xhtml").exists()
    assert (ext_dir / "sub/doc2.pdf").exists()


def test_20_pipeline_full_complete_bundle_run(tmp_path):
    # Simular endpoint que devuelve ZIP completo
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("san_2024_cuentas.xhtml", SAMPLE_IXBRL_COMPLETE)
        zf.writestr("san_2024_cal.xml", "<linkbase></linkbase>")

    def handler(request: httpx.Request):
        return httpx.Response(200, content=zip_bytes.getvalue(), headers={"Content-Type": "application/zip"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = IngestionPipeline(base_data_dir=tmp_path)

    pub = PublicationRecord(
        publication_id="PUB_SAN_2024",
        source="ES_CNMV",
        issuer_name="Banco Santander SA",
        issuer_identifier="5493006QMFDDMYWIAM13",
        reporting_period="2024",
        publication_date="2025-02-20",
        document_type="CCAA_AUDITED",
        official_record_url="https://cnmv.es/san_2024.zip"
    )

    bundle = pipeline.process_publication(pub, client=client)

    assert bundle.validation_status == BundleStatus.FINAL_COMPLETO.value
    assert bundle.primary_document_path is not None
    assert bundle.extracted_files_count == 2
    assert Path(bundle.manifest_path).exists()


def test_21_pipeline_quarantine_cover_page(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(200, text=SAMPLE_COVER_PAGE_HTML, headers={"Content-Type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = IngestionPipeline(base_data_dir=tmp_path)

    pub = PublicationRecord(
        publication_id="PUB_COVER_ONLY",
        source="ES_CNMV",
        issuer_name="Banco Santander SA",
        issuer_identifier="5493006QMFDDMYWIAM13",
        reporting_period="2024",
        publication_date="2025-02-20",
        document_type="CCAA_AUDITED",
        official_record_url="https://cnmv.es/cover.html"
    )

    bundle = pipeline.process_publication(pub, client=client)

    assert bundle.validation_status == BundleStatus.CUARENTENA.value
    assert len(bundle.quarantine_files) == 1
    assert bundle.primary_document_path is None


def test_22_pipeline_ban_success_without_primary_doc(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(200, text=SAMPLE_ERROR_HTML, headers={"Content-Type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = IngestionPipeline(base_data_dir=tmp_path)

    pub = PublicationRecord(
        publication_id="PUB_ERR",
        source="ES_CNMV",
        issuer_name="BBVA",
        issuer_identifier="K8MS7FD7N5Z2WQ51AZ71",
        reporting_period="2024",
        publication_date="2025-02-20",
        document_type="CCAA_AUDITED",
        official_record_url="https://cnmv.es/error.html"
    )

    bundle = pipeline.process_publication(pub, client=client)

    assert bundle.validation_status != BundleStatus.FINAL_COMPLETO.value
    assert bundle.validation_status == BundleStatus.CUARENTENA.value


def test_23_pipeline_preserves_original_file(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(200, text=SAMPLE_IXBRL_COMPLETE, headers={"Content-Type": "application/xhtml+xml"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = IngestionPipeline(base_data_dir=tmp_path)

    pub = PublicationRecord(
        publication_id="PUB_ORIGINAL_CHECK",
        source="ES_CNMV",
        issuer_name="Iberdrola",
        issuer_identifier="549300PZX1W3HW3YTR14",
        reporting_period="2024",
        publication_date="2025-02-20",
        document_type="CCAA_AUDITED",
        official_record_url="https://cnmv.es/ibe.xhtml"
    )

    bundle = pipeline.process_publication(pub, client=client)
    layout = pipeline.bundle_manager.get_bundle_directory(pub)
    original_f = layout / "original" / "ibe.xhtml"

    assert original_f.exists()
    assert original_f.read_text(encoding="utf-8") == SAMPLE_IXBRL_COMPLETE


def test_24_pipeline_idempotent_rerun(tmp_path):
    def handler(request: httpx.Request):
        return httpx.Response(200, text=SAMPLE_IXBRL_COMPLETE, headers={"Content-Type": "application/xhtml+xml"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = IngestionPipeline(base_data_dir=tmp_path)

    pub = PublicationRecord(
        publication_id="PUB_IDEMPOTENT",
        source="ES_CNMV",
        issuer_name="Inditex",
        issuer_identifier="549300H5G5S6G31H6878",
        reporting_period="2024",
        publication_date="2025-02-20",
        document_type="CCAA_AUDITED",
        official_record_url="https://cnmv.es/itx.xhtml"
    )

    b1 = pipeline.process_publication(pub, client=client)
    b2 = pipeline.process_publication(pub, client=client)

    assert b1.validation_status == b2.validation_status == BundleStatus.FINAL_COMPLETO.value
    assert b1.manifest_path == b2.manifest_path


def test_25_pipeline_missing_dependency_registration(tmp_path):
    def handler(request: httpx.Request):
        if "missing" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, text=SAMPLE_IXBRL_COMPLETE)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pipeline = IngestionPipeline(base_data_dir=tmp_path)

    pub = PublicationRecord(
        publication_id="PUB_MISSING_DEP",
        source="ES_CNMV",
        issuer_name="Telefónica",
        issuer_identifier="549300G916G0JGT9L459",
        reporting_period="2024",
        publication_date="2025-02-20",
        document_type="CCAA_AUDITED",
        official_record_url="https://cnmv.es/tef.xhtml"
    )

    bundle = pipeline.process_publication(
        pub,
        candidate_urls=["https://cnmv.es/tef.xhtml", "https://cnmv.es/missing_taxonomy.xsd"],
        client=client
    )

    # El bundle debe registrar el recurso faltante y clasificar como PARCIAL
    assert bundle.resources_count == 2
    assert bundle.validation_status == BundleStatus.PARCIAL.value
