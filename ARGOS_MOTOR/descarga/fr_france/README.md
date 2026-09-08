# SUBMÓDULO DE DESCARGA: FRANCIA (AMF / INFO-FINANCIÈRE)

## 1. Identificación y Regulación del OAM en Francia
* **Autoridad Nacional Competente (NCA)**: Autorité des marchés financiers (AMF - `amf-france.org`).
* **Mecanismo Centralizado Oficial (OAM)**: **`info-financiere.gouv.fr`** (Gestionado por la Direction de l'information légale et administrative - DILA, bajo supervisión de la AMF de acuerdo a la Directiva de Transparencia 2004/109/CE).
* **Plataforma de Decisiones y Divulgación Regulatoria**: **BDIF** (Base des Décisions et Informations Financières - AMF / data.gouv.fr).
* **Mercados e Índices**: Euronext Paris (CAC 40, SBF 120, Euronext Growth Paris).
* **Entidades Clave**: Airbus SE, LVMH, TotalEnergies, Sanofi, BNP Paribas, Schneider Electric, Air Liquide, AXA, Hermès, L'Oréal, Vinci.

---

## 2. Estratificación del Método de Descarga
La ingesta en Francia se divide en dos vías complementarias:

### Vía 1: Endpoint Centralizado OAM (`info-financiere.gouv.fr`)
* **Naturaleza**: Repositorio oficial centralizado donde los emisores depositan obligatoriamente sus *Rapports Financiers Annuels (RFA)* y *Documents d'Enregistrement Universel (URD)*.
* **Canal Técnico**:
  - Consulta web estructurada por número SIREN/LEI o denominación social.
  - Formato documental: Paquetes ZIP con taxonomía ESEF RTS (a partir de FY2021) y documentos PDF/A certificados con firma digital.
  - Metadatos disponibles: Fecha y hora exacta de depósito ante el OAM, código de archivo de difusión (*diffuseur agréé*).

### Vía 2: API Abierta BDIF / data.gouv.fr
* **Naturaleza**: Conjunto de datos abiertos de la AMF publicados en `data.gouv.fr` que lista la totalidad de decisiones, visados de folletos, y notificaciones de operaciones de directivos e información periódica.
* **Uso en ARGOS**: Sincronización diaria para detectar la publicación de nuevos informes anuales o hechos relevantes (*communiqués de presse réglementés*).

---

## 3. Configuración Documental y Tipología de Archivos
* **Document d'Enregistrement Universel (URD)**: Documento de referencia anual que agrupa las cuentas anuales consolidadas (normas IFRS-UE), el informe de gestión (*rapport de gestion*), el informe de gobierno corporativo (*rapport sur le gouvernement d'entreprise*), la declaración de rendimiento extrafinanciero (*DPEF / CSRD*) y los informes de los auditores de cuentas (*Rapports des commissaires aux comptes*).
* **Rapport Financier Annuel (RFA)**: En caso de no publicar URD, el emisor deposita el RFA estricto.
* **Paquete ESEF**: Fichero ZIP conteniendo el informe primario en `.xhtml` etiquetado con la taxonomía IFRS y las extensiones locales de la empresa.

---

## 4. Auditoría de la Propia Descarga (Francia)
Para cada archivo descargado en `data/raw/FR_AMF/`:
1. **Validación de Identidad**: Cotejo del código LEI y número SIREN francés (9 dígitos) contra el registro oficial del INSEE / GLEIF.
2. **Validación de Integridad**: Comprobación de magic bytes (`PK\x03\x04` para ESEF o `%PDF-`).
3. **Sellado Criptográfico**: Generación de hash SHA-256 e inclusión en el manifiesto `MANIFEST_FR_AMF_{YYYYMMDD}.json`.
4. **Detección de Cuarentena**: Si el servidor de `info-financiere` o Euronext devuelve una página de términos de servicio (ToS) o un aviso legal HTML en lugar del binario, el archivo se redirige a cuarentena.

---

## 5. Ejecución
```bash
# Descarga de emisores franceses (CAC 40 / SBF 120)
python ARGOS_MOTOR/descarga/fr_france/downloader_amf.py --index CAC40 --year 2024

# Auditoría y verificación de descargas
python ARGOS_MOTOR/descarga/fr_france/audit_download_fr.py
```
