# PROMPT PARA OPENHANDS (GEMINI 3.5 PRO): VERIFICADOR Y CRAWLER ASÍNCRONO EQS / DGAP
## Proyecto: STATER / ARGOS MOTOR — Extracción Masiva de Enlaces Verificados EQS

Eres el Ingeniero Senior de Scraping Distribuido e Ingesta Financiera de STATER.
Tu misión es ejecutar en tu entorno Docker de Linux un verificador ultrarrápido y asíncrono que valide todos los PDFs disponibles en el servidor regulatorio de **EQS Group (antigua DGAP)** para las empresas de Prime Standard de Alemania.

---

### 1. ARQUITECTURA DEL REPOSITORIO EQS

Las cuentas anuales de los emisores cotizados alemanes bajo mandato regulatorio (*WpHG*) se alojan en:
`https://irpages2.eqs.com/Download/Companies/{CompanySlug}/Annual%20Reports/{ISIN}-JA-{Year}-EQ-D-{Version}.pdf`

- Las cabeceras HTTP redirigen con `301/302` a `https://ir-api.eqs.com/media/document/...` con estado final `200 OK` y `Content-Type: application/pdf`.
- No hay CAPTCHA ni Wicket session. Las respuestas son directas e inmediatas.

---

### 2. ENTRADA Y ARCHIVOS A UTILIZAR

En el workspace tienes:
1. `ARGOS_MOTOR/config/prime_standard_companies.json` (172 empresas con ticker, ISIN, nombres).
2. `ARGOS_MOTOR/config/eqs_company_slugs.json` (si ya fue generado por Qwen Coder). Si no existe aún, puedes derivar los slugs candidatos directamente de los nombres comerciales e históricos de las empresas (ej. BASF, BMW, Siemens, Daimler, HeidelbergCement, eads, Volkswagen, etc.).

---

### 3. TAREA A EJECUTAR

Escribe y ejecuta un script en Python asíncrono (`scratch/crawler_eqs_async.py`) utilizando `httpx` (o `aiohttp`):

1. **Paralelismo**: Ejecuta con un semáforo de concurrencia de 15–20 conexiones simultáneas.
2. **Prueba de Existencia**:
   - Para cada empresa (172) y cada año (2012–2025):
   - Probar los slugs candidatos de la empresa.
   - Probar las versiones `00` y `01`:
     `https://irpages2.eqs.com/Download/Companies/{slug}/Annual%20Reports/{isin}-JA-{year}-EQ-D-{ver}.pdf`
   - Realizar una petición `HEAD` con `follow_redirects=True`.
   - Si devuelve `200 OK` y el `Content-Type` contiene `pdf`:
     * Registrar el enlace verificado, el tamaño en bytes (`Content-Length`) y la URL final redirigida.
     * Pasar al siguiente año (hit exitoso).
3. **Salida Estructurada**:
   Guardar todos los aciertos en:
   `scratch/eqs_verified_links.json`

   Formato JSON esperado:
   ```json
   {
     "BASF": {
       "isin": "DE000BASF111",
       "reports": {
         "2012": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2012-EQ-D-00.pdf",
         "2013": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2013-EQ-D-00.pdf",
         "2014": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2014-EQ-D-00.pdf",
         "2015": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2015-EQ-D-00.pdf",
         "2016": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2016-EQ-D-00.pdf",
         "2017": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2017-EQ-D-00.pdf",
         "2018": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2018-EQ-D-00.pdf",
         "2019": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2019-EQ-D-00.pdf",
         "2024": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2024-EQ-D-00.pdf"
       }
     }
   }
   ```

---

### 4. PROTOCOLO DE EJECUCIÓN

1. Crear el script `scratch/crawler_eqs_async.py`.
2. Ejecutarlo:
   ```bash
   python scratch/crawler_eqs_async.py
   ```
3. Imprimir el resumen final de aciertos por año (cuántos informes se verificaron para 2012, 2013, ... 2025).
4. El archivo generado `scratch/eqs_verified_links.json` será absorbido directamente por Antigravity para descargar los PDFs reales a `D:/ARGOS_DATA/raw/DE_BAFIN/`.
