"""
U4 — Comparación ESTRUCTURADA entre el resultado del pipeline unificado y registros de la ruta legacy.

Es solo EVIDENCIA de migración: recibe diccionarios ya producidos (no ejecuta, importa ni modifica ningún código legacy ni
lee su disco). Clave de comparación: (autoridad, emisor, ejercicio, tipo). Campos comparados: sha256 y tamaño.
Estados: MATCH · DIFFERENT (con la lista de campos) · ONLY_NEW · ONLY_LEGACY.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

Key = Tuple[str, str, int, str]


@dataclass(frozen=True)
class ComparisonItem:
    key: Key
    status: str
    differences: Tuple[str, ...] = ()
    new: Optional[Dict[str, Any]] = None
    legacy: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"key": list(self.key), "status": self.status, "differences": list(self.differences),
                "new": self.new, "legacy": self.legacy}


@dataclass
class MigrationComparison:
    items: List[ComparisonItem] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, int]:
        return dict(Counter(i.status for i in self.items))

    @property
    def equivalent(self) -> bool:
        return all(i.status == "MATCH" for i in self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {"summary": self.summary, "equivalent": self.equivalent, "items": [i.to_dict() for i in self.items]}


def _first(rec: Mapping[str, Any], *names: str):
    for n in names:
        if rec.get(n) not in (None, ""):
            return rec[n]
    return None


def normalize_new(candidate, outcome) -> Dict[str, Any]:
    """Fila del resultado unificado a partir del candidato y su ``PipelineResult``."""
    return {"authority": candidate.authority, "issuer": candidate.issuer_id, "fiscal_year": candidate.fiscal_year,
            "doc_type": candidate.doc_type, "sha256": getattr(outcome, "sha256", None), "size_bytes": None,
            "state": getattr(outcome, "state", None)}


def normalize_legacy(rec: Mapping[str, Any]) -> Dict[str, Any]:
    """Fila legacy (formas de ``legacy_bridge``/manifiestos antiguos): acepta sinónimos de campo."""
    return {"authority": str(_first(rec, "authority", "source") or "").upper(),
            "issuer": str(_first(rec, "issuer_id", "issuer_lei", "lei", "ticker") or ""),
            "fiscal_year": int(_first(rec, "fiscal_year", "year") or 0), "doc_type": str(_first(rec, "doc_type") or ""),
            "sha256": (str(_first(rec, "sha256", "sha256_hash") or "").lower() or None),
            "size_bytes": _first(rec, "size_bytes", "file_size_bytes"), "state": _first(rec, "status")}


def _key(row: Mapping[str, Any]) -> Key:
    return (str(row["authority"]).upper(), str(row["issuer"]), int(row["fiscal_year"]), str(row["doc_type"]))


def compare_with_legacy(new_rows: Iterable[Mapping[str, Any]], legacy_records: Iterable[Mapping[str, Any]]) -> MigrationComparison:
    new = {_key(r): dict(r) for r in new_rows}
    old = {_key(r): r for r in (normalize_legacy(x) for x in legacy_records)}
    out = MigrationComparison()
    for k in sorted(set(new) | set(old)):
        n, o = new.get(k), old.get(k)
        if n is None:
            out.items.append(ComparisonItem(k, "ONLY_LEGACY", legacy=o))
        elif o is None:
            out.items.append(ComparisonItem(k, "ONLY_NEW", new=n))
        else:
            diffs = [f for f in ("sha256", "size_bytes")
                     if n.get(f) is not None and o.get(f) is not None and str(n[f]) != str(o[f])]
            out.items.append(ComparisonItem(k, "DIFFERENT" if diffs else "MATCH", tuple(diffs), n, o))
    return out
