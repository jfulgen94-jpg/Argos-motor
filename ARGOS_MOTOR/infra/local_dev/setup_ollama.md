# Configuración del Entorno Local Ollama

1. Instalar Ollama en Windows:
   `winget install Ollama.Ollama`
2. Descargar modelo base:
   `ollama pull qwen2.5:14b`
3. Crear el modelo forense de STATER:
   `ollama create stater-audit -f ./mod_07_ai_agents/modelfiles/Modelfile.stater-audit`
4. Probar:
   `ollama run stater-audit "Test prompt"`
