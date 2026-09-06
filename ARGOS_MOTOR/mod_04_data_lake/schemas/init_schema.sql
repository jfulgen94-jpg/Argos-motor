-- ============================================================================
-- STATER MOTOR ARGOS — DDL MAESTRO DE INICIALIZACIÓN (DUCKDB)
-- Inicializa las 4 capas del Data Lake: RAW -> STAGING -> CORE -> ANALYTICS
-- ============================================================================

-- 1. Capa RAW
.read documents_raw.sql

-- 2. Capa STAGING
.read financial_facts_raw.sql

-- 3. Capa CORE
.read financial_panel.sql

-- 4. Capa ANALYTICS
.read audit_kams.sql
.read esg_kpis.sql
