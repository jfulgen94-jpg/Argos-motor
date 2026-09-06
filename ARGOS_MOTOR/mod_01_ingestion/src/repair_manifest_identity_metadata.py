"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Script de reparación forense puntual: corrige los manifiestos de
INFORMES_ANUALES_COMPLETOS cuyo campo interno "ticker"/"company_name" quedó
relleno con un fragmento del LEI duplicado (bug de un generador previo a esta
sesión), en vez del ticker y la razón social reales.

No descarga nada nuevo ni modifica los archivos físicos ya sellados: solo
corrige el metadato descriptivo del manifiesto, dejando constancia auditable
del valor original y de la fuente usada para la corrección (nombre de la
carpeta + catálogo maestro `config/master_universe_es.json`).

Uso:
    python -m mod_01_ingestion.src.repair_manifest_identity_metadata [--dry-run]
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT = Path("data/raw/ES_CNMV/INFORMES_ANUALES_COMPLETOS")
CATALOG_PATH = Path("config/master_universe_es.json")


def load_catalog() -> Tuple[Dict[str, dict], Dict[str, Tuple[str, dict]]]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    companies = catalog["companies"]
    by_lei = {}
    for ticker, info in companies.items():
        lei = (info.get("lei") or "").upper()
        if lei:
            by_lei[lei] = (ticker, info)
    return companies, by_lei


def looks_like_lei_fragment(value: str) -> bool:
    """El bug detectado produce valores tipo '959800MA', '8EWQ2UQK', alfanuméricos
    de longitud corta sin espacios, muy distintos de un ticker real de mercado
    (2-5 letras) o de una razón social real (con espacios y sufijo societario)."""
    if not value:
        return True
    if re.fullmatch(r"[A-Z0-9]{6,12}", value.upper()) and not re.fullmatch(r"[A-Z]{2,6}", value.upper()):
        return True
    return False


def repair_manifest(manifest_path: Path, companies: Dict[str, dict], by_lei: Dict[str, Tuple[str, dict]], dry_run: bool) -> Optional[str]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    current_ticker = str(data.get("ticker", ""))
    current_name = str(data.get("company_name", ""))

    if not looks_like_lei_fragment(current_ticker) and current_name.upper() != f"{current_ticker.upper()}_{current_ticker.upper()}_SA".upper():
        return None  # ya está bien

    company_folder = manifest_path.parent.parent.name  # .../{TICKER}_{Name}/manifest_sha256/*.json
    folder_ticker = company_folder.split("_")[0].upper()

    resolved_ticker = None
    resolved_name = None
    source = None

    if folder_ticker in companies:
        resolved_ticker = folder_ticker
        resolved_name = companies[folder_ticker].get("name_legal")
        source = "master_universe_es.json (por ticker de carpeta)"
    else:
        # Intentar resolver por LEI embebido en el nombre de fichero del informe sellado
        lei_match = re.search(r"([0-9A-Z]{18}[0-9A-Z]{2})", current_ticker.upper())
        if lei_match and lei_match.group(1) in by_lei:
            resolved_ticker, info = by_lei[lei_match.group(1)]
            resolved_name = info.get("name_legal")
            source = "master_universe_es.json (por LEI)"

    if not resolved_ticker:
        # No se puede resolver automáticamente con garantías: no se fabrica un valor.
        return f"UNRESOLVED: {manifest_path} (folder_ticker={folder_ticker} no está en el catálogo maestro)"

    if not dry_run:
        data["_forensic_correction"] = {
            "corrected_at": datetime.now(timezone.utc).isoformat(),
            "reason": "El campo ticker/company_name original contenía un fragmento del LEI duplicado, no la identidad real.",
            "original_ticker": current_ticker,
            "original_company_name": current_name,
            "resolution_source": source,
        }
        data["ticker"] = resolved_ticker
        data["company_name"] = resolved_name
        manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    return f"FIXED: {manifest_path} -> ticker={resolved_ticker}, company_name={resolved_name} (fuente: {source})"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo reporta, no escribe cambios")
    args = parser.parse_args()

    companies, by_lei = load_catalog()

    fixed, unresolved, untouched = [], [], 0
    for manifest_path in ROOT.rglob("manifest_sha256/*.json"):
        result = repair_manifest(manifest_path, companies, by_lei, dry_run=args.dry_run)
        if result is None:
            untouched += 1
        elif result.startswith("FIXED"):
            fixed.append(result)
        else:
            unresolved.append(result)

    print(f"Manifiestos ya correctos: {untouched}")
    print(f"Manifiestos corregidos:   {len(fixed)}")
    print(f"Manifiestos sin resolver: {len(unresolved)}")
    for line in fixed:
        print("  " + line)
    for line in unresolved:
        print("  " + line)

    if args.dry_run:
        print("\n[DRY-RUN] No se escribió ningún cambio en disco.")


if __name__ == "__main__":
    main()
