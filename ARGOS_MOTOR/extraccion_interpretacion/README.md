# ARGOS MOTOR — MÓDULO MAESTRO DE EXTRACCIÓN, PARSEO E INTERPRETACIÓN CONTABLE

## 1. Misión y Alcance Técnico
El subsistema de **Extracción e Interpretación** transforma los documentos brutos sellados en `data/raw/` (paquetes ESEF xHTML/iXBRL, XML, taxonomías y PDFs) en estructuras contables tabulares, normalizadas y auditables para el **Data Lake Institucional** (DuckDB / Parquet).

El pipeline ejecuta tres niveles de procesamiento analítico:
1. **Extracción y Desempaquetado XBRL/iXBRL**: Lectura de taxonomías IFRS-EU / RTS ESEF 2019/815, resolución de hipercubos y mapeo de etiquetas dimensionales (balance, pérdidas y ganancias, flujos de efectivo, estado de cambios en el patrimonio neto).
2. **Segmentación Documental Obligatoria**:
   - **Informes Anuales Completos**: Contienen dentro del mismo archivo/paquete las Cuentas Anuales Auditadas, el Informe de Gestión, el Informe de Sostenibilidad/EINF y el Informe de Auditoría Independiente.
   - **Informes Parciales**: Documentos que contienen únicamente el dictamen de auditoría, estados no consolidados, o que carecen de la memoria o el estado no financiero.
3. **Auditoría Forense y NLP Contable**:
   - Detección y clasificación de la **Opinión del Auditor Independiente**: Favorable (Limpia / Unqualified), Con Salvedades (Qualified), Desfavorable (Adverse), o Denegada (Disclaimer of Opinion).
   - Extracción de **Cuestiones Clave de Auditoría (KAM - Key Audit Matters)** e Incertidumbres Materiales relacionadas con la Empresa en Funcionamiento (*Going Concern*).
   - Verificación de concordancia matemática: Ecuación fundamental del balance ($Activo = Pasivo + Patrimonio\ Neto$), cuadre de flujos de caja y conciliación de saldos iniciales/finales.

---

## 2. Taxonomías Regulatorias y Normativa Aplicable

```
[Documento Bruto iXBRL / xHTML / PDF]
                 │
                 ▼
     [Detector de Jurisdicción]
                 │
  ┌──────────────┼──────────────┬──────────────┬──────────────┐
  ▼              ▼              ▼              ▼              ▼
[España: PGC]  [Francia: PCG] [Alemania: HGB] [Italia: OIC]  [Países Bajos]
  │              │              │              │              │
  └──────────────┴──────────────┼──────────────┴──────────────┘
                                ▼
              [Capa de Consolidación: NIIF-UE / IFRS]
                                │
                                ▼
         [Taxonomía Base ESEF RTS / filings.xbrl.org]
                                │
                                ▼
      [Data Lake: Parquet / DuckDB Tablas Canónicas]
```

---

## 3. Estructura de Submódulos por País (5 Países)

| Submódulo | Jurisdicción | Normativa Contable Nacional / Marco UE | Segmentación Clave | Foco de Auditoría Forense |
|---|---|---|---|---|
| [`es_spain/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/extraccion_interpretacion/es_spain/README.md) | España | PGC / NIIF-UE / Ley 11/2018 (EINF) | Paquetes ESEF vs. Informes IPP / Cuentas Individuales | Dictamen auditoría ICAC, Salvedades, Párrafos de Énfasis, IAGC/IARC |
| [`fr_france/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/extraccion_interpretacion/fr_france/README.md) | Francia | Plan Comptable Général (PCG) / IFRS-UE | URD (Document d'Enregistrement Universel) vs. Rapport Financier Annuel | Rapport des commissaires aux comptes, DPEF / CSRD |
| [`de_germany/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/extraccion_interpretacion/de_germany/README.md) | Alemania | HGB (Handelsgesetzbuch) / IFRS-UE | Geschäftsbericht completo vs. Einzelabschluss | Bestätigungsvermerk des Wirtschaftsprüfers, Lagebericht |
| [`it_italy/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/extraccion_interpretacion/it_italy/README.md) | Italia | Principi Contabili Nazionali (OIC) / IFRS-UE | Relazione Finanziaria Annuale vs. Fascicolo di Bilancio | Relazione della Società di Revisione, DNF (Dichiarazione Non Finanziaria) |
| [`nl_netherlands/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/extraccion_interpretacion/nl_netherlands/README.md) | Países Bajos | Dutch GAAP (RJ - Raad voor de Jaarverslaggeving) / IFRS | Geïntegreerd Jaarverslag vs. Jaarrekening | Controleverklaring van de onafhankelijke accountant, Bestuursverslag |

---

## 4. Esquema de Salida hacia el Data Lake
Todo proceso de extracción genera registros normalizados con trazabilidad criptográfica:
```json
{
  "doc_id": "ES_CNMV_5493006QMFDDMYWIAM13_2024_ESEF",
  "lei": "5493006QMFDDMYWIAM13",
  "ticker": "SAN",
  "fiscal_year": 2024,
  "completeness_status": "COMPLETO_INTEGRADO",
  "components_detected": {
    "financial_statements": true,
    "management_report": true,
    "sustainability_report": true,
    "audit_report": true
  },
  "audit_opinion": "FAVORABLE_SIN_SALVEDADES",
  "auditor_firm": "PricewaterhouseCoopers Auditores, S.L.",
  "auditor_partner": "Firma Colegiada",
  "key_audit_matters_count": 4,
  "accounting_standard": "NIIF_UE",
  "balance_sheet_balanced": true,
  "total_assets": 1823412000000.0,
  "net_income": 12574000000.0,
  "source_sha256": "3a7b8c...",
  "lake_ingestion_timestamp": "2026-09-07T22:45:00Z"
}
```
