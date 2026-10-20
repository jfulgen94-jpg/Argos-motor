"""
U4 — Proveedor de enlaces por REPLAY (fixture JSON): descubrimiento determinista, sin red y sin escritura.

Cumple el contrato ``LinkProvider`` de los adapters (``Callable[[DiscoveryRequest], Iterable[Dict]]``). El fixture es una lista
de registros o ``{"records": [...]}``. Se devuelven copias, en el orden del fixture; el router fija el orden final.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Union

from mod_01_ingestion.src.unified.models import DiscoveryRequest


class ReplayFixtureError(ValueError):
    pass


class ReplayLinkProvider:
    def __init__(self, source: Union[str, Path, List[Dict[str, Any]]]):
        if isinstance(source, (str, Path)):
            try:
                data = json.loads(Path(source).read_text(encoding="utf-8"))
            except (OSError, ValueError) as ex:
                raise ReplayFixtureError(f"fixture de replay ilegible: {type(ex).__name__}") from ex
        else:
            data = source
        if isinstance(data, dict):
            data = data.get("records")
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ReplayFixtureError("el fixture debe ser una lista de registros (o {'records': [...]})")
        self._records = copy.deepcopy(data)

    def __call__(self, request: DiscoveryRequest) -> Iterable[Dict[str, Any]]:
        return copy.deepcopy(self._records)
