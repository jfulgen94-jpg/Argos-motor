# AUDITORÍA TÉCNICA Y ESTADO REAL: MOD_07_AI_AGENTS
**Módulo:** Enrutador de Agentes IA y Análisis Forense (Ollama Local / Azure OpenAI)  
**Ruta en el repositorio:** `ARGOS_MOTOR/mod_07_ai_agents`  
**Estado:** Implementado con enrutador dual inteligente, agente Ollama local y cliente Azure OpenAI.

---

## 1. INVENTARIO REAL DE ARCHIVOS CREADOS

```
ARGOS_MOTOR/mod_07_ai_agents/
├── README.md                      (Guía de configuración de modelos locales y despliegue Azure)
├── src/
│   ├── __init__.py                (Exports de AgentRouter, OllamaAgent, AzureOpenAIAgent)
│   ├── agent_router.py            (Router dinámico entre Ollama y Azure OpenAI según entorno y privacidad)
│   ├── ollama_agent.py            (Cliente asíncrono para servidor Ollama local con Qwen 14B / stater-audit)
│   └── azure_openai_agent.py      (Cliente Azure OpenAI para producción con GPT-4o)
└── tests/
    ├── __init__.py
    └── test_agent_router.py       (Pruebas de enrutamiento por entorno y método síncrono run())
```

---

## 2. CLASES, MÉTODOS Y ENRUTAMIENTO IMPLEMENTADO

### A. `AgentRouter` (`src/agent_router.py`)
- **Propósito:** Decidir qué motor de IA debe procesar cada solicitud de análisis forense según criterios de privacidad y precisión.
- **Estrategia de Enrutamiento:**
  - Si `STATER_ENV="local"` o `task_type="batch_confidential"` → **OllamaAgent** (100% privado en local, sin salida a internet).
  - Si `STATER_ENV="azure"` o `task_type="high_precision"` → **AzureOpenAIAgent** (GPT-4o corporativo con SLA institucional).
- **Métodos Implementados:**
  - `active_model -> str`: Retorna el identificador del modelo activo (`stater-audit`, `qwen2.5:14b` o `gpt-4o`).
  - `route(task_type: str)`: Retorna la instancia de agente correspondiente.
  - `run(prompt: str, task_type: str = "batch_confidential", timeout: float = 120.0) -> str`: Wrapper síncrono para ejecutar prompts y obtener la respuesta de texto.

### B. `OllamaAgent` (`src/ollama_agent.py`)
- **Propósito:** Inferencia local sin costes por token ni exposición de datos confidenciales.
- **Métodos Implementados:**
  - `extract_kams(prompt: str) -> dict`: Llama a `POST /api/generate` de Ollama con `temperature: 0.1` y `format: json`.
  - `score_csrd(prompt: str) -> dict`: Evalúa métricas de sostenibilidad en formato JSON.

### C. `AzureOpenAIAgent` (`src/azure_openai_agent.py`)
- **Propósito:** Procesamiento de alta precisión en la nube para clientes Enterprise.
- **Métodos Implementados:**
  - Utiliza `AsyncAzureOpenAI` con credenciales de `AZURE_OPENAI_ENDPOINT` y `AZURE_OPENAI_API_KEY`.

---

## 3. SUITE DE TESTS IMPLEMENTADOS (`tests/`)
- `test_agent_router_defaults_to_ollama_in_local`: Comprueba que en entorno local use Ollama.
- `test_agent_router_active_model_local`: Verifica nombre del modelo local (`stater-audit`).
- `test_agent_router_active_model_azure`: Verifica nombre del modelo Azure (`gpt-4o`).
- `test_agent_router_has_run_method`: Valida la existencia del método síncrono `run()`.

---

## 4. ANÁLISIS DE CAPACIDADES Y GAPS
- **Capacidad Real:** Arquitectura híbrida que protege la confidencialidad de los datos de clientes institucionales.
- **Gap:** Requiere tener el demonio de Ollama ejecutándose en `http://localhost:11434` o las claves de Azure configuradas en variables de entorno para responder fuera del modo mock.
