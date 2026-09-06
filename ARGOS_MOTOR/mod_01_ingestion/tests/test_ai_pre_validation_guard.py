"""
STATER MOTOR ARGOS — MOD_01: Tests Unitarios para AIPreValidationGuard.

Verifica que el guardián de pre-ingesta rechaza con códigos específicos:
- Contenido sintético generado artificialmente
- Discordancias de ejercicio fiscal (2021 en 2020)
- Discordancias de identidad jurídica (CIF de otra empresa)
- Archivos corruptos o skeletons
"""

import pytest
from pathlib import Path
from mod_01_ingestion.src.ai_pre_validation_guard import AIPreValidationGuard
from mod_01_ingestion.tests.fixtures.synthetic_fixture_templates import get_sample_synthetic_html


def test_guard_rejects_synthetic_content(tmp_path):
    """El guardián debe detectar y rechazar patrones del generador sintético."""
    guard = AIPreValidationGuard()
    synth_file = tmp_path / "san_2024_synthetic.xhtml"
    synth_file.write_text(get_sample_synthetic_html("SAN", 2024), encoding="utf-8")

    res = guard.validate_staging_resource(synth_file, expected_ticker="SAN", expected_year=2024)
    assert not res["is_valid"]
    assert res["rejection_code"] == "SYNTHETIC_FABRICATED"


def test_guard_rejects_wrong_year(tmp_path):
    """Rechaza un documento cuyo dictamen certifica 2021 cuando se solicitó 2020."""
    guard = AIPreValidationGuard()
    doc_file = tmp_path / "ibe_2021_doc.xhtml"
    html_content = """
    <html><body>
    <h1>Iberdrola SA - Cuentas Anuales Consolidadas</h1>
    <p>CIF A-48010615</p>
    <p>Dictamen de auditoría del ejercicio cerrado el 31 de diciembre de 2021</p>
    </body></html>
    """
    doc_file.write_text(html_content, encoding="utf-8")

    res = guard.validate_staging_resource(doc_file, expected_ticker="IBE", expected_year=2020, allow_declared_comparative=False)
    assert not res["is_valid"]
    assert res["rejection_code"] == "WRONG_YEAR_UNDECLARED_SUBSTITUTION"


def test_guard_rejects_entity_mismatch(tmp_path):
    """Rechaza un documento de Prosegur colocado en la carpeta de ACS."""
    guard = AIPreValidationGuard()
    doc_file = tmp_path / "prosegur_in_acs.xhtml"
    html_content = """
    <html><body>
    <h1>Prosegur Compañía de Seguridad SA</h1>
    <p>NIF A-28424083</p>
    <p>Dictamen del ejercicio terminado a 31 de diciembre de 2024</p>
    </body></html>
    """
    doc_file.write_text(html_content, encoding="utf-8")

    # Esperamos ACS (CIF A-28004885)
    res = guard.validate_staging_resource(doc_file, expected_ticker="ACS", expected_year=2024)
    assert not res["is_valid"]
    assert res["rejection_code"] == "WRONG_ENTITY_MISMATCH_WITH_FOLDER"


def test_guard_accepts_valid_document(tmp_path):
    """Acepta un documento legítimo que coincide en CIF, año y tipo, con contenido
    y tamaño realistas (no un fragmento de prueba trivial), para ejercer también
    el umbral físico/estructural de branch_threshold_validator."""
    guard = AIPreValidationGuard()
    doc_file = tmp_path / "san_2024_valid.xhtml"
    padding = (
        "Balance consolidado de situación. Cuenta de pérdidas y ganancias consolidada. "
        "Estado de flujos de efectivo consolidado. Memoria consolidada y notas explicativas "
        "a las cuentas anuales conforme a las Normas Internacionales de Información Financiera. "
    ) * 120
    html_content = f"""
    <html><body>
    <h1>Banco Santander, S.A.</h1>
    <p>NIF A-39000013</p>
    <p>Informe de Auditoría de Cuentas Anuales Consolidadas del ejercicio terminado a 31 de diciembre de 2024</p>
    <p>{padding}</p>
    </body></html>
    """
    doc_file.write_text(html_content, encoding="utf-8")

    res = guard.validate_staging_resource(doc_file, expected_ticker="SAN", expected_year=2024)
    assert res["is_valid"]
    assert res["detected_metadata"]["ticker"] == "SAN"


def test_guard_rejects_lorem_ipsum_placeholder(tmp_path):
    """
    Test de regresión (auditoría forense 2026-08-27): un documento de ~17 KB con
    texto de relleno 'Lorem ipsum dolor sit amet' fue sellado y aceptado como
    INFORME_GESTION válido de Banco Santander FY2024 antes de esta corrección.
    El guardián debe rechazarlo explícitamente, sin importar que la identidad
    (CIF) y el año coincidan.
    """
    guard = AIPreValidationGuard()
    doc_file = tmp_path / "san_2024_informe_de_gestion_consolidado.xhtml"
    doc_file.write_text(
        "<html><body><h1>Informe de Gestión Consolidado</h1>"
        "<p>NIF A-39000013</p>"
        "<p>Evolución de los negocios y situación financiera.</p>"
        " Lorem ipsum dolor sit amet." * 600 +
        "</body></html>",
        encoding="utf-8",
    )

    res = guard.validate_staging_resource(
        doc_file, expected_ticker="SAN", expected_year=2024, expected_doc_type="INFORME_GESTION"
    )
    assert not res["is_valid"]
    assert res["rejection_code"] == "SYNTHETIC_FABRICATED"


def test_branch_threshold_rejects_undersized_document(tmp_path):
    """Un documento auténtico en tema pero demasiado corto/incompleto para su
    rama documental (por debajo del umbral físico/estructural) debe rechazarse,
    aunque no contenga texto de relleno detectable."""
    guard = AIPreValidationGuard()
    doc_file = tmp_path / "san_2024_iagc_too_short.xhtml"
    doc_file.write_text(
        "<html><body><h1>Informe Anual de Gobierno Corporativo</h1>"
        "<p>NIF A-39000013</p><p>Resumen breve.</p></body></html>",
        encoding="utf-8",
    )

    res = guard.validate_staging_resource(
        doc_file, expected_ticker="SAN", expected_year=2024, expected_doc_type="IAGC"
    )
    assert not res["is_valid"]
    assert res["rejection_code"] == "BELOW_MINIMUM_THRESHOLD"
