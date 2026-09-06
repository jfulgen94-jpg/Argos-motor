"""
STATER MOTOR ARGOS — MOD_04: Data Lake Manager.
Gestiona la base de datos DuckDB embebida y los archivos Parquet en disco.
Proporciona operaciones ACID locales y funciones de exportación/ingesta.
"""
from pathlib import Path
import os
import duckdb
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

# Rutas por defecto ancladas a la raíz del repositorio
ROOT_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = Path(__file__).resolve().parents[3]

env_db = os.getenv("STATER_DUCKDB_PATH")
if env_db:
    DEFAULT_DB_PATH = Path(env_db) if Path(env_db).is_absolute() else (ROOT_DIR / env_db)
else:
    # Check if DB exists in workspace root data/lake or inside ARGOS_MOTOR/data/lake
    cand1 = ROOT_DIR / "data" / "lake" / "duckdb" / "stater_motor.duckdb"
    cand2 = WORKSPACE_DIR / "data" / "lake" / "duckdb" / "stater_motor.duckdb"
    if cand1.exists():
        DEFAULT_DB_PATH = cand1
    elif cand2.exists():
        DEFAULT_DB_PATH = cand2
    else:
        DEFAULT_DB_PATH = cand1

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


class LakeManager:
    """Administrador del Data Lake DuckDB + Parquet de STATER."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        """Obtiene una conexión DuckDB con fallback ante bloqueos de lectura/escritura."""
        try:
            return duckdb.connect(str(self.db_path), read_only=read_only)
        except duckdb.IOException as e:
            if "utilizado por otro proceso" in str(e) or "already open" in str(e):
                if read_only:
                    return duckdb.connect(str(self.db_path), read_only=True)
                # Fallback a base de datos de ingesta desacoplada para no bloquear la ejecución
                fallback_path = self.db_path.parent / (self.db_path.stem + "_ingest.duckdb")
                conn = duckdb.connect(str(fallback_path), read_only=False)
                return conn
            raise e

    def init_database(self) -> None:
        """Ejecuta todos los scripts DDL para crear las tablas si no existen."""
        conn = self.get_connection(read_only=False)
        sql_files = [
            "documents_raw.sql",
            "financial_facts_raw.sql",
            "financial_panel.sql",
            "audit_kams.sql",
            "esg_kpis.sql",
        ]
        try:
            for sql_file in sql_files:
                file_path = SCHEMAS_DIR / sql_file
                if file_path.exists():
                    sql_content = file_path.read_text(encoding="utf-8")
                    conn.execute(sql_content)
        finally:
            conn.close()

    def insert_document_raw(self, doc_dict: Dict[str, Any]) -> None:
        """Inserta o actualiza un documento en documents_raw con valores por defecto seguros."""
        conn = self.get_connection()
        doc_id = doc_dict.get("doc_id", "DOC_UNKNOWN")
        full_doc = {
            "doc_id": doc_id,
            "source": doc_dict.get("source", "UNKNOWN"),
            "issuer_lei": doc_dict.get("issuer_lei"),
            "issuer_isin": doc_dict.get("issuer_isin"),
            "ticker": doc_dict.get("ticker"),
            "company_name": doc_dict.get("company_name", "UNKNOWN"),
            "doc_type": doc_dict.get("doc_type", doc_dict.get("form_type", "10-K")),
            "fiscal_year": int(doc_dict.get("fiscal_year", 2024)),
            "fiscal_period": doc_dict.get("fiscal_period", "FY"),
            "filing_date": doc_dict.get("filing_date"),
            "download_url": doc_dict.get("download_url") or f"https://stater.local/data/raw/{doc_id}",
            "file_path": doc_dict.get("file_path") or f"data/raw/{doc_id}",
            "file_size_bytes": doc_dict.get("file_size_bytes", 0),
            "sha256_hash": doc_dict.get("sha256_hash", ""),
            "status": doc_dict.get("status", "downloaded"),
            "quarantine_msg": doc_dict.get("quarantine_msg"),
        }
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO documents_raw (
                    doc_id, source, issuer_lei, issuer_isin, ticker, company_name,
                    doc_type, fiscal_year, fiscal_period, filing_date, download_url,
                    file_path, file_size_bytes, sha256_hash, download_ts, status, quarantine_msg
                ) VALUES (
                    $doc_id, $source, $issuer_lei, $issuer_isin, $ticker, $company_name,
                    $doc_type, $fiscal_year, $fiscal_period, $filing_date, $download_url,
                    $file_path, $file_size_bytes, $sha256_hash, CURRENT_TIMESTAMP, $status, $quarantine_msg
                )
            """,
                full_doc,
            )
        finally:
            conn.close()

    def upsert_financial_panel_record(self, record: Dict[str, Any]) -> None:
        """
        Inserta o actualiza un registro anual consolidado en financial_panel.
        Valida que el balance esté cuadrado y marca balance_check.
        """
        # Calcular cuadre
        activo = record.get("total_activo") or 0.0
        pasivo = record.get("total_pasivo") or 0.0
        pn = record.get("patrimonio_neto") or 0.0
        
        imbalance = round(abs(activo - (pasivo + pn)), 4)
        record["balance_imbalance_eur"] = imbalance
        record["balance_check"] = (imbalance == 0.0)
        
        if "version_id" not in record:
            record["version_id"] = datetime.now(timezone.utc).strftime("v%Y%m%d")

        conn = self.get_connection()
        try:
            # Lista de campos según financial_panel schema
            columns = [
                "entity_lei", "fiscal_year", "ticker", "company_name", "source_market",
                "reporting_currency", "accounting_standard", "period_end_date",
                "total_activo", "activo_no_corriente", "inmovilizado_material", "inmovilizado_intangible",
                "activo_corriente", "existencias", "deudores_comerciales", "efectivo_y_equivalentes",
                "total_pasivo", "pasivo_no_corriente", "deuda_financiera_lp",
                "pasivo_corriente", "deuda_financiera_cp", "acreedores_comerciales",
                "patrimonio_neto", "capital_social", "reservas", "resultado_ejercicio_bal",
                "revenue", "cost_of_goods_sold", "gross_profit", "operating_expenses",
                "ebitda", "depreciation_amort", "ebit", "financial_result", "ebt", "income_tax",
                "beneficio_neto", "beneficio_atribuible",
                "cfo", "capex", "cfi", "cff", "fcf", "dividendos_pagados",
                "balance_imbalance_eur", "balance_check", "quality_score", "version_id"
            ]
            
            # Asegurar que todas las claves existan en el dict con valor None si faltan
            safe_record = {col: record.get(col, None) for col in columns}
            placeholders = ", ".join([f"${col}" for col in columns])
            col_names = ", ".join(columns)

            query = f"""
                INSERT OR REPLACE INTO financial_panel ({col_names}, updated_at)
                VALUES ({placeholders}, CURRENT_TIMESTAMP)
            """
            conn.execute(query, safe_record)
        finally:
            conn.close()

    def insert_audit_kam(self, kam_dict: Dict[str, Any]) -> None:
        """Inserta una Cuestión Clave de Auditoría (KAM/CAM)."""
        conn = self.get_connection()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_kams (
                    kam_id, entity_lei, fiscal_year, doc_id, audit_firm, signing_partner,
                    audit_opinion, has_going_concern, kam_title, kam_topic, severity,
                    risk_description, audit_response, text_span, extraction_method,
                    confidence_score, human_validated
                ) VALUES (
                    $kam_id, $entity_lei, $fiscal_year, $doc_id, $audit_firm, $signing_partner,
                    $audit_opinion, $has_going_concern, $kam_title, $kam_topic, $severity,
                    $risk_description, $audit_response, $text_span, $extraction_method,
                    $confidence_score, $human_validated
                )
            """,
                kam_dict,
            )
        finally:
            conn.close()

    def insert_esg_kpi(self, esg_dict: Dict[str, Any]) -> None:
        """Inserta un KPI de sostenibilidad (CSRD/ESRS)."""
        conn = self.get_connection()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO esg_kpis (
                    kpi_id, entity_lei, fiscal_year, doc_id, framework, esrs_standard,
                    esrs_code, kpi_name, kpi_value_numeric, kpi_value_text, unit,
                    s_score_component, s_score_weight, s_score_value, greenwashing_flag,
                    greenwashing_notes, source_section, extraction_method, confidence_score
                ) VALUES (
                    $kpi_id, $entity_lei, $fiscal_year, $doc_id, $framework, $esrs_standard,
                    $esrs_code, $kpi_name, $kpi_value_numeric, $kpi_value_text, $unit,
                    $s_score_component, $s_score_weight, $s_score_value, $greenwashing_flag,
                    $greenwashing_notes, $source_section, $extraction_method, $confidence_score
                )
            """,
                esg_dict,
            )
        finally:
            conn.close()

    def export_table_to_parquet(self, table_name: str, output_path: Path, partition_cols: Optional[List[str]] = None) -> None:
        """Exporta una tabla a formato Parquet columnar de alto rendimiento."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.get_connection(read_only=True)
        try:
            if partition_cols:
                part_clause = f", PARTITION_BY ({', '.join(partition_cols)})"
            else:
                part_clause = ""
            query = f"COPY {table_name} TO '{output_path.as_posix()}' (FORMAT PARQUET{part_clause})"
            conn.execute(query)
        finally:
            conn.close()

    def get_document_raw(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Recupera un documento por su doc_id."""
        conn = self.get_connection(read_only=True)
        try:
            res = conn.execute("SELECT * FROM documents_raw WHERE doc_id = ?", [doc_id]).fetchone()
            if not res:
                return None
            cols = [desc[0] for desc in conn.description]
            return dict(zip(cols, res))
        finally:
            conn.close()

