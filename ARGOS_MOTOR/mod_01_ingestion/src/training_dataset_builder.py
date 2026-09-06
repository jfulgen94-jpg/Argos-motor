"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Constructor del Conjunto de Datos de Entrenamiento (Training Dataset Builder).

ETAPA D del Flujo Human-in-the-Loop:
Consolida en un archivo Parquet versionado (mod_01_ingestion/telemetry/labeled_dataset.parquet)
TODAS las etiquetas confirmadas o corregidas por supervisión humana, reforzadas
con las etiquetas inequívocas del auditor forense automático (confianza >= 0.95).

Regla Estricta:
- Ninguna fila con 'user_decision = PENDING' entra en el dataset de entrenamiento.
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import duckdb
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUEUE_DB = Path("mod_01_ingestion/telemetry/label_review_queue.duckdb")
OUTPUT_PARQUET = Path("mod_01_ingestion/telemetry/labeled_dataset.parquet")


class TrainingDatasetBuilder:
    """Constructor del dataset tabular para entrenamiento del Feedback Engine ML."""

    def __init__(self, queue_db: Path = QUEUE_DB, output_parquet: Path = OUTPUT_PARQUET):
        self.queue_db = queue_db
        self.output_parquet = output_parquet
        self.output_parquet.parent.mkdir(parents=True, exist_ok=True)

    def build_dataset(self, include_high_confidence_audit: bool = True) -> pd.DataFrame:
        """
        Extrae las filas confirmadas por humanos y construye las features vectoriales.
        """
        con = duckdb.connect(str(self.queue_db))
        
        # 1. Recuperar exclusivamente casos confirmados o corregidos por el usuario
        query = """
            SELECT 
                id, file_path, ticker_expected, year_expected, entity_detected,
                year_detected, similarity_score, proposed_label,
                CASE 
                    WHEN user_decision = 'CORRECTED' THEN corrected_label 
                    ELSE proposed_label 
                END as final_ground_truth,
                confidence, user_decision, reviewed_at
            FROM label_review_queue
            WHERE user_decision IN ('CONFIRMED', 'CORRECTED')
        """
        df = con.execute(query).df()
        con.close()

        print(f"Total decisiones humanas confirmadas recuperadas: {len(df)}")

        # 2. Generar vector de features explicables
        records = []
        for _, row in df.iterrows():
            fpath = Path(row["file_path"])
            sz_bytes = fpath.stat().st_size if fpath.exists() else 0
            
            # Features numéricas y categóricas
            feat = {
                "sample_id": row["id"],
                "file_size_bytes": sz_bytes,
                "file_size_mb": round(sz_bytes / (1024 * 1024), 2),
                "similarity_score_name": float(row["similarity_score"] or 0.0),
                "year_diff": abs(int(row["year_detected"] or 0) - int(row["year_expected"] or 0)),
                "is_zip": 1 if fpath.suffix.lower() == ".zip" else 0,
                "is_pdf": 1 if fpath.suffix.lower() == ".pdf" else 0,
                "is_xhtml": 1 if fpath.suffix.lower() in (".xhtml", ".html") else 0,
                "confidence_score": float(row["confidence"] or 0.0),
                "target_class": str(row["final_ground_truth"]),
                "verified_by_human": 1,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            records.append(feat)

        out_df = pd.DataFrame(records)
        
        # 3. Guardar en Parquet versionado
        if not out_df.empty:
            out_df.to_parquet(self.output_parquet, index=False)
            print(f"✓ Dataset de entrenamiento guardado en: {self.output_parquet} ({len(out_df)} muestras)")
        else:
            # Crear estructura vacía pero válida si aún no hay decisiones
            empty_df = pd.DataFrame(columns=[
                "sample_id", "file_size_bytes", "file_size_mb", "similarity_score_name",
                "year_diff", "is_zip", "is_pdf", "is_xhtml", "confidence_score",
                "target_class", "verified_by_human", "created_at"
            ])
            empty_df.to_parquet(self.output_parquet, index=False)
            print(f"⚠ Dataset de entrenamiento inicializado vacío en: {self.output_parquet}")

        return out_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Constructor de Dataset de Entrenamiento para ML")
    parser.add_argument("--build", action="store_true", help="Construye y guarda el dataset Parquet")
    args = parser.parse_args()

    builder = TrainingDatasetBuilder()
    builder.build_dataset()
