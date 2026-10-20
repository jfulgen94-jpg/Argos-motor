"""
U5D — Preparación de un piloto controlado de UNA fuente, SIN descargas reales: raíz de datos unificada aislada, exclusión de
herramientas legacy, cobertura de Azure con cliente simulado y piloto en PENDING_APPROVAL con canario como puerta de entrada.
Todo sintético y offline (tmp_path, DuckDB temporal, sockets bloqueados).
"""
import ast
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from mod_01_ingestion.src import identity_audit_reorganizer as reorg
from mod_01_ingestion.src.unified import legacy_exclusions as lx
from mod_01_ingestion.src.unified.approvals import ApprovalRegistry
from mod_01_ingestion.src.unified.canary import Alert, run_canary
from mod_01_ingestion.src.unified.canary_reports import CanaryReportStore
from mod_01_ingestion.src.unified.cloud_sync import UNIFIED_PREFIX, UnifiedSyncError, UnifiedSynchronizer, build_plan
from mod_01_ingestion.src.unified.config import PathPolicyError
from mod_01_ingestion.src.unified.data_root import (DEFAULT_PILOT_ROOT, STRUCTURE, UnifiedDataRoot, resolve_unified_root,
                                                   validate_unified_root)
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.pilot import (HARD_MAX_DOCUMENTS, PilotBudget, PilotError, PilotLimitExceeded, PilotLimits,
                                               build_pilot_plan, evaluate_gate, submit_pilot, write_plan)
from mod_01_ingestion.src.unified.source_config import parse_source_configs
from mod_01_ingestion.tests.test_unified_ops import env, rep
from mod_01_ingestion.tests.test_unified_source_config import (ES_DOMAINS, US_DOMAINS, config, contract_dict, source)

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
ARGOS_MOTOR = Path(__file__).resolve().parents[2]
PILOT, TEST = ExecutionMode.PILOT, ExecutionMode.TEST
SHA_A, SHA_B = hashlib.sha256(b"blob-a").hexdigest(), hashlib.sha256(b"blob-b").hexdigest()


def tree_fingerprint(base):
    out = {}
    for p in sorted(Path(base).rglob("*")):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(base).as_posix()] = (hashlib.sha256(p.read_bytes()).hexdigest(), st.st_mtime_ns)
    return out


def make_unified(tmp_path, name="unified", mode=PILOT):
    """Raíz unificado inicializado, con contenido sintético en todas las estructuras."""
    root = UnifiedDataRoot(tmp_path / name, mode).initialize()
    lay = root.layout
    blob = lay.cas / SHA_A[:2] / SHA_A
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"blob-a")
    view = lay.raw / "SEC" / "2026" / "doc.pdf"
    view.parent.mkdir(parents=True, exist_ok=True)
    os.link(blob, view)
    pin = lay.cas_pins / SHA_A / "pin-1"
    pin.parent.mkdir(parents=True, exist_ok=True)
    os.link(blob, pin)
    (lay.versions / "sec").mkdir(parents=True, exist_ok=True)
    (lay.versions / "sec" / "v1.json").write_text(json.dumps({"version": 1, "sha256": SHA_A}), encoding="utf-8")
    (lay.manifests / "SEC").mkdir(parents=True, exist_ok=True)
    (lay.manifests / "SEC" / "m.json").write_text(json.dumps({"doc": "d1", "sha256": SHA_A}), encoding="utf-8")
    (lay.reports / "r.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    lay.catalog_db.write_bytes(b"DUCKDB-SYNTHETIC-CATALOG")
    return root


# ================================================================= 1. raíz de datos unificada aislada
def test_default_root_is_d_unified_pilot_and_resolving_or_validating_never_writes(tmp_path, monkeypatch):
    assert DEFAULT_PILOT_ROOT == Path("D:/ARGOS_DATA/unified_pilot")
    monkeypatch.delenv("ARGOS_UNIFIED_ROOT", raising=False)

    def boom(*a, **k):
        raise AssertionError("resolver/validar no puede escribir en disco")
    monkeypatch.setattr(Path, "mkdir", boom)
    monkeypatch.setattr(Path, "write_text", boom)
    monkeypatch.setattr(Path, "write_bytes", boom)
    r = resolve_unified_root(None, PILOT)
    assert r.path == DEFAULT_PILOT_ROOT and r.mode is PILOT
    validate_unified_root(DEFAULT_PILOT_ROOT, PILOT)


@pytest.mark.parametrize("mode", [TEST, ExecutionMode.SANDBOX])
def test_tests_never_get_a_default_root_nor_an_operational_one(tmp_path, monkeypatch, mode):
    monkeypatch.delenv("ARGOS_UNIFIED_ROOT", raising=False)
    with pytest.raises(PathPolicyError, match="indicar"):
        resolve_unified_root(None, mode)
    with pytest.raises(PathPolicyError):
        resolve_unified_root(DEFAULT_PILOT_ROOT, mode)                        # ruta operativa en pruebas
    with pytest.raises(PathPolicyError):
        validate_unified_root("D:/ARGOS_DATA/otro", mode)
    assert resolve_unified_root(tmp_path / "u", mode).path == tmp_path / "u"   # temporal autorizado


def test_root_must_be_separate_from_the_legacy_tree(tmp_path, monkeypatch):
    legacy_env = tmp_path / "legacy_data"
    monkeypatch.setenv("ARGOS_DATA_ROOT", str(legacy_env))
    bad = ["relative/dir", "D:/ARGOS_DATA/raw", "D:/ARGOS_DATA/raw/unified", "D:/ARGOS_DATA", "D:/",
           str(ARGOS_MOTOR / "data"), str(ARGOS_MOTOR / "data" / "raw" / "ES_CNMV"), str(ARGOS_MOTOR / "data" / "unified"),
           str(legacy_env), str(legacy_env / "raw"), str(legacy_env / "raw" / "x")]
    for b in bad:
        for mode in (PILOT, TEST):
            with pytest.raises(PathPolicyError):
                validate_unified_root(b, mode)
    # hermano de raw/ dentro de la raíz legacy: admitido para PILOT (como el valor por defecto), nunca para pruebas
    validate_unified_root(legacy_env / "unified_pilot", PILOT)
    with pytest.raises(PathPolicyError):
        validate_unified_root(legacy_env / "unified_pilot", TEST)


def test_env_variable_selects_the_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_UNIFIED_ROOT", str(tmp_path / "from_env"))
    assert resolve_unified_root(None, TEST).path == tmp_path / "from_env"
    assert resolve_unified_root(tmp_path / "explicit", TEST).path == tmp_path / "explicit"    # el argumento manda


def test_initialize_creates_the_clear_structure_and_marker_only_there(tmp_path):
    root = UnifiedDataRoot(tmp_path / "u", PILOT)
    assert not (tmp_path / "u").exists() and not root.is_initialized()
    root.initialize()
    for d in STRUCTURE:
        assert (root.path / d).is_dir(), d
    assert STRUCTURE == ("raw", "cas", "cas_pins", "manifests", "versions", "catalog", "reports")
    assert root.is_initialized() and json.loads(root.marker.read_text())["kind"] == "ARGOS_UNIFIED_ROOT"
    lay = root.layout
    assert lay.cas_pins == root.path / "cas_pins" and lay.reports == root.path / "reports"
    assert lay.catalog_db == root.path / "catalog" / "unified_catalog.duckdb"
    before = tree_fingerprint(root.path)
    root.initialize()                                                          # idempotente
    assert tree_fingerprint(root.path) == before
    with pytest.raises(PathPolicyError):
        UnifiedDataRoot(Path("D:/ARGOS_DATA/raw/x"), PILOT).initialize()          # nunca sobre el legacy


# ================================================================= 2. exclusión de herramientas legacy
def test_marker_and_reserved_dirs(tmp_path):
    root = make_unified(tmp_path)
    assert lx.find_unified_root(root.path / "cas" / "ab") == root.path
    for d in lx.RESERVED_DIRS:
        assert lx.is_unified_reserved(root.path / d / "x")
    assert not lx.is_unified_reserved(root.path / "raw" / "SEC" / "doc.pdf")        # las vistas siguen siendo legibles
    assert not lx.is_unified_reserved(tmp_path / "legacy" / "cas" / "x")           # fuera de un raíz: nada se excluye
    with pytest.raises(lx.UnifiedTreeViolation):
        lx.assert_not_unified(root.path / "raw")
    lx.assert_not_unified(tmp_path / "legacy")


def test_iter_files_prunes_a_descendant_unified_root_and_reserved_dirs(tmp_path):
    root = make_unified(tmp_path / "disk", name="unified_pilot")
    (tmp_path / "disk" / "raw" / "ES").mkdir(parents=True)
    (tmp_path / "disk" / "raw" / "ES" / "a.pdf").write_bytes(b"legacy")
    below = {p.relative_to(tmp_path / "disk").as_posix() for p in lx.iter_files(tmp_path / "disk")}
    assert below == {"raw/ES/a.pdf"}                                              # el raíz unificado se poda entero
    inside = {p.relative_to(root.path).as_posix() for p in lx.iter_files(root.path)}
    assert inside == {"raw/SEC/2026/doc.pdf"}                                     # solo la vista; nada de cas/versions/...


def test_legacy_reorganizer_sweep_does_not_touch_the_unified_tree(tmp_path, monkeypatch):
    root = make_unified(tmp_path)
    before = tree_fingerprint(root.path)
    monkeypatch.setattr(reorg, "RAW_ROOT", root.path)
    hashed = []
    real = reorg.sha256_of
    monkeypatch.setattr(reorg, "sha256_of", lambda p, *a, **k: (hashed.append(Path(p)), real(p, *a, **k))[1])
    report = reorg.audit_tree({}, {})
    seen = {p.relative_to(root.path).as_posix() for p in hashed}
    assert seen == {"raw/SEC/2026/doc.pdf"} and report["scanned_files"] == 1 and report["duplicate_groups"] == {}
    assert tree_fingerprint(root.path) == before
    with pytest.raises(lx.UnifiedTreeViolation):                                   # --apply se niega a mover/borrar
        reorg.apply_moves({"needs_move": [{"file": str(root.path / "raw" / "SEC" / "2026" / "doc.pdf"), "prefix": [],
                                           "year": "2026", "from_folder": "x", "to_folder": "y"}]})
    assert tree_fingerprint(root.path) == before


def test_legacy_reorganizer_default_behaviour_is_unchanged_on_a_legacy_tree(tmp_path, monkeypatch):
    legacy = tmp_path / "ES_CNMV"
    (legacy / "2024" / "XYZ").mkdir(parents=True)
    (legacy / "2024" / "XYZ" / "a.pdf").write_bytes(b"x")
    (legacy / "cas").mkdir()
    (legacy / "cas" / "b.pdf").write_bytes(b"y")                                   # sin marcador: un árbol legacy normal
    monkeypatch.setattr(reorg, "RAW_ROOT", legacy)
    assert reorg.audit_tree({}, {})["scanned_files"] == 2


def test_forensic_auditor_sweep_does_not_touch_the_unified_tree(tmp_path, monkeypatch):
    from mod_01_ingestion.src.forensic_dataset_auditor import ForensicDatasetAuditor
    (tmp_path / "work" / "config").mkdir(parents=True)
    shutil.copy2(ARGOS_MOTOR / "config" / "master_universe_es.json", tmp_path / "work" / "config" / "master_universe_es.json")
    monkeypatch.chdir(tmp_path / "work")
    root = make_unified(tmp_path)
    (root.layout.cas / SHA_B[:2]).mkdir(parents=True)
    (root.layout.cas / SHA_B[:2] / "x.pdf").write_bytes(b"%PDF cas")                 # un .pdf dentro de cas/
    before = tree_fingerprint(root.path)
    result = ForensicDatasetAuditor(base_dir=root.path).run_full_audit(output_dir=tmp_path / "out")
    audited = json.dumps(result, default=str)
    assert "cas" + os.sep not in audited and "x.pdf" not in audited and "doc.pdf" in audited
    assert tree_fingerprint(root.path) == before


def test_every_legacy_extractor_and_audit_is_guarded():
    files = sorted((ARGOS_MOTOR / "extraccion_interpretacion").glob("*/extractor_*.py")) + \
        sorted((ARGOS_MOTOR / "extraccion_interpretacion").glob("*/forensic_audit_*.py"))
    assert len(files) == 10
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "legacy_exclusions import is_unified_reserved" in text and text.count("is_unified_reserved(") >= 1, f.name
        ast.parse(text)
    spec = importlib.util.spec_from_file_location("extractor_es_u5d", ARGOS_MOTOR / "extraccion_interpretacion/es_spain/extractor_es.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)                                                    # el import (con la guarda) no falla


def test_legacy_extractor_package_scan_skips_reserved_dirs(tmp_path):
    spec = importlib.util.spec_from_file_location("extractor_es_u5d2", ARGOS_MOTOR / "extraccion_interpretacion/es_spain/extractor_es.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    root = make_unified(tmp_path)
    before = tree_fingerprint(root.path)
    out = m.analyze_and_extract_package(root.path, "2026")
    listed = json.dumps(out, default=str)
    assert "blob-a" not in listed and SHA_A not in listed and "v1.json" not in listed and "m.json" not in listed
    assert tree_fingerprint(root.path) == before                                  # no escribe en el árbol unificado


# ================================================================= 3. Azure: cobertura con cliente simulado
class FakeBlob:
    def __init__(self, store, name, fail=0):
        self.store, self.name, self.fail = store, name, fail

    def upload_blob(self, data, overwrite=False, content_settings=None, metadata=None, **kw):
        if self.store.failures.get(self.name, 0) > 0:
            self.store.failures[self.name] -= 1
            raise RuntimeError("transient")
        if self.name in self.store.blobs and not overwrite:
            raise RuntimeError("exists")
        body = data if isinstance(data, bytes) else data.read()
        self.store.blobs[self.name] = {"data": body, "metadata": dict(metadata or {})}
        self.store.order.append(self.name)


class FakeContainer:
    def __init__(self):
        self.blobs, self.order, self.failures = {}, [], {}

    def list_blobs(self, name_starts_with="", include=None):
        for n, b in sorted(self.blobs.items()):
            if n.startswith(name_starts_with):
                yield SimpleNamespace(name=n, size=len(b["data"]), metadata=b["metadata"])

    def get_blob_client(self, name):
        return FakeBlob(self, name)


def sync(root, container, **kw):
    return UnifiedSynchronizer(container, sleep=lambda s: None).sync(root.path, **kw)


def test_azure_sync_covers_cas_pins_versions_manifests_catalog_and_reports(tmp_path):
    root = make_unified(tmp_path)
    c = FakeContainer()
    res = sync(root, c)
    assert res["errors"] == [] and res["conflicts"] == []
    assert res["by_kind"] == {"cas": 1, "cas_pin": 1, "catalog": 1, "manifests": 1, "reports": 1, "versions": 1}
    assert set(c.blobs) == {f"{UNIFIED_PREFIX}{r}" for r in (
        f"cas/{SHA_A[:2]}/{SHA_A}", f"cas_pins/{SHA_A}/pin-1", "versions/sec/v1.json", "manifests/SEC/m.json",
        "reports/r.json", "catalog/unified_catalog.duckdb")}                       # misma jerarquía; raw/ no se duplica
    assert c.order[0].startswith("unified/cas/") and c.order[-1] == "unified/catalog/unified_catalog.duckdb"
    cas = c.blobs[f"unified/cas/{SHA_A[:2]}/{SHA_A}"]
    assert cas["data"] == b"blob-a" and cas["metadata"]["sha256"] == SHA_A and cas["metadata"]["unified_kind"] == "cas"
    pin = c.blobs[f"unified/cas_pins/{SHA_A}/pin-1"]
    assert pin["data"] == b"" and pin["metadata"]["pin_of"] == SHA_A and pin["metadata"]["blob_size"] == "6"
    man = c.blobs["unified/manifests/SEC/m.json"]
    assert man["metadata"]["sha256"] == hashlib.sha256(man["data"]).hexdigest() and man["metadata"]["stater_managed"] == "true"


def test_azure_sync_is_idempotent_and_detects_changes(tmp_path):
    root = make_unified(tmp_path)
    c = FakeContainer()
    sync(root, c)
    again = sync(root, c)
    assert again["uploaded"] == 0 and again["skipped_exists"] == 6
    (root.layout.manifests / "SEC" / "m.json").write_text(json.dumps({"doc": "d1", "sha256": SHA_B}), encoding="utf-8")
    third = sync(root, c)
    assert third["uploaded_blobs"] == ["unified/manifests/SEC/m.json"]
    assert json.loads(c.blobs["unified/manifests/SEC/m.json"]["data"])["sha256"] == SHA_B


def test_azure_sync_never_overwrites_an_immutable_cas_blob_and_dry_run_uploads_nothing(tmp_path):
    root = make_unified(tmp_path)
    c = FakeContainer()
    c.blobs[f"unified/cas/{SHA_A[:2]}/{SHA_A}"] = {"data": b"CORRUPT-REMOTE", "metadata": {"sha256": "0" * 64}}
    res = sync(root, c)
    assert res["conflicts"] == [{"blob": f"unified/cas/{SHA_A[:2]}/{SHA_A}", "reason": "CAS_IMMUTABLE_MISMATCH"}]
    assert c.blobs[f"unified/cas/{SHA_A[:2]}/{SHA_A}"]["data"] == b"CORRUPT-REMOTE"
    c2 = FakeContainer()
    dry = sync(root, c2, dry_run=True)
    assert dry["dry_run"] and dry["uploaded"] == 6 and c2.blobs == {}


def test_azure_sync_skips_secrets_temporaries_symlinks_and_a_non_quiescent_catalog(tmp_path):
    root = make_unified(tmp_path)
    lay = root.layout
    (lay.manifests / "azure_secrets.json").write_text('{"connection_string": "x"}', encoding="utf-8")
    (lay.manifests / "leak.json").write_text('{"cs": "DefaultEndpointsProtocol=https;AccountKey=abcdefghijklmnop=="}', encoding="utf-8")
    (lay.manifests / "tok.json").write_text('{"h": "Bearer abcdefghijklmnopqrstuv"}', encoding="utf-8")
    (lay.versions / "x.part").write_bytes(b"partial")
    (lay.reports / ".env").write_text("K=V", encoding="utf-8")
    (lay.reports / "key.pem").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    (lay.staging / "tmp.bin").write_bytes(b"staging")
    (lay.locks / "a.lock").write_bytes(b"")
    (lay.telemetry / "t.jsonl").write_text("{}", encoding="utf-8")
    (lay.quarantine / "q.bin").write_bytes(b"q")
    try:
        os.symlink(lay.raw, lay.reports / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pass
    (lay.catalog_db.parent / "unified_catalog.duckdb.wal").write_bytes(b"pending")
    c = FakeContainer()
    res = sync(root, c)
    names = set(c.blobs)
    for forbidden in ("azure_secrets", "leak", "tok", ".part", ".env", ".pem", "staging", ".lock", "telemetry", "quarantine",
                      "catalog", "link"):
        assert not any(forbidden in n for n in names), forbidden
    reasons = {s["path"]: s["reason"] for s in res["skipped"]}
    assert reasons["catalog/unified_catalog.duckdb"] == "CATALOG_NOT_QUIESCENT"
    assert reasons["manifests/leak.json"] == reasons["manifests/tok.json"] == "SENSITIVE_OR_TEMPORARY"
    assert "AccountKey" not in json.dumps(res) and all("abcdefghijklmnop" not in json.dumps(b["metadata"]) for b in c.blobs.values())


def test_azure_sync_retries_transient_errors_and_reports_final_failures(tmp_path):
    root = make_unified(tmp_path)
    c = FakeContainer()
    c.failures["unified/reports/r.json"] = 2
    ok = sync(root, c)
    assert ok["errors"] == [] and "unified/reports/r.json" in c.blobs
    c2 = FakeContainer()
    c2.failures["unified/reports/r.json"] = 99
    bad = sync(root, c2)
    assert bad["errors"] == [{"blob": "unified/reports/r.json", "error": "RuntimeError"}] and "unified/reports/r.json" not in c2.blobs
    assert "unified/catalog/unified_catalog.duckdb" in c2.blobs                      # un fallo no impide el resto


def test_azure_sync_requires_an_initialized_unified_root(tmp_path):
    with pytest.raises(UnifiedSyncError):
        build_plan(tmp_path)
    (tmp_path / "plain").mkdir()
    with pytest.raises(UnifiedSyncError):
        UnifiedSynchronizer(FakeContainer()).sync(tmp_path / "plain")
    root = make_unified(tmp_path)
    with pytest.raises(UnifiedSyncError):
        build_plan(root.layout.cas)                                                # un subdirectorio no es el raíz


def test_legacy_synchronizer_exposes_the_unified_sync_without_credentials(tmp_path):
    spec = importlib.util.spec_from_file_location("azure_sync_u5d", ARGOS_MOTOR / "cloud" / "azure_data_lake_sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s = mod.AzureDataLakeSynchronizer.__new__(mod.AzureDataLakeSynchronizer)         # sin conexión ni credenciales
    s.container_client = FakeContainer()
    root = make_unified(tmp_path)
    res = s.sync_unified(root.path)
    assert res["uploaded"] == 6 and len(s.container_client.blobs) == 6
    text = (UNIFIED / "cloud_sync.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert not any(isinstance(n, ast.Attribute) and n.attr == "environ" for n in ast.walk(tree))
    assert "azure_secrets" not in text.replace('"azure_secrets.json"', "") and "connection_string" not in text.lower()


# ================================================================= 4. piloto de una fuente: PENDING_APPROVAL, sin descargas
def pilot_configs(with_contract=True):
    over = {"identity_contract": contract_dict(approval={"status": "PENDING_APPROVAL", "ref": ""})} if with_contract else {}
    return parse_source_configs(config(source("SEC", "US", US_DOMAINS, **over), source("CNMV", "ES", ES_DOMAINS)))


def limits(**over):
    d = dict(allowed_domains=("www.sec.gov",), max_documents=5, max_bytes_per_document=1_000_000, max_total_bytes=3_000_000,
             max_total_s=120)
    d.update(over)
    return PilotLimits(**d)


def make_plan(tmp_path, configs=None, authority="SEC", **lim):
    root = UnifiedDataRoot(tmp_path / "pilot_root", PILOT)
    return root, build_pilot_plan(configs or pilot_configs(), authority, limits(**lim), root)


def test_pilot_is_single_source_with_strict_limits(tmp_path):
    cfgs = pilot_configs()
    for bad in ("FCA", "AMF", "SEC,CNMV", ""):
        with pytest.raises(PilotError, match="única fuente"):
            make_plan(tmp_path, cfgs, bad)
    root, plan = make_plan(tmp_path, cfgs, "cnmv", allowed_domains=("www.cnmv.es",))
    assert plan.authority == "CNMV" and plan.subject_id == "pilot:CNMV"
    for kw in ({"max_documents": 0}, {"max_documents": HARD_MAX_DOCUMENTS + 1}, {"max_documents": True},
               {"max_bytes_per_document": 0}, {"max_bytes_per_document": 2 * 1024 ** 3},
               {"max_total_bytes": 1, "max_bytes_per_document": 2}, {"max_total_s": 0}, {"max_total_s": 99999},
               {"allowed_domains": ()}, {"allowed_domains": ("https://www.sec.gov",)}, {"allowed_domains": ("*.sec.gov",)},
               {"allowed_domains": ("www.sec.gov/files",)}):
        with pytest.raises(PilotError):
            limits(**kw)
    with pytest.raises(PilotError, match="fuera de la configuración"):
        make_plan(tmp_path, cfgs, "SEC", allowed_domains=("evil.example.org",))
    with pytest.raises(PilotError, match="supera"):
        make_plan(tmp_path, cfgs, "SEC", max_bytes_per_document=50_000_000, max_total_bytes=60_000_000)
    with pytest.raises(PilotError, match="PILOT"):
        build_pilot_plan(cfgs, "SEC", limits(), UnifiedDataRoot(tmp_path / "t", TEST))
    with pytest.raises(PathPolicyError):
        build_pilot_plan(cfgs, "SEC", limits(), UnifiedDataRoot(Path("D:/ARGOS_DATA/raw/x"), PILOT))


def approve_all(reg, plan, configs, who="alice", approver="bob"):
    reg.approve("sec_sandbox", "SOURCE_CONFIG", configs.config_version, approver, "T-1")
    reg.approve("sec_sandbox", "IDENTITY_CONTRACT", "1", approver, "T-2")
    reg.approve(plan.subject_id, "PILOT_PLAN", plan.plan_version, approver, "T-3")


def test_pilot_submission_stays_pending_approval_and_downloads_nothing(tmp_path):
    cfgs = pilot_configs()
    root, plan = make_plan(tmp_path, cfgs)
    reg = ApprovalRegistry(tmp_path / "approvals.duckdb")
    out = submit_pilot(plan, cfgs, reg, "alice")
    assert out == {"sec_sandbox:SOURCE_CONFIG": "PENDING_APPROVAL", "sec_sandbox:IDENTITY_CONTRACT": "PENDING_APPROVAL",
                   "pilot:SEC:PILOT_PLAN": "PENDING_APPROVAL"}
    assert {(p["subject_id"], p["kind"]) for p in reg.pending()} == {("sec_sandbox", "SOURCE_CONFIG"),
                                                                    ("sec_sandbox", "IDENTITY_CONTRACT"), ("pilot:SEC", "PILOT_PLAN")}
    assert not any(s["subject_id"] == "cnmv_sandbox" for s in reg.pending())           # una única fuente
    assert not root.path.exists()                                                      # no se creó el raíz unificado
    assert list(tmp_path.iterdir()) and {p.name for p in tmp_path.iterdir()} <= {"approvals.duckdb", "approvals.duckdb.wal"}
    with pytest.raises(Exception):
        reg.approve("pilot:SEC", "PILOT_PLAN", plan.plan_version, "alice", "T")        # cuatro ojos: no se autoaprueba


def test_pilot_gate_blocks_until_approved_root_initialized_and_canary_ok(tmp_path):
    cfgs = pilot_configs()
    root, plan = make_plan(tmp_path, cfgs)
    reg = ApprovalRegistry(tmp_path / "approvals.duckdb")
    store = CanaryReportStore(tmp_path / "canary.duckdb")
    now = "2026-10-13T12:00:00+00:00"
    submit_pilot(plan, cfgs, reg, "alice")
    d = evaluate_gate(plan, cfgs, reg, store, now_iso=now)
    assert not d.allowed
    assert {"ROOT_NOT_INITIALIZED", "PLAN_PENDING_APPROVAL", "SOURCE_CONFIG_PENDING_APPROVAL", "IDENTITY_CONTRACT_PENDING_APPROVAL",
            "CANARY_MISSING"} <= set(d.blockers)
    approve_all(reg, plan, cfgs)
    root.initialize()
    d = evaluate_gate(plan, cfgs, reg, store, now_iso=now)
    assert d.blockers == ["CANARY_MISSING"] and not d.allowed
    store.save(rep("SEC", finished="2026-10-13T10:00:00+00:00"), run_id="r1")
    assert evaluate_gate(plan, cfgs, reg, store, now_iso=now).allowed
    assert "CANARY_STALE" in evaluate_gate(plan, cfgs, reg, store, now_iso="2026-10-15T12:00:00+00:00").blockers
    # un canario en WARN o ERROR cierra la puerta
    store.save(rep("SEC", finished="2026-10-13T11:00:00+00:00", alerts=[Alert("W", "WARN", "m")]), run_id="r2")
    assert evaluate_gate(plan, cfgs, reg, store, now_iso=now).blockers == ["CANARY_WARN"]
    store.save(rep("SEC", finished="2026-10-13T11:30:00+00:00", alerts=[Alert("E", "ERROR", "m")]), run_id="r3")
    assert evaluate_gate(plan, cfgs, reg, store, now_iso=now).blockers == ["CANARY_ERROR"]
    store.save(rep("SEC", finished="2026-10-13T11:45:00+00:00"), run_id="r4")
    assert evaluate_gate(plan, cfgs, reg, store, now_iso=now).allowed
    # una revocación o un plan distinto lo cierran de nuevo
    reg.revoke("pilot:SEC", "PILOT_PLAN", plan.plan_version, "carol", "no procede")
    assert evaluate_gate(plan, cfgs, reg, store, now_iso=now).blockers == ["PLAN_REVOKED"]


def test_pilot_gate_rejects_a_modified_plan_and_a_missing_contract(tmp_path):
    cfgs = pilot_configs()
    root, plan = make_plan(tmp_path, cfgs)
    reg = ApprovalRegistry(tmp_path / "approvals.duckdb")
    store = CanaryReportStore(tmp_path / "canary.duckdb")
    submit_pilot(plan, cfgs, reg, "alice")
    approve_all(reg, plan, cfgs)
    root.initialize()
    store.save(rep("SEC", finished="2026-10-13T11:00:00+00:00"), run_id="r1")
    now = "2026-10-13T12:00:00+00:00"
    assert evaluate_gate(plan, cfgs, reg, store, now_iso=now).allowed
    _, bigger = make_plan(tmp_path, cfgs, max_documents=50)                          # mismos id y versión, otros límites
    assert evaluate_gate(bigger, cfgs, reg, store, now_iso=now).blockers == ["PLAN_APPROVED"]
    nocontract = pilot_configs(with_contract=False)
    _, p2 = make_plan(tmp_path, nocontract)
    assert "CONTRACT_REQUIRED" in evaluate_gate(p2, nocontract, reg, store, now_iso=now).blockers


def test_canary_is_the_entry_gate_using_a_real_sandbox_canary(tmp_path):
    runner, http, ledger, ads, store = env(tmp_path)
    cfgs = pilot_configs()
    root, plan = make_plan(tmp_path, cfgs)
    reg = ApprovalRegistry(tmp_path / "approvals.duckdb")
    submit_pilot(plan, cfgs, reg, "alice")
    approve_all(reg, plan, cfgs)
    root.initialize()
    now = "2026-10-13T12:00:00+00:00"
    assert evaluate_gate(plan, cfgs, reg, store, now_iso=now).blockers == ["CANARY_MISSING"]
    r = run_canary(runner, "SEC", expected=[], ledger=ledger, clock=lambda: "2026-10-13T11:00:00+00:00")
    assert r.mode == "SANDBOX"
    store.save(r, run_id=runner.run.run_id, trigger="MANUAL")
    decision = evaluate_gate(plan, cfgs, reg, store, now_iso=now)
    assert decision.allowed and decision.details["canary"]["status"] == "OK"


def test_pilot_budget_enforces_source_domain_documents_bytes_and_time(tmp_path):
    _, plan = make_plan(tmp_path, max_documents=2, max_bytes_per_document=100, max_total_bytes=150, max_total_s=10)
    clock = {"t": 0.0}
    b = PilotBudget(plan, clock=lambda: clock["t"])
    with pytest.raises(PilotError):
        b.check_time()                                                              # sin start
    b.start()
    for code, call in (("PILOT_SINGLE_SOURCE", lambda: b.begin_document("CNMV", "https://www.sec.gov/a")),
                       ("PILOT_DOMAIN_NOT_ALLOWED", lambda: b.begin_document("SEC", "https://evil.example.org/a")),
                       ("PILOT_DOMAIN_NOT_ALLOWED", lambda: b.begin_document("SEC", "https://www.sec.gov.evil.org/a"))):
        with pytest.raises(PilotLimitExceeded) as e:
            call()
        assert e.value.code == code
    assert b.documents == 0
    b.begin_document("SEC", "https://www.sec.gov/a")
    b.record_bytes(100)
    with pytest.raises(PilotLimitExceeded) as e:
        b.record_bytes(101)
    assert e.value.code == "PILOT_DOCUMENT_TOO_LARGE"
    b.begin_document("sec", "https://www.sec.gov/b")
    with pytest.raises(PilotLimitExceeded) as e:
        b.record_bytes(60)
    assert e.value.code == "PILOT_TOTAL_BYTES"
    with pytest.raises(PilotLimitExceeded) as e:
        b.begin_document("SEC", "https://www.sec.gov/c")
    assert e.value.code == "PILOT_MAX_DOCUMENTS"
    clock["t"] = 11.0
    with pytest.raises(PilotLimitExceeded) as e:
        b.begin_document("SEC", "https://www.sec.gov/d")
    assert e.value.code == "PILOT_TIME_EXCEEDED"


def test_write_plan_requires_an_initialized_root_and_records_the_content_hash(tmp_path):
    cfgs = pilot_configs()
    root, plan = make_plan(tmp_path, cfgs)
    with pytest.raises(PilotError):
        write_plan(root, plan)
    assert not root.path.exists()
    root.initialize()
    p = write_plan(root, plan)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert p.parent == root.layout.reports / "pilot" and data["authority"] == "SEC" and data["single_source"] is True
    assert len(data["content_hash"]) == 64


# ================================================================= arquitectura: el módulo del piloto no puede descargar
def test_pilot_and_sync_modules_have_no_download_or_network_capability():
    forbidden = ("download_service", "ingest_runner", "adapters", "requests", "urllib.request", "http.client", "socket",
                 "sandbox_replay", "configured_adapter", "router", "legacy_bridge")
    for name in ("pilot.py", "cloud_sync.py", "data_root.py", "legacy_exclusions.py"):
        tree = ast.parse((UNIFIED / name).read_text(encoding="utf-8"))
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        for m in mods:
            assert not any(m == f or m.endswith("." + f) or f"{f}." in m + "." and f in m.split(".") for f in forbidden), (name, m)
    legacy = ast.parse((UNIFIED / "legacy_exclusions.py").read_text(encoding="utf-8"))
    stdlib_only = [n.module for n in ast.walk(legacy) if isinstance(n, ast.ImportFrom) and n.module]
    assert all(not m.startswith("mod_01_ingestion") for m in stdlib_only)                  # solo biblioteca estándar
    for other in ("canary_scheduler.py", "ops_status.py", "ingest_runner.py", "download_service.py"):
        t = (UNIFIED / other).read_text(encoding="utf-8")
        assert "unified.pilot" not in t and "cloud_sync" not in t
