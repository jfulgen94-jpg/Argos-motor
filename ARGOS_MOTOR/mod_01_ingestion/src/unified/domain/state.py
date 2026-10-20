"""Validación de transiciones de estado (tabla en ``enums.ALLOWED_TRANSITIONS``)."""
from __future__ import annotations

from mod_01_ingestion.src.unified.domain.enums import ALLOWED_TRANSITIONS, PipelineStatus
from mod_01_ingestion.src.unified.domain.errors import InvalidStateTransitionError


def is_allowed_transition(src: PipelineStatus, dst: PipelineStatus) -> bool:
    return PipelineStatus(dst) in ALLOWED_TRANSITIONS[PipelineStatus(src)]


def assert_transition(src: PipelineStatus, dst: PipelineStatus) -> None:
    if not is_allowed_transition(src, dst):
        raise InvalidStateTransitionError(
            f"transición no permitida: {PipelineStatus(src).value} -> {PipelineStatus(dst).value}")
