-- ============================================================================
-- STATER MOTOR ARGOS — CAPA ANALYTICS: audit_kams
-- Extracción estructurada de Cuestiones Clave de Auditoría (KAMs ISA 701)
-- y Critical Audit Matters (CAMs PCAOB AS 3101) con puntuación de severidad
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_kams (
    kam_id              VARCHAR PRIMARY KEY,    -- UUID único del KAM
    entity_lei          VARCHAR NOT NULL,       -- LEI del emisor
    fiscal_year         INTEGER NOT NULL,       -- Año fiscal auditado
    doc_id              VARCHAR NOT NULL,       -- FK a documents_raw(doc_id)
    audit_firm          VARCHAR,                -- Firma auditora (ej: 'PwC', 'Deloitte', 'EY', 'KPMG', 'BDO')
    signing_partner     VARCHAR,                -- Socio firmante del informe
    audit_opinion       VARCHAR DEFAULT 'UNQUALIFIED', -- 'UNQUALIFIED' | 'QUALIFIED' | 'ADVERSE' | 'DISCLAIMER'
    has_going_concern   BOOLEAN DEFAULT FALSE,  -- Párrafo de énfasis de Empresa en Funcionamiento
    
    kam_title           VARCHAR NOT NULL,       -- Título de la cuestión clave (ej: 'Recuperabilidad del Fondo de Comercio')
    kam_topic           VARCHAR NOT NULL,       -- Categoría normalizada: 'impairment', 'revenue_recognition', 'provisions', 'tax_assets', 'financial_instruments', 'going_concern', 'valuation_assets', 'it_systems', 'other'
    severity            VARCHAR NOT NULL,       -- 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
    risk_description    TEXT,                   -- Descripción del riesgo contable según el auditor
    audit_response      TEXT,                   -- Procedimientos de auditoría aplicados en respuesta al riesgo
    text_span           TEXT NOT NULL,          -- Texto íntegro extraído del informe
    
    extraction_method   VARCHAR NOT NULL,       -- 'regex_heuristic' | 'ollama_qwen14b' | 'azure_gpt4o'
    confidence_score    DOUBLE DEFAULT 1.0,     -- Confianza de la extracción (0.0 a 1.0)
    human_validated     BOOLEAN DEFAULT FALSE,  -- True si ha sido validado por el protocolo de revisión humana 25%
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_kams_lei_year ON audit_kams(entity_lei, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_kams_topic ON audit_kams(kam_topic);
CREATE INDEX IF NOT EXISTS idx_kams_severity ON audit_kams(severity);
CREATE INDEX IF NOT EXISTS idx_kams_going_concern ON audit_kams(has_going_concern);
