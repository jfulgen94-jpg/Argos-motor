"""
Pruebas unitarias y de integración para IngestRunner (MOD_01 Multi-Year).
"""
import io
import zipfile
import pytest
import httpx
from pathlib import Path
from mod_01_ingestion.src.ingest_runner import IngestRunner
from mod_04_data_lake.src.lake_manager import LakeManager


def test_ingest_runner_init():
    runner = IngestRunner(dry_run=True)
    assert runner.dry_run is True
    assert runner.edgar is not None
    assert runner.oam_router is not None


def test_ingest_runner_load_universe():
    runner = IngestRunner(dry_run=True)
    universe = runner.load_universe()
    assert "markets" in universe
    assert "US" in universe["markets"]
    assert "ES" in universe["markets"]


def test_ingest_eu_company_requires_real_es_documents(tmp_path):
    db_file = tmp_path / "test_ingest.duckdb"
    runner = IngestRunner(db_path=str(db_file), dry_run=False)

    res = runner.ingest_eu_company(
        market_code="ES",
        ticker="SAN",
        entity_lei="5493006QMFDDMYWIAM13",
        company_name="Banco Santander SA",
        fiscal_year=2024
    )

    assert res is None


def test_ingest_es_annual_package_downloads_and_registers_all_documents(tmp_path):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr(
            "san_2024_report.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:ifrs-full="http://xbrl.ifrs.org/taxonomy/2023-03-23/ifrs-full" xmlns:xbrli="http://www.xbrl.org/2003/instance">
<body>
<xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="lei">5493006QMFDDMYWIAM13</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:unit id="EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
<h1>Cuentas anuales consolidadas</h1>
<p>Informe de auditoría</p>
<table>
<tr><td><ix:nonFraction name="ifrs-full:Assets" contextRef="c1" unitRef="EUR">10</ix:nonFraction></td></tr>
<tr><td><ix:nonFraction name="ifrs-full:EquityAndLiabilities" contextRef="c1" unitRef="EUR">10</ix:nonFraction></td></tr>
<tr><td><ix:nonFraction name="ifrs-full:Equity" contextRef="c1" unitRef="EUR">4</ix:nonFraction></td></tr>
</table>
</body></html>"""
        )
        zf.writestr("san_2024_cor.xsd", "<xs:schema></xs:schema>")

    # NOTA: el relleno de estos documentos de prueba usa contenido regulatorio
    # real y repetido (NUNCA "Lorem ipsum" ni texto simulado genérico), porque
    # document_completeness_validator.py rechaza y cuarentena expresamente
    # cualquier documento con patrones de texto de relleno detectables
    # (véase SYNTHETIC_FIXTURE_PATTERNS), tal y como debe hacer en producción.
    gestion_tail = (
        " Durante el ejercicio, el Grupo ha mantenido su política de gestión de "
        "riesgo de liquidez, riesgo de crédito y riesgo de mercado mediante "
        "instrumentos financieros derivados de cobertura, y ha ejecutado sus "
        "programas de acciones propias y autocartera conforme a la legislación "
        "mercantil vigente."
    ) * 40
    csrd_tail = (
        " El Grupo reporta su información sobre cuestiones medioambientales, "
        "las emisiones de gases de efecto invernadero de alcance 1, 2 y 3, y su "
        "adecuación a la taxonomía europea de actividades elegibles en términos "
        "de turnover, capex y opex, así como las cuestiones sociales y relativas "
        "al personal y su política de derechos humanos y lucha contra la corrupción."
    ) * 40
    iagc_tail = (
        " La estructura del accionariado y las participaciones significativas se "
        "detallan junto con la composición del consejo de administración, sus "
        "consejeros ejecutivos e independientes, la comisión de auditoría, la "
        "comisión de nombramientos y los sistemas de control interno (SCIIF)."
    ) * 40
    iarc_tail = (
        " La política de remuneraciones del consejo detalla la remuneración fija, "
        "la retribución variable anual devengada, los planes de acciones y los "
        "sistemas de ahorro a largo plazo aprobados por la Junta General."
    ) * 40
    gestion_doc = f"<html><body><h1>Informe de Gestión Consolidado</h1><p>Evolución de los negocios y situación económica. Principales riesgos e incertidumbres. Investigación, desarrollo e innovación.</p>{gestion_tail}</body></html>"
    csrd_doc = f"<html><body><h1>Estado de Información No Financiera</h1><p>CSRD y sostenibilidad del grupo.</p>{csrd_tail}</body></html>"
    iagc_doc = f"<html><body><h1>Informe Anual de Gobierno Corporativo</h1><p>IAGC del emisor.</p>{iagc_tail}</body></html>"
    iarc_doc = f"<html><body><h1>Informe Anual sobre Remuneraciones de los Consejeros</h1><p>IARC del ejercicio.</p>{iarc_tail}</body></html>"

    def handler(request: httpx.Request):
        url = str(request.url)
        if url.endswith("esef.zip"):
            return httpx.Response(200, content=zip_bytes.getvalue(), headers={"Content-Type": "application/zip"})
        if url.endswith("gestion.xhtml"):
            return httpx.Response(200, text=gestion_doc, headers={"Content-Type": "application/xhtml+xml"})
        if url.endswith("csrd.xhtml"):
            return httpx.Response(200, text=csrd_doc, headers={"Content-Type": "application/xhtml+xml"})
        if url.endswith("iagc.xhtml"):
            return httpx.Response(200, text=iagc_doc, headers={"Content-Type": "application/xhtml+xml"})
        if url.endswith("iarc.xhtml"):
            return httpx.Response(200, text=iarc_doc, headers={"Content-Type": "application/xhtml+xml"})
        return httpx.Response(404)

    db_file = tmp_path / "test_ingest.duckdb"
    runner = IngestRunner(db_path=str(db_file), dry_run=False)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    package = runner.ingest_es_annual_package(
        ticker="SAN",
        fiscal_year=2024,
        entity_lei="5493006QMFDDMYWIAM13",
        company_name="Banco Santander SA",
        document_urls={
            "ESEF_PACKAGE": "https://www.cnmv.es/docs/san_2024_esef.zip",
            "INFORME_GESTION": "https://www.cnmv.es/docs/san_2024_gestion.xhtml",
            "EINF_CSRD": "https://www.cnmv.es/docs/san_2024_csrd.xhtml",
            "IAGC": "https://www.cnmv.es/docs/san_2024_iagc.xhtml",
            "IARC": "https://www.cnmv.es/docs/san_2024_iarc.xhtml",
        },
        client=client,
    )

    assert package["package_status"] == "FINAL_COMPLETO"
    assert package["downloaded_count"] == 5
    assert package["quarantined_count"] == 0
    assert Path(package["manifest_path"]).exists()

    docs_by_type = {doc["doc_type"]: doc for doc in package["documents"]}
    assert docs_by_type["ESEF_PACKAGE"]["file_path"].endswith(".zip")
    assert docs_by_type["ESEF_PACKAGE"]["extracted_files_count"] == 2

    lake = LakeManager(db_path=str(db_file))
    stored = lake.get_document_raw("ES_CNMV_5493006QMFDDMYWIAM13_2024_IAGC")
    assert stored is not None
    assert stored["ticker"] == "SAN"


def test_ingest_eu_historical_multiyear(tmp_path):
    db_file = tmp_path / "test_hist.duckdb"
    runner = IngestRunner(db_path=str(db_file), dry_run=False)

    docs = runner.ingest_eu_historical(
        market_code="ES",
        ticker="IBE",
        entity_lei="549300PZX1W3HW3YTR14",
        company_name="Iberdrola SA",
        start_year=2019,
        end_year=2024
    )

    assert docs == []


def test_ingest_batch_execution(tmp_path):
    db_file = tmp_path / "test_batch.duckdb"
    runner = IngestRunner(db_path=str(db_file), dry_run=False)

    report = runner.ingest_batch(market_filter="ES", limit=3, fiscal_year=2024)
    assert report["module"] == "MOD_01_INGESTION_HISTORICAL"
    assert report["total_filings_ingested"] == 0
    assert report["errors"] == 3
