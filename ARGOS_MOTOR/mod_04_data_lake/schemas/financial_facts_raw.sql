-- ============================================================================
-- STATER MOTOR ARGOS — CAPA STAGING: financial_facts_raw
-- Hechos XBRL / iXBRL desglosados concepto por concepto antes de consolidación
-- ============================================================================

CREATE TABLE IF NOT EXISTS financial_facts_raw (
    fact_id         VARCHAR PRIMARY KEY,    -- Hash único (doc_id + concept + period_end + context)
    doc_id          VARCHAR NOT NULL,       -- FK a documents_raw(doc_id)
    entity_lei      VARCHAR NOT NULL,       -- LEI del emisor
    period_start    DATE,                   -- Inicio del período contable
    period_end      DATE NOT NULL,          -- Fin del período contable (cierre fiscal)
    concept         VARCHAR NOT NULL,       -- Concepto XBRL original (ej: 'ifrs-full:Assets', 'us-gaap:Revenues')
    concept_std     VARCHAR NOT NULL,       -- Concepto canónico normalizado por STATER (ej: 'total_activo', 'revenue')
    value           DOUBLE NOT NULL,        -- Valor numérico reportado
    unit            VARCHAR NOT NULL,       -- Moneda o unidad (ej: 'EUR', 'USD', 'shares')
    decimals        INTEGER,                -- Precisión decimal reportada
    taxonomy        VARCHAR NOT NULL,       -- 'IFRS-FULL' | 'US-GAAP' | 'PGC-2007' | 'EXTENSION'
    statement       VARCHAR NOT NULL,       -- 'BS' (Balance) | 'PL' (PyG) | 'CF' (Flujos) | 'EQ' (Patrimonio) | 'NOTE'
    context_ref     VARCHAR,                -- Identificador de contexto XBRL
    is_restated     BOOLEAN DEFAULT FALSE   -- Indica si es un hecho reformulado de ejercicios previos
);

CREATE INDEX IF NOT EXISTS idx_facts_entity_period ON financial_facts_raw(entity_lei, period_end);
CREATE INDEX IF NOT EXISTS idx_facts_concept_std ON financial_facts_raw(concept_std);
CREATE INDEX IF NOT EXISTS idx_facts_doc_id ON financial_facts_raw(doc_id);
