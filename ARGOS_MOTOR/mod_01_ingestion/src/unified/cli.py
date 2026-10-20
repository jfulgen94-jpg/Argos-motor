"""
FASE 4 — CLI único de ingesta unificada.

  python -m mod_01_ingestion.src.unified.cli --authority BAFIN --years 2020 2021
      --data-root D:\\ARGOS_DATA --provider eqs:ARGOS_MOTOR/config/eqs_verified_links.json [--limit 5] [--dry-run]

``--dry-run`` solo descubre (cero red, cero escrituras). La descarga real requiere red y NO se
ejecuta en tests. Proveedores: ``eqs:<json>`` y ``esef:<json>`` (BAFIN), ``json:<archivo>``
(lista de registros normalizados; CNMV y BAFIN).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mod_01_ingestion.src.unified.adapters.bafin import BaFinAdapter, EqsVerifiedLinksProvider, EsefCatalogProvider
from mod_01_ingestion.src.unified.adapters.cnmv import CNMVAdapter
from mod_01_ingestion.src.unified.config import resolve_layout
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.models import DiscoveryRequest


def _json_provider(path: Path):
    def provider(_req):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return provider


def _make_provider(spec: str):
    kind, _, p = spec.partition(":")
    if kind == "eqs":
        return EqsVerifiedLinksProvider(Path(p))
    if kind == "esef":
        return EsefCatalogProvider(Path(p))
    if kind == "json":
        return _json_provider(Path(p))
    raise SystemExit(f"Proveedor desconocido: {spec}")


def build_adapter(authority: str, specs):
    authority = authority.upper()
    providers = [_make_provider(s) for s in specs]
    if authority == "BAFIN":
        return BaFinAdapter(providers)
    if authority == "CNMV":
        return CNMVAdapter(lambda req: [r for pr in providers for r in pr(req)])
    raise SystemExit(f"Autoridad sin adapter unificado todavía: {authority}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="STATER — ingesta unificada (ruta única)")
    ap.add_argument("--authority", required=True)
    ap.add_argument("--years", nargs="*", type=int, default=[])
    ap.add_argument("--issuers", nargs="*", default=[])
    ap.add_argument("--doc-types", nargs="*", default=[])
    ap.add_argument("--provider", action="append", default=[], help="eqs:<json> | esef:<json> | json:<json>")
    ap.add_argument("--data-root", default=None, help="por defecto ARGOS_DATA_ROOT")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    adapter = build_adapter(a.authority, a.provider)
    req = DiscoveryRequest(authority=a.authority, fiscal_years=a.years, issuer_ids=a.issuers,
                           doc_types=a.doc_types, limit=a.limit)
    if a.dry_run:
        cands = adapter.discover(req)
        print(json.dumps({"dry_run": True, "authority": a.authority, "candidates": len(cands),
                          "sample": [c.to_dict() for c in cands[:3]]}, ensure_ascii=False, indent=2))
        return 0
    layout = resolve_layout(a.data_root)
    runner = UnifiedIngestRunner(layout, {a.authority: adapter})
    report = runner.run_discovery(req)
    print(json.dumps({"run_id": report.run_id, "outcomes": [o.__dict__ for o in report.outcomes]},
                     ensure_ascii=False, indent=2))
    return 0 if all(o.state in ("COMPLETED", "SKIPPED_ALREADY_PRESENT", "SKIPPED_DUPLICATE") for o in report.outcomes) else 2


if __name__ == "__main__":
    sys.exit(main())
