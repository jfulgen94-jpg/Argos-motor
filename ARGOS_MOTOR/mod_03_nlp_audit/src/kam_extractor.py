"""
STATER MOTOR ARGOS — MOD_03: Key Audit Matters (KAM) Extractor.
Extrae y estructura Cuestiones Clave de Auditoría (ISA 701) y Critical Audit Matters (PCAOB AS 3101)
a partir de textos de auditoría utilizando el router de agentes IA (MOD_07).
"""
import json
import uuid
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from mod_07_ai_agents.src.agent_router import AgentRouter

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "kam_extraction_prompt.txt"


class KAMExtractor:
    """Extractor forense de KAMs / CAMs."""

    def __init__(self, agent_router: Optional[AgentRouter] = None):
        self.router = agent_router or AgentRouter()
        self.prompt_template = ""
        if PROMPT_PATH.exists():
            self.prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    async def extract_from_text(self, filing_text: str, entity_lei: str, fiscal_year: int, doc_id: str) -> List[Dict[str, Any]]:
        """
        Ejecuta la extracción sobre un fragmento de texto del informe de auditoría.
        Devuelve una lista de registros listos para insertar en la tabla `audit_kams`.
        """
        agent = self.router.route(task_type="batch_confidential")
        prompt = self.prompt_template.replace("{filing_text}", filing_text[:12000]) if self.prompt_template else filing_text
        
        raw_response = await agent.extract_kams(prompt)
        
        # Parsear respuesta estructurada
        if isinstance(raw_response, dict):
            # Extraer choices si viene en formato OpenAI completion
            if "choices" in raw_response:
                content = raw_response["choices"][0]["message"]["content"]
                parsed_data = json.loads(content)
            else:
                parsed_data = raw_response
        elif isinstance(raw_response, str):
            parsed_data = json.loads(raw_response)
        else:
            parsed_data = {}

        audit_firm = parsed_data.get("audit_firm", "UNKNOWN")
        signing_partner = parsed_data.get("signing_partner")
        audit_opinion = parsed_data.get("audit_opinion", "UNQUALIFIED")
        has_going_concern = parsed_data.get("has_going_concern", False)
        
        results = []
        for kam in parsed_data.get("kams", []):
            results.append({
                "kam_id": str(uuid.uuid4()),
                "entity_lei": entity_lei,
                "fiscal_year": fiscal_year,
                "doc_id": doc_id,
                "audit_firm": audit_firm,
                "signing_partner": signing_partner,
                "audit_opinion": audit_opinion,
                "has_going_concern": has_going_concern,
                "kam_title": kam.get("kam_title", "Sin título"),
                "kam_topic": kam.get("kam_topic", "other"),
                "severity": kam.get("severity", "MEDIUM"),
                "risk_description": kam.get("risk_description"),
                "audit_response": kam.get("audit_response"),
                "text_span": kam.get("text_span", ""),
                "extraction_method": "ollama_qwen14b",
                "confidence_score": 0.95,
                "human_validated": False,
            })
            
        return results
