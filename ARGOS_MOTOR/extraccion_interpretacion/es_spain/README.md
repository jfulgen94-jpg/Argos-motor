# SUBMÓDULO DE EXTRACCIÓN E INTERPRETACIÓN: ESPAÑA (CNMV / PGC / NIIF-UE)

## 1. Marco Técnico y Normativo Contable
* **Normativa de Consolidación**: Normas Internacionales de Información Financiera adoptadas por la Unión Europea (NIIF-UE / IFRS-EU).
* **Normativa Individual**: Plan General de Contabilidad español (PGC - Real Decreto 1514/2007) y Circulares contables de la CNMV / Banco de España.
* **Marco de Información No Financiera y Sostenibilidad**: Ley 11/2018 en materia de información no financiera y diversidad (EINF) y directiva CSRD.
* **Normas Técnicas de Auditoría**: Normas Internacionales de Auditoría adaptadas para su aplicación en España (NIA-ES) emitidas por el ICAC (Instituto de Contabilidad y Auditoría de Cuentas).

---

## 2. Segmentación Documental: Completo vs. Parcial
El extractor clasifica cada paquete procesado en disco:

### A. Informe Anual Completo (ESEF / IFA Integrado)
Requisito estricto: Debe integrar en una única estructura auditable:
1. **Balance de Situación Consolidado** (*Statement of Financial Position*).
2. **Cuenta de Pérdidas y Ganancias Consolidada** (*Income Statement / Statement of Comprehensive Income*).
3. **Estado de Flujos de Efectivo** (*Statement of Cash Flows*).
4. **Estado de Cambios en el Patrimonio Neto** (*Statement of Changes in Equity*).
5. **Memoria Consolidada** (*Notes to the Financial Statements*).
6. **Informe de Gestión Consolidado** (incluyendo evolución de negocios, riesgos, I+D, autocartera).
7. **Estado de Información No Financiera (EINF)** verificado por prestador independiente.
8. **Informe de Auditoría de Cuentas Anuales Consolidadas** emitido por auditor inscrito en el ROAC.

### B. Informes Parciales (Descargas Específicas / Satélites)
* **Solo Informe de Auditoría**: Emisión separada del dictamen de auditoría sin las notas completas.
* **Informes Financieros Semestrales (H1)** e **Intermedios (Q1/Q3)**.
* **Informe Anual de Gobierno Corporativo (IAGC)** e **Informe Anual de Remuneraciones (IARC)**.

---

## 3. Motor de Auditoría Forense y NLP Contable
El script `forensic_audit_es.py` ejecuta las siguientes verificaciones forenses:
1. **Categorización del Dictamen de Auditoría**:
   - `OPINION_FAVORABLE`: Opinión limpia sin modificaciones.
   - `OPINION_CON_SALVEDADES`: Salvedades por limitación al alcance o desacuerdo con el marco contable.
   - `OPINION_DESFAVORABLE`: Efecto muy significativo de incorrecciones materiales.
   - `DENEGACION_DE_OPINION`: Limitación de alcance generalizada o incertidumbre extrema.
2. **Párrafos de Énfasis y Cuestiones Clave (KAM)**:
   - Detección de párrafos de énfasis (*Emphasis of Matter*) sobre contingencias fiscales, litigios o valoraciones de activos intangibles (*goodwill*).
   - Extracción estructurada de Cuestiones Clave de Auditoría (p. ej. deterioro de activos, provisiones crediticias según NIIF 9, reconocimiento de ingresos según NIIF 15).
3. **Conciliación Matemática de Balances**:
   - $Activo\ Total == Pasivo\ Total + Patrimonio\ Neto$.
   - Verificación de concordancia entre el resultado del ejercicio en la cuenta de resultados y el traspaso a reservas en el estado de cambios en el patrimonio neto.

---

## 4. Ejecución
```bash
# Extraer estados financieros y segmentar
python ARGOS_MOTOR/extraccion_interpretacion/es_spain/extractor_es.py --year 2024

# Ejecutar auditoría forense y control de salvedades
python ARGOS_MOTOR/extraccion_interpretacion/es_spain/forensic_audit_es.py
```
