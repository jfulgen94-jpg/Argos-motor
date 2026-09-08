# SUBMÓDULO DE DESCARGA: ITALIA (CONSOB / 1INFO / EMARKET STORAGE)

## 1. Identificación y Regulación del OAM en Italia
* **Autoridad Nacional Competente (NCA)**: Commissione Nazionale per le Società e la Borsa (CONSOB - `consob.it`).
* **Mecanismos Centralizados Oficiales de Almacenamiento (OAM - Storage Autorizzati)**:
  A diferencia de Francia o Alemania, CONSOB autoriza mecanismos privados certificados bajo el Reglamento de Emisores (art. 65-septies):
  1. **`1Info`** (`1info.it`): Plataforma operada por **Computershare S.p.A.** autorizada por CONSOB para el archivo centralizado de información regulada.
  2. **`eMarket STORAGE`** (`emarketstorage.it`): Plataforma operada por **Teleborsa S.r.l. / Spafid Connect** (Grupo Mediobanca / Euronext).
* **Aclaración Jurídica Fundamental**:
  En Italia, el acrónimo *OAM* corresponde oficialmente al *Organismo degli Agenti e dei Mediatori* (supervisión de agentes financieros y proveedores cripto). El mecanismo centralizado para información financiera corporativa se denomina estrictamente **Sistema di Stoccaggio Centralizzato (Storage Autorizzato)**.
* **Mercados e Índices**: Borsa Italiana / Euronext Milan (FTSE MIB, FTSE Italia Mid Cap, Euronext Growth Milan).
* **Entidades Clave**: Enel, Eni, Intesa Sanpaolo, UniCredit, Ferrari, Stellantis, Assicurazioni Generali, Leonardo, Moncler, Prysmian, Campari.

---

## 2. Estratificación del Método de Descarga
### Canal A: Ingesta ESEF / XBRL Oficial
* Para ejercicios $FY_{2021}$ en adelante, los emisores de Borsa Italiana publican el paquete ESEF en su mecanismo de almacenamiento asignado (`1Info` o `eMarket STORAGE`) y en el repositorio europeo.
* Se consulta vía LEI y código ISIN italiano.

### Canal B: Plataformas 1Info / eMarket STORAGE
* Descarga de la *Relazione Finanziaria Annuale* (Bilancio d'Esercizio, Bilancio Consolidato, Relazione del Collegio Sindacale e Relazione della Società di Revisione).
* Formatos: `.zip` (ESEF), `.pdf` (documento firmado digitalmente con marca de tiempo).

---

## 3. Configuración Documental Italiana
* **Relazione Finanziaria Annuale (Completa)**:
  1. *Bilancio Consolidato e Separato* (Estados financieros bajo IFRS/NIIF-UE).
  2. *Relazione sulla Gestione* (Informe de gestión, art. 2428 c.c.).
  3. *Dichiarazione Non Finanziaria (DNF / CSRD)* (D.Lgs. 254/2016).
  4. *Relazione della Società di Revisione* (Dictamen de auditoría emitido según art. 14 del D.Lgs. 39/2010).
  5. *Relazione del Collegio Sindacale* (Informe del órgano de control interno italiano).
  6. *Relazione sul Governo Societario e gli Assetti Proprietari*.

---

## 4. Auditoría de la Descarga (Italia)
* En `data/raw/IT_CONSOB/`, se auditan los 84 registros existentes que actualmente se encuentran en estado `.meta.json` para ejecutar la descarga de sus paquetes primarios ESEF.
* Sellado criptográfico SHA-256 en `MANIFEST_IT_CONSOB_{YYYYMMDD}.json`.

---

## 5. Ejecución
```bash
# Descarga de emisores italianos FTSE MIB
python ARGOS_MOTOR/descarga/it_italy/downloader_consob.py --index FTSEMIB --years 2022,2023,2024

# Auditoría de descargas
python ARGOS_MOTOR/descarga/it_italy/audit_download_it.py
```
