# ARGOS MOTOR — MÓDULO MAESTRO DE DESCARGA E INGESTA DOCUMENTAL

## 1. Arquitectura y Misión
El subsistema de **Descarga e Ingesta** de ARGOS MOTOR tiene como objetivo la adquisición automatizada, verificable y trazable de la totalidad de los documentos financieros regulatorios obligatorios emitidos por emisores cotizados en mercados regulados europeos.

El módulo rechaza categóricamente cualquier dato sintético o generado artificialmente. Todo archivo almacenado en el lago de datos canónico debe proceder de:
1. **Mecanismos Centralizados Oficiales de Información Regulada (OAM - Officially Appointed Mechanisms)** según la Directiva de Transparencia de la UE (Directiva 2004/109/CE y RTS ESEF 2019/815).
2. **Supervisores Nacionales de Mercados de Valores (NCAs)**: CNMV (España), AMF (Francia), BaFin (Alemania), CONSOB (Italia), AFM (Países Bajos).
3. **Plataformas Oficiales de Acceso Electrónico Europeo (EEAP / filings.xbrl.org / ESMA)**.

---

## 2. Flujo Canónico de Ingesta (Cadena de Custodia)
Toda descarga en cualquiera de los cinco países se rige por un pipeline de 9 fases secuenciales e idempotentes:

```
[1. Discovery] ──> [2. Staging Temporal] ──> [3. Descarga Reanudable] ──> [4. Validación Magic Bytes & HTTP]
         │
         ▼
[5. Validación Entidad / Año / Tipo] ──> [6. Sellado Criptográfico SHA-256] ──> [7. Manifest & Registro]
         │
         ▼
[8. Movimiento Atómico a /data/raw] ──> [9. Control de Cuarentena (Fallo/Corrupción)]
```

### Reglas Críticas del Flujo:
- **Idempotencia Absoluta**: Si un documento ya existe con idéntico SHA-256 en la ubicación canónica, la descarga se omite registrando el acierto en caché (*cache-hit*).
- **Aislamiento en Staging**: Ningún archivo se escribe directamente en `data/raw/` durante la transferencia de red. Todo archivo se descarga en una carpeta efímera `data/staging/tmp_download/{run_id}/`.
- **Validación de Cabeceras y Magic Bytes**: Se prohíbe clasificar un archivo por su extensión. Todo archivo descargado debe verificarse mediante sus bytes mágicos:
  - `PK\x03\x04` para paquetes ZIP/ESEF.
  - `%PDF-` para informes en formato PDF.
  - `<!DOCTYPE html` o `<?xml` o `<html` para paquetes xHTML/XML/iXBRL.
  - Si una respuesta HTTP 200 devuelve una página HTML de bloqueo, captcha o error 403 camuflado, el archivo se desvía a `data/quarantine/` y no contamina el lago.

---

## 3. Estructura de Submódulos por País (5 Países)
El módulo de descarga se divide en 5 submódulos especializados por jurisdicción:

| Submódulo | País | Autoridad Supervisora | OAM Oficial (Mecanismo Centralizado) | Mercados / Índices Objetivo |
|---|---|---|---|---|
| [`es_spain/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/descarga/es_spain/README.md) | España | **CNMV** | Registro Oficial CNMV / BME / ESEF ESMA | IBEX 35, Mercado Continuo, BME Growth (~200 valores) |
| [`fr_france/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/descarga/fr_france/README.md) | Francia | **AMF** | **info-financiere.gouv.fr** (DILA) + AMF BDIF | CAC 40, SBF 120, Euronext Paris |
| [`de_germany/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/descarga/de_germany/README.md) | Alemania | **BaFin** | **Unternehmensregister** (Bundesanzeiger) | DAX 40, MDAX, SDAX, Regulierter Markt |
| [`it_italy/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/descarga/it_italy/README.md) | Italia | **CONSOB** | **1Info** (Computershare) / **eMarket STORAGE** | FTSE MIB, Euronext Milan (MTA) |
| [`nl_netherlands/`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/descarga/nl_netherlands/README.md) | Países Bajos | **AFM** | **Loket AFM** (Registers Financiële Verslaggeving) | AEX 25, AMX, Euronext Amsterdam |

---

## 4. Tipología Documental Ingerida
Para cada empresa y ejercicio fiscal ($FY_{2020}$ a $FY_{2024+}$), el motor busca:
1. **Informe Financiero Anual Completo (IFA / ESEF Package)**: Paquete ZIP/xHTML que integra Cuentas Anuales Consolidadas, Informe de Gestión, Informe del Auditor Independiente y Estado de Información No Financiera (EINF/CSRD).
2. **Informe de Auditoría Standalone**: Informe emitido por auditor externo colegiado en caso de no estar embebido.
3. **Informes Satélite Regulatorios**:
   - IAGC: Informe Anual de Gobierno Corporativo.
   - IARC: Informe Anual sobre Remuneraciones de los Consejeros.
   - Informes Periódicos Intermedios: Semestral (H1) y Trimestral (Q1/Q3).

---

## 5. Auditoría de la Descarga y Control de Calidad
Cada script de descarga genera un manifiesto `MANIFEST_{COUNTRY}_{YYYYMMDD}.json` con el siguiente esquema por documento:
```json
{
  "doc_id": "ES_CNMV_5493006QMFDDMYWIAM13_2024_ESEF",
  "lei": "5493006QMFDDMYWIAM13",
  "ticker": "SAN",
  "company_name": "Banco Santander, S.A.",
  "fiscal_year": 2024,
  "source_url": "https://www.cnmv.es/portal/Consultas/DerechosVoto/IP.aspx?nif=A-39000013",
  "http_status": 200,
  "magic_bytes_verified": "PK_ZIP",
  "sha256": "3a7b8c...",
  "file_size_bytes": 14582910,
  "destination_path": "data/raw/ES_CNMV/INFORMES_ANUALES_COMPLETOS/2024/SAN-A-39000013/",
  "status": "VALID_ORIGINAL_SEALED"
}
```
