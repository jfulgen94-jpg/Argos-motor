"""
Script integral y universal de descompresión y sellado criptográfico SHA-256.
Procesa:
1. IBEX 35
2. Todo el Mercado Continuo Español (~130 empresas, 2020-2024)
3. BME Growth (Clean Universe)
4. Ejercicios Especiales 2025+ (eDreams, etc.)

Lee los metadatos .meta.json adjuntos a cada bundle descargado para obtener
denominación social y ticker exacto, omite los ya sellados y desempaqueta
todos los pendientes en data/raw/ES_CNMV/{AÑO}/{TICKER}_{EMPRESA}/.
"""

import sys, os, io, json, hashlib, zipfile, shutil, re
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

WORKSPACE_ROOT = Path(r"c:\Users\jfulg\Desktop\Stater")
BASE_RAW = WORKSPACE_ROOT / "ARGOS_MOTOR" / "data" / "raw"
TARGET_DIR = BASE_RAW / "ES_CNMV"

def calc_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()

def find_all_zips():
    found = []
    for z in WORKSPACE_ROOT.rglob("*.zip"):
        if "__MACOSX" in str(z):
            continue
        found.append(z)
    return sorted(found)

def get_bundle_metadata(zip_path: Path):
    """
    Intenta extraer ticker, company_name y año desde:
    1. Archivo .meta.json adyacente
    2. Nombre del archivo y partes de la ruta
    """
    ticker = None
    year = None
    company_name = None
    
    # 1. Buscar .meta.json adyacente
    meta_path = zip_path.with_suffix('.meta.json')
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as mf:
                mdata = json.load(mf)
            ticker = mdata.get("ticker")
            company_name = mdata.get("company_name") or mdata.get("entity_name")
            year = str(mdata.get("year")) if mdata.get("year") else None
        except:
            pass
            
    # 2. Extraer año de la ruta si no se obtuvo
    path_str = str(zip_path).replace("\\", "/")
    if not year:
        year_match = re.search(r'\b(2019|2020|2021|2022|2023|2024|2025|2026)\b', path_str)
        year = year_match.group(1) if year_match else None

    # 3. Extraer ticker del nombre si no se obtuvo
    if not ticker:
        name = zip_path.name
        prefix_match = re.match(r'^([a-zA-Z0-9]+)_(\d{4})_', name)
        if prefix_match:
            cand = prefix_match.group(1).upper()
            if cand not in ["IPP", "DATA", "ES"]:
                ticker = cand
                
    if not ticker:
        parent_dir = zip_path.parent.name.upper()
        if len(parent_dir) <= 6 and not parent_dir.isdigit() and parent_dir != "BME_GROWTH":
            ticker = parent_dir
            
    if not company_name:
        if ticker:
            company_name = f"{ticker}_SA"
        else:
            company_name = zip_path.stem

    # Limpieza de nombre de carpeta
    clean_company = re.sub(r'[^a-zA-Z0-9_]', '_', company_name.replace(' ', '_')).strip('_')
    
    return ticker or "DESCONOCIDO", year or "2024", clean_company

def process_all_zip_bundles():
    all_zips = find_all_zips()
    print(f"Total ZIPs encontrados en workspace: {len(all_zips)}\n")
    
    results = []
    processed_count = 0
    unpacked_new = 0
    
    for zip_path in all_zips:
        size_bytes = zip_path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        
        # Ignorar archivos diminutos que no son reportes
        if size_bytes < 50000 and "ipp_" not in zip_path.name:
            continue
            
        zip_sha256 = calc_sha256(zip_path)
        ticker, year, company_name = get_bundle_metadata(zip_path)
        name = zip_path.name.lower()
        
        is_esef_bundle = size_mb > 0.3 and ("bundle" in name or "esef" in name or ticker != "DESCONOCIDO" or "landing_raw" in str(zip_path))
        
        zip_info = {
            "source_path": str(zip_path),
            "filename": zip_path.name,
            "size_bytes": size_bytes,
            "size_mb": round(size_mb, 2),
            "sha256": zip_sha256,
            "ticker": ticker,
            "year": year,
            "company_name": company_name,
            "is_esef_bundle": is_esef_bundle,
            "extracted_files": []
        }
        
        processed_count += 1
        
        if is_esef_bundle and year:
            company_folder_name = f"{ticker}_{company_name}"
            dest_dir = TARGET_DIR / year / company_folder_name / "extracted"
            manifest_path = TARGET_DIR / year / company_folder_name / f"{ticker.lower()}_{year}_extracted_manifest.json"
            
            # Comprobar si ya estaba descomprimido y sellado
            if manifest_path.exists() and dest_dir.exists() and any(dest_dir.iterdir()):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        cached_data = json.load(mf)
                    zip_info["extracted_files"] = cached_data.get("files", [])
                    print(f"📦 [{processed_count}/{len(all_zips)}] {ticker} ({year}) — ⏭ Ya procesado y sellado ({len(zip_info['extracted_files'])} archivos)")
                    results.append(zip_info)
                    continue
                except:
                    pass
            
            print(f"📦 [{processed_count}/{len(all_zips)}] {ticker} ({year}) — Descomprimiendo {zip_path.name} ({size_mb:.2f} MB)...")
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Descomprimir directamente sin duplicar el archivo ZIP en disco
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    for member in zf.infolist():
                        if member.is_dir():
                            continue
                        target_file_path = dest_dir / member.filename
                        target_file_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        with zf.open(member) as source, open(target_file_path, "wb") as target:
                            shutil.copyfileobj(source, target)
                        
                        f_size = target_file_path.stat().st_size
                        f_sha256 = calc_sha256(target_file_path)
                        
                        zip_info["extracted_files"].append({
                            "relative_path": member.filename,
                            "full_path": str(target_file_path),
                            "size_bytes": f_size,
                            "size_kb": round(f_size / 1024, 2),
                            "sha256": f_sha256
                        })
                        
                unpacked_new += 1
                print(f"   ✓ Descomprimido en: {dest_dir} ({len(zip_info['extracted_files'])} archivos)")
                
                manifest_data = {
                    "ticker": ticker,
                    "company_name": company_name,
                    "year": int(year) if year.isdigit() else year,
                    "bundle_zip": {
                        "filename": zip_path.name,
                        "canonical_path": str(zip_path),
                        "sha256": zip_sha256,
                        "size_bytes": size_bytes,
                        "size_mb": round(size_mb, 2)
                    },
                    "extracted_directory": str(dest_dir),
                    "extracted_count": len(zip_info["extracted_files"]),
                    "files": zip_info["extracted_files"],
                    "processed_at": datetime.now(timezone.utc).isoformat()
                }
                
                with open(manifest_path, "w", encoding="utf-8") as mf:
                    json.dump(manifest_data, mf, indent=2, ensure_ascii=False)
                
            except Exception as e:
                print(f"   ✗ Error descomprimiendo: {e}")
                zip_info["error"] = str(e)
                
        results.append(zip_info)
        
    global_report_path = TARGET_DIR / "ORGANIZED_INVENTORY_SHA256.json"
    with open(global_report_path, "w", encoding="utf-8") as gf:
        json.dump(results, gf, indent=2, ensure_ascii=False)
        
    print(f"\n" + "=" * 70)
    print(f"✅ DESCOMPRESIÓN Y SELLADO UNIVERSAL FINALIZADO")
    print(f"  ✓ Nuevos paquetes extraídos: {unpacked_new}")
    print(f"  ✓ Total paquetes en inventario: {len(results)}")
    print(f"  📄 Inventario global consolidado: {global_report_path}")
    print("=" * 70)
    return results

if __name__ == "__main__":
    process_all_zip_bundles()
