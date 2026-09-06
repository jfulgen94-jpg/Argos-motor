-- ============================================================================
-- STATER MOTOR ARGOS — CAPA ANALYTICS: esg_kpis
-- Métricas normalizadas de sostenibilidad (CSRD / ESRS E1-G1) y Capital Humano (S-Score v2.0)
-- ============================================================================

CREATE TABLE IF NOT EXISTS esg_kpis (
    kpi_id              VARCHAR PRIMARY KEY,    -- UUID único del KPI
    entity_lei          VARCHAR NOT NULL,       -- LEI del emisor
    fiscal_year         INTEGER NOT NULL,       -- Año fiscal reportado
    doc_id              VARCHAR NOT NULL,       -- FK a documents_raw(doc_id)
    framework           VARCHAR NOT NULL,       -- 'CSRD_ESRS' | 'GRI' | 'SASB' | 'SEC_CLIMATE'
    
    esrs_standard       VARCHAR NOT NULL,       -- 'ESRS_E1' (Clima) | 'ESRS_S1' (Propia plantilla) | 'ESRS_G1' (Gobernanza) etc.
    esrs_code           VARCHAR NOT NULL,       -- Código de divulgación (ej: 'E1-1', 'E1-6', 'S1-6', 'G1-1')
    kpi_name            VARCHAR NOT NULL,       -- Nombre canónico (ej: 'ghg_scope_1_tonnes', 'gender_pay_gap_pct')
    kpi_value_numeric   DOUBLE,                 -- Valor numérico cuantitativo si aplica
    kpi_value_text      VARCHAR,                -- Valor cualitativo / categórico si aplica
    unit                VARCHAR,                -- 'tCO2e', 'EUR', 'percentage', 'headcount', 'ratio'
    
    -- Scoring STATER
    s_score_component   VARCHAR,                -- 'human_capital', 'diversity', 'health_safety', 'climate_transition'
    s_score_weight      DOUBLE DEFAULT 1.0,     -- Ponderación en el S-Score
    s_score_value       DOUBLE,                 -- Puntuación normalizada (0 a 100)
    
    -- Detección Forense de Greenwashing
    greenwashing_flag   BOOLEAN DEFAULT FALSE,  -- True si hay contradicción entre narrativa y datos duros
    greenwashing_notes  TEXT,                   -- Detalle de la inconsistencia detectada
    
    source_section      VARCHAR,                -- Sección del informe (ej: 'Capítulo 4: Capital Humano')
    extraction_method   VARCHAR NOT NULL,       -- 'regex_heuristic' | 'ollama_qwen14b' | 'azure_gpt4o'
    confidence_score    DOUBLE DEFAULT 1.0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_esg_lei_year ON esg_kpis(entity_lei, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_esg_standard ON esg_kpis(esrs_standard);
CREATE INDEX IF NOT EXISTS idx_esg_code ON esg_kpis(esrs_code);
CREATE INDEX IF NOT EXISTS idx_esg_greenwashing ON esg_kpis(greenwashing_flag);
