"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Generador de Propuestas de Clasificación Asistidas por IA (Label Proposer).

ETAPA A del Flujo Human-in-the-Loop:
Para cada caso no clasificado, en zona gris (score 0.75-0.90) o marcado como
UNRESOLVED_REQUIRES_MANUAL_REVIEW por el auditor forense, genera una propuesta
estructurada con evidencia textual y score de confianza, insertándola en la
cola de revisión humana (DuckDB / CSV) sin modificar el dataset en disco.
"""

import sys
import os
import json
import csv
import re
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import duckdb

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from mod_01_ingestion.src.entity_resolver import EntityResolver, compute_comprehensive_similarity, normalize_cif
from mod_01_ingestion.src.ai_pre_validation_guard import AIPreValidationGuard

DB_PATH = Path("mod_01_ingestion/telemetry/label_review_queue.duckdb")
EXPORTS_DIR = Path("data/catalogs")


class LabelProposer:
    """Generador de propuestas de clasificación para supervisión humana."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.resolver = EntityResolver()
        self.guard = AIPreValidationGuard(self.resolver)
        self._init_db()

    def _init_db(self):
        """Inicializa la tabla DuckDB para la cola de revisión humana."""
        con = duckdb.connect(str(self.db_path))
        con.execute("""
            CREATE TABLE IF NOT EXISTS label_review_queue (
                id VARCHAR PRIMARY KEY,
                file_path VARCHAR,
                ticker_expected VARCHAR,
                year_expected INTEGER,
                entity_detected VARCHAR,
                cif_detected VARCHAR,
                year_detected INTEGER,
                similarity_score DOUBLE,
                proposed_label VARCHAR,
                confidence DOUBLE,
                evidence_text VARCHAR,
                user_decision VARCHAR DEFAULT 'PENDING', -- PENDING | CONFIRMED | CORRECTED | REJECTED
                corrected_label VARCHAR,
                reviewed_at VARCHAR,
                reviewer_note VARCHAR,
                created_at VARCHAR
            )
        """)
        con.close()

    def generate_proposals_from_audit(self, audit_report_path: Path) -> List[Dict[str, Any]]:
        """Genera propuestas a partir de los casos no resueltos o en zona gris de un informe de auditoría."""
        if not audit_report_path.exists():
            raise FileNotFoundError(f"Reporte de auditoría no encontrado: {audit_report_path}")

        with open(audit_report_path, "r", encoding="utf-8") as f:
            audit_data = json.load(f)

        records = audit_data.get("records", [])
        proposals: List[Dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        con = duckdb.connect(str(self.db_path))

        for rec in records:
            file_path = Path(rec["file_path"])
            if not file_path.exists():
                continue

            tax = rec.get("taxonomy", "")
            # Procesar casos en zona gris o no resueltos
            is_unresolved = tax in ("UNRESOLVED_REQUIRES_MANUAL_REVIEW", "UNSEALED_OR_TAMPERED", "WRONG_ENTITY_MISMATCH_WITH_FOLDER", "WRONG_YEAR_UNDECLARED_SUBSTITUTION")
            
            if is_unresolved:
                prop = self._build_single_proposal(file_path, rec)
                proposals.append(prop)

                # Insertar en DuckDB
                con.execute("""
                    INSERT OR REPLACE INTO label_review_queue 
                    (id, file_path, ticker_expected, year_expected, entity_detected, cif_detected, 
                     year_detected, similarity_score, proposed_label, confidence, evidence_text, 
                     user_decision, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """, [
                    prop["id"], prop["file_path"], prop["ticker_expected"], prop["year_expected"],
                    prop["entity_detected"], prop["cif_detected"], prop["year_detected"],
                    prop["similarity_score"], prop["proposed_label"], prop["confidence"],
                    prop["evidence_text"][:500], now_iso
                ])

        con.close()

        # Exportar CSV ordenado por confianza ascendente
        self._export_review_csv(proposals)
        return proposals

    def _build_single_proposal(self, file_path: Path, audit_rec: Dict[str, Any]) -> Dict[str, Any]:
        """Construye una propuesta detallada con evidencia textual."""
        header_text = self.guard._extract_header_text(file_path, max_bytes=300000)
        cif_det = self.guard._extract_cif_from_text(header_text)
        name_det = self.guard._extract_company_name_from_text(header_text)
        year_det = self.guard._extract_fiscal_year_from_text(header_text, file_path)

        ticker_exp = audit_rec.get("folder_ticker") or "UNKNOWN"
        year_exp = audit_rec.get("folder_year") or 0

        exp_entity = self.resolver.get_by_ticker(ticker_exp)
        exp_name = exp_entity.get("name_legal", "") if exp_entity else ""
        exp_cif = exp_entity.get("cif_nif", "") if exp_entity else ""

        sim_score = compute_comprehensive_similarity(name_det or header_text[:400], exp_name, cif_det, exp_cif)

        # Determinar etiqueta propuesta y nivel de confianza
        proposed_label = audit_rec.get("taxonomy", "UNRESOLVED_REQUIRES_MANUAL_REVIEW")
        confidence = 0.85

        if sim_score >= 0.95 and year_det == year_exp:
            proposed_label = "VALID_ORIGINAL_SEALED"
            confidence = 0.98
        elif cif_det and exp_cif and normalize_cif(cif_det) != normalize_cif(exp_cif):
            proposed_label = "WRONG_ENTITY_MISMATCH_WITH_FOLDER"
            confidence = 0.95
        elif year_det and year_exp and year_det != year_exp:
            proposed_label = "WRONG_YEAR_UNDECLARED_SUBSTITUTION"
            confidence = 0.92

        evidence_snippet = header_text[:400].replace("\n", " ").strip() if header_text else "Sin texto extraíble"

        prop_id = f"PROP_{ticker_exp}_{year_exp}_{file_path.stem}"

        return {
            "id": prop_id,
            "file_path": str(file_path.as_posix()),
            "ticker_expected": ticker_exp,
            "year_expected": year_exp,
            "entity_detected": name_det or "NO_DETECTADO",
            "cif_detected": cif_det or "NO_DETECTADO",
            "year_detected": year_det or 0,
            "similarity_score": round(sim_score, 3),
            "proposed_label": proposed_label,
            "confidence": round(confidence, 3),
            "evidence_text": evidence_snippet
        }

    def _export_review_csv(self, proposals: List[Dict[str, Any]]) -> Path:
        """Exporta la cola de revisión en formato CSV ordenado por confianza ascendente."""
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        csv_path = EXPORTS_DIR / f"REVIEW_QUEUE_{ts}.csv"
        csv_latest = EXPORTS_DIR / "REVIEW_QUEUE_LATEST.csv"

        sorted_proposals = sorted(proposals, key=lambda x: x["confidence"])

        fieldnames = [
            "id", "file_path", "ticker_expected", "year_expected",
            "entity_detected", "cif_detected", "year_detected",
            "similarity_score", "proposed_label", "confidence",
            "user_decision", "corrected_label", "reviewer_note", "evidence_text"
        ]

        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for p in sorted_proposals:
                row = dict(p)
                row["user_decision"] = "PENDING"
                row["corrected_label"] = ""
                row["reviewer_note"] = ""
                writer.writerow(row)

        with open(csv_latest, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for p in sorted_proposals:
                row = dict(p)
                row["user_decision"] = "PENDING"
                row["corrected_label"] = ""
                row["reviewer_note"] = ""
                writer.writerow(row)

        print(f"✓ Cola de revisión exportada a CSV: {csv_path}")
        return csv_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generador de Propuestas de Clasificación Asistidas por IA")
    parser.add_argument("--audit-report", help="Ruta al reporte JSON del auditor forense")
    parser.add_argument("--scope", default="data/raw/ES_CNMV", help="Scope para ejecutar")
    args = parser.parse_args()

    proposer = LabelProposer()
    if args.audit_report:
        proposer.generate_proposals_from_audit(Path(args.audit_report))
    else:
        # Localizar último reporte de auditoría si existe
        candidates = sorted(Path("data/raw/ES_CNMV").glob("FORENSIC_AUDIT_REPORT_*.json"))
        if candidates:
            proposer.generate_proposals_from_audit(candidates[-1])
        else:
            print("No se encontró ningún reporte de auditoría previo. Ejecute primero forensic_dataset_auditor.py")
