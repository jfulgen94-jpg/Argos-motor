"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Auditor forense y reorganizador de identidad para data/raw/ES_CNMV.

Recorre TODO lo ya descargado (no solo lo nuevo), para cada archivo:
  1. Intenta extraer un LEI real de 20 caracteres del propio nombre de fichero
     (patrón estándar ESEF: {LEI}-{YYYY-MM-DD}-...), que es la fuente de verdad
     más fiable porque va sellada por el propio emisor del filing.
  2. Si no hay LEI en el nombre, intenta resolver por el ticker de la carpeta
     contenedora contra el catálogo maestro (config/master_universe_es.json).
  3. Calcula el sha256 de cada archivo para detectar duplicados exactos.
  4. Determina la carpeta canónica correcta: data/raw/ES_CNMV/{YEAR}/{TICKER}-{CIF_NIF}/
  5. NO mueve nada en modo --dry-run (por defecto). Con --apply, ejecuta los
     movimientos y purga duplicados, dejando un reporte JSON detallado.

Nunca inventa una identidad: todo archivo cuyo LEI no está en el catálogo
maestro queda listado en `unresolved_entities`, no se reubica.
"""
import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

RAW_ROOT = Path("data/raw/ES_CNMV")
CATALOG_PATH = Path("config/master_universe_es.json")
REPORT_DIR = Path("data/raw/ES_CNMV/_AUDIT_REPORTS")

LEI_IN_FILENAME_RE = re.compile(r"\b([0-9A-Z]{18}[0-9A-Z]{2})\b")
YEAR_RE = re.compile(r"\b(20[12][0-9])\b")


def load_catalog() -> Tuple[Dict[str, dict], Dict[str, Tuple[str, dict]]]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    companies = catalog["companies"]
    by_lei = {}
    for ticker, info in companies.items():
        lei = (info.get("lei") or "").upper()
        if lei:
            by_lei[lei] = (ticker, info)
    return companies, by_lei


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def locate_year_and_company(parts: Tuple[str, ...]) -> Optional[Tuple[Tuple[str, ...], str, str]]:
    """Localiza (prefijo_de_carpetas, año, carpeta_empresa) dentro de `parts`,
    soportando los dos layouts reales del dataset:
      {YEAR}/{COMPANY}/...
      {ALGUN_PREFIJO}/{YEAR}/{COMPANY}/...  (p.ej. INFORMES_ANUALES_COMPLETOS)
    Devuelve None si `parts` no contiene un tramo {YEAR}/{COMPANY} reconocible.
    """
    for idx in range(len(parts) - 1):
        if YEAR_RE.fullmatch(parts[idx]):
            return parts[:idx], parts[idx], parts[idx + 1]
    return None


def canonical_dirname(ticker: str, cif_nif: str) -> str:
    """Nombre canónico exigido: {TICKER}-{CIF_NIF}."""
    safe_cif = (cif_nif or "SIN_CIF").replace(" ", "")
    return f"{ticker.upper()}-{safe_cif}"


def resolve_identity(file_path: Path, company_folder: str, companies: Dict[str, dict], by_lei) -> Optional[Tuple[str, dict, str]]:
    """Devuelve (ticker, company_info, metodo_resolucion) o None si no se puede resolver."""
    # Los ficheros dentro de `taxonomias_xbrl_esef/` son el paquete de taxonomía XBRL/ESEF
    # ESTÁNDAR: su nombre embebe el LEI del AGENTE/EMISOR DE LA TAXONOMÍA (o de un tercero),
    # no el LEI de la empresa propietaria de la carpeta. Son intencionalmente idénticos entre
    # empresas distintas. Por tanto, para estos ficheros NUNCA se debe confiar en el LEI del
    # nombre de archivo como identidad: se resuelve siempre por el ticker de la carpeta
    # contenedora, igual que el resto de la evidencia documental de esa empresa.
    if "taxonomias_xbrl_esef" not in file_path.parts:
        # 1. LEI embebido en el propio nombre de archivo (fuente más fiable para documentos
        #    propios de la empresa: cuentas, informes de gestión, ESEF principal, etc.)
        lei_match = LEI_IN_FILENAME_RE.search(file_path.name.upper())
        if lei_match and lei_match.group(1) in by_lei:
            ticker, info = by_lei[lei_match.group(1)]
            return ticker, info, "LEI_EN_NOMBRE_DE_ARCHIVO"

    # 2. Ticker de la carpeta contenedora (menos fiable, pero válido si está en catálogo).
    #    La carpeta puede venir en formato legado "{TICKER}_{Nombre_Empresa_SA}" o ya en
    #    formato canónico "{TICKER}-{CIF_NIF}"; el ticker es el primer token alfanumérico
    #    antes del primer separador ("_" o "-").
    folder_ticker = re.split(r"[_-]", company_folder, maxsplit=1)[0].upper()
    if folder_ticker in companies:
        return folder_ticker, companies[folder_ticker], "TICKER_DE_CARPETA"

    return None


def audit_tree(companies, by_lei) -> dict:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanned_files": 0,
        "by_hash": defaultdict(list),
        "resolved": [],
        "unresolved_entities": [],
        "already_correct": 0,
        "needs_move": [],
    }

    for file_path in RAW_ROOT.rglob("*"):
        if not file_path.is_file():
            continue
        if "_AUDIT_REPORTS" in file_path.parts or "quarantine" in str(file_path).lower():
            continue
        report["scanned_files"] += 1

        digest = sha256_of(file_path)
        report["by_hash"][digest].append(str(file_path))

        # Determinar prefijo/año/carpeta de empresa a partir de la ruta relativa.
        # El dataset real convive en dos layouts:
        #   data/raw/ES_CNMV/{YEAR}/{COMPANY}/...
        #   data/raw/ES_CNMV/{INFORMES_..._X}/{YEAR}/{COMPANY}/...
        try:
            rel = file_path.relative_to(RAW_ROOT)
        except ValueError:
            continue
        parts = rel.parts

        located = locate_year_and_company(parts)
        if located is None:
            continue  # no sigue ninguno de los esquemas soportados
        prefix_parts, year_part, company_folder = located

        resolved = resolve_identity(file_path, company_folder, companies, by_lei)
        if resolved is None:
            report["unresolved_entities"].append({
                "file": str(file_path),
                "year": year_part,
                "folder": company_folder,
            })
            continue

        ticker, info, method = resolved
        expected_dirname = canonical_dirname(ticker, info.get("cif_nif", ""))
        report["resolved"].append({
            "file": str(file_path),
            "prefix": list(prefix_parts),
            "year": year_part,
            "current_folder": company_folder,
            "resolved_ticker": ticker,
            "expected_folder": expected_dirname,
            "method": method,
        })

        if company_folder == expected_dirname:
            report["already_correct"] += 1
        else:
            report["needs_move"].append({
                "file": str(file_path),
                "prefix": list(prefix_parts),
                "year": year_part,
                "from_folder": company_folder,
                "to_folder": expected_dirname,
                "method": method,
            })

    def company_key(path_str: str) -> Optional[Tuple[str, ...]]:
        """(prefijo, year, company_folder) de una ruta bajo RAW_ROOT, o None si no aplica."""
        try:
            rel_parts = Path(path_str).relative_to(RAW_ROOT).parts
        except ValueError:
            return None
        located = locate_year_and_company(rel_parts)
        if located is None:
            return None
        prefix_parts, year_part, company_folder = located
        return (prefix_parts, year_part, company_folder)

    # Duplicados: mismo hash en más de un archivo.
    # IMPORTANTE: los ficheros de taxonomía XBRL/ESEF (.xsd, _cal.xml, _pre.xml, _def.xml,
    # _lab.xml, etc.) son EL MISMO estándar oficial y por diseño son byte-idénticos entre
    # TODAS las empresas: no son duplicados erróneos, son referencias legítimas al taxonomy
    # package de cada compañía. Solo se consideran "duplicado purgable" los grupos cuyo hash
    # se repite DENTRO de la misma empresa/año (copias accidentales), nunca entre empresas
    # distintas.
    all_groups = {h: paths for h, paths in report["by_hash"].items() if len(paths) > 1}
    purgeable_groups = {}
    shared_cross_company_groups = {}
    for digest, paths in all_groups.items():
        keys = {company_key(p) for p in paths}
        keys.discard(None)
        if len(keys) <= 1:
            # todas las copias pertenecen a la misma empresa/año -> duplicado accidental real
            purgeable_groups[digest] = paths
        else:
            # el mismo hash aparece en empresas distintas -> archivo de taxonomía/estándar
            # compartido legítimamente; se reporta mas NO se purga.
            shared_cross_company_groups[digest] = paths

    report["duplicate_groups"] = purgeable_groups
    report["shared_cross_company_files"] = shared_cross_company_groups
    report["duplicate_file_count"] = sum(len(v) - 1 for v in purgeable_groups.values())
    report["shared_cross_company_file_count"] = sum(len(v) for v in shared_cross_company_groups.values())
    del report["by_hash"]
    return report


def apply_moves(report: dict, keep_duplicates: bool = False) -> dict:
    """Ejecuta físicamente las reubicaciones y purga de duplicados detectados."""
    moved = []
    move_errors = []
    for item in report["needs_move"]:
        src = Path(item["file"])
        if not src.exists():
            continue
        prefix = Path(*item.get("prefix", []))
        base_from = RAW_ROOT / prefix / item["year"] / item["from_folder"]
        dest_dir = RAW_ROOT / prefix / item["year"] / item["to_folder"]
        # Preservar subestructura relativa dentro de la carpeta de empresa
        try:
            rel_within_company = src.relative_to(base_from)
        except ValueError:
            rel_within_company = Path(src.name)
        dest_path = dest_dir / rel_within_company
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dest_path.exists():
                # Ya existe en destino: no sobrescribir ciegamente, marcar para revisión
                move_errors.append({"file": str(src), "reason": "destino ya existe", "dest": str(dest_path)})
                continue
            shutil.move(str(src), str(dest_path))
            moved.append({"from": str(src), "to": str(dest_path)})
        except Exception as ex:
            move_errors.append({"file": str(src), "reason": str(ex)})

    purged = []
    if not keep_duplicates:
        for digest, paths in report["duplicate_groups"].items():
            existing = [Path(p) for p in paths if Path(p).exists()]
            if len(existing) <= 1:
                continue
            # Conservar el de ruta más corta (normalmente el mejor ubicado tras el move)
            existing.sort(key=lambda p: len(str(p)))
            keep = existing[0]
            for dup in existing[1:]:
                try:
                    dup.unlink()
                    purged.append({"kept": str(keep), "removed": str(dup)})
                except Exception as ex:
                    move_errors.append({"file": str(dup), "reason": f"no se pudo purgar duplicado: {ex}"})

    return {"moved": moved, "move_errors": move_errors, "purged_duplicates": purged}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Ejecuta los movimientos y purgas de verdad")
    parser.add_argument("--keep-duplicates", action="store_true", help="No purgar duplicados exactos")
    args = parser.parse_args()

    companies, by_lei = load_catalog()
    report = audit_tree(companies, by_lei)

    print(f"Archivos escaneados:        {report['scanned_files']}")
    print(f"Ya en carpeta correcta:     {report['already_correct']}")
    print(f"Requieren reubicación:      {len(report['needs_move'])}")
    print(f"Entidades sin resolver:     {len(report['unresolved_entities'])}")
    print(f"Grupos de duplicados reales (purgables): {len(report['duplicate_groups'])}")
    print(f"Archivos duplicados reales a purgar:     {report['duplicate_file_count']}")
    print(f"Grupos de taxonomía compartida (NO tocar): {len(report['shared_cross_company_files'])}")
    print(f"Archivos de taxonomía compartida:          {report['shared_cross_company_file_count']}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"IDENTITY_AUDIT_{ts}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReporte guardado en: {report_path}")

    if args.apply:
        print("\n--- APLICANDO REUBICACIONES Y PURGA DE DUPLICADOS ---")
        result = apply_moves(report, keep_duplicates=args.keep_duplicates)
        print(f"Movidos:              {len(result['moved'])}")
        print(f"Errores de movimiento:{len(result['move_errors'])}")
        print(f"Duplicados purgados:  {len(result['purged_duplicates'])}")
        result_path = REPORT_DIR / f"IDENTITY_REORG_APPLIED_{ts}.json"
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Reporte de aplicación guardado en: {result_path}")
    else:
        print("\n[DRY-RUN] No se movió ni borró nada. Usa --apply para ejecutar de verdad.")


if __name__ == "__main__":
    main()
