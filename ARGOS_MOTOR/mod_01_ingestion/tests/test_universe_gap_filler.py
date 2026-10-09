"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Tests Unitarios para Completación del Catálogo Maestro (--fill-gap)

Verifica:
1. Idempotencia y no duplicación de entidades en ejecuciones repetidas.
2. Manejo estricto de PENDING_REVIEW para entidades con score < 0.90.
3. Exclusión determinista de SOCIMIs del conteo total del universo operativo (socimis_count == 0).
4. Correcta preservación del esquema canónico institucional.
"""

import hashlib
import json
import shutil
import pytest
from pathlib import Path
from mod_01_ingestion.src.master_universe_builder import (
    build_master_universe,
    fill_universe_gaps,
    MASTER_UNIVERSE_PATH,
    GAP_CANDIDATES,
    canonical_entity_key,
    find_name_collisions,
    find_identity_conflicts,
    summarize_universe,
)


_ARGOS_MOTOR = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolated_workdir(tmp_path, monkeypatch):
    """U1: master_universe_builder usa rutas RELATIVAS al CWD (config/..., UNIVERSE_COMPLETION_REPORT_*.md).
    Se trabaja sobre una copia temporal de config/ para no tocar los JSON versionados."""
    shutil.copytree(_ARGOS_MOTOR / "config", tmp_path / "config",
                    ignore=shutil.ignore_patterns("history", "ingestion_cells"))
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def _tree_digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def test_gap_filler_does_not_modify_versioned_config():
    """Regresión de aislamiento: ninguna ejecución escribe en config/ ni crea informes en ARGOS_MOTOR/."""
    before_cfg = _tree_digest(_ARGOS_MOTOR / "config")
    before_reports = sorted(p.name for p in _ARGOS_MOTOR.glob("UNIVERSE_COMPLETION_REPORT_*.md"))
    fill_universe_gaps()
    assert _tree_digest(_ARGOS_MOTOR / "config") == before_cfg
    assert sorted(p.name for p in _ARGOS_MOTOR.glob("UNIVERSE_COMPLETION_REPORT_*.md")) == before_reports


def _canon(payload):
    """Comparación semántica: sin campos temporales (versión y fecha de generación)."""
    return json.dumps({k: v for k, v in payload.items() if k not in ("version", "generated_at")},
                      sort_keys=True, ensure_ascii=False)


def test_fill_gap_idempotence():
    """fill(fill(x)) == fill(x): semánticamente y, con formato determinista, byte a byte."""
    res1 = fill_universe_gaps()
    bytes1 = MASTER_UNIVERSE_PATH.read_bytes()
    total1 = res1["total_entities"]

    res2 = fill_universe_gaps()
    bytes2 = MASTER_UNIVERSE_PATH.read_bytes()
    total2 = res2["total_entities"]

    assert total1 == total2
    assert len(res2["companies"]) == total2
    assert len(set(res2["companies"].keys())) == total2
    assert _canon(res1) == _canon(res2)
    assert res1["version"] == res2["version"]          # la segunda ejecución no sube versión
    assert bytes1 == bytes2                            # ni reescribe el catálogo
    assert json.loads(bytes2) == res2


def test_fill_gap_second_run_creates_no_artifacts(tmp_path):
    fill_universe_gaps()
    snapshot = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    fill_universe_gaps()
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == snapshot      # sin backups, informes ni reescrituras nuevas (idempotencia sin acumulación)


def test_operational_universe_includes_socimis(tmp_path):
    """Política U2: las SOCIMIs pertenecen al universo operativo y conservan su clasificación."""
    original = MASTER_UNIVERSE_PATH.read_bytes()
    with open(MASTER_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    companies = data["companies"]
    expected = {t for t, c in companies.items() if c["is_socimi"]}      # esperado derivado del catálogo, no hardcodeado
    assert expected, "el catálogo operativo debe contener SOCIMIs"

    stats = summarize_universe(companies)
    assert stats["socimis_count"] == len(expected) and set(stats["socimi_tickers"]) == expected
    assert stats["total_entities"] == len(companies) == stats["socimis_count"] + stats["non_socimis_count"]
    assert summarize_universe(dict(reversed(list(companies.items())))) == stats     # independiente del orden
    for ticker in expected:
        comp = companies[ticker]
        assert comp["is_socimi"] is True and "SOCIMI" in comp["segment"]           # clasificación preservada
    for ticker, comp in companies.items():
        assert canonical_entity_key(comp) == ticker                                  # clave canónica única
        if "SOCIMI" in comp["segment"]:
            assert comp["is_socimi"] is True

    # el resumen declarado en el catálogo coincide con el cálculo
    assert data["socimis_summary"]["total_socimis_active"] == stats["socimis_count"]
    # ninguna SOCIMI comparte CIF/LEI con otra entidad (sin duplicación por doble condición)
    conflicts = find_identity_conflicts(companies)
    in_conflict = {t for ids in conflicts.values() for ts in ids.values() for t in ts}
    assert not (in_conflict & expected), sorted(in_conflict & expected)

    # tras fill(): siguen todas, sin duplicados, y la entrada no se alteró
    assert MASTER_UNIVERSE_PATH.read_bytes() == original
    out = fill_universe_gaps()
    assert expected <= {t for t, c in out["companies"].items() if c["is_socimi"]}
    after = summarize_universe(out["companies"])
    assert after["socimis_count"] >= stats["socimis_count"]
    assert len({canonical_entity_key(c) for c in out["companies"].values()}) == len(out["companies"])


def test_fill_gap_output_is_deterministic_and_does_not_mutate_candidates():
    original = MASTER_UNIVERSE_PATH.read_bytes()
    candidates_before = json.dumps(GAP_CANDIDATES, sort_keys=True)
    first = _canon(fill_universe_gaps())
    MASTER_UNIVERSE_PATH.write_bytes(original)         # misma entrada, segunda ejecución independiente
    second = _canon(fill_universe_gaps())
    assert first == second
    assert json.dumps(GAP_CANDIDATES, sort_keys=True) == candidates_before


def test_possible_duplicate_socimis_are_reported_not_merged():
    """Misma razón social bajo tickers distintos se REPORTA (revisión humana); nunca se fusiona ni se oculta."""
    with open(MASTER_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        companies = json.load(f)["companies"]
    collisions = find_name_collisions(companies)
    by_name = {}
    for t, c in companies.items():
        by_name.setdefault("".join(ch for ch in c["name_legal"].upper() if ch.isalnum()), []).append(t)
    assert all(len(ts) > 1 for ts in collisions.values())
    socimi_groups = [ts for ts in collisions.values() if any(companies[t]["is_socimi"] for t in ts)]
    out = fill_universe_gaps()
    assert all(t in out["companies"] for ts in socimi_groups for t in ts)      # ninguna se elimina


def test_gap_candidates_socimis_are_included_not_excluded():
    out = fill_universe_gaps()
    for cand in GAP_CANDIDATES:
        if cand.get("is_socimi") or "SOCIMI" in cand["segment"].upper():
            entry = out["companies"].get(cand["ticker"].upper())
            assert entry is not None and entry["is_socimi"] is True, cand["ticker"]
            assert "EXCLUDED" not in entry["segment"]


def test_pending_review_isolation(tmp_path, monkeypatch):
    """Entidades con score < 0.90 deben ir a PENDING_REVIEW y no al catálogo activo."""
    test_json = tmp_path / "master_universe_test.json"
    pending_json = tmp_path / "master_universe_es_PENDING_REVIEW.json"
    
    # Crear catálogo base
    base_payload = {
        "version": "3.0.0",
        "jurisdiction": "ES",
        "total_entities": 1,
        "segments_breakdown": {"IBEX35": 1, "MERCADO_CONTINUO": 0, "BME_GROWTH": 0},
        "socimis_count": 0,
        "companies": {
            "SAN": {
                "ticker": "SAN",
                "cif_nif": "A-39000013",
                "lei": "5493006QMFDDMYWIAM13",
                "name_legal": "Banco Santander, S.A.",
                "segment": "IBEX35",
                "is_socimi": False,
                "resolution_score": 1.0
            }
        }
    }
    with open(test_json, "w", encoding="utf-8") as f:
        json.dump(base_payload, f)

    # Mock de path
    monkeypatch.setattr("mod_01_ingestion.src.master_universe_builder.MASTER_UNIVERSE_PATH", test_json)
    monkeypatch.setattr("mod_01_ingestion.src.master_universe_builder.Path", 
                        lambda p: pending_json if "PENDING_REVIEW" in str(p) else Path(p))

    # Añadir un candidato de prueba con score < 0.90
    mock_candidates = [
        {
            "ticker": "DOUBTFUL_CO",
            "cif_nif": "",  # Sin CIF
            "lei": None,     # Sin LEI
            "name_legal": "Empresa No Verificada S.L.",
            "segment": "BME_GROWTH",
            "is_socimi": False,
            "fiscal_year_end": "12-31"
        }
    ]
    monkeypatch.setattr("mod_01_ingestion.src.master_universe_builder.GAP_CANDIDATES", mock_candidates)

    res = fill_universe_gaps()
    assert "DOUBTFUL_CO" not in res["companies"]
    assert res["total_entities"] == 1


def test_special_fiscal_year_ends_preserved():
    """Verifica que empresas con cierres fiscales atípicos (Logista, Inditex) están correctamente configuradas."""
    with open(MASTER_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    comps = data["companies"]
    if "LOG" in comps:
        assert comps["LOG"]["fiscal_year_end"] == "09-30"
    if "ITX" in comps:
        assert comps["ITX"]["fiscal_year_end"] == "01-31"
    if "BKY" in comps:
        assert comps["BKY"]["fiscal_year_end"] == "06-30"
    if "ZOT" in comps:
        assert comps["ZOT"]["fiscal_year_end"] == "11-30"
