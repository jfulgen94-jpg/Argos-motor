# MOD_05 — Motor Cuantitativo SFI Lab

## Propósito
Calcula 40+ ratios financieros, construye factores cuantitativos (Value, Quality, Momentum, Low Volatility), ejecuta el DCF determinista con matrices de sensibilidad WACC × g, y el S-Score v2.0 de Capital Humano.

## Inputs
- Tabla `financial_panel` (de MOD_04)
- Tabla `esg_kpis` (de MOD_03 vía MOD_04)

## Outputs
- Tabla `ratios_panel` en capa ANALYTICS
- Tabla `scores_panel` (scores E, S, G, total, S-Score v2.0)
- Tabla `dcf_valuations` (Bear/Base/Bull)

## Fórmulas clave
Definidas en `config/formulas.yaml`. Ejemplo:
```yaml
roic:
  formula: "ebit * (1 - tax_rate) / (total_activo - activo_corriente)"
  source_fields: [ebit, tax_rate, total_activo, activo_corriente]
```
