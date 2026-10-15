"""
CNMV-U4 — Señal de sustitución/rectificación declarada por la fuente (dominio puro).

Una ficha oficial puede indicar, como motivo de información adicional, la «sustitución del informe financiero anual». Eso es una SEÑAL de posible
republicación, no una republicación confirmada: ``POSSIBLE_REPUBLICATION`` → revisión humana (``NEEDS_REVIEW``). Nunca activa
``REPUBLICATION_CONFIRMED``, nunca reemplaza contenido previo y no presupone que el nº de registro sea la identidad lógica o de versión.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.transport import assert_no_secret

POSSIBLE_REPUBLICATION = "POSSIBLE_REPUBLICATION"
_RE = re.compile(r"sustituci|sustituy|sustituid|rectific|republic|reenvi|nuevo envio")


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def indicates_replacement(text: Optional[str]) -> bool:
    return bool(text) and bool(_RE.search(_norm(text)))


@dataclass(frozen=True)
class ReplacementSignal:
    kind: str                         # siempre POSSIBLE_REPUBLICATION: este módulo no confirma nada
    source: str                       # p. ej. CNMV_IFA_ADDITIONAL_INFO
    registration_number: Optional[str]
    observed_text: str                # texto público de la ficha (acotado), sin URLs ni secretos
    observed_at: str

    def __post_init__(self):
        if self.kind != POSSIBLE_REPUBLICATION:
            raise DomainValidationError("una señal de sustitución solo puede ser POSSIBLE_REPUBLICATION (nunca confirmada)")
        object.__setattr__(self, "observed_text", " ".join(str(self.observed_text).split())[:200])
        assert_no_secret({"t": self.observed_text, "s": self.source, "r": self.registration_number}, "ReplacementSignal")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "source": self.source, "registration_number": self.registration_number,
                "observed_text": self.observed_text, "observed_at": self.observed_at}


def replacement_signal(text: Optional[str], *, source: str, registration_number: Optional[str], observed_at: str
                       ) -> Optional[ReplacementSignal]:
    """``ReplacementSignal`` si el texto oficial indica sustitución/rectificación; si no, ``None``."""
    if not indicates_replacement(text):
        return None
    return ReplacementSignal(POSSIBLE_REPUBLICATION, source, registration_number, str(text), observed_at)
