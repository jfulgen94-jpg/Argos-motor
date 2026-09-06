# MOD_03 — Motor NLP de Auditoría, CSRD y Gobernanza

## Propósito
Extrae texto estructurado de informes de auditoría (KAMs ISA 701 / CAMs PCAOB AS 3101), divulgaciones de sostenibilidad CSRD/ESRS y secciones de gobierno corporativo (IAGC).

## Agente de IA
Este módulo consume MOD_07 (AI Agents). En Fase 0 usa `ollama/stater-audit` (local). En Fase 1+ usa `Azure OpenAI GPT-4o`.

## Inputs
- Textos extraídos de filings (MOD_02)
- Prompts en `prompts/`

## Outputs
- Tabla `audit_kams` (KAMs/CAMs con severidad LOW/MEDIUM/HIGH/CRITICAL)
- Tabla `esg_kpis` (métricas CSRD/ESRS E1-G1 y S-Score v2.0)

## Ejecución
```bash
python src/kam_extractor.py --entity_lei 2138003EK6LKVJK FASS
python src/csrd_mapper.py --entity_lei 2138003EK6LKVJK
```
