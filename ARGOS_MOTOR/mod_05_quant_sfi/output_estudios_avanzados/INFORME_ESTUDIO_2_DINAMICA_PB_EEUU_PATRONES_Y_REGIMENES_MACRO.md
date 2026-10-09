# INFORME PERICIAL 2: DINÁMICA DE RELACIONES P/B EN ESTADOS UNIDOS
## EVOLUCIÓN HISTÓRICA, EQUILIBRIO EN RANGOS INDIVIDUALES, CASOS ATÍPICOS Y REGÍMENES MACRO (2019 - 2026)

**Entorno de Análisis:** SFI Quantitative Lab — Argos Motor  
**Universo Auditado:** Muestra representativa de cotizadas de EE.UU. (NYSE / NASDAQ - 56 cotizadas)  
**Dataset Histórico Subyacente:** [`02_series_historicas_pb_usa_2019_2026.csv`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/mod_05_quant_sfi/output_estudios_avanzados/02_series_historicas_pb_usa_2019_2026.csv)  
**Resumen Sectorial Macro:** [`04_analisis_sectores_y_regimenes_macro_pb.csv`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/mod_05_quant_sfi/output_estudios_avanzados/04_analisis_sectores_y_regimenes_macro_pb.csv)  

---

### 1. ¿RIGE EL FENÓMENO DE "CARAS VS. BARATAS" EL MERCADO O SON OTROS FACTORES?
#### El Múltiplo P/B como Termómetro y no como Causa

El análisis pericial demuestra que el ratio Precio/Valor Contable ($P/B$) **no determina el precio por sí mismo, sino que es un resultado matemático** de la rentabilidad esperada del capital contable según el modelo fundamental de valoración residual (Edwards-Bell-Ohlson / Gordon):

$$\frac{P}{B} = 1 + \frac{ROE - r}{r - g}$$

Donde $ROE$ es la rentabilidad sobre recursos propios, $r$ es la tasa de rentabilidad exigida (coste del capital) y $g$ es la tasa de crecimiento sostenible:
- Si una empresa genera de forma consistente un $ROE > r$ (retorno superior al coste de capital), la acción **cotiza estructuralmente con prima** ($P/B > 1,0\text{x}$).
- Si una empresa genera un $ROE < r$, el mercado destruye valor contable y cotiza con **descuento estructural** ($P/B < 1,0\text{x}$).
- **Factores reales que mueven los precios:** El precio no se mueve porque una acción "esté barata a P/B 0,5x", sino por:
  1. Shocks en la rentabilidad operativa subyacente ($\Delta ROE$ y $\Delta \text{Márgenes}$).
  2. Olas de liquidez macroeconómica (regímenes de tipos de la Reserva Federal).
  3. Expectativas de obsolescencia tecnológica vs. foso defensivo (*economic moat*).

---

### 2. ¿TIENDEN LAS EMPRESAS A UN EQUILIBRIO EN UN RANGO CARACTERÍSTICO?
#### Reversión a la Media a Nivel de Firma vs. Equilibrio del Mercado

Las cotizadas estadounidenses **no revierten hacia una media universal de mercado** (el mercado no fuerza a Apple a cotizar a $P/B = 1,0\text{x}$ ni a Ford a cotizar a $P/B = 5,0\text{x}$). 

Por el contrario, cada empresa oscila en torno a un **atractor estacionario individual (canal de múltiplos)** configurado por la naturaleza de su negocio:

```
[Banda Tecnológica / Software] P/B: 8x ──────────────────────────── 25x (Apple, Microsoft, Nvidia)
[Banda Calidad / Consumo Defensivo] P/B: 4x ────────────── 10x (P&G, Coca-Cola, Johnson & Johnson)
[Banda Cíclica / Energía / Finanzas] P/B: 1.1x ───── 1.6x (JPMorgan, ExxonMobil, Chevron)
[Banda Deep Value / Capital Intensivo] P/B: 0.5x ── 0.9x (Citigroup, Ford, General Motors, AT&T)
```

Las fluctuaciones cíclicas alejan temporalmente a la empresa de su canal, pero la gravedad fundamental la devuelve a su rango característico a menos que se produzca una ruptura estructural en su ventaja competitiva.

---

### 3. INDIVIDUALIZACIÓN POR EMPRESAS EN ESTADOS UNIDOS

#### 3.1. Casos Perennes a un Patrón (Estructurales)

| Ticker | Empresa | Patrón | Rango P/B (2019-2026) | P/B Medio | Razón del Anclaje Estructural |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **`MSFT`** | Microsoft Corporation | **Perenne Cara** | $6,1\text{x} - 10,4\text{x}$ | $8,5\text{x}$ | Margen neto $>35\%$, liderazgo en Cloud/IA, $ROE > 35\%$. Recompra de acciones mantiene bajo el capital contable. |
| **`AAPL`** | Apple Inc. | **Perenne Cara** | $24,9\text{x} - 52,1\text{x}$ | $36,8\text{x}$ | Retorno de capital masivo vía dividendos y recompras; patrimonio neto reducido que eleva el P/B contable. |
| **`V`** | Visa Inc. | **Perenne Cara** | $14,3\text{x} - 22,0\text{x}$ | $18,4\text{x}$ | Monopolio natural de red transaccional con márgenes operativos $>65\%$ y nulo requerimiento de capital físico. |
| **`NVDA`** | NVIDIA Corporation | **Perenne Cara** | $13,6\text{x} - 28,4\text{x}$ | $20,8\text{x}$ | Cuasi-monopolio en infraestructura acelerada de IA y márgenes brutos $>75\%$. |
| **`C`** | Citigroup Inc. | **Perenne Barata** | $0,41\text{x} - 0,66\text{x}$ | $0,55\text{x}$ | Descuento permanente por menor rentabilidad ($ROE < 8\%$) frente a pares y restricciones regulatorias de la Fed. |
| **`F`** | Ford Motor Co. | **Perenne Barata** | $0,56\text{x} - 0,90\text{x}$ | $0,74\text{x}$ | Negocio intensivo en capital, deuda abultada en división de crédito y pérdidas continuadas en división eléctrica Model e. |
| **`T`** | AT&T Inc. | **Perenne Barata** | $0,68\text{x} - 1,08\text{x}$ | $0,87\text{x}$ | Carga masiva de deuda de fusiones pasadas y exigencia continua de capex en 5G/fibra con bajo retorno marginal. |

---

#### 3.2. Casos Raros y Rupturas de Patrón (Transiciones de Múltiplos)

1. **La Caída Estructural de Intel (`INTC`): De Joya Tecnológica a Múltiplo deprimido**
   - *2019:* Cotizaba a **$P/B = 3,60\text{x}$** como líder hegemónico de procesadores mundiales.
   - *2021-2024:* Pérdida del nodo de fabricación frente a TSMC, retrasos en centros de datos, pérdidas de 7.000M$ en la división Foundry y colapso de márgenes.
   - *2026:* Se desplomó hasta **$P/B = 0,65\text{x}$**, pasando de la cesta *Buena Cara* a *Baja Barata*. El salto extraordinario en precio en 2026 responde a catalizadores exógenos de rescate estatal (CHIPS Act) y planes de escisión de fábricas.
2. **El Colapso de las Grandes Cadenas de Medios: Paramount (`PARA`) y Warner Bros. Discovery (`WBD`)**
   - En 2019-2021 cotizaban a múltiplos saludables ($P/B = 1,8\text{x}-2,1\text{x}$).
   - La disrupción del streaming y la fuga de abonados del cable tradicional forzó a WBD a registrar un **deterioro contable de fondos de comercio de $9.100\text{M}\$$** en 2024, hundiendo su $P/B$ hasta **$0,35\text{x}$**, y a Paramount hasta **$0,45\text{x}$** previo a su dilución forzosa con Skydance.
3. **El Deterioro Patrimonial por Crisis Operativa: Boeing (`BA`)**
   - Tras los incidentes del 737 MAX, huelgas laborales y pérdidas multimillonarias en contratos de defensa, acumuló patrimonio neto negativo, convirtiendo su análisis P/B en anómalo ($P/B > 3,0\text{x}$ aparente por el derrumbe de los fondos propios contables).

---

### 4. EVOLUCIÓN SECTORIAL A TRAVÉS DE LOS REGÍMENES MACRO (2019 - 2026)

| Sector | P/B Medio 2019<br>(Pre-COVID) | P/B Medio 2021<br>(Tipos Cero / Estímulo) | P/B Medio 2022<br>(Shock Inflación Fed 5,25%) | P/B Medio 2024<br>(Normalización) | P/B Medio 2026<br>(Actualidad / Era IA) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Tecnología** | $8,89\text{x}$ | **$16,06\text{x}$** | $9,43\text{x}$ | $12,18\text{x}$ | **$13,55\text{x}$** |
| **Financiero** | $5,90\text{x}$ | **$11,60\text{x}$** | $7,12\text{x}$ | $9,07\text{x}$ | **$10,06\text{x}$** |
| **Consumo Básico** | $7,09\text{x}$ | **$11,05\text{x}$** | $6,03\text{x}$ | $7,08\text{x}$ | **$7,64\text{x}$** |
| **Salud / Farma** | $4,30\text{x}$ | **$7,96\text{x}$** | $4,80\text{x}$ | $6,12\text{x}$ | **$6,79\text{x}$** |
| **Consumo Cíclico** | $4,66\text{x}$ | **$7,27\text{x}$** | $3,89\text{x}$ | $4,67\text{x}$ | **$5,11\text{x}$** |
| **Industriales** | $2,60\text{x}$ | **$3,79\text{x}$** | $2,21\text{x}$ | $2,70\text{x}$ | **$2,95\text{x}$** |
| **Energía** | $2,01\text{x}$ | **$2,74\text{x}$** | $1,54\text{x}$ | $1,46\text{x}$ | **$1,47\text{x}$** |
| **Materiales Básicos** | $1,21\text{x}$ | **$1,38\text{x}$** | $0,86\text{x}$ | $1,03\text{x}$ | **$1,15\text{x}$** |
| **Telecomunicaciones** | $0,85\text{x}$ | **$0,93\text{x}$** | **$0,59\text{x}$** | $0,70\text{x}$ | **$0,77\text{x}$** |

#### Conclusiones de los Regímenes Macro:
1. **La Burbuja de Múltiplos de 2021:** Con tipos de interés al $0\%$ y expansión cuantitativa, el P/B del sector tecnológico se disparó un $+80,6\%$ (de $8,89\text{x}$ a $16,06\text{x}$), extendiendo la prima incluso a cotizadas deficitarias.
2. **El Filtro de Gravedad de 2022:** La subida vertical de los tipos de la Fed hasta el $5,25\%$ contrajo drásticamente las valoraciones relativas en todos los sectores, expulsando el capital de empresas sin flujo de caja libre positivo hacia compañías con balances desapalancados.
3. **La Gran Divergencia de 2024-2026:** Los sectores no han rebotado en bloque. La tecnología y finanzas de pagos han recuperado niveles de prima histórica gracias a la monetización de la IA y altos márgenes de interés, mientras que las telecomunicaciones ($0,77\text{x}$) y energía tradicional ($1,47\text{x}$) permanecen comprimidas bajo descuentos estructurales.
