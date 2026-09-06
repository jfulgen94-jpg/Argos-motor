-- ============================================================================
-- STATER MOTOR ARGOS — CAPA RAW: documents_raw
-- Registro inmutable de todos los filings descargados (SEC + 5 OAMs Europeos)
-- ============================================================================

CREATE TABLE IF NOT EXISTS documents_raw (
    doc_id          VARCHAR PRIMARY KEY,    -- UUID / Hash identificador único del documento
    source          VARCHAR NOT NULL,       -- 'SEC_EDGAR' | 'CNMV' | 'AMF' | 'BAFIN' | 'CONSOB' | 'AFM'
    issuer_lei      VARCHAR,                -- Código LEI (GLEIF - 20 caracteres)
    issuer_isin     VARCHAR,                -- Código ISIN (12 caracteres)
    ticker          VARCHAR,                -- Ticker bursátil (ej: AAPL, SAN.MC)
    company_name    VARCHAR,                -- Razón social del emisor
    doc_type        VARCHAR NOT NULL,       -- '10-K' | '10-Q' | '8-K' | 'ESEF' | 'CSRD' | 'IAGC'
    fiscal_year     INTEGER NOT NULL,       -- Ej: 2024
    fiscal_period   VARCHAR DEFAULT 'FY',   -- 'FY' | 'Q1' | 'Q2' | 'Q3' | 'Q4' | 'H1' | 'H2'
    filing_date     DATE,                   -- Fecha oficial de publicación en el regulador
    download_url    VARCHAR NOT NULL,       -- URL exacta desde donde se descargó
    file_path       VARCHAR NOT NULL,       -- Ruta local en disco (data/raw/...)
    file_size_bytes BIGINT,                 -- Tamaño del archivo descargado
    sha256_hash     VARCHAR(64) NOT NULL,   -- Sello criptográfico SHA-256 inmutable
    download_ts     TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Timestamp de ingesta
    status          VARCHAR DEFAULT 'RAW',  -- 'RAW' | 'PARSED' | 'FAILED' | 'QUARANTINE'
    quarantine_msg  VARCHAR                 -- Razón de cuarentena si aplica
);

CREATE INDEX IF NOT EXISTS idx_docs_lei_year ON documents_raw(issuer_lei, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_docs_source ON documents_raw(source);
CREATE INDEX IF NOT EXISTS idx_docs_status ON documents_raw(status);
