# MOD_07 — Motor de Agentes de IA (Ollama + Azure OpenAI)

## Propósito
Proporciona capacidad de razonamiento financiero y jurídico avanzado al motor. Actúa como servicio interno consumido por MOD_03.

## Arquitectura del Router
```
STATER_ENV=local   → OllamaAgent  (qwen2.5:14b, sin coste, confidencial)
STATER_ENV=azure   → AzureOpenAI (GPT-4o, créditos Founders Hub)
Tarea batch/noche  → Siempre Ollama (ahorro de créditos)
Alta precisión B2B → Azure OpenAI (calidad máxima para clientes)
```

## Instalación de Ollama (Semana 2)
```powershell
winget install Ollama.Ollama
ollama pull qwen2.5:14b
ollama create stater-audit -f modelfiles/Modelfile.stater-audit
ollama run stater-audit "Test: extract KAMs"
```

## Costes Azure OpenAI (con créditos Microsoft Founders Hub)
- GPT-4o: ~0.005 $/1K tokens
- Un 10-K típico: ~15.000 tokens
- Los 2.500$ de créditos cubren ~33.000 informes completos
