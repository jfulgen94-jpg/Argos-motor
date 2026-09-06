# AUDITORÍA TÉCNICA Y ESTADO REAL: MOD_03_NLP_AUDIT
**Módulo:** Auditoría Semántica NLP, Extractor Forense de KAMs/CAMs y Mapeador CSRD/ESRS  
**Ruta en el repositorio:** `ARGOS_MOTOR/mod_03_nlp_audit`  
**Estado:** Implementado con prompts de auditoría estructurados, extractores y detector de greenwashing.

---

## 1. INVENTARIO REAL DE ARCHIVOS CREADOS

```
ARGOS_MOTOR/mod_03_nlp_audit/
├── README.md                      (Documentación metodológica ISA 701, CSRD y Greenwashing)
├── prompts/
│   ├── kam_extraction_prompt.txt  (Prompt de extracción estructurada de KAMs en formato JSON)
│   ├── csrd_scoring_prompt.txt    (Prompt de evaluación y scoring de estándares ESRS)
│   └── greenwash_detect_prompt.txt(Prompt de detección de discrepancias y claims no fundamentados)
├── src/
│   ├── __init__.py                (Exports de KAMExtractor, CSRDMapper, GreenwashingDetector, IAGCExtractor)
│   ├── kam_extractor.py           (Extractor asíncrono de KAMs / CAMs conectado al router de agentes IA)
│   ├── csrd_mapper.py             (Mapeador de divulgaciones de sostenibilidad CSRD / ESRS)
│   ├── greenwashing_detector.py   (Detector determinista y semántico de contradicciones ESG)
│   ├── iagc_extractor.py          (Extractor de métricas de gobierno corporativo del IAGC de CNMV)
│   └── agent_client.py            (Cliente wrapper para conexión con agentes)
└── tests/
    ├── __init__.py
    └── test_nlp_components.py     (Pruebas de IAGCExtractor y GreenwashingDetector)
```

---

## 2. CLASES, MÉTODOS Y PROMPTS IMPLEMENTADOS

### A. `KAMExtractor` (`src/kam_extractor.py`)
- **Propósito:** Identificar y extraer cuestiones clave de auditoría (ISA 701) y Critical Audit Matters (PCAOB AS 3101) a partir de los informes de los auditores independientes.
- **Métodos Implementados:**
  - `extract_from_text(filing_text: str, entity_lei: str, fiscal_year: int, doc_id: str) -> List[Dict[str, Any]]`:
    - Enruta la tarea a `AgentRouter` (modo `batch_confidential` con Ollama o Azure).
    - Aplica `kam_extraction_prompt.txt` sobre los primeros 12.000 caracteres del texto de auditoría.
    - Extrae: firma auditora (`audit_firm`), socio firmante (`signing_partner`), tipo de opinión (`audit_opinion`), empresa en funcionamiento (`has_going_concern`), título de la KAM (`kam_title`), severidad (`LOW/MEDIUM/HIGH/CRITICAL`), descripción del riesgo (`risk_description`), respuesta de auditoría y extracto de texto.

### B. `GreenwashingDetector` (`src/greenwashing_detector.py`)
- **Propósito:** Detectar discrepancias entre declaraciones públicas de sostenibilidad y las tendencias reales de emisiones.
- **Métodos Implementados:**
  - `detect_inconsistencies(claims: list[str], actual_emissions_trend: float) -> dict`:
    - Si la empresa afirma ser *"carbon neutral"* o *"net zero"* pero la tendencia real de emisiones es positiva (`actual_emissions_trend > 0`), emite una alerta `greenwashing_flag = True` con severidad `HIGH`.

### C. `CSRDMapper` (`src/csrd_mapper.py`) y `IAGCExtractor` (`src/iagc_extractor.py`)
- **CSRDMapper:** Mapea textos de sostenibilidad a los 12 estándares europeos ESRS (E1 Cambio Climático, E2 Contaminación, S1 Fuerza Laboral Propia, G1 Conducta Empresarial).
- **IAGCExtractor:** Extrae del informe de gobierno corporativo el % de consejeros independientes y la presencia femenina en el Consejo de Administración.

---

## 3. SUITE DE TESTS IMPLEMENTADOS (`tests/`)
- `test_iagc_extractor`: Valida extracción de % de consejeros independientes y mujeres en el consejo.
- `test_greenwashing_detector`: Comprueba que una promesa de neutralidad con emisiones al alza (+5%) activa la alerta de greenwashing.

---

## 4. ANÁLISIS DE CAPACIDADES Y GAPS
- **Capacidad Real:** Prompts diseñados con formato JSON estricto y tipado de severidad de riesgos.
- **Gap:** Requiere que el motor Ollama (`stater-audit`) o Azure OpenAI esté levantado para ejecutar inferencias en tiempo real; de lo contrario recurre al modo fallback.
