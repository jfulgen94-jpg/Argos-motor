# AUDITORÍA TÉCNICA Y ESTADO REAL: MOD_05_QUANT_SFI
**Módulo:** Motor Cuantitativo de Ratios Financieros y Valoración DCF (SFI Lab)  
**Ruta en el repositorio:** `ARGOS_MOTOR/mod_05_quant_sfi`  
**Estado:** Implementado con motor determinista de 40+ ratios y modelo DCF con matrices de sensibilidad.

---

## 1. INVENTARIO REAL DE ARCHIVOS CREADOS

```
ARGOS_MOTOR/mod_05_quant_sfi/
├── README.md                      (Documentación de fórmulas financieras y modelo de valoración)
├── src/
│   ├── __init__.py                (Exports de RatioEngine, DCFEngine, safe_div)
│   ├── ratio_engine.py            (Calculador determinista de ratios de liquidez, solvencia, rentabilidad y DuPont)
│   └── dcf_engine.py              (Modelo de descuento de flujos de caja libre y sensibilidad WACC/g)
└── tests/
    ├── __init__.py
    ├── test_ratio_engine.py       (Pruebas de safe_div y cálculo exhaustivo de ratios)
    └── test_dcf_engine.py         (Pruebas de valoración intrínseca y validación de parámetros WACC/g)
```

---

## 2. CLASES, FÓRMULAS Y MÉTODOS IMPLEMENTADOS

### A. `safe_div` y `RatioEngine` (`src/ratio_engine.py`)
- **`safe_div(num, den)`:** Previene `ZeroDivisionError` y gestiona `NaN` / `None`, redondeando a 6 decimales.
- **Familias de Ratios Calculadas en `compute_all_ratios(f: dict)`:**
  1. **Liquidez:**
     - `current_ratio = activo_corriente / pasivo_corriente`
     - `quick_ratio = (activo_corriente - existencias) / pasivo_corriente`
     - `cash_ratio = efectivo / pasivo_corriente`
  2. **Solvencia y Endeudamiento:**
     - `debt_to_equity = deuda_total / patrimonio_neto`
     - `debt_to_assets = deuda_total / total_activo`
     - `financial_leverage = total_activo / patrimonio_neto`
     - `net_debt = deuda_total - efectivo`
     - `net_debt_to_ebitda = net_debt / ebitda`
  3. **Rentabilidad y Descomposición DuPont:**
     - `gross_margin = gross_profit / revenue`
     - `ebitda_margin = ebitda / revenue`
     - `net_margin = beneficio_neto / revenue`
     - `roa = beneficio_neto / total_activo`
     - `roe = beneficio_neto / patrimonio_neto`
     - `roic = nopat / invested_capital` *(NOPAT = EBIT * (1 - TaxRate))*
     - *DuPont 3 Factores:* `Margen Neto * Rotación de Activos * Apalancamiento Financiero`.
  4. **Eficiencia y Flujo de Caja:**
     - `asset_turnover = revenue / total_activo`
     - `fcf_conversion = fcf / ebitda`
     - `fcf_margin = fcf / revenue`

### B. `DCFEngine` (`src/dcf_engine.py`)
- **Propósito:** Determinar el valor intrínseco por acción mediante proyección de Free Cash Flow a 5 años y valor terminal Gordon Shapiro.
- **Métodos Implementados:**
  - `calculate_valuation(base_fcf: float, shares_outstanding: float, net_debt: float = 0.0, forecast_years: int = 5, growth_rate: float = 0.05, base_wacc: float = 0.09, base_terminal_g: float = 0.025) -> Dict[str, Any]`:
    - Valida que `base_wacc > base_terminal_g` (evita asíntota matemática).
    - Proyecta FCFs futuros y los descuenta al WACC actual.
    - Calcula el Valor Terminal: `TV = [FCF_n * (1 + g)] / (WACC - g)`.
    - Calcula Enterprise Value (`EV = PV(FCFs) + PV(TV)`) y Equity Value (`Equity = EV - NetDebt`).
    - Obtiene el **Valor Intrínseco por Acción** (`intrinsic_value_per_share = Equity / shares`).
    - **Matriz de Sensibilidad:** Genera una cuadrícula bidimensional evaluando WACC (-1%, 0, +1%) vs. g (-0.5%, 0, +0.5%).

---

## 3. SUITE DE TESTS IMPLEMENTADOS (`tests/`)
- `test_safe_div`: Comprueba división por cero, `None` y números válidos.
- `test_ratio_engine_computations`: Verifica cálculos de ROE, ROA, ROIC y márgenes.
- `test_dcf_engine_valuation`: Valida que el valor intrínseco por acción y la matriz de sensibilidad de 9 celdas sean matemáticamente exactos.
- `test_dcf_engine_invalid_inputs`: Verifica que `WACC <= g` o `shares <= 0` lance `ValueError`.

---

## 4. ANÁLISIS DE CAPACIDADES Y GAPS
- **Capacidad Real:** Motores matemáticos 100% deterministas, sin librerías externas pesadas y con ejecución en microsegundos.
- **Gap:** Requiere que el panel de datos financieros de entrada tenga los campos `cfo`, `capex` y `ebt` bien poblados para calcular el 100% de los 40 ratios.
