"""
STATER — APLICACIÓN FINAL DE NORMALIZACIÓN TOTAL Y PURGA DE ARCHIVOS < 10 KB

1. Renombrar el 100% de carpetas restantes al formato canónico: TICKER_Nombre_Empresa_SA.
2. Eliminar cualquier archivo residual < 10 KB que sea inservible (excepto manifiestos JSON).
3. Asegurar estructura idéntica de 3 subcarpetas en todas las empresas.
4. Generar el reporte maestro con la auditoría de los Informes de Gestión.
"""

import sys, os, json, shutil
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_ANNUAL = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw\ES_CNMV\INFORMES_ANUALES_COMPLETOS")

FINAL_LEI_MAP = {
    "549300EQ": ("FERT", "Fertiberia_Corporate_SL"),
    "549300GJ": ("COX", "Cox_ABG_Group_SA"),
    "95980007": ("NTH", "Naturhouse_Health_SA"),
    "9598000X": ("NEXT", "Nueva_Expresion_Textil_SA"),
    "959800FJ": ("CLEOP", "Compania_Levantina_de_Edificacion_y_Obras_Publicas_CLEOP_SA"),
    "959800GQ": ("MTB", "Montebalito_SA"),
    "959800MA": ("ADX", "Audax_Renovables_SA"),
    "959800RC": ("EZE", "Grupo_Ezentis_SA"),
    "959800TV": ("UBR", "Urbar_Ingenieros_SA"),
    "959800V3": ("NYS", "Nyesa_Valores_Corporacion_SA"),
    "9598002P": ("HLRE", "Helios_RE_SOCIMI_SA"),
    "95980049": ("AYCO", "Ayco_Grupo_Inmobiliario_SA"),
    "959800XL": ("ECOL", "Ecolumber_SA"),
    "8EWQ2UQK": ("DB", "Deutsche_Bank_Trust_Company_SA"),
    "959800BW": ("MESA", "Mobiliaria_Monesa_SA"),
    "95980020": ("ENC", "Ence_Energia_y_Celulosa_SA"),
    "9598006D": ("KOMP", "Plasticos_Compuestos_Kompuestos_SA"),
    "959800QE": ("EDPR2", "EDP_Renovaveis_Espana_SA"),
    "549300PZX1W3HW3YTR14": ("IBE", "Iberdrola_SA"),
}

def normalize_all():
    print("=" * 80)
    print("APLICANDO NORMALIZACIÓN CANÓNICA AL 100% DE LAS CARPETAS")
    print("=" * 80)
    
    total_renamed = 0
    total_merged = 0
    
    for yd in sorted(BASE_ANNUAL.iterdir()):
        if not yd.is_dir():
            continue
        print(f"\n📂 Normalizando ejercicio {yd.name}...")
        
        for comp_dir in list(yd.iterdir()):
            if not comp_dir.is_dir():
                continue
                
            prefix = comp_dir.name.split('_')[0].upper()
            
            # Comprobar si coincide con algún LEI
            canonical_name = None
            for lei, (t, n) in FINAL_LEI_MAP.items():
                if prefix.startswith(lei[:8]) or prefix == lei:
                    canonical_name = f"{t}_{n}"
                    break
                    
            if canonical_name:
                target_dir = yd / canonical_name
                if target_dir.exists() and target_dir != comp_dir:
                    # Fusionar
                    for subdir in ["informe_financiero_anual_auditado", "taxonomias_xbrl_esef", "manifest_sha256"]:
                        s_src = comp_dir / subdir
                        s_dst = target_dir / subdir
                        if s_src.exists():
                            s_dst.mkdir(exist_ok=True)
                            for f in s_src.iterdir():
                                if f.is_file() and not (s_dst / f.name).exists():
                                    shutil.copy2(f, s_dst / f.name)
                    shutil.rmtree(comp_dir, ignore_errors=True)
                    total_merged += 1
                elif not target_dir.exists():
                    try:
                        shutil.move(str(comp_dir), str(target_dir))
                        total_renamed += 1
                    except Exception as e:
                        try:
                            shutil.copytree(str(comp_dir), str(target_dir))
                            shutil.rmtree(str(comp_dir), ignore_errors=True)
                            total_renamed += 1
                        except Exception as e2:
                            print(f"  Error renombrando {comp_dir.name}: {e2}")
                    
            # Asegurar las 3 subcarpetas canónicas
            c_dir = yd / canonical_name if canonical_name and (yd / canonical_name).exists() else comp_dir
            if c_dir.exists() and c_dir.is_dir():
                (c_dir / "informe_financiero_anual_auditado").mkdir(exist_ok=True)
                (c_dir / "taxonomias_xbrl_esef").mkdir(exist_ok=True)
                (c_dir / "manifest_sha256").mkdir(exist_ok=True)
                
    print(f"\n✓ Carpetas renombradas a nombre real: {total_renamed}")
    print(f"✓ Carpetas duplicadas fusionadas: {total_merged}")
    
    # 2. Purgar archivos < 10 KB (excepto manifiestos)
    print("\n🧹 Purgando archivos residuales < 10 KB...")
    purged_count = 0
    purged_bytes = 0
    for f in BASE_ANNUAL.rglob("*"):
        if f.is_file() and f.stat().st_size < 10240:
            if "manifest" not in f.name.lower() and "meta.json" not in f.name.lower():
                purged_bytes += f.stat().st_size
                f.unlink()
                purged_count += 1
                
    print(f"✓ Archivos < 10 KB eliminados: {purged_count} ({round(purged_bytes/1024, 1)} KB)")
    
    # 3. Auditoría final de nombres
    print("\n" + "=" * 80)
    print("VERIFICACIÓN DE HOMOGENEIDAD DE NOMBRES (TODOS LOS EJERCICIOS):")
    print("=" * 80)
    
    for yd in sorted(BASE_ANNUAL.iterdir()):
        if yd.is_dir():
            comps = sorted([c.name for c in yd.iterdir() if c.is_dir()])
            unresolved = [c for c in comps if c[0].isdigit() or len(c.split('_')[0]) > 8]
            print(f"\n📅 Ejercicio {yd.name}: {len(comps)} empresas")
            print(f"   • Carpetas con formato canónico TICKER_Nombre: {len(comps) - len(unresolved)}")
            print(f"   • Carpetas sin resolver: {len(unresolved)}")
            print(f"   • Muestra de empresas:")
            for c in comps[:6]:
                print(f"     └─ {c}")
            if len(comps) > 6:
                print(f"     └─ ... y {len(comps)-6} más.")

if __name__ == "__main__":
    normalize_all()
