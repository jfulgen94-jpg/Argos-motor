"""Internal client adapter consuming MOD_07 AI Agents."""
from mod_07_ai_agents.src.agent_router import AgentRouter


class AgentClient:
    def __init__(self):
        self.router = AgentRouter()

    def get_agent(self, task_type: str = "batch_confidential"):
        return self.router.route(task_type)
