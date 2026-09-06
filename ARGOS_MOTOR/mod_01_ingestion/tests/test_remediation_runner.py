"""
STATER MOTOR ARGOS — MOD_01: Test de Integración para RemediationRunner.

Verifica que el runner de remediación:
1. Mueve a cuarentena los archivos clasificados como WRONG_ENTITY o SYNTHETIC_FABRICATED
2. Re-etiqueta los manifiestos de cifras comparativas declaradas
3. Mantiene la cola de DuckDB actualizada y es idempotente
"""

import json
import pytest
from pathlib import Path
from mod_01_ingestion.src.forensic_dataset_auditor import ForensicDatasetAuditor
from mod_01_ingestion.src.remediation_runner import RemediationRunner
from mod_01_ingestion.tests.fixtures.synthetic_fixture_templates import get_sample_synthetic_html


def test_remediation_runner_lifecycle(tmp_path):
    mock_base = tmp_path / "ES_CNMV"
    mock_base.mkdir(parents=True, exist_ok=True)

    pad_text = " Estado Financiero Consolidado y Memoria Explicativa." * 100

    # 1. Crear caso Prosegur en ACS
    acs_dir = mock_base / "2024" / "ACS_Actividades_de_Construccion_SA"
    acs_dir.mkdir(parents=True, exist_ok=True)
    acs_file = acs_dir / "acs_2024_prosegur.xhtml"
    acs_file.write_text(f"<html><body><h1>Prosegur Compañía de Seguridad SA</h1><p>CIF A-28424083</p><p>ejercicio 2024</p><p>{pad_text}</p></body></html>", encoding="utf-8")

    # 2. Crear caso Sintético en BBVA
    bbva_dir = mock_base / "2024" / "BBVA_Banco_Bilbao_Vizcaya_Argentaria_SA"
    bbva_dir.mkdir(parents=True, exist_ok=True)
    bbva_file = bbva_dir / "bbva_2024_synth.xhtml"
    bbva_file.write_text(get_sample_synthetic_html("BBVA", 2024) + pad_text, encoding="utf-8")

    # 3. Crear caso Año comparativo con manifiesto
    ibe_dir = mock_base / "2020" / "IBE_Iberdrola_SA"
    ibe_dir.mkdir(parents=True, exist_ok=True)
    ibe_file = ibe_dir / "ibe_2020_doc.xhtml"
    ibe_file.write_text(f"<html><body><h1>Iberdrola SA</h1><p>CIF A-48010615</p><p>ejercicio cerrado el 31 de diciembre de 2021</p><p>{pad_text}</p></body></html>", encoding="utf-8")
    manifest_ibe = ibe_dir / "ibe_2020_manifest.json"
    manifest_ibe.write_text(json.dumps({"ticker": "IBE", "year": 2020}), encoding="utf-8")

    # Ejecutar auditoría
    auditor = ForensicDatasetAuditor(base_dir=mock_base)
    report = auditor.run_full_audit(output_dir=tmp_path / "reports")
    report_json = tmp_path / "reports" / [f.name for f in (tmp_path / "reports").glob("*.json")][0]

    # Ejecutar remediación
    quarantine_dir = tmp_path / "quarantine"
    db_path = tmp_path / "remediation.duckdb"
    runner = RemediationRunner(db_path=db_path, quarantine_dir=quarantine_dir)
    
    queued = runner.populate_queue_from_audit_report(report_json)
    assert queued >= 3

    results = runner.process_remediation_queue()
    assert results["quarantined"] >= 2  # ACS y BBVA movidos
    assert results["re_tagged_comparative"] >= 1  # IBE re-etiquetado

    # Verificar que los archivos contaminantes ya no están en su carpeta original
    assert not acs_file.exists()
    assert not bbva_file.exists()

    # Verificar que el manifiesto de IBE tiene provenance
    with open(manifest_ibe, "r", encoding="utf-8") as f:
        m_data = json.load(f)
    assert "COMPARATIVE_EXTRACTED" in m_data.get("provenance", "")

    # Idempotencia: segunda ejecución no vuelve a procesar tareas DONE
    results_second = runner.process_remediation_queue()
    assert results_second["total_processed"] == 0
