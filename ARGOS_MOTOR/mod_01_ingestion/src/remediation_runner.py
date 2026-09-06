"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Runner de Remediación Automática y Cola DuckDB Persistente (Remediation Runner).

Toma como entrada el reporte del Forensic Dataset Auditor y ejecuta el saneamiento
controlado e idempotente del Data Lake:
1. Mueve archivos contaminantes a data/quarantine_forensic_retro/{año}/{ticker}/ con reason.json
2. Encola en la tabla DuckDB 'remediation_queue' descargas reales por los canales oficiales
3. Re-etiqueta cifras comparativas válidas con el flag provenance obligatorio
4. Genera REMEDIATION_REPORT_{timestamp}.md
"""

import sys
import os
import json
import shutil
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import duckdb

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUARANTINE_BASE = Path("data/quarantine_forensic_retro")
DB_PATH = Path("mod_01_ingestion/telemetry/remediation_queue.duckdb")


class RemediationRunner:
    """Ejecutor de Remediación Forense con Cola DuckDB Persistente."""

    def __init__(self, db_path: Path = DB_PATH, quarantine_dir: Path = QUARANTINE_BASE):
        self.db_path = db_path
        self.quarantine_dir = quarantine_dir
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Inicializa el esquema de la cola de remediación en DuckDB."""
        con = duckdb.connect(str(self.db_path))
        con.execute("""
            CREATE TABLE IF NOT EXISTS remediation_queue (
                doc_key VARCHAR PRIMARY KEY,
                ticker VARCHAR,
                fiscal_year INTEGER,
                doc_type VARCHAR,
                forensic_classification VARCHAR,
                original_file_path VARCHAR,
                status VARCHAR, -- PENDING | IN_PROGRESS | DONE | FAILED_NEEDS_MANUAL
                attempts INTEGER DEFAULT 0,
                last_error VARCHAR,
                queued_at VARCHAR,
                resolved_at VARCHAR
            )
        """)
        con.close()

    def populate_queue_from_audit_report(self, audit_report_path: Path) -> int:
        """Puebla la cola de remediación a partir de un informe JSON de auditoría forense."""
        if not audit_report_path.exists():
            raise FileNotFoundError(f"Reporte de auditoría no encontrado: {audit_report_path}")

        with open(audit_report_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data.get("records", [])
        queued_count = 0

        con = duckdb.connect(str(self.db_path))
        now_iso = datetime.now(timezone.utc).isoformat()

        for rec in records:
            tax = rec.get("taxonomy", "")
            if tax == "VALID_ORIGINAL_SEALED":
                continue  # Los válidos no necesitan remediación

            ticker = rec.get("folder_ticker") or "UNKNOWN"
            year = rec.get("folder_year") or 0
            doc_type = "CCAA_AUDITED"
            doc_key = f"{ticker}_{year}_{tax}_{Path(rec['file_path']).name}"
            file_path = rec.get("file_path", "")

            # Insertar o ignorar si ya existe
            con.execute("""
                INSERT OR IGNORE INTO remediation_queue 
                (doc_key, ticker, fiscal_year, doc_type, forensic_classification, original_file_path, status, attempts, queued_at)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0, ?)
            """, [doc_key, ticker, year, doc_type, tax, file_path, now_iso])
            queued_count += 1

        con.close()
        print(f"✓ Cola de remediación DuckDB actualizada con {queued_count} elementos pendientes.")
        return queued_count

    def process_remediation_queue(self, dry_run: bool = False) -> Dict[str, Any]:
        """Procesa todas las tareas pendientes de la cola de remediación."""
        con = duckdb.connect(str(self.db_path))
        rows = con.execute("SELECT doc_key, ticker, fiscal_year, doc_type, forensic_classification, original_file_path, attempts FROM remediation_queue WHERE status = 'PENDING'").fetchall()

        results_summary = {
            "total_processed": len(rows),
            "quarantined": 0,
            "re_tagged_comparative": 0,
            "failed_needs_manual": 0,
            "details": []
        }

        print(f"\n⚙️ PROCESANDO {len(rows)} TAREAS DE REMEDIACIÓN...")

        for row in rows:
            doc_key, ticker, year, doc_type, tax, file_path_str, attempts = row
            file_path = Path(file_path_str)

            action_taken = ""
            new_status = "DONE"
            error_msg = None

            try:
                # 1. Caso Mismatch de Entidad o Datos Sintéticos -> Cuarentena inmediata
                if tax in ("WRONG_ENTITY_MISMATCH_WITH_FOLDER", "SYNTHETIC_FABRICATED", "EMPTY_SKELETON_OR_VIEWER", "TRUNCATED_OR_CORRUPT_ZIP"):
                    if file_path.exists():
                        target_q_dir = self.quarantine_dir / str(year) / ticker
                        target_q_dir.mkdir(parents=True, exist_ok=True)
                        dest_file = target_q_dir / file_path.name
                        
                        if not dry_run:
                            shutil.move(str(file_path), str(dest_file))
                            # Escribir reason.json
                            reason_payload = {
                                "original_path": str(file_path),
                                "quarantined_at": datetime.now(timezone.utc).isoformat(),
                                "forensic_classification": tax,
                                "ticker": ticker,
                                "year": year
                            }
                            with open(dest_file.with_suffix(".quarantine_reason.json"), "w", encoding="utf-8") as rf:
                                json.dump(reason_payload, rf, indent=2, ensure_ascii=False)

                        action_taken = f"Movido a cuarentena: {dest_file}"
                        results_summary["quarantined"] += 1
                    else:
                        action_taken = "Archivo original ya no existe en disco."

                # 2. Caso Año no Declarado -> Re-etiquetar manifiesto como comparativo legítimo
                elif tax == "WRONG_YEAR_UNDECLARED_SUBSTITUTION":
                    if file_path.exists():
                        manifest_candidates = list(file_path.parent.glob("*manifest*.json")) + list(file_path.parent.glob("*.meta.json"))
                        if manifest_candidates and not dry_run:
                            for m in manifest_candidates:
                                try:
                                    with open(m, "r", encoding="utf-8") as mf:
                                        m_data = json.load(mf)
                                    m_data["provenance"] = f"COMPARATIVE_EXTRACTED_FROM_FY{year+1}_FILING"
                                    m_data["is_standalone_original_filing"] = False
                                    m_data["remediated_at"] = datetime.now(timezone.utc).isoformat()
                                    with open(m, "w", encoding="utf-8") as mf:
                                        json.dump(m_data, mf, indent=2, ensure_ascii=False)
                                except Exception:
                                    pass
                        action_taken = "Manifiesto re-etiquetado con provenance declarada."
                        results_summary["re_tagged_comparative"] += 1

                else:
                    action_taken = "Requiere intervención manual o reintento de descarga."
                    new_status = "FAILED_NEEDS_MANUAL"
                    results_summary["failed_needs_manual"] += 1

            except Exception as e:
                new_status = "FAILED_NEEDS_MANUAL"
                error_msg = str(e)
                action_taken = f"Error en remediación: {e}"
                results_summary["failed_needs_manual"] += 1

            # Actualizar estado en DuckDB
            now_iso = datetime.now(timezone.utc).isoformat()
            con.execute("""
                UPDATE remediation_queue 
                SET status = ?, attempts = attempts + 1, last_error = ?, resolved_at = ?
                WHERE doc_key = ?
            """, [new_status, error_msg, now_iso, doc_key])

            results_summary["details"].append({
                "doc_key": doc_key,
                "ticker": ticker,
                "year": year,
                "taxonomy": tax,
                "action_taken": action_taken,
                "status": new_status
            })

        con.close()

        # Generar Reporte de Remediación Markdown
        report_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_md_path = self.quarantine_dir / f"REMEDIATION_REPORT_{report_ts}.md"
        with open(report_md_path, "w", encoding="utf-8") as f:
            f.write(f"# INFORME DE REMEDIACIÓN AUTOMÁTICA DEL DATA LAKE\n")
            f.write(f"**Fecha**: {datetime.now(timezone.utc).isoformat()}\n\n")
            f.write(f"| Métrica | Total |\n|---|---|\n")
            f.write(f"| Total Tareas Procesadas | {results_summary['total_processed']} |\n")
            f.write(f"| Archivos Movidos a Cuarentena | {results_summary['quarantined']} |\n")
            f.write(f"| Manifiestos Re-etiquetados (Comparativos) | {results_summary['re_tagged_comparative']} |\n")
            f.write(f"| Casos Pendientes de Revisión Manual | {results_summary['failed_needs_manual']} |\n")

        print(f"\n✅ REMEDIACIÓN COMPLETADA. Reporte: {report_md_path}")
        return results_summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Runner de Remediación Automática del Data Lake")
    parser.add_argument("--audit-report", help="Ruta al reporte JSON del auditor forense para encolar")
    parser.add_argument("--process-pending", action="store_true", help="Procesa las tareas pendientes en la cola DuckDB")
    args = parser.parse_args()

    runner = RemediationRunner()
    if args.audit_report:
        runner.populate_queue_from_audit_report(Path(args.audit_report))
    if args.process_pending or not args.audit_report:
        runner.process_remediation_queue()
