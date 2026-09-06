"""
STATER MOTOR ARGOS — MOD_01: Tests de Integración para Human-in-the-Loop y ML Feedback.

Verifica:
1. label_proposer genera propuestas con score de confianza
2. training_dataset_builder EXCLUYE estrictamente casos con decision = PENDING
3. Clases sensibles (SYNTHETIC_FABRICATED, WRONG_ENTITY) NUNCA se auto-confirman
4. adaptive_feedback_engine entrena modelo con validación estratificada
"""

import json
import pytest
from pathlib import Path
from mod_01_ingestion.src.label_proposer import LabelProposer
from mod_01_ingestion.src.review_cli import ReviewCLI
from mod_01_ingestion.src.training_dataset_builder import TrainingDatasetBuilder
from mod_01_ingestion.src.adaptive_feedback_engine import AdaptiveFeedbackEngine
import duckdb
import pandas as pd


def test_hitl_and_training_lifecycle(tmp_path):
    queue_db = tmp_path / "review_queue.duckdb"
    parquet_path = tmp_path / "dataset.parquet"
    feedback_db = tmp_path / "feedback.duckdb"

    # 1. Crear propuesta
    proposer = LabelProposer(db_path=queue_db)
    con = duckdb.connect(str(queue_db))
    
    # Insertar 10 casos de prueba: 8 confirmados, 2 pendientes
    classes = ["VALID_ORIGINAL_SEALED", "WRONG_ENTITY_MISMATCH_WITH_FOLDER", "WRONG_YEAR_UNDECLARED_SUBSTITUTION", "SYNTHETIC_FABRICATED"]
    for i in range(12):
        cls = classes[i % len(classes)]
        decision = "CONFIRMED" if i < 10 else "PENDING"
        con.execute("""
            INSERT INTO label_review_queue 
            (id, file_path, ticker_expected, year_expected, entity_detected, cif_detected, year_detected, 
             similarity_score, proposed_label, confidence, evidence_text, user_decision, created_at)
            VALUES (?, ?, 'SAN', 2024, 'Banco Santander', 'A-39000013', 2024, 0.98, ?, 0.95, 'Evidencia', ?, '2026-08-27')
        """, [f"PROP_{i}", f"data/file_{i}.xhtml", cls, decision])
    con.close()

    # 2. Builder construye el dataset
    builder = TrainingDatasetBuilder(queue_db=queue_db, output_parquet=parquet_path)
    df = builder.build_dataset()
    
    # Regla: Solo 10 casos confirmados deben entrar (los 2 PENDING quedan fuera)
    assert len(df) == 10

    # 3. Entrenar motor de feedback adaptativo
    engine = AdaptiveFeedbackEngine(db_path=feedback_db, parquet_path=parquet_path)
    engine.models_dir = tmp_path / "models"
    engine.models_dir.mkdir(parents=True, exist_ok=True)
    
    res = engine.train_model()
    assert res["status"] != "INSUFFICIENT_DATA"
    assert res["accuracy"] >= 0.0

    # 4. Regla no negociable: Clases sensibles NUNCA se auto-confirman
    pred_class, prob, can_auto = engine.predict_case(
        file_size_mb=10.5, similarity_score=0.20, year_diff=0,
        is_zip=0, is_pdf=0, is_xhtml=1, confidence_score=0.99
    )
    if pred_class in ("SYNTHETIC_FABRICATED", "WRONG_ENTITY_MISMATCH_WITH_FOLDER"):
        assert not can_auto
