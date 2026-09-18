# PROMPT MAESTRO PARA OPENHANDS (GEMINI 2.5 / 2.0 PRO) — CANAL B DEFINITIVO
## Módulo: ARGOS MOTOR — Adquisición Histórica Alemania (DE_BAFIN 2012–2025)
**Objetivo:** Exprimir al máximo la capacidad del motor alemán (`download_canal_b_historico.py`) para completar el horizonte temporal completo (2012 a 2025) de las 1.011 sociedades cotizadas del universo (`master_universe_de.json`), superando las barreras de CAPTCHA, Wicket y ConnectTimeout.

---

### INSTRUCCIÓN MAESTRA PARA COPIAR EN OPENHANDS:

```markdown
Eres un Ingeniero Principal de Infraestructura de Datos Financieros y Scraping Forense en STATER Financial Technologies.
Tu misión es ejecutar, monitorizar y completar la adquisición documental de Alemania en `ARGOS_MOTOR/descarga/de_germany/` sobre el universo maestro de 1.011 sociedades cotizadas (`ARGOS_MOTOR/config/master_universe_de.json`), cubriendo tanto el histórico (2012–2019) como el cierre reciente (2023–2025).

---

### 1. ESTADO DEL DATA LAKE Y A QUÉ PUEDE ASPIRAR EL MOTOR

El repositorio en `D:/ARGOS_DATA/raw/DE_BAFIN` (reflejado en el enlace simbólico `ARGOS_DATA_DISK`) cuenta actualmente con:
- **303 paquetes ZIP ESEF** (2020–2022) sellados con hash SHA-256 e inmutables. ¡NO RE-DESCARGAR!
- **18 PDFs de cuentas anuales auditadas** (2012–2019) de Deutsche Bank, Lufthansa y Bayer.
- **5 documentos contables oficiales HTML** de SAP y Deutsche Bank (2023–2025).
- **427 ficheros `.meta.json`** individuales auditados.

#### Techo Operativo del Universo (1.011 Sociedades):
1. **PRIME_STANDARD (172 empresas)**: Incluye DAX40, MDAX, SDAX y TecDAX (>90% de la capitalización bursátil alemana).
   * **Aspiración:** 100% de cobertura documental. Todas publican informes anuales completos en PDF en sus portales de Investor Relations Y en Bundesanzeiger (§ 114 WpHG).
2. **GENERAL_STANDARD (376 empresas)**:
   * **Aspiración:** 75%–90% de cobertura vía Bundesanzeiger Área 22 (§ 325 HGB).
3. **SCALE & FREIVERKEHR (463 empresas)**: Micro-caps y mercado no regulado.
   * **Aspiración:** Cobertura de cuentas anuales individuales/consolidadas depositadas bajo HGB.
4. **Control de Entidades Recientes (Spin-offs)**: Entidades nacidas por escisión reciente (ej. Siemens Energy `SIEM` en 2020, Daimler Truck `DTG` en 2021) NO existían entre 2012 y 2019. Deben marcarse como `NOT_INCORPORATED_YET` en los manifiestos de esos años para evitar búsquedas estériles.

---

### 2. LECCIONES TÉCNICAS CRÍTICAS Y ARQUITECTURA DEL MOTOR

El script `ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py` integra las siguientes salvaguardas arquitectónicas que DEBES respetar y mantener:

1. **Persistencia de Sesión de Navegador (`launch_persistent_context`)**:
   - Bundesanzeiger utiliza Cloudflare y CAPTCHAs matemáticos/gráficos.
   - El script utiliza un directorio de perfil persistente en `ARGOS_MOTOR/descarga/de_germany/.playwright_bafin_session`.
   - **Protocolo de activación**: Al ejecutar con `--bafin-manual`, el navegador se abre visible. El operador o tú resolvéis **1 solo CAPTCHA**. Una vez resuelto y pulsado ENTER, las cookies y tokens de sesión quedan guardados en disco. Las siguientes peticiones e iteraciones se ejecutan de forma automatizada sin solicitar nuevos CAPTCHAs durante horas.

2. **Ventana Temporal de Depósito Contable (Regla de Oro § 325 HGB)**:
   - Las cuentas anuales de un ejercicio fiscal `{year}` (ej. 2016) se formulan, auditan y depositan **al año siguiente (`year + 1`) o principios del segundo (`year + 2`)**.
   - En las búsquedas de Bundesanzeiger, el filtro de fechas DEBE ser:
     `start_date: 01.01.{year+1}` hasta `end_date: 31.12.{year+2}`.
     *(Filtrar por el mismo año `{year}` arroja 0 resultados porque el ejercicio aún no había cerrado ni auditado).*

3. **Aislamiento de Pestañas en Apache Wicket**:
   - El Bundesanzeiger opera con URLs de sesión dinámica (`suchen2?7-1...`).
   - Al abrir publicaciones del listado de resultados, **NUNCA se debe usar `page.go_back()`** ni pinchar en la misma pestaña porque Wicket invalida el estado (`ExpiredPageException`).
   - El script abre cada publicación candidata en una pestaña secundaria (`context.new_page()`), extrae el contenido/descarga, y la cierra (`pub_tab.close()`), dejando intacta la página de resultados.

4. **Validación Criptográfica y Contable Estricta (`is_valid_financial_document`)**:
   - **PDFs**: Magic bytes `%PDF-` y tamaño > 5.000 bytes.
   - **HTMLs**: Descarte inmediato de hashes boilerplate (`3f418fa1...`), firmas de Next.js (`_next/`), o avisos de `Sicherheitsabfrage` (CAPTCHA no resuelto).
   - Verificación contable obligatoria: presencia de al menos 2 términos contables alemanes (`Aktiva`, `Passiva`, `Bilanzsumme`, `Eigenkapital`, `Jahresabschluss`, `Konzernabschluss`).

5. **Resolución por Registro Mercantil (`hrb_reg`)**:
   - 789 de las 1.011 sociedades disponen de número HRB exacto en `master_universe_de.json`.
   - Si la búsqueda por nombre limpio genera ambigüedad, emplear el número HRB para una resolución inequívoca.

---

### 3. PROTOCOLO DE EJECUCIÓN POR FASES

Ejecuta el pipeline siguiendo este orden estricto de prioridades para maximizar el valor de los datos adquiridos:

#### Fase 1: Activación de Sesión Persistente y Validación DAX40 (2012–2019)
Lanza el script en modo visible asistido para activar la sesión de Bundesanzeiger:
```bash
python ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py --segment DAX40 --years 2012-2019 --bafin-manual
```
*Acción requerida:* En la ventana de Chromium que se abrirá automáticamente, navega y resuelve el CAPTCHA de Bundesanzeiger una sola vez. Pulsa ENTER en el terminal. Comprueba cómo el script descarga y sella los balances de las empresas del DAX.

#### Fase 2: Expansión a MDAX, SDAX y TecDAX (Prime Standard)
Con la sesión persistente ya guardada en `.playwright_bafin_session`, ejecuta de forma continua:
```bash
python ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py --segment "MDAX,SDAX,TECDAX" --years 2012-2019 --delay-min 2.5 --delay-max 4.5
```

#### Fase 3: Adquisición del Cierre Reciente (2023–2025)
Ejecuta para incorporar los informes auditados y declaraciones de los últimos ejercicios para todo el Prime Standard:
```bash
python ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py --segment "DAX40,MDAX,SDAX,TECDAX" --years 2023-2025
```

#### Fase 4: Resto del Universo (General Standard) en Lotes de 50
Para el tramo largo de emisores, procesa en bloques controlados:
```bash
python ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py --segment GENERAL_STANDARD --years 2012-2025 --max-companies 50
```

#### Fase 5: Auditoría y Sellado Final de Manifiestos
Al culminar, ejecuta la auditoría del repositorio alemán:
```bash
python ARGOS_MOTOR/descarga/de_germany/audit_download_de.py
```
Verifica que los manifiestos `MANIFEST_BAFIN_{year}.json` en `D:/ARGOS_DATA/raw/DE_BAFIN` y en `ARGOS_MOTOR/audits/manifests/` reflejen los nuevos hits y hashes consolidados.
```

---
*Documento actualizado en el repositorio central de STATER Financial Technologies.*
