"""Agent Router -- Routes tasks to Ollama (local) or Azure OpenAI (production)."""
import os
import httpx


class AgentRouter:
    """Intelligent router: Ollama for batch/confidential, Azure for production/precision."""

    def __init__(self):
        self._env = os.getenv("STATER_ENV", "local")
        self._model = os.getenv("OLLAMA_MODEL", "stater-audit")
        self._base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    @property
    def active_model(self) -> str:
        """Returns the active model identifier."""
        if self._env == "azure":
            return os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        return self._model

    def route(self, task_type: str = "batch_confidential"):
        if self._env == "local" or task_type == "batch_confidential":
            from .ollama_agent import OllamaAgent
            return OllamaAgent(model=self._model)
        elif self._env == "azure" or task_type == "high_precision":
            from .azure_openai_agent import AzureOpenAIAgent
            return AzureOpenAIAgent()
        else:
            raise ValueError(f"Unknown STATER_ENV: {self._env}")

    def run(self, prompt: str, task_type: str = "batch_confidential", timeout: float = 120.0) -> str:
        """
        Synchronous convenience wrapper.
        Routes to Ollama locally or Azure OpenAI in production.
        Returns the model text response.
        """
        if self._env == "azure":
            from .azure_openai_agent import AzureOpenAIAgent
            agent = AzureOpenAIAgent()
            return agent.run_sync(prompt)

        # Default: Ollama local via REST (synchronous httpx)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
