"""
U5E — Artefactos PENDIENTES de configuración, contrato y plan del piloto CNMV (Telefónica 2019, un solo documento).
Todo offline: JSON del checkout, DuckDB temporal de aprobaciones, sin red, sin D:, sin descargas.
"""
import ast
import copy
import json
import os
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified import cnmv_pilot as cp
from mod_01_ingestion.src.unified.approvals import ApprovalError, ApprovalRegistry
from mod_01_ingestion.src.unified.cnmv_pilot import (
    ARTIFACT_DIR, CnmvPilotArtifacts, NotActivatable, PilotArtifactError, activate, find_markers, is_marker, load_artifacts,
    parse_artifacts, submit_pending)
from mod_01_ingestion.src.unified.data_root import DEFAULT_PILOT_ROOT

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
MANIFEST_2019 = Path(__file__).resolve().parents[2] / "audits" / "manifests" / "MANIFEST_CNMV_2019.json"


def raw():
    return {k: json.loads((ARTIFACT_DIR / n).read_text(encoding="utf-8")) for k, n in cp.FILES.items()}


def loaded():
    return load_artifacts()


def completed(tmp_root: Path) -> CnmvPilotArtifacts:
    """Variante SINTÉTICA con todos los marcadores resueltos (como la dejaría un aprobador); el destino es un tmp_path."""
    r = raw()
    s = r["config"]["source"]
    r["config"]["official_evidence_ref"] = "SYNTHETIC-OFFICIAL-REF-1"
    s["allowed_domains_evidence"] = "SYNTHETIC-OFFICIAL-REF-2"
    s["user_agent"] = "STATER-Pilot/1.0"
    s["contact"] = "data-ops@stater-sandbox.test"
    c = r["contract"]
    c.update(namespace="synthetic-ns", id_scope="VERSION", source_document_id_field="synthetic-id-field",
             allowed_evidence_kinds=["REVISION_NUMBER"], republication_evidence="SYNTHETIC-OFFICIAL-REF-3")
    p = r["plan"]
    p["control_document"].update(year_semantics="SYNTHETIC-FISCAL-YEAR", url_status="SYNTHETIC-OFFICIAL-REF-4",
                                 control_status="SYNTHETIC-OFFICIAL-REF-5")
    p["destination_root"] = str(tmp_root)
    return parse_artifacts(r["config"], r["contract"], r["plan"])


def approve_all(reg, art, who="bob"):
    for kind, s in art.subjects().items():
        reg.approve(s["subject_id"], kind, s["version"], who, f"TICKET-{kind}")


def registry(tmp_path):
    return ApprovalRegistry(tmp_path / "approvals.duckdb")


# ================================================================= artefactos pendientes versionados
def test_three_artifacts_exist_and_are_pending_approval():
    art = loaded()
    for d, name in ((art.config, "CNMV_SOURCE_CONFIG"), (art.contract, "CNMV_IDENTITY_CONTRACT"), (art.plan, "CNMV_PILOT_PLAN")):
        assert d["artifact"] == name and d["status"] == "PENDING_APPROVAL"
    s = art.config["source"]
    assert (s["source_id"], s["authority"], s["country_code"], s["allowed_domains"]) == ("cnmv_pilot", "CNMV", "ES", ["www.cnmv.es"])
    assert s["rate"] == {"min_interval_s": 5, "max_concurrent": 1} and s["timeout_s"] == 60 and s["max_total_s"] == 300
    assert s["max_bytes"] == 64 * 1024 * 1024 and s["http_403_policy"] == "PERMANENT_NO_RETRY" and 403 not in s["retries"]["retry_statuses"]
    # el User-Agent es un marcador no activable y no hay ningún correo inventado
    assert "NOT_ACTIVATABLE" in s["user_agent"] and "@" not in json.dumps(art.config)


def test_pending_markers_cover_every_unknown_value_and_nothing_is_invented():
    art = loaded()
    assert set(find_markers(art.config)) == {"official_evidence_ref", "source.allowed_domains_evidence", "source.user_agent",
                                             "source.contact"}
    assert set(find_markers(art.contract)) == {"namespace", "id_scope", "source_document_id_field", "allowed_evidence_kinds",
                                               "republication_evidence"}
    assert set(find_markers(art.plan)) == {"control_document.year_semantics", "control_document.url_status",
                                           "control_document.control_status"}
    c = art.contract
    assert (c["initial_version_policy"], c["expected_sha256_authority"]) == ("NONE", False)       # defaults seguros, no inventados
    assert is_marker("REQUIRES_OFFICIAL_EVIDENCE") and is_marker("PENDING_APPROVAL:X") and is_marker("  ") and not is_marker("ok")
    assert find_markers({"status": "PENDING_APPROVAL", "x": 1}) == []                              # el status administrativo no cuenta


def test_control_document_is_exactly_telefonica_2019_pdf_with_the_local_control_values():
    cd = loaded().plan["control_document"]
    assert (cd["issuer_name"], cd["ticker"], cd["nif"], cd["fiscal_year"], cd["document_family"]) == (
        "Telefónica, S.A.", "TEF", "A28015865", 2019, "ANNUAL_REPORT_PDF")
    assert cd["candidate_url"] == "https://www.cnmv.es/AUDITA/2019/18290.pdf" and cd["url_status"] == "REQUIRES_OFFICIAL_EVIDENCE"
    assert cd["local_control_size_bytes"] == 23_864_356 and cd["control_status"] == "REQUIRES_OFFICIAL_EVIDENCE"
    # el SHA de control sale del manifiesto local del checkout (sin abrir ni re-hashear nada de D:)
    rec = [r for r in json.loads(MANIFEST_2019.read_text(encoding="utf-8"))["manifest"] if r["ticker"] == "TEF"]
    assert len(rec) == 1 and rec[0]["sha256"] == cd["local_control_sha256"] and rec[0]["size_bytes"] == cd["local_control_size_bytes"]
    assert rec[0]["url"] == cd["candidate_url"]


def test_plan_limits_destination_and_gates():
    p = loaded().plan
    assert p["limits"] == {"max_documents": 1, "max_concurrent": 1, "min_interval_s": 5, "request_timeout_s": 60, "max_total_s": 300,
                           "max_bytes_per_document": 67108864, "max_total_bytes": 67108864, "allowed_domains": ["www.cnmv.es"]}
    assert Path(p["destination_root"]) == DEFAULT_PILOT_ROOT and p["destination_status"] == "NOT_CREATED"
    assert p["gates"] == {"canary_sandbox_ok_required": True, "four_eyes_required": True, "max_canary_age_s": 86400}
    assert p["single_source"] is True
    pp = loaded().pilot_plan()
    assert pp.authority == "CNMV" and pp.limits.max_documents == 1 and pp.limits.allowed_domains == ("www.cnmv.es",)


# ================================================================= nada pendiente puede activarse
def test_nothing_pending_can_activate(tmp_path):
    art, reg = loaded(), registry(tmp_path)
    res = activate(art, reg)
    assert not res.active and res.configs is None and res.plan is None
    assert {"SOURCE_CONFIG_NOT_SUBMITTED", "IDENTITY_CONTRACT_NOT_SUBMITTED", "PILOT_PLAN_NOT_SUBMITTED"} <= set(res.blockers)
    with pytest.raises(NotActivatable) as e:
        art.source_config_set()
    assert any("source.user_agent" in b for b in e.value.blockers) and any("namespace" in b for b in e.value.blockers)
    st = submit_pending(art, reg, "alice")
    assert st == {"SOURCE_CONFIG": "PENDING_APPROVAL", "IDENTITY_CONTRACT": "PENDING_APPROVAL", "PILOT_PLAN": "PENDING_APPROVAL"}
    res = activate(art, reg)
    assert not res.active and {"SOURCE_CONFIG_PENDING_APPROVAL", "IDENTITY_CONTRACT_PENDING_APPROVAL",
                               "PILOT_PLAN_PENDING_APPROVAL"} <= set(res.blockers)


def test_even_if_a_marker_artifact_is_approved_by_mistake_it_stays_inactive(tmp_path):
    art, reg = loaded(), registry(tmp_path)
    submit_pending(art, reg, "alice")
    approve_all(reg, art)                                   # error humano: se aprueba el contenido con marcadores
    res = activate(art, reg)
    assert not res.active and res.configs is None
    for marker in ("CONFIG_MARKER:source.user_agent", "CONFIG_MARKER:source.contact", "CONTRACT_MARKER:namespace",
                   "CONTRACT_MARKER:id_scope", "PLAN_MARKER:control_document.url_status"):
        assert marker in res.blockers, marker
    assert not any(b.startswith(("SOURCE_CONFIG_", "IDENTITY_CONTRACT_", "PILOT_PLAN_")) for b in res.blockers)


def test_a_marker_user_agent_or_contact_is_rejected_for_activation(tmp_path):
    r = raw()
    done = completed(tmp_path / "root")
    for field in ("user_agent", "contact"):
        d = copy.deepcopy(done.config)
        d["source"][field] = r["config"]["source"][field]            # solo ESE campo vuelve a ser marcador
        art = CnmvPilotArtifacts(d, done.contract, done.plan)
        with pytest.raises(NotActivatable) as e:
            art.source_config_set()
        assert e.value.blockers == [f"CONFIG_MARKER:source.{field}"]
        reg = registry(tmp_path / field)
        submit_pending(art, reg, "alice")
        approve_all(reg, art)
        assert f"CONFIG_MARKER:source.{field}" in activate(art, reg).blockers
    d = copy.deepcopy(done.config)
    d["source"]["user_agent"] = "STATER-Pilot/1.0 changeme"            # el analizador estricto también lo rechaza
    with pytest.raises(NotActivatable):
        CnmvPilotArtifacts(d, done.contract, done.plan).source_config_set()


def test_a_contract_without_official_evidence_cannot_activate_field_by_field(tmp_path):
    done = completed(tmp_path / "root")
    r = raw()
    for field in ("namespace", "id_scope", "source_document_id_field", "allowed_evidence_kinds", "republication_evidence"):
        c = copy.deepcopy(done.contract)
        c[field] = r["contract"][field]
        art = CnmvPilotArtifacts(done.config, c, done.plan)
        assert art.blockers() == [f"CONTRACT_MARKER:{field}"]
        reg = registry(tmp_path / field)
        submit_pending(art, reg, "alice")
        approve_all(reg, art)
        res = activate(art, reg)
        assert not res.active and f"CONTRACT_MARKER:{field}" in res.blockers


# ================================================================= solo se activa desde el registro
def test_complete_artifacts_activate_only_through_the_approval_registry(tmp_path):
    art = completed(tmp_path / "root")
    assert art.blockers() == []
    reg = registry(tmp_path)
    assert not activate(art, reg).active                              # completo, pero sin registro
    submit_pending(art, reg, "alice")
    assert not activate(art, reg).active                              # enviado, sin aprobar
    with pytest.raises(ApprovalError):
        reg.approve("cnmv_pilot", "SOURCE_CONFIG", art.config["config_version"], "alice", "T")      # cuatro ojos
    approve_all(reg, art, "bob")
    res = activate(art, reg)
    assert res.active and res.blockers == []
    s = res.configs.get("CNMV")
    assert s.source_id == "cnmv_pilot" and s.allowed_domains == ("www.cnmv.es",) and s.contract is not None
    assert s.contract_status == "ACTIVE" and s.min_interval_s == 5 and s.max_concurrent == 1 and s.max_bytes == 64 * 1024 * 1024
    assert res.plan.limits.max_documents == 1 and res.plan.root == str(tmp_path / "root")
    first = next(iter(art.subjects().values()))
    reg.revoke(first["subject_id"], "SOURCE_CONFIG", art.config["config_version"], "carol", "retirada")
    assert not activate(art, reg).active


@pytest.mark.parametrize("path,value", [
    (("plan", "control_document", "candidate_url"), "https://www.cnmv.es/AUDITA/2019/99999.pdf"),
    (("plan", "control_document", "nif"), "A28000000"),
    (("plan", "control_document", "fiscal_year"), 2020),
    (("plan", "control_document", "document_family"), "ESEF_ZIP"),
    (("plan", "control_document", "local_control_sha256"), "0" * 64),
    (("plan", "control_document", "local_control_size_bytes"), 1),
    (("plan", "limits", "max_total_s"), 299),
    (("plan", "limits", "max_bytes_per_document"), 1_000_000),
    (("plan", "limits", "min_interval_s"), 6),
    (("plan", "destination_root"), "SET_IN_TEST"),
    (("config", "source", "rate", "min_interval_s"), 6),
    (("config", "source", "max_bytes"), 1_000_000),
    (("config", "source", "timeout_s"), 30),
    (("config", "source", "retries", "max_retries"), 2),
    (("contract", "namespace"), "other-ns"),
    (("contract", "id_scope"), "LOGICAL_DOCUMENT"),
])
def test_changing_any_approved_field_invalidates_the_approval(tmp_path, path, value):
    art = completed(tmp_path / "root")
    reg = registry(tmp_path)
    submit_pending(art, reg, "alice")
    approve_all(reg, art)
    assert activate(art, reg).active
    data = {"config": copy.deepcopy(art.config), "contract": copy.deepcopy(art.contract), "plan": copy.deepcopy(art.plan)}
    node = data
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = str(tmp_path / "otro_root") if value == "SET_IN_TEST" else value
    changed = CnmvPilotArtifacts(data["config"], data["contract"], data["plan"])        # sin pasar por los validadores
    res = activate(changed, reg)
    assert not res.active
    kind = {"config": "SOURCE_CONFIG", "contract": "IDENTITY_CONTRACT", "plan": "PILOT_PLAN"}[path[0]]
    assert any(b.startswith(kind + "_") for b in res.blockers), res.blockers          # la aprobación previa deja de valer


# ================================================================= una sola fuente, un solo documento (fail closed)
@pytest.mark.parametrize("mutate", [
    lambda r: r["plan"]["limits"].update(max_documents=2),
    lambda r: r["plan"]["limits"].update(max_concurrent=2),
    lambda r: r["plan"].update(authority="SEC"),
    lambda r: r["plan"].update(single_source=False),
    lambda r: r["plan"]["limits"].update(allowed_domains=["www.cnmv.es", "cnmv.es"]),
    lambda r: r["plan"]["control_document"].update(ticker="SAN"),
    lambda r: r["plan"]["control_document"].update(fiscal_year=2020),
    lambda r: r["plan"]["control_document"].update(document_family="ESEF_ZIP"),
    lambda r: r["plan"]["control_document"].update(candidate_url="https://evil.example.org/a.pdf"),
    lambda r: r["plan"]["control_document"].update(candidate_url="http://www.cnmv.es/AUDITA/2019/18290.pdf"),
    lambda r: r["plan"]["control_document"].update(candidate_url="https://www.cnmv.es/AUDITA/2019/18290.pdf?token=x"),
    lambda r: r["plan"]["control_document"].update(local_control_sha256="abc"),
    lambda r: r["plan"]["control_document"].update(local_control_size_bytes=10 ** 9),
    lambda r: r["plan"]["control_document"].update(extra_document="x"),
    lambda r: r["plan"].update(documents=[{}]),
    lambda r: r["plan"].update(destination_status="CREATED"),
    lambda r: r["plan"].update(destination_root="D:/ARGOS_DATA/raw/ES_CNMV/pilot"),
    lambda r: r["plan"].update(destination_root="relative/root"),
    lambda r: r["plan"]["gates"].update(four_eyes_required=False),
    lambda r: r["plan"]["gates"].update(canary_sandbox_ok_required=False),
    lambda r: r["plan"].update(status="APPROVED"),
    lambda r: r["config"]["source"].update(source_id="otra"),
    lambda r: r["config"]["source"].update(authority="SEC"),
    lambda r: r["config"]["source"].update(allowed_domains=["www.cnmv.es", "www.sec.gov"]),
    lambda r: r["config"]["source"].update(http_403_policy="RETRY"),
    lambda r: r["config"]["source"]["retries"].update(retry_statuses=[403]),
    lambda r: r["config"]["source"]["rate"].update(max_concurrent=2),
    lambda r: r["config"]["source"]["rate"].update(min_interval_s=1),
    lambda r: r["config"]["source"].update(timeout_s=120),
    lambda r: r["config"]["source"].update(max_total_s=900),
    lambda r: r["config"]["source"].update(max_bytes=10 ** 9),
    lambda r: r["config"]["source"]["retries"].update(max_retries=5),
    lambda r: r["config"]["source"].update(password="x"),
    lambda r: r["config"].update(sources=[]),
    lambda r: r["config"].update(status="APPROVED"),
    lambda r: r["contract"].update(initial_version_policy="TRUST_FIRST_VALIDATED"),
    lambda r: r["contract"].update(expected_sha256_authority=True),
    lambda r: r["contract"].update(authority="SEC"),
    lambda r: r["contract"].update(token="x"),
])
def test_artifacts_are_fail_closed(mutate):
    r = raw()
    mutate(r)
    with pytest.raises(PilotArtifactError):
        parse_artifacts(r["config"], r["contract"], r["plan"])


# ================================================================= sin D:, sin red, sin descargas
def test_loading_and_activating_never_touch_d_or_the_network(tmp_path, monkeypatch):
    d_target = Path("D:/ARGOS_DATA/unified_pilot")
    existed = d_target.exists()
    reg = registry(tmp_path)                                 # la DuckDB de aprobaciones es temporal y se crea ANTES del parche
    reg.pending()
    real_mkdir, real_open = os.mkdir, open

    def guard_path(p):
        if str(p).replace("\\", "/").upper().startswith("D:/"):
            raise AssertionError(f"acceso a D: prohibido: {p}")

    monkeypatch.setattr(os, "mkdir", lambda p, *a, **k: (guard_path(p), real_mkdir(p, *a, **k))[1])
    import builtins

    def guarded_open(f, mode="r", *a, **k):
        if isinstance(f, (str, os.PathLike)):
            guard_path(f)
        return real_open(f, mode, *a, **k)
    monkeypatch.setattr(builtins, "open", guarded_open)
    art = load_artifacts()
    submit_pending(art, reg, "alice")
    res = activate(art, reg)
    assert not res.active
    assert d_target.exists() == existed and not Path(art.plan["destination_root"]).joinpath("x").exists()
    with pytest.raises(PilotArtifactError):
        load_artifacts(Path("D:/ARGOS_DATA/otro"))                                       # tampoco lee de una ruta operativa


def test_module_has_no_network_download_or_runtime_dependencies():
    forbidden = {"requests", "urllib.request", "http.client", "socket", "download_service", "ingest_runner", "adapters",
                 "sandbox_replay", "configured_adapter", "router", "legacy_bridge", "cli", "duckdb", "subprocess"}
    tree = ast.parse((UNIFIED / "cnmv_pilot.py").read_text(encoding="utf-8"))
    mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
           [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    for m in mods:
        assert not (set(m.split(".")) & forbidden) and m != "urllib.request", m
    text = (UNIFIED / "cnmv_pilot.py").read_text(encoding="utf-8")
    assert ".mkdir(" not in text and "write_text" not in text and "write_bytes" not in text and "urlopen" not in text
    for other in ("pilot.py", "approvals.py", "ingest_runner.py", "download_service.py"):
        assert "cnmv_pilot" not in (UNIFIED / other).read_text(encoding="utf-8")


def test_committed_artifact_files_are_only_these_three_and_contain_no_secrets():
    names = sorted(p.name for p in ARTIFACT_DIR.iterdir())
    assert names == sorted(cp.FILES.values())
    text = "".join((ARTIFACT_DIR / n).read_text(encoding="utf-8") for n in names).lower()
    for bad in ("password", "token", "secret", "api_key", "bearer", "cookie", "@"):
        assert bad not in text, bad


def test_plan_and_config_must_be_coherent_even_when_both_are_approved(tmp_path):
    done = completed(tmp_path / "root")
    cases = {"PLAN_BYTES_EXCEED_CONFIG": ("max_bytes", 30_000_000), "PLAN_TIME_EXCEEDS_CONFIG": ("max_total_s", 200),
             "PLAN_RATE_INCONSISTENT_WITH_CONFIG": ("rate", {"min_interval_s": 10, "max_concurrent": 1})}
    for code, (key, val) in cases.items():
        cfg = copy.deepcopy(done.config)
        cfg["source"][key] = val
        art = CnmvPilotArtifacts(cfg, done.contract, done.plan)
        reg = registry(tmp_path / code)
        submit_pending(art, reg, "alice")
        approve_all(reg, art)
        res = activate(art, reg)
        assert not res.active and code in res.blockers, (code, res.blockers)
    cfg = copy.deepcopy(done.config)
    cfg["source"]["allowed_domains"] = ["cnmv.es"]
    art = CnmvPilotArtifacts(cfg, done.contract, done.plan)
    reg = registry(tmp_path / "dom")
    submit_pending(art, reg, "alice")
    approve_all(reg, art)
    assert "PLAN_DOMAINS_DIFFER_FROM_CONFIG" in activate(art, reg).blockers
