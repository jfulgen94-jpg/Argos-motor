# PROMPT PARA OPENHANDS (GEMINI 3.5 PRO): VERIFICADOR Y CRAWLER ASÍNCRONO EQS / DGAP
## Proyecto: STATER / ARGOS MOTOR — Extracción Masiva de Enlaces Verificados EQS (Alemania)

Eres el Ingeniero Senior de Scraping Distribuido e Ingesta Financiera de STATER.
Tu misión es ejecutar en tu entorno Docker de Linux un verificador ultrarrápido y asíncrono que valide todos los PDFs anuales disponibles en el servidor regulatorio de **EQS Group (antigua DGAP)** para las 172 empresas del universo Prime Standard de Alemania (2012–2025).

---

### 1. ARQUITECTURA DEL REPOSITORIO EQS

Las cuentas anuales de los emisores cotizados alemanes bajo mandato regulatorio (*WpHG*) se alojan en:
`https://irpages2.eqs.com/Download/Companies/{CompanySlug}/Annual%20Reports/{ISIN}-JA-{Year}-{Lang}-{Version}.pdf`

- **{CompanySlug}**: Slug corporativo (ej. `BASF`, `Daimler`, `Siemens`, `eads`, `Volkswagen`, etc.).
- **{ISIN}**: Código ISIN de 12 caracteres (ej. `DE000BASF111`, `NL0000235190`).
- **{Year}**: Año fiscal auditado (2012 a 2025).
- **{Lang}**: `EQ-D` (Alemán, prioritario por mandato legal) o `EQ-E` (Inglés, usado por multinacionales como Airbus).
- **{Version}**: `00` o `01`.

Las cabeceras HTTP redirigen con `301/302` a `https://ir-api.eqs.com/media/document/...` con estado final `200 OK` y `Content-Type: application/pdf`.
**Ventaja crítica**: No hay CAPTCHA, ni sesión Wicket, ni bloqueo de IP. Las peticiones `HEAD` resuelven en ~100-200 ms.

---

### 2. ARCHIVOS DISPONIBLES EN EL REPOSITORIO (GENERADOS POR QWEN CODER)

Tras hacer `git pull origin main`, ya tienes en el workspace:
1. `ARGOS_MOTOR/config/prime_standard_companies.json`: Catálogo de 172 empresas con ticker, ISIN, LEI, razón social y nombre comercial.
2. `ARGOS_MOTOR/config/eqs_company_slugs.json`: Mapeo exhaustivo de las 172 empresas con sus slugs y alias históricos candidatos ordenados por probabilidad (generado y validado por Qwen Coder).
3. `ARGOS_MOTOR/descarga/de_germany/crawler_eqs_async.py`: Script asíncrono de alto rendimiento listo para ejecutar.

---

### 3. PROTOCOLO DE EJECUCIÓN DIRECTA

Tienes dos opciones operativas:

#### Opción A (Recomendada — Ejecución Inmediata):
Ejecuta directamente el script preconfigurado:
```bash
python ARGOS_MOTOR/descarga/de_germany/crawler_eqs_async.py
```
Este script:
- Emplea `httpx` asíncrono con un semáforo de concurrencia de 25 peticiones concurrentes.
- Itera las 172 empresas para los 14 años (2012–2025).
- Prueba en cascada: `slugs` -> `['EQ-D', 'EQ-E']` -> `['00', '01']`.
- Con solo peticiones `HEAD` (sin descargar el binario para máxima velocidad).
- Guarda automáticamente los resultados en:
  - `ARGOS_MOTOR/config/eqs_verified_links.json`
  - `scratch/eqs_verified_links.json`

#### Opción B (Si deseas ejecutar tu propia implementación):
Escribe tu script asíncrono en Python (`scratch/crawler_eqs_async.py`) con `httpx` o `aiohttp`, asegurando que guarde la salida estructurada en `ARGOS_MOTOR/config/eqs_verified_links.json`.

---

### 4. FORMATO DE SALIDA ESPERADO (`eqs_verified_links.json`)

```json
{
  "_metadata": {
    "crawled_at": "2026-09-23T22:00:00Z",
    "total_companies_checked": 172,
    "companies_with_hits": 130,
    "total_verified_filings": 1250,
    "years_range": "2012-2025",
    "year_stats": {
      "2012": 85,
      "2013": 89,
      "2014": 94,
      "2015": 97,
      "2016": 102,
      "2017": 105,
      "2018": 110,
      "2019": 115,
      "2020": 120,
      "2021": 122,
      "2022": 118,
      "2023": 95,
      "2024": 72,
      "2025": 26
    }
  },
  "companies": {
    "BASF": {
      "isin": "DE000BASF111",
      "name": "BASF SE",
      "reports_count": 14,
      "reports": {
        "2012": {
          "source_url": "https://irpages2.eqs.com/Download/Companies/BASF/Annual%20Reports/DE000BASF111-JA-2012-EQ-D-00.pdf",
          "resolved_url": "https://ir-api.eqs.com/media/document/...",
          "lang": "EQ-D",
          "version": "00",
          "size_bytes": 12450890
        }
      }
    }
  }
}
```

---

### 5. ACCIÓN FINAL POST-EJECUCIÓN

Una vez finalizado el escaneo:
1. Imprime el resumen por consola con el porcentaje de cobertura obtenido por año.
2. Agrega y sube el archivo resultante a git:
   ```bash
   git add ARGOS_MOTOR/config/eqs_verified_links.json
   git commit -m "feat(de_germany): registrar catalogo de enlaces anuales verificados 2012-2025 en EQS"
   git push origin main
   ```
3. Con este catálogo en el repositorio, **Antigravity** en local procederá a la descarga concurrente masiva directamente a `D:/ARGOS_DATA/raw/DE_BAFIN/`, validará el hash SHA-256 de cada documento y generará los manifiestos de auditoría definitivos.
