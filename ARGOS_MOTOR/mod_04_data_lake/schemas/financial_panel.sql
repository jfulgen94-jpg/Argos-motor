-- ============================================================================
-- STATER MOTOR ARGOS — CAPA CORE: financial_panel
-- Panel financiero anual consolidado (una fila por empresa-año)
-- Estándar de cuadre matemático: Activo = Pasivo + Patrimonio Neto
-- ============================================================================

CREATE TABLE IF NOT EXISTS financial_panel (
    entity_lei          VARCHAR NOT NULL,       -- LEI del emisor
    fiscal_year         INTEGER NOT NULL,       -- Año fiscal (ej: 2024)
    ticker              VARCHAR,                -- Ticker bursátil
    company_name        VARCHAR,                -- Razón social
    source_market       VARCHAR NOT NULL,       -- 'US' | 'ES' | 'FR' | 'DE' | 'IT' | 'NL'
    reporting_currency  VARCHAR NOT NULL,       -- 'EUR' | 'USD' | 'GBP' | etc.
    accounting_standard VARCHAR NOT NULL,       -- 'IFRS' | 'US-GAAP' | 'LOCAL-GAAP'
    period_end_date     DATE NOT NULL,          -- Fecha de cierre fiscal

    -- --- ESTADO DE SITUACIÓN FINANCIERA (BALANCE) ---------------------------
    total_activo            DOUBLE,             -- Activo Total
    activo_no_corriente     DOUBLE,             -- Inmovilizado / Activo Fijo
    inmovilizado_material   DOUBLE,             -- PPE (Propiedad, Planta y Equipo)
    inmovilizado_intangible DOUBLE,             -- Intangibles + Goodwill
    activo_corriente        DOUBLE,             -- Activo Circulante
    existencias             DOUBLE,             -- Inventarios
    deudores_comerciales    DOUBLE,             -- Clientes / Cuentas por cobrar
    efectivo_y_equivalentes DOUBLE,             -- Tesorería y equivalentes

    total_pasivo            DOUBLE,             -- Pasivo Total
    pasivo_no_corriente     DOUBLE,             -- Deuda a largo plazo + provisiones LP
    deuda_financiera_lp     DOUBLE,             -- Deuda financiera LP
    pasivo_corriente        DOUBLE,             -- Pasivo Circulante
    deuda_financiera_cp     DOUBLE,             -- Deuda financiera CP
    acreedores_comerciales  DOUBLE,             -- Proveedores / Cuentas por pagar

    patrimonio_neto         DOUBLE,             -- Fondos Propios + PN Total
    capital_social          DOUBLE,             -- Capital emitido
    reservas                DOUBLE,             -- Reservas y resultados acumulados
    resultado_ejercicio_bal DOUBLE,             -- Beneficio atribuido en Balance

    -- --- CUENTA DE PÉRDIDAS Y GANANCIAS (INCOME STATEMENT) -------------------
    revenue                 DOUBLE,             -- Cifra de Negocios / Ventas
    cost_of_goods_sold      DOUBLE,             -- Coste de Ventas (COGS)
    gross_profit            DOUBLE,             -- Margen Bruto (Revenue - COGS)
    operating_expenses      DOUBLE,             -- Gastos Operativos (Opex)
    ebitda                  DOUBLE,             -- Resultado de Explotación antes de Amortizaciones
    depreciation_amort      DOUBLE,             -- Dotaciones de Amortización (D&A)
    ebit                    DOUBLE,             -- Resultado Operativo (EBIT)
    financial_result        DOUBLE,             -- Resultado Financiero Neto
    ebt                     DOUBLE,             -- Beneficio Antes de Impuestos
    income_tax              DOUBLE,             -- Gasto por Impuesto sobre Beneficios
    beneficio_neto          DOUBLE,             -- Beneficio Neto Consolidado
    beneficio_atribuible    DOUBLE,             -- Beneficio atribuible a la sociedad dominante

    -- --- ESTADO DE FLUJOS DE EFECTIVO (CASH FLOW STATEMENT) -----------------
    cfo                     DOUBLE,             -- Flujo de Efectivo de las Actividades de Explotación
    capex                   DOUBLE,             -- Inversiones en Inmovilizado (Capital Expenditures)
    cfi                     DOUBLE,             -- Flujo de Efectivo de Actividades de Inversión
    cff                     DOUBLE,             -- Flujo de Efectivo de Actividades de Financiación
    fcf                     DOUBLE,             -- Free Cash Flow = CFO - Capex
    dividendos_pagados      DOUBLE,             -- Dividendos efectivamente abonados

    -- --- CONTROL DE CALIDAD FORENSE Y TRAZABILIDAD --------------------------
    balance_imbalance_eur   DOUBLE DEFAULT 0.0, -- Descuadre absoluto = |Activo - (Pasivo + PN)|
    balance_check           BOOLEAN NOT NULL,   -- TRUE si balance_imbalance_eur == 0.0
    quality_score           DOUBLE DEFAULT 1.0, -- Score de integridad de datos (0.0 a 1.0)
    version_id              VARCHAR NOT NULL,   -- Snapshot diario 'vYYYYMMDD'
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (entity_lei, fiscal_year)
);

CREATE INDEX IF NOT EXISTS idx_panel_lei ON financial_panel(entity_lei);
CREATE INDEX IF NOT EXISTS idx_panel_year ON financial_panel(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_panel_market ON financial_panel(source_market);
CREATE INDEX IF NOT EXISTS idx_panel_balance_check ON financial_panel(balance_check);
