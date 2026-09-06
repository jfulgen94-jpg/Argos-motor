# ADR 002: Arquitectura Híbrida Ollama Local vs Azure OpenAI

## Estado
Aceptado

## Decisión
Se implementa una arquitectura híbrida desacoplada mediante `AgentRouter`:
- **Ollama local (`stater-audit` / `qwen2.5:14b`)** para desarrollo, tests, procesamiento batch nocturno y confidencialidad estricta.
- **Azure OpenAI (`gpt-4o`)** para producción institucional de alta concurrencia y valoraciones a clientes B2B (financiado con los créditos Microsoft Founders Hub).
