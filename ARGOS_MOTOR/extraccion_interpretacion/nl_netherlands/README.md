# SUBMÓDULO DE EXTRACCIÓN E INTERPRETACIÓN: PAÍSES BAJOS (AFM / DUTCH GAAP / IFRS-UE)

## 1. Marco Contable y Normativo Neerlandés
* **Normativa de Consolidación**: IFRS adoptadas por la UE para emisores cotizados en Euronext Amsterdam (AEX 25 / AMX).
* **Normativa Individual**: Libro 2, Título 9 del Código Civil neerlandés (*Burgerlijk Wetboek / BW2 Titel 9*) y directrices de la *Raad voor de Jaarverslaggeving (RJ)*.
* **Auditoría Legal**: Realizada por contables públicos colegiados (*Registeraccountant - RA*) regulados por la NBA (Koninklijke Nederlandse Beroepsorganisatie van Accountants) bajo las normas NVCOS (Nadere voorschriften controle- en overige standaarden).
* **Sostenibilidad**: *Duurzaamheidsrapportage* / CSRD.

---

## 2. Segmentación: Geïntegreerd Jaarverslag vs. Jaarrekening
* **COMPLETO**: *Geïntegreerd Jaarverslag (Annual Integrated Report)*:
  Integra:
  1. *Geconsolideerde Winst-en-verliesrekening* (Cuenta de pérdidas y ganancias consolidada).
  2. *Geconsolideerde Balans* (Balance consolidado).
  3. *Toelichting op de Geconsolideerde Jaarrekening* (Memoria consolidada).
  4. *Bestuursverslag* (Informe del consejo de administración).
  5. *Controleverklaring van de onafhankelijke accountant* (Dictamen del auditor).
  6. *Duurzaamheidsverslag / CSRD*.
* **PARCIAL**: *Enkelvoudige Jaarrekening* (cuentas no consolidadas) o informes provisionales (*Halfjaarberichten*).

---

## 3. Extracción Forense y Clasificación de Dictamen
El script `forensic_audit_nl.py` clasifica la *Controleverklaring*:
- `GOEDKEURENDE_CONTROLEVERKLARING`: Dictamen favorable sin salvedades (limpio / approved).
- `CONTROLEVERKLARING_MET_BEPERKING`: Dictamen con salvedades (*qualified*).
- `AFKEURENDE_CONTROLEVERKLARING`: Dictamen desfavorable (*adverse*).
- `OORDEELSONTHOUDING`: Denegación de opinión (*disclaimer of opinion*).
- `BENADRUKKING_VAN_AANGELEGENHEDEN`: Párrafos de énfasis (*Emphasis of Matter*).

---

## 4. Ejecución
```bash
python ARGOS_MOTOR/extraccion_interpretacion/nl_netherlands/extractor_nl.py --year 2024
python ARGOS_MOTOR/extraccion_interpretacion/nl_netherlands/forensic_audit_nl.py
```
