# SUBMÓDULO DE EXTRACCIÓN E INTERPRETACIÓN: ITALIA (CONSOB / OIC / IFRS-UE)

## 1. Marco Contable y Normativo Italiano
* **Normativa de Consolidación**: IFRS adoptadas por la UE (D.Lgs. 38/2005) para sociedades cotizadas en Euronext Milan (MTA / FTSE MIB).
* **Normativa Individual**: Código Civil italiano (*Codice Civile*, arts. 2423 y ss.) y principios contables nacionales emitidos por el OIC (Organismo Italiano di Contabilità).
* **Auditoría Legal**: *Revisione legale dei conti* (D.Lgs. 39/2010 y D.Lgs. 135/2016) ejecutada por sociedades de auditoría inscritas en el registro del MEF/CONSOB.
* **Sostenibilidad**: Dichiarazione Non Finanziaria (DNF - D.Lgs. 254/2016) / CSRD.

---

## 2. Segmentación: Relazione Finanziaria Annuale vs. Bilancio Parziale
* **COMPLETO**: *Relazione Finanziaria Annuale*:
  Integra:
  1. *Stato Patrimoniale Consolidato* (Balance consolidado).
  2. *Conto Economico Consolidato* (Cuenta de pérdidas y ganancias).
  3. *Rendiconto Finanziario* (Flujos de efectivo).
  4. *Nota Integrativa* (Memoria explicativa).
  5. *Relazione sulla Gestione* (Informe de gestión).
  6. *Relazione della Società di Revisione* (Dictamen del auditor).
  7. *Relazione del Collegio Sindacale* (Informe de la sindicatura).
  8. *Dichiarazione Non Finanziaria (DNF)*.
* **PARCIAL**: *Bilancio Separato* o *Resoconti intermedi di gestione* (informes trimestrales).

---

## 3. Extracción Forense y Clasificación de Dictamen
El script `forensic_audit_it.py` clasifica la opinión de la *Società di Revisione*:
- `GIUDIZIO_SENZA_MODIFICHE`: Opinión favorable sin modificaciones (limpia).
- `GIUDIZIO_CON_MODIFICHE`: Opinión con salvedades / modificaciones.
- `GIUDIZIO_NEGATIVO`: Opinión adversa.
- `DICHIARAZIONE_DI_IMPOSSIBILITA_DI_ESPRIMERE_UN_GIUDIZIO`: Denegación de opinión.
- `RICHIAMI_DI_INFORMATIVA`: Párrafos de énfasis (*Emphasis of Matter*).

---

## 4. Ejecución
```bash
python ARGOS_MOTOR/extraccion_interpretacion/it_italy/extractor_it.py --year 2024
python ARGOS_MOTOR/extraccion_interpretacion/it_italy/forensic_audit_it.py
```
