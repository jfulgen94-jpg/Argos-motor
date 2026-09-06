"""Unit tests for MOD_07 Agent Router."""
import os
import pytest
from mod_07_ai_agents.src.agent_router import AgentRouter
from mod_07_ai_agents.src.ollama_agent import OllamaAgent


def test_agent_router_defaults_to_ollama_in_local():
    os.environ["STATER_ENV"] = "local"
    router = AgentRouter()
    agent = router.route("batch_confidential")
    assert isinstance(agent, OllamaAgent)
    assert agent.model == "stater-audit"


def test_agent_router_active_model_local():
    """active_model returns the OLLAMA_MODEL env or default 'stater-audit'."""
    os.environ["STATER_ENV"] = "local"
    os.environ.pop("OLLAMA_MODEL", None)
    router = AgentRouter()
    assert router.active_model == "stater-audit"


def test_agent_router_active_model_azure():
    """In Azure mode, active_model returns the deployment name."""
    os.environ["STATER_ENV"] = "azure"
    os.environ["AZURE_OPENAI_DEPLOYMENT"] = "gpt-4o-stater"
    router = AgentRouter()
    assert router.active_model == "gpt-4o-stater"
    # Cleanup
    os.environ["STATER_ENV"] = "local"


def test_agent_router_has_run_method():
    """AgentRouter must expose a synchronous .run() method."""
    router = AgentRouter()
    assert hasattr(router, "run"), "AgentRouter must have a .run() synchronous method"
    assert callable(router.run)
