# SUBMÓDULO DE DESCARGA: ALEMANIA (BAFIN / UNTERNEHMENSREGISTER)

## 1. Identificación y Regulación del OAM en Alemania
* **Autoridad Nacional Competente (NCA)**: Bundesanstalt für Finanzdienstleistungsaufsicht (BaFin - `bafin.de`).
* **Mecanismo Centralizado Oficial (OAM)**: **`www.unternehmensregister.de`** (Operado por Bundesanzeiger Verlag GmbH, designado conforme a la Sección 26 de la WpHG - Ley alemana del mercado de valores y la Directiva de Transparencia 2004/109/CE).
* **Fuentes Complementarias**:
  - **Bundesanzeiger** (`bundesanzeiger.de`): Diario oficial para publicaciones societarias y estados contables.
  - **Handelsregister**: Registro mercantil judicial (para datos constitutivos).
  - **BaFin Unternehmensdatenbank**: Base de datos de emisores bajo supervisión.
* **Mercados e Índices**: Frankfurt Stock Exchange / Deutsche Börse (DAX 40, MDAX, SDAX, Regulierter Markt).
* **Entidades Clave**: SAP, Siemens, Allianz, Deutsche Telekom, Mercedes-Benz, BMW, Bayer, BASF, Deutsche Bank, Volkswagen, Munich Re.

---

## 2. Estratificación del Método de Descarga
La ingesta en Alemania debe distinguir con rigor entre:
1. **El OAM (Unternehmensregister)**: Plataforma obligatoria donde se depositan los *Rechnungslegungsunterlagen* (informes financieros anuales consolidados con dictamen de auditoría y paquete ESEF).
2. **El Transparenzregister**: Registro de titularidad real / beneficiarios efectivos (no almacena informes financieros).

### Canal A: Ingesta ESEF / XBRL Oficial
* Para ejercicios $FY_{2021}$ en adelante, las empresas del Prime Standard y General Standard depositan el archivo ZIP reglamentario ESEF.
* Se consulta vía LEI en la federación ESEF europea y los metadatos sincronizados de `unternehmensregister.de`.

### Canal B: Bundesanzeiger / Unternehmensregister Web API
* Búsqueda institucional por número de registro mercantil (*Handelsregisternummer* ej. HRB) o código LEI.
* Descarga de balances certificados en formato PDF/A y xHTML.

---

## 3. Configuración Documental Alemana
* **Geschäftsbericht (Informe Anual Completo)**: Integra:
  1. *Konzernabschluss* (Cuentas Anuales Consolidadas bajo IFRS/NIIF-UE).
  2. *Konzernlagebericht* (Informe de Gestión Consolidado, Sección 315 HGB).
  3. *Nichtfinanzieller Bericht* (Declaración no financiera / Sostenibilidad CSRD).
  4. *Bestätigungsvermerk des unabhängigen Abschlussprüfers* (Dictamen del auditor de cuentas).
  5. *Bericht des Aufsichtsrats* (Informe del Consejo de Supervisión).
* **Einzelabschluss (Cuentas Individuales)**: Cuentas no consolidadas elaboradas bajo el Código de Comercio alemán (*HGB - Handelsgesetzbuch*). Se marcan como **PARCIAL**.

---

## 4. Auditoría de la Descarga (Alemania)
* Comprobación de magic bytes y descarte de respuestas captcha del Bundesanzeiger.
* Sellado criptográfico SHA-256 en `MANIFEST_DE_BAFIN_{YYYYMMDD}.json`.
* Detección de cuarentena para páginas de error o visualizadores HTML vacíos (*Empty Skeleton / Viewer*).

---

## 5. Ejecución
```bash
# Descarga de emisores alemanes DAX 40
python ARGOS_MOTOR/descarga/de_germany/downloader_bafin.py --index DAX40 --years 2022,2023,2024

# Auditoría de descargas
python ARGOS_MOTOR/descarga/de_germany/audit_download_de.py
```
