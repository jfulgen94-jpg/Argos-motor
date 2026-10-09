"""Azure OpenAI Agent — Production-grade inference for B2B precision tasks."""
import os
import json
from pathlib import Path
import openai


class AzureOpenAIAgent:
    """Drop-in replacement for OllamaAgent using Azure OpenAI."""

    def __init__(self, deployment: str = None):
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        key = os.getenv("AZURE_OPENAI_KEY")
        dep = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT")

        if not endpoint or not key:
            secrets_path = Path(__file__).resolve().parents[2] / "config" / "azure_secrets.json"
            if secrets_path.exists():
                try:
                    sec = json.loads(secrets_path.read_text(encoding="utf-8"))
                    endpoint = endpoint or sec.get("openai_endpoint")
                    key = key or sec.get("openai_key")
                    dep = dep or sec.get("openai_deployment", "gpt-4.1-mini")
                except Exception:
                    pass

        self.deployment = dep or "gpt-4.1-mini"
        self.client = openai.AzureOpenAI(
            api_key=key,
            api_version="2024-08-01-preview",
            azure_endpoint=endpoint,
        )

    async def extract_kams(self, prompt: str) -> dict:
        return self.extract_kams_sync(prompt)

    def extract_kams_sync(self, prompt: str) -> dict:
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        content = response.choices[0].message.content
        return json.loads(content)

