"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Interfaz de Supervisión Humana por CLI (Review CLI).

ETAPA C del Flujo Human-in-the-Loop:
Permite al usuario revisar de forma ágil e interactiva las propuestas de clasificación
generadas por la IA, o importar revisiones masivas realizadas en hoja de cálculo (CSV).

Modos de Uso:
1. Interactivo por terminal: python -m mod_01_ingestion.src.review_cli --next
2. Importación por lotes:    python -m mod_01_ingestion.src.review_cli --import-reviewed-csv data/catalogs/REVIEW_QUEUE_LATEST.csv
3. Estadísticas de revisión: python -m mod_01_ingestion.src.review_cli --stats
"""

import sys
import os
import csv
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import duckdb

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path("mod_01_ingestion/telemetry/label_review_queue.duckdb")

TAXONOMY_OPTIONS = [
    "VALID_ORIGINAL_SEALED",
    "VALID_COMPARATIVE_DECLARED",
    "WRONG_ENTITY_MISMATCH_WITH_FOLDER",
    "WRONG_YEAR_UNDECLARED_SUBSTITUTION",
    "SYNTHETIC_FABRICATED",
    "EMPTY_SKELETON_OR_VIEWER",
    "TRUNCATED_OR_CORRUPT_ZIP",
    "UNSEALED_OR_TAMPERED",
    "DUPLICATE_CONFLICTING_HASH",
    "UNRESOLVED_REQUIRES_MANUAL_REVIEW"
]


class ReviewCLI:
    """Consola interactiva de supervisión de etiquetas regulatorias."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        if not self.db_path.exists():
            from mod_01_ingestion.src.label_proposer import LabelProposer
            LabelProposer(db_path=self.db_path)

    def interactive_review(self, limit: int = 50):
        """Modo interactivo terminal para revisar propuestas pendientes."""
        con = duckdb.connect(str(self.db_path))
        query = """
            SELECT id, file_path, ticker_expected, year_expected, entity_detected, 
                   year_detected, similarity_score, proposed_label, confidence, evidence_text
            FROM label_review_queue
            WHERE user_decision = 'PENDING'
            ORDER BY confidence ASC
            LIMIT ?
        """
        rows = con.execute(query, [limit]).fetchall()
        con.close()

        if not rows:
            print("✓ No hay propuestas pendientes de revisión en la cola. ¡Todo al día!")
            return

        print("=" * 80)
        print(f"📋 SESIÓN DE REVISIÓN HUMANA (HUMAN-IN-THE-LOOP) — {len(rows)} Casos Pendientes")
        print("Instrucciones: [C]onfirmar propuesta | [R]echazar | [E]ditar etiqueta | [S]altar | [Q] Salir")
        print("=" * 80)

        for idx, row in enumerate(rows, 1):
            prop_id, fpath, t_exp, y_exp, ent_det, y_det, sim_score, prop_label, conf, evid = row
            
            print(f"\n[{idx}/{len(rows)}] ─── Caso: {prop_id} ───")
            print(f"  • Archivo:             {fpath}")
            print(f"  • Esperado en Carpeta: {t_exp} ({y_exp})")
            print(f"  • Detectado en Doc:    {ent_det} (Año: {y_det}) [Similitud: {sim_score:.2f}]")
            print(f"  • Propuesta IA:        \033[1m{prop_label}\033[0m (Confianza: {conf:.2f})")
            print(f"  • Evidencia:           \"{evid[:180]}...\"")
            
            choice = input("\n  ➤ Acción [C/r/e/s/q]: ").strip().lower()
            
            if choice == "q":
                print("Sesión de revisión guardada e interrumpida por el usuario.")
                break
            elif choice in ("c", ""):
                self._record_decision(prop_id, "CONFIRMED", prop_label, note="Confirmado por CLI")
                print(f"  ✓ Confirmado como: {prop_label}")
            elif choice == "r":
                self._record_decision(prop_id, "REJECTED", "UNRESOLVED_REQUIRES_MANUAL_REVIEW", note="Rechazado por usuario")
                print("  ✗ Rechazado.")
            elif choice == "e":
                print("\n  Opciones de taxonomía:")
                for o_idx, opt in enumerate(TAXONOMY_OPTIONS, 1):
                    print(f"    {o_idx}. {opt}")
                sel = input("  Seleccione número (1-10): ").strip()
                try:
                    chosen_tax = TAXONOMY_OPTIONS[int(sel) - 1]
                    self._record_decision(prop_id, "CORRECTED", chosen_tax, note="Corregido manualmente en CLI")
                    print(f"  ✓ Corregido a: {chosen_tax}")
                except Exception:
                    print("  ⚠ Opción inválida, caso saltado.")
            elif choice == "s":
                print("  ⏭ Caso saltado por ahora.")
                continue

    def import_reviewed_csv(self, csv_path: Path):
        """Importa un CSV editado por el usuario con las decisiones humanas confirmadas."""
        if not csv_path.exists():
            raise FileNotFoundError(f"Archivo CSV no encontrado: {csv_path}")

        con = duckdb.connect(str(self.db_path))
        imported_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                decision = row.get("user_decision", "PENDING").strip().upper()
                if decision in ("CONFIRMED", "CORRECTED", "REJECTED"):
                    prop_id = row.get("id")
                    corrected_label = row.get("corrected_label") or row.get("proposed_label")
                    note = row.get("reviewer_note", "Importado desde CSV")

                    con.execute("""
                        UPDATE label_review_queue
                        SET user_decision = ?, corrected_label = ?, reviewed_at = ?, reviewer_note = ?
                        WHERE id = ?
                    """, [decision, corrected_label, now_iso, note, prop_id])
                    imported_count += 1

        con.close()
        print(f"✓ Importadas con éxito {imported_count} decisiones humanas desde {csv_path}")

    def _record_decision(self, prop_id: str, decision: str, corrected_label: str, note: str = ""):
        """Persiste inmediatamente la decisión humana en DuckDB."""
        con = duckdb.connect(str(self.db_path))
        now_iso = datetime.now(timezone.utc).isoformat()
        con.execute("""
            UPDATE label_review_queue
            SET user_decision = ?, corrected_label = ?, reviewed_at = ?, reviewer_note = ?
            WHERE id = ?
        """, [decision, corrected_label, now_iso, note, prop_id])
        con.close()

    def print_stats(self):
        """Muestra estadísticas actuales del estado de revisión."""
        con = duckdb.connect(str(self.db_path))
        stats = con.execute("""
            SELECT user_decision, COUNT(*) 
            FROM label_review_queue 
            GROUP BY user_decision
        """).fetchall()
        con.close()

        print("\n📊 ESTADO ACTUAL DE LA COLA DE REVISIÓN:")
        for dec, cnt in stats:
            print(f"  • {dec}: {cnt} casos")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLI de Supervisión Humana (Human-in-the-Loop)")
    parser.add_argument("--next", action="store_true", help="Inicia sesión interactiva de revisión")
    parser.add_argument("--import-reviewed-csv", help="Importa decisiones desde archivo CSV editado")
    parser.add_argument("--stats", action="store_true", help="Muestra estadísticas de la cola de revisión")
    args = parser.parse_args()

    cli = ReviewCLI()
    if args.import_reviewed_csv:
        cli.import_reviewed_csv(Path(args.import_reviewed_csv))
    elif args.stats:
        cli.print_stats()
    else:
        cli.interactive_review()
