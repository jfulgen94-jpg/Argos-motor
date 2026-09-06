"""
STATER MOTOR ARGOS — MOD_01: Test de Integración para ForensicDatasetAuditor.

Crea un mini-dataset simulado en tmp_path con:
1. Un archivo válido con manifiesto y sellado correcto (VALID_ORIGINAL_SEALED)
2. Un archivo con entidad equivocada (Prosegur en ACS)
3. Un archivo con año 2021 en carpeta 2020 sin declarar
4. Un archivo generado con plantilla sintética (SYNTHETIC_FABRICATED)

Verifica que el auditor clasifica cada uno exactamente según su taxonomía.
"""

import json
import hashlib
import pytest
from pathlib import Path
from mod_01_ingestion.src.forensic_dataset_auditor import ForensicDatasetAuditor
from mod_01_ingestion.tests.fixtures.synthetic_fixture_templates import get_sample_synthetic_html


def test_forensic_auditor_on_mock_dataset(tmp_path):
    """Verifica la clasificación forense de los 4 casos arquetípicos."""
    mock_base = tmp_path / "ES_CNMV"
    mock_base.mkdir(parents=True, exist_ok=True)

    # 1. Caso Válido: SAN 2024
    san_dir = mock_base / "2024" / "SAN_Banco_Santander_SA"
    san_dir.mkdir(parents=True, exist_ok=True)
    san_file = san_dir / "san_2024_cuentas_anuales.xhtml"
    pad_text = " Estado Financiero Consolidado y Memoria Explicativa." * 100
    san_content = f"<html><body><h1>Banco Santander SA</h1><p>CIF A-39000013</p><p>ejercicio cerrado el 31 de diciembre de 2024</p><p>{pad_text}</p></body></html>"
    san_file.write_text(san_content, encoding="utf-8")
    san_sha = hashlib.sha256(san_file.read_bytes()).hexdigest()
    
    # Crear manifiesto válido para SAN
    manifest_san = san_dir / "san_2024_manifest.json"
    manifest_san.write_text(json.dumps({"sha256": san_sha, "ticker": "SAN"}), encoding="utf-8")

    # 2. Caso Entidad Equivocada: Prosegur en ACS 2024
    acs_dir = mock_base / "2024" / "ACS_Actividades_de_Construccion_SA"
    acs_dir.mkdir(parents=True, exist_ok=True)
    acs_file = acs_dir / "acs_2024_report.xhtml"
    acs_content = f"<html><body><h1>Prosegur Compañía de Seguridad SA</h1><p>CIF A-28424083</p><p>ejercicio 2024</p><p>{pad_text}</p></body></html>"
    acs_file.write_text(acs_content, encoding="utf-8")

    # 3. Caso Año no Declarado: 2021 en carpeta 2020 de IBE
    ibe_dir = mock_base / "2020" / "IBE_Iberdrola_SA"
    ibe_dir.mkdir(parents=True, exist_ok=True)
    ibe_file = ibe_dir / "ibe_2020_doc.xhtml"
    ibe_content = f"<html><body><h1>Iberdrola SA</h1><p>CIF A-48010615</p><p>ejercicio cerrado el 31 de diciembre de 2021</p><p>{pad_text}</p></body></html>"
    ibe_file.write_text(ibe_content, encoding="utf-8")

    # 4. Caso Sintético: Plantilla fabricada en BBVA 2024
    bbva_dir = mock_base / "2024" / "BBVA_Banco_Bilbao_Vizcaya_Argentaria_SA"
    bbva_dir.mkdir(parents=True, exist_ok=True)
    bbva_file = bbva_dir / "bbva_2024_synth.xhtml"
    bbva_file.write_text(get_sample_synthetic_html("BBVA", 2024) + pad_text, encoding="utf-8")

    # Ejecutar auditor
    auditor = ForensicDatasetAuditor(base_dir=mock_base)
    report = auditor.run_full_audit(output_dir=tmp_path / "reports")

    records = {Path(r["file_path"]).name: r for r in report["records"]}

    assert records["san_2024_cuentas_anuales.xhtml"]["taxonomy"] == "VALID_ORIGINAL_SEALED"
    assert records["acs_2024_report.xhtml"]["taxonomy"] == "WRONG_ENTITY_MISMATCH_WITH_FOLDER"
    assert records["ibe_2020_doc.xhtml"]["taxonomy"] == "WRONG_YEAR_UNDECLARED_SUBSTITUTION"
    assert records["bbva_2024_synth.xhtml"]["taxonomy"] == "SYNTHETIC_FABRICATED"
