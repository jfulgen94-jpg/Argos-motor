# SUBMÓDULO DE EXTRACCIÓN E INTERPRETACIÓN: FRANCIA (AMF / PCG / IFRS-UE)

## 1. Marco Contable y Normativo Francés
* **Normativa de Consolidación**: IFRS adoptadas por la UE para emisores de Euronext Paris (CAC 40 y SBF 120).
* **Normativa Social / Individual**: Plan Comptable Général (PCG) aprobado por la Autorité des Normes Comptables (ANC).
* **Auditoría Legal**: *Commissariat aux comptes* regulado por el Code de commerce y las Normes d'Exercice Professionnel (NEP) de la CNCC (Compagnie Nationale des Commissaires aux Comptes).
* **Sostenibilidad**: Déclaration de Performance Extra-Financière (DPEF) / Directiva CSRD, auditada por un Organisme Tiers Indépendant (OTI).

---

## 2. Segmentación: URD Completo vs. RFA Parcial
* **COMPLETO**: *Document d'Enregistrement Universel (URD)*:
  Contiene en un único volumen integrado las cuentas consolidadas IFRS, el informe de gestión (*rapport de gestion*), el informe del consejo sobre el gobierno corporativo, la DPEF y los informes de los comisarios de cuentas (*Rapport des commissaires aux comptes sur les comptes consolidés*).
* **PARCIAL**: *Rapport Financier Annuel (RFA)* simple o informes semestrales (*Rapports semestriels*).

---

## 3. Extracción y Clasificación Forense
El módulo `forensic_audit_fr.py` analiza el dictamen de los commissaires aux comptes:
- `CERTIFICATION_SANS_RESERVE`: Opinión limpia (sin reservas).
- `CERTIFICATION_AVEC_RESERVES`: Opinión con reservas (desacuerdos o limitaciones de auditoría).
- `REFUS_DE_CERTIFIER`: Rechazo de certificación (opinión adversa).
- `OBSERVATIONS_SIGNIFICATIVES`: Párrafos de observación / énfasis.

---

## 4. Ejecución
```bash
python ARGOS_MOTOR/extraccion_interpretacion/fr_france/extractor_fr.py --year 2024
python ARGOS_MOTOR/extraccion_interpretacion/fr_france/forensic_audit_fr.py
```
