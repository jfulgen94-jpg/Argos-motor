# SUBMÓDULO DE EXTRACCIÓN E INTERPRETACIÓN: ALEMANIA (BAFIN / HGB / IFRS-UE)

## 1. Marco Contable y Normativo Alemán
* **Normativa de Consolidación**: IFRS adoptadas por la UE (Sección 315e del Código de Comercio alemán - *Handelsgesetzbuch / HGB*).
* **Normativa Individual**: Handelsgesetzbuch (HGB) y principios de contabilidad generalmente aceptados alemanes (*GoB - Grundsätze ordnungsmäßiger Buchführung*).
* **Auditoría Legal**: Realizada por auditores jurados de cuentas (*Wirtschaftsprüfer / WP*) regulados por el WPO (Wirtschaftsprüferordnung) y normas del IDW (Institut der Wirtschaftsprüfer in Deutschland).
* **Sostenibilidad**: *Nichtfinanzieller Konzernbericht* (Sección 315b HGB) / CSRD.

---

## 2. Segmentación: Geschäftsbericht vs. Einzelabschluss
* **COMPLETO**: *Geschäftsbericht (Konzernbericht)*:
  Integra en una sola estructura:
  1. *Konzern-Gewinn- und Verlustrechnung* (Cuenta de resultados consolidada).
  2. *Konzernbilanz* (Balance consolidado).
  3. *Konzernanhang* (Memoria consolidada).
  4. *Zusammengefasster Lagebericht* (Informe de gestión consolidado).
  5. *Bestätigungsvermerk des unabhängigen Abschlussprüfers* (Dictamen de auditoría).
* **PARCIAL**: *Einzelabschluss HGB* (estados no consolidados individuales de la matriz) o informes trimestrales (*Quartalsmitteilungen*).

---

## 3. Extracción y Clasificación Forense
El script `forensic_audit_de.py` clasifica el *Bestätigungsvermerk*:
- `UNEINGESCHRAENKTER_BESTAETIGUNGSVERMERK`: Dictamen de auditoría sin salvedades (limpio).
- `EINGESCHRAENKTER_BESTAETIGUNGSVERMERK`: Dictamen con salvedades.
- `VERSAGUNGSVERMERK`: Denegación de opinión o dictamen negativo.
- `HERVORHEBUNG_EINES_SACHVERHALTS`: Párrafos de énfasis (*Emphasis of Matter*).

---

## 4. Ejecución
```bash
python ARGOS_MOTOR/extraccion_interpretacion/de_germany/extractor_de.py --year 2024
python ARGOS_MOTOR/extraccion_interpretacion/de_germany/forensic_audit_de.py
```
