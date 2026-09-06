"""Azure OpenAI Agent — Production-grade inference for B2B precision tasks."""
import os
import openai


class AzureOpenAIAgent:
    """Drop-in replacement for OllamaAgent using Azure OpenAI (GPT-4o)."""

    def __init__(self, deployment: str = "gpt-4o"):
        self.client = openai.AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2024-08-01-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        )
        self.deployment = deployment

    async def extract_kams(self, filing_text: str) -> dict:
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "user", "content": f"Extract KAMs from:\n\n{filing_text}"}],
            response_format={"type": "json_object"},
        )
        return response.model_dump()
