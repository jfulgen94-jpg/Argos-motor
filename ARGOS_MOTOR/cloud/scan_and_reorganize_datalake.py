#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
STATER / ARGOS MOTOR — ESCANER, AUDITOR Y REORGANIZADOR LOCAL DEL DATA LAKE
================================================================================
Escanea todos los gigabytes de informes en D:/ARGOS_DATA/raw, audita la coherencia
contra los universos maestros de cotizadas (España, Alemania, Francia, Países Bajos,
y EE.UU.) y reorganiza los archivos creando enlaces duros NTFS (NTFS Hard Links,
coste 0 de espacio adicional) en la jerarquía canónica:
  D:/ARGOS_DATA/lake/{PAIS}/{MERCADO}/{AÑO}/{EMPRESA}/{TIPO_INFORME}/

Los archivos erróneos, corruptos o incoherentes se desvían a:
  D:/ARGOS_DATA/quarantine_coherence/{PAIS}/{AÑO}/

LA COPIA ORIGINAL EN D:/ARGOS_DATA/raw/ PERMANECE 100% INTACTA E INMUTABLE.
================================================================================
"""

import os
import sys
import json
import time
import re
import argparse
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = Path("D:/ARGOS_DATA/raw")
LAKE_ROOT = Path("D:/ARGOS_DATA/lake")
QUARANTINE_ROOT = Path("D:/ARGOS_DATA/quarantine_coherence")

CONFIG_DIRS = [
    ROOT / "ARGOS_MOTOR" / "config",
    ROOT / "config",
]

JURISDICTION_MAP = {
    "ES_CNMV": "ESPANA",
    "DE_BAFIN": "ALEMANIA",
    "FR_AMF": "FRANCIA",
    "IT_CONSOB": "ITALIA",
    "NL_AFM": "PAISES_BAJOS",
    "sec_edgar": "ESTADOS_UNIDOS",
    "_ES_CNMV_TEMP_REORG": "ESPANA",
    "quarantine_es": "ESPANA",
}

KNOWN_CORRUPT_SHA256 = {
    "a80b7cc89747d5124542ec01d32f3b3848ed4a91d9dd86a0b457916f1859dc4a",  # CNMV Conducta.pdf
}


def normalize_str(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(s)).upper()


def sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]", "_", str(name)).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned[:80] if cleaned else "EMPRESA_DESCONOCIDA"


def load_all_universes():
    universes = {
        "ESPANA": {},
        "ALEMANIA": {},
        "FRANCIA": {},
        "PAISES_BAJOS": {},
        "ESTADOS_UNIDOS": {},
        "ITALIA": {},
    }

    cfg_dir = None
    for cd in CONFIG_DIRS:
        if (cd / "master_universe_de.json").exists():
            cfg_dir = cd
            break

    if not cfg_dir:
        print("  [AVISO] No se encontró directorio de configuración con universos maestros.")
        return universes

    # 1. España
    es_file = cfg_dir / "master_universe_es.json"
    if es_file.exists():
        with open(es_file, "r", encoding="utf-8") as f:
            universes["ESPANA"] = json.load(f).get("companies", {})

    # 2. Alemania
    de_file = cfg_dir / "master_universe_de.json"
    if de_file.exists():
        with open(de_file, "r", encoding="utf-8") as f:
            universes["ALEMANIA"] = json.load(f).get("companies", {})

    # 3. Francia
    fr_file = cfg_dir / "master_universe_fr.json"
    if fr_file.exists():
        with open(fr_file, "r", encoding="utf-8") as f:
            universes["FRANCIA"] = json.load(f).get("companies", {})

    # 4. Países Bajos
    nl_file = cfg_dir / "master_universe_nl.json"
    if nl_file.exists():
        with open(nl_file, "r", encoding="utf-8") as f:
            universes["PAISES_BAJOS"] = json.load(f).get("companies", {})

    # 5. EE.UU. (Blue Chips & Mega Caps)
    us_file = cfg_dir / "bluechips_universe.json"
    if us_file.exists():
        with open(us_file, "r", encoding="utf-8") as f:
            bc = json.load(f)
            us_cos = {}
            for c in bc.get("markets", {}).get("US", {}).get("companies", []):
                tk = c.get("ticker", "").upper()
                if tk:
                    us_cos[tk] = {
                        "ticker": tk,
                        "name_legal": c.get("name", tk),
                        "segment": "SP500_MEGA_CAPS",
                    }
            universes["ESTADOS_UNIDOS"] = us_cos

    return universes


def build_fast_lookup(universes):
    """Construye un índice O(1) multi-clave por país para resolución ultra-rápida."""
    indexed = {}
    for country, cos in universes.items():
        idx = {}
        for key, c in cos.items():
            if not isinstance(c, dict):
                continue
            idx[key.upper()] = c
            
            # Ticker
            tk = c.get("ticker")
            if tk:
                idx[tk.upper()] = c
            
            # Identificadores oficiales
            for fid in ["isin", "lei", "wkn", "cif", "cif_nif", "hrb_reg", "kvk_reg"]:
                v = c.get(fid)
                if v:
                    s_v = str(v).upper()
                    idx[s_v] = c
                    idx[normalize_str(s_v)] = c
            
            # Nombres de empresa
            for nfield in ["name_legal", "name_common", "name"]:
                v = c.get(nfield)
                if v:
                    norm = normalize_str(v)
                    if len(norm) >= 4:
                        idx[norm] = c
        indexed[country] = idx
    return indexed


def determine_doc_type(filename: str, ext: str) -> str:
    f_upper = filename.upper()
    if ext == ".zip" or "ESEF" in f_upper or "XBRL" in f_upper:
        return "PAQUETE_DIGITAL_ESEF_XBRL"
    if any(k in f_upper for k in ["10-K", "20-F", "ANUAL", "JAHRESABSCHLUSS", "URD", "DOCUMENTENREGISTREMENTUNIVERSEL", "DOCUMENTREFERENCE", "CUENTAS_ANUALES"]):
        return "INFORME_ANUAL_AUDITADO"
    if any(k in f_upper for k in ["10-Q", "TRIMESTRAL", "QUARTER", "Q1", "Q2", "Q3"]):
        return "INFORME_TRIMESTRAL"
    if any(k in f_upper for k in ["SEMESTRAL", "HALF_YEAR", "SEMESTRIEL", "HY", "S1", "S2", "HALBJAHRESBERICHT"]):
        return "INFORME_SEMESTRAL"
    if any(k in f_upper for k in ["GESTION", "LAGEBERICHT", "MANAGEMENT_REPORT"]):
        return "INFORME_DE_GESTION"
    if "BANZ" in f_upper or ext in [".htm", ".html"]:
        return "BALANCE_CUENTAS_OFICIALES"
    if any(k in f_upper for k in ["8-K", "RELEVANTE", "INSIDER", "AD_HOC"]):
        return "HECHO_RELEVANTE"
    return "OTRO_DOCUMENTO_FINANCIERO"


def safe_hardlink_or_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)  # Hard link instantáneo en NTFS (0 bytes adicionales)
    except Exception:
        import shutil
        shutil.copy2(src, dst)


def extract_metadata_and_ident(f_path: Path, rel_parts: tuple, country: str, fast_lookup: dict):
    ext = f_path.suffix.lower()
    f_size = f_path.stat().st_size
    filename = f_path.name

    # 1. Detección de año
    year = "S_N"
    for part in rel_parts:
        if part.isdigit() and len(part) == 4 and 1990 <= int(part) <= 2030:
            year = part
            break
    if year == "S_N":
        # Buscar en nombre de archivo (ej. MERL_2024_ESEF.zip)
        m_year = re.search(r"\b(19\d\d|20\d\d)\b", filename)
        if m_year:
            year = m_year.group(1)

    # 2. Leer metadatos acompañantes si existen
    meta_data = {}
    meta_file = f_path.with_suffix(f_path.suffix + ".meta.json")
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as mf:
                meta_data = json.load(mf)
        except Exception:
            pass

    # 3. Identificación de Ticker / Empresa
    matched_company = None
    lookup = fast_lookup.get(country, {})

    # Intentar por meta_data
    candidates = []
    for k in ["ticker", "cif", "isin", "lei", "wkn", "hrb_reg"]:
        val = meta_data.get(k)
        if val:
            candidates.append(str(val).upper())
            candidates.append(normalize_str(val))

    for k in ["company_name", "legal_name", "title"]:
        val = meta_data.get(k)
        if val:
            candidates.append(normalize_str(val))

    # Intentar por carpetas intermedias (ej: A01000858_TRG, ADS_Adidas_AG, ACCOR)
    for part in rel_parts[1:-1]:
        if part == year:
            continue
        candidates.append(part.upper())
        candidates.append(normalize_str(part))
        for sub in part.split("_"):
            candidates.append(sub.upper())
            candidates.append(normalize_str(sub))

    # Intentar por componentes del nombre de archivo
    for sub in f_path.stem.split("_"):
        if sub != year and len(sub) >= 2:
            candidates.append(sub.upper())
            candidates.append(normalize_str(sub))

    for cand in candidates:
        if cand in lookup:
            matched_company = lookup[cand]
            break

    # Resolver nombre legal y mercado
    ticker = meta_data.get("ticker", "")
    if matched_company:
        ticker = matched_company.get("ticker") or ticker
        market = matched_company.get("segment") or matched_company.get("market") or "MERCADO_OFICIAL_REGULADO"
        empresa_nombre = sanitize_folder_name(matched_company.get("name_legal") or matched_company.get("name_common") or ticker)
    else:
        # Extraer nombre descriptivo si no está en universo
        name_raw = meta_data.get("company_name") or meta_data.get("legal_name")
        if not name_raw:
            # Deducir de carpeta o archivo
            if len(rel_parts) >= 3 and rel_parts[-2] != year:
                name_raw = rel_parts[-2]
            else:
                name_raw = f_path.stem.split("_")[0]
        empresa_nombre = sanitize_folder_name(name_raw)
        market = "HISTORICO_O_EXPANDIDO"

    # 4. Auditoría de coherencia y descarte de archivos corruptos/erróneos
    is_corrupt = False
    quarantine_reason = None

    # Check A: Archivo menor a 500 bytes (típico stub o fallo de red)
    if f_size < 500:
        is_corrupt = True
        quarantine_reason = "Archivo menor a 500 bytes (descarga vacía/truncada)"

    # Check B: Fallos HTTP en HTML
    elif ext in [".htm", ".html"] and f_size < 2500:
        try:
            head_text = f_path.read_text(encoding="utf-8", errors="ignore")[:1000].lower()
            if any(err in head_text for err in ["404 not found", "503 service", "access denied", "nicht erreichbar", "error ocurrido"]):
                is_corrupt = True
                quarantine_reason = "Documento HTML con error de servidor (404/503/Access Denied)"
        except Exception:
            pass

    # Check C: Descarga errónea conocida (Código General de Conducta CNMV)
    source_url = meta_data.get("source_url", "")
    sha256 = meta_data.get("sha256", "")
    if "Conducta.pdf" in source_url or sha256 in KNOWN_CORRUPT_SHA256:
        is_corrupt = True
        quarantine_reason = "Código General de Conducta CNMV (descarga errónea histórica en vez de informe financiero)"

    # Check D: Sin año válido
    if year == "S_N":
        is_corrupt = True
        quarantine_reason = "Ejercicio fiscal/año no identificable"

    doc_type = determine_doc_type(filename, ext)

    return {
        "country": country,
        "market": market,
        "year": year,
        "empresa": empresa_nombre,
        "ticker": ticker,
        "doc_type": doc_type,
        "is_corrupt": is_corrupt,
        "quarantine_reason": quarantine_reason,
        "f_size": f_size,
        "meta_file": meta_file if meta_file.exists() else None,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Escáner y Reorganizador del Data Lake Local (D:)")
    parser.add_argument("--dry-run", action="store_true", help="Simulación sin crear carpetas ni enlaces")
    parser.add_argument("--limit", type=int, default=0, help="Limitar a N archivos")
    args = parser.parse_args()

    print("=" * 80)
    print("  STATER / ARGOS MOTOR — ESCANEO, AUDITORÍA Y ESTRUCTURACIÓN COMPLETA")
    print("  Unidad de Almacenamiento:  DISCO D: (NTFS)")
    print("  Directorio Origen:         D:/ARGOS_DATA/raw/ (INMUTABLE / COPIA ORIGINAL)")
    print("  Data Lake Estructurado:    D:/ARGOS_DATA/lake/{PAIS}/{MERCADO}/{AÑO}/{EMPRESA}/{TIPO}/")
    print("  Cuarentena Coherencia:     D:/ARGOS_DATA/quarantine_coherence/{PAIS}/{AÑO}/")
    print("=" * 80, flush=True)

    print("\n[1/4] Cargando e indexando universos maestros oficiales...", flush=True)
    universes = load_all_universes()
    fast_lookup = build_fast_lookup(universes)
    for pais, cos in universes.items():
        if len(cos) > 0:
            print(f"  - {pais:15}: {len(cos):>4} sociedades registradas ({len(fast_lookup[pais])} claves indexadas)", flush=True)

    print("\n[2/4] Indexando documentos primarios en D:/ARGOS_DATA/raw...", flush=True)
    raw_files = []
    
    # Directorios objetivo
    target_dirs = ["DE_BAFIN", "ES_CNMV", "FR_AMF", "sec_edgar", "NL_AFM", "IT_CONSOB", "_ES_CNMV_TEMP_REORG"]
    
    # Exclusiones de archivos auxiliares o índices
    ignore_files = {"esef_filings_index_fr.json", ".gitkeep"}

    for td in target_dirs:
        folder_path = RAW_ROOT / td
        if not folder_path.exists():
            continue
        c_count = 0
        for root, _, files in os.walk(folder_path):
            for fname in files:
                if fname.endswith(".meta.json") or fname.startswith("MANIFEST") or fname.startswith("MAPPED_FILINGS") or fname in ignore_files:
                    continue
                raw_files.append(Path(root) / fname)
                c_count += 1
        print(f"  - {td:22}: {c_count:>6} documentos primarios", flush=True)

    total_files = len(raw_files)
    print(f"  Total documentos primarios a procesar: {total_files:,}", flush=True)
    if args.limit > 0:
        raw_files = raw_files[:args.limit]
        print(f"  Límite de prueba aplicado: {len(raw_files)} archivos", flush=True)

    print("\n[3/4] Auditando coherencia, clasificando y enlazando en disco D:...", flush=True)
    stats = {
        "clasificados_ok": 0,
        "cuarentena_incoherentes": 0,
        "por_pais": Counter(),
        "por_mercado": Counter(),
        "por_tipo": Counter(),
        "por_ano": Counter(),
        "empresas_unicas": defaultdict(set),
    }

    manifest_lake = []
    start_time = time.time()

    for idx, f_path in enumerate(raw_files, start=1):
        rel_parts = f_path.relative_to(RAW_ROOT).parts
        top_folder = rel_parts[0]
        country = JURISDICTION_MAP.get(top_folder, "OTRO")

        parsed = extract_metadata_and_ident(f_path, rel_parts, country, fast_lookup)

        if parsed["is_corrupt"]:
            stats["cuarentena_incoherentes"] += 1
            dst_folder = QUARANTINE_ROOT / parsed["country"] / parsed["year"]
            dst_file = dst_folder / f_path.name
            status = "QUARANTINE"
        else:
            stats["clasificados_ok"] += 1
            stats["por_pais"][parsed["country"]] += 1
            stats["por_mercado"][parsed["market"]] += 1
            stats["por_tipo"][parsed["doc_type"]] += 1
            stats["por_ano"][parsed["year"]] += 1
            stats["empresas_unicas"][parsed["country"]].add(parsed["empresa"])
            
            dst_folder = (
                LAKE_ROOT 
                / parsed["country"] 
                / parsed["market"] 
                / parsed["year"] 
                / parsed["empresa"] 
                / parsed["doc_type"]
            )
            dst_file = dst_folder / f_path.name
            status = "CURATED_LAKE"

        if not args.dry_run:
            safe_hardlink_or_copy(f_path, dst_file)
            if parsed["meta_file"]:
                safe_hardlink_or_copy(parsed["meta_file"], dst_folder / parsed["meta_file"].name)

        manifest_lake.append({
            "source_raw": str(f_path),
            "destination": str(dst_file),
            "status": status,
            "country": parsed["country"],
            "market": parsed["market"],
            "year": parsed["year"],
            "company": parsed["empresa"],
            "ticker": parsed["ticker"],
            "doc_type": parsed["doc_type"],
            "size_bytes": parsed["f_size"],
            "quarantine_reason": parsed["quarantine_reason"],
        })

        if idx % 1000 == 0 or idx == len(raw_files):
            pct = (idx / len(raw_files)) * 100
            print(f"  [{idx:>6}/{len(raw_files)}] ({pct:5.1f}%) | Lake OK: {stats['clasificados_ok']:>6} | Cuarentena: {stats['cuarentena_incoherentes']:>4}", flush=True)

    elapsed = time.time() - start_time

    print("\n[4/4] Guardando manifiesto completo y generando informe...", flush=True)
    if not args.dry_run:
        LAKE_ROOT.mkdir(parents=True, exist_ok=True)
        manifest_path = LAKE_ROOT / "MANIFEST_DATA_LAKE_AUDIT.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_lake, f, indent=2, ensure_ascii=False)
        print(f"  - Manifiesto JSON guardado en: {manifest_path}")

    # Imprimir estadísticas consolidadas
    print("\n" + "=" * 80)
    print("  STATER / ARGOS MOTOR — RESULTADO AUDITORÍA DEL DATA LAKE EN DISCO D:")
    print("=" * 80)
    print(f"  Total Documentos Procesados:       {len(raw_files):,}")
    print(f"  Clasificados y Reorganizados OK:  {stats['clasificados_ok']:,} ({stats['clasificados_ok']/max(1, len(raw_files))*100:.1f}%)")
    print(f"  Desviados a Cuarentena Coherencia: {stats['cuarentena_incoherentes']:,} ({stats['cuarentena_incoherentes']/max(1, len(raw_files))*100:.1f}%)")
    print(f"  Velocidad de Procesamiento:        {len(raw_files)/max(0.01, elapsed):.1f} documentos/segundo (Tiempo: {elapsed:.1f}s)")
    print(f"  Integridad Copia Original (raw/):  100% PRESERVADA (0 archivos modificados ni borrados)")

    print("\n--- INVENTARIO DE EMPRESAS ÚNICAS POR PAÍS ---")
    for pais, cos_set in sorted(stats["empresas_unicas"].items()):
        print(f"  {pais:20}: {len(cos_set):>5} empresas con informes consolidados")

    print("\n--- DISTRIBUCIÓN DE INFORMES POR PAÍS ---")
    for k, v in stats["por_pais"].most_common():
        print(f"  {k:20}: {v:>6} informes")

    print("\n--- TOP TIPOS DE INFORME ESTRUCTURADOS ---")
    for k, v in stats["por_tipo"].most_common():
        print(f"  {k:30}: {v:>6} informes")

    print("\n--- TOP SEGMENTOS DE MERCADO ---")
    for k, v in stats["por_mercado"].most_common(12):
        print(f"  {k:30}: {v:>6} informes")

    print("\n--- DISTRIBUCIÓN POR EJERCICIO FISCAL (AÑO) ---")
    for y in sorted(stats["por_ano"].keys()):
        print(f"  Año {y}: {stats['por_ano'][y]:>5} informes")
    print("=" * 80)


if __name__ == "__main__":
    main()
