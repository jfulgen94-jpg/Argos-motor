# ==============================================================================
# PROMPT ULTRA-OPTIMIZADO PARA GEMINI EN OPENHANDS (MÍNIMO CONSUMO DE TOKENS)
# MISIÓN: VALIDACIÓN, DESCARGA Y AUDITORÍA UNIVERSAL DE FRANCIA (ARGOS MOTOR)
# ==============================================================================

Actúa como Auditor Cuantitativo y de Sistemas de ARGOS MOTOR.
Tu objetivo es auditar y ejecutar la adquisición institucional de empresas francesas siguiendo una arquitectura de mercado estricta, ejecutando código directamente SIN navegar a ciegas para consumir el MÍNIMO de tokens y créditos.

==============================================================================
1. ARQUITECTURA DE MERCADO BASE (EURONEXT PARIS)
==============================================================================
Tu universo de búsqueda y clasificación se divide exactamente en:

A) GRANDES CAPITALIZACIONES (Large Caps - 60 empresas):
   - CAC 40 (40 empresas):
     * 35 empresas con sede en Francia (LVMH, L'Oréal, TotalEnergies, Hermès, Sanofi, BNP Paribas, etc.)
     * 5 holdings internacionales con cotización y ponderación en París:
       - Airbus SE (NL - Supervisor AFM) -> LEI: 2138006MO74EAPV35Y72
       - Stellantis NV (NL - Supervisor AFM) -> LEI: 549300LKT3UKJEW8KW64
       - STMicroelectronics NV (NL - Supervisor AFM) -> LEI: 213800Z8OHIZUDWIPQ83
       - ArcelorMittal SA (LU - Supervisor CSSF) -> LEI: 2138001EP3E3725F5670
       - Eurofins Scientific SE (LU - Supervisor CSSF) -> LEI: 529900JEFHUWR19O3642
   - CAC Next 20 (20 empresas): Air France-KLM, Arkema, BioMérieux, Eiffage, Forvia, Gecina, Getlink, Klépierre, Rémy Cointreau, Rexel, Sartorius Stedim, Sodexo, Soitec, Ubisoft, Valeo, Vivendi, etc.
   * Método de extracción: ESEF ZIP directo (2020-2026) + AMF URD PDF (2012-2019).

B) MEDIANAS CAPITALIZACIONES (Mid & Small Caps - SBF 120 / CAC All-Tradable):
   - CAC Mid 60 (60 empresas que completan el SBF 120): Alten, Amundi, Bic, Elis, Eramet, Fnac Darty, Ipsos, Nexans, Rubis, Scor, Sopra Steria, Spie, TF1, Verallia, Vicat, Virbac...
   - CAC Small (~150 empresas): Pequeñas empresas cotizadas en el mercado regulado.
   * Método de extracción: ESEF ZIP directo (2020-2026) + AMF URD PDF (2012-2019).

C) CRECIMIENTO Y PYMES (Growth & Access - ~450 empresas):
   - Euronext Growth Paris (~280-320 pymes en expansión - MTF):
     * ATENCIÓN: Al no ser mercado regulado estricto de la UE, NO tienen obligación de emitir ESEF ZIP.
     * Presentan su Rapport Financier Annuel en PDF ante la AMF o en su web.
   - Euronext Access Paris (~150 microcaps).
   * Método de extracción: Canal Mixto (188 ya tienen ESEF ZIP en el índice; el resto requiere PDF Crawler AMF).

Total de emisores en París: entre 700 y 850 empresas.

==============================================================================
2. ARCHIVOS CLAVE Y DATOS PRE-INDEXADOS EN EL WORKSPACE (NO BUSQUES EN LA WEB)
==============================================================================
Para evitar consumir tokens buscando en internet, utiliza los archivos que ya están listos:
1. Catálogo Maestro: `ARGOS_MOTOR/config/master_universe_fr.json` (297 empresas ya clasificadas).
2. Entidades XBRL verificadas: `scratch_fr_xbrl_entities.json` (292 LEIs oficiales con URLs y años).
3. Motor de Descarga Oficial: `ARGOS_MOTOR/descarga/fr_france/downloader_amf.py`.
4. Configuración: `ARGOS_MOTOR/descarga/fr_france/config_fr.json`.
5. Destino Canónico de Almacenamiento: `D:/ARGOS_DATA/raw/FR_AMF` (o fallback en `ARGOS_MOTOR/data/raw/FR_AMF`).

==============================================================================
3. PASOS EXACTOS DE EJECUCIÓN (SOLO EJECUTA ESTOS COMANDOS)
==============================================================================

PASO 1: VALIDACIÓN RÁPIDA DEL UNIVERSO (Sin leer archivos gigantes en el contexto)
Ejecuta en terminal:
```bash
python -c "
import json
with open('ARGOS_MOTOR/config/master_universe_fr.json', encoding='utf-8') as f:
    u = json.load(f)
print('Total entidades:', u['summary']['total_entities'])
for k, v in u['summary']['segments_breakdown'].items():
    print(f'  {k}: {v}')
"
```

PASO 2: SIMULACIÓN DE COBERTURA (Dry-Run 2022-2024)
Ejecuta en terminal para verificar cuántos filings están listos para descarga directa sin gastar ancho de banda:
```bash
python -u ARGOS_MOTOR/descarga/fr_france/downloader_amf.py --dry-run --years 2022,2023,2024
```

PASO 3: DESCARGA DE PRUEBA CONTROLADA INSTITUCIONAL (5 Filings de diferentes segmentos)
Ejecuta la descarga de 5 paquetes representativos sellados en disco D con SHA-256:
```bash
python -u ARGOS_MOTOR/descarga/fr_france/downloader_amf.py --years 2023 --max 5
```

PASO 4: VERIFICACIÓN DE SELLADO Y HASHES EN DISCO D
Ejecuta para confirmar que los archivos `.zip` y `.meta.json` están intactos:
```bash
python -c "
import os
from pathlib import Path
base = Path('D:/ARGOS_DATA/raw/FR_AMF/2023')
if not base.exists(): base = Path('ARGOS_MOTOR/data/raw/FR_AMF/2023')
files = list(base.glob('*/*'))
print(f'Archivos en 2023: {len(files)}')
for f in files[:10]:
    print(' ', f.name, f.stat().st_size, 'bytes')
"
```

PASO 5: GENERACIÓN DEL INFORME FINAL DE AUDITORÍA
Crea el archivo `ARGOS_MOTOR/audits/AUDIT_FRANCE_UNIVERSAL.md` resumiendo:
- Desglose exacto del universo (CAC 40, CAC Next 20, SBF 120 Mid 60, Euronext Growth).
- Tratamiento de los 5 holdings en NL/LU.
- Justificación legal de por qué ESEF es 2020-2026 y pre-2020 (2012-2019) es PDF oficial OAM.
- Estado de los archivos descargados y hashes SHA-256.

==============================================================================
REGLAS DE EFICIENCIA PARA EL AGENTE:
- NO leas archivos JSON de más de 50 líneas directamente en tu ventana de contexto; usa scripts Python de 3 líneas.
- NO ejecutes búsquedas web indiscriminadas; la base de LEIs y nombres ya está resuelta.
- Reporta brevemente en markdown tras completar los 5 pasos.
==============================================================================
