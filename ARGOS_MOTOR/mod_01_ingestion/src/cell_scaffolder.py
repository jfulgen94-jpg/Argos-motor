"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Generador de las 10 "celdas" de ingesta: 2 universos (MERCADO_CONTINUO fusionado
con IBEX35, BME_GROWTH) x 5 años (2020-2024).

Cada celda es SOLO CONFIGURACIÓN (config/ingestion_cells/{SEGMENT}_{YEAR}/cell.json):
declara su alcance exacto (qué tickers debe cubrir, según el catálogo maestro de 175
empresas) y su estado de cobertura actual (medido contra data/raw/ES_CNMV). No hay
código duplicado por celda: las 10 celdas comparten el mismo runner
(`cell_runner.py`) y los mismos componentes forenses/de alimentación ya existentes
(`forensic_dataset_auditor.py`, `ingest_runner.py`, `remediation_runner.py`).

"Comunicadas pero independientes" se traduce así:
  - Independientes: cada celda puede ejecutarse sola (`cell_runner.py --segment ... --year ...`)
    y su config/estado vive en su propia carpeta, sin acoplarse a las demás.
  - Comunicadas: todas comparten el mismo catálogo maestro, el mismo validador
    forense (ai_pre_validation_guard + document_completeness_validator +
    branch_threshold_validator) y el mismo auditor de dataset
    (forensic_dataset_auditor.py), de modo que un hallazgo de fraude/placeholder
    detectado en una celda usa exactamente la misma regla en las otras 9.

Regla de oro: este scaffolder NUNCA descarga ni inventa nada; solo calcula y
persiste el alcance esperado y la cobertura real ya presente en disco.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

CATALOG_PATH = Path("config/master_universe_es.json")
RAW_ROOT = Path("data/raw/ES_CNMV/INFORMES_ANUALES_COMPLETOS")
CELLS_ROOT = Path("config/ingestion_cells")

YEARS = ["2020", "2021", "2022", "2023", "2024"]
# IBEX35 se fusiona operativamente con MERCADO_CONTINUO: ambos cotizan en el mismo
# mercado regulado (Mercado Continuo/SIBE); IBEX35 es solo el índice selectivo de sus
# 35 valores más líquidos, no un mercado distinto de BME_GROWTH.
SEGMENT_MERGE = {
    "MERCADO_CONTINUO": {"MERCADO_CONTINUO", "IBEX35"},
    "BME_GROWTH": {"BME_GROWTH"},
}

EXPECTED_DOCUMENTS = [
    "cuentas_anuales_consolidadas_auditadas",
    "informe_de_gestion_consolidado",
    "estado_informacion_no_financiera_csrd",
    "informe_anual_gobierno_corporativo_IAGC",
    "informe_anual_remuneraciones_IARC",
]


def load_catalog() -> Dict[str, dict]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["companies"]


def tickers_for_segment(companies: Dict[str, dict], segment: str) -> List[str]:
    wanted_segments = SEGMENT_MERGE[segment]
    return sorted(t for t, info in companies.items() if info.get("segment") in wanted_segments)


def measure_coverage(year: str, tickers: List[str]) -> Dict[str, dict]:
    year_dir = RAW_ROOT / year
    lei_pattern = re.compile(r"[0-9A-Z]{20}")
    coverage = {}
    for ticker in tickers:
        # carpeta canónica real: {TICKER}-{CIF...}; puede no existir todavía.
        matches = list(year_dir.glob(f"{ticker}-*")) if year_dir.exists() else []
        if not matches:
            coverage[ticker] = {"folder_exists": False, "documents_present": []}
            continue
        folder = matches[0]
        present = []
        for doc_key in EXPECTED_DOCUMENTS:
            if doc_key == "cuentas_anuales_consolidadas_auditadas":
                # El bundle ESEF principal se nombra por LEI, no por palabra clave
                # (p.ej. "5493006QMFDDMYWIAM13-20241231-en.xhtml"), así que se detecta
                # por carpeta estándar "informe_financiero_anual_auditado/" con .xhtml/.zip,
                # o por coincidencia literal de la palabra clave en el nombre.
                esef_folder = folder / "informe_financiero_anual_auditado"
                has_esef = esef_folder.exists() and any(
                    f.suffix.lower() in (".xhtml", ".html", ".zip", ".pdf") and lei_pattern.search(f.name.upper())
                    for f in esef_folder.glob("*") if f.is_file()
                )
                has_keyword = any(folder.rglob(f"*{doc_key}*"))
                if has_esef or has_keyword:
                    present.append(doc_key)
            else:
                if any(folder.rglob(f"*{doc_key}*")):
                    present.append(doc_key)
        coverage[ticker] = {
            "folder_exists": True,
            "folder": str(folder),
            "documents_present": present,
            "documents_missing": [d for d in EXPECTED_DOCUMENTS if d not in present],
        }
    return coverage


def build_cell(segment: str, year: str, companies: Dict[str, dict]) -> dict:
    tickers = tickers_for_segment(companies, segment)
    coverage = measure_coverage(year, tickers)
    fully_covered = sum(1 for c in coverage.values() if not c.get("documents_missing") and c["folder_exists"])
    return {
        "cell_id": f"{segment}_{year}",
        "segment": segment,
        "year": year,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_tickers": tickers,
        "expected_ticker_count": len(tickers),
        "expected_documents_per_company": EXPECTED_DOCUMENTS,
        "coverage": coverage,
        "fully_covered_companies": fully_covered,
        "pending_companies": len(tickers) - fully_covered,
        "shared_components": {
            "feeding": ["mod_01_ingestion/src/ingest_runner.py", "mod_01_ingestion/src/es_cnmv_client.py",
                        "mod_01_ingestion/src/bme_growth_client.py", "mod_01_ingestion/src/xbrl_org_client.py"],
            "forensic": ["mod_01_ingestion/src/forensic_dataset_auditor.py",
                         "mod_01_ingestion/src/ai_pre_validation_guard.py",
                         "mod_01_ingestion/src/document_completeness_validator.py",
                         "mod_01_ingestion/src/branch_threshold_validator.py",
                         "mod_01_ingestion/src/remediation_runner.py"],
        },
    }


def main():
    companies = load_catalog()
    CELLS_ROOT.mkdir(parents=True, exist_ok=True)
    summary = []
    for segment in SEGMENT_MERGE:
        for year in YEARS:
            cell = build_cell(segment, year, companies)
            cell_dir = CELLS_ROOT / cell["cell_id"]
            cell_dir.mkdir(parents=True, exist_ok=True)
            (cell_dir / "cell.json").write_text(json.dumps(cell, indent=2, ensure_ascii=False), encoding="utf-8")
            summary.append({
                "cell_id": cell["cell_id"],
                "expected": cell["expected_ticker_count"],
                "fully_covered": cell["fully_covered_companies"],
                "pending": cell["pending_companies"],
            })
            print(f"{cell['cell_id']:<22} esperadas={cell['expected_ticker_count']:>3} "
                  f"completas={cell['fully_covered_companies']:>3} pendientes={cell['pending_companies']:>3}")

    (CELLS_ROOT / "_SUMMARY.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n10 celdas generadas en {CELLS_ROOT}/")


if __name__ == "__main__":
    main()
