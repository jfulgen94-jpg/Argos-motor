"""
U2 — Barrera de persistencia, bloqueo de cnmv_engine_v5 y contrato canónico de adapters.
Offline: sin red; todo bajo ``tmp_path``. Los tests de SOCIMIs/idempotencia están en test_universe_gap_filler.py.
"""
import ast
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

from mod_01_ingestion.src.unified import persistence_guard
from mod_01_ingestion.src.unified.adapters.bafin import BaFinAdapter, EqsVerifiedLinksProvider
from mod_01_ingestion.src.unified.adapters.cnmv import CNMVAdapter
from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.domain import protocols
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode, SourceType
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, SimulatedDataRejectedError
from mod_01_ingestion.src.unified.domain.models import CatalogRecord, ManifestRecord
from mod_01_ingestion.src.unified.domain.policy import (
    assert_candidate_allowed, is_host_allowed, validate_allowed_domains)
from mod_01_ingestion.src.unified.lock_manager import LockManager
from mod_01_ingestion.src.unified.models import DiscoveryRequest
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository
from mod_01_ingestion.src.unified import source_adapter as v1_module

ARGOS_MOTOR = Path(__file__).resolve().parents[2]
UNIFIED = ARGOS_MOTOR / "mod_01_ingestion" / "src" / "unified"
V5 = ARGOS_MOTOR / "descarga" / "es_spain" / "cnmv_engine_v5.py"
GOOD_SHA = "cd" * 32


def manifest(**over):
    kw = dict(manifest_version="1.0.0", document_id="CNMV_L1_2023_ESEF", run_id="r1", job_id="j1", authority="CNMV",
              country_code="ES", issuer_id="L1", fiscal_year=2023, doc_type="ESEF_PACKAGE",
              source_url="https://example.test/a.zip", final_url=None, raw_path="raw/a.zip", cas_path="cas/x",
              sha256=GOOD_SHA, size_bytes=1, mime_type=None, http_status=200, status="RAW_VALIDATED",
              completeness_status="OK")
    kw.update(over)
    return ManifestRecord(**kw)


def tree(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.exists() else []


# =============================================================== PERSISTENCIA (7-14)
@pytest.mark.parametrize("mode", [ExecutionMode.LIVE, ExecutionMode.PILOT])
def test_manifest_stage_rejects_simulated_before_creating_files(tmp_path, mode):
    repo = ManifestRepository(DataLayout(tmp_path / "root"), mode=mode)
    for rec in (manifest(doc_type="SIMULATED"), manifest(status="SIMULATED")):
        with pytest.raises(SimulatedDataRejectedError):
            repo.stage(rec)
    assert tree(tmp_path) == []                       # ni directorios ni .pending


@pytest.mark.parametrize("mode", [ExecutionMode.LIVE, ExecutionMode.PILOT, ExecutionMode.TEST, ExecutionMode.SANDBOX])
def test_manifest_stage_rejects_placeholder_hash_in_every_mode(tmp_path, mode):
    repo = ManifestRepository(DataLayout(tmp_path / "root"), mode=mode)
    rec = manifest()
    rec.sha256 = "placeholder"                         # mutación posterior a la construcción
    rec.status = "CACHE_HIT"
    with pytest.raises(SimulatedDataRejectedError):
        repo.stage(rec)
    rec.sha256 = ""
    with pytest.raises(SimulatedDataRejectedError):
        repo.stage(rec)
    assert tree(tmp_path) == []


def test_flags_fake_and_synthetic_rejected_at_persistence(tmp_path):
    repo = ManifestRepository(DataLayout(tmp_path / "root"), mode=ExecutionMode.LIVE)
    pending_dir = tmp_path / "root" / "manifests" / "CNMV" / "2023"
    pending_dir.mkdir(parents=True)
    forged = pending_dir / "CNMV_L1_2023_ESEF.json.pending"
    forged.write_text(json.dumps({**manifest().to_dict(), "synthetic": True, "extra": {"synthetic": True}}))
    with pytest.raises(SimulatedDataRejectedError):    # commit revalida un .pending forjado
        repo.commit(forged)
    assert forged.exists() and not forged.with_name("CNMV_L1_2023_ESEF.json").exists()


def test_catalog_upsert_rejects_before_touching_duckdb(tmp_path):
    cat = CatalogRepository(tmp_path / "cat" / "c.duckdb", mode=ExecutionMode.LIVE)
    before = (cat.db_path.stat().st_size, cat.count())
    rec = CatalogRecord(document_id="d", run_id="r", job_id="j", authority="CNMV", country_code="ES", issuer_id="L1",
                        fiscal_year=2023, doc_type="SIMULATED", sha256=GOOD_SHA, raw_path="x", manifest_path="y",
                        status="RAW_VALIDATED", size_bytes=1)
    with pytest.raises(SimulatedDataRejectedError):
        cat.upsert(rec)
    rec.doc_type, rec.sha256 = "ESEF_PACKAGE", "placeholder"
    with pytest.raises(SimulatedDataRejectedError):
        cat.upsert(rec)
    assert (cat.db_path.stat().st_size, cat.count()) == before == (before[0], 0)


def test_cas_promote_rejects_invalid_hash_before_filesystem(tmp_path):
    layout = DataLayout(tmp_path / "root")
    cas = ContentAddressedRawStore(layout, LockManager(layout.locks))
    staged = tmp_path / "x.bin"
    staged.write_bytes(b"data")
    before = tree(tmp_path / "root")                    # el constructor de LockManager ya creó locks/
    for bad in ("placeholder", "", "abc"):
        with pytest.raises(DomainValidationError):
            cas.promote(staged, bad, Path("ES_CNMV/2023/x.bin"))
    assert tree(tmp_path / "root") == before            # promote no tocó el filesystem


def test_sandbox_allows_simulated_fixture_only_under_authorized_temp_root(tmp_path, monkeypatch):
    rec = manifest(doc_type="SIMULATED")
    for mode in (ExecutionMode.TEST, ExecutionMode.SANDBOX):
        repo = ManifestRepository(DataLayout(tmp_path / mode.value), mode=mode)
        pending = repo.stage(rec)                      # tmp_path está bajo el directorio temporal del sistema
        assert pending.exists()
    for op in ("D:/ARGOS_DATA/raw/ES_CNMV", str(ARGOS_MOTOR / "data" / "raw"), str(ARGOS_MOTOR / "data")):
        with pytest.raises(SimulatedDataRejectedError):
            persistence_guard.assert_persistable(rec, ExecutionMode.SANDBOX, Path(op))
    # un root configurado como operativo (ARGOS_DATA_ROOT) tampoco, aunque esté bajo el temporal
    op_root = tmp_path / "configured_operational"
    monkeypatch.setenv("ARGOS_DATA_ROOT", str(op_root))
    with pytest.raises(SimulatedDataRejectedError):
        persistence_guard.assert_persistable(rec, ExecutionMode.TEST, op_root / "raw")
    # el CWD no es criterio de seguridad
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SimulatedDataRejectedError):
        persistence_guard.assert_persistable(rec, ExecutionMode.TEST, Path("D:/ARGOS_DATA/raw"))


def test_caller_omitting_mode_cannot_lower_security(tmp_path):
    with pytest.warns(DeprecationWarning, match="LIVE"):
        mrepo = ManifestRepository(DataLayout(tmp_path / "root"))
    with pytest.warns(DeprecationWarning, match="LIVE"):
        crepo = CatalogRepository(tmp_path / "c.duckdb")
    assert mrepo.mode is ExecutionMode.LIVE and crepo.mode is ExecutionMode.LIVE
    with pytest.raises(SimulatedDataRejectedError):
        mrepo.stage(manifest(doc_type="SIMULATED"))
    with pytest.raises(Exception):
        ManifestRepository(DataLayout(tmp_path / "r2"), mode="STAGING")     # modos desconocidos no se toleran


def test_valid_manifest_still_passes_and_schema_is_unchanged(tmp_path):
    repo = ManifestRepository(DataLayout(tmp_path / "root"), mode=ExecutionMode.LIVE)
    rec = manifest()
    final = repo.commit(repo.stage(rec))
    data = json.loads(final.read_text(encoding="utf-8"))
    assert set(data) == set(ManifestRecord.__dataclass_fields__)           # sin campos nuevos
    assert data["sha256"] == GOOD_SHA and repo.get("CNMV", 2023, rec.document_id) == data


# =============================================================== CNMV v5 (15-19)
def _run_v5(args, cwd, extra_env=None):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ARGOS_MOTOR), **(extra_env or {})}
    return subprocess.run([sys.executable, str(V5), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=60)


def test_v5_import_has_no_side_effects(tmp_path):
    code = (
        "import importlib.util, os, socket, sys\n"
        "def deny(*a, **k): raise RuntimeError('network blocked')\n"
        "socket.socket.connect = deny; socket.create_connection = deny; socket.getaddrinfo = deny\n"
        "before = sorted(os.listdir('.'))\n"
        f"spec = importlib.util.spec_from_file_location('cnmv_engine_v5', r'{V5}')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "assert sorted(os.listdir('.')) == before\n"
        "assert m.DEPRECATED_TEST_ONLY is True\n"
        "print('OK')\n")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ARGOS_MOTOR)}
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
    assert list(tmp_path.iterdir()) == []


def test_v5_default_execution_is_blocked_before_any_write(tmp_path):
    r = _run_v5(["--years", "2024"], tmp_path)
    assert r.returncode == 2 and "BLOQUEADO" in r.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode", ["LIVE", "PILOT", "live", "pilot", "PRODUCTION", ""])
def test_v5_live_and_pilot_always_blocked(tmp_path, mode):
    out = tmp_path / "out"
    r = _run_v5(["--years", "2024", "--mode", mode, "--allow-simulated", "--output-root", str(out)], tmp_path)
    assert r.returncode == 2
    assert not out.exists()


def test_v5_cannot_write_to_operational_raw_or_use_cwd(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("cnmv_engine_v5_under_test", V5)
    v5 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v5)
    ok = v5.assert_run_allowed("TEST", True, tmp_path / "sandbox")
    assert ok == tmp_path / "sandbox"
    for bad in ("D:/ARGOS_DATA/raw/ES_CNMV", str(ARGOS_MOTOR / "data" / "raw" / "ES_CNMV"),
                str(ARGOS_MOTOR / "data"), "."):
        with pytest.raises(v5.SimulationBlocked):
            v5.assert_run_allowed("SANDBOX", True, bad)
    with pytest.raises(v5.SimulationBlocked):
        v5.assert_run_allowed("TEST", False, tmp_path)               # sin --allow-simulated
    with pytest.raises(v5.SimulationBlocked):
        v5.assert_run_allowed("TEST", True, None)                    # sin output-root explícito
    guarded = ARGOS_MOTOR / "data" / "raw" / "ES_CNMV_U2_PROBE"
    with pytest.raises(v5.SimulationBlocked):
        v5.CNMVEngineV5({"mode": "TEST", "allow_simulated": True, "master_universe_path": "x"}, guarded)
    assert not guarded.exists()                                        # la compuerta actúa antes de mkdir
    monkeypatch.setenv("ARGOS_DATA_ROOT", str(tmp_path / "ops"))
    with pytest.raises(v5.SimulationBlocked):
        v5.assert_run_allowed("TEST", True, tmp_path / "ops" / "raw")


def test_v5_sandbox_run_marks_output_as_simulated_under_temp_only(tmp_path):
    spec = importlib.util.spec_from_file_location("cnmv_engine_v5_sandbox", V5)
    v5 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v5)
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps({"version": "t", "total_entities": 1,
                                    "companies": {"SAN": {"cif_nif": "A-39000013"}}}))
    out = tmp_path / "sandbox_out"
    cfg = {"master_universe_path": str(universe), "mode": "SANDBOX", "allow_simulated": True, "max_workers": 1}
    engine = v5.CNMVEngineV5(cfg, out)
    asyncio.run(engine.run_ingestion([2024], ["ALL"], False))        # fase moderna: sin red
    doc = json.loads((out / "MANIFEST_CNMV_2024.json").read_text(encoding="utf-8"))
    assert doc["SIMULATED"] is True and doc["execution_mode"] == "SANDBOX"
    assert all(r["simulated"] and r["doc_type"] == "SIMULATED" for r in doc["manifest"])
    for rec in doc["manifest"]:                                       # y el guard sigue rechazándolo en LIVE/PILOT
        for mode in (ExecutionMode.LIVE, ExecutionMode.PILOT):
            with pytest.raises(SimulatedDataRejectedError):
                persistence_guard.assert_persistable(rec, mode, out)


def test_no_productive_entrypoint_invokes_cnmv_engine_v5():
    repo_root = ARGOS_MOTOR.parent
    offenders = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "archive", "node_modules", "tests", "data")]
        for fn in filenames:
            if fn.endswith((".py", ".bat", ".cmd", ".sh", ".ps1", ".toml", ".yml", ".yaml")):
                p = Path(dirpath) / fn
                if p.resolve() == V5.resolve():
                    continue
                try:
                    if "cnmv_engine_v5" in p.read_text(encoding="utf-8", errors="ignore"):
                        offenders.append(str(p.relative_to(repo_root)))
                except OSError:
                    pass
    assert offenders == []


# =============================================================== ADAPTERS (20-25)
def test_adapters_declare_canonical_contract():
    cnmv, bafin = CNMVAdapter(lambda r: []), BaFinAdapter([])
    assert (cnmv.name, cnmv.allowed_domains, cnmv.source_type) == ("CNMV", ("www.cnmv.es", "cnmv.es"), SourceType.OFFICIAL_OAM)
    assert (bafin.name, bafin.allowed_domains, bafin.source_type) == (
        "BAFIN", ("ir-api.eqs.com", "filings.xbrl.org"), SourceType.OFFICIAL_INDEX)
    for a in (cnmv, bafin):
        assert isinstance(a, protocols.SourceAdapter)
        validate_allowed_domains(a.allowed_domains)
        assert a.source_type not in (SourceType.SIMULATED, SourceType.TEST_FIXTURE)


def test_candidates_carry_source_and_type_and_pass_live_policy():
    cnmv = CNMVAdapter(lambda r: [{"lei": "L1", "ticker": "SAN", "name": "X", "fiscal_year": 2023,
                                   "doc_type": "ESEF_PACKAGE", "url": "https://www.cnmv.es/a.zip"}])
    c = cnmv.discover(DiscoveryRequest(authority="CNMV"))[0]
    assert (c.source, c.source_type) == ("CNMV", SourceType.OFFICIAL_OAM)
    assert_candidate_allowed(c, ExecutionMode.LIVE)
    prov_esef = lambda r: [{"ticker": "SAP", "lei": "L2", "name": "SAP", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
                            "url": "https://filings.xbrl.org/x.zip", "source_type": SourceType.OFFICIAL_INDEX}]
    d = BaFinAdapter([prov_esef]).discover(DiscoveryRequest(authority="BAFIN"))[0]
    assert d.source == "BAFIN" and d.source_type is SourceType.OFFICIAL_INDEX


def test_eqs_catalog_candidates_are_not_labelled_official(tmp_path):
    f = tmp_path / "eqs.json"
    f.write_text(json.dumps({"companies": {"SAP": {"isin": "DE0007164600", "name": "SAP", "reports": {
        "2023": {"source_url": "https://ir-api.eqs.com/x.pdf"}}}}}))
    c = BaFinAdapter([EqsVerifiedLinksProvider(f)]).discover(DiscoveryRequest(authority="BAFIN"))[0]
    assert c.source_type is SourceType.LEGACY_SCRAPER and urlparse(c.source_url).hostname in BaFinAdapter.allowed_domains


def test_allowed_domains_are_explicit_without_wildcards_or_loose_suffixes():
    for a in (CNMVAdapter, BaFinAdapter):
        assert all("*" not in d and "/" not in d and not d.startswith(".") for d in a.allowed_domains)
    for bad in [(), ("*",), ("*.cnmv.es",), (".cnmv.es",), ("https://cnmv.es",), ("cnmv.es/x",), ("CNMV.es",), ["cnmv.es"], ("cnmv",)]:
        with pytest.raises(DomainValidationError):
            validate_allowed_domains(bad)
    doms = CNMVAdapter.allowed_domains
    assert is_host_allowed("www.cnmv.es", doms) and is_host_allowed("a.b.cnmv.es", doms) and is_host_allowed("CNMV.ES.", doms)
    for evil in ("evilcnmv.es", "cnmv.es.evil.com", "wwwcnmv.es", "", "cnmv.esx"):
        assert not is_host_allowed(evil, doms), evil


def test_adapters_have_no_legacy_or_http_dependencies():
    forbidden = {"httpx", "requests", "aiohttp", "socket", "urllib.request", "http.client", "playwright", "duckdb"}
    for f in sorted((UNIFIED / "adapters").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        for m in mods:
            assert m not in forbidden and m.split(".")[0] not in {"httpx", "requests", "aiohttp", "socket"}, (f.name, m)
            assert "descarga" not in m and not m.endswith(("ingest_runner", "robust_downloader", "cnmv_engine"))


def test_single_canonical_source_adapter_protocol():
    assert v1_module.SourceAdapter is protocols.SourceAdapter           # el nombre de Fase 4 es reexport
    defs = []
    for f in UNIFIED.rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ClassDef) and n.name.endswith("SourceAdapter") and any(
                    getattr(b, "id", getattr(b, "attr", "")) == "Protocol" for b in n.bases):
                defs.append(f"{f.name}:{n.name}")
    assert defs == ["protocols.py:SourceAdapter"], defs                  # ningún tercer Protocol
