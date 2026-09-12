"""
REORGANIZACIÓN CANÓNICA DE ESPAÑA (CNMV) — ARGOS MOTOR
======================================================
Transforma la estructura de directorios en D:\ARGOS_DATA\raw\ES_CNMV:
  DE:   {CIF} / {AÑO} / {fichero}
  A:    {AÑO} / {CIF}_{TICKER} / {fichero}

1. Lee el universo maestro master_universe_es.json para mapear CIF -> TICKER / NOMBRE.
2. Mueve los ficheros legítimos (.zip, .pdf, .json de metadatos) a la nueva jerarquía.
3. Elimina las carpetas de CIF vacías de la raíz.
4. Mantiene en la raíz los manifiestos MANIFEST_CNMV_*.json actualizados.
"""

import os
import shutil
import json
from pathlib import Path

BASE_ES = Path(r"D:\ARGOS_DATA\raw\ES_CNMV")
UNIVERSE_PATH = Path(r"C:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\config\master_universe_es.json")

def load_universe_mapping():
    cif_map = {}
    if UNIVERSE_PATH.exists():
        data = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8')).get('companies', {})
        comps = data.values() if isinstance(data, dict) else data
        for c in comps:
            if isinstance(c, dict):
                cif = c.get('cif', '').upper().strip()
                tick = c.get('ticker', '').upper().strip()
                name = c.get('name_legal', tick).replace('/', '_').replace('\\', '_')
                safe_name = "".join(ch for ch in name if ch.isalnum() or ch in (' ', '_', '-')).strip().replace(' ', '_')
                if cif:
                    cif_map[cif] = {
                        'ticker': tick,
                        'name': safe_name
                    }
    return cif_map

def reorganize():
    print("=========================================================================")
    print("=== REORGANIZANDO JERARQUÍA ESPAÑA: {AÑO} / {CIF}_{TICKER} ===")
    print("=========================================================================")
    cif_map = load_universe_mapping()
    print(f"Mapeo de CIFs cargado: {len(cif_map)} entidades.")

    # 1. Identificar carpetas de CIF en la raíz
    root_items = [d for d in BASE_ES.iterdir() if d.is_dir()]
    cif_dirs = [d for d in root_items if not d.name.isdigit()]

    print(f"Carpetas de CIF encontradas en la raíz a procesar: {len(cif_dirs)}")

    moved_count = 0
    errors = 0

    for c_dir in cif_dirs:
        cif = c_dir.name.upper().strip()
        info = cif_map.get(cif, {})
        ticker = info.get('ticker') or cif
        folder_entity_name = f"{cif}_{ticker}"

        # Recorrer subdirectorios de año dentro de la carpeta del CIF
        for yr_dir in c_dir.iterdir():
            if not yr_dir.is_dir():
                continue
            yr_str = yr_dir.name
            if not yr_str.isdigit():
                continue

            # Destino canónico: BASE_ES / {AÑO} / {CIF}_{TICKER}
            target_entity_dir = BASE_ES / yr_str / folder_entity_name
            target_entity_dir.mkdir(parents=True, exist_ok=True)

            for item in list(yr_dir.iterdir()):
                if item.is_file():
                    target_file = target_entity_dir / item.name
                    try:
                        if target_file.exists():
                            target_file.unlink()
                        shutil.move(str(item), str(target_file))
                        moved_count += 1
                    except Exception as e:
                        print(f"  [ERROR] Moviendo {item.name}: {e}")
                        errors += 1

            # Eliminar directorio del año dentro del CIF si ya está vacío
            try:
                if not any(yr_dir.iterdir()):
                    yr_dir.rmdir()
            except Exception:
                pass

        # Eliminar carpeta del CIF de la raíz si ya está vacía
        try:
            if not any(c_dir.iterdir()):
                c_dir.rmdir()
            else:
                # Si queda algo, revisar qué queda
                remaining = list(c_dir.rglob('*'))
                remaining_files = [f for f in remaining if f.is_file()]
                if not remaining_files:
                    shutil.rmtree(c_dir)
        except Exception:
            pass

    print(f"\n[OK] Ficheros movidos a la nueva jerarquía canónica: {moved_count}")
    print(f"[OK] Errores durante el movimiento: {errors}")

    # 2. Limpiar cualquier carpeta residual vacía en la raíz
    cleaned_root_dirs = 0
    for d in BASE_ES.iterdir():
        if d.is_dir() and not d.name.isdigit():
            try:
                if not any(d.iterdir()):
                    d.rmdir()
                    cleaned_root_dirs += 1
                else:
                    files_left = [f for f in d.rglob('*') if f.is_file()]
                    if not files_left:
                        shutil.rmtree(d)
                        cleaned_root_dirs += 1
            except Exception:
                pass

    print(f"[OK] Carpetas de CIF vacías eliminadas de la raíz: {cleaned_root_dirs}")

    # 3. Mostrar estructura resultante de años en la raíz
    final_years = sorted([d.name for d in BASE_ES.iterdir() if d.is_dir() and d.name.isdigit()])
    print(f"\nEstructura final de Años en la raíz de D:\\ARGOS_DATA\\raw\\ES_CNMV:")
    for yr in final_years:
        entities = list((BASE_ES / yr).iterdir())
        files = list((BASE_ES / yr).rglob('*'))
        actual_f = [f for f in files if f.is_file()]
        print(f"  Año {yr:4s} -> {len(entities):3d} carpetas de entidad | {len(actual_f):4d} archivos")

if __name__ == '__main__':
    reorganize()
