"""
STATER MOTOR ARGOS — MOD_01: Branch Threshold & Anti-Lorem Ipsum Validator.
Valida los documentos de cada rama documental según pesos, caracteres mínimos
y rechaza automáticamente cualquier archivo con texto de relleno (Lorem Ipsum, texto simulado).
"""
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from enum import Enum


class DocumentBranch(str, Enum):
    CCAA_AUDITED = "CCAA_AUDITED"
    INFORME_GESTION = "INFORME_GESTION"
    EINF_CSRD = "EINF_CSRD"
    IAGC = "IAGC"
    IARC = "IARC"


# Umbrales mínimos serios por cada rama documental
BRANCH_THRESHOLDS = {
    DocumentBranch.CCAA_AUDITED: {
        "min_chars": 10_000,
        "min_size_bytes": 12_000,
        "required_sections": [
            re.compile(r"balance\s+(?:consolidado|de\s+situaci[oó]n)", re.IGNORECASE),
            re.compile(r"cuenta\s+de\s+(?:p[eé]rdidas\s+y\s+ganancias|resultados)", re.IGNORECASE),
            re.compile(r"estado\s+de\s+flujos\s+de\s+efectivo", re.IGNORECASE),
            re.compile(r"memoria\s+consolidada|notas\s+explicativas", re.IGNORECASE),
            re.compile(r"informe\s+de\s+auditor[ií]a|dictamen\s+de\s+auditor[ií]a", re.IGNORECASE),
        ],
        "min_sections_matched": 4
    },
    DocumentBranch.INFORME_GESTION: {
        "min_chars": 4_000,
        "min_size_bytes": 5_000,
        "required_sections": [
            re.compile(r"evoluci[oó]n\s+de\s+los\s+negocios|situaci[oó]n\s+econ[oó]mica", re.IGNORECASE),
            re.compile(r"principales\s+riesgos\s+e\s+incertidumbres", re.IGNORECASE),
            re.compile(r"riesgo\s+de\s+liquidez|riesgo\s+de\s+cr[eé]dito|riesgo\s+de\s+mercado", re.IGNORECASE),
            re.compile(r"acciones\s+propias|autocartera", re.IGNORECASE),
            re.compile(r"investigaci[oó]n,\s+desarrollo\s+e\s+innovaci[oó]n|i\+d", re.IGNORECASE),
        ],
        "min_sections_matched": 3
    },
    DocumentBranch.EINF_CSRD: {
        "min_chars": 3_500,
        "min_size_bytes": 4_500,
        "required_sections": [
            re.compile(r"informaci[oó]n\s+sobre\s+cuestiones\s+medioambientales", re.IGNORECASE),
            re.compile(r"emisiones\s+de\s+gases\s+de\s+efecto\s+invernadero|scope\s+[123]|alcance\s+[123]", re.IGNORECASE),
            re.compile(r"taxonom[ií]a\s+europea|actividades\s+elegibles|capex|opex|turnover", re.IGNORECASE),
            re.compile(r"cuestiones\s+sociales\s+y\s+relativas\s+al\s+personal|brecha\s+salarial", re.IGNORECASE),
            re.compile(r"derechos\s+humanos|lucha\s+contra\s+la\s+corrupci[oó]n", re.IGNORECASE),
        ],
        "min_sections_matched": 3
    },
    DocumentBranch.IAGC: {
        "min_chars": 3_000,
        "min_size_bytes": 4_000,
        "required_sections": [
            re.compile(r"estructura\s+del\s+accionariado|participaciones\s+significativas", re.IGNORECASE),
            re.compile(r"consejo\s+de\s+administraci[oó]n|consejeros\s+ejecutivos|independientes", re.IGNORECASE),
            re.compile(r"comisi[oó]n\s+de\s+auditor[ií]a|comisi[oó]n\s+de\s+nombramientos", re.IGNORECASE),
            re.compile(r"sistemas\s+de\s+control\s+interno|sciif", re.IGNORECASE),
        ],
        "min_sections_matched": 3
    },
    DocumentBranch.IARC: {
        "min_chars": 2_500,
        "min_size_bytes": 3_500,
        "required_sections": [
            re.compile(r"pol[ií]tica\s+de\s+remuneraciones|remuneraci[oó]n\s+del\s+consejo", re.IGNORECASE),
            re.compile(r"retribuciones\s+devengadas|retribuci[oó]n\s+fija|variable\s+anual", re.IGNORECASE),
            re.compile(r"planes\s+de\s+acciones|sistemas\s+de\s+ahorro", re.IGNORECASE),
        ],
        "min_sections_matched": 2
    }
}

LOREM_IPSUM_PATTERNS = [
    re.compile(r"lorem\s+ipsum", re.IGNORECASE),
    re.compile(r"dolor\s+sit\s+amet", re.IGNORECASE),
    re.compile(r"consectetur\s+adipiscing", re.IGNORECASE),
    re.compile(r"(?:lorem\s+ipsum\s+dolor\s+sit\s+amet[,\s\.]*){3,}", re.IGNORECASE),
    re.compile(r"texto\s+simulado\s+de\s+relleno", re.IGNORECASE),
]


class BranchThresholdValidator:
    """Validador de ramas documentales y detector de texto de relleno."""

    @staticmethod
    def detect_lorem_ipsum(text: str) -> bool:
        """Devuelve True si detecta patrones de Lorem Ipsum o texto de relleno."""
        for pat in LOREM_IPSUM_PATTERNS:
            if pat.search(text):
                return True
        return False

    @classmethod
    def validate_file_branch(cls, file_path: Path, branch: DocumentBranch) -> Dict[str, Any]:
        """
        Valida rigurosamente un archivo frente a los umbrales de su rama documental.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {
                "is_valid": False,
                "reason": "El archivo no existe.",
                "branch": branch.value,
                "quarantine": True
            }

        size_bytes = file_path.stat().st_size
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        char_count = len(content)

        # 1. Rechazo tajante a Lorem Ipsum
        if cls.detect_lorem_ipsum(content):
            return {
                "is_valid": False,
                "reason": "RECHAZADO: Detectado texto de relleno artificial (Lorem Ipsum / Mock).",
                "branch": branch.value,
                "char_count": char_count,
                "file_size_bytes": size_bytes,
                "quarantine": True
            }

        # 2. Umbrales de la rama
        thresholds = BRANCH_THRESHOLDS.get(branch)
        if not thresholds:
            return {"is_valid": True, "branch": branch.value, "quarantine": False}

        reasons = []
        if char_count < thresholds["min_chars"]:
            reasons.append(f"Caracteres insuficientes ({char_count:,} < {thresholds['min_chars']:,} requeridos).")

        if size_bytes < thresholds["min_size_bytes"]:
            reasons.append(f"Tamaño insuficiente ({size_bytes:,} bytes < {thresholds['min_size_bytes']:,} bytes requeridos).")

        # 3. Comprobar secciones requeridas
        matched_sections = 0
        for pat in thresholds["required_sections"]:
            if pat.search(content):
                matched_sections += 1

        if matched_sections < thresholds["min_sections_matched"]:
            reasons.append(f"Secciones obligatorias insuficientes ({matched_sections} < {thresholds['min_sections_matched']} requeridas).")

        is_valid = len(reasons) == 0
        return {
            "is_valid": is_valid,
            "branch": branch.value,
            "char_count": char_count,
            "file_size_bytes": size_bytes,
            "matched_sections": matched_sections,
            "reasons": reasons,
            "quarantine": not is_valid
        }
