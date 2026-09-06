# AUDITORÍA TÉCNICA Y ESTADO REAL: MOD_02_PARSER
**Módulo:** Parser XBRL/iXBRL, Mapeador de Taxonomías y Validador Contable Determinista  
**Ruta en el repositorio:** `ARGOS_MOTOR/mod_02_parser`  
**Estado:** Implementado con parsers duales (ESEF iXBRL HTML y SEC US-GAAP XML), mapeo a diccionario canónico y validador de balance.

---

## 1. INVENTARIO REAL DE ARCHIVOS CREADOS

```
ARGOS_MOTOR/mod_02_parser/
├── README.md                      (Documentación del pipeline de parsing y normalización)
├── config/
│   └── taxonomy_dict.yaml         (Diccionario de 45 conceptos financieros canónicos)
├── src/
│   ├── __init__.py                (Exports de XBRLParser, USGAAPParser, TaxonomyMapper, BalanceValidator)
│   ├── taxonomy_mapper.py         (Mapeador semántico de etiquetas heterogéneas a nombres estándar)
│   ├── xbrl_parser.py             (Parser de paquetes ESEF inline XBRL / XHTML mediante BeautifulSoup)
│   ├── usgaap_parser.py           (Parser de XMLs XBRL de SEC EDGAR con prefijos us-gaap)
│   └── balance_validator.py       (Validador determinista: Activo = Pasivo + Patrimonio Neto)
└── tests/
    ├── __init__.py
    ├── test_balance_validator.py  (Pruebas de balance cuadrado y detección de descuadres hacia cuarentena)
    ├── test_taxonomy_mapper.py    (Pruebas de mapeo de conceptos canónicos)
    └── test_xbrl_parser.py        (Pruebas de extracción de hechos contables iXBRL y XML)
```

---

## 2. CLASES, MÉTODOS Y LÓGICA IMPLEMENTADA

### A. `TaxonomyMapper` (`src/taxonomy_mapper.py` + `config/taxonomy_dict.yaml`)
- **Propósito:** Traducir cientos de variantes de nombres contables de taxonomías IFRS y US-GAAP a un conjunto unificado de conceptos canónicos (`total_activo`, `revenue`, `patrimonio_neto`, `ebitda`, `ebit`, `cfo`, `fcf`, etc.).
- **Métodos Implementados:**
  - `map_concept(raw_concept: str) -> Optional[str]`: Normaliza el string eliminando prefijos (`ifrs-full:`, `us-gaap:`, `esef:`), espacios y caracteres especiales, consultando el diccionario YAML cargado en memoria.

### B. `XBRLParser` (`src/xbrl_parser.py`)
- **Propósito:** Procesar informes financieros anuales en formato Inline XBRL (iXBRL / XHTML) de empresas europeas.
- **Métodos Implementados:**
  - `parse_ixbrl_html(content_str: str, entity_lei: str, fiscal_year: int) -> List[Dict[str, Any]]`:
    - Utiliza `BeautifulSoup(content_str, "html.parser")`.
    - Localiza etiquetas `ix:nonFraction` e `ix:fraction`.
    - Extrae el concepto (`name`), el valor numérico (limpiando comas de formato inglés) y la unidad (`unitref`, por defecto `EUR`).
    - Mapea el concepto a estándar canónico y devuelve la lista de hechos estructurados.

### C. `USGAAPParser` (`src/usgaap_parser.py`)
- **Propósito:** Procesar documentos XML de instancias XBRL tradicionales de la SEC de EE.UU.
- **Métodos Implementados:**
  - `parse_xbrl_xml(xml_content: str, entity_lei: str, fiscal_year: int) -> List[Dict[str, Any]]`:
    - Utiliza `BeautifulSoup(xml_content, "xml")`.
    - Itera sobre todos los tags con prefijo o namespace `us-gaap`.
    - Extrae valor numérico, mapea a concepto canónico y asigna unidad (`unitRef`, por defecto `USD`).

### D. `BalanceValidator` (`src/balance_validator.py`)
- **Propósito:** Garantizar matemáticamente la ecuación fundamental de la contabilidad (`Total Activo = Total Pasivo + Patrimonio Neto`).
- **Métodos Implementados:**
  - `validate(total_assets: float, total_liabilities: float, equity: float, tolerance: float = 100.0) -> Tuple[bool, float]`:
    - Calcula el descuadre exacto: `imbalance = abs(total_assets - (total_liabilities + equity))`.
    - Si `imbalance <= tolerance`, retorna `(True, imbalance)`.
    - Si no, retorna `(False, imbalance)` marcando el filing para envío a la tabla de cuarentena.

---

## 3. SUITE DE TESTS IMPLEMENTADOS (`tests/`)
- `test_balanced_filing_passes`: Comprueba que un balance cuadrado (`100 = 60 + 40`) pasa con `is_valid = True` e `imbalance = 0.0`.
- `test_imbalanced_filing_goes_to_quarantine`: Comprueba que un balance descuadrado (`100 != 50 + 40`) devuelve `is_valid = False` e `imbalance = 10.0`.
- `test_taxonomy_mapper_mappings`: Verifica mapeos clave (`Assets` → `total_activo`, `Revenues` → `revenue`).
- `test_parse_ixbrl_html`: Valida extracción desde fragmentos HTML con `<ix:nonFraction name="ifrs-full:Assets">`.
- `test_parse_usgaap_xml`: Valida extracción desde XML con `<us-gaap:Revenues>`.

---

## 4. ANÁLISIS DE CAPACIDADES Y GAPS
- **Capacidad Real:** El parser es ligero, rápido y desacoplado, mapeando conceptos heterogéneos a un esquema unificado.
- **Gap:** Actualmente extrae hechos individuales basados en etiquetas lineales; no procesa contextos dimensionales complejos (ej. desglose por segmentos geográficos o periodos comparativos multianuales dentro del mismo filing).
