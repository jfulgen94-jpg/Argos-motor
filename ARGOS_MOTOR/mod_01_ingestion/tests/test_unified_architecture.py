"""
U1 — Tests arquitectónicos y de dominio del núcleo ``unified``. Offline: sin red, todo bajo ``tmp_path``.
Mapa de criterios: ver audits/UNIFIED_DOWNLOAD_U1_2026-10-09/05_ARCHITECTURE_TESTS.md (AT-01..AT-17).
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified.application import ports
from mod_01_ingestion.src.unified.compatibility import legacy_models as compat
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.domain import protocols
from mod_01_ingestion.src.unified.domain.enums import (
    ALLOWED_TRANSITIONS, AttestationLevel, AttestationScope, CoverageStatus, ExecutionMode, PipelineStatus,
    SourceType)
from mod_01_ingestion.src.unified.domain.errors import (
    CompatibilityMappingError, DomainValidationError, InvalidCandidateError, InvalidSourceMetadataError,
    InvalidStateTransitionError, SimulatedDataRejectedError, UnifiedDownloadError, UnsupportedExecutionModeError,
    sanitize_message)
from mod_01_ingestion.src.unified.domain.models import (
    DocumentCandidate, JobContext, ManifestRecord, PipelineResult, RunContext, SourceAttestation, SourceMetadata)
from mod_01_ingestion.src.unified.domain.policy import (
    assert_candidate_allowed, assert_manifest_allowed, assert_not_simulated)
from mod_01_ingestion.src.unified.domain.state import assert_transition
from mod_01_ingestion.src.unified.ingest_runner import JobOutcome, UnifiedIngestRunner
from mod_01_ingestion.src.unified.models import DiscoveryRequest, JobState

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
ARGOS_MOTOR = Path(__file__).resolve().parents[2]
GOOD_SHA = "ab" * 32


def cand(**kw):
    base = dict(authority="CNMV", country_code="es", issuer_id="LEI1", fiscal_year=2023, doc_type="ESEF_PACKAGE",
                source_url="https://example.test/a.zip", source_type=SourceType.OFFICIAL_OAM)
    base.update(kw)
    return DocumentCandidate(**base)


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            yield n.module


def _py(subdir):
    return sorted((UNIFIED / subdir).rglob("*.py"))


# --------------------------------------------------------------------------- AT-01..03 import sin efectos
def test_at01_03_import_has_no_file_network_or_duckdb_side_effects(tmp_path):
    code = (
        "import os, sys, socket\n"
        "def deny(*a, **k): raise RuntimeError('network blocked')\n"
        "socket.socket.connect = deny; socket.create_connection = deny; socket.getaddrinfo = deny\n"
        "before = sorted(os.listdir('.'))\n"
        "import mod_01_ingestion.src.unified, mod_01_ingestion.src.unified.models\n"
        "import mod_01_ingestion.src.unified.domain.models, mod_01_ingestion.src.unified.domain.policy\n"
        "import mod_01_ingestion.src.unified.domain.protocols, mod_01_ingestion.src.unified.application.ports\n"
        "import mod_01_ingestion.src.unified.compatibility.legacy_models\n"
        "assert sorted(os.listdir('.')) == before, 'import creó archivos'\n"
        "for m in ('duckdb', 'httpx', 'requests', 'arelle'):\n"
        "    assert m not in sys.modules, m + ' cargado al importar'\n"
        "print('OK')\n")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ARGOS_MOTOR)}
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- AT-04..07 reglas de dependencia
FORBIDDEN_INFRA = ("httpx", "requests", "duckdb", "arelle", "aiohttp", "playwright")


@pytest.mark.parametrize("layer", ["domain", "application", "compatibility"])
def test_at04_05_inner_layers_do_not_import_infra_or_descarga(layer):
    for f in _py(layer):
        for mod in _imports(f):
            root = mod.split(".")[0]
            assert root not in FORBIDDEN_INFRA, f"{f.name} importa {mod}"
            assert "descarga" not in mod, f"{f.name} importa legado {mod}"


def test_at04_domain_imports_only_stdlib_and_domain():
    allowed_prefix = "mod_01_ingestion.src.unified.domain"
    for f in _py("domain"):
        for mod in _imports(f):
            if mod.split(".")[0] == "mod_01_ingestion":
                assert mod.startswith(allowed_prefix), f"{f.name}: dominio importa {mod}"
            else:
                assert mod.split(".")[0] in sys.stdlib_module_names, f"{f.name}: import no estándar {mod}"


APP_PKG = "mod_01_ingestion.src.unified.application"
DOMAIN_PKG = "mod_01_ingestion.src.unified.domain"
# Excepción ESTRECHA (U5A): el caso de uso preflight consume únicamente el puerto de lookup. Ningún otro módulo de
# application puede importar application.*; todo lo demás sale solo hacia domain.
APP_INTERNAL_EXCEPTIONS = {"preflight.py": {f"{APP_PKG}.ports"}}


def test_at04_application_depends_only_on_domain():
    for f in _py("application"):
        allowed_app = APP_INTERNAL_EXCEPTIONS.get(f.name, set())
        for mod in _imports(f):
            if mod.split(".")[0] == "mod_01_ingestion":
                assert mod.startswith(DOMAIN_PKG) or mod in allowed_app, f"{f.name}: {mod}"


def test_at04_preflight_use_case_has_no_infrastructure_or_io_imports():
    mods = set(_imports(UNIFIED / "application" / "preflight.py"))
    assert not {m for m in mods if m.split(".")[0] in FORBIDDEN_INFRA + ("pathlib", "os", "shutil", "socket", "sqlite3")}
    infra = {"cas_store", "repositories", "ingest_runner", "preflight_lookup", "unit_of_work", "telemetry", "download_service"}
    assert not {m for m in mods if m.rsplit(".", 1)[-1] in infra}


def test_at04_ports_are_free_of_duckdb_and_concrete_filesystem_access():
    tree = ast.parse((UNIFIED / "application" / "ports.py").read_text(encoding="utf-8"))
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "open" not in calls
    assert not {m.split(".")[0] for m in _imports(UNIFIED / "application" / "ports.py")} & {"duckdb", "os", "shutil", "sqlite3"}
    names = {m.rsplit(".", 1)[-1] for m in _imports(UNIFIED / "application" / "ports.py")}
    assert not names & {"repositories", "cas_store", "ingest_runner", "preflight_lookup"}


def test_at04_preflight_lookup_is_infrastructure_adapter_outside_inner_layers():
    assert (UNIFIED / "preflight_lookup.py").is_file()
    assert not (UNIFIED / "application" / "preflight_lookup.py").exists()
    assert not (UNIFIED / "domain" / "preflight_lookup.py").exists()
    mods = set(_imports(UNIFIED / "preflight_lookup.py"))
    assert {"mod_01_ingestion.src.unified.cas_store", "mod_01_ingestion.src.unified.repositories"} <= mods


def test_at04_domain_never_imports_application_or_infrastructure():
    for f in _py("domain"):
        for mod in _imports(f):
            assert not mod.startswith(APP_PKG), f"{f.name}: dominio importa application ({mod})"


def test_at04_runner_may_depend_on_preflight_use_case_but_not_the_reverse():
    runner_mods = set(_imports(UNIFIED / "ingest_runner.py"))
    assert f"{APP_PKG}.preflight" in runner_mods
    for f in _py("application"):
        assert "mod_01_ingestion.src.unified.ingest_runner" not in set(_imports(f))


def test_at04_no_import_cycles_inside_unified():
    graph = {}
    for f in UNIFIED.rglob("*.py"):
        rel = f.relative_to(UNIFIED.parent.parent.parent).with_suffix("")
        name = ".".join(rel.parts)
        name = name[:-9] if name.endswith(".__init__") else name
        graph[name] = {m for m in _imports(f) if m.startswith("mod_01_ingestion.src.unified")}
    graph = {k: {d for d in v if d in graph} for k, v in graph.items()}
    state = {}

    def visit(n, stack):
        state[n] = 1
        for d in graph[n]:
            if state.get(d) == 1:
                raise AssertionError(f"ciclo: {' -> '.join(stack + [n, d])}")
            if d not in state:
                visit(d, stack + [n])
        state[n] = 2
    for n in graph:
        if n not in state:
            visit(n, [])


LEGACY_RUNNERS = ("ingest_runner", "robust_downloader", "cnmv_engine", "cnmv_real_downloader", "gap_fill_downloader")


def test_at06_adapters_do_not_import_legacy_runners_or_infra():
    for f in _py("adapters"):
        for mod in _imports(f):
            assert "descarga" not in mod, f"{f.name} importa {mod}"
            assert mod.split(".")[-1] not in LEGACY_RUNNERS, f"{f.name} importa {mod}"
            assert mod.split(".")[0] not in FORBIDDEN_INFRA, f"{f.name} importa {mod}"
            assert "unified.cas_store" not in mod and "unified.repositories" not in mod


def test_at07_new_modules_have_no_hardcoded_urls():
    for layer in ("domain", "application", "compatibility"):
        for f in _py(layer):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            doc_nodes = {id(n.body[0].value) for n in ast.walk(tree)
                         if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body
                         and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_nodes:
                    assert "://" not in n.value, f"{f.name}: URL hardcodeada {n.value!r}"


# --------------------------------------------------------------------------- AT-08..09 validación de modelos
@pytest.mark.parametrize("kw", [{"authority": ""}, {"issuer_id": " "}, {"doc_type": ""}, {"country_code": ""},
                                {"source_url": ""}, {"source_url": "ftp://x/y"}, {"fiscal_year": 0},
                                {"fiscal_year": "2023"}, {"country_code": "ESP"}])
def test_at08_candidate_rejects_empty_or_invalid_essentials(kw):
    with pytest.raises(InvalidCandidateError):
        cand(**kw)


def test_at08_candidate_normalizes_country_and_is_stable():
    c = cand()
    assert c.country_code == "ES" and c.document_id == "CNMV_LEI1_2023_ESEF_PACKAGE" == cand().document_id


def test_at08_context_and_metadata_validation():
    with pytest.raises(DomainValidationError):
        RunContext(run_id="")
    with pytest.raises(DomainValidationError):
        RunContext(started_at="2026-10-09T10:00:00")          # sin zona horaria
    with pytest.raises(UnsupportedExecutionModeError):
        RunContext(mode="PRODUCTION")
    assert RunContext().mode is ExecutionMode.LIVE            # fail-closed
    with pytest.raises(DomainValidationError):
        JobContext(run_id="r", job_id="", document_id="d", authority="CNMV")
    with pytest.raises(InvalidSourceMetadataError):
        SourceMetadata(resolved_url="", file_name="a.zip")
    with pytest.raises(InvalidSourceMetadataError):
        SourceMetadata(resolved_url="https://x.test/a.zip", file_name="")
    with pytest.raises(InvalidSourceMetadataError):   # filename nunca es dato verificado
        SourceMetadata(resolved_url="https://x.test/a.zip", file_name="a.zip", field_provenance={"file_name": "VERIFIED"})
    m = SourceMetadata(resolved_url="https://x.test/a.zip", file_name="a.zip",
                       field_provenance={"expected_sha256": "VERIFIED"}, expected_sha256=GOOD_SHA)
    assert m.is_verified("expected_sha256") and not m.is_verified("file_name")


@pytest.mark.parametrize("bad", ["placeholder", "PLACEHOLDER", "abc", "z" * 64, "ab" * 31])
def test_at09_placeholder_and_malformed_hashes_rejected(bad):
    with pytest.raises(DomainValidationError):
        cand(expected_sha256=bad)
    with pytest.raises(DomainValidationError):
        SourceMetadata(resolved_url="https://x.test/a", file_name="a", expected_sha256=bad)
    with pytest.raises(DomainValidationError):
        ManifestRecord(**_manifest_kwargs(sha256=bad))
    cand(expected_sha256=GOOD_SHA)   # válido


def _manifest_kwargs(**over):
    kw = dict(manifest_version="1.0.0", document_id="d1", run_id="r1", job_id="j1", authority="CNMV",
              country_code="ES", issuer_id="LEI1", fiscal_year=2023, doc_type="ESEF_PACKAGE",
              source_url="https://x.test/a.zip", final_url=None, raw_path="raw/a.zip", cas_path="cas/ab/cd/x",
              sha256=GOOD_SHA, size_bytes=1, mime_type=None, http_status=200, status="RAW_VALIDATED",
              completeness_status="OK")
    kw.update(over)
    return kw


def test_source_attestation_requires_evidence_and_aware_timestamp():
    ok = dict(algorithm="sha256", expected_digest=GOOD_SHA, authority="ESMA", evidence_ref="https://x.test/ev",
              scope=AttestationScope.PACKAGE, acquired_at="2026-10-09T10:00:00+00:00")
    assert SourceAttestation(**ok).level is AttestationLevel.OFFICIAL_HASH
    for bad in ({"algorithm": "md5"}, {"expected_digest": "placeholder"}, {"evidence_ref": ""},
                {"acquired_at": "2026-10-09T10:00:00"}, {"authority": ""}):
        with pytest.raises(DomainValidationError):
            SourceAttestation(**{**ok, **bad})


# --------------------------------------------------------------------------- AT-10..12 guard SIMULATED
SIM_VARIANTS = [
    dict(doc_type="SIMULATED"), dict(source_type=SourceType.SIMULATED),
    dict(extra={"synthetic": True}), dict(extra={"fake": True}), dict(extra={"fixture": True}),
]


@pytest.mark.parametrize("mode", [ExecutionMode.LIVE, ExecutionMode.PILOT])
@pytest.mark.parametrize("kw", SIM_VARIANTS)
def test_at10_11_simulated_rejected_in_live_and_pilot(mode, kw):
    with pytest.raises(SimulatedDataRejectedError):
        assert_not_simulated(cand(**kw), mode)
    with pytest.raises(SimulatedDataRejectedError):
        assert_candidate_allowed(cand(**kw), mode)


def test_at10_live_requires_declared_source_type_and_rejects_fixture():
    with pytest.raises(SimulatedDataRejectedError):
        assert_candidate_allowed(cand(source_type=None), ExecutionMode.LIVE)
    with pytest.raises(SimulatedDataRejectedError):
        assert_candidate_allowed(cand(source_type=SourceType.TEST_FIXTURE), ExecutionMode.LIVE)
    assert_candidate_allowed(cand(), ExecutionMode.LIVE)         # oficial declarado: permitido


def test_at11_pilot_fixture_only_with_explicit_allowlist():
    c = cand(source_type=SourceType.TEST_FIXTURE)
    with pytest.raises(SimulatedDataRejectedError):
        assert_candidate_allowed(c, ExecutionMode.PILOT)
    assert_candidate_allowed(c, ExecutionMode.PILOT, pilot_fixture_allowlist=frozenset({c.document_id}))
    sim = cand(source_type=SourceType.SIMULATED)    # allowlist nunca habilita SIMULATED
    with pytest.raises(SimulatedDataRejectedError):
        assert_candidate_allowed(sim, ExecutionMode.PILOT, pilot_fixture_allowlist=frozenset({sim.document_id}))


@pytest.mark.parametrize("mode", [ExecutionMode.TEST, ExecutionMode.SANDBOX])
def test_at12_fixtures_allowed_in_test_and_sandbox(mode):
    for kw in SIM_VARIANTS + [dict(source_type=SourceType.TEST_FIXTURE)]:
        assert_candidate_allowed(cand(**kw), mode)


def test_unknown_mode_rejected():
    with pytest.raises(UnsupportedExecutionModeError):
        assert_not_simulated(cand(), "PRODUCTION")


def test_manifest_guard_rejects_engine_v5_style_records_in_live():
    engine_v5_record = {"ticker": "SAN", "year": 2024, "doc_type": "SIMULATED", "sha256": "placeholder",
                        "size_bytes": 0, "status": "CACHE_HIT"}
    for mode in (ExecutionMode.LIVE, ExecutionMode.PILOT):
        with pytest.raises(SimulatedDataRejectedError):
            assert_manifest_allowed(engine_v5_record, mode)
    assert_manifest_allowed(engine_v5_record, ExecutionMode.SANDBOX)
    assert_manifest_allowed(ManifestRecord(**_manifest_kwargs()), ExecutionMode.LIVE)
    with pytest.raises(SimulatedDataRejectedError):
        assert_manifest_allowed(ManifestRecord(**_manifest_kwargs(doc_type="SIMULATED")), ExecutionMode.LIVE)


class _StubAdapter:
    authority = "CNMV"
    country_code = "ES"

    def __init__(self, candidates):
        self._c = candidates

    def discover(self, request):
        return list(self._c)

    def fetch_metadata(self, candidate):  # pragma: no cover - no debe alcanzarse
        raise AssertionError("fetch_metadata no debe invocarse para un candidato simulado")


class _ExplodingDownload:
    telemetry = None

    def download(self, *a, **k):  # pragma: no cover
        raise AssertionError("no debe haber descarga")


def _data_snapshot():
    out = {}
    for p in list((ARGOS_MOTOR / "data").rglob("*")) if (ARGOS_MOTOR / "data").exists() else []:
        if p.is_file():
            st = p.stat()
            out[str(p)] = (st.st_size, st.st_mtime_ns)
    return out


@pytest.mark.parametrize("mode,expect_failed", [(ExecutionMode.LIVE, True), (ExecutionMode.PILOT, True),
                                                (ExecutionMode.SANDBOX, False)])
def test_runner_guard_blocks_simulated_before_any_io(tmp_path, mode, expect_failed):
    before = _data_snapshot()
    sim = cand(doc_type="SIMULATED")
    runner = UnifiedIngestRunner(DataLayout(tmp_path / "root"), {"CNMV": _StubAdapter([sim])},
                                 download=_ExplodingDownload(), run=RunContext(mode=mode))
    if expect_failed:
        rep = runner.run_discovery(DiscoveryRequest(authority="CNMV"))
        assert rep.outcomes[0].state == JobState.FAILED.value
        assert rep.outcomes[0].error_class == "VALIDATION_REJECTED"
        assert not list((tmp_path / "root" / "raw").rglob("*.*"))
    else:
        # SANDBOX permite avanzar hasta metadatos. Desde U4 un fallo del adapter se TIPIFICA (FAILED/ADAPTER) en lugar de
        # tumbar el run: el trampolín de ``fetch_metadata`` queda en el mensaje y la descarga nunca se invoca.
        rep = runner.run_discovery(DiscoveryRequest(authority="CNMV"))
        assert rep.outcomes[0].state == JobState.FAILED.value and rep.outcomes[0].failure_stage == "ADAPTER"
        assert "fetch_metadata" in (rep.outcomes[0].message or "")
    assert _data_snapshot() == before        # AT-17: ni raw ni DuckDB del árbol del proyecto cambian


# --------------------------------------------------------------------------- AT-13..15 compatibilidad
def test_at13_14_states_serializable_and_phase4_values_preserved():
    phase4 = {"DISCOVERED", "QUEUED", "DOWNLOADING", "VERIFYING", "VALIDATING", "PROMOTING", "MANIFESTING",
              "CATALOGING", "COMPLETED", "QUARANTINED", "FAILED", "SKIPPED_DUPLICATE"}
    assert phase4 <= {s.value for s in PipelineStatus}
    assert JobState is PipelineStatus and JobState.SKIPPED_DUPLICATE.value == "SKIPPED_DUPLICATE"
    added = {"SKIPPED_ALREADY_PRESENT", "DOWNLOAD_STARTED", "DOWNLOADED_TO_STAGING", "VALIDATED", "ATTESTED",
             "PROMOTED", "NOT_PUBLISHED", "NOT_APPLICABLE"}
    assert added <= {s.value for s in PipelineStatus}
    assert json.loads(json.dumps({"s": PipelineStatus.SKIPPED_DUPLICATE, "m": ExecutionMode.LIVE})) == \
        {"s": "SKIPPED_DUPLICATE", "m": "LIVE"}
    assert set(ALLOWED_TRANSITIONS) == set(PipelineStatus)
    assert {c.value for c in CoverageStatus} >= {"EXPECTED", "NOT_PUBLISHED", "SOURCE_BLOCKED", "MANUAL_REVIEW"}


def test_state_transitions():
    assert_transition(PipelineStatus.DISCOVERED, PipelineStatus.SKIPPED_ALREADY_PRESENT)
    assert_transition(PipelineStatus.CATALOGING, PipelineStatus.COMPLETED)
    for src, dst in [(PipelineStatus.COMPLETED, PipelineStatus.DOWNLOADING),
                     (PipelineStatus.SKIPPED_ALREADY_PRESENT, PipelineStatus.QUEUED),
                     (PipelineStatus.DISCOVERED, PipelineStatus.PROMOTED)]:
        with pytest.raises(InvalidStateTransitionError):
            assert_transition(src, dst)


def test_at15_legacy_imports_still_resolve():
    import importlib
    for name in ("models", "ingest_runner", "repositories", "source_adapter", "telemetry", "download_service",
                 "validation_pipeline", "cas_store", "lock_manager", "rate_limiter", "config", "legacy_bridge",
                 "adapters.cnmv", "adapters.bafin"):
        importlib.import_module(f"mod_01_ingestion.src.unified.{name}")
    from mod_01_ingestion.src.models import PublicationRecord, DocumentResource   # noqa: F401
    from mod_01_ingestion.src.unified.models import (  # noqa: F401
        CatalogRecord, DocumentCandidate as DC, ErrorClass, ManifestRecord as MR, RunContext as RC)
    assert DC is DocumentCandidate and RC is RunContext and MR is ManifestRecord
    assert JobOutcome is PipelineResult


def test_legacy_publication_mapper_is_explicit_and_lossy_documented():
    from mod_01_ingestion.src.models import IngestionMode, PublicationRecord
    pub = PublicationRecord(publication_id="p1", source="CNMV", issuer_name="X", issuer_identifier="LEI1",
                            reporting_period="2023-12", publication_date="2024-03-01", document_type="ESEF",
                            official_record_url="https://example.test/r", mode=IngestionMode.LIVE.value)
    c = compat.publication_to_candidate(pub, authority="CNMV", country_code="ES",
                                        source_type=SourceType.OFFICIAL_OAM)
    assert c.fiscal_year == 2023 and c.extra["legacy_reporting_period"] == "2023-12"
    assert "publication_id" in " ".join(compat.LOSSY_FIELDS["PublicationRecord->DocumentCandidate"])
    fx = PublicationRecord(**{**pub.__dict__, "mode": IngestionMode.FIXTURE.value})
    assert compat.publication_to_candidate(fx, authority="CNMV", country_code="ES").source_type is SourceType.TEST_FIXTURE
    with pytest.raises(CompatibilityMappingError):
        compat.publication_to_candidate(fx, authority="CNMV", country_code="ES", source_type=SourceType.OFFICIAL_OAM)
    with pytest.raises(CompatibilityMappingError):
        compat.publication_to_candidate(PublicationRecord(**{**pub.__dict__, "reporting_period": "n/a"}),
                                        authority="CNMV", country_code="ES")
    with pytest.raises(CompatibilityMappingError):
        compat.execution_mode_from_legacy("PROD")


# --------------------------------------------------------------------------- Protocols / contrato
class _V2Adapter:
    name = "x"
    allowed_domains = ("example.test",)

    def discover(self, request):
        return iter(())

    def fetch_metadata(self, candidate):
        return SourceMetadata(resolved_url=candidate.source_url, file_name="a.zip")


def test_source_adapter_contract_is_minimal_and_has_no_infra_methods():
    assert isinstance(_V2Adapter(), protocols.SourceAdapter)
    members = {n for n in vars(protocols.SourceAdapter) if not n.startswith("_")}
    assert members == {"discover", "fetch_metadata"}
    assert set(protocols.SourceAdapter.__annotations__) == {"name", "allowed_domains"}


def test_pipeline_ports_cover_existing_implementations():
    from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
    from mod_01_ingestion.src.unified.download_service import DownloadService
    from mod_01_ingestion.src.unified.lock_manager import LockManager
    from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
    from mod_01_ingestion.src.unified.repositories import ManifestRepository, QuarantineService
    from mod_01_ingestion.src.unified.telemetry import TelemetryLogger
    from mod_01_ingestion.src.unified.validation_pipeline import ValidationPipeline
    for impl, proto in [(DownloadService, ports.DownloadServicePort), (ContentAddressedRawStore, ports.ContentAddressedStore),
                        (LockManager, ports.LockManager), (DomainRateLimiter, ports.DomainRateLimiter),
                        (QuarantineService, protocols.QuarantineService), (TelemetryLogger, protocols.TelemetrySink),
                        (ValidationPipeline, protocols.ValidationService), (ManifestRepository, protocols.KnownDocumentRepository)]:
        missing = [m for m in vars(proto) if not m.startswith("_") and not hasattr(impl, m)]
        assert not missing, f"{impl.__name__} no cumple {proto.__name__}: {missing}"


# --------------------------------------------------------------------------- errores
def test_errors_hierarchy_and_secret_redaction():
    for exc in (DomainValidationError, InvalidCandidateError, InvalidSourceMetadataError, SimulatedDataRejectedError,
                InvalidStateTransitionError, UnsupportedExecutionModeError, CompatibilityMappingError):
        assert issubclass(exc, UnifiedDownloadError)
    msg = str(UnifiedDownloadError("fallo Authorization: Bearer abc123 cookie=SESSION42 "
                                   "token: xyz https://h.test/p?api_key=SECRET&a=1 " + "x" * 900))
    for leak in ("abc123", "SESSION42", "xyz", "SECRET"):
        assert leak not in msg
    assert len(msg) < 560
    assert sanitize_message("sin secretos") == "sin secretos"


def test_no_unified_download_package_was_created():
    assert not (UNIFIED.parent / "unified_download").exists()
