# MOD_02 — Motor Parser XBRL / iXBRL

## Propósito
Convierte los filings XBRL (US-GAAP) e iXBRL (ESEF) en tablas financieras estructuradas en DuckDB. Aplica la regla de cuadre de balance con tolerancia cero.

## Regla de Oro — Tolerancia Cero en Cuadre
```
Activo Total = Pasivo Total + Patrimonio Neto
```
Cualquier filing que no cumpla esta condición se envía automáticamente a CUARENTENA.

## Inputs
- Archivos crudos de `data/raw/` (provistos por MOD_01)
- Diccionario de taxonomía: `config/taxonomy_dict.yaml`

## Outputs
- Tabla `financial_facts_raw` (datos granulares XBRL)
- Tabla `financial_panel` (panel anual normalizado por empresa)

## Ejecución
```bash
python src/xbrl_parser.py --doc_id AAPL_2024_10K
python src/balance_validator.py --batch
```
