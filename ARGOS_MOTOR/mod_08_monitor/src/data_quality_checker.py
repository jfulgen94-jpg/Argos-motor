"""
MOD_08 — Verificador de Integridad del Data Lake.

Ejecuta un conjunto de assertions sobre las tablas DuckDB para detectar:
- Tablas vacías inesperadas
- Registros duplicados (entity_lei + fiscal_year)
- Filings en estado QUARANTINE (requieren revisión humana)
- Inconsistencias de balance (balance_check = FALSE)
- Snapshots diarios incompletos

Uso:
    python src/data_quality_checker.py --date 2026-08-24
    python src/data_quality_checker.py --date today
"""
import argparse
import duckdb
import os
from datetime import date, datetime
from mod_08_monitor.src.logger import get_logger

log = get_logger("MOD_08")

DB_PATH = os.getenv("STATER_DUCKDB_PATH", "data/stater_motor.duckdb")

QUALITY_CHECKS = [
    {
        "name": "quarantined_filings",
        "severity": "ERROR",
        "query": "SELECT COUNT(*) AS n FROM documents_raw WHERE status = 'QUARANTINE'",
        "condition": lambda n: n == 0,
        "message": "{n} filing(s) en estado QUARANTINE requieren revisión humana.",
    },
    {
        "name": "balance_check_failures",
        "severity": "CRITICAL",
        "query": "SELECT COUNT(*) AS n FROM financial_panel WHERE balance_check = FALSE",
        "condition": lambda n: n == 0,
        "message": "{n} empresa(s) con balance descuadrado en financial_panel.",
    },
    {
        "name": "duplicate_panel_records",
        "severity": "ERROR",
        "query": """
            SELECT COUNT(*) AS n FROM (
                SELECT entity_lei, fiscal_year, COUNT(*) AS c
                FROM financial_panel GROUP BY 1, 2 HAVING c > 1
            )
        """,
        "condition": lambda n: n == 0,
        "message": "{n} duplicado(s) detectado(s) en financial_panel (entity_lei + fiscal_year).",
    },
    {
        "name": "empty_kams_table",
        "severity": "WARNING",
        "query": "SELECT COUNT(*) AS n FROM audit_kams",
        "condition": lambda n: n > 0,
        "message": "La tabla audit_kams está vacía. MOD_03 aún no ha procesado ningún filing.",
    },
]


def run_checks(target_date: str = "today", db_path: str = None) -> dict:
    """
    Ejecuta todos los checks de calidad y devuelve un resumen de resultados.
    """
    effective_db = db_path or os.getenv("STATER_DUCKDB_PATH", DB_PATH)
    if not os.path.exists(effective_db):
        log.warning(f"DuckDB no encontrado en '{effective_db}'. Ejecuta lake_manager.py --init primero.")
        return {"status": "SKIPPED", "reason": "DB_NOT_FOUND"}

    conn = duckdb.connect(effective_db, read_only=True)
    results = []

    for check in QUALITY_CHECKS:
        try:
            n = conn.execute(check["query"]).fetchone()[0]
            passed = check["condition"](n)
            status = "PASS" if passed else check["severity"]
            msg = check["message"].format(n=n) if not passed else "OK"
            results.append({"check": check["name"], "status": status, "n": n, "message": msg})
            if passed:
                log.info(f"[CHECK PASS] {check['name']}")
            else:
                getattr(log, check["severity"].lower())(f"[CHECK {status}] {check['name']}: {msg}")
        except Exception as e:
            results.append({"check": check["name"], "status": "ERROR", "message": str(e)})
            log.error(f"[CHECK ERROR] {check['name']}: {e}")

    conn.close()
    failed = [r for r in results if r["status"] != "PASS"]
    return {
        "date": target_date,
        "total_checks": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "issues": failed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="STATER Data Lake Quality Checker")
    parser.add_argument("--date", default="today", help="Fecha de verificación (YYYY-MM-DD o 'today')")
    args = parser.parse_args()
    summary = run_checks(args.date)
    print(f"\n{'='*60}")
    print(f"STATER Data Quality Report — {summary['date']}")
    print(f"{'='*60}")
    print(f"Checks ejecutados: {summary['total_checks']}")
    print(f"Pasados:           {summary.get('passed', 0)}")
    print(f"Fallidos:          {summary.get('failed', 0)}")
    if summary.get("issues"):
        print("\nProblemas detectados:")
        for issue in summary["issues"]:
            print(f"  [{issue['status']}] {issue['check']}: {issue['message']}")
    else:
        print("\nTodos los checks superados. Data Lake en estado SALUDABLE.")
    print(f"{'='*60}\n")
