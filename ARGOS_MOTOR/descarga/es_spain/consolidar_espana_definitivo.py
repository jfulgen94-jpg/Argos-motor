"""
CONSOLIDACIÓN Y SANEAMIENTO DEFINITIVO DE ESPAÑA (CNMV) — ARGOS MOTOR
=====================================================================
Reorganiza y unifica todo el data lake de España en D:\\ARGOS_DATA\\raw\\ES_CNMV:
  1. Estructura canónica única: {AÑO} / {CIF}_{TICKER} / {archivos}
  2. Mapeo riguroso de CIFs desde master_universe_es.json.
  3. Integración de INFORMES_ANUALES_COMPLETOS en sus carpetas anuales correspondientes.
  4. Descarte absoluto de duplicados y purga de carpetas vacías.
  5. Verificación criptográfica SHA-256 y regeneración de MANIFEST_CNMV_{AÑO}.json.
"""

import sys
import os
import shutil
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(line_buffering=True)

def get_base_paths():
    repo_root = Path(__file__).resolve().parents[3]
    canonical_d = Path("D:/ARGOS_DATA/raw/ES_CNMV")
    if canonical_d.parent.exists():
        base_es = canonical_d
    else:
        base_es = repo_root / "data" / "raw" / "ES_CNMV"
        if not base_es.exists():
            base_es = repo_root / "ARGOS_MOTOR" / "data" / "raw" / "ES_CNMV"

    universe_path = repo_root / "ARGOS_MOTOR" / "config" / "master_universe_es.json"
    if not universe_path.exists():
        universe_path = Path("ARGOS_MOTOR/config/master_universe_es.json")
    return base_es, universe_path

BASE_ES, UNIVERSE_PATH = get_base_paths()

def calculate_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_universe_mapping():
    data = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8')).get('companies', {})
    cif_to_info = {}
    ticker_to_info = {}
    for c in data.values():
        if isinstance(c, dict):
            cif = c.get('cif_nif', '').replace('-', '').upper().strip()
            tick = c.get('ticker', '').upper().strip()
            name = c.get('name_legal', tick).replace('/', '_').replace('\\', '_')
            info = {'cif': cif, 'ticker': tick, 'name': name, 'lei': c.get('lei', '')}
            if cif:
                cif_to_info[cif] = info
            if tick:
                ticker_to_info[tick] = info
    return cif_to_info, ticker_to_info

def clean_empty_folders(root_dir: Path):
    removed = 0
    for current_root, dirs, files in list(os.walk(root_dir, topdown=False)):
        p = Path(current_root)
        if p == root_dir:
            continue
        try:
            if not any(p.iterdir()):
                p.rmdir()
                removed += 1
        except Exception:
            pass
    return removed

def consolidate():
    print("=========================================================================")
    print("=== CONSOLIDACIÓN Y NORMALIZACIÓN DEFINITIVA ESPAÑA (CNMV) ===")
    print("=========================================================================")
    cif_to_info, ticker_to_info = get_universe_mapping()
    print(f"Universo cargado: {len(cif_to_info)} CIFs mapeados.")
    if not BASE_ES.exists():
        BASE_ES.mkdir(parents=True, exist_ok=True)
        print(f"Directorio base inicializado: {BASE_ES}")

    # 1. Integrar INFORMES_ANUALES_COMPLETOS
    iac_dir = BASE_ES / "INFORMES_ANUALES_COMPLETOS"
    if iac_dir.exists():
        print("\n--- Integrando INFORMES_ANUALES_COMPLETOS a la estructura canónica ---")
        for yr_dir in iac_dir.iterdir():
            if not yr_dir.is_dir() or not yr_dir.name.isdigit():
                continue
            yr = yr_dir.name
            for comp_dir in yr_dir.iterdir():
                if not comp_dir.is_dir():
                    continue
                dname = comp_dir.name.upper().replace('_', '-')
                # Extraer ticker o CIF de nombres como ADX-A-62338827 o SAN-A39000013
                parts = dname.split('-')
                cand_ticker = parts[0].strip()
                cand_cif = "".join(parts[1:]).replace('-', '').strip()
                
                info = ticker_to_info.get(cand_ticker) or cif_to_info.get(cand_cif)
                if info:
                    cif = info['cif']
                    tick = info['ticker']
                else:
                    cif = cand_cif or "UNKNOWN"
                    tick = cand_ticker or "UNKNOWN"

                dest_dir = BASE_ES / yr / f"{cif}_{tick}"
                dest_dir.mkdir(parents=True, exist_ok=True)

                for f in comp_dir.iterdir():
                    if f.is_file():
                        target = dest_dir / f.name
                        if not target.exists():
                            shutil.move(str(f), str(target))
                        elif target.stat().st_size < f.stat().st_size:
                            target.unlink()
                            shutil.move(str(f), str(target))
                        else:
                            f.unlink()

        # Eliminar carpeta de origen una vez migrada
        shutil.rmtree(iac_dir, ignore_errors=True)
        print(" [OK] INFORMES_ANUALES_COMPLETOS integrados y eliminados de raíz.")

    # 2. Reorganizar carpetas {AÑO} / {CIF}_{CIF} a {AÑO} / {CIF}_{TICKER}
    print("\n--- Normalizando nombres de carpetas de entidad a {CIF}_{TICKER} ---")
    years = [d for d in BASE_ES.iterdir() if d.is_dir() and d.name.isdigit()]
    renamed = 0

    for yr_dir in years:
        for c_dir in list(yr_dir.iterdir()):
            if not c_dir.is_dir():
                continue
            name_parts = c_dir.name.split('_')
            cif_cand = name_parts[0].upper().replace('-', '').strip()
            
            info = cif_to_info.get(cif_cand)
            if info:
                tick = info['ticker']
                canonical_name = f"{cif_cand}_{tick}"
            else:
                canonical_name = c_dir.name

            target_dir = yr_dir / canonical_name
            if target_dir != c_dir:
                target_dir.mkdir(parents=True, exist_ok=True)
                for f in c_dir.iterdir():
                    if f.is_file():
                        target_f = target_dir / f.name
                        if not target_f.exists() or target_f.stat().st_size < f.stat().st_size:
                            shutil.move(str(f), str(target_f))
                        else:
                            f.unlink()
                try:
                    c_dir.rmdir()
                except Exception:
                    pass
                renamed += 1

    print(f" [OK] Carpetas renombradas/consolidadas: {renamed}")

    # 3. Eliminar carpetas vacías
    removed_empty = clean_empty_folders(BASE_ES)
    print(f" [OK] Carpetas vacías eliminadas: {removed_empty}")

    # 4. Generar Manifiestos Anuales Oficiales de España
    print("\n--- Generando Manifiestos Anuales Oficiales CNMV ---")
    years = sorted([d.name for d in BASE_ES.iterdir() if d.is_dir() and d.name.isdigit()])
    total_docs = 0

    for yr in years:
        yr_dir = BASE_ES / yr
        manifest_file = BASE_ES / f"MANIFEST_CNMV_{yr}.json"
        filings = []

        for entity_dir in sorted(yr_dir.iterdir()):
            if not entity_dir.is_dir():
                continue
            parts = entity_dir.name.split('_')
            cif = parts[0]
            ticker = parts[1] if len(parts) > 1 else cif
            info = cif_to_info.get(cif, {})

            for f in sorted(entity_dir.iterdir()):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in ['.zip', '.pdf', '.xhtml']:
                    continue
                
                sz = f.stat().st_size
                sha = calculate_sha256(f)
                doc_type = "ESEF_ZIP" if f.suffix.lower() == '.zip' else "AUDIT_PDF"
                
                filings.append({
                    "ticker": ticker,
                    "cif": cif,
                    "company_name": info.get('name', ticker),
                    "lei": info.get('lei'),
                    "year": int(yr),
                    "file_name": f.name,
                    "rel_path": f"{yr}/{entity_dir.name}/{f.name}",
                    "doc_type": doc_type,
                    "size_bytes": sz,
                    "size_mb": round(sz / (1024 * 1024), 2),
                    "sha256": sha
                })

        manifest_data = {
            "year": int(yr),
            "jurisdiction": "ES",
            "supervisor": "CNMV",
            "total_filings": len(filings),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "filings": filings
        }
        manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding='utf-8')
        total_docs += len(filings)
        print(f"  [DOC] Manifiesto CNMV {yr}: {manifest_file.name} ({len(filings)} filings)")

    print(f"\n=========================================================================")
    print(f"=== CONSOLIDACIÓN COMPLETADA: {total_docs} DOCUMENTOS LEGÍTIMOS SELLADOS ===")
    print(f"=========================================================================")

if __name__ == '__main__':
    consolidate()
