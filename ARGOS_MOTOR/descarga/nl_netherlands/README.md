# SUBMÓDULO DE DESCARGA: PAÍSES BAJOS (AFM / LOKET AFM)

## 1. Identificación y Regulación del OAM en los Países Bajos
* **Autoridad Nacional Competente (NCA)**: Autoriteit Financiële Markten (AFM - `afm.nl`).
* **Mecanismo Centralizado Oficial (OAM)**: **`Registers Financiële Verslaggeving / Loket AFM`** (Designado conforme al artículo 5:52m de la Ley de Supervisión Financiera neerlandesa - *Wet op het financieel toezicht / Wft* y la Directiva 2004/109/CE).
* **Distinción Institucional Obligatoria**:
  - **AFM**: OAM oficial exclusivo para la información regulada de emisores cotizados en mercados regulados (paquetes ESEF, cuentas consolidadas, hechos relevantes).
  - **KvK (Kamer van Koophandel)**: Cámara de comercio neerlandesa para el depósito mercantil ordinario de sociedades no cotizadas (*Besloten Vennootschap - BV*). No opera como OAM de mercados de valores.
* **Mercados e Índices**: Euronext Amsterdam (AEX 25, AMX, Euronext Growth Amsterdam).
* **Entidades Clave**: ASML Holding NV, Unilever PLC, Prosus NV, ING Groep NV, Heineken NV, Koninklijke Ahold Delhaize NV, Wolters Kluwer NV, Koninklijke Philips NV, ASM International NV, Randstad NV.

---

## 2. Estratificación del Método de Descarga
### Canal A: Ingesta ESEF Neerlandesa
* Los emisores de Euronext Amsterdam depositan simultáneamente ante el AFM y el público sus paquetes ESEF.
* Consulta vía LEI del emisor neerlandés (ej. ASML: `724500Y6DUVHQD6OXN27`).
* Formato: Paquete ZIP reglamentario xHTML con etiquetas IFRS dimensionales.

### Canal B: Registro Público AFM (Financiële Verslaggeving)
* Búsqueda por denominación legal, número KvK o código LEI.
* Descarga de resoluciones de supervisión contable bajo la *Wet toezicht financiële verslaggeving (Wtfv)*.

---

## 3. Configuración Documental Neerlandesa
* **Geïntegreerd Jaarverslag (Informe Anual Integrado)**:
  1. *Geconsolideerde Jaarrekening* (Estados financieros consolidados bajo IFRS-UE).
  2. *Bestuursverslag* (Informe de la dirección / Director's Report).
  3. *Duurzaamheidsverslag / CSRD* (Informe de sostenibilidad).
  4. *Controleverklaring van de onafhankelijke accountant* (Dictamen del auditor independiente emitido según normas neerlandesas de auditoría - NVCOS).
  5. *Verslag van de Raad van Commissarissen* (Informe del consejo de supervisión).

---

## 4. Auditoría de la Descarga (Países Bajos)
* En `data/raw/NL_AFM/`, se auditan los 73 registros existentes (actualmente 3 paquetes primarios completos y 67 registros en estado metadato `.meta.json`).
* Sellado criptográfico SHA-256 en `MANIFEST_NL_AFM_{YYYYMMDD}.json`.

---

## 5. Ejecución
```bash
# Descarga de emisores neerlandeses AEX 25
python ARGOS_MOTOR/descarga/nl_netherlands/downloader_afm.py --index AEX25 --years 2022,2023,2024

# Auditoría de descargas
python ARGOS_MOTOR/descarga/nl_netherlands/audit_download_nl.py
```
