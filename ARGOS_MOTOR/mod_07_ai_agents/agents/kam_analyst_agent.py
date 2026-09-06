"""Specialized ISA 701 / PCAOB KAM forensic analyst agent."""
from mod_07_ai_agents.src.agent_router import AgentRouter


class KAMAnalystAgent:
    def __init__(self):
        self.agent = AgentRouter().route("batch_confidential")

    async def analyze_kam(self, text: str):
        return await self.agent.extract_kams(text)
