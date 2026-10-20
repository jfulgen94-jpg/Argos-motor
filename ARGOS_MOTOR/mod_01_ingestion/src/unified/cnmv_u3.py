"""
CNMV-U3 — Descubrimiento seguro 2020-hoy con enlaces tokenizados: SOLO metadatos y evidencia saneada. No descarga, no sigue enlaces tokenizados,
no persiste tokens. Reutiliza ``cnmv_evidence`` (saneado, clasificación, presupuesto) y el listado IFA oficial de CNMV-U1.

Por emisor: 1 ficha IFA + hasta 1 página de detalle por ejercicio (``infadicionifa``: información adicional / motivo) = ≤ 12 solicitudes.
Los tokens existen solo en memoria durante el análisis; lo persistido lleva host/path sin query y, de los tokens, solo una huella con sal por
ejecución. Se detiene ante un 403.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from mod_01_ingestion.src.unified.cnmv_discovery import DOC_TYPE, ISSUERS, LISTING_URL, DiscoveryError, _norm, _plain
from datetime import datetime, timezone

from mod_01_ingestion.src.unified.domain.republication import replacement_signal
from mod_01_ingestion.src.unified.cnmv_evidence import (
    BudgetedFetcher, FullRow, contains_token, link_kind_summary, new_salt, parse_full, sanitize_html, sanitize_text,
    _anchor_info)

YEARS = (2020, 2021, 2022, 2023, 2024, 2025)
QUERY_NIF = {"TEF": "A28015865", "SAN": "A39000013", "IBE": "A-48010615", "BBVA": "A48265169", "REP": "A78374725"}
DETAIL_URL = "https://www.cnmv.es/portal/Consultas/ifa/infadicionifa?id=0&nreg={nreg}&nregaud={nregaud}"
GENERIC_SHA_PREFIX = "a80b7cc89747"
REPUBLICATION_RE = re.compile(r"rectific|sustitu|correcci|republic|reenv|anula|modific|subsan", re.I)


def additional_info(page: str, salt: str) -> List[Dict[str, Any]]:
    """Filas de la tabla ``gridInformacionAdicional`` (fecha, motivo y tipo de enlace del documento; nunca el enlace)."""
    m = re.search(r"<table[^>]*gridInformacionAdicional[^>]*>(.*?)</table>", page, re.S)
    if not m:
        return []
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 2:
            continue
        links = [_anchor_info(a, salt) for a in re.findall(r"<a\s([^>]*)>", tr)]
        out.append({"pub_date": _plain(tds[0]) or None, "motive": _plain(tds[1]) or None,
                    "link_kinds": [x.kind for x in links], "token_fps": [x.fp for x in links if x.fp]})
    return out


def local_files(inv: Dict[str, Dict[str, Any]], nif: str, ticker: str, fy: int) -> List[Dict[str, Any]]:
    prefix = f"{fy}/{nif.replace('-', '')}_{ticker}/"
    return [{"name": rel[len(prefix):], "ext": v["ext"], "size": v["size"], "sha12": v["sha256"][:12],
             "generic_placeholder": v["sha256"].startswith(GENERIC_SHA_PREFIX)}
            for rel, v in sorted(inv.items()) if rel.startswith(prefix) and v["ext"] in (".pdf", ".zip", ".xhtml")]


def local_class(files: List[Dict[str, Any]]) -> str:
    if not files:
        return "MISSING_LOCAL"
    if any(f["generic_placeholder"] for f in files):
        return "LOCAL_CONFLICT"                      # el archivo local es el PDF genérico repetido, no este informe
    return "LOCAL_PRESENT_INSUFFICIENT_EVIDENCE"


def run_u3(root: Path, *, issuers=ISSUERS, years=YEARS, fetcher: Optional[BudgetedFetcher] = None, salt: Optional[str] = None,
           inventory: Optional[Dict[str, Dict[str, Any]]] = None, ledger_write: bool = True) -> Dict[str, Any]:
    from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, LedgerStatus
    from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot, validate_unified_root
    from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
    from mod_01_ingestion.src.unified.models import RunContext
    from mod_01_ingestion.src.unified.telemetry import TelemetryLogger

    root = Path(root)
    validate_unified_root(root, ExecutionMode.PILOT)
    ur = UnifiedDataRoot(root, ExecutionMode.PILOT)
    if not ur.is_initialized():
        raise DiscoveryError("la raíz unificada debe estar inicializada")
    lay = ur.layout
    salt = salt or new_salt()
    run = RunContext(data_root=str(root), mode=ExecutionMode.PILOT, operator="cnmv_u3_discovery")
    tel = TelemetryLogger(lay.telemetry, run)
    fetcher = fetcher or BudgetedFetcher(telemetry=tel)
    if fetcher.telemetry is None:
        fetcher.telemetry = tel
    out_dir = lay.reports / "pilot" / "discovery"
    pages = out_dir / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    ledger = CoverageLedger(lay.catalog_db, ExecutionMode.PILOT, telemetry=tel)
    keys = {(t, y): CoverageKey("ES", "CNMV", t, y, DOC_TYPE) for t in issuers for y in years}
    if ledger_write:
        ledger.expect(list(keys.values()), run_id=run.run_id)
    cells: List[Dict[str, Any]] = []
    all_fps: List[str] = []
    all_nregs: Dict[str, List[str]] = {}
    for ticker, (nif, entity) in issuers.items():
        fetcher.begin_issuer(ticker)
        qnif = QUERY_NIF.get(ticker, nif)
        fr = fetcher.fetch(LISTING_URL.format(nif=qnif))
        rows: List[FullRow] = []
        problem: Optional[str] = None
        if fr.outcome != "OK" or not fr.text:
            problem = fr.reason or fr.outcome
        else:
            try:
                rows = parse_full(fr.text, salt)
                cap = re.search(r"<caption[^>]*>(.*?)</caption>", fr.text, re.S)
                if _norm(_plain(cap.group(1)) if cap else "") != _norm(entity):
                    problem, rows = "ENTITY_MISMATCH", []
            except DiscoveryError as ex:
                problem = f"PARSE:{type(ex).__name__}"
            (pages / f"u3_ifa_{ticker}.html").write_text(sanitize_html(fr.text, salt), encoding="utf-8")
        for y in years:
            key = keys[(ticker, y)]
            matches = [r for r in rows if r.fiscal_year == y]
            cell: Dict[str, Any] = {"ticker": ticker, "nif": nif, "nif_query_variant": qnif, "fiscal_year": y, "doc_type": DOC_TYPE,
                                    "rows_for_year": len(matches), "limitations": []}
            files = local_files(inventory or {}, nif, ticker, y)
            cell["local_files"], cell["local_class"] = files, local_class(files)
            ledger_status, why = LedgerStatus.NEEDS_REVIEW, None
            if problem:
                blocked = problem.startswith(("BLOCKED:", "HALTED"))
                cell.update(status="SOURCE_UNAVAILABLE" if blocked or problem.startswith("HTTP_5") else "NEEDS_REVIEW", reason=problem)
                ledger_status, why = (LedgerStatus.SOURCE_UNAVAILABLE if cell["status"] == "SOURCE_UNAVAILABLE"
                                      else LedgerStatus.NEEDS_REVIEW), problem[:60]
                cell["cross_class"] = "NEEDS_REVIEW"
            elif not matches:
                cell.update(status="NEEDS_REVIEW", reason="FY_ROW_ABSENT")
                cell["limitations"].append("la ficha IFA no lista este ejercicio; la ausencia en la ficha no prueba que no se haya publicado")
                why, cell["cross_class"] = "FY_ROW_ABSENT", "NEEDS_REVIEW"
            else:
                row = matches[0]
                kind = link_kind_summary(row)
                fps = [i.fp for i in row.all_links() if i.fp]
                all_fps += fps
                all_nregs.setdefault(row.nreg, []).append(f"{ticker}:{y}")
                tipo_kinds = {lbl: sorted({i.kind for i in v}) for lbl, v in row.tipo.items()}
                cell.update(nreg=row.nreg, fy_date=row.fy_date, pub_date=row.pub_date, auditor=row.auditor, opinion=row.opinion,
                            emphasis=row.emphasis, remarks=row.remarks, status=kind,
                            formats={"xhtml_feue_tipo_column": tipo_kinds, "zip_xbrl_column": sorted({i.kind for i in row.zip_links}),
                                     "pdf_registry_cell": sorted({i.kind for i in row.registry_cell})},
                            link_delivery=sorted({i.kind for i in row.all_links()}), token_fps=fps,
                            detail_link=bool([i for i in row.extension if i.kind == "DETAIL_PAGE"]))
                cell["format_legend"] = ("CNMV indica en la ficha: columna Tipo = informe en formato FEUE/xHTML (individual/consolidado); "
                                         "columna Fichero ZIP/Xbri = paquete comprimido; número de registro enlazado = PDF. No verificado sin descargar.")
                signals = []
                if len(matches) > 1:
                    signals.append(f"{len(matches)} filas para el mismo ejercicio")
                if row.remarks and REPUBLICATION_RE.search(row.remarks):
                    signals.append("observaciones: " + row.remarks[:120])
                # página de detalle (información adicional / motivo) — metadato HTML oficial, sin documentos
                det_links = [i for i in row.extension if i.kind == "DETAIL_PAGE" and i.params and "nreg" in i.params and "nregaud" in i.params]
                cell["additional_info"] = []
                if det_links:
                    pr = det_links[0].params
                    dr = fetcher.fetch(DETAIL_URL.format(nreg=pr["nreg"], nregaud=pr["nregaud"]))
                    if dr.outcome == "OK" and dr.text:
                        cell["additional_info"] = additional_info(dr.text, salt)
                        all_fps += [f for a in cell["additional_info"] for f in a["token_fps"]]
                        (pages / f"u3_detail_{ticker}_{y}.html").write_text(sanitize_html(dr.text, salt), encoding="utf-8")
                        for a in cell["additional_info"]:
                            if a["motive"] and REPUBLICATION_RE.search(a["motive"]):
                                signals.append("información adicional: " + a["motive"][:120])
                    else:
                        cell["limitations"].append(f"página de detalle no obtenida: {dr.reason or dr.outcome}")
                cell["republication_signals"] = signals
                # CNMV-U4: señal OFICIAL de sustitución => POSSIBLE_REPUBLICATION (revisión humana); jamás REPUBLICATION_CONFIRMED
                observed = datetime.now(timezone.utc).isoformat()
                texts = [row.remarks] + [a["motive"] for a in cell["additional_info"]]
                sigs = [s for s in (replacement_signal(t, source="CNMV_IFA", registration_number=row.nreg, observed_at=observed)
                                    for t in texts) if s is not None]
                cell["replacement_signals"] = [s.to_dict() for s in sigs]
                cell["republication_status"] = "POSSIBLE_REPUBLICATION" if sigs else "NONE_OBSERVED"
                if kind == "DISCOVERED_TOKENIZED":
                    cell["cross_class"] = "TOKENIZED_REQUIRES_APPROVAL"
                    cell["limitations"].append("los enlaces llevan un token opaco: no se siguen, no se piden con HEAD y no se persisten; "
                                               "no se puede afirmar qué recurso exacto (xHTML/ZIP/PDF) devuelve cada uno")
                    why = "TOKENIZED_REQUIRES_APPROVAL"
                elif kind == "DISCOVERED_DIRECT_STABLE":
                    cell["cross_class"] = "DIRECT_STABLE_AVAILABLE"
                    ledger_status, why = LedgerStatus.FOUND, "OFFICIAL_LISTING_DIRECT_URL"
                else:
                    cell["cross_class"] = "NEEDS_REVIEW"
                    why = "NO_DOCUMENT_LINK"
                cell["review_reason"] = why
            current = ledger.get(key) if ledger_write else None
            if ledger_write and not (current is not None and current.status is LedgerStatus.PROMOTED):     # PROMOTED es intocable
                evid = {"method": "cnmv_ifa_listing", "ref": f"nreg:{cell['nreg']}" if cell.get("nreg") else f"listing:{ticker}"}
                ledger.record(key, ledger_status, reason=(why or "NEEDS_REVIEW")[:80], evidence=evid, run_id=run.run_id)
            cur = ledger.get(key)
            cell["ledger_status"] = cur.status.value if cur is not None else None
            cells.append(cell)
    # ---- evidencia para el modelo de identidad (solo datos observados en esta ejecución)
    dup_fps = sorted(f for f in set(all_fps) if all_fps.count(f) > 1)
    ev = {"salt": salt, "token_fingerprints_total": len(all_fps), "token_fingerprints_unique": len(set(all_fps)),
          "repeated_fingerprints_in_session": len(dup_fps),
          "nreg_unique_across_cells": all(len(v) == 1 for v in all_nregs.values()),
          "cells_with_republication_signals": [f"{c['ticker']}:{c['fiscal_year']}" for c in cells if c.get("republication_signals")],
          "cells_with_multiple_rows_per_year": [f"{c['ticker']}:{c['fiscal_year']}" for c in cells if c.get("rows_for_year", 0) > 1]}
    summary = {"unit": "CNMV-U3", "issuers": list(issuers), "years": list(years), "requests_total": fetcher.total_requests,
               "requests_per_issuer": dict(fetcher.per_issuer), "http_status_counts": dict(fetcher.status_counts),
               "wait_seconds_between_requests": fetcher.waits, "durations_s": fetcher.durations, "halted": fetcher.halted,
               "documents_downloaded": 0, "document_bodies_read": 0, "identity_evidence": ev, "cells": cells}
    text = json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True, default=str)
    if contains_token(text) or sanitize_text(text) != text:
        raise DiscoveryError("el resultado aún contiene un token: no se persiste")
    (out_dir / "cnmv_u3_results.json").write_text(text, encoding="utf-8")
    with open(out_dir / "cnmv_u3_matrix.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "fiscal_year", "status", "nreg", "fy_date", "pub_date", "delivery", "cross_class", "local_class", "ledger_status"])
        for c in cells:
            w.writerow([c["ticker"], c["fiscal_year"], c["status"], c.get("nreg"), c.get("fy_date"), c.get("pub_date"),
                        "+".join(c.get("link_delivery", [])), c["cross_class"], c["local_class"], c["ledger_status"]])
    return summary
