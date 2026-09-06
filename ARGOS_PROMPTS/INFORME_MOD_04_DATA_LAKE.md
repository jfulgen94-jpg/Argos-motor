# AUDITORÍA TÉCNICA Y ESTADO REAL: MOD_04_DATA_LAKE
**Módulo:** Data Lake Columnar OLAP (DuckDB + Apache Parquet)  
**Ruta en el repositorio:** `ARGOS_MOTOR/mod_04_data_lake`  
**Estado:** Implementado con esquemas DDL SQL particionados, motor de DuckDB sin bloqueos y validación de balance en inserción.

---

## 1. INVENTARIO REAL DE ARCHIVOS CREADOS

```
ARGOS_MOTOR/mod_04_data_lake/
├── README.md                      (Documentación del Data Lake y estructura de capas Bronze/Silver/Gold)
├── schemas/
│   ├── init_schema.sql            (Script DDL maestro con todas las tablas)
│   ├── documents_raw.sql          (Tabla de documentos brutos ingestados)
│   ├── staging_facts.sql          (Tabla de hechos contables sin normalizar)
│   ├── core_financials.sql        (Tabla del panel financiero consolidado)
│   ├── audit_kams.sql             (Tabla de cuestiones clave de auditoría)
│   └── esg_kpis.sql               (Tabla de métricas CSRD / ESG)
├── src/
│   ├── __init__.py                (Exports de LakeManager)
│   └── lake_manager.py            (Gestor integral de base de datos DuckDB y exportaciones Parquet)
└── tests/
    ├── __init__.py
    └── test_lake_integrity.py     (Pruebas de inicialización DDL, inserción de documentos y panel balanceado)
```

---

## 2. ARQUITECTURA DE DATOS Y ESQUEMAS SQL (`schemas/`)

### Tablas Creadas en DuckDB:
1. **`documents_raw` (Capa Bronze):**
   - `doc_id` (VARCHAR PK), `source`, `country_code`, `issuer_lei`, `ticker`, `company_name`, `doc_type`, `fiscal_year`, `file_path`, `file_size_bytes`, `sha256_hash`, `status`, `ingested_at`.
2. **`financial_facts_raw` (Capa Silver - Staging):**
   - `fact_id` (VARCHAR PK), `doc_id`, `entity_lei`, `fiscal_year`, `concept_raw`, `concept_std`, `value_num`, `unit`, `is_normalized`.
3. **`financial_panel` (Capa Gold - Core):**
   - `panel_id` (VARCHAR PK), `entity_lei`, `ticker`, `company_name`, `source_market`, `fiscal_year`, `total_activo`, `total_pasivo`, `patrimonio_neto`, `revenue`, `ebitda`, `ebit`, `beneficio_neto`, `cfo`, `capex`, `fcf`, `balance_imbalance_eur`, `balance_check` (BOOLEAN).
4. **`audit_kams` (Auditoría):**
   - `kam_id` (VARCHAR PK), `doc_id`, `entity_lei`, `fiscal_year`, `audit_firm`, `signing_partner`, `audit_opinion`, `has_going_concern`, `kam_title`, `severity`, `risk_description`.
5. **`quarantine_imbalanced_filings` (Cuarentena):**
   - Registros que fallaron la validación de balance (`balance_check = False`).

### B. `LakeManager` (`src/lake_manager.py`)
- **Gestión de Concurrencia:** Conexión persistente gestionada con manejo seguro de cierres y reconexiones para evitar colisiones de bloqueo (*file locking*) en DuckDB.
- **Métodos Implementados:**
  - `init_database()`: Ejecuta `init_schema.sql` y crea las tablas si no existen.
  - `insert_document_raw(doc: Dict[str, Any])`: Inserta metadatos y hash SHA-256 en `documents_raw`.
  - `upsert_financial_panel(data: Dict[str, Any])`: Calcula el descuadre contable (`abs(activo - (pasivo + pn))`), asigna `balance_check` e inserta en `financial_panel` o envía a `quarantine_imbalanced_filings`.
  - `export_to_parquet(table_name: str, output_path: Path)`: Exporta cualquier tabla a formato Apache Parquet vectorizado.

---

## 3. SUITE DE TESTS IMPLEMENTADOS (`tests/`)
- `test_init_database_creates_all_tables`: Verifica que se creen las 6 tablas maestras en DuckDB.
- `test_insert_document_raw`: Comprueba la persistencia y lectura de un documento con hash SHA-256.
- `test_upsert_financial_panel_with_balanced_math`: Verifica que un balance cuadrado se inserte con `balance_check = True`.
- `test_upsert_financial_panel_flags_imbalance`: Comprueba que un balance descuadrado se marque con `balance_check = False` y registre el importe exacto del descuadre en euros.

---

## 4. ANÁLISIS DE CAPACIDADES Y GAPS
- **Capacidad Real:** Capacidad analítica OLAP local ultra-rápida con DuckDB, sin necesidad de servidores pesados de base de datos.
- **Gap:** En entornos concurrentes multi-proceso, DuckDB requiere acceso en modo solo lectura (`read_only=True`) para lectores concurrentes si hay un proceso escritor activo.
