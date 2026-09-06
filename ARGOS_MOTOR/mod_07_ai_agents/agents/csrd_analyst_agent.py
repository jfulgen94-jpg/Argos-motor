"""Specialized CSRD / ESRS sustainability analyst agent."""
from mod_07_ai_agents.src.agent_router import AgentRouter


class CSRDAnalystAgent:
    def __init__(self):
        self.agent = AgentRouter().route("batch_confidential")

    async def analyze_csrd(self, text: str):
        return await self.agent.extract_kams(text)
