"""Ollama Agent — Local LLM inference via Ollama REST API."""
import httpx
import os


class OllamaAgent:
    def __init__(self, model: str = "stater-audit"):
        self.model = model
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def extract_kams(self, filing_text: str) -> dict:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": f"Extract KAMs from:\n\n{filing_text}"}],
                    "response_format": {"type": "json_object"},
                },
            )
        return response.json()
